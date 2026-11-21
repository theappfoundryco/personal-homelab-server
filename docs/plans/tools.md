# Tools: one description, two front doors

## What is built (v1)

- `core/tools.py` holds a small registry: a name, one line saying what the tool does, typed arguments, and a function that returns plain text. Arguments are checked before a tool runs. A tool that raises says so instead of taking the assistant down.
- **Built-in tools** (all read only): `list_reminders`, `list_notes`, `list_goals`, `my_day` (today or tomorrow), `weather`, `server_health`.
- **Front door 1, the local AI.** A message that asks for more than one thing (`core/chat.py` `MULTI`, for example "what are my reminders and what's the weather?") goes to Ollama's `/api/chat` with `tools`.
  - The model may call several tools, up to 3 rounds and 6 calls a round, and then answers from what they returned.
  - A model that does not take tools gets a 400 from Ollama, and the normal chat answers instead.
  - Everyday messages never take this path, so they stay on the fast classifier.
- **Front door 2, MCP.** `POST /api/bot/mcp` answers JSON-RPC 2.0: `initialize`, `ping`, `tools/list` and `tools/call`.
  - Notifications get a 202 and batches are accepted. Any other method returns `-32601`.
  - Protocol versions 2025-03-26, 2025-06-18 and 2025-11-25 are accepted.
  - It is off until `homelab mcp`, which makes a 48-character token (mode 0600, owned by you) and prints the `claude mcp add` line. `homelab mcp off` deletes the token, which shuts every client out.
  - The token is compared in constant time (`hmac.compare_digest`).
  - It goes through the dashboard's address, so it follows the same access setting: this machine only, or the home network with the PIN.

## Why read only first

A model that can change things needs a person in the loop. Small models sometimes pick the wrong tool, and a prompt can be steered by text the model reads (a note, a calendar event, an email). So v1 offers nothing that writes.

## Next: tools that change something

1. A tool declares `changes=True`.
2. **The local AI:** a change is never run directly. The assistant sends a Telegram message describing the exact call ("Add a reminder: call Sam, Friday 6:00 PM?") with Yes and No buttons, the same pattern as `modules/homeassistant` (PR #26). Only Yes runs it.
3. **MCP:** changes stay off unless `mcp.allow_changes: true`, and even then each one asks on Telegram first. The MCP reply says the change is waiting for approval in Telegram.
4. **Host actions** (restart, update) are never tools. They stay behind `core/agent.py`'s allowlist.
5. **Logging:** every tool call (name, arguments, who asked: chat or MCP) goes to the run log, so the Night log can show it.
6. **Golden tests:** a set of sentences and the tools they should pick, run against the profile models, so a model change that picks worse tools fails CI.

## Modules

A module can add its own tools with `TOOLS.add(...)` through `host.need`. Home Assistant's states (PR #26) are the obvious next one: `home_status` (read) and, after the Yes/No design above, `home_action` (change).
