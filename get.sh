#!/usr/bin/env bash
# One-line install: downloads the project with git (so `homelab update` works later) and runs install.sh.
#   curl -fsSL https://raw.githubusercontent.com/theappfoundryco/personal-homelab-server/main/get.sh | bash
#   ... | bash -s -- --lan          pass options through to install.sh
# Environment: HL_DIR (program folder, default ~/personal-homelab-server), HL_CHANNEL (stable or edge, default stable), HL_REPO (another copy, for testing)
set -eu
REPO="${HL_REPO:-https://github.com/theappfoundryco/personal-homelab-server.git}"
DIR="${HL_DIR:-$HOME/personal-homelab-server}"
CHANNEL="${HL_CHANNEL:-stable}"

say() { printf '  %s\n' "$*"; }
stop() { printf '  stop  %s\n' "$*" >&2; exit 1; }

# git is needed to download and later update. On a Mac it comes with Apple's command line tools.
if ! git --version >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin)
      xcode-select --install >/dev/null 2>&1 || true
      stop "git is needed. A window to install Apple's command line tools has opened. Finish it, then run this command again." ;;
    Linux)
      say "Installing git (needed to download and update the homelab)"
      if command -v apt-get >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq git
      elif command -v dnf >/dev/null; then sudo dnf install -y -q git
      elif command -v pacman >/dev/null; then sudo pacman -S --noconfirm git
      else stop "Install git with your package manager, then run this command again."; fi ;;
    *) stop "This system is not supported yet. It runs on macOS and Linux." ;;
  esac
fi

if [ -d "$DIR/.git" ]; then
  say "Already downloaded in $DIR. Running the installer again (it keeps your settings)."
  say "To get a newer version, use: homelab update"
elif [ -e "$DIR" ]; then
  stop "$DIR already exists and is not this project. Move it, or choose another folder: HL_DIR=~/somewhere"
else
  say "Downloading into $DIR"
  git clone --quiet "$REPO" "$DIR"
  # Stable starts at the newest release so `homelab update` can move forward from it. Edge follows main.
  if [ "$CHANNEL" = edge ]; then
    mkdir -p "${HL_HOME:-$HOME/.homelab}" && echo edge > "${HL_HOME:-$HOME/.homelab}/channel"
  else
    tag="$(git -C "$DIR" tag -l 'v[0-9]*' --sort=-v:refname | grep -v -- - | head -n 1 || true)"
    if [ -n "$tag" ]; then git -C "$DIR" -c advice.detachedHead=false checkout --quiet "$tag"; say "Version $tag"; fi
  fi
fi

cd "$DIR"
# When piped from curl, stdin is the script itself. Give the installer the keyboard so it can ask questions.
if [ ! -t 0 ] && (exec </dev/tty) 2>/dev/null; then exec ./install.sh "$@" < /dev/tty; fi
exec ./install.sh "$@"
