"""Release notes from commit sentences: security: is Security, feat: is New, fix: is Fixed. Other prefixes (docs:, chore:, release: ...)
and sentences with no prefix are left out. Used by the dashboard's update popup and by scripts/release.py, so both say the same thing."""
import re

CATS = (("security", "security"), ("feat", "new"), ("fix", "fixed"))  # commit prefix, notes section; the popup shows them in this order
NOTE = re.compile(r"(feat|fix|security)(?:\([^)]*\))?!?:\s*(.+)")


def parse_notes(subjects):
    """Commit subjects as release notes: feat: is New, fix: is Fixed, security: is Security. Other prefixes (docs:, chore:, ...) are left out."""
    out = {sec: [] for _, sec in CATS}
    for s in subjects:
        m = NOTE.fullmatch(str(s or "").strip())
        if not m:
            continue
        text = re.sub(r"\s*\(#\d+\)$", "", m.group(2)).strip().rstrip(".")
        text = text[:1].upper() + text[1:] + "." if text else ""
        sec = dict(CATS)[m.group(1)]
        if text and text not in out[sec]:
            out[sec].append(text)
    return out


TITLES = {"security": "Security", "new": "New", "fixed": "Fixed"}


def markdown(notes):
    """The notes as Markdown sections for a GitHub Release, Security first."""
    out = []
    for _, sec in CATS:
        if notes.get(sec):
            out.append(f"### {TITLES[sec]}\n" + "\n".join(f"- {x}" for x in notes[sec]))
    return "\n\n".join(out) or "Small changes behind the scenes."
