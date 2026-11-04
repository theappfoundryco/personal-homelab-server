#!/usr/bin/env bash
# Takes the assistant off this machine so install.sh can be tested from scratch, again and again.
#   dev-reset.sh               remove the assistant (shows the list and asks first)
#   dev-reset.sh --yes         do not ask
#   dev-reset.sh --dry-run     show what would go, change nothing
#   dev-reset.sh --images      also remove the downloaded app images (the next install downloads them again)
#   dev-reset.sh --deep        also remove Docker itself (OrbStack, Colima) so the Docker install path is tested too; implies --images
#   dev-reset.sh --reinstall   run install.sh when done (with --yes --no-open; HL_NAME=Sam skips the name question)
# It only touches this project: its containers, volumes and network (compose project "homelab"), the data folder (HL_HOME, default ~/.homelab),
# the host helper, and the local files install.sh creates (stack/.env, stack/config.yaml, stack/secrets). Your code and other Docker projects stay.
# The repo is found from HL_REPO, else from this file's folder (when it sits in scripts/), else the folder you run it from.
set -u

YES=0 DRY=0 IMAGES=0 DEEP=0 AGAIN=0
for a in "$@"; do
  case "$a" in
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    --images) IMAGES=1 ;;
    --deep) DEEP=1; IMAGES=1 ;;
    --reinstall) AGAIN=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a (try --help)"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${HL_REPO:-}" ]; then REPO="$HL_REPO"
elif [ -f "$HERE/../install.sh" ]; then REPO="$(cd "$HERE/.." && pwd)"
else REPO="$PWD"; fi
[ -f "$REPO/install.sh" ] && [ -f "$REPO/stack/compose.yaml" ] || { echo "  stop  $REPO is not the project folder. Run it from the project folder, or set HL_REPO=/path/to/it"; exit 1; }

HL_HOME="${HL_HOME:-$HOME/.homelab}"
case "$HL_HOME" in ""|/|"$HOME"|"$HOME/") echo "  stop  HL_HOME is '$HL_HOME', which is not a folder that is safe to delete."; exit 1 ;; esac

