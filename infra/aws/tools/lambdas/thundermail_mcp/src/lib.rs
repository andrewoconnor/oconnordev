pub mod aws_secret;
use lambda_runtime::LambdaEvent;
use serde_json::{Value, json};

pub trait SecretStore {
    fn get(&self) -> impl std::future::Future<Output = Result<String>> + Send;
}
type Result<T> = std::result::Result<T, String>;
#[derive(serde::Deserialize, Debug)]
#[serde(deny_unknown_fields)]
struct List {
    #[serde(default = "default_limit")]
    limit: usize,
    cursor: Option<String>,
}
#[derive(serde::Deserialize, Debug)]
#[serde(deny_unknown_fields)]
struct Search {
    mailbox: String,
    #[serde(default = "all")]
    query: String,
    #[serde(default = "default_limit")]
    limit: usize,
    cursor: Option<String>,
}
#[derive(serde::Deserialize, Debug)]
#[serde(deny_unknown_fields)]
struct Get {
    mailbox: String,
    uid: u32,
    uid_validity: u32,
    #[serde(default = "default_bytes")]
    max_bytes: usize,
}
#[derive(serde::Deserialize, serde::Serialize, Debug)]
#[serde(deny_unknown_fields)]
struct Cursor {
    mailbox: String,
    query: String,
    uid_validity: u32,
    before_uid: u32,
}
#[derive(Debug)]
enum Request {
    List(List),
    Search(Search, Option<Cursor>),
    Get(Get),
}
fn default_limit() -> usize {
    20
}
fn default_bytes() -> usize {
    16384
}
fn all() -> String {
    "all".into()
}
fn mailbox(s: &str) -> bool {
    !s.is_empty() && s.len() <= 256 && !s.chars().any(char::is_control)
}
fn parse(tool: &str, v: Value) -> Result<Request> {
    let bad = || "Invalid arguments".to_string();
    match tool {
        "thundermail___imap_list_mailboxes" => {
            let x: List = serde_json::from_value(v).map_err(|_| bad())?;
            if !(1..=100).contains(&x.limit)
                || x.cursor.as_ref().is_some_and(|s| {
                    s.len() > 1024
                        || serde_json::from_str::<String>(s).map_or(true, |s| !mailbox(&s))
                })
            {
                return Err(bad());
            }
            Ok(Request::List(x))
        }
        "thundermail___imap_search_messages" => {
            let x: Search = serde_json::from_value(v).map_err(|_| bad())?;
            if !mailbox(&x.mailbox)
                || !["all", "unseen"].contains(&x.query.as_str())
                || !(1..=100).contains(&x.limit)
            {
                return Err(bad());
            }
            let c = if let Some(s) = &x.cursor {
                if s.len() > 1024 {
                    return Err(bad());
                }
                let c: Cursor = serde_json::from_str(s).map_err(|_| bad())?;
                if c.mailbox != x.mailbox
                    || c.query != x.query
                    || c.uid_validity == 0
                    || c.before_uid == 0
                {
                    return Err(bad());
                }
                Some(c)
            } else {
                None
            };
            Ok(Request::Search(x, c))
        }
        "thundermail___imap_get_message" => {
            let x: Get = serde_json::from_value(v).map_err(|_| bad())?;
            if !mailbox(&x.mailbox)
                || x.uid == 0
                || x.uid_validity == 0
                || !(1..=65536).contains(&x.max_bytes)
            {
                return Err(bad());
            }
            Ok(Request::Get(x))
        }
        _ => Err("Unknown tool".into()),
    }
}
fn response(result: Result<Value>) -> Value {
    let value = match result {
        Ok(v) => {
            json!({"isError":false,"content":[{"type":"text","text":v.to_string()}],"structuredContent":v})
        }
        Err(e) => json!({"isError":true,"content":[{"type":"text","text":e}]}),
    };
    if serde_json::to_vec(&value).map_or(true, |b| b.len() > 131072) {
        json!({"isError":true,"content":[{"type":"text","text":"Response exceeds 128 KiB budget; reduce limit or max_bytes"}]})
    } else {
        value
    }
}
pub async fn handle<S: SecretStore>(event: LambdaEvent<Value>, store: &S) -> Value {
    invoke(event, store, Endpoint::Production).await
}
#[derive(Clone, Copy)]
enum Endpoint {
    Production,
    #[cfg(test)]
    Loopback(std::net::SocketAddr),
}
async fn invoke<S: SecretStore>(event: LambdaEvent<Value>, store: &S, endpoint: Endpoint) -> Value {
    let tool = event
        .context
        .client_context
        .as_ref()
        .and_then(|x| x.custom.get("bedrockAgentCoreToolName"))
        .map(String::as_str)
        .unwrap_or("");
    let request = match parse(tool, event.payload) {
        Ok(x) => x,
        Err(e) => return response(Err(e)),
    };
    response(
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            let password = store
                .get()
                .await
                .map_err(|_| "SecretStoreGet unavailable".to_string())?;
            run(request, password, endpoint).await
        })
        .await
        .unwrap_or_else(|_| Err("Mail deadline exceeded".into())),
    )
}
mod budget;
mod connect;
mod upstream_imap;
async fn run(request: Request, password: String, endpoint: Endpoint) -> Result<Value> {
    use upstream_imap as imap;
    let mut session = connect::connect(endpoint, password).await?;
    let config = imap::ServerConfig {
        socket_timeout_ms: 3000,
    };
    let safe_error = |e: imap::AppError| {
        match e {
            imap::AppError::Timeout(s) => {
                drop(s);
                "IMAP operation timed out"
            }
            imap::AppError::NotFound(s) => {
                drop(s);
                "Mailbox or message unavailable"
            }
            imap::AppError::Internal(s) => {
                drop(s);
                "IMAP operation failed"
            }
        }
        .to_string()
    };
    match request {
        Request::List(x) => {
            let names = imap::list_all_mailboxes(&config, &mut session)
                .await
                .map_err(safe_error)?;
            let mut names: Vec<String> = names.into_iter().map(|n| n.name().to_owned()).collect();
            names.sort();
            names.dedup();
            let after = x
                .cursor
                .as_ref()
                .map(|s| serde_json::from_str::<String>(s).expect("validated cursor"));
            names.retain(|s| after.as_ref().is_none_or(|a| s > a));
            let more = names.len() > x.limit;
            names.truncate(x.limit);
            let cursor = if more {
                names
                    .last()
                    .map(|s| serde_json::to_string(s).expect("string"))
            } else {
                None
            };
            Ok(json!({"mailboxes":names,"next_cursor":cursor}))
        }
        Request::Search(x, c) => {
            let validity = imap::select_mailbox_readonly(&config, &mut session, &x.mailbox)
                .await
                .map_err(safe_error)?;
            if c.as_ref().is_some_and(|c| c.uid_validity != validity) {
                return Err("Stale cursor UIDVALIDITY".into());
            }
            let before = c.as_ref().map_or(u32::MAX, |c| c.before_uid);
            let query = format!(
                "UID 1:{} {}",
                before,
                if x.query == "unseen" { "UNSEEN" } else { "ALL" }
            );
            let mut uids = imap::uid_search(&config, &mut session, &query)
                .await
                .map_err(safe_error)?;
            uids.retain(|u| *u > 0 && *u <= before);
            let more = uids.len() > x.limit;
            uids.truncate(x.limit);
            let cursor = if more {
                uids.last().filter(|u| **u > 1).map(|u| {
                    serde_json::to_string(&Cursor {
                        mailbox: x.mailbox.clone(),
                        query: x.query,
                        uid_validity: validity,
                        before_uid: u - 1,
                    })
                    .expect("cursor")
                })
            } else {
                None
            };
            let messages: Vec<Value> = uids
                .into_iter()
                .map(|uid| json!({"mailbox":x.mailbox,"uid_validity":validity,"uid":uid}))
                .collect();
            Ok(json!({"messages":messages,"next_cursor":cursor}))
        }
        Request::Get(x) => {
            let validity = imap::select_mailbox_readonly(&config, &mut session, &x.mailbox)
                .await
                .map_err(safe_error)?;
            if validity != x.uid_validity {
                return Err("Stale message UIDVALIDITY".into());
            }
            // Fail closed: never use upstream BODY[] fallback when PEEK is rejected.
            let query = format!("(UID BODY.PEEK[]<0.{}>)", x.max_bytes);
            let fetch = imap::fetch_one(&config, &mut session, x.uid, &query)
                .await
                .map_err(safe_error)?;
            if fetch.uid != Some(x.uid) {
                return Err("Mismatched message UID".into());
            }
            let body = fetch.body().ok_or("Message body unavailable")?;
            if body.len() > x.max_bytes {
                return Err("IMAP body exceeded requested limit".into());
            }
            Ok(
                json!({"mailbox":x.mailbox,"uid":x.uid,"uid_validity":validity,"raw_utf8":String::from_utf8_lossy(body),"returned_bytes":body.len(),"possibly_truncated":body.len()==x.max_bytes}),
            )
        }
    }
}
#[cfg(test)]
mod wire_tests;
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Counting(AtomicUsize);
    impl SecretStore for Counting {
        async fn get(&self) -> Result<String> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err("disabled".into())
        }
    }
    fn event(tool: &str, args: Value) -> LambdaEvent<Value> {
        let mut c = lambda_runtime::Context::default();
        c.client_context=Some(serde_json::from_value(json!({"custom":{"bedrockAgentCoreToolName":tool,"bedrockAgentCoreMessageVersion":"1.0"}})).unwrap());
        LambdaEvent::new(args, c)
    }
    #[tokio::test]
    async fn invalid_inputs_never_read_secret() {
        let store = Counting(AtomicUsize::new(0));
        for (tool, args) in [
            ("thundermail___delete_message", json!({})),
            ("other___imap_list_mailboxes", json!({})),
            ("thundermail___imap_list_mailboxes", json!({"account":"x"})),
            ("thundermail___imap_list_mailboxes", json!({"limit":0})),
            ("thundermail___imap_list_mailboxes", json!({"limit":101})),
            ("thundermail___imap_list_mailboxes", json!({"cursor":"x"})),
            (
                "thundermail___imap_search_messages",
                json!({"mailbox":"INBOX\r\nSTORE","query":"all"}),
            ),
            (
                "thundermail___imap_search_messages",
                json!({"mailbox":"INBOX","query":"ALL STORE"}),
            ),
            (
                "thundermail___imap_get_message",
                json!({"mailbox":"INBOX","uid":0,"uid_validity":7}),
            ),
            (
                "thundermail___imap_get_message",
                json!({"mailbox":"INBOX","uid":1,"uid_validity":7,"max_bytes":65537}),
            ),
            (
                "thundermail___imap_get_message",
                json!({"mailbox":"INBOX","uid":1,"uid_validity":7,"host":"evil"}),
            ),
            ("thundermail___imap_list_mailboxes", json!([])),
        ] {
            assert_eq!(handle(event(tool, args), &store).await["isError"], true);
        }
        assert_eq!(
            store.0.load(Ordering::SeqCst),
            0,
            "validation must precede SecretStoreGet"
        );
    }
}
