"""Render production Cedar using OpenTofu, evaluate offline with cedarpy."""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import cedarpy

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-mock"
TOOLS = {"imap_list_mailboxes", "imap_search_messages", "imap_get_message"}


class ThundermailCedarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "infra/aws/tools/target-thundermail.tf").read_text()
        template = re.search(
            r"statement = <<-CEDAR\n(.*?)\n\s*CEDAR", source, re.S
        ).group(1)
        template = (
            template.replace("each.key", "tool")
            .replace("local.thundermail_action_prefix", '"thundermail___"')
            .replace("aws_bedrockagentcore_gateway.hermes.gateway_arn", "local.gateway")
            .replace(
                "aws_cognito_resource_server.hermes.scope_identifiers[0]",
                '"hermes-mcp/invoke"',
            )
        )
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            Path(directory, "main.tf").write_text(f"""locals {{
  gateway = {json.dumps(GATEWAY)}
  policies = {{ for tool in {json.dumps(sorted(TOOLS))} : tool => <<-CEDAR
{template}
CEDAR
  }}
}}
""")
            result = subprocess.run(
                ["tofu", "console", "-no-color"],
                cwd=directory,
                input="jsonencode(local.policies)\n",
                text=True,
                capture_output=True,
                check=True,
            )
            cls.policies = "\n".join(json.loads(json.loads(result.stdout)).values())

    def decision(
        self,
        tool,
        *,
        scope="hermes-mcp/invoke",
        principal_type="OAuthUser",
        gateway=GATEWAY,
    ):
        uid = {"type": "AgentCore::" + principal_type, "id": "fixture"}
        entity = {
            "uid": uid,
            "attrs": {},
            "parents": [],
            "tags": {} if scope is None else {"scope": scope},
        }
        return cedarpy.is_authorized(
            {
                "principal": uid,
                "action": {"type": "AgentCore::Action", "id": tool},
                "resource": {"type": "AgentCore::Gateway", "id": gateway},
                "context": {},
            },
            self.policies,
            [entity],
        ).allowed

    def test_only_three_exact_scoped_reads(self):
        for tool in TOOLS:
            self.assertTrue(self.decision("thundermail___" + tool))
            self.assertFalse(self.decision(tool))
            self.assertFalse(self.decision("thundermail___" + tool, scope=None))
            self.assertFalse(self.decision("thundermail___" + tool, scope="other"))
            self.assertFalse(
                self.decision("thundermail___" + tool, principal_type="Service")
            )
            self.assertFalse(self.decision("thundermail___" + tool, gateway="other"))
        for tool in [
            "imap_delete_message",
            "smtp_send",
            "imap_move_message",
            "calendar_create",
            "login",
            "get_message",
            "imap-list-mailboxes",
        ]:
            self.assertFalse(self.decision("thundermail___" + tool))
