"""Important emails from Gmail, read over IMAP with an app password."""
import email
import email.header
import email.utils
import imaplib
import os
import re

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ gmail (IMAP + app password)
def gmail_items(limit=6):
    if not os.path.exists(GMAIL_FILE):
        return None
    pw = open(GMAIL_FILE).read().strip().replace(" ", "")
    with imaplib.IMAP4_SSL("imap.gmail.com", timeout=20) as M:
        M.login(GMAIL_USER, pw)
        M.select("INBOX", readonly=True)
        _, ids = M.search(None, "X-GM-RAW", '"is:unread is:important newer_than:2d -category:promotions -category:social"')
        out = []
        for i in reversed(ids[0].split()[-limit:]):
            _, data = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            msg = email.message_from_bytes(data[0][1])
            dec = lambda h: "".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p for p, c in email.header.decode_header(h or ""))
            sender = re.sub(r"\s*<.*>", "", dec(msg["From"])).strip('" ') or dec(msg["From"])
            out.append({"from": sender[:40], "subject": dec(msg["Subject"])[:90]})
        return out


@cached(600)
def gmail_cached():
    return gmail_items(5)


def gmail():
    typing()
    try:
        items = gmail_items()
    except Exception as e:
        return send(f"📧 I couldn't sign in to Gmail ({esc(e)}). The app password may be wrong or revoked.")
    if items is None:
        return send("📧 Gmail isn't connected yet.\n\n1. Open myaccount.google.com/apppasswords\n2. Create a password named <i>homelab</i>\n"
                    "3. On the server, save it in <code>~/.files/gmail.secret.txt</code>\n\nThen ask me again.")
    if not items:
        return send("📧 No important unread emails. Inbox zero vibes ✨")
    send("📧 <b>Important unread</b>\n" + "\n".join(f"• <b>{esc(i['from'])}</b>: {esc(i['subject'])}" for i in items),
         [[U("Open Gmail", "https://mail.google.com")]])


def register(app):
    host.need(globals(), "GMAIL_FILE", "GMAIL_USER", "U", "send", "typing")
