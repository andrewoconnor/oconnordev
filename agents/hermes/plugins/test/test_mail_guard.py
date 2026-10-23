import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "mail_guard", ROOT / "agents/hermes/plugins/mail-guard/__init__.py"
)
mail_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mail_guard)

MAIL = "mcp_agentcore_thundermail_imap_get_message"


def manifest_tools():
    names = set()
    for path in (ROOT / "agents/hermes/adapter").glob("*-mcp-tools.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        prefix = document.get("client_tool_prefix", "")
        names.update(prefix + tool for tool in document["tools"])
    return names


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "mail-guard" / "tainted.json"
        self.guard = mail_guard.Guard(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_untainted_session_is_not_gated(self):
        self.assertIsNone(self.guard.pre_tool_call("terminal", session_id="s"))

    def test_mail_read_requires_approval_for_actions_in_that_session_only(self):
        self.guard.post_tool_call(MAIL, session_id="s")
        for tool in [
            "terminal",
            "write_file",
            "execute_code",
            "web_extract",
            "memory",
            "cronjob",
            "delegate_task",
            "mcp_agentcore_push_files",
            "mcp_agentcore_aws___run_script",
            "mcp_other_server_anything",
        ]:
            decision = self.guard.pre_tool_call(tool, session_id="s")
            self.assertEqual(decision["action"], "approve", tool)
            self.assertIn(tool, decision["message"])
        self.assertIsNone(self.guard.pre_tool_call("terminal", session_id="other"))

    def test_reads_stay_allowed_after_taint(self):
        self.guard.post_tool_call(MAIL, session_id="s")
        for tool in [
            "read_file",
            "todo",
            "mcp_agentcore_google_getMessage",
            "mcp_agentcore_schwab_getQuotes",
            "mcp_agentcore_aws___read_documentation",
            "mcp_agentcore_get_file_contents",
        ]:
            self.assertIsNone(self.guard.pre_tool_call(tool, session_id="s"), tool)

    def test_every_mail_and_calendar_target_taints_with_any_server_name(self):
        for tool in [
            "mcp_agentcore_google_listEvents",
            "mcp_agentcore_outlook_listMessages",
            "mcp_renamed_thundermail_caldav_list_events",
        ]:
            guard = mail_guard.Guard(self.path.with_name(tool + ".json"))
            guard.post_tool_call(tool, task_id="t")
            self.assertTrue(guard.is_tainted("t"), tool)
        self.guard.post_tool_call("mcp_agentcore_schwab_getQuotes", session_id="s")
        self.guard.post_tool_call("web_search", session_id="s")
        self.assertFalse(self.guard.is_tainted("s"))

    def test_unknown_server_name_fails_closed(self):
        guard = mail_guard.Guard(self.path, server="renamed")
        guard.post_tool_call(MAIL, session_id="s")
        decision = guard.pre_tool_call("mcp_agentcore_schwab_getQuotes", session_id="s")
        self.assertEqual(decision["action"], "approve")

    def test_block_mode_blocks(self):
        guard = mail_guard.Guard(self.path, mode="block")
        guard.post_tool_call(MAIL, session_id="s")
        self.assertEqual(
            guard.pre_tool_call("terminal", session_id="s")["action"], "block"
        )

    def test_taint_survives_a_restart_and_expires(self):
        now = [1000.0]
        self.guard = mail_guard.Guard(self.path, clock=lambda: now[0])
        self.guard.post_tool_call(MAIL, session_id="old")
        self.assertTrue(mail_guard.Guard(self.path).is_tainted("old"))
        now[0] += mail_guard.RETENTION_SECONDS + 1
        self.guard.post_tool_call(MAIL, session_id="new")
        restarted = mail_guard.Guard(self.path)
        self.assertFalse(restarted.is_tainted("old"))
        self.assertTrue(restarted.is_tainted("new"))

    def test_missing_ids_taint_every_session(self):
        self.guard.post_tool_call(MAIL)
        self.assertEqual(
            self.guard.pre_tool_call("terminal", session_id="any")["action"], "approve"
        )

    def test_taint_follows_subagents_and_session_lineage(self):
        self.guard.post_tool_call(MAIL, session_id="parent")
        self.guard.subagent_start(parent_session_id="parent", child_session_id="child")
        self.assertTrue(self.guard.is_tainted("child"))
        self.guard.pre_llm_call(session_id="compressed", parent_session_id="parent")
        self.assertTrue(self.guard.is_tainted("compressed"))
        self.guard.subagent_stop(
            parent_session_id="clean",
            tool_call_history=[{"tool_name": "mcp_agentcore_outlook_getMessage"}],
        )
        self.assertTrue(self.guard.is_tainted("clean"))
        self.guard.subagent_stop(
            parent_session_id="still-clean", tool_call_history=[{"tool_name": "todo"}]
        )
        self.assertFalse(self.guard.is_tainted("still-clean"))

    def test_corrupt_state_starts_empty(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")
        self.assertFalse(mail_guard.Guard(self.path).is_tainted("s"))

    def test_register_wires_every_hook(self):
        class Context:
            hooks = {}

            def register_hook(self, name, callback):
                self.hooks[name] = callback

        context = Context()
        mail_guard.register(context)
        self.assertEqual(
            set(context.hooks),
            {
                "post_tool_call",
                "pre_tool_call",
                "pre_llm_call",
                "subagent_start",
                "subagent_stop",
            },
        )

    def test_every_adapter_tool_is_classified_and_writes_are_never_read_tools(self):
        tools = manifest_tools()
        self.assertEqual(tools, mail_guard.READ_TOOLS | mail_guard.WRITE_TOOLS)
        self.assertFalse(mail_guard.READ_TOOLS & mail_guard.WRITE_TOOLS)
        sources = {
            tool
            for tool in tools
            if tool.startswith(("thundermail-", "google-", "outlook-"))
        }
        self.assertEqual(sources, mail_guard.SOURCE_TOOLS)
        for tool in sources:
            self.assertTrue(mail_guard.is_source(f"mcp_agentcore_{tool}"), tool)
