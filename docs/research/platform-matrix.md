# Platform matrix

What every machine this project may land on looks like, how to detect it, where Docker comes from, and what works there. Written 2026-11-21 from the source of widely used installers (links pin the exact commit read) and from queries run inside each distribution's official container image. Where something was not checked, it says so.

## Sources and licences

This project is MIT. Ideas and facts from any licence; code only from MIT, BSD or Apache, with attribution. **No code was copied for this work**: `core/hardware/system.py` and `docker_plan` in `install.sh` were written from the facts below.

| Project | File read | Licence | Used for |
|---|---|---|---|
| Docker `get.docker.com` | [docker/docker-install `install.sh`](https://github.com/docker/docker-install/blob/8ad27bd3ac871feabe62f1d926c4067800c1732f/install.sh) | Apache 2.0 | Which distributions it supports (`get_distribution`, L312), forks (`check_forked`, L391), end-of-life warnings (L569 to L590), refusals (`sles` L793, "Unsupported distribution" L808), WSL (`is_wsl`, L282) |
| Ollama | [ollama/ollama `scripts/install.sh`](https://github.com/ollama/ollama/blob/0b243a141a64110ef31d47ec35900cefcd467a18/scripts/install.sh) | MIT | WSL1 vs WSL2 (L101 to L106), Jetson (L179), "is systemd running" not "is systemctl installed" (L231), GPU by PCI vendor id (`check_gpu`, L277) |
| Tailscale | [tailscale/tailscale `scripts/installer.sh`](https://github.com/tailscale/tailscale/blob/05abd5d73e993fde80c78dea140ed1cbec48cd6b/scripts/installer.sh) | BSD 3-Clause | A long ID to package-manager table (L58 to L340), clean refusals with the exact fix (NixOS L299, Bazzite L305) |
| k3s | [k3s-io/k3s `install.sh`](https://github.com/k3s-io/k3s/blob/647ad6706757349803c34d1e33bc3e7384c68544/install.sh) | Apache 2.0 | systemd or OpenRC, else refuse (`verify_system`, L122), SELinux policy handling (`setup_selinux`, L585) |
| Home Assistant Supervised | [home-assistant/supervised-installer `README.md`](https://github.com/home-assistant/supervised-installer/blob/d29af7d8987b9a9a04fd17e48b2d51955d4fef7a/README.md) | Apache 2.0 | What a strict "supported system" policy looks like (one Debian, nothing else) |
| Pi-hole `basic-install.sh` | [pi-hole/pi-hole](https://github.com/pi-hole/pi-hole/tree/f7c0220e63e753c664a1ec08d42d6b647b86005d) | EUPL 1.2 | Ideas only. Not used tonight. |
| Netdata `kickstart.sh` | [netdata/netdata](https://github.com/netdata/netdata/tree/e61556ef0749e177233959fbe1e6fb9ab9fb03b8) | GPL 3.0 | Ideas only. Not used tonight. |
| Nextcloud AIO | [nextcloud/all-in-one](https://github.com/nextcloud/all-in-one/tree/eef92f9d3b135b3aaf99b8e0404b1183ba3df4e4) | AGPL 3.0 | Ideas only. Not used tonight. |

Not read tonight (left for a later pass): CasaOS, Umbrel, Runtipi, YunoHost, Cosmos, Coolify, linuxserver.io, Homepage, Homarr, Dashy, Uptime Kuma, Immich, Open WebUI docs.

## Detection

| Fact | How | Notes |
|---|---|---|
| Distribution | `/etc/os-release`: `ID`, `ID_LIKE`, `VERSION_ID`, `PRETTY_NAME`, `UBUNTU_CODENAME` | Read it in a subshell in bash: it also sets `NAME` and `VERSION`, which clobber a script's own variables |
| Family | `ID`, then each word of `ID_LIKE` | Rocky and Alma say `rhel centos fedora`; Amazon Linux says `fedora` but is its own case |
| Init system | `/run/systemd/system` exists (systemd booted), `/run/openrc` (OpenRC), `/run/runit` (runit), launchd on a Mac | Never "is `systemctl` installed": containers have it without systemd (Ollama does the same, L231) |
| WSL | `microsoft` in `/proc/sys/kernel/osrelease` | WSL1 says `Microsoft`, WSL2 `microsoft-standard-WSL2` |
| Container | `/.dockerenv`, `/run/.containerenv` (Podman), `docker`/`lxc`/`kubepods` in `/proc/1/cgroup` | |
| SELinux | `/sys/fs/selinux/enforce`: `1` enforcing, `0` permissive, missing off | |
| Laptop | `/sys/class/dmi/id/chassis_type` in 8, 9, 10, 11, 14, 30, 31, 32, or a `BAT*` in `/sys/class/power_supply`; on a Mac `pmset -g batt` lists `InternalBattery` | |
| Docker flavour | `docker info`: `Operating System: Docker Desktop`, `OrbStack`, `Name: colima`, `podman`, `rootless` in security options | |
| Compose | `docker compose version --short` | v1 (`docker-compose` 1.x) does not provide `docker compose` |
| Linger | `/var/lib/systemd/linger/$USER` exists | Without it systemd stops user services at logout |

## Where Docker comes from

Checked by querying the package manager inside each official image on 2026-11-21 (`harness/pkg-facts.sh`, run read-only).

| Distribution (image) | get.docker.com | Distribution packages found | What we do |
|---|---|---|---|
| Debian 11 (`debian:11`) | yes, with a 10 s end-of-life warning | `docker.io` 20.10, `docker-compose` 1.25 (v1) | get.docker.com, plus an end-of-life note |
| Debian 12 (`debian:12`) | yes | `docker.io` 20.10, `docker-compose` 1.29 (v1 only) | get.docker.com |
| Debian 13 (`debian:13`) | yes | `docker.io` 26.1, `docker-compose` 2.26 | get.docker.com |
| Ubuntu 20.04 | yes, end of life | `docker.io` 26.1, `docker-compose-v2` 2.27 | get.docker.com, plus a note |
| Ubuntu 22.04, 24.04 | yes | `docker.io` 29.1, `docker-compose-v2` 2.40 | get.docker.com |
| Ubuntu-based, not known by name (Mint, Pop!_OS, Zorin) | only if `lsb_release -u` works | as Ubuntu | `docker.io docker-compose-v2` (os-release has `UBUNTU_CODENAME`) |
| Debian-based, not known by name | only if `lsb_release -u` works | Debian 12 has compose v1 only | Stop, link to Docker's Debian steps |
| Fedora 40 | yes, end-of-life warning (below 43) | `moby-engine` 24, `docker-compose` 1.29 (v1) | get.docker.com, plus a note |
| Fedora 41 | yes, end-of-life warning | `moby-engine` 29, `docker-compose` 2.40 | get.docker.com, plus a note |
| Rocky 9, Alma 8 | yes | no Docker packages (Podman only) | get.docker.com |
| Amazon Linux 2023 | no ("Unsupported distribution") | `docker` 25, **no compose** | Stop with the compose plugin link |
| openSUSE Leap 15.6 | no | `docker` 28.5, `docker-compose` 2.22, `docker-buildx` | `zypper install docker docker-compose` |
| openSUSE Tumbleweed | no | `docker` 29.9, `docker-compose` 5.8, `docker-buildx` | same |
| Arch | no | `docker` 29.10, `docker-compose` 5.8, `docker-buildx` | `pacman -S --needed docker docker-compose docker-buildx` |
| Alpine 3.18, 3.20 | no | `docker`, `docker-cli-compose` 2.17 / 2.27, `docker-openrc` | `apk add docker docker-cli-compose`, then `rc-update add docker default` |
| Void | no | `docker` 29.8, `docker-compose` 5.5 | `xbps-install docker docker-compose`, runit service link |
| NixOS | no | declarative only | Stop: `virtualisation.docker.enable = true;` (not checked in a container: `nixos/nix` is not NixOS) |
| Gentoo | no | `app-containers/docker` (compiles) | Stop with the `emerge` line (not checked) |

Python 3: missing in the container base images of Arch, Alpine, openSUSE, Void, Debian, Ubuntu, Fedora 41 and Alma 8 (Fedora 40, Rocky 9 and Amazon Linux have it). Desktop and server installs of Debian, Ubuntu and Fedora normally ship it; minimal Arch, Alpine and Void installs often do not. The `homelab` command and the host helper are Python, so the installer now installs it with the distribution's packages.

## What works where

| | systemd Linux | Alpine (OpenRC) | Void (runit) | Container (no init) | WSL2 | Mac |
|---|---|---|---|---|---|---|
| Core apps | yes | yes | yes | yes | refused today | yes |
| Host helper, Restart and Update buttons | yes | no (systemd user unit) | no | no | no | yes (LaunchAgent) |
| Survives logout | with `loginctl enable-linger` | | | | | yes |
| `host.docker.internal` | only with `extra_hosts: host-gateway` | same | same | same | Docker Desktop: yes | yes |

## Findings that became fixes tonight

1. Fresh Ubuntu, Debian and Fedora have Python but not PyYAML, so the installer skipped the hardware check and never saved `host-hardware.json`. Fixed: saving needs no PyYAML.
2. `registry.this_platform()` runs inside Docker, so a Mac was treated as Linux for modules' `platforms:`. Fixed: the installer's saved OS wins.
3. get.docker.com was run on every Linux, and it stops on Arch, Alpine, openSUSE, Void, Amazon Linux and NixOS. Fixed: distribution packages or a clear stop.
4. No Python on minimal Linux images. Fixed: installed like Docker, with one line saying why.
5. `telegram-bot` and `open-webui` point at `host.docker.internal` for an Ollama outside Docker without `extra_hosts`, so it does not resolve on Linux Docker Engine. The SohamDarekar fork has the fix (`0365128`); left for its author's pull request.
6. `homelab restart` returned before the dashboard answered (PR #14).

## Open gaps, ranked

Score = people it hits (1 to 3) x how badly it fails today (1 to 3) x how safely we can detect it (1 to 3).

| Gap | Hits | Fails | Detect | Score | Status |
|---|---|---|---|---|---|
| Ports already in use (3000, 3001, 3080, 5678, 8081, 8888, 8889, 9090, 11434) before `compose up`; only 3095 is checked | 3 | 3 | 3 | 27 | Plan: `docs/plans/platform-profile.md` |
| `host.docker.internal` on Linux | 3 | 2 | 3 | 18 | Fork commit `0365128` |
| Linger missing, helper dies at logout | 2 | 2 | 3 | 12 | Doctor row built; installer already prints the command |
| User not in `docker` group in this login | 3 | 2 | 2 | 12 | Installer already re-runs with `sg docker`; doctor row built |
| Laptop sleeps, briefing and reminders missed | 2 | 2 | 2 | 8 | Doctor row built |
| SELinux enforcing blocks bind mounts | 1 | 3 | 3 | 9 | Doctor row built; volume labels not changed (see below) |
| Rootless Docker | 1 | 2 | 3 | 6 | Doctor row built. On this Ubuntu 24.04 host, `docker:dind-rootless` would not start (`fork/exec /proc/self/exe: operation not permitted`: unprivileged user namespaces are restricted by AppArmor) |
| Podman with `podman-docker` | 1 | 2 | 2 | 4 | Doctor says limited; not tested |

## SELinux and `:z`

`:z` relabels the host folder for container use. That is safe for folders this project owns (`stack/`, the data folder) and harmful on system paths (`/var/run`, `/sys`, `/var/lib/docker`, `/dev/disk`), which node-exporter and cAdvisor mount. Adding `:z` blindly would relabel system folders. Not changed tonight: it needs a Fedora or Rocky VM with SELinux enforcing to test, which a container cannot give. The doctor says "limited" and asks people not to turn SELinux off.

## Not verified tonight

- Anything on real hardware other than this one Linux box; no Raspberry Pi, no Mac.
- NixOS, Gentoo, Podman, WSL2.
- GPU passthrough (NVIDIA Container Toolkit) and AMD ROCm.
