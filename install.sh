#!/usr/bin/env bash
# Sets up the assistant on this machine: checks the system, makes your data folder and settings, starts it, opens the dashboard.
# Safe to run again: it keeps your settings and passwords and only fills in what is missing.
#   ./install.sh            do it
#   ./install.sh --dry-run  show what it would do, change nothing
#   ./install.sh --yes      answer yes to the install offers (Docker), for scripts
#   ./install.sh --no-open  do not open the browser
#   ./install.sh --lan      let phones and laptops on your network open the dashboard (needs a PIN first)
#   ./install.sh --local    back to this machine only
# Environment: HL_HOME (data folder, default ~/.homelab), HL_PORT (dashboard port, default 3095)
set -eu
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK="$HERE/stack"
HL_HOME="${HL_HOME:-$HOME/.homelab}"
HL_PORT="${HL_PORT:-3095}"
MIN_DISK_GB=5     # below this the images cannot be pulled
WARN_DISK_GB=15   # below this a local AI model will not fit
DRY=0 YES=0 OPEN=1 BIND=

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --no-open) OPEN=0 ;;
    --lan) BIND=0.0.0.0 ;;
    --local) BIND=127.0.0.1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a (try --help)"; exit 2 ;;
  esac
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then  # colour only for a person at a terminal, never in logs or pipes
  B=$'\033[1m' D=$'\033[2m' R=$'\033[0m' G=$'\033[32m' Y=$'\033[33m' RD=$'\033[31m' C=$'\033[36m'
