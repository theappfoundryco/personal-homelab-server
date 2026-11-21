"""Tools and MCP: arguments are checked, a broken tool never breaks the assistant, MCP is off until you turn it on and needs the token,
the JSON-RPC methods answer as the spec says, and the local AI runs the tools it asks for."""
import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import harness
from core import cli, tools
from test_cli import Base


def post(base, body, token=None, raw=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(base + "/mcp", data=raw or json.dumps(body).encode(), headers=h, method="POST"), timeout=10) as r:
            text = r.read()
            return r.status, json.loads(text) if text else None
    except HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Registry(unittest.TestCase):
    def setUp(self):
        self.t = tools.Tools()
        self.t.add("echo", "Says it back.", lambda word, times=1: " ".join([word] * times), {"word": ("string", "A word."), "times": ("integer", "How often.")}, required=["word"])
        self.t.add("broken", "Always fails.", lambda: 1 / 0)

    def test_arguments_are_checked_and_said_plainly(self):
        self.assertEqual(self.t.call("echo", {"word": "hi", "times": "2"}), ("hi hi", True))  # a number written as text is fine
        self.assertEqual(self.t.call("echo", {}), ("echo needs word.", False))
        self.assertEqual(self.t.call("echo", {"word": "hi", "times": True}), ("times should be a integer.", False))
        self.assertEqual(self.t.call("echo", {"word": "hi", "rm": "-rf"}), ("echo does not take rm.", False))
        self.assertEqual(self.t.call("nope", {}), ("There is no tool called nope.", False))
        self.assertEqual(self.t.call("broken", {})[1], False)
        self.assertIn("could not answer", self.t.call("broken", {})[0])

    def test_one_description_for_both_doors(self):
        s = self.t.schemas()[0]
        self.assertEqual(s["inputSchema"]["required"], ["word"])
        self.assertEqual(self.t.for_ollama()[0]["function"]["parameters"], s["inputSchema"])

    def test_the_local_ai_runs_what_it_asks_for_then_answers(self):
        seen = []

        def model(messages, spec):
            seen.append(messages[-1])
            if messages[-1]["role"] == "user":
                return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "echo", "arguments": {"word": "rain"}}},
                                                                                        {"function": {"name": "echo", "arguments": '{"word": "sun", "times": 2}'}}]}}
            return {"message": {"role": "assistant", "content": "Rain, then sun."}}
        self.assertEqual(tools.answer_with_tools(model, self.t, [{"role": "user", "content": "weather and more?"}]), "Rain, then sun.")
        self.assertEqual(seen[-1], {"role": "tool", "content": "sun sun", "tool_name": "echo"})
        self.assertIsNone(tools.answer_with_tools(lambda m, s: None, self.t, [{"role": "user", "content": "x"}]))  # a model without tools

    def test_only_messages_that_ask_for_more_than_one_thing_take_the_tool_path(self):
        from core import chat
        for yes in ("what are my reminders and what's the weather tomorrow?", "any notes? is the server ok?", "show my goals and my day"):
            self.assertTrue(chat.MULTI.search(yes), yes)
        for no in ("tell me a joke", "salt and pepper", "how are you?"):
            self.assertFalse(chat.MULTI.search(no), no)


class MCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = harness.load_bot()
        cls.base = harness.start_api(cls.bot)[1]

    def tearDown(self):
        p = os.path.join(self.bot.DATA, tools.TOKEN_FILE)
        if os.path.exists(p):
            os.remove(p)

    def test_off_until_turned_on_then_only_with_the_token(self):
        code, out = post(self.base, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual((code, out["error"]["message"]), (401, "MCP is off. Turn it on with: homelab mcp"))
        token = tools.token(self.bot.DATA, make=True)
        self.assertEqual(oct(os.stat(os.path.join(self.bot.DATA, tools.TOKEN_FILE)).st_mode & 0o777), "0o600")
        self.assertEqual(post(self.base, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token="wrong")[0], 401)
        self.assertEqual(post(self.base, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=token)[0], 200)

    def test_the_methods_mcp_needs(self):
        token = tools.token(self.bot.DATA, make=True)
        code, out = post(self.base, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}, token)
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(out["result"]["serverInfo"]["name"], "homelab")
        self.assertEqual(post(self.base, {"jsonrpc": "2.0", "method": "notifications/initialized"}, token), (202, {}))
        names = {t["name"] for t in post(self.base, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token)[1]["result"]["tools"]}
        self.assertEqual(names, {"list_reminders", "list_notes", "list_goals", "my_day", "weather", "server_health"})
        out = post(self.base, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_goals", "arguments": {}}}, token)[1]
        self.assertFalse(out["result"]["isError"])
        open_goals = [g["text"] for g in self.bot.state.get("goals") or [] if not g.get("achieved")]  # other tests may tick one off
        self.assertEqual(out["result"]["content"][0]["text"], "\n".join(f"- {g}" for g in open_goals) or "No goals.")
        out = post(self.base, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "delete_everything"}}, token)[1]
        self.assertTrue(out["result"]["isError"])
        self.assertEqual(post(self.base, {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, token)[1]["error"]["code"], -32601)
        self.assertEqual(post(self.base, None, token, raw=b"{not json")[0], 400)
        batch = post(self.base, [{"jsonrpc": "2.0", "id": 6, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}], token)[1]
        self.assertEqual(batch, [{"jsonrpc": "2.0", "id": 6, "result": {}}])
        self.assertEqual(harness.call(self.base, "GET", "/mcp")[0], 405)


class CommandLine(Base):
    def test_mcp_on_prints_how_to_connect_and_off_shuts_everyone_out(self):
        self.assertEqual(cli.main(["mcp"], self.ctx), 0)
        token = open(os.path.join(self.data, tools.TOKEN_FILE)).read().strip()
        self.assertIn(f'claude mcp add --transport http homelab http://localhost:3999/api/bot/mcp --header "Authorization: Bearer {token}"', self.say())
        self.lines.clear()
        cli.main(["mcp"], self.ctx)
        self.assertIn(token, self.say())  # the same token again
        cli.main(["mcp", "off"], self.ctx)
        self.assertFalse(os.path.exists(os.path.join(self.data, tools.TOKEN_FILE)))


if __name__ == "__main__":
    unittest.main()