OS=linux; [ "$(uname -s)" = Darwin ] && OS=mac
UID_NOW="$(id -u)"
PLIST="$HOME/Library/LaunchAgents/homelab.agent.plist"
UNIT="$HOME/.config/systemd/user/homelab-agent.service"
AUTO="$HOME/Library/LaunchAgents/homelab.docker.plist"  # Docker starting at login (homelab autostart on)
# What install.sh and homelab recorded putting on this machine (core/manifest.py); only those are removed, never what you had before
OURS="$(awk '$1 == "brew" {print $2}' "$HL_HOME/installed.txt" 2>/dev/null | tr '\n' ' ')"
OLLAMA_OURS=0; case " $OURS " in *" ollama "*) OLLAMA_OURS=1 ;; esac; [ -e "$HL_HOME/ollama-by-homelab" ] && OLLAMA_OURS=1
LINKED=0; case "$(readlink "$HOME/.local/bin/homelab" 2>/dev/null)" in "$REPO"/*) LINKED=1 ;; esac
STACK="$REPO/stack"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then B=$'\033[1m' D=$'\033[2m' R=$'\033[0m' G=$'\033[32m' Y=$'\033[33m' C=$'\033[36m'; else B= D= R= G= Y= C=; fi
if [ -n "$B" ]; then OKM="${G}✓${R}"; WARNM="${Y}!${R}"; else OKM="ok  "; WARNM="warn"; fi
say() { printf '%s\n' "$*"; }
ok() { printf '  %s  %s\n' "$OKM" "$*"; }
warn() { printf '  %s  %s\n' "$WARNM" "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '  would run: %s\n' "$*"; else "$@" >/dev/null 2>&1; fi; }
have_docker() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

# What is there now
CONT="" VOLS="" NETS="" IMGS=""
if have_docker; then
  CONT="$(docker ps -aq --filter label=com.docker.compose.project=homelab 2>/dev/null)"
  VOLS="$(docker volume ls -q --filter label=com.docker.compose.project=homelab 2>/dev/null)"
  NETS="$(docker network ls -q --filter label=com.docker.compose.project=homelab 2>/dev/null)"
  IMGS="homelab-telegram-bot:local"
  [ "$IMAGES" = 1 ] && IMGS="$IMGS $(grep -E '^[[:space:]]+image:' "$STACK/compose.yaml" | awk '{print $2}' | tr '\n' ' ')"
fi
count() { [ -n "$1" ] && printf '%s\n' "$1" | grep -c . || echo 0; }

row() { printf '  %s%-12s%s %s\n' "$C" "$1" "$R" "$2"; }
printf '%sRemoving the assistant%s %s(%s)%s\n' "$B" "$R" "$D" "$REPO" "$R"
[ -n "$CONT$VOLS$NETS" ] && row "Docker" "$(count "$CONT") containers, $(count "$VOLS") volumes, $(count "$NETS") network$( [ "$IMAGES" = 1 ] && echo ', every app image' || echo ', the local image')"
have_docker || warn "Docker is not running, so containers, volumes and images are skipped"
[ -e "$HL_HOME" ] && row "Data" "$HL_HOME ${D}(settings, journal, backups, passwords)${R}"
FILES=""; for f in "$STACK/.env" "$STACK/config.yaml"; do [ -e "$f" ] && FILES="$FILES ${f#"$REPO"/}"; done
[ -d "$STACK/secrets" ] && [ -n "$(ls -A "$STACK/secrets" 2>/dev/null)" ] && FILES="$FILES stack/secrets/*"
[ -n "$FILES" ] && row "Files" "${FILES# }"
{ [ -e "$PLIST" ] || [ -e "$UNIT" ]; } && row "Host helper" "installed"
[ -e "$AUTO" ] && row "Autostart" "Docker starting at login"
[ "$LINKED" = 1 ] && row "Command" "the homelab command and its PATH line"
[ "$OLLAMA_OURS" = 1 ] && row "AI engine" "Ollama from Homebrew$( [ "$DEEP" = 1 ] && echo ', and its models in ~/.ollama' || echo " ${D}(models in ~/.ollama kept; --deep removes them)${R}")"
[ -n "$OURS" ] && row "Recorded" "installed by homelab with Homebrew: ${OURS% }$( [ "$DEEP" = 1 ] || echo " ${D}(only Ollama goes without --deep)${R}")"
[ "$DEEP" = 1 ] && row "Docker itself" "$( [ "$OS" = mac ] && echo 'OrbStack, Colima, docker from Homebrew, ~/.colima' || echo 'not automatic on Linux (see the end)')"
say "  ${D}Kept: your code, other Docker projects, Docker Desktop${R}"
[ "$DRY" = 1 ] && say "  ${D}(dry run: nothing is changed)${R}"

if [ "$DRY" != 1 ] && [ "$YES" != 1 ]; then
  [ -t 0 ] || { echo "  stop  Not a terminal, so I cannot ask. Use --yes."; exit 1; }
  printf '\nRemove all of this? [y/N] '; read -r r || r=
  case "$r" in y|Y|yes) ;; *) echo "Nothing changed."; exit 0 ;; esac
fi

T0=$SECONDS
# 1. The host helper first, so it does not restart things while they are being removed
if [ "$OS" = mac ]; then
  [ -e "$PLIST" ] && { run launchctl bootout "gui/$UID_NOW/homelab.agent"; run rm -f "$PLIST"; }
else
  [ -e "$UNIT" ] && { run systemctl --user disable --now homelab-agent.service; run rm -f "$UNIT"; run systemctl --user daemon-reload; }
fi

[ -e "$AUTO" ] && run rm -f "$AUTO"
[ "$LINKED" = 1 ] && run env PYTHONPATH="$REPO" python3 -c "import sys; from core import shellpath; shellpath.remove(sys.argv[1], sys.argv[2])" "$REPO" "$HOME"
if [ "$OLLAMA_OURS" = 1 ] && command -v brew >/dev/null 2>&1; then
  run brew services stop ollama
  run brew uninstall ollama
  [ "$DEEP" = 1 ] && [ -d "$HOME/.ollama" ] && run rm -rf "$HOME/.ollama"
fi

# 2. Containers, volumes, network, images
if have_docker; then
  [ -n "$CONT" ] && run docker rm -f $CONT
  [ -n "$VOLS" ] && run docker volume rm $VOLS
  [ -n "$NETS" ] && run docker network rm $NETS
  for i in $IMGS; do run docker rmi "$i"; done
fi

# 3. Files
[ -e "$HL_HOME" ] && run rm -rf "$HL_HOME"
for f in "$STACK/.env" "$STACK/config.yaml"; do [ -e "$f" ] && run rm -f "$f"; done
[ -d "$STACK/secrets" ] && run find "$STACK/secrets" -mindepth 1 -delete

# 4. Docker itself (only with --deep)
if [ "$DEEP" = 1 ]; then
  if [ "$OS" = mac ]; then
    command -v colima >/dev/null 2>&1 && run colima delete -f
    if command -v brew >/dev/null 2>&1; then
      brew list --cask orbstack >/dev/null 2>&1 && run brew uninstall --cask orbstack
      for f in colima docker docker-compose docker-buildx; do brew list --formula "$f" >/dev/null 2>&1 && run brew uninstall "$f"; done
    fi
    for f in docker-compose docker-buildx; do [ -L "$HOME/.docker/cli-plugins/$f" ] && run rm -f "$HOME/.docker/cli-plugins/$f"; done
    [ -d "$HOME/.colima" ] && run rm -rf "$HOME/.colima"
  else
    warn "Docker on Linux is not removed automatically. Remove it with your package manager (apt remove docker-ce docker-ce-cli containerd.io docker-compose-plugin)."
  fi
fi

if [ "$DRY" = 1 ]; then say ""; say "Dry run finished."; exit 0; fi
printf '\n  %s  %sClean%s %s(%ss).%s Start again with %s/install.sh\n' "$OKM" "$B" "$R" "$D" "$((SECONDS - T0))" "$R" "$REPO"
if [ "$AGAIN" = 1 ]; then
  say ""
  cd "$REPO" && exec ./install.sh --yes --no-open
fi
