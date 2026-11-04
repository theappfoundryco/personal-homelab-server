# Homelab shell kit. Sourced from /etc/bash.bashrc for every interactive login.
# Edit /etc/homelab/homelab.sh, then run `hlreload`.

[[ $- != *i* ]] && return

HL_DIR=/opt/homelab
HL_HOST=$(hostname)

_R=$'\033[0m'; _B=$'\033[1m'; _D=$'\033[2m'
_RED=$'\033[31m'; _GRN=$'\033[32m'; _YLW=$'\033[33m'; _BLU=$'\033[38;5;39m'
_MAG=$'\033[38;5;213m'; _CYN=$'\033[36m'; _GRY=$'\033[38;5;244m'

_sudo() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

# Colored header with a rule under it
_hdr() {
  printf "\n${_B}${_BLU}%s${_R}\n" "$1"
  printf "${_GRY}%s${_R}\n" "$(_rep ─ ${2:-44})"
}

# Label/value row
_row() { printf "  ${_GRY}%-16s${_R} %s\n" "$1" "$2"; }

# Pick a color by thresholds: _lvl value warn crit
_lvl() {
  local v=${1%.*}
  if (( v >= $3 )); then printf "%s" "$_RED"; elif (( v >= $2 )); then printf "%s" "$_YLW"; else printf "%s" "$_GRN"; fi
}

# Repeat a string n times: _rep "█" 5
_rep() { local s="" i; for (( i = 0; i < $2; i++ )); do s+=$1; done; printf "%s" "$s"; }

# Progress bar: _bar percent [width] [warn] [crit]
_bar() {
  local p=${1%.*} w=${2:-24} warn=${3:-60} crit=${4:-85} c fill
  (( p > 100 )) && p=100; (( p < 0 )) && p=0
  c=$(_lvl "$p" "$warn" "$crit")
  fill=$(( p * w / 100 ))
  printf "%s%s${_GRY}%s${_R} %s%3d%%${_R}" "$c" "$(_rep █ $fill)" "$(_rep ░ $(( w - fill )))" "$c" "$p"
}

_signoff() {
  local -a lines=("All systems nominal 🛰️" "Purring like a cat 🐈" "Shipshape 🛟" "Looking crisp ✨" "Carry on 🦾" "Green across the board 🟢")
  printf "\n  ${_D}%s${_R}\n\n" "${lines[RANDOM % ${#lines[@]}]}"
}

# ─── Hardware ────────────────────────────────────────────────────────────────