else B= D= R= G= Y= RD= C=; fi
LOG="${HL_LOG:-$HL_HOME/install.log}"  # everything the quiet steps print goes here; shown only if a step fails
say()  { printf '%s\n' "$*"; }
sect() { printf '\n%s%s%s\n' "$B$C" "$1" "$R"; }
if [ -n "$B" ]; then OKM="${G}✓${R}    " WARNM="${Y}!${R}    " STOPM="${RD}✗${R}    "; else OKM="ok    " WARNM="warn  " STOPM="stop  "; fi  # symbols with colour, words without
ok()   { printf '  %s%s\n' "$OKM" "$*"; }
warn() { printf '  %s%s\n' "$WARNM" "$*"; }
stop() { printf '  %s%s\n' "$STOPM" "$*"; exit 1; }
step() { # step "doing it" "done" command... : runs a command quietly with a spinner; full output goes to the log, shown only on failure
  local doing="$1" did="$2"; shift 2
  if [ "$DRY" = 1 ]; then printf '  would run: %s\n' "$*"; return 0; fi
  mkdir -p "$(dirname "$LOG")"; printf '\n$ %s\n' "$*" >> "$LOG"
  if [ "${HL_VERBOSE:-0}" = 1 ]; then "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; fi
  "$@" >>"$LOG" 2>&1 </dev/null &  # no input: a hidden prompt must fail, never wait where nobody can see it
  local pid=$! i=0 t0=$SECONDS rc=0 last cols secs room shown frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  if [ -t 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      cols="${COLUMNS:-$(tput cols 2>/dev/null || echo 80)}"; secs="$((SECONDS - t0))"
      [ "$cols" -ge 20 ] 2>/dev/null || cols=80
      shown="$doing"; [ "${#shown}" -gt $((cols - 14)) ] && shown="${doing%% (*}"  # drop a note in brackets first, so a cut never leaves "(" open
      [ "${#shown}" -gt $((cols - 14)) ] && shown="${shown:0:$((cols - 15))}…"
      room=$((cols - ${#shown} - ${#secs} - 10)); last=""  # the whole line must fit in one row, or each frame wraps and stacks
      if [ "$room" -gt 12 ]; then
        last="$(tail -n 3 "$LOG" 2>/dev/null | tr '\r' '\n' | tr -d '\033' | grep . | tail -n 1 | sed -E 's/.*msg="([^"]*)".*/\1/')"; last="${last:0:room}"
      fi
      printf '\r  %s%s%s %s %s(%ss) %s%s\033[K' "$C" "${frames[i % 10]}" "$R" "$shown" "$D" "$secs" "$last" "$R"
      if [ -n "${LIMIT:-}" ] && [ "$secs" -ge "$LIMIT" ]; then kill "$pid" 2>/dev/null; printf '\n(stopped after %ss with no result)\n' "$secs" >> "$LOG"; break; fi
      i=$((i + 1)); sleep 0.2
    done
    printf '\r\033[K'
  else printf '  %s...\n' "$doing"; fi
  wait "$pid" || rc=$?
  if [ "$rc" = 0 ]; then ok "$did $D($((SECONDS - t0))s)$R"
  else
    printf '  %s%s did not work. The last lines it printed:\n' "$STOPM" "$doing"
    tail -n 12 "$LOG" | sed 's/^/        /'
    printf '        Full log: %s\n' "$LOG"
  fi
  return "$rc"
}
do_it() { # run a command, or only show it in a dry run
  if [ "$DRY" = 1 ]; then printf '  would run: %s\n' "$*"; else "$@"; fi
}
ask() { # ask "question" -> 0 if yes. Never yes without a person or --yes.
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  printf '  %s [y/N] ' "$1"; read -r reply || return 1
  [ "$reply" = y ] || [ "$reply" = Y ] || [ "$reply" = yes ]
}
ask_yes() { # ask_yes "question" -> 0 unless they say no. For the extras most people want; Enter means yes.
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  printf '  %s [Y/n] ' "$1"; read -r reply || return 1
  case "$reply" in n|N|no|No|NO) return 1 ;; *) return 0 ;; esac
}
pick_apps() { # pick_apps "catalog lines (id<TAB>name<TAB>MB<TAB>about)" "ticked ids" "locked id" -> PICKED; returns 1 if the screen cannot show a menu
  [ -t 0 ] && [ -t 1 ] && [ -n "$B" ] && [ -z "${HL_PLAIN:-}" ] || return 1
  local rows cols; rows="$(tput lines 2>/dev/null || echo 0)"; cols="$(tput cols 2>/dev/null || echo 0)"
  [ "$rows" -ge 12 ] 2>/dev/null && [ "$cols" -ge 60 ] 2>/dev/null || return 1
  local ids=() names=() mbs=() abouts=() sel=() n=0 id name mb about
  while IFS=$'\t' read -r id name mb about; do
    ids[n]="$id"; names[n]="$name"; mbs[n]="$mb"; abouts[n]="$about"
    case " $2 " in *" $id "*) sel[n]=1 ;; *) sel[n]=0 ;; esac; n=$((n + 1))
  done <<< "$1"
  [ "$n" -gt 0 ] || return 1
  local view=$((rows - 7)); [ "$view" -gt "$n" ] && view="$n"
  local cur=0 top=0 drawn=0 key rest i j tot cnt size mark line old
  old="$(stty -g)"
  restore() { stty "$old" 2>/dev/null; printf '\033[?25h'; }
  trap 'restore; printf "\n"; exit 130' INT TERM
  stty -echo; printf '\033[?25l'
  while :; do
    [ "$cur" -lt "$top" ] && top="$cur"; [ "$cur" -ge $((top + view)) ] && top=$((cur - view + 1))
    [ "$drawn" -gt 0 ] && printf '\033[%dA' "$drawn"
    drawn=0
    for ((j = 0; j < view; j++)); do
      i=$((top + j)); mark="${D}[ ]${R}"; [ "${sel[i]}" = 1 ] && mark="[${G}x${R}]"
      line="${names[i]}"; [ "${ids[i]}" = "$3" ] && { mark="${D}[-]${R}"; line="$line (already running here)"; }
      if [ "$i" = "$cur" ]; then printf '\033[2K  %s›%s %s %s%s%s  %sabout %s MB%s\n' "$C" "$R" "$mark" "$B" "$line" "$R" "$D" "${mbs[i]}" "$R"
      else printf '\033[2K    %s %s  %sabout %s MB%s\n' "$mark" "$line" "$D" "${mbs[i]}" "$R"; fi
      drawn=$((drawn + 1))
    done
    tot=0 cnt=0; for ((i = 0; i < n; i++)); do [ "${sel[i]}" = 1 ] && { tot=$((tot + mbs[i])); cnt=$((cnt + 1)); }; done
    if [ "$tot" -ge 1000 ]; then size="$((tot / 1000)).$(((tot % 1000) / 100)) GB"; else size="$tot MB"; fi
    more=""; [ "$view" -lt "$n" ] && more="  ($((cur + 1)) of $n, more with ↑ ↓)"
    printf '\033[2K      %s%s%s%s\n' "$D" "${abouts[cur]:0:$((cols - 8))}" "$more" "$R"
    if [ "$cnt" = 0 ]; then printf '\033[2K  %sNothing selected%s\n' "$B" "$R"; else printf '\033[2K  %sSelected: %s app%s, about %s%s\n' "$B" "$cnt" "$([ "$cnt" = 1 ] || echo s)" "$size" "$R"; fi
    printf '\033[2K  %s↑ ↓ move   Space select   a all or none   Enter done%s\n' "$D" "$R"
    drawn=$((drawn + 3))
    IFS= read -rsn1 key || break
    case "$key" in
      $'\033') IFS= read -rsn2 rest; case "$rest" in '[A'|'OA') key=up ;; '[B'|'OB') key=down ;; esac ;;
    esac
    case "$key" in
      up|k) [ "$cur" -gt 0 ] && cur=$((cur - 1)) ;;
      down|j) [ "$cur" -lt $((n - 1)) ] && cur=$((cur + 1)) ;;
      ' '|x) [ "${ids[cur]}" != "$3" ] && sel[cur]=$((1 - sel[cur])) ;;
      a|A) j=1; for ((i = 0; i < n; i++)); do [ "${sel[i]}" = 1 ] && j=0; done
           for ((i = 0; i < n; i++)); do [ "${ids[i]}" != "$3" ] && sel[i]=$j; done ;;
      '') break ;;
    esac
  done
  restore; trap - INT TERM; unset -f restore
  PICKED=""; for ((i = 0; i < n; i++)); do [ "${sel[i]}" = 1 ] && PICKED="$PICKED ${ids[i]}"; done
  PICKED="${PICKED# }"; return 0
}
banner() { # the name in big letters, only for a person at a terminal wide enough to show it
  [ -t 1 ] && [ -n "$B" ] || return 0
  [ -n "${HL_NO_CLEAR:-}" ] || printf '\033[H\033[2J'  # clears the screen but keeps scrollback, so earlier output is one scroll away
  [ "${COLUMNS:-$(tput cols 2>/dev/null || echo 80)}" -ge 66 ] 2>/dev/null || return 0
  local shades=(223 217 216 210 204 168) i=0 ver line  # warm sand to rose, easy on the eyes
  [ "$(tput colors 2>/dev/null || echo 8)" -ge 256 ] 2>/dev/null || shades=(36 36 36 36 36 36)
  printf '\n'
  while IFS= read -r line; do
    if [ "${shades[0]}" = 36 ]; then printf '  \033[36m%s\033[0m\n' "$line"; else printf '  \033[38;5;%sm%s\033[0m\n' "${shades[i]}" "$line"; fi
    i=$((i + 1))
  done <<'ART'
██╗  ██╗ ██████╗ ███╗   ███╗███████╗██╗      █████╗ ██████╗
██║  ██║██╔═══██╗████╗ ████║██╔════╝██║     ██╔══██╗██╔══██╗
███████║██║   ██║██╔████╔██║█████╗  ██║     ███████║██████╔╝
██╔══██║██║   ██║██║╚██╔╝██║██╔══╝  ██║     ██╔══██║██╔══██╗
██║  ██║╚██████╔╝██║ ╚═╝ ██║███████╗███████╗██║  ██║██████╔╝
╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝
ART
  ver="$(git -C "$HERE" describe --tags --abbrev=0 2>/dev/null || true)"
  printf '  %sYour own assistant, dashboard and apps, on your own machine.%s %s%s%s\n' "$D" "$R" "$D" "${ver:+v${ver#v}}" "$R"
  printf '  %s© %s TheAppFoundryCo  ·  theappfoundry.co/homelab%s\n' "$D" "$(date +%Y)" "$R"
  printf '  %sPrivacy: theappfoundry.co/homelab/privacy  ·  Terms: theappfoundry.co/homelab/terms%s\n' "$D" "$R"
  printf '  %s%s%s\n\n' "$D" "────────────────────────────────────────────────────────────" "$R"
}
rec() { # rec kind value: notes something put on this machine outside the folder, so uninstall removes exactly that (core/manifest.py)
  [ "$DRY" = 1 ] && return 0; mkdir -p "$HL_HOME"; grep -qx "$1 $2" "$HL_HOME/installed.txt" 2>/dev/null || printf '%s %s\n' "$1" "$2" >> "$HL_HOME/installed.txt"
}
brew_new() { local f; for f in "$@"; do brew list --formula "$f" >/dev/null 2>&1 || printf '%s ' "$f"; done; } # the ones not installed yet
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true; }

