# Hermes mail guard plugin

## What it does

`agents/hermes/plugins/mail-guard/` is a Hermes plugin. It marks a session as
tainted when the session calls a Thundermail, Google or Outlook tool through the
AgentCore adapter, because mail and calendar content can contain instructions
from other people. In a tainted session, every tool call needs your approval in
chat, except these read tools:

- `read_file`, `search_files`, `todo`, `clarify` and `session_search`.
- The read tools of the adapter (`READ_TOOLS` in `__init__.py`), for example the
  mail, calendar, Schwab, AWS documentation and GitHub read tools.

The terminal, file writes, code execution, the browser, web tools, memory, cron,
delegation, GitHub writes, `aws___run_script` and the tools of other MCP servers
all need approval. Hermes denies the call if you deny it or if the approval
times out.

The taint also moves to subagents of a tainted session, to a session whose
parent session is tainted, and to the parent of a subagent that read mail. If a
hook call has no session ID, the guard taints all sessions. The guard keeps the
taint in `$HERMES_HOME/mail-guard/tainted.json` for 30 days, so it stays after a
gateway restart. `/new` starts a session that is not tainted.

`test_mail_guard.py` makes sure that every tool in the adapter manifests is in
`READ_TOOLS` or `WRITE_TOOLS`. When you add a tool to a manifest, add it to one
of the two sets.

## Install or update

1. Merge the change and copy the full 40-character commit SHA from master.
2. On the Hermes host, install that commit and enable the plugin:
   ```sh
   hermes plugins install andrewoconnor/oconnordev/agents/hermes/plugins/mail-guard --ref <sha> --enable
   ```
   To update, add `--force` and give the new SHA.
3. Restart the gateway: `hermes gateway restart`.
4. In a session, run `/plugins` and make sure that `mail-guard` is loaded.
5. Test it. Ask Hermes to read one email, then to run `echo test` in the
   terminal. Hermes must ask for approval before it runs the command.

## Settings

Set these variables in the environment of the Hermes gateway:

- `HERMES_MAIL_GUARD_MODE=block` blocks the calls instead of asking for
  approval.
- `HERMES_MAIL_GUARD_SERVER` is the name of the adapter in `mcp_servers`. The
  default is `agentcore`. If the name is different, the guard still taints, but
  it also asks approval for the adapter's read tools.

## Limits

- `/yolo` and `approvals.mode: off` can skip approval prompts. If you use them,
  set `HERMES_MAIL_GUARD_MODE=block`.
- Approve only the exact action that you asked for. If you select an
  "always" scope, Hermes may stop asking for that action.
- The guard does not taint web pages, files or other MCP servers. It does not
  change what the model reads or writes in chat.
- The guard runs as part of Hermes. It does not replace the gateway's Cedar
  policies, which Hermes cannot change.
