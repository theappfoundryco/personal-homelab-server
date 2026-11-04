"""Reads config.yaml and checks it. Never raises: a broken file or a bad value means the default, plus a plain-English message."""
import os
import re
from zoneinfo import ZoneInfo

import yaml

TIME = "time"      # "6:30 AM", "6:30 pm" or 24-hour "18:30"
ZONE = "timezone"  # an IANA name like "Europe/London"

# name -> type. A dict is a section, a list holds one entry type, str/bool/int/float/TIME/ZONE are values.
SCHEMA = {
    "owner": {"name": str},
    "timezone": ZONE,
    "home": {"city": str, "country": str, "lat": float, "lon": float, "tz": ZONE},
    "dashboard_url": str,
    "world_clock": [{"flag": str, "label": str, "tz": ZONE}],
    "schedule": {"briefing": TIME, "evening_plan": TIME, "news_at": [TIME], "evening_on": bool, "weekly_on": bool},
    "models": {"chat": str, "embed": str, "journal": str, "claude_journal": str, "claude_news": str},
    "features": {"therapy_recap": bool},
    "support": {"therapist": str, "helpline_name": str, "helpline_tel": str},
    "therapy": {"calendar_words": [str]},
    "night": {"journal": bool, "journal_at": TIME, "insights": bool, "backup": bool, "backup_at": TIME, "backup_to": str, "backup_keep": int,
              "github": bool, "github_repo": str, "github_at": TIME},  # what runs at night; the host helper does the backup and the GitHub copy
    "news": {"topics": [str], "feeds": [{"name": str, "url": str, "topic": str}], "ai": str, "model": str},  # ai: auto, claude, openai, ollama or none
    "ollama": {"url": str},  # where Ollama runs; default http://ollama:11434 (the compose service)
    "dashboard": {  # how the page is laid out; edited in the dashboard's Settings, never needed in config.yaml
        "tabs": [str],           # bottom menu order, by tab id
        "tabs_hidden": [str],
        "home_hidden": [str],    # home cards to hide, by card id
        "tiles_hidden": [str],   # built-in app and tool tiles to hide, by name
        "tiles": [{"name": str, "sub": str, "url": str, "icon": str, "group": str}],  # your own tiles (group: apps or tools)
    },
    "modules": {"*": bool},  # modules: {gym: false} switches a module off
}

EXAMPLES = {TIME: "4:30 AM", ZONE: "Europe/London", str: "some text", bool: "true or false", int: "a whole number", float: "a number like 51.5"}


def clock_time(v, default):
    """A time written for people ("6:30 AM", "6:30 pm", or 24-hour "18:30") as (hour, minute)."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?\s*", str(v or ""), re.I)
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "p" else 0)
    return (h, mi) if h < 24 and mi < 60 else default


def _valid(kind, v):
    if kind is TIME:
        return clock_time(v, None) is not None
    if kind is ZONE:
        try:
            ZoneInfo(str(v))
            return isinstance(v, str)
        except Exception:
            return False
    if kind is bool:
        return isinstance(v, bool)
    if kind is float:
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if kind is int:
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, str)


def check(data, schema=SCHEMA, path=""):
    """Friendly problems found in data, as a list of strings. Unknown keys are reported as likely typos."""
    out = []
    if not isinstance(data, dict):
        return [f"{path or 'config.yaml'} should be a list of settings (name: value), not a single value."]
    for key, v in data.items():
        here = f"{path}.{key}" if path else key
        if key not in schema and "*" in schema:
            key_schema = schema["*"]
        elif key in schema:
            key_schema = schema[key]
        else:
            key_schema = None
        if key_schema is None:
            out.append(f"{here} is not a setting I know. Check the spelling against config.example.yaml.")
            continue
        kind = key_schema
        if v is None:
            continue
        if isinstance(kind, dict):
            out += check(v, kind, here)
        elif isinstance(kind, list):
            if not isinstance(v, list):
                out.append(f"{here} should be a list (one entry per line, starting with a dash).")
                continue
            for i, item in enumerate(v):
                if isinstance(kind[0], dict):
                    out += check(item, kind[0], f"{here}[{i + 1}]")
                elif not _valid(kind[0], item):
                    out.append(f"{here}[{i + 1}] should look like {EXAMPLES[kind[0]]} (you wrote {item!r}).")
        elif not _valid(kind, v):
            out.append(f"{here} should look like {EXAMPLES[kind]} (you wrote {v!r}).")
    return out


class Config:
    def __init__(self, data=None, problems=None):
        self.data = data if isinstance(data, dict) else {}
        self.problems = problems or []

    def get(self, path, default=None):
        """get("owner.name", "friend"): a value by dotted path."""
        v = self.data
        for k in path.split("."):
            if not isinstance(v, dict) or k not in v:
                return default
            v = v[k]
        return default if v is None else v

    def feature(self, name, default=True):
        return bool(self.get(f"features.{name}", default))

    def time(self, path, default):
        """A time setting as (hour, minute); a bad value gives the default."""
        return clock_time(self.get(path), default)


def load(path=None, log=print):
    """Config from the file at path (default: HL_CONFIG or /config/config.yaml). Problems are logged, never raised."""
    path = path or os.environ.get("HL_CONFIG", "/config/config.yaml")
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log("config.yaml not found: using defaults. Copy config.example.yaml to config.yaml and edit it.")
        return Config()
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark else ""
        log(f"config.yaml has a typing mistake{where}, so defaults are used until it is fixed. Indentation and colons are the usual cause.")
        return Config(problems=["unreadable"])
    except Exception as e:
        log(f"config.yaml could not be read ({e}): using defaults.")
        return Config(problems=["unreadable"])
    problems = check(data)
    for p in problems:
        log(f"config.yaml: {p}")
    return Config(data, problems)
