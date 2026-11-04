# HANDOFF

Where the project stands, how it is put together, how to run the tests, and what has not been verified yet. Read it before you start, and update it when you finish something.

## What this is

A private, self-hosted assistant for the day: a dashboard (notes, journal, gym, health reminders, calendar, weather, news, a morning briefing and more), a Telegram bot, and optional apps (Grafana and Prometheus monitoring, local AI with Ollama and Open WebUI, speech to text, n8n and others). It runs in Docker, is installed once, and is updated with git. Linux and macOS work today, WSL2 is planned. It adapts to the hardware, and every optional feature degrades gracefully when its dependency is missing.

## Current state

- Version 0.1.0, the first tagged release. The public history starts there.
- Install: `get.sh` (one line, `curl ... | bash`) downloads the project with git and runs `install.sh`. It starts on the newest `v*` tag (stable) or on `main` (`HL_CHANNEL=edge`).
- Update: `homelab update` needs a clean git tree, fetches, refuses a diverged copy, takes a snapshot backup, stops services, fast-forwards, runs data migrations, rebuilds, waits for `/api/bot/doctor`, and rolls back by itself on any failure. Channels: `stable` (highest release tag) and `edge` (`origin/main`).
- Setup wizard on first run: name and time zone, machine, modules, AI engine, Telegram, access. Every step can be skipped.
- Custom apps: you can add your own Docker apps from Settings or the command line, each in its own compose project.
- CI (`.github/workflows`): `leak-scan`, `lint`, `compose`, `pins` and `tests` on every push and pull request. Releases are cut by release-please, and images are built and signed by `images.yml`.

## Architecture map

```
core/            the engine: config, settings, module registry, HTTP API, scheduler, store, LLM client, doctor,
                 setup wizard backend, CLI (core/cli.py), host helper (core/agent.py), migrations, hardware probe
core/hardware/   the machine probe and the profiles that pick AI models
core/telegram/   the bot transport
modules/         one folder per feature (journal, gym, news, ...) with a module.yaml and register(app)
stack/           compose.yaml, the dashboard (stack/landing/site), config.example.yaml, monitoring configs
host/            scripts for the host machine, outside Docker
install.sh       the installer (questions first, then quiet steps with a spinner; full output in $HL_HOME/install.log)
get.sh           the one-line installer
bin/homelab      the command line (a thin wrapper around core/cli.py)
scripts/         guards (data, personal values, tokens, pins) and dev-reset.sh
tests/           unit tests (stdlib unittest), golden API replies, Playwright end-to-end tests on demo data
demo/            fake demo data generator (fixed seed) and the demo screenshots
docs/            modules guide, anti-patterns, this file, the disclaimer
.github/         CI, issue and PR templates, CODEOWNERS, rulesets/main.json
```

Ideas that hold it together:

- **Modules** talk to the core through `core/host.py` (`host.provide` and `host.need`) and never import each other. See `docs/modules.md` and `modules/_template`.
- **Capabilities and doctor.** Each dependency (Ollama, Whisper, Telegram, calendar, host helper) is a capability. `homelab doctor` and the dashboard say what works, what is limited and how to fix it.
- **Config.** `stack/config.yaml` (copied from `config.example.yaml`) plus a `settings.json` in the data folder that the dashboard writes on top. The schema and validation are in `core/config.py`.
- **Hardware.** The installer saves the real machine to `host-hardware.json` in the data folder, because the app inside Docker only sees Docker's virtual machine.
- **Host helper** (`core/agent.py`): a small user-level service (systemd user unit or a LaunchAgent) that lets the containerised app restart apps or start an update by dropping a request file. It has an allowlist, only touches this project's containers, and reboot is off unless you ask for it.
- **Pins.** Every image is pinned to an exact version (`scripts/check-pins.py`). Renovate proposes updates weekly. Watchtower is optional and off.

## Run the tests

```bash
python3 -W ignore -m unittest discover -s tests   # unit tests, about a minute
make check                                        # data guard, personal values, design tokens, image pins, gitleaks
make test                                         # golden API tests and bot router tests
make test-e2e                                     # dashboard smoke tests on demo data (pip install playwright pyyaml; playwright install chromium)
make update-golden                                # re-record the golden API replies (review the git diff first)
make update-baselines                             # re-record the phone-width screenshots (review them first)
python3 demo/screenshots.py                        # re-record the README screenshots from demo data (needs playwright; review them first)
```

The unit tests and `make check` run on both macOS and Linux. The maintainer has a private list of personal values (`.private/denylist.txt`). `make hooks` turns on maintainer mode when that file exists, and then the check is required. Contributors have no list and are covered by `scripts/check-personal.py` (emails and public IPs), gitleaks, the data guard and review.

## What has been verified

- The unit tests and `make check` pass on an Apple Silicon Mac, including `make check` with the maintainer's personal-value list.
- `get.sh` against a local throwaway repository (fresh download, release and edge channels, second run, refusals).
- The compose stack has run for real on one Apple Silicon Mac (OrbStack).

## What has not been verified

- **`get.sh` over the real internet.** The raw GitHub address only works once the repository is public. The stable path (checking out the newest tag) has only been tested against a local repository.
- **A real Mac and Linux install** with Colima, Docker Desktop, Docker Engine and a Raspberry Pi. The Colima and official-Linux-Docker paths in `install.sh` are covered by tests with fake tools only.
- **Custom apps on real Docker.** Adding, starting and removing your own app has only run against fake tools.
- **Homebrew record and purge** (what the installer installed, and removing it again) on a real Mac.
- **launchd and systemd.** The host helper, autostart and the reboot path have never run for real on both systems.
- **`homelab update`, rollback and `restore`** against a real remote or a real failure.
- **GitHub workflows.** None has run yet. Action versions in `.github/workflows` were written from memory and are unchecked.
- **Pinned image versions** (n8n, Grafana, Open WebUI) were never started together. Check them and take `homelab backup` first.
- **Model tags** in the hardware profiles are not checked against the Ollama library.

## Known gaps and open work

- Some features are India-specific (news sources, cricket) and need generalising. Journal tags and the schedule need a pass.
- Linux host-layer assumptions (metrics, network fallback) are not generalised. AdGuard and SearXNG need config templates.
- A Grafana ntfy alert, the calendar wizard step and a dashboard Update button are not built.
- Backups are unencrypted. `homelab` is not on the PATH until you run `homelab path add`. On Linux the helper needs `sudo loginctl enable-linger $USER` to survive logout (the installer prints it, it cannot run it).
- No cross-process update lock beyond the helper's own check. `homelab update` still builds images locally. Switching to prebuilt registry images is a later step.
- Windows (WSL2) is refused politely for now.
- macOS polish: a compose override (no host-mounted metrics, a light cAdvisor), native Ollama for the Apple GPU, launchd jobs for backup and stats, and a test matrix (OrbStack, Docker Desktop, Colima).
- Budget maths is frozen. A separate budget plan is waiting to slot in.

## Good first things

Run the whole install and reset loop on your own machine and write down everything that surprises you. Fix the first rough edge you hit. Pick one open item above and propose a plan before building. Always work on a branch and open a pull request into `main`.
