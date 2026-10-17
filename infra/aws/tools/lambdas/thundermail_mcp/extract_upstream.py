"""Reproducible minimal IMAP read closure from reviewed upstream pin; no network."""

import difflib
import hashlib
import json
import pathlib
import subprocess
import sys

up = pathlib.Path(sys.argv[1])
out = pathlib.Path(__file__).parent
pin = "da362f41fef8c0969b14b63e6bb5194b84e84549"
assert (
    subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=up, text=True).strip()
    == pin
)
source = (up / "src/imap.rs").read_text()
lines = source.splitlines(keepends=True)
spans = [(28, 76), (84, 86), (285, 322), (344, 385), (652, 668)]
header = (
    "// Extracted from mail-mcp/src/imap.rs at "
    + pin
    + ".\n"
    + """// MIT; see LICENSE.upstream and extraction.json. No write operations included.
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;
use async_imap::{Session,types::Fetch};
use futures::TryStreamExt;
use tokio::io::{AsyncRead,AsyncWrite,ReadBuf};
use tokio::net::TcpStream;
use tokio::time::timeout;
use crate::budget::Budget;
#[derive(Debug)]
pub enum AppError { Timeout(String), Internal(String), NotFound(String) }
impl std::fmt::Display for AppError {
 fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{write!(f,"{self:?}")}
}
pub type AppResult<T> = std::result::Result<T,AppError>;
pub struct ServerConfig {pub socket_timeout_ms:u64}
pub type ImapSession = Session<Budget<ImapStream>>;
"""
)
selected = "\n".join("".join(lines[a - 1 : b]) for a, b in spans)
text = header + selected
# Compile the plaintext stream out of production, not just disable its selector.
text = text.replace("    Plain(TcpStream),", "    #[cfg(test)]\n    Plain(TcpStream),")
for method in ["poll_read", "poll_write", "poll_flush", "poll_shutdown"]:
    text = text.replace(
        f"            ImapStream::Plain(s) => Pin::new(s).{method}",
        "            #[cfg(test)]\n"
        f"            ImapStream::Plain(s) => Pin::new(s).{method}",
    )
(out / "src/upstream_imap.rs").write_text(text)
if len(sys.argv) > 2:
    subprocess.run(
        [sys.argv[2], "--edition", "2024", str(out / "src/upstream_imap.rs")],
        check=True,
    )
    text = (out / "src/upstream_imap.rs").read_text()
(out / "upstream-read-closure.patch").write_text(
    "".join(
        difflib.unified_diff(
            selected.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile="selected-original-imap.rs",
            tofile="src/upstream_imap.rs",
            n=0,  # Retain no whitespace-only context in the attribution patch.
        )
    )
)
(out / "LICENSE.upstream").write_bytes((up / "LICENSE").read_bytes())
(out / "extraction.json").write_text(
    json.dumps(
        {
            "repository": "https://github.com/tecnologicachile/mail-mcp",
            "pin": pin,
            "source": "src/imap.rs",
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "line_spans_inclusive": spans,
            "selected_original_lines": sum(b - a + 1 for a, b in spans),
            "adaptations": (
                "Small support types replace full config/errors; ImapSession wraps "
                "upstream stream in Budget. TLS/password connection is separately "
                "adapted from original connect_authenticated; OAuth/config loaders/ID "
                "not retained. Original fetch_raw_message BODY[] fallback "
                "intentionally "
                "NOT extracted; caller uses only bounded BODY.PEEK[]."
            ),
            "excluded": (
                "SMTP, writes, Graph/EWS, OAuth, MIME/PDF, rmcp, HTTP, config loading, "
                "in-memory pagination"
            ),
        },
        indent=2,
    )
    + "\n"
)
print("Extracted", sum(b - a + 1 for a, b in spans), "upstream lines")
