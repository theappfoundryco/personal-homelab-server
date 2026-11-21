"""Tools: what the assistant can look up, described once and used by two front doors.

1. The local AI. When a message asks for more than one thing ("what are my reminders and what's the weather tomorrow?"), the chat model is
   offered these tools through Ollama's /api/chat `tools`, may call several, and answers from their results. Everyday messages keep the
   fast classifier path and never pay for this.
2. MCP (the Model Context Protocol, an open spec). POST /mcp answers JSON-RPC (initialize, tools/list, tools/call), so Claude Desktop,
   Claude Code or any MCP client can ask your homelab "what are my reminders" or "is the server healthy". It is off until you run
   homelab mcp, which makes a token and prints how to connect.

Every tool here only reads. Nothing that changes your data or your machine is offered to either door yet: a change from a model needs a
Yes or No from you first, and that design is in docs/plans/tools.md. Standard library only."""
import hmac
import json
import os
import secrets

PROTOCOL = "2025-11-25"  # the newest MCP version this speaks; the older ones below ask nothing more of a tools-only server
KNOWN = {"2025-03-26", "2025-06-18", "2025-11-25"}
TOKEN_FILE = "mcp-token"
TYPES = {"string": str, "integer": int, "boolean": bool}


class Tools:
    def __init__(self):
        self.items = {}

    def add(self, name, description, fn, params=None, required=()):
        """params: {name: (type, description)}; fn(**args) returns text. Read-only tools only."""
        self.items[name] = {"description": description, "fn": fn, "params": params or {}, "required": tuple(required)}

    def schemas(self):
        """The list both Ollama and MCP take: name, description and a JSON schema of the arguments."""
        return [{"name": n, "description": t["description"],
                 "inputSchema": {"type": "object", "properties": {k: {"type": ty, "description": d} for k, (ty, d) in t["params"].items()},
                                 "required": list(t["required"])}} for n, t in self.items.items()]

    def for_ollama(self):
        return [{"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["inputSchema"]}} for s in self.schemas()]

    def call(self, name, args):
        """(text, ok). Unknown tools and wrong arguments are said plainly, so a model can correct itself."""
        t = self.items.get(name)
        if not t:
            return f"There is no tool called {name}.", False
        args = args if isinstance(args, dict) else {}
        clean = {}
        for k, v in args.items():
            if k not in t["params"]:
                return f"{name} does not take {k}.", False
            want = TYPES[t["params"][k][0]]
            if want is int and isinstance(v, str) and v.strip().lstrip("-").isdigit():
                v = int(v)
            if not isinstance(v, want) or (want is int and isinstance(v, bool)):
                return f"{k} should be a {t['params'][k][0]}.", False
            clean[k] = v
        missing = [k for k in t["required"] if k not in clean]
        if missing:
            return f"{name} needs {', '.join(missing)}.", False
        try:
            return str(t["fn"](**clean))[:4000], True
        except Exception as e:  # a tool that breaks says so, it never takes the assistant down
            return f"{name} could not answer: {e}", False


def token(data_dir, make=False):
    """The MCP token (48 random hex characters), kept in the data folder and readable only by you. Only `homelab mcp` makes it,
    so MCP stays off until you turn it on, and the file belongs to you rather than to the container."""
    p = os.path.join(data_dir, TOKEN_FILE)
    try:
        with open(p) as f:
            t = f.read().strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    if not make:
        return None
    t = secrets.token_hex(24)
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t + "\n")
    os.replace(p + ".tmp", p)
    return t


def mcp(tools, message, version):
    """One JSON-RPC message in, (reply or None for a notification). Only the methods MCP needs for tools."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None, "error": {"code": -32600, "message": "Not a JSON-RPC 2.0 request."}}
    mid, method, params = message.get("id"), message["method"], message.get("params") or {}
    if "id" not in message:
        return None  # notifications/initialized and friends need no answer
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") if params.get("protocolVersion") in KNOWN else PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "homelab", "version": version},
                  "instructions": "Your own homelab: reminders, notes, your day, the weather and the server's health. Every tool only reads."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools.schemas()}
    elif method == "tools/call":
        text, ok = tools.call(params.get("name"), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": not ok}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"{method} is not offered here."}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def allowed(req, data_dir):
    want, got = token(data_dir), (req.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    return bool(want and got) and hmac.compare_digest(got.encode(), want.encode())


def routes(router, tools, data_dir, version):
    @router.post("/mcp")
    def mcp_post(req):
        if not allowed(req, data_dir):
            why = "A token is needed. See it with: homelab mcp" if token(data_dir) else "MCP is off. Turn it on with: homelab mcp"
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": why}}, 401
        try:
            body = req.json()
        except ValueError:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "That is not JSON."}}, 400
        if isinstance(body, list):  # a batch
            out = [r for r in (mcp(tools, m, version) for m in body) if r is not None]
            return (out, 200) if out else ({}, 202)
        out = mcp(tools, body, version)
        return (out, 200) if out is not None else ({}, 202)

    @router.get("/mcp")
    def mcp_get(req):
        return {"error": "This MCP endpoint answers POST only (no event stream)."}, 405


def answer_with_tools(chat_call, tools, messages, rounds=3):
    """The local AI door: offer the tools, run what the model asks for, and give its answer. chat_call(messages, tools) is Ollama /api/chat
    without streaming. Returns the final text, or None when the model does not take tools (then the normal chat answers)."""
    spec = tools.for_ollama()
    for _ in range(rounds):
        reply = chat_call(messages, spec)
        msg = (reply or {}).get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or None
        messages = messages + [msg]
        for c in calls[:6]:
            f = c.get("function") or {}
            args = f.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            text, _ = tools.call(f.get("name"), args)
            messages.append({"role": "tool", "content": text, "tool_name": f.get("name")})
    return None


def builtin(tools, state, nice_when, tz, day_events, event_line, weather_lines, location, doctor, strip_tags):
    """The tools every install has. Each reads your own data on this machine and returns a few plain lines."""
    from datetime import datetime, timedelta

    from core.helpers import now

    def reminders(limit=10):
        rs = sorted(state.get("reminders") or [], key=lambda r: r["due"])[:max(1, min(int(limit), 30))]
        return "\n".join(f"{nice_when(datetime.fromtimestamp(r['due'], tz))}: {r['text']}" for r in rs) or "No reminders."

    def notes(limit=10):
        return "\n".join(f"- {n['text']}" for n in (state.get("notes") or [])[:max(1, min(int(limit), 30))]) or "No notes."

    def goals():
        return "\n".join(f"- {g['text']}" for g in state.get("goals") or [] if not g.get("achieved")) or "No goals."

    def day(day="today"):
        d = now().date() + timedelta(1 if str(day).lower() == "tomorrow" else 0)
        events = [strip_tags(event_line(e, False)).lstrip("• ").strip() for e in day_events(d)]
        due = [f"{nice_when(datetime.fromtimestamp(r['due'], tz))}: {r['text']}" for r in state.get("reminders") or []
               if datetime.fromtimestamp(r["due"], tz).date() == d]
        return (f"{d:%A %d %B}\nCalendar: " + ("; ".join(events) or "nothing") + "\nReminders: " + ("; ".join(due) or "none"))

    def weather():
        loc = location()
        return f"{loc['city']}: " + strip_tags(" ".join(weather_lines(loc)[:4]))

    def health():
        r = doctor()
        broken = [c["title"] for c in r["capabilities"] if not c["ok"] and not c.get("off")]
        failed = [m["name"] for m in r["modules"] if m.get("state") == "failed"]
        return ("Everything is working." if r["ok"] and not broken else "Problems: " + "; ".join(broken + [f"module {m} failed" for m in failed] + r["config"])) \
            + f"\nModules running: {sum(1 for m in r['modules'] if m.get('state') in ('on', 'degraded'))} of {len(r['modules'])}."

    tools.add("list_reminders", "Your upcoming reminders, soonest first.", reminders, {"limit": ("integer", "How many, up to 30 (default 10).")})
    tools.add("list_notes", "Your notes, newest first.", notes, {"limit": ("integer", "How many, up to 30 (default 10).")})
    tools.add("list_goals", "Your long-term goals that are not achieved yet.", goals)
    tools.add("my_day", "Calendar events and reminders for today or tomorrow.", day, {"day": ("string", "today or tomorrow (default today).")})
    tools.add("weather", "The weather now and later today where you are.", weather)
    tools.add("server_health", "Whether the homelab is healthy: anything broken, and how many modules are on.", health)