main() {  # everything runs inside a function so bash reads the whole file first; editing install.sh while it runs cannot break that run
banner
printf '%sSetting up the assistant%s %s(%s)%s\n' "$B" "$R" "$D" "$HERE" "$R"
[ -f "$STACK/compose.yaml" ] || stop "Run install.sh from inside the downloaded folder (stack/compose.yaml is missing next to it)."

# 1. Which system is this
sect "Checking this machine"
case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) if uname -r | grep -qi microsoft; then OS=wsl; else OS=linux; fi ;;
  *) stop "This system ($(uname -s)) is not supported. Linux and macOS work today." ;;
esac
[ "$OS" = wsl ] && stop "Windows (WSL2) is not supported yet. Linux and macOS work today."
ok "$OS, $(uname -m)"

# 2. Docker: installed, new enough, running. Everything here runs from the terminal; no app has to be opened.
wait_docker() { # wait_docker seconds -> 0 once Docker answers
  local i=0; while [ "$i" -lt "$1" ]; do docker info >/dev/null 2>&1 && return 0; sleep 2; i=$((i + 2)); done; return 1
}
mac_memory_gb() { echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1073741824 )); }
install_docker_mac() { # Colima is Docker without an app: a small background VM driven by the terminal
  if ! command -v brew >/dev/null 2>&1; then
    say "        Installing Homebrew first (the Mac package manager Docker comes from). It may ask for your Mac password."
    do_it env NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || return 1
    rec homebrew yes
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
  fi
  local new; new="$(brew_new colima docker docker-compose docker-buildx)"
  step "Installing Docker (Colima)" "Docker installed" env -u HOMEBREW_ASK brew install colima docker docker-compose docker-buildx || return 1
  for f in $new; do rec brew "$f"; done
  link_plugins
}
link_plugins() { # Docker finds its plugins in ~/.docker/cli-plugins
  [ "$DRY" = 1 ] && return 0
  mkdir -p "$HOME/.docker/cli-plugins"
  for pl in docker-compose docker-buildx; do
    if [ -x "$(brew --prefix)/opt/$pl/bin/$pl" ]; then [ -e "$HOME/.docker/cli-plugins/$pl" ] || rec plugin-link "$HOME/.docker/cli-plugins/$pl"; ln -sfn "$(brew --prefix)/opt/$pl/bin/$pl" "$HOME/.docker/cli-plugins/$pl"; fi
  done
  return 0
}
start_docker_mac() { # starts whichever Docker this Mac has, from the terminal
  if ! command -v orbctl >/dev/null 2>&1 && ! command -v colima >/dev/null 2>&1 && [ ! -d /Applications/Docker.app ]; then  # a leftover docker command with nothing behind it would otherwise wait in silence
    say "        There is a Docker command, but nothing to run it (no Docker Desktop, OrbStack or Colima). Installing Colima, a light one with no app to open."
    install_docker_mac || return 1
  fi
  if command -v orbctl >/dev/null 2>&1; then step "Starting Docker" "Docker started" orbctl start
  elif command -v colima >/dev/null 2>&1; then
    mem=$(( $(mac_memory_gb) / 2 )); [ "$mem" -gt 6 ] && mem=6; [ "$mem" -lt 2 ] && mem=2
    if [ -d "$HOME/.colima/default" ]; then say "        Docker (Colima) is starting. This takes under a minute."
    else say "        Docker (Colima) is starting for the first time. It downloads a small Linux system (about 300 MB), so 2 to 5 minutes is normal."; fi
    LIMIT=600 step "Starting Docker" "Docker started" colima start --cpu 4 --memory "$mem" --disk 60 || {
      say "        If it stays stuck, run: colima stop --force && colima start   then run install.sh again."; return 1; }
    [ "$DRY" = 1 ] || docker context use colima >/dev/null 2>&1 || true  # another Docker installed earlier can leave the terminal pointed at it
  elif [ -d /Applications/Docker.app ]; then do_it open -a Docker
    [ "$DRY" = 1 ] || step "Waiting for Docker Desktop to start" "Docker started" wait_docker 180; return
  fi
  [ "$DRY" = 1 ] || wait_docker 120
}
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker is not installed. It runs the assistant and its apps."
  if [ "$OS" = mac ]; then
    say "        Installing Colima (a light Docker with no app to open) with Homebrew."
    install_docker_mac || stop "Could not install Docker. Install it yourself (brew install colima docker docker-compose), then run install.sh again."
  else
    say "        Installing it with Docker's own installer for Linux (get.docker.com). It asks for your password."
    if command -v curl >/dev/null 2>&1; then
      do_it sh -c 'curl -fsSL https://get.docker.com | sudo sh' || stop "Docker's installer failed. See the messages above."
      rec docker-linux yes
      do_it sudo systemctl enable --now docker
      do_it sudo usermod -aG docker "${USER:-$(id -un)}"
    else
      say "        curl is missing, so Docker can't be downloaded. Install Docker yourself, then run install.sh again."
      [ "$DRY" = 1 ] && say "  (dry run: the checks below need Docker, so it stops here)" && exit 0
      exit 1
    fi
  fi
  [ "$DRY" = 1 ] && say "  (dry run: the checks below need Docker, so it stops here)" && exit 0