cpuinfo() {
  local model cores threads mhz max load1 load5 load15 temp
  model=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo | sed 's/(R)//g; s/(TM)//g; s/ CPU//')
  cores=$(lscpu | awk -F: '/^Core\(s\) per socket/{gsub(/ /,"",$2); print $2}')
  threads=$(nproc)
  mhz=$(awk -F': ' '/cpu MHz/{s+=$2; n++} END{printf "%.0f", s/n}' /proc/cpuinfo)
  max=$(lscpu | awk -F: '/CPU max MHz/{gsub(/ /,"",$2); printf "%.0f", $2}')
  read -r load1 load5 load15 _ < /proc/loadavg
  temp=$(cat /sys/class/thermal/thermal_zone*/type 2>/dev/null | paste - <(cat /sys/class/thermal/thermal_zone*/temp) | awk '$1=="x86_pkg_temp"{printf "%.0f", $2/1000}')

  _hdr "CPU  ${_R}${_D}${model}"
  _row "Cores/threads" "${_B}${cores}${_R} / ${_B}${threads}${_R}"
  _row "Clock" "${_B}${mhz}${_R} MHz avg  ${_D}(max ${max})${_R}"
  _row "Load 1/5/15" "$(_lvl "${load1%.*}" 4 7)${load1}${_R}  ${load5}  ${load15}  ${_D}(of ${threads})${_R}"
  [[ -n $temp ]] && _row "Package temp" "$(_lvl "$temp" 60 80)${temp}°C${_R}"

  # Per-core usage sampled over half a second
  local -a a b
  mapfile -t a < <(awk '/^cpu[0-9]/{print $2+$3+$4+$7+$8, $5+$6}' /proc/stat)
  sleep 0.5
  mapfile -t b < <(awk '/^cpu[0-9]/{print $2+$3+$4+$7+$8, $5+$6}' /proc/stat)
  printf "\n"
  local i u1 i1 u2 i2 pct
  for i in "${!a[@]}"; do
    read -r u1 i1 <<<"${a[i]}"; read -r u2 i2 <<<"${b[i]}"
    pct=$(( ( (u2-u1) * 100 ) / ( (u2-u1) + (i2-i1) + 1 ) ))
    printf "  ${_GRY}core %-2d${_R} %s" "$i" "$(_bar "$pct" 20)"
    (( i % 2 )) && printf "\n" || printf "    "
  done
  (( ${#a[@]} % 2 )) && printf "\n"
  _signoff
}

raminfo() {
  local total avail used swapt swapf pct
  total=$(awk '/MemTotal/{print $2}' /proc/meminfo); avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  swapt=$(awk '/SwapTotal/{print $2}' /proc/meminfo); swapf=$(awk '/SwapFree/{print $2}' /proc/meminfo)
  used=$(( total - avail )); pct=$(( used * 100 / total ))
  _hdr "Memory"
  _row "RAM" "$(_bar $pct 28 75 90)  ${_D}$(numfmt --to=iec $((used*1024))) of $(numfmt --to=iec $((total*1024)))${_R}"
  if (( swapt > 0 )); then
    _row "Swap" "$(_bar $(( (swapt-swapf) * 100 / swapt )) 28 30 70)  ${_D}$(numfmt --to=iec $(((swapt-swapf)*1024))) of $(numfmt --to=iec $((swapt*1024)))${_R}"
  fi
  printf "\n  ${_B}Top 5 by memory${_R}\n"
  ps -eo rss=,comm= --sort=-rss | head -5 | while read -r rss cmd; do
    printf "  ${_MAG}%8s${_R}  %s\n" "$(numfmt --to=iec $((rss*1024)))" "$cmd"
  done
  _signoff
}

diskinfo() {
  _hdr "Disks"
  df -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs --output=target,size,used,pcent | tail -n +2 |
  while read -r mnt size used pct; do
    _row "$mnt" "$(_bar "${pct%\%}" 28 75 90)  ${_D}$(numfmt --to=iec "$used") of $(numfmt --to=iec "$size")${_R}"
  done
  printf "\n  ${_B}Biggest Docker volumes${_R}\n"
  _sudo du -sh /var/lib/docker/volumes/*/ 2>/dev/null | sort -rh | head -5 |
    while read -r sz path; do printf "  ${_CYN}%8s${_R}  %s\n" "$sz" "$(basename "$path")"; done
  _signoff
}

ssdh() {
  local dev=${1:-/dev/nvme0n1} out
  out=$(_sudo smartctl -a "$dev" 2>/dev/null) || { printf "${_RED}✗ could not read %s${_R}\n" "$dev"; return 1; }
  _hdr "SSD health  ${_R}${_D}${dev}"
  awk -v R="$_R" -v B="$_B" -v G="$_GRN" -v Y="$_YLW" -v RD="$_RED" -v GY="$_GRY" -v BL="$_BLU" '
    function row(k, v) { printf "  %s%-16s%s %s\n", GY, k, R, v }
    /Model Number:/ { m=$0; sub(/.*Model Number: */, "", m); row("Model", B m R) }
    /SMART overall-health/ { s=$NF; row("Self-test", (s=="PASSED" ? G "✓ " s : RD "✗ " s) R) }
    /^Temperature:/ { t=$2; c=(t<=50?G:(t<=60?Y:RD)); row("Temperature", c t "°C" R) }
    /Percentage Used:/ { u=$3; gsub("%","",u); row("Wear", BL u "%" R " used, " (u<80?G:RD) 100-u "% life left" R) }
    /Available Spare:/ && !/Threshold/ { row("Spare", $3) }
    /Data Units Read:/ { v=$0; sub(/.*\[/, "", v); sub(/\].*/, "", v); row("Data read", v) }
    /Data Units Written:/ { v=$0; sub(/.*\[/, "", v); sub(/\].*/, "", v); row("Data written", v) }
    /Power On Hours:/ { h=$4; gsub(",","",h); row("Power on", h " h " GY "(" int(h/24) " days)" R) }
    /Power Cycles:/ { row("Power cycles", $3) }
    /Unsafe Shutdowns:/ { row("Unsafe shutdowns", ($3>20?Y:"") $3 R) }
    /Media and Data Integrity Errors:/ { row("Media errors", ($NF>0?RD:G) $NF R) }
  ' <<<"$out"
  _signoff
}

