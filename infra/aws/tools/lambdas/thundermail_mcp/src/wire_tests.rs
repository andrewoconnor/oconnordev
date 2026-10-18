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
async fn caldav_fixture(
    status: &'static str,
    body: &'static str,
) -> (Endpoint, tokio::task::JoinHandle<String>) {
    caldav_fixture_body(status, move |_| body).await
}
async fn caldav_fixture_body(
    status: &'static str,
    body: impl Fn(&str) -> &'static str + Send + 'static,
) -> (Endpoint, tokio::task::JoinHandle<String>) {
    caldav_fixture_requests(status, body, if status.starts_with("207 ") { 2 } else { 1 }).await
}
async fn caldav_fixture_requests(
    status: &'static str,
    body: impl Fn(&str) -> &'static str + Send + 'static,
    requests: usize,
) -> (Endpoint, tokio::task::JoinHandle<String>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        let mut all_requests = String::new();
        let (socket, _) = listener.accept().await.unwrap();
        let mut reader = BufReader::new(socket);
        for _ in 0..requests {
            let mut head = String::new();
            let mut length = 0;
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).await.unwrap();
                if let Some(v) = line.to_ascii_lowercase().strip_prefix("content-length:") {
                    length = v.trim().parse().unwrap();
                }
                head.push_str(&line);
                if line == "\r\n" {
                    break;
                }
            }
            let mut request = vec![0; length];
            tokio::io::AsyncReadExt::read_exact(&mut reader, &mut request)
                .await
                .unwrap();
            let request = head + &String::from_utf8(request).unwrap();
            let body = body(&request);
            let response = format!(
                "HTTP/1.1 {status}\r\ncontent-type: application/xml\r\ncontent-length: {}\r\n\r\n{body}",
                body.len()
            );
            reader
                .get_mut()
                .write_all(response.as_bytes())
                .await
                .unwrap();
            all_requests.push_str(&request);
        }
        all_requests
    });
    (Endpoint::Loopback(addr), task)
}
#[tokio::test]
async fn caldav_preserves_all_day_dates_and_timed_midnight_events() {
    const RAW: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VCALENDAR
BEGIN:VEVENT
UID:all-day
DTSTART;VALUE=DATE:20261102
DTEND;VALUE=DATE:20261103
END:VEVENT
BEGIN:VEVENT
UID:midnight
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT
END:VCALENDAR]]></c:calendar-data></d:multistatus>"#;
    const EXPANDED: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VCALENDAR
BEGIN:VEVENT
UID:all-day
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT
BEGIN:VEVENT
UID:midnight
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT
END:VCALENDAR]]></c:calendar-data></d:multistatus>"#;
    let (ep, task) = caldav_fixture_body("207 Multi-Status", |request| {
        if request.contains("<C:expand ") {
            EXPANDED
        } else {
            RAW
        }
    })
    .await;
    let value = call(
        ep,
        "caldav_list_events",
        json!({"start":"2026-11-02T00:00:00Z","end":"2026-11-03T00:00:00Z"}),
    )
    .await;
    assert_eq!(value["isError"], false, "{value}");
    let events = value["structuredContent"]["events"].as_array().unwrap();
    let all_day = events.iter().find(|e| e["uid"] == "all-day").unwrap();
    assert_eq!(all_day["all_day"], true);
    assert_eq!(all_day["start"], "20261102");
    assert_eq!(all_day["end"], "20261103");
    let midnight = events.iter().find(|e| e["uid"] == "midnight").unwrap();
    assert_eq!(midnight["all_day"], false);
    assert_eq!(midnight["start"], "20261102T000000Z");
    task.await.unwrap();
}
#[tokio::test]
async fn caldav_expands_recurring_events_without_losing_date_types() {
    const RAW: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VCALENDAR
BEGIN:VEVENT
UID:annual-day
DTSTART;VALUE=DATE:20251102
DTEND;VALUE=DATE:20251103
RRULE:FREQ=YEARLY
END:VEVENT
BEGIN:VEVENT
UID:annual-midnight
DTSTART:20251102T000000Z
DTEND:20251103T000000Z
RRULE:FREQ=YEARLY
END:VEVENT
END:VCALENDAR]]></c:calendar-data></d:multistatus>"#;
    const EXPANDED: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VCALENDAR