fi
docker compose version >/dev/null 2>&1 || stop "Docker is installed but not its 'compose' part. Update Docker, or install the docker-compose-plugin package."
if ! docker info >/dev/null 2>&1; then
  if [ "$OS" = mac ]; then
    start_docker_mac || stop "Docker did not start. Try: colima start   (or orbctl start, or open Docker Desktop), then run install.sh again."
  elif [ "${HL_REEXEC:-}" != 1 ] && command -v sg >/dev/null 2>&1 && docker info 2>&1 | grep -qi "permission denied"; then
    say "  Your user was just added to the docker group; continuing with it"
    HL_REEXEC=1 exec sg docker -c "$(printf '%q ' "$0" "$@")"
  else stop "Docker is installed but not running or not allowed for your user. Try: sudo systemctl start docker, and sudo usermod -aG docker \$USER (then log out and in)."; fi
fi
ok "Docker is running"
if [ "$OS" = mac ] && ! docker buildx version >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then  # without it Docker falls back to a slow old builder and warns
  BX="$(brew_new docker-buildx)"; step "Adding Docker's build tool" "Build tool added" env -u HOMEBREW_ASK brew install docker-buildx && { [ -z "$BX" ] || rec brew docker-buildx; link_plugins; }
fi

# 3. Disk space where the data goes
WHERE="$HL_HOME"; while [ ! -d "$WHERE" ] && [ "$WHERE" != / ]; do WHERE="$(dirname "$WHERE")"; done  # the nearest folder that exists
FREE_GB="$(df -Pk "$WHERE" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')"
if [ -z "$FREE_GB" ]; then warn "Could not read free disk space. Carrying on."
elif [ "$FREE_GB" -lt "$MIN_DISK_GB" ]; then stop "Only $FREE_GB GB free in $HL_HOME. The apps need about $MIN_DISK_GB GB. Free some space or set HL_HOME to a bigger drive."
elif [ "$FREE_GB" -lt "$WARN_DISK_GB" ]; then warn "$FREE_GB GB free. Enough to start, but a local AI model needs 3 to 20 GB more."
else ok "$FREE_GB GB free"; fi

