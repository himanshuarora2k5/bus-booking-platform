#!/usr/bin/env bash
# One-command health check and error report. It only READS things, so it is safe to run any time.
#
# Usage:   bash scripts/doctor.sh
#
# 1. It prints "PROBLEM -> FIX" lines for the most common mistakes. Try those fixes first.
# 2. It saves a full report (passwords and tokens hidden) to doctor-report.txt.
#    If the fixes do not solve it, copy that report into a NEW chat with Claude (or any AI).

REPORT="doctor-report.txt"
PROBLEMS=0
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

problem() { PROBLEMS=$((PROBLEMS + 1)); printf 'PROBLEM: %s\n   FIX:  %s\n' "$1" "$2"; }
ok() { printf 'ok:      %s\n' "$1"; }

# --- find the project folder (works from anywhere) ---
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2> /dev/null && pwd)"
PROJECT=""
for d in "$PWD" "$here" "$HOME/bus-booking-platform"; do
  if [ -n "$d" ] && [ -f "$d/docker-compose.yml" ]; then PROJECT="$d"; break; fi
done
if [ -n "$PROJECT" ]; then cd "$PROJECT" || exit 1; fi

echo "=== doctor: checking your setup ($(date '+%a %d %b %H:%M')) ==="

# --- computer ---
if grep -qi microsoft /proc/version 2> /dev/null; then ok "running inside WSL (Ubuntu on Windows)"; fi
mem_mb="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2> /dev/null)"
if [ -n "${mem_mb:-}" ] && [ "$mem_mb" -lt 1500 ]; then
  problem "only ${mem_mb} MB of memory is free" "close heavy programs (browser tabs); in PowerShell run: wsl --shutdown   then reopen Ubuntu and run: sudo service docker start"
else ok "memory free: ${mem_mb:-unknown} MB"; fi
disk_mb="$(df -Pm / 2> /dev/null | awk 'NR==2 {print $4}')"
if [ -n "${disk_mb:-}" ] && [ "$disk_mb" -lt 5000 ]; then
  problem "disk is nearly full (${disk_mb} MB free)" "docker system prune -f     (does not delete your data volumes)"
else ok "disk free: ${disk_mb:-unknown} MB"; fi
if getent hosts github.com > /dev/null 2>&1; then ok "internet/DNS works"; else
  problem "cannot look up internet names (DNS is broken in WSL)" "printf '[network]\ngenerateResolvConf=false\n' | sudo tee /etc/wsl.conf ; echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf ; then in PowerShell: wsl --shutdown"
fi

# --- docker ---
DOCKER_OK=0
if ! command -v docker > /dev/null 2>&1; then
  problem "Docker is not installed" "curl -fsSL https://get.docker.com | sudo sh ; sudo usermod -aG docker \$USER ; then close and reopen Ubuntu"
else
  if docker info > /dev/null 2> "$TMP"; then
    DOCKER_OK=1; ok "Docker is running"
  elif grep -qi "permission denied" "$TMP"; then
    problem "you are not allowed to use Docker yet" "sudo usermod -aG docker \$USER ; then CLOSE the Ubuntu window and open it again"
  elif grep -qiE "cannot connect|is the docker daemon running" "$TMP"; then
    problem "Docker is installed but not started" "sudo service docker start"
  else
    problem "Docker does not answer: $(head -c 150 "$TMP")" "sudo service docker start   (then run this doctor again)"
  fi
  if ! docker compose version > /dev/null 2>&1; then
    problem "the 'docker compose' command is missing" "sudo apt-get install -y docker-compose-plugin"
  fi
fi

# --- project ---
if [ -z "$PROJECT" ]; then
  problem "cannot find the project folder" "cd ~/bus-booking-platform   (then run: bash scripts/doctor.sh)"