# The NVMe drive itself: model, firmware, size, PCIe link (ssdh has its health). Linux take on macOS system_profiler SPNVMeDataType
nvmeinfo() {
  local dev=${1:-/dev/nvme0n1} out ctrl link
  out=$(_sudo smartctl -i "$dev" 2>/dev/null) || { printf "${_RED}✗ could not read %s${_R}\n" "$dev"; return 1; }
  _hdr "NVMe drive  ${_R}${_D}${dev}"
  awk -v R="$_R" -v B="$_B" -v GY="$_GRY" '
    function row(k, v) { printf "  %s%-16s%s %s\n", GY, k, R, v }
    function val(l) { sub(/^[^:]*: */, "", l); return l }
    /^Model Number:/ { row("Model", B val($0) R) }
    /^Serial Number:/ { row("Serial", val($0)) }
    /^Firmware Version:/ { row("Firmware", val($0)) }
    /^Total NVM Capacity:/ { v=val($0); sub(/.*\[/, "", v); sub(/\].*/, "", v); row("Capacity", v) }
    /^NVMe Version:/ { row("NVMe version", val($0)) }
    /^Number of Namespaces:/ { row("Namespaces", val($0)) }' <<<"$out"
  ctrl=$(readlink -f /sys/block/"${dev##*/}"/device/device 2>/dev/null)
  [[ -r $ctrl/current_link_speed ]] && link="$(<"$ctrl"/current_link_speed) x$(<"$ctrl"/current_link_width) ${_GRY}(max $(<"$ctrl"/max_link_speed) x$(<"$ctrl"/max_link_width))${_R}"
  [[ -n $link ]] && _row "PCIe link" "$link"
  _row "Partitions" "$(lsblk -nro NAME,SIZE,MOUNTPOINT "$dev" | awk 'NR>1{printf "%s%s %s%s  ", $1, ($3?" ("$3")":""), $2, ""}')"
  _signoff
}

temps() {
  _hdr "Temperatures"
  local t z
  for z in /sys/class/thermal/thermal_zone*; do
    t=$(( $(cat "$z/temp") / 1000 ))
    _row "$(cat "$z/type")" "$(_lvl $t 60 80)${t}°C${_R}"
  done
  t=$(_sudo smartctl -A /dev/nvme0n1 2>/dev/null | awk '/^Temperature:/{print $2}')
  [[ -n $t ]] && _row "nvme0n1" "$(_lvl "$t" 55 70)${t}°C${_R}"
  _signoff
}

# ─── Network ─────────────────────────────────────────────────────────────────

