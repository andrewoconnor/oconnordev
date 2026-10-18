//! Read-only CalDAV event query on the owner's default Thundermail calendar.
use crate::{
    Endpoint, Result,
    budget::Budget,
    connect::{self, HOST, OWNER},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use http_body_util::{BodyExt, Full};
use hyper::{Method, Request, body::Bytes, client::conn::http1::SendRequest};
use hyper_util::rt::TokioIo;
use serde_json::{Map, Value, json};

pub const PATH: &str = "/dav/cal/oconnor%40thundermail.com/default/";
const PORT: u16 = 443;
const CALDAV: &str = "urn:ietf:params:xml:ns:caldav";
const SHORT_TEXT: usize = 512;
const LONG_TEXT: usize = 2048;

#[derive(Debug)]
pub struct Range {
    pub start: String,
    pub end: String,
    pub limit: usize,
}

pub fn utc(value: &str) -> Option<String> {
    let b = value.as_bytes();
    let digits = |r: std::ops::Range<usize>| b[r].iter().all(u8::is_ascii_digit);
    let number = |r: std::ops::Range<usize>| value[r].parse::<u32>().ok();
    if b.len() != 20
        || !(digits(0..4) && digits(5..7) && digits(8..10))
        || !(digits(11..13) && digits(14..16) && digits(17..19))
        || (b[4], b[7], b[10], b[13], b[16], b[19]) != (b'-', b'-', b'T', b':', b':', b'Z')
        || !(1..=12).contains(&number(5..7)?)
        || !(1..=31).contains(&number(8..10)?)
        || number(11..13)? > 23
        || number(14..16)? > 59
        || number(17..19)? > 59
    {
        return None;
    }
    Some(format!(
        "{}{}{}T{}{}{}Z",
        &value[0..4],
        &value[5..7],
        &value[8..10],
        &value[11..13],
        &value[14..16],
        &value[17..19]
    ))
}

fn query(range: &Range, expand: bool) -> String {
    let (start, end) = (&range.start, &range.end);
    let data = if expand {
        format!(r#"<C:calendar-data><C:expand start="{start}" end="{end}"/></C:calendar-data>"#)
    } else {
        concat!(
            r#"<C:calendar-data><C:comp name="VCALENDAR"><C:comp name="VEVENT">"#,
            r#"<C:prop name="UID"/><C:prop name="DTSTART"/><C:prop name="RECURRENCE-ID"/>"#,
            "</C:comp></C:comp></C:calendar-data>"
        )
        .into()
    };
    format!(
        r#"<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>{data}</D:prop>
  <C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">
    <C:time-range start="{start}" end="{end}"/>
  </C:comp-filter></C:comp-filter></C:filter>
</C:calendar-query>"#
    )
}

pub async fn events(endpoint: Endpoint, password: &str, range: &Range) -> Result<Value> {
    let io = TokioIo::new(Budget::new(connect::stream(endpoint, PORT).await?));
    let (mut sender, connection) = hyper::client::conn::http1::handshake(io)
        .await
        .map_err(|_| "CalDAV connection failed")?;
    tokio::spawn(connection);
    let originals = report(&mut sender, password, range, false).await?;
    let mut found = report(&mut sender, password, range, true).await?;
    for event in &mut found {
        preserve_date_type(event, &originals);
    }
    found.sort_by(|a, b| a["start"].as_str().cmp(&b["start"].as_str()));
    let truncated = found.len() > range.limit;
    found.truncate(range.limit);
    Ok(json!({"calendar":"default","events":found,"truncated":truncated}))
}

fn preserve_date_type(event: &mut Value, originals: &[Value]) {
    let Some(uid) = event["uid"].as_str() else {
        return;
    };
    let same_uid = |source: &&Value| source["uid"].as_str() == Some(uid);
    let recurrence = event["recurrence_id"].as_str();
    let source = originals
        .iter()
        .filter(same_uid)
        .find(|source| {
            let (Some(id), Some(expanded)) = (source["recurrence_id"].as_str(), recurrence) else {
                return false;
            };
            expanded == id || (id.len() == 8 && expanded.starts_with(id))
        })
        .or_else(|| {
            originals
                .iter()
                .filter(same_uid)
                .find(|source| source.get("recurrence_id").is_none())
        });
    if source.is_none_or(|source| source["all_day"] != true) {
        return;
    }
    let date = |key: &str| {
        event[key]
            .as_str()
            .and_then(|value| value.strip_suffix("T000000Z"))
            .filter(|date| date.len() == 8 && date.bytes().all(|b| b.is_ascii_digit()))
            .map(str::to_owned)
    };
    let (start, end) = (date("start"), date("end"));
    if start.is_none() || (event.get("end").is_some() && end.is_none()) {
        return;
    }
    for (key, value) in [("start", start), ("end", end)] {
        if let Some(value) = value {
            event[key] = Value::String(value);
        }
    }
    event["all_day"] = Value::Bool(true);
    if let Some(map) = event.as_object_mut() {
        map.remove("start_tzid");
        map.remove("end_tzid");
    }
}

async fn report(
    sender: &mut SendRequest<Full<Bytes>>,
    password: &str,
    range: &Range,
    expand: bool,
) -> Result<Vec<Value>> {
    sender
        .ready()
        .await
        .map_err(|_| "CalDAV connection failed")?;
    let request = Request::builder()
        .method(Method::from_bytes(b"REPORT").expect("method"))
        .uri(PATH)
        .header("host", HOST)
        .header("depth", "1")
        .header("content-type", "application/xml; charset=utf-8")
        .header(
            "authorization",
            format!("Basic {}", STANDARD.encode(format!("{OWNER}:{password}"))),
        )
        .body(Full::new(Bytes::from(query(range, expand))))
        .map_err(|_| "CalDAV request invalid")?;
    let response = sender
        .send_request(request)
        .await
        .map_err(|_| "CalDAV request failed")?;
    match response.status().as_u16() {
        207 => {}
        401 | 403 => return Err("CalDAV authentication failed".into()),
        status => return Err(format!("CalDAV request failed with HTTP {status}")),
    }
    let body = response
        .into_body()
        .collect()
        .await
        .map_err(|_| "CalDAV response exceeded the transfer budget or failed")?
        .to_bytes();
    let text = std::str::from_utf8(&body).map_err(|_| "CalDAV response is not UTF-8")?;
    parse_multistatus(text)
}

fn parse_multistatus(text: &str) -> Result<Vec<Value>> {
    let document =
        roxmltree::Document::parse(text).map_err(|_| "CalDAV response is not valid XML")?;
    Ok(document
        .descendants()
        .filter(|node| node.has_tag_name((CALDAV, "calendar-data")))
        .flat_map(|node| {
            let ics: String = node.children().filter_map(|c| c.text()).collect();
            parse_events(&ics)
        })
        .collect())
}

fn unfold(ics: &str) -> Vec<String> {
    let mut lines: Vec<String> = Vec::new();
    for raw in ics.split('\n') {
        let line = raw.strip_suffix('\r').unwrap_or(raw);
        match (line.strip_prefix([' ', '\t']), lines.last_mut()) {
            (Some(rest), Some(last)) => last.push_str(rest),
            _ => lines.push(line.to_owned()),
        }
    }
    lines
}

fn split_unquoted(text: &str, separator: char) -> Vec<&str> {
    let (mut parts, mut start, mut quoted) = (Vec::new(), 0, false);
    for (i, c) in text.char_indices() {
        if c == '"' {
            quoted = !quoted;
        } else if c == separator && !quoted {
            parts.push(&text[start..i]);
            start = i + 1;
        }
    }
    parts.push(&text[start..]);
    parts
}

struct Property<'a> {
    name: String,
    params: Vec<(String, &'a str)>,
    value: &'a str,
}

fn property(line: &str) -> Option<Property<'_>> {
    let mut quoted = false;
    let colon = line.char_indices().find_map(|(i, c)| {
        if c == '"' {
            quoted = !quoted;
        }
        (c == ':' && !quoted).then_some(i)
    })?;
    let mut head = split_unquoted(&line[..colon], ';').into_iter();
    let name = head.next()?.to_ascii_uppercase();
    let params = head
        .filter_map(|p| p.split_once('='))
        .map(|(k, v)| (k.to_ascii_uppercase(), v.trim_matches('"')))
        .collect();
    Some(Property {
        name,
        params,
        value: &line[colon + 1..],
    })
}

fn unescape(value: &str, limit: usize) -> String {
    let mut out = String::new();
    let mut chars = value.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('n' | 'N') => out.push('\n'),
            Some(other) => out.push(other),
            None => break,
        }
    }
    out.chars().take(limit).collect()
}

