# Plan: a platform profile, so the installer and the doctor say what this machine can do

Status: the plumbing below is **built** in this pull request (it changes no screen). The parts marked **plan only** change how the installer or the dashboard behave and wait for the maintainer's yes.

Research and sources: `docs/research/platform-matrix.md`.

## The idea

The project already probes the hardware on the real machine and saves it (`host-hardware.json`), because the app inside Docker only sees its own container. The platform goes in the same file, under `platform`. Then every place that needs to know "what is this machine" reads one set of facts:

```
install.sh  ->  python3 -m core hardware --save DATA  ->  host-hardware.json { ...hardware, platform: {...} }
                                                             |
              core/registry.this_platform(DATA)  <-----------+  modules' platforms: [linux, mac]
              core/doctor.report(... machine)    <-----------+  "On this machine" rows
```

## Built

- `core/hardware/system.py`: plain functions over text and files, every reader passed in.
  - `parse_os_release`, `family`, `init_system`, `selinux`, `where` (container, WSL, machine), `laptop`, `docker_flavour`, `docker_source`, `detect`.
  - `checks(platform)`: doctor rows, each `works`, `limited` (why) or `unavailable` (why, and what to type instead). Something normal for a platform is shown as `--`, not a warning.
- `hardware.save()` adds `platform` when the installer saves the machine.
- `python3 -m core hardware --save` works without PyYAML (only the profile name needs it, and the app inside Docker has it).
- `registry.this_platform(DATA)` uses the saved OS, so a Mac is a Mac for modules.
- `homelab doctor` prints an "On this machine" block:
  ```
  On this machine
    --    Host helper and autostart: This machine uses OpenRC. The host helper is a systemd user service.
          Fix: Start it after a restart with: homelab start. ...
    warn  Keep running after you log out: When you log out, systemd stops your services, the host helper with them.
          Fix: Run once: sudo loginctl enable-linger $USER
    warn  Always on: This looks like a laptop. While it sleeps, reminders, the morning briefing and backups wait.
  ```
- `install.sh`:
  - `os_info` and `docker_plan`: get.docker.com only where it supports the distribution; Arch, Alpine (OpenRC), openSUSE and Void use their own packages, shown on one line, run with sudo; NixOS, Gentoo, Amazon Linux and unknown systems stop with exactly what to do. Same rules as `docker_source()`; a test checks they agree on every recorded distribution.
  - Python 3 is installed with the distribution's packages when missing, with one line saying why.
- Tests: `tests/test_platform.py` (recorded `/etc/os-release` from 17 official images and a recorded `docker info`), plus installer, doctor and hardware tests.

## Plan only (needs a yes)

### 1. Port check for every app before `compose up`

Today only the dashboard port (3095) is checked. Grafana 3000, Uptime Kuma 3001, Homepage 3080, n8n 5678, Open WebUI 8081, Dozzle 8888, SearXNG 8889, Prometheus 9090 and Ollama 11434 are fixed in `stack/compose.yaml`. On a machine that already runs any of them, `compose up` fails with Docker's own error.

- Every host port becomes `${HL_<APP>_PORT:-default}` (the fork's `HL_GRAFANA_PORT`, generalised).
- Before starting, the installer and `homelab apps add` check each chosen app's port. If it is busy and not ours, they say which program has it (`lsof -iTCP:<port> -sTCP:LISTEN` or `ss -ltnp`) and pick the next free port, writing it to `.env`:
  ```
    warn  Port 3000 (Grafana) is used by another program (node). Grafana will use 3002 instead.
  ```
- The dashboard tiles read the ports from the API instead of hard-coding them.

This changes installer output and dashboard links, so it is plan only.

### 2. SELinux volume labels

Add `:z` only to folders the project owns (`stack/` configs, the data folder) and never to system paths. Needs a Fedora or Rocky VM with SELinux enforcing to test.

### 3. Host helper on OpenRC and runit

An OpenRC user service does not exist the way a systemd user unit does. Options: a system service running as the user (`/etc/init.d/homelab-agent` with `command_user`), or keep "unavailable" and the commands to type. Recommendation: keep it unavailable until someone asks; Alpine users are rare for this project.

### 4. Raspberry Pi and low memory

`core/hardware/profiles.yaml` already picks the `tiny` and `small` profiles. The app catalogue should hide or warn about Ollama, Open WebUI, Whisper and n8n on `tiny` (under about 5 GB). Changes the setup wizard, so plan only.

### 5. GPU

Offer the GPU path only when `nvidia-smi` works and the NVIDIA Container Toolkit is installed (`docker info` lists the `nvidia` runtime); otherwise CPU with a note. AMD ROCm: `/dev/kfd` exists. Not built: nothing to test it on tonight.

## Rules kept

- Ask everything first, then work. Docker and Python are installed without asking, with one line saying what and why.
- Full output in `install.log`. Nothing waits behind a spinner.
- No new dependency.