netinfo() {
  local lan wifi ts pub
  lan=$(ip -4 -o addr show eno1 2>/dev/null | awk '{print $4}')
  wifi=$(ip -4 -o addr show wlp2s0 2>/dev/null | awk '{print $4}')
  ts=$(tailscale ip -4 2>/dev/null)
  pub=$(curl -s -m 4 https://ifconfig.me || echo "?")
  _hdr "Network"
  _row "Hostname" "${_B}$(hostname)${_R}"
  _row "Tailscale" "${_MAG}${ts}${_R}  ${_D}${HL_HOST}${_R}"
  _row "Ethernet" "${lan:-${_D}down${_R}}"
  _row "Wi-Fi" "${wifi:-${_D}down${_R}}"
  _row "Public IP" "$pub"
  _row "Gateway" "$(ip route | awk '/default/{print $3; exit}')"
  _row "DNS" "$(resolvectl dns 2>/dev/null | awk 'NF>3{print $NF}' | sort -u | paste -sd' ')"
  local rx tx
  read -r rx tx < <(awk '/eno1/{print $2, $10}' /proc/net/dev)
  _row "Since boot" "↓ $(numfmt --to=iec "$rx")  ↑ $(numfmt --to=iec "$tx")"
  printf "\n  ${_B}Tailnet peers${_R}\n"
  tailscale status 2>/dev/null | awk -v G="$_GRN" -v D="$_D" -v R="$_R" '
    $1 ~ /^100\./ { st = ($0 ~ /offline/) ? D "offline" R : G "●" R; printf "  %s %-24s %s%s%s\n", st, $2, D, $1, R }'
  _signoff
}

pingtest() {
  local target=${1:-1.1.1.1} avg
  avg=$(ping -c 4 -q "$target" 2>/dev/null | awk -F/ '/rtt|round-trip/{print $5}')
  [[ -z $avg ]] && { printf "${_RED}✗ %s unreachable${_R}\n" "$target"; return 1; }
  printf "Average latency to ${_B}%s${_R}: " "$target"
  if (( ${avg%.*} < 50 )); then printf "${_GRN}%s ms (Excellent)${_R}\n" "$avg"
  elif (( ${avg%.*} < 100 )); then printf "${_YLW}%s ms (Okay)${_R}\n" "$avg"
  else printf "${_RED}%s ms (Poor)${_R}\n" "$avg"; fi
}

ports() {
  _hdr "Listening ports" 60
  _sudo ss -tulnpH | awk -v C="$_CYN" -v D="$_D" -v R="$_R" '
    { split($5, a, ":"); port=a[length(a)]; addr=substr($5, 1, length($5)-length(port)-1)
      proc=$7; gsub(/users:\(\("|".*/, "", proc)
      key=$1 port addr; if (seen[key]++) next
      printf "  %s%-4s%s %-6s %-28s %s%s%s\n", D, $1, R, port, addr, C, proc, R }' | sort -k2 -n
  echo
}

dnsstats() {
  local pw s
  pw=$(_sudo awk -F= '/^ADGUARD_PASSWORD=/{print $2}' $HL_DIR/.env)
  s=$(curl -s -u "admin:$pw" localhost:3002/control/stats) || return 1
  _hdr "AdGuard (last 24h)"
  _row "Queries" "${_B}$(jq -r .num_dns_queries <<<"$s")${_R}"
  _row "Blocked" "${_RED}$(jq -r .num_blocked_filtering <<<"$s")${_R}  ${_D}($(jq -r 'if .num_dns_queries>0 then (.num_blocked_filtering*1000/.num_dns_queries|floor/10) else 0 end' <<<"$s")%)${_R}"
  _row "Avg latency" "$(jq -r '.avg_processing_time*1000|floor' <<<"$s") ms"
  printf "\n  ${_B}Top blocked${_R}\n"
  jq -r '.top_blocked_domains[:6][] | to_entries[0] | "\(.value)\t\(.key)"' <<<"$s" |
    while IFS=$'\t' read -r n d; do printf "  ${_RED}%6s${_R}  %s\n" "$n" "$d"; done
  _signoff
}

# ─── Docker / services ───────────────────────────────────────────────────────

dps() {
  _hdr "Containers" 72
  local stats
  stats=$(_sudo docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}')
  _sudo docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}' | sort |
  while IFS=$'\t' read -r name status image; do
    local dot cpu mem
    case $status in
      *unhealthy*) dot="${_RED}●" ;; Up*) dot="${_GRN}●" ;; *) dot="${_RED}●" ;;
    esac
    cpu=$(awk -F'\t' -v n="$name" '$1==n{print $2}' <<<"$stats")
    mem=$(awk -F'\t' -v n="$name" '$1==n{split($3,a," / "); print a[1]}' <<<"$stats")
    printf "  %s${_R} ${_B}%-14s${_R} ${_CYN}%7s${_R} ${_MAG}%10s${_R}  ${_D}%s${_R}\n" "$dot" "$name" "${cpu:--}" "${mem:--}" "$status"
  done
  _signoff
}