# 4. The dashboard's port
ours() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx landing; }
busy() {
  if command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; fi
}
if busy "$HL_PORT" && ! ours; then
  stop "Port $HL_PORT is used by something else. Pick another one: HL_PORT=3100 ./install.sh"
fi
ok "port $HL_PORT is available"

# 5. Your data folder and settings (kept if they exist)
sect "Setting up"
DATA="$HL_HOME/data"
for d in "$DATA" "$HL_HOME/stats" "$STACK/secrets"; do [ "$DRY" = 1 ] || mkdir -p "$d"; done
ok "data folder $DATA"
if [ -f "$STACK/config.yaml" ]; then ok "config.yaml kept"
else [ "$DRY" = 1 ] || cp "$STACK/config.example.yaml" "$STACK/config.yaml"; ok "config.yaml created from the example"; NEWCFG=1; fi

tz() { # the IANA zone name, if we can tell
  local z=""
  if [ -r /etc/timezone ]; then z="$(cat /etc/timezone)"
  else z="$(readlink /etc/localtime 2>/dev/null | sed -n 's#.*/zoneinfo/##p')"; fi
  printf '%s' "${z:-UTC}"
}
# Your name and time zone go into config.yaml the first time only. HL_NAME skips the question (for scripts).
if [ "${NEWCFG:-0}" = 1 ] && [ "$DRY" != 1 ]; then
  NAME="${HL_NAME:-}"
  if [ -z "$NAME" ] && [ "$YES" != 1 ] && [ -t 0 ]; then printf '  What should I call you? (Enter to skip) '; read -r NAME || NAME=; fi
  NAME="$(printf '%s' "$NAME" | tr -d '"\\\n')"; NAME="${NAME:0:40}"
  ZONE="$(tz)"
  awk -v n="$NAME" -v z="$ZONE" '
    !dn && n != "" && /^  name: "/ { print "  name: \"" n "\"                # how the dashboard and bot greet you"; dn = 1; next }
    !dz && z != "" && /^timezone: "/ { print "timezone: \"" z "\"               # your IANA time zone, e.g. \"Europe/London\" or \"America/New_York\""; dz = 1; next }
    { print }' "$STACK/config.yaml" > "$STACK/config.yaml.new" && mv "$STACK/config.yaml.new" "$STACK/config.yaml"
  [ -n "$NAME" ] && ok "Hello, $NAME" || say "        No name given. You can set it in the setup wizard or Settings."
  ok "time zone $ZONE"
fi
# The last question, asked now so nothing waits for you once the long part starts.
HELPER=0
if [ -e "$HOME/Library/LaunchAgents/homelab.agent.plist" ] || [ -e "$HOME/.config/systemd/user/homelab-agent.service" ]; then ok "host helper already installed"
elif [ "$DRY" != 1 ] && [ -z "${HL_NO_HELPER:-}" ]; then
  HELPER=1  # needed for the dashboard's Restart, Update, Apps and live numbers, so it is installed without asking
  say "  ${D}The host helper will be installed: a small background service, running as you, behind the dashboard's Restart, Update and Apps buttons and its live numbers. It can only touch this project's apps. Remove it with: homelab agent uninstall${R}"
fi
# After a restart: Colima only comes back if something starts it. The other Docker apps have their own switch.
AUTOSTART=0
if [ "$OS" = mac ] && [ "$DRY" != 1 ]; then
  case "$(docker context show 2>/dev/null)" in
    colima*) if [ -e "$HOME/Library/LaunchAgents/homelab.docker.plist" ]; then ok "Docker starts by itself after a restart"
             else AUTOSTART=1  # a home server has to come back after a restart, so this is not a question
               say "  ${D}Docker will start by itself after the Mac restarts, so the assistant is always back. Turn it off with: homelab autostart off${R}"; fi ;;
    orbstack) say "  ${D}To have it back after a restart: OrbStack, Settings, General, Start at login.${R}" ;;
    desktop-linux) say "  ${D}To have it back after a restart: Docker Desktop, Settings, General, Start Docker Desktop when you sign in.${R}" ;;
  esac
