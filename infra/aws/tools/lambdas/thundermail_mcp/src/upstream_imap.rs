// Extracted from mail-mcp/src/imap.rs at da362f41fef8c0969b14b63e6bb5194b84e84549.
// MIT; see LICENSE.upstream and extraction.json. No write operations included.
use crate::budget::Budget;
use async_imap::{Session, types::Fetch};
use futures::TryStreamExt;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::TcpStream;
use tokio::time::timeout;
#[derive(Debug)]
pub enum AppError {
    Timeout(String),
    Internal(String),
    NotFound(String),
}
impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
pub type AppResult<T> = std::result::Result<T, AppError>;
pub struct ServerConfig {
    pub socket_timeout_ms: u64,
}
pub type ImapSession = Session<Budget<ImapStream>>;
/// Wrapper enum that supports both TLS and plaintext IMAP streams.
#[derive(Debug)]
#[allow(clippy::large_enum_variant)] // TLS is the dominant variant; boxing it would add indirection on the hot path
pub enum ImapStream {
    Tls(tokio_rustls::client::TlsStream<TcpStream>),
    #[cfg(test)]
    Plain(TcpStream),
}

impl AsyncRead for ImapStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        match self.get_mut() {
            ImapStream::Tls(s) => Pin::new(s).poll_read(cx, buf),
            #[cfg(test)]
            ImapStream::Plain(s) => Pin::new(s).poll_read(cx, buf),
        }
    }
}

impl AsyncWrite for ImapStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        match self.get_mut() {
            ImapStream::Tls(s) => Pin::new(s).poll_write(cx, buf),
            #[cfg(test)]
            ImapStream::Plain(s) => Pin::new(s).poll_write(cx, buf),
        }
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        match self.get_mut() {
            ImapStream::Tls(s) => Pin::new(s).poll_flush(cx),
            #[cfg(test)]
            ImapStream::Plain(s) => Pin::new(s).poll_flush(cx),
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        match self.get_mut() {
            ImapStream::Tls(s) => Pin::new(s).poll_shutdown(cx),
            #[cfg(test)]
            ImapStream::Plain(s) => Pin::new(s).poll_shutdown(cx),
        }
    }
}

impl Unpin for ImapStream {}

fn socket_timeout(server: &ServerConfig) -> Duration {
    Duration::from_millis(server.socket_timeout_ms)
}

/// List all visible mailboxes/folders
///
/// Returns up to the server's full mailbox list. Caller should truncate if
/// necessary (e.g., to 200 items).
pub async fn list_all_mailboxes(
    server: &ServerConfig,
    session: &mut ImapSession,
) -> AppResult<Vec<async_imap::types::Name>> {
    let stream = timeout(socket_timeout(server), session.list(None, Some("*")))
        .await
        .map_err(|_| AppError::Timeout("LIST timed out".to_owned()))
        .and_then(|r| r.map_err(|e| AppError::Internal(format!("LIST failed: {e}"))))?;

    timeout(socket_timeout(server), stream.try_collect::<Vec<_>>())
        .await
        .map_err(|_| AppError::Timeout("LIST stream timed out".to_owned()))
        .and_then(|r| r.map_err(|e| AppError::Internal(format!("LIST stream failed: {e}"))))
}

/// Select mailbox in read-only mode
///
/// Uses `EXAMINE` command to fetch mailbox state without marking messages
/// as read. Returns the `UIDVALIDITY` for message ID stability.
pub async fn select_mailbox_readonly(
    server: &ServerConfig,
    session: &mut ImapSession,
    mailbox: &str,
) -> AppResult<u32> {
    let selected = timeout(socket_timeout(server), session.examine(mailbox))
        .await
        .map_err(|_| AppError::Timeout(format!("EXAMINE timed out for mailbox '{mailbox}'")))
        .and_then(|r| {
            r.map_err(|e| AppError::NotFound(format!("cannot examine mailbox '{mailbox}': {e}")))
        })?;
    selected
        .uid_validity
        .ok_or_else(|| AppError::Internal("mailbox missing UIDVALIDITY".to_owned()))
}

/// Fetch a single message with custom query
///
/// Runs a `UID FETCH` for a specific UID and returns the first result.
/// Used internally by other fetch functions.
///
/// # Errors
///
/// - `NotFound` if UID does not exist in mailbox
/// - `Timeout` or `Internal` for network/protocol errors
pub async fn fetch_one(
    server: &ServerConfig,
    session: &mut ImapSession,
    uid: u32,
    query: &str,
) -> AppResult<Fetch> {
    let stream = timeout(
        socket_timeout(server),
        session.uid_fetch(uid.to_string(), query),
    )
    .await
    .map_err(|_| AppError::Timeout("UID FETCH timed out".to_owned()))
    .and_then(|r| r.map_err(|e| AppError::Internal(format!("uid fetch failed: {e}"))))?;
    let fetches: Vec<Fetch> = timeout(socket_timeout(server), stream.try_collect())
        .await
        .map_err(|_| AppError::Timeout("UID FETCH stream timed out".to_owned()))
        .and_then(|r| r.map_err(|e| AppError::Internal(format!("uid fetch stream failed: {e}"))))?;

    if let Some(fetch) = fetches.into_iter().next() {
        return Ok(fetch);
    }

    let existence_query = format!("UID {uid}");
    match uid_search(server, session, existence_query.as_str()).await {
        Ok(matches) if matches.contains(&uid) => Err(AppError::Internal(format!(
            "UID FETCH returned no data for existing uid {uid}; possible server FETCH incompatibility (query: {query})"
        ))),
        Ok(_) => Err(AppError::NotFound(format!("message uid {uid} not found"))),
        Err(error) => Err(AppError::Internal(format!(
            "UID FETCH returned no data for uid {uid}; failed to verify existence: {error}"
        ))),
    }
}

/// Search for messages matching query
///
/// Runs `UID SEARCH` and returns matching UIDs in descending order (newest
/// first). Callers typically limit the result set via pagination.
pub async fn uid_search(
    server: &ServerConfig,
    session: &mut ImapSession,
    query: &str,
) -> AppResult<Vec<u32>> {
    let set = timeout(socket_timeout(server), session.uid_search(query))
        .await
        .map_err(|_| AppError::Timeout("UID SEARCH timed out".to_owned()))
        .and_then(|r| r.map_err(|e| AppError::Internal(format!("uid search failed: {e}"))))?;
    let mut uids: Vec<u32> = set.into_iter().collect();
    uids.sort_unstable_by(|a, b| b.cmp(a));
    Ok(uids)
}