# Every web service, its tailnet URL, and whether it answers
svc() {
  _hdr "Services" 62
  # Probe the local port: the host cannot reach its own tailscale serve listeners
  local line name port path code
  for line in "Homepage|3080|" "Grafana|3000|:3000" "Uptime Kuma|3001|:3001" "AdGuard|3002|:3002" \
    "n8n|5678|:5678" "Dozzle|8888|:8888" "Prometheus|9090|:9090"; do
    IFS='|' read -r name port path <<<"$line"
    code=$(curl -s -o /dev/null -m 4 -w '%{http_code}' "http://127.0.0.1:$port/")
    if [[ $code =~ ^[23] ]]; then printf "  ${_GRN}✓${_R} %-12s ${_CYN}http://%s%s${_R}\n" "$name" "$HL_HOST" "$path"
    else printf "  ${_RED}✗${_R} %-12s ${_CYN}http://%s%s${_R} ${_RED}(%s)${_R}\n" "$name" "$HL_HOST" "$path" "$code"; fi
  done
  _signoff
}

dlogs() { [[ -z $1 ]] && { echo "Usage: dlogs <container>"; return 1; }; _sudo docker logs -f --tail 100 "$1"; }
cdh() { cd "$HL_DIR" || return; }

# Everyday shortcuts (ported from the Mac)
alias cdd='cd ~/Desktop'
alias ccd='cd ~/Downloads'
alias cls='clear'
close() { exit; }  # ends this shell: closes the terminal tab here, or the SSH session when you're in from the Mac
hlup() { (cd "$HL_DIR" && _sudo docker compose up -d "$@"); }
hlpull() { (cd "$HL_DIR" && _sudo docker compose pull && _sudo docker compose up -d && _sudo docker image prune -f); }
hlrestart() { (cd "$HL_DIR" && _sudo docker compose restart "$@"); }
hledit() { _sudo "${EDITOR:-vim}" "$HL_DIR/compose.yaml"; }
hlreload() { source /etc/homelab/homelab.sh && printf "${_GRN}✓${_R} homelab kit reloaded\n"; }

# Push a notification to your phone: notify "backup done" [title]
notify() {
  [[ -z $1 ]] && { echo "Usage: notify <message> [title]"; return 1; }
  curl -s -o /dev/null -w '' -H "Title: ${2:-$(hostname)}" -H "Tags: computer" -d "$1" http://127.0.0.1:8090/homelab &&
    printf "${_GRN}✓${_R} sent to your phone\n"
}

# Run any command and get pinged when it finishes: ding make build
ding() {
  local start=$SECONDS rc
  "$@"; rc=$?
  local took=$(( SECONDS - start ))
  if (( rc == 0 )); then notify "✅ '$*' finished in ${took}s" "Done" >/dev/null
  else notify "❌ '$*' failed (exit $rc) after ${took}s" "Failed" >/dev/null; fi
  return $rc
}

updates() {
  local n
  n=$(apt list --upgradable 2>/dev/null | grep -c upgradable)
  _hdr "Updates"
  _row "apt packages" "$( (( n > 0 )) && printf "${_YLW}%s waiting${_R}" "$n" || printf "${_GRN}✓ up to date${_R}")"
  _row "Reboot needed" "$([[ -f /var/run/reboot-required ]] && printf "${_YLW}yes${_R}" || printf "${_GRN}no${_R}")"
  _row "Docker images" "${_D}Watchtower updates them nightly at 04:00${_R}"
  _signoff
}

topcpu() { ps -eo pcpu=,pid=,comm= --sort=-pcpu | head -${1:-10} | awk -v C="$_CYN" -v R="$_R" '{printf "  %s%5s%%%s  %-7s %s\n", C, $1, R, $2, $3}'; }
topmem() { ps -eo pmem=,rss=,comm= --sort=-rss | head -${1:-10} | awk -v M="$_MAG" -v R="$_R" '{printf "  %s%5s%%%s  %7.0fM  %s\n", M, $1, R, $2/1024, $3}'; }