fi
# The homelab command from any folder: a link in ~/.local/bin, and that folder on the PATH if it is not yet
ADDPATH=0 CMD="$HERE/bin/homelab" PFORCE=""
PST="$("$HERE/bin/homelab" path status 2>/dev/null | head -n 1 || true)"; PWHY="$(printf '%s' "$PST" | sed -E 's/^ *[a-z_]+ +//')"; PST="$(printf '%s' "$PST" | awk '{print $1}')"
case "$PST" in
  ready) ok "homelab command already in your terminal, skipping"; CMD=homelab ;;
  clash) warn "Skipping the homelab command: $PWHY Use $HERE/bin/homelab instead." ;;
  *) if [ "$DRY" != 1 ] && [ -z "${HL_NO_PATH:-}" ]; then
       case "$PST" in
         needs_line) say "  ${D}The homelab command is linked, but new terminals do not find it yet. This adds one line to your shell's startup file.${R}" ;;
         stale) say "  ${D}The homelab command points at a download that is gone. This points it here.${R}" ;;
         other) say "  ${D}The homelab command runs another download of this project ($PWHY). Yes points it at this folder.${R}"; PFORCE=--force ;;
         *) say "  ${D}Lets you type homelab status, homelab update and so on from any folder, instead of $HERE/bin/homelab.${R}" ;;
       esac
       if ask_yes "$([ "$PST" = other ] && echo 'Point the homelab command here?' || echo 'Add the homelab command to your terminal?')"; then ADDPATH=1; else say "        Skipped. Add it any time with: $HERE/bin/homelab path add"; fi
     fi ;;
esac
# Phones and laptops at home. Only with a PIN, because the dashboard holds your journal and budget. Asked now, set after the .env exists.
LANPIN=""
if [ -z "$BIND" ] && [ "$DRY" != 1 ] && [ "$YES" != 1 ] && [ -t 0 ] && ! grep -q '^HL_BIND=0.0.0.0' "$STACK/.env" 2>/dev/null \
   && PYTHONPATH="$HERE" python3 -W ignore -c 'import yaml' >/dev/null 2>&1; then
  say "  ${D}Phones and laptops on your home network can open the dashboard too. Changing settings then needs a PIN.${R}"
  if ask "Open it to your home network?"; then
    while :; do
      printf '  Choose a PIN (4 to 12 digits, hidden as you type): '; read -rs LANPIN || LANPIN=""; echo
      case "$LANPIN" in ""|*[!0-9]*) ;; *) [ "${#LANPIN}" -ge 4 ] && [ "${#LANPIN}" -le 12 ] && break ;; esac
      [ -z "$LANPIN" ] && break
      say "        Use 4 to 12 digits (or press Enter to skip)."
    done
    if [ -n "$LANPIN" ]; then BIND=0.0.0.0; else say "        Skipped. You can do it later in the setup wizard's Access step."; fi
  fi
fi
# Which optional apps run. The dashboard and the assistant always do; everything else is your choice (change it later in Settings, Apps).
HOST_OLLAMA=0
if [ "$DRY" != 1 ] && tags="$(curl -fs -m 2 http://127.0.0.1:11434/api/tags 2>/dev/null)" && printf '%s' "$tags" | grep -q '"models"'; then
  HOST_OLLAMA=1; n="$(printf '%s' "$tags" | grep -o '"name"' | wc -l | tr -d ' ')"
  ok "found Ollama already running here, with $n model(s). The assistant will use it."
  grep -q '^ollama:' "$STACK/config.yaml" || printf '\nollama:\n  url: "http://host.docker.internal:11434"   # the Ollama already running on this machine (found by install.sh)\n' >> "$STACK/config.yaml"