BEGIN:VEVENT
UID:annual-day
RECURRENCE-ID:20261102T000000Z
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT
BEGIN:VEVENT
UID:annual-midnight
RECURRENCE-ID:20261102T000000Z
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT
END:VCALENDAR]]></c:calendar-data></d:multistatus>"#;
    let (ep, task) = caldav_fixture_requests(
        "207 Multi-Status",
        |request| {
            if request.contains("<C:expand ") {
                EXPANDED
            } else {
                RAW
            }
        },
        2,
    )
    .await;
    let value = call(
        ep,
        "caldav_list_events",
        json!({"start":"2026-11-02T00:00:00Z","end":"2026-11-03T00:00:00Z"}),
    )
    .await;
    assert_eq!(value["isError"], false, "{value}");
    let events = value["structuredContent"]["events"].as_array().unwrap();
    let day = events.iter().find(|e| e["uid"] == "annual-day").unwrap();
    assert_eq!(day["start"], "20261102");
    assert_eq!(day["end"], "20261103");
    assert_eq!(day["all_day"], true);
    let timed = events
        .iter()
        .find(|e| e["uid"] == "annual-midnight")
        .unwrap();
    assert_eq!(timed["start"], "20261102T000000Z");
    assert_eq!(timed["all_day"], false);
    assert_eq!(task.await.unwrap().matches("REPORT ").count(), 2);
}
#[tokio::test]
async fn caldav_unmatched_timezone_override_is_returned_as_the_server_sent_it() {
    const RAW: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VCALENDAR
BEGIN:VEVENT
UID:zoned-series
DTSTART;TZID=America/New_York:20261001T090000
RRULE:FREQ=DAILY
END:VEVENT
BEGIN:VEVENT
UID:zoned-series
RECURRENCE-ID;TZID=America/New_York:20261102T090000
DTSTART;VALUE=DATE:20261102
DTEND;VALUE=DATE:20261103
END:VEVENT
END:VCALENDAR]]></c:calendar-data></d:multistatus>"#;
    const EXPANDED: &str = r#"<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:calendar-data><![CDATA[BEGIN:VEVENT
UID:zoned-series
RECURRENCE-ID:20261102T140000Z
DTSTART:20261102T000000Z
DTEND:20261103T000000Z
END:VEVENT]]></c:calendar-data></d:multistatus>"#;
    let (ep, task) = caldav_fixture_requests(
        "207 Multi-Status",
        |request| {
            if request.contains("<C:expand ") {
                EXPANDED
            } else {
                RAW
            }
        },
        2,
    )
    .await;
    let value = call(
        ep,
        "caldav_list_events",
        json!({"start":"2026-11-02T00:00:00Z","end":"2026-11-03T00:00:00Z"}),
    )
    .await;
    assert_eq!(value["isError"], false, "{value}");
    let event = &value["structuredContent"]["events"][0];
    assert_eq!(event["start"], "20261102T000000Z");
    assert_eq!(event["all_day"], false);
    task.await.unwrap();
}
const MULTISTATUS: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><response>
<href>/dav/cal/oconnor%40thundermail.com/default/b.ics</href><propstat><prop><C:calendar-data>BEGIN:VCALENDAR
BEGIN:VEVENT
UID:late
SUMMARY:Second
DTSTART:20261017T150000Z
END:VEVENT
BEGIN:VEVENT
UID:early
SUMMARY:First
DTSTART:20261017T090000Z
END:VEVENT
END:VCALENDAR
</C:calendar-data></prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"#;
#[tokio::test]
async fn caldav_report_queries_default_calendar_with_basic_auth() {
    let (ep, task) = caldav_fixture("207 Multi-Status", MULTISTATUS).await;
    let value = call(
        ep,
        "caldav_list_events",
        json!({"start":"2026-10-17T00:00:00Z","end":"2026-10-18T00:00:00Z","limit":1}),
    )
    .await;
    assert_eq!(value["isError"], false, "{value}");
    let result = &value["structuredContent"];
    assert_eq!(result["truncated"], true);
    assert_eq!(result["events"].as_array().unwrap().len(), 1);
    assert_eq!(result["events"][0]["uid"], "early");
    let request = task.await.unwrap();
    assert!(request.starts_with("REPORT /dav/cal/oconnor%40thundermail.com/default/ HTTP/1.1\r\n"));
    let lower = request.to_ascii_lowercase();
    assert!(lower.contains("\r\ndepth: 1\r\n"));
    assert!(lower.contains("\r\nhost: mail.thundermail.com\r\n"));
    let token = base64::Engine::encode(
        &base64::engine::general_purpose::STANDARD,
        "oconnor@thundermail.com:synthetic-only",
    );
    assert!(request.contains(&format!("authorization: Basic {token}\r\n")));
    assert!(request.contains(r#"<C:time-range start="20261017T000000Z" end="20261018T000000Z"/>"#));
    assert!(request.contains(r#"<C:expand start="20261017T000000Z" end="20261018T000000Z"/>"#));
    assert!(
        request.contains(
            r#"<C:prop name="UID"/><C:prop name="DTSTART"/><C:prop name="RECURRENCE-ID"/>"#
        )
    );
    assert_eq!(request.matches("REPORT ").count(), 2);
}
#[tokio::test]
async fn caldav_rejected_credentials_fail_without_detail() {
    let (ep, task) = caldav_fixture("401 Unauthorized", "denied").await;
    let value = call(
        ep,
        "caldav_list_events",
        json!({"start":"2026-10-17T00:00:00Z","end":"2026-10-18T00:00:00Z"}),
    )
    .await;
    assert_eq!(value["isError"], true);
    assert_eq!(value["content"][0]["text"], "CalDAV authentication failed");
    task.await.unwrap();
}