# ─── The big picture ─────────────────────────────────────────────────────────

hl() {
  local up load1 temp mem_pct disk_pct running total
  up=$(uptime -p | sed 's/up //')
  read -r load1 _ < /proc/loadavg
  temp=$(paste <(cat /sys/class/thermal/thermal_zone*/type) <(cat /sys/class/thermal/thermal_zone*/temp) | awk '$1=="x86_pkg_temp"{printf "%.0f", $2/1000}')
  mem_pct=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d", (t-a)*100/t}' /proc/meminfo)
  disk_pct=$(df --output=pcent / | tail -1 | tr -dc 0-9)
  running=$(_sudo docker ps -q 2>/dev/null | wc -l); total=$(_sudo docker ps -aq 2>/dev/null | wc -l)

  printf "\n${_B}${_MAG}  ◆ %s${_R}  ${_D}%s · up %s${_R}\n" "$(hostname)" "$(tailscale ip -4 2>/dev/null)" "$up"
  printf "${_GRY}  %s${_R}\n" "$(_rep ─ 52)"
  printf "  ${_GRY}%-9s${_R} %s   ${_D}load %s · %s°C${_R}\n" "CPU" "$(_bar "$(awk '{printf "%d", $1*100/'"$(nproc)"'}' /proc/loadavg)" 18)" "$load1" "${temp:-?}"
  printf "  ${_GRY}%-9s${_R} %s\n" "Memory" "$(_bar "$mem_pct" 18 75 90)"
  printf "  ${_GRY}%-9s${_R} %s\n" "Disk /" "$(_bar "$disk_pct" 18 75 90)"
  printf "  ${_GRY}%-9s${_R} %s\n" "Docker" "$( (( running == total )) && printf "${_GRN}%s/%s running${_R}" "$running" "$total" || printf "${_YLW}%s/%s running${_R}" "$running" "$total")"
  printf "\n  ${_D}Dashboard${_R} ${_CYN}http://%s${_R}   ${_D}Commands${_R} ${_B}hlhelp${_R}\n\n" "$HL_HOST"
}

hlhelp() {
  _hdr "Homelab commands" 58
  printf "  ${_B}Overview${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" hl "one-glance status (shown at login)" svc "every web UI with URL and health" dps "containers with CPU and memory"
  printf "  ${_B}Hardware${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" cpuinfo "model, clocks, load, per-core bars" raminfo "RAM, swap, top memory users" \
    diskinfo "filesystems and biggest volumes" nvmeinfo "NVMe model, firmware, size, PCIe link" \
    ssdh "NVMe SMART health and wear" temps "every thermal sensor"
  printf "  ${_B}Network${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" netinfo "IPs, DNS, tailnet peers" pingtest "latency check [host]" \
    ports "what is listening where" dnsstats "AdGuard queries and top blocked"
  printf "  ${_B}Stack${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" cdh "cd /opt/homelab" hlup "docker compose up -d [svc]" hlpull "pull new images and restart" \
    hlrestart "restart [svc]" hledit "edit compose.yaml" dlogs "follow a container's logs" updates "apt and reboot status"
  printf "  ${_B}Shortcuts${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" cdd "cd ~/Desktop" ccd "cd ~/Downloads" cls "clear the screen" close "close this terminal or SSH session"
  printf "  ${_B}Claude${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" hlclaude "desktop app: status, start, stop, restart, log"
  printf "  ${_B}Fun${_R}\n"
  printf "    ${_CYN}%-12s${_R} %s\n" notify "push a message to your phone" ding "run a command, get pinged when done" \
    topcpu "top processes by CPU" topmem "top processes by memory" hlreload "reload this kit"
  echo
}

# Show the status card once per login shell
shopt -q login_shell && [[ -z $HL_SHOWN ]] && { export HL_SHOWN=1; hl; }