fi
APPS_PY="from core import apps"
if [ -f "$DATA/apps.json" ]; then ok "apps kept: $(PYTHONPATH="$HERE" python3 -c "$APPS_PY; print(', '.join(apps.chosen('$DATA')) or 'none')" 2>/dev/null || echo 'as before')"
elif [ "$DRY" != 1 ]; then
  CHOSEN="${HL_APPS-}"
  if [ -z "${HL_APPS+x}" ] && [ "$YES" != 1 ] && [ -t 0 ] && command -v python3 >/dev/null 2>&1; then
    if [ "$OS" = mac ]; then MEMGB="$(mac_memory_gb)"; else MEMGB=$(( $(awk '/^MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0) / 1048576 )); fi
    SUGGEST=""; [ "$HOST_OLLAMA" = 0 ] && [ "${MEMGB:-0}" -ge 8 ] && SUGGEST="ollama"
    say "  ${D}Pick the extra apps you want. You can add or remove them any time in Settings, Apps.${R}"
    LOCKED=""; [ "$HOST_OLLAMA" = 1 ] && LOCKED=ollama
    CAT="$(PYTHONPATH="$HERE" python3 -c "$APPS_PY
for a, v in apps.CATALOG.items(): print(a, 'Local AI engine (Ollama, on this Mac with its GPU)' if a == 'ollama' and '$OS' == 'mac' and $( command -v brew >/dev/null 2>&1 && echo True || echo False ) else v[0], v[3], v[1], sep='\t')")"
    if pick_apps "$CAT" "$SUGGEST" "$LOCKED"; then
      CHOSEN="$PICKED"
      case " $CHOSEN " in *" adguard "*) ask_yes "AdGuard Home needs port 53 and suits a machine that is always on. Keep it?" || CHOSEN="$(printf '%s' "$CHOSEN" | tr ' ' '\n' | grep -vx adguard | tr '\n' ' ')" ;; esac
    else  # no room for a menu (pipe, small window or HL_PLAIN=1): pick by number
      IDS="$(PYTHONPATH="$HERE" python3 -c "$APPS_PY; print(' '.join(apps.CATALOG))")"
      PYTHONPATH="$HERE" python3 -c "
$APPS_PY
for i, (a, v) in enumerate(apps.CATALOG.items(), 1):
    note = ' (already running here, not needed)' if a == 'ollama' and $HOST_OLLAMA else (' (suggested)' if a == '$SUGGEST' else '')
    print(f'   {i:>2}  {v[0]}, about {v[3]} MB{note}')
    print(f'       {v[1]}')"
      printf '  Numbers to add, with spaces between (Enter for %s, 0 for none): ' "${SUGGEST:-none}"; read -r picks || picks=; picks="${picks//,/ }"
      if [ -z "$picks" ]; then CHOSEN="$SUGGEST"
      else CHOSEN=""; for p in $picks; do id="$(printf '%s\n' $IDS | sed -n "${p}p" 2>/dev/null)"; [ -n "$id" ] && CHOSEN="$CHOSEN $id"; done; fi
    fi
    [ "$HOST_OLLAMA" = 1 ] && CHOSEN="$(printf '%s' "$CHOSEN" | tr ' ' '\n' | grep -vx ollama | tr '\n' ' ')"  # the port is taken by the one already running
  fi
  # On a Mac the AI engine runs on the Mac itself (Homebrew), where it gets the Apple GPU; Docker would give it the CPU only. Set up after the apps start.
  NATIVE_AI=0
  if [ "$OS" = mac ] && [ -z "${HL_OLLAMA_DOCKER:-}" ] && command -v brew >/dev/null 2>&1 && printf ' %s ' $CHOSEN | grep -q ' ollama '; then
    NATIVE_AI=1; CHOSEN="$(printf '%s' "$CHOSEN" | tr ' ' '\n' | grep -vx ollama | tr '\n' ' ' || true)"
  fi
  NATIVE_JSON=""
  if [ "$HOST_OLLAMA" = 1 ]; then NATIVE_JSON=', "native": ["ollama"]'; CHOSEN="ollama $CHOSEN"; fi  # the one already running here counts as chosen, outside Docker
  mkdir -p "$DATA"
  printf '{"apps": [%s]%s}\n' "$(for a in $CHOSEN; do printf '"%s",' "$a"; done | sed 's/,$//')" "$NATIVE_JSON" > "$DATA/apps.json"
  CHOSEN="$(printf '%s' "$CHOSEN" | tr ' ' '\n' | grep -vx ollama | tr '\n' ' ' || true)"
  if [ "$NATIVE_AI" = 1 ]; then CHOSEN="ollama $CHOSEN"; fi  # for the line below
  [ -n "${CHOSEN// /}" ] && ok "apps: $(echo $CHOSEN)" || ok "no extra apps for now (add them in Settings, Apps)"
fi
if [ -f "$STACK/.env" ]; then
  ok ".env kept"
elif [ "$DRY" = 1 ]; then
  say "  would run: create $STACK/.env with new passwords, timezone $(tz) and your data folder"
else
  : > "$STACK/.env"; chmod 600 "$STACK/.env"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      TG_TOKEN=*|TG_CHAT=*) line="${line%%=*}=" ;;
      HL_TIMEZONE=*) line="HL_TIMEZONE=$(tz)" ;;
      *=change-me*) line="${line%%=*}=$(rand)" ;;
    esac
    printf '%s\n' "$line" >> "$STACK/.env"
  done < "$STACK/.env.example"
  { printf '\nHL_DATA_DIR=%s\nHL_STATS_DIR=%s\nHL_PORT=%s\n' "$DATA" "$HL_HOME/stats" "$HL_PORT"; } >> "$STACK/.env"
  ok ".env created with new passwords (only you have them)"
fi

# Who can reach the dashboard. Opening it to the network is only done with a PIN set, because it holds your journal and budget.
if [ -n "$LANPIN" ]; then  # the PIN goes in through stdin, never on a command line where other users could see it
  printf '%s' "$LANPIN" | PYTHONPATH="$HERE" python3 -W ignore -c 'import sys; from core import config, settings; settings.Settings(sys.argv[1], config.Config({}), log=lambda m: None).set_pin(sys.stdin.read().strip())' "$DATA" \
    && ok "PIN set" || warn "Could not save the PIN. Set it in the setup wizard's Access step."
  LANPIN=""