else
  ok "project folder: $PROJECT"
  if [ ! -f .env ]; then
    problem "the .env settings file is missing" "bash scripts/make_env.sh"
  else
    ok ".env exists"
    if grep -q $'\r' .env; then problem ".env has Windows line endings" "sed -i 's/\\r\$//' .env"; fi
    set -a
    # shellcheck source=/dev/null
    . ./.env 2> /dev/null
    set +a
  fi
  crlf="$(grep -l $'\r' scripts/*.sh infra/*.sh 2> /dev/null | head -3 | tr '\n' ' ')"
  if [ -n "$crlf" ]; then problem "script files have Windows line endings: $crlf" "sed -i 's/\\r\$//' scripts/*.sh infra/*.sh"; fi

  running=0
  if [ "$DOCKER_OK" = 1 ]; then running="$(docker compose ps -q 2> /dev/null | wc -l)"; fi
  for p in 8000 9090 3000 "${HTTPS_PORT:-8443}" "${HTTP_PORT:-8080}"; do
    if [ "$running" = 0 ] && ss -ltn 2> /dev/null | grep -q ":${p} "; then
      problem "port $p is already used by something else" "sudo ss -ltnp | grep ':$p '     (find it, stop it) - or change the port in .env"
    fi
  done

  if [ "$DOCKER_OK" = 1 ] && [ -f .env ]; then
    ps_text="$(docker compose ps -a 2> /dev/null)"
    if [ "$running" = 0 ]; then
      problem "the stack is not running" "bash scripts/deploy.sh v1      (or, if you started it before: docker compose start)"
    else
      bad="$(printf '%s\n' "$ps_text" | grep -Ei 'unhealthy|restarting|exited|dead' | awk '{print $1}' | tr '\n' ' ')"
      if [ -n "$bad" ]; then problem "these containers are not healthy: $bad" "docker compose logs --tail 30 <name>   (the report below already contains them)"; else ok "all containers running"; fi
    fi
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:8000/health/ready 2> /dev/null)"
    case "$code" in
      200) ok "app answers /health/ready = 200" ;;
      503) problem "app is running but its database is not ready" "docker compose start db ; wait 15 seconds ; run the doctor again" ;;
      *)
        if [ "$running" != 0 ]; then problem "the app does not answer (code ${code:-none})" "docker compose start app ; if it still fails: bash scripts/deploy.sh v1"; fi
        ;;
    esac
  fi

  if [ -d .git ]; then
    if git ls-files --error-unmatch .env > /dev/null 2>&1; then
      problem ".env is tracked by git - your passwords would be public" "git rm --cached .env ; git commit -m 'stop tracking .env' ; then change the passwords"
    fi
    if git ls-files -z | xargs -0 grep -lE 'ghp_[A-Za-z0-9]{20,}' 2> /dev/null | grep -q .; then
      problem "a GitHub token is written inside a tracked file" "remove it, delete that token on GitHub (Settings > Developer settings), make a new one"
    fi
  fi
fi

echo
if [ "$PROBLEMS" = 0 ]; then echo "RESULT: no common problems found."; else echo "RESULT: $PROBLEMS problem(s) found. Do the FIX lines, then run this doctor again."; fi

# --- full report (secrets hidden) ---
redact() {
  local s
  s="cat"
  if [ -f .env ]; then
    while IFS='=' read -r k v; do
      case "$k" in *PASSWORD* | *TOKEN* | *SECRET*) if [ "${#v}" -ge 6 ]; then s="$s | sed 's|$v|[hidden]|g'"; fi ;; esac
    done < .env
  fi
  eval "$s" | sed -E 's/ghp_[A-Za-z0-9]+/[token hidden]/g; s#://[^/@ ]+:[^/@ ]+@#://[hidden]@#g'
}
{
  echo "### doctor report $(date -u '+%F %T') UTC"
  echo "### system"; uname -a; grep PRETTY_NAME /etc/os-release 2> /dev/null; echo "memory MB free: ${mem_mb:-?}  disk MB free: ${disk_mb:-?}"
  echo "### docker"; docker --version 2>&1; docker compose version 2>&1; id -nG
  echo "### project: ${PROJECT:-NOT FOUND}"
  if [ "$DOCKER_OK" = 1 ] && [ -n "$PROJECT" ]; then
    echo "### docker compose ps -a"; docker compose ps -a 2>&1
    for s in app db proxy prometheus grafana; do
      echo "### logs: $s (last 25 lines)"; docker compose logs --tail 25 "$s" 2>&1
    done
  fi
  if [ -n "$PROJECT" ]; then
    echo "### listening ports"; ss -ltn 2> /dev/null | grep -E ':(8000|9090|3000|8080|8443|80|443) ' || echo "none of ours"
    echo "### .deploy"; cat .deploy/current 2> /dev/null; tail -8 .deploy/history.log 2> /dev/null
    echo "### env (names only)"; grep -vE '^#|^$' .env 2> /dev/null | cut -d= -f1 | tr '\n' ' '; echo
    if [ -d .git ]; then
      echo "### git"; git status -sb 2>&1 | head -12; git log --oneline -3 2>&1
      git remote -v 2>&1 | head -2
    fi
    echo "### evidence"; head -5 evidence/LATEST.md 2> /dev/null
  fi
} 2>&1 | redact > "$REPORT"
echo "Full report saved to $REPORT ($(wc -l < "$REPORT") lines, passwords and tokens hidden)."
echo "Not solved? Open a NEW chat with Claude and paste the output of:  cat $REPORT"
