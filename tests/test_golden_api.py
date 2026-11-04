"""Golden API tests: every offline route is recorded once, then must not change.

    python3 -m unittest discover tests            run
    UPDATE_GOLDEN=1 python3 -m unittest discover tests   re-record (review the diff before committing)

A refactor that changes a reply, or what a write leaves on disk, fails here.
"""
import json
import os
import unittest

from harness import ROOT, call, load_bot, start_api

GOLDEN = os.path.join(ROOT, "tests", "golden")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

GET_ROUTES = ["/config", "/sg", "/sg/ai", "/gym", "/journal", "/journal/now", "/journal/weekly", "/journal/deep",
              "/journal/deep/letters", "/journal/month?m=2026-10", "/journal/year?y=2026", "/runs", "/past", "/notes",
              "/nope"]

# writes, in order: (method, path, body)
POST_STEPS = [
    ("POST", "/notes", {"text": "  Golden note  "}),
    ("POST", "/notes", {"text": "   "}),
    ("POST", "/goals/achieve", {"id": "__goal0__"}),
    ("POST", "/gym/day", {"name": "Core"}),
    ("POST", "/gym/day", {"name": ""}),
    ("POST", "/gym/exercise", {"day": "__day_core__", "name": "Hanging leg raise"}),
    ("POST", "/gym/exercise", {"day": "nope", "name": "x"}),
    ("POST", "/gym/set", {"ex": "__ex_core__", "kg": 0, "reps": 12}),
    ("POST", "/gym/set", {"ex": "__ex_core__", "kg": 0, "reps": 0}),
    ("POST", "/gym/weight", {"date": "2026-11-03", "kg": 77.5}),
    ("POST", "/gym/weight", {"date": "2026-11-03", "kg": 5}),
    ("POST", "/journal/save", {"text": "Golden entry. A calm day."}),
    ("POST", "/journal/save", {"text": "Too early", "date": "2999-01-01"}),
    ("POST", "/capture/peek", {"text": "remind me to call Sam tomorrow at 5 pm"}),
    ("POST", "/capture/peek", {"text": "note: ideas for the weekend"}),
    ("POST", "/sg/tick", {"date": "2026-11-03", "id": "m1@0800", "done": True}),
    ("POST", "/sg/tick", {"date": "2999-01-01", "id": "m1@0800", "done": True}),
    ("POST", "/sg/health", {"id": "appt1", "due": "2026-12-01"}),
    ("POST", "/nope", {}),
]


def check(name, data):
    path = os.path.join(GOLDEN, name + ".json")
    text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if UPDATE or not os.path.exists(path):
        with open(path, "w") as f:
            f.write(text)
        return
    with open(path) as f:
        want = f.read()
    if want != text:
        import difflib
        diff = "".join(list(difflib.unified_diff(want.splitlines(True), text.splitlines(True), "golden", "now"))[:60])
        raise AssertionError(f"{name} changed:\n{diff}")


class GoldenApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()
        cls.srv, cls.base = start_api(cls.bot)
        os.makedirs(GOLDEN, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_1_get_routes(self):
        for p in GET_ROUTES:
            with self.subTest(route=p):
                code, body = call(self.base, "GET", p)
                check("get" + p.replace("/", "_").replace("?", "_").replace("=", "_"), {"status": code, "body": body})

    def test_2_writes(self):
        out = []
        ids = {"goal": call(self.base, "GET", "/notes")[1]["goals"][0]["id"]}
        for method, path, body in POST_STEPS:
            body = json.loads(json.dumps(body).replace("__goal0__", ids.get("goal", "")).replace("__day_core__", ids.get("day", ""))
                              .replace("__ex_core__", ids.get("ex", "")))
            code, reply = call(self.base, method, path, body)
            if path == "/gym/day" and code == 200 and "day" in reply:
                ids["day"] = reply["day"]["id"]
            if path == "/gym/exercise" and code == 200 and "exercise" in reply:
                ids["ex"] = reply["exercise"]["id"]
            out.append({"step": f"{method} {path}", "body": body, "status": code, "reply": reply})
        check("writes_replies", out)
        # what the writes left behind, read back through the API
        after = {p: call(self.base, "GET", p)[1] for p in ("/notes", "/gym", "/journal/month?m=2026-11")}
        check("writes_after", after)

    def test_3_no_network(self):
        from harness import _net_calls
        self.assertEqual(_net_calls, [], "a route tried to reach the internet")


if __name__ == "__main__":
    unittest.main()
