"""The off-site copy: your data, encrypted by restic, in a storage service you choose (S3, Backblaze B2, Azure, Google Cloud, a restic REST server, or a folder such as a mounted drive).
restic runs as its own pinned container, so nothing new is installed on the machine. The password stays in .env and never leaves it in plain text;
lose it and the copy can never be read, which is why setup shows it once and the local backups hold it too.
The command line does the work (core/cli.py, `homelab offsite ...`); this file holds the parts the assistant needs too: the state file and its doctor line."""
import json
import os
import re
import time

IMAGE = "restic/restic:0.19.1"
STATE = "offsite.json"  # in the data folder: where (without any login in it), when it was set up, the last good copy and the last error
KEEP = ("--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6")
STALE = 3 * 86400  # no good copy for this long is a warning
KINDS = {  # repository prefix -> (name, the .env lines it needs besides HL_RESTIC_REPOSITORY and HL_RESTIC_PASSWORD)
    "s3:": ("S3 or any S3-compatible storage", ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")),
    "b2:": ("Backblaze B2", ("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY")),
    "azure:": ("Azure Blob Storage", ("AZURE_ACCOUNT_NAME", "AZURE_ACCOUNT_KEY")),
    "gs:": ("Google Cloud Storage", ("GOOGLE_PROJECT_ID", "GOOGLE_ACCESS_TOKEN")),
    "rest:": ("a restic REST server", ()),
    "/": ("a folder on this machine", ()),
}
# Only these .env names are handed to the restic container, and only by name (-e NAME), so no secret is ever on a command line.
PASS_ON = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", "AWS_SESSION_TOKEN", "B2_ACCOUNT_ID", "B2_ACCOUNT_KEY",
           "AZURE_ACCOUNT_NAME", "AZURE_ACCOUNT_KEY", "AZURE_ACCOUNT_SAS", "GOOGLE_PROJECT_ID", "GOOGLE_ACCESS_TOKEN",
           "RESTIC_REST_USERNAME", "RESTIC_REST_PASSWORD")


def kind(repo):
    """(name, needed .env names) for a repository address, or None when it is not one restic can reach from its container."""
    repo = (repo or "").strip()
    if not repo or any(ch in repo for ch in "\n\r\0") or ".." in repo.split("/"):
        return None
    for prefix, k in KINDS.items():
        if repo.startswith(prefix) and len(repo) > len(prefix):
            return k
    return None


def shown(repo):
    """The address with any login taken out (rest:https://user:pass@host/ becomes rest:https://host/), for messages and the state file."""
    return re.sub(r"(://)[^/@\s]+@", r"\1", repo or "")


def read(data_dir):
    try:
        with open(os.path.join(data_dir, STATE)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write(data_dir, **change):
    d = {**read(data_dir), **change}
    p = os.path.join(data_dir, STATE)
    os.makedirs(data_dir, exist_ok=True)
    with open(p + ".tmp", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(p + ".tmp", p)
    return d


def check(data_dir, clock=time.time):
    """For the doctor: (ok, detail). Only asked when an off-site copy is set up."""
    s = read(data_dir)
    ok, err = s.get("last_ok") or 0, s.get("last_error") or {}
    if ok and clock() - ok < STALE and (err.get("at") or 0) <= ok:
        return True, ""
    if err.get("at") and err["at"] > ok:
        return False, f"The last off-site copy failed: {err.get('msg') or 'no reason given'}."
    return False, "No off-site copy in the last 3 days." if ok else "No off-site copy has been made yet."