fn parse_events(ics: &str) -> Vec<Value> {
    let (mut events, mut current, mut nested) = (Vec::new(), None::<Map<String, Value>>, 0usize);
    for line in unfold(ics) {
        let upper = line.to_ascii_uppercase();
        let Some(event) = current.as_mut() else {
            if upper == "BEGIN:VEVENT" {
                current = Some(Map::new());
            }
            continue;
        };
        if upper.starts_with("BEGIN:") {
            nested += 1;
        } else if upper.starts_with("END:") && nested > 0 {
            nested -= 1;
        } else if upper == "END:VEVENT" {
            events.extend(current.take().map(Value::Object));
        } else if nested == 0
            && let Some(p) = property(&line)
        {
            add(event, &p);
        }
    }
    events
}

fn add(event: &mut Map<String, Value>, p: &Property<'_>) {
    let param = |key: &str| p.params.iter().find(|(k, _)| k == key).map(|(_, v)| *v);
    let text = |limit| Value::String(unescape(p.value, limit));
    match p.name.as_str() {
        "UID" | "SUMMARY" | "LOCATION" | "STATUS" => {
            event.insert(p.name.to_ascii_lowercase(), text(SHORT_TEXT));
        }
        "DESCRIPTION" => {
            event.insert("description".into(), text(LONG_TEXT));
        }
        "RRULE" | "RECURRENCE-ID" | "DURATION" => {
            event.insert(
                p.name.to_ascii_lowercase().replace('-', "_"),
                text(SHORT_TEXT),
            );
        }
        "DTSTART" | "DTEND" => {
            let key = if p.name == "DTSTART" { "start" } else { "end" };
            event.insert(key.into(), text(SHORT_TEXT));
            if key == "start" {
                let all_day = param("VALUE") == Some("DATE") || p.value.len() == 8;
                event.insert("all_day".into(), Value::Bool(all_day));
            }
            if let Some(tzid) = param("TZID") {
                event.insert(
                    format!("{key}_tzid"),
                    Value::String(unescape(tzid, SHORT_TEXT)),
                );
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utc_accepts_only_rfc3339_utc_seconds() {
        assert_eq!(
            utc("2026-10-17T09:05:00Z").as_deref(),
            Some("20261017T090500Z")
        );
        for bad in [
            "",
            "2026-10-17",
            "2026-10-17T09:05:00",
            "2026-10-17T09:05:00+00:00",
            "2026-13-17T09:05:00Z",
            "2026-10-00T09:05:00Z",
            "2026-10-17T24:00:00Z",
            "2026-10-17T09:60:00Z",
            "2026-10-17 09:05:00Z",
            "２026-10-17T09:05:00Z",
        ] {
            assert_eq!(utc(bad), None, "{bad}");
        }
    }

    #[test]
    fn events_unfold_unescape_and_skip_nested_components() {
        let ics = "BEGIN:VCALENDAR\r\nBEGIN:VTIMEZONE\r\nDTSTART:19700101T000000\r\nEND:VTIMEZONE\r\n\
BEGIN:VEVENT\r\nUID:a@example\r\nSUMMARY:Long\r\n  title\\, part\\n2\r\n\
DTSTART;TZID=\"America/New_York\":20261017T090000\r\nDTEND;TZID=America/New_York:20261017T100000\r\n\
LOCATION;ALTREP=\"https://x.example/a:b\":Room 1\r\nBEGIN:VALARM\r\nSUMMARY:Alarm\r\nEND:VALARM\r\n\
RRULE:FREQ=WEEKLY;BYDAY=SA\r\nX-OTHER:ignored\r\nEND:VEVENT\r\n\
BEGIN:VEVENT\r\nUID:b@example\r\nSUMMARY:Holiday\r\nDTSTART;VALUE=DATE:20261018\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        let events = parse_events(ics);
        assert_eq!(events.len(), 2);
        assert_eq!(
            events[0],
            json!({"uid":"a@example","summary":"Long title, part\n2","start":"20261017T090000",
                "all_day":false,"start_tzid":"America/New_York","end":"20261017T100000",
                "end_tzid":"America/New_York","location":"Room 1","rrule":"FREQ=WEEKLY;BYDAY=SA"})
        );
        assert_eq!(
            events[1],
            json!({"uid":"b@example","summary":"Holiday","start":"20261018","all_day":true})
        );
    }

    #[test]
    fn all_day_override_keeps_its_timed_recurrence_identity() {
        let originals = parse_events(
            "BEGIN:VEVENT\nUID:series\nDTSTART:20261001T090000Z\nRRULE:FREQ=DAILY\nEND:VEVENT\nBEGIN:VEVENT\nUID:series\nRECURRENCE-ID:20261102T090000Z\nDTSTART;VALUE=DATE:20261102\nDTEND;VALUE=DATE:20261104\nEND:VEVENT\n",
        );
        let mut event = json!({"uid":"series","recurrence_id":"20261102T090000Z","start":"20261102T000000Z","end":"20261104T000000Z","all_day":false});
        preserve_date_type(&mut event, &originals);
        assert_eq!(event["all_day"], true);
        assert_eq!(event["start"], "20261102");
        assert_eq!(event["end"], "20261104");
        assert_eq!(event["recurrence_id"], "20261102T090000Z");
    }

    #[test]
    fn timed_override_of_date_series_is_not_converted_to_all_day() {
        let originals = parse_events(
            "BEGIN:VEVENT\nUID:series\nDTSTART;VALUE=DATE:20261001\nRRULE:FREQ=DAILY\nEND:VEVENT\nBEGIN:VEVENT\nUID:series\nRECURRENCE-ID;VALUE=DATE:20261102\nDTSTART:20261102T000000Z\nDTEND:20261103T000000Z\nEND:VEVENT\n",
        );
        let mut event = json!({"uid":"series","recurrence_id":"20261102T000000Z","start":"20261102T000000Z","end":"20261103T000000Z","all_day":false});
        let before = event.clone();
        preserve_date_type(&mut event, &originals);
        assert_eq!(event, before);
    }

    #[test]
    fn unmatched_or_non_midnight_events_are_left_unchanged() {
        let originals =
            parse_events("BEGIN:VEVENT\nUID:known\nDTSTART;VALUE=DATE:20261102\nEND:VEVENT\n");
        for mut event in [
            json!({"uid":"unknown","start":"20261102T000000Z","all_day":false}),
            json!({"start":"20261102T000000Z","all_day":false}),
            json!({"uid":"known","start":"20261101T230000Z","end":"20261102T230000Z","all_day":false}),
            json!({"uid":"known","start":"20261102T000000Z","end":"20261102T230000Z","all_day":false}),
        ] {
            let before = event.clone();
            preserve_date_type(&mut event, &originals);
            assert_eq!(event, before);
        }
    }

    #[test]
    fn text_is_bounded() {
        let ics = format!(
            "BEGIN:VEVENT\nSUMMARY:{}\nDESCRIPTION:{}\nEND:VEVENT\n",
            "s".repeat(4000),
            "d".repeat(9000)
        );
        let events = parse_events(&ics);
        assert_eq!(events[0]["summary"].as_str().unwrap().len(), SHORT_TEXT);
        assert_eq!(events[0]["description"].as_str().unwrap().len(), LONG_TEXT);
    }

    #[test]
    fn multistatus_reads_escaped_and_cdata_calendar_data_with_any_prefix() {
        let xml = r#"<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
 <d:response><d:propstat><d:prop><cal:calendar-data>BEGIN:VEVENT&#13;
UID:one&#13;
DTSTART:20261017T130000Z&#13;
END:VEVENT&#13;
</cal:calendar-data></d:prop></d:propstat></d:response>
 <d:response><d:propstat><d:prop><cal:calendar-data><![CDATA[BEGIN:VEVENT
UID:two
DTSTART:20261017T120000Z
END:VEVENT
]]></cal:calendar-data></d:prop></d:propstat></d:response>
</d:multistatus>"#;
        let events = parse_multistatus(xml).unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["uid"], "one");
        assert_eq!(events[1]["uid"], "two");
        assert!(parse_multistatus("<!DOCTYPE x [<!ENTITY a 'b'>]><x>&a;</x>").is_err());
    }
}
