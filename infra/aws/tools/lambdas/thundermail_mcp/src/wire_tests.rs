use super::*;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
fn event(tool: &str, args: Value) -> LambdaEvent<Value> {
    let mut c = lambda_runtime::Context::default();
    c.client_context=Some(serde_json::from_value(json!({"custom":{"bedrockAgentCoreToolName":format!("thundermail___{tool}"),"bedrockAgentCoreMessageVersion":"1.0"}})).unwrap());
    LambdaEvent::new(args, c)
}
async fn fixture(
    reject_peek: bool,
) -> (
    Endpoint,
    Arc<Mutex<Vec<String>>>,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let commands = Arc::new(Mutex::new(Vec::new()));
    let log = commands.clone();
    let task = tokio::spawn(async move {
        loop {
            let (socket, _) = listener.accept().await.unwrap();
            let log = log.clone();
            tokio::spawn(async move {
                let (r, mut w) = socket.into_split();
                w.write_all(b"* OK synthetic IMAP fixture\r\n")
                    .await
                    .unwrap();
                let mut r = BufReader::new(r);
                let mut line = String::new();
                loop {
                    line.clear();
                    if r.read_line(&mut line).await.unwrap_or(0) == 0 {
                        break;
                    }
                    let (tag, cmd) = line.trim_end().split_once(' ').unwrap();
                    log.lock().unwrap().push(if cmd.starts_with("LOGIN ") {
                        "LOGIN <synthetic-redacted>".into()
                    } else {
                        cmd.to_string()
                    });
                    let response = if cmd.starts_with("LOGIN ") {
                        format!("{tag} OK authenticated\r\n")
                    } else if cmd.starts_with("LIST ") {
                        format!(
                            "* LIST () \"/\" \"Archive\"\r\n* LIST () \"/\" \"INBOX\"\r\n{tag} OK list\r\n"
                        )
                    } else if cmd.starts_with("EXAMINE ") {
                        format!(
                            "* 2 EXISTS\r\n* OK [UIDVALIDITY 7] stable\r\n{tag} OK [READ-ONLY] examined\r\n"
                        )
                    } else if cmd.starts_with("UID SEARCH ") {
                        let ids = if cmd.contains("UID 1:1") { "1" } else { "1 2" };
                        format!("* SEARCH {ids}\r\n{tag} OK search\r\n")
                    } else if cmd.starts_with("UID FETCH ") {
                        if reject_peek {
                            format!("{tag} BAD PEEK rejected\r\n")
                        } else {
                            let raw = "Subject: Synthetic\r\n\r\nfixture only\r\n";
                            format!(
                                "* 2 FETCH (UID 2 FLAGS () BODY[]<0> {{{}}}\r\n{raw})\r\n{tag} OK fetch\r\n",
                                raw.len()
                            )
                        }
                    } else {
                        format!("{tag} BAD forbidden or unsupported\r\n")
                    };
                    if w.write_all(response.as_bytes()).await.is_err() {
                        break;
                    }
                }
            });
        }
    });
    (Endpoint::Loopback(addr), commands, task)
}
async fn call(endpoint: Endpoint, tool: &str, args: Value) -> Value {
    let (store, rx) = aws_secret::tests::synthetic();
    let output = invoke(event(tool, args), &store, endpoint).await;
    aws_secret::tests::assert_get(rx);
    output
}
#[tokio::test]
#[ignore = "run only through isolated native_imap_runtime_test.py"]
async fn native_runtime_worker() {
    let address: std::net::SocketAddr = std::env::var("THUNDERMAIL_TEST_ADDR")
        .expect("explicit synthetic endpoint")
        .parse()
        .unwrap();
    assert!(address.ip().is_loopback());
    lambda_runtime::run(lambda_runtime::service_fn(|event| async move {
        let (store, rx) = aws_secret::tests::synthetic();
        let output = invoke(event, &store, Endpoint::Loopback(address)).await;
        aws_secret::tests::assert_get(rx);
        Ok::<_, lambda_runtime::Error>(output)
    }))
    .await
    .unwrap();
}
#[tokio::test]
async fn response_budget_rejects_before_serialized_lambda_output_grows() {
    let value = response(Ok(json!({"raw_utf8":"x".repeat(131072)})));
    assert_eq!(
        value["isError"], true,
        "structured content and text duplicate must fit output bound"
    );
    assert!(serde_json::to_vec(&value).unwrap().len() <= 131072);
}
#[tokio::test]
async fn rejected_peek_fails_closed_without_body_fallback() {
    let (ep, log, task) = fixture(true).await;
    let value = call(
        ep,
        "imap_get_message",
        json!({"mailbox":"INBOX","uid":2,"uid_validity":7}),
    )
    .await;
    assert_eq!(value["isError"], true);
    let commands = log.lock().unwrap().clone();
    assert_eq!(
        commands
            .iter()
            .filter(|c| c.starts_with("UID FETCH "))
            .count(),
        1
    );
    assert!(
        !commands
            .iter()
            .any(|c| c.contains("BODY[]") || c.starts_with("SELECT ") || c.contains("STORE"))
    );
    task.abort();
}
#[tokio::test]
async fn stale_uidvalidity_fails_before_fetch_or_search() {
    let (ep, log, task) = fixture(false).await;
    let get = call(
        ep,
        "imap_get_message",
        json!({"mailbox":"INBOX","uid":2,"uid_validity":8}),
    )
    .await;
    assert_eq!(get["isError"], true);
    let cursor = serde_json::to_string(
        &json!({"mailbox":"INBOX","query":"all","uid_validity":8,"before_uid":1}),
    )
    .unwrap();
    let search = call(
        ep,
        "imap_search_messages",
        json!({"mailbox":"INBOX","cursor":cursor}),
    )
    .await;
    assert_eq!(search["isError"], true);
    assert!(
        !log.lock()
            .unwrap()
            .iter()
            .any(|s| s.starts_with("UID FETCH ") || s.starts_with("UID SEARCH "))
    );
    task.abort();
}
#[tokio::test]
async fn ignored_partial_fetch_limit_is_rejected() {
    let (ep, _log, task) = fixture(false).await;
    let value = call(
        ep,
        "imap_get_message",
        json!({"mailbox":"INBOX","uid":2,"uid_validity":7,"max_bytes":1}),
    )
    .await;
    assert_eq!(value["isError"], true);
    task.abort();
}
#[tokio::test]
async fn wire_transfer_limit_stops_oversized_greeting() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let ep = Endpoint::Loopback(listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        let (mut s, _) = listener.accept().await.unwrap();
        let _ = s
            .write_all(format!("* OK {}\r\n", "x".repeat(300000)).as_bytes())
            .await;
    });
    let result = call(ep, "imap_list_mailboxes", json!({})).await;
    assert_eq!(result["isError"], true);
    task.abort();
}
#[tokio::test]
async fn secret_lookup_is_runtime_only_and_entire_call_has_deadline() {
    struct Never;
    impl SecretStore for Never {
        async fn get(&self) -> Result<String> {
            std::future::pending().await
        }
    }
    let start = std::time::Instant::now();
    let result = invoke(
        event("imap_list_mailboxes", json!({})),
        &Never,
        Endpoint::Production,
    )
    .await;
    assert_eq!(result["content"][0]["text"], "Mail deadline exceeded");
    assert!(start.elapsed() < std::time::Duration::from_secs(7));
}
#[tokio::test]
async fn three_owned_reads_use_real_upstream_imap_and_cold_start_cursors() {
    let (ep, log, task) = fixture(false).await;
    let first = call(ep, "imap_list_mailboxes", json!({"limit":1})).await;
    assert_eq!(first["isError"], false, "{first}");
    assert_eq!(first["structuredContent"]["mailboxes"], json!(["Archive"]));
    let cursor = first["structuredContent"]["next_cursor"].clone();
    let second = call(
        ep,
        "imap_list_mailboxes",
        json!({"limit":1,"cursor":cursor}),
    )
    .await;
    assert_eq!(second["structuredContent"]["mailboxes"], json!(["INBOX"]));
    assert!(second["structuredContent"]["next_cursor"].is_null());
    let first = call(
        ep,
        "imap_search_messages",
        json!({"mailbox":"INBOX","limit":1}),
    )
    .await;
    assert_eq!(first["isError"], false, "{first}");
    assert_eq!(
        first["structuredContent"]["messages"],
        json!([{"uid":2,"uid_validity":7,"mailbox":"INBOX"}])
    );
    let second = call(
        ep,
        "imap_search_messages",
        json!({"mailbox":"INBOX","limit":1,"cursor":first["structuredContent"]["next_cursor"]}),
    )
    .await;
    assert_eq!(second["structuredContent"]["messages"][0]["uid"], 1);
    let get = call(
        ep,
        "imap_get_message",
        json!({"mailbox":"INBOX","uid":2,"uid_validity":7,"max_bytes":64}),
    )
    .await;
    assert_eq!(get["isError"], false, "{get}");
    assert!(
        get["structuredContent"]["raw_utf8"]
            .as_str()
            .unwrap()
            .contains("fixture only")
    );
    let commands = log.lock().unwrap().clone();
    assert!(commands.iter().any(|s| s.starts_with("EXAMINE ")));
    assert!(commands.iter().any(|s| s.contains("BODY.PEEK[]<0.64>")));
    assert!(
        !commands
            .iter()
            .any(|s| s.starts_with("SELECT ") || s.contains("STORE") || s.contains("\\Seen"))
    );
    task.abort();
}
