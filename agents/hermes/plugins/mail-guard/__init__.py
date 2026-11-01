from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

LOGGER = logging.getLogger("mail-guard")
GLOBAL = "*"
RETENTION_SECONDS = 30 * 86400
SOURCE_PATTERN = re.compile(r"_(thundermail|google|outlook)_")

SOURCE_TOOLS = frozenset(
    {
        "thundermail-imap_list_mailboxes",
        "thundermail-imap_search_messages",
        "thundermail-imap_get_message",
        "thundermail-caldav_list_events",
        "google-getMessage",
        "google-listCalendars",
        "google-listEvents",
        "google-listLabels",
        "google-listMessages",
        "outlook-getMessage",
        "outlook-listCalendars",
        "outlook-listEvents",
        "outlook-listMailFolders",
        "outlook-listMessages",
    }
)
READ_TOOLS = SOURCE_TOOLS | frozenset(
    {
        "schwab-getAccount",
        "schwab-getAccountNumbers",
        "schwab-getMarketHours",
        "schwab-getPriceHistory",
        "schwab-getQuotes",
        "schwab-listAccounts",
        "schwab-searchInstruments",
        "plaid-listItems",
        "plaid-getAccounts",
        "plaid-getTransactions",
        "plaid-getItemStatus",
        "plaid-getRecurringTransactions",
        "plaid-getLiabilities",
        "plaid-getHoldings",
        "aws___get_regional_availability",
        "aws___get_tasks",
        "aws___list_regions",
        "aws___read_documentation",
        "aws___retrieve_skill",
        "aws___search_documentation",
        "get_file_contents",
        "list_branches",
        "get_commit",
        "pull_request_read",
        "get_job_logs",
        "repository_ruleset_read",
        "list_repository_collaborators",
        "list_label",
        "get_label",
        "discover",
        "provider",
        "query",
    }
)
WRITE_TOOLS = frozenset(
    {
        "create_branch",
        "push_files",
        "delete_file",
        "create_pull_request",
        "aws___run_script",
    }
)
BUILTIN_READ_TOOLS = frozenset(
    {"read_file", "search_files", "todo", "clarify", "session_search"}
)


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def is_source(tool_name: str) -> bool:
    name = normalize(tool_name or "")
    return name.startswith("mcp_") and bool(SOURCE_PATTERN.search(name + "_"))


def default_state_path() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / "mail-guard" / "tainted.json"


class Guard:
    def __init__(
        self,
        state_path: Path,
        server: str = "agentcore",
        mode: str = "approve",
        clock=time.time,
    ):
        self.state_path = state_path
        self.mode = "block" if mode == "block" else "approve"
        self.clock = clock
        self.lock = threading.Lock()
        self.allowed = BUILTIN_READ_TOOLS | {
            normalize(f"mcp_{server}_{tool}") for tool in READ_TOOLS
        }
        self.tainted = self._load()

    def _load(self) -> dict[str, float]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(key): float(value)
            for key, value in data.items()
            if isinstance(value, (int, float))
        }

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.state_path.parent)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(self.tainted, stream)
        os.replace(temporary, self.state_path)

    def taint(self, *ids: str | None) -> None:
        keys = [key for key in ids if key] or [GLOBAL]
        now = self.clock()
        with self.lock:
            self.tainted = {
                key: stamp
                for key, stamp in self.tainted.items()
                if now - stamp < RETENTION_SECONDS
            }
            self.tainted.update({key: now for key in keys})
            self._save()
        LOGGER.warning("mail-guard tainted %s", ",".join(keys))

    def is_tainted(self, *ids: str | None) -> bool:
        with self.lock:
            return GLOBAL in self.tainted or any(
                key in self.tainted for key in ids if key
            )

    def allows(self, tool_name: str) -> bool:
        return tool_name in BUILTIN_READ_TOOLS or normalize(tool_name) in self.allowed

    def post_tool_call(self, tool_name="", session_id="", task_id="", **kwargs):
        if is_source(tool_name):
            self.taint(session_id, task_id)

    def pre_tool_call(self, tool_name="", session_id="", task_id="", **kwargs):
        if not self.is_tainted(session_id, task_id) or self.allows(tool_name):
            return None
        message = (
            f"This session read untrusted email or calendar content. "
            f"Allow {tool_name} only if you asked for this exact action."
        )
        return {"action": self.mode, "message": message}

    def pre_llm_call(self, session_id="", parent_session_id="", task_id="", **kwargs):
        if (
            parent_session_id
            and self.is_tainted(parent_session_id)
            and not self.is_tainted(session_id, task_id)
        ):
            self.taint(session_id, task_id)
        return None

    def subagent_start(self, parent_session_id="", child_session_id="", **kwargs):
        if parent_session_id and self.is_tainted(parent_session_id):
            self.taint(child_session_id)

    def subagent_stop(self, parent_session_id="", tool_call_history=(), **kwargs):
        if any(
            isinstance(call, dict) and is_source(str(call.get("tool_name", "")))
            for call in tool_call_history or ()
        ):
            self.taint(parent_session_id)


def register(ctx):
    guard = Guard(
        default_state_path(),
        server=os.environ.get("HERMES_MAIL_GUARD_SERVER", "agentcore"),
        mode=os.environ.get("HERMES_MAIL_GUARD_MODE", "approve"),
    )
    for hook in (
        "post_tool_call",
        "pre_tool_call",
        "pre_llm_call",
        "subagent_start",
        "subagent_stop",
    ):
        ctx.register_hook(hook, getattr(guard, hook))