fi
if [ -n "$BIND" ]; then
  if [ "$BIND" = 0.0.0.0 ] && ! grep -q '"_pin"' "$DATA/settings.json" 2>/dev/null; then
    stop "Set a PIN first: open the dashboard, Settings, Security (or the setup wizard's Access step). Then run ./install.sh --lan again."
  fi
  if [ "$DRY" = 1 ]; then say "  would run: set HL_BIND=$BIND in $STACK/.env"
  else
    grep -v '^HL_BIND=' "$STACK/.env" > "$STACK/.env.new" || true
    printf 'HL_BIND=%s\n' "$BIND" >> "$STACK/.env.new"; mv "$STACK/.env.new" "$STACK/.env"; chmod 600 "$STACK/.env"
    ok "dashboard reachable from: $([ "$BIND" = 0.0.0.0 ] && echo 'your network (PIN required for changes)' || echo 'this machine only')"
  fi
fi

# 6. What this machine can run
say ""
if command -v python3 >/dev/null 2>&1 && PYTHONPATH="$HERE" python3 -W ignore -c 'import yaml' >/dev/null 2>&1; then
  PYTHONPATH="$HERE" python3 -W ignore -m core hardware $([ "$DRY" = 1 ] || echo "--save $DATA") 2>/dev/null | sed -n '1,2p' | sed 's/^/  /' || warn "Could not read the hardware."
else
  warn "Python 3 with PyYAML is not here, so the hardware check is skipped. The setup can still run without it."
fi

# 7. Start
sect "Starting"
cd "$STACK"
SERVICES="$(PYTHONPATH="$HERE" python3 -c "from core import apps; print(' '.join(apps.services(apps.chosen('$DATA'), apps.native('$DATA'))))" 2>/dev/null || echo landing telegram-bot docker-proxy)"
step "Downloading and building the apps (the first time takes a few minutes)" "Apps started" env BUILDKIT_PROGRESS=plain COMPOSE_PROGRESS=plain docker compose up -d --build $SERVICES || stop "The apps did not start. Fix the problem above, then run install.sh again (it is safe to repeat)."
if [ "$DRY" = 1 ]; then sect "Dry run done. Nothing was changed."; exit 0; fi
if [ "${NATIVE_AI:-0}" = 1 ]; then
  step "Setting up the AI engine on this Mac (it uses the Apple GPU)" "AI engine running on this Mac" "$HERE/bin/homelab" apps add ollama \
    || warn "Could not set it up on the Mac. Add it later in Settings, Apps, or run: homelab apps add ollama"
  docker restart telegram-bot >/dev/null 2>&1 || true  # the assistant reads the new AI address when it starts
fi

URL="http://localhost:$HL_PORT"
wait_dashboard() { local n=0; while [ "$n" -lt 60 ]; do curl -fs "$URL/api/bot/doctor" >/dev/null 2>&1 && return 0; sleep 2; n=$((n + 1)); done; return 1; }
step "Waiting for the dashboard" "Dashboard is up" wait_dashboard || stop "It did not come up in two minutes. See why with: cd $STACK && docker compose logs telegram-bot"

if [ "$HELPER" = 1 ]; then
  step "Installing the host helper" "Host helper installed" "$HERE/bin/homelab" agent install || warn "Could not install it. Try later with: $HERE/bin/homelab agent install"
  [ "$OS" = linux ] && say "        ${D}To keep it running when you are logged out: sudo loginctl enable-linger \$USER${R}"
fi

if [ "$AUTOSTART" = 1 ]; then
  if out="$("$HERE/bin/homelab" autostart on 2>&1)"; then ok "$(printf '%s' "$out" | sed -E 's/^ *ok +//')"
  else warn "$(printf '%s' "$out" | sed -E 's/^ *(warn|stop) +//')"; fi
fi
if [ "$ADDPATH" = 1 ]; then
  if out="$("$HERE/bin/homelab" path add $PFORCE 2>&1)"; then CMD=homelab; ok "$(printf '%s' "$out" | sed -E 's/^ *ok +//')"
  else warn "$(printf '%s' "$out" | sed -E 's/^ *(warn|stop) +//')"; fi
fi

[ "$DRY" = 1 ] || printf '%s\n' "$CMD" > "$DATA/cli.txt" 2>/dev/null || true  # the dashboard writes commands the way this terminal runs them
printf '\n  %s%sReady.%s Your dashboard is at %s%s%s\n' "$B" "$G" "$R" "$B" "$URL" "$R"
if [ "$BIND" = 0.0.0.0 ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"; [ -n "$IP" ] || IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  [ -n "$IP" ] && say "  From your phone on the same network: http://$IP:$HL_PORT"
fi
say "  ${D}Telegram is not connected yet. The setup wizard in the dashboard walks you through it.${R}"
say "  ${D}Look after it with${R} $CMD status  ${D}(also: update, backup, modules, logs, help)${R}"
# Last, so nothing is left to answer in the terminal once the browser takes over
if [ "$OPEN" = 1 ]; then
  say "  ${D}Opening it in your browser...${R}"
  if [ "$OS" = mac ]; then open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then xdg-open "$URL" >/dev/null 2>&1 || true; fi
fi
}
main "$@"; exit $?  # one line, so bash never reads past it even if the file is edited during a run
