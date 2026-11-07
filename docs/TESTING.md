# Testing on real machines

The unit tests (`python3 -W ignore -m unittest discover -s tests`), `make check` and `make test-e2e` run everywhere with fake tools.
The **Install test** workflow installs for real on fresh Linux x64 and arm64 machines every week and on changes to the installer.
What is left needs a real machine and a person. Tick what you tried, with the date and the machine, in the pull request or in
docs/HANDOFF.md under "What has been verified".

## Install
- [ ] Mac, Apple Silicon, nothing installed: the one-line install installs Homebrew and Colima, and opens the dashboard.
- [ ] Mac with a leftover `docker` command and nothing to run it: Colima is installed, with a line saying so.
- [ ] Mac with OrbStack, and one with Docker Desktop: both are used as they are.
- [ ] Linux x64 (Ubuntu or Debian) without Docker: Docker Engine is installed with its own installer.
- [ ] Raspberry Pi 4 or 5, 64-bit Raspberry Pi OS: installs and the dashboard answers. (32-bit is not supported.)
- [ ] Running the installer a second time keeps every setting and password.

## The host helper and starting by itself
- [ ] Mac: `homelab agent install`, then Settings, Updates shows Update now. After a restart of the Mac it is still running (launchd).
- [ ] Linux: the same with systemd (`systemctl --user status homelab-agent`).
- [ ] `homelab autostart on`, restart the machine: the dashboard comes back without anyone logging in (Linux) or after login (Mac).

## Updates
- [ ] From the previous release, the dashboard offers the new one with its notes, and Update now finishes and reloads.
- [ ] The Telegram message for a new version arrives once, and its Update now button works.
- [ ] A release that only changes code restarts in seconds; one that changes `stack/telegram/requirements.txt` rebuilds.
- [ ] Pulling with git by hand, then `homelab update`: it restarts with the new files instead of saying up to date.

## Backups
- [ ] Back up now on the Backups page: a new backup is listed within a minute.
- [ ] A USB drive chosen as the place for copies: the copy lands there.
- [ ] Unplug the drive, back up: the page and Telegram say it is not plugged in. Plug it back in: the copy goes within 5 minutes.
- [ ] Mac: the first copy to a USB drive. If macOS blocks it, the page says how to allow it (Privacy & Security).
- [ ] Lock the copies with a passphrase, then restore a locked copy with `homelab restore <file>.enc`.
- [ ] Restore from the Backups page: the dashboard comes back with the older data, and a before-restore copy exists.
- [ ] A disk over 90% full gives one Telegram alert that day. Stopping the bot container (not with `homelab stop`) gives one alert after 10 minutes.

## Medicines and Money
- [ ] A medicine with reminders on: the Telegram message comes at its time, 5 min and 15 min snooze, Done ticks it.
- [ ] Quiet hours: a reminder inside them arrives without a sound.
- [ ] Pills left: a refill reminder 5 days before they run out.
- [ ] Money: set up, Show, + Spent, and leave the tab: amounts are hidden again. With a settings PIN, Show asks for it.
