# Security policy

## Reporting a problem

Please report security problems privately, through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability** ([direct link](https://github.com/theappfoundryco/personal-homelab-server/security/advisories/new)). Do not open a public issue, discussion or pull request for it.

Include what you found, how to reproduce it, and what it could let someone do. You will get a reply as soon as the maintainers can manage, and a fix or a clear answer after that. Please give us a reasonable time to fix it before you share details.

## What is in scope

- The installer and the update flow (`get.sh`, `install.sh`, `homelab update`, backup and restore)
- The host helper (`core/agent.py`, `host/`) and anything that runs on your machine outside Docker
- The dashboard and its HTTP API, the PIN and network access settings
- The Telegram bot and how it handles tokens, secrets and who may talk to it
- The Docker setup: ports, mounted folders, privileges, pinned image versions
- Secrets or personal data ending up in the repository, in logs or in backups

## What is not in scope

- Bugs in the apps we install (Grafana, n8n, Ollama and others). Report those to their own projects, though we want to hear about unsafe defaults we chose.
- Problems that need someone to already have full access to your machine or your account
- A dashboard you chose to open to your network without a PIN
- Reports from automated scanners with no working proof

## Supported versions

Only the newest release and `main` get fixes.
