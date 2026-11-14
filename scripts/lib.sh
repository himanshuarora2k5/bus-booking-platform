#!/usr/bin/env bash
# Shared helpers. Other scripts load this with:   . "$(dirname "$0")/lib.sh"
# (Do not run this file directly.)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ ! -f .env ]; then
  echo "ERROR: .env file not found in $ROOT" >&2
  echo "Fix:   cp .env.example .env     (then edit the passwords inside it)" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

log() { printf '%s  %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

# wait_ready <seconds> [expected-version]
# Succeeds as soon as /health/ready answers 200 (and reports the expected version, if given).
wait_ready() {
  local timeout="$1" want="${2:-}" i=0 body
  while [ "$i" -lt "$timeout" ]; do
    if body="$(curl -fsS --max-time 3 "$BASE_URL/health/ready" 2>/dev/null)"; then
      if [ -z "$want" ] || printf '%s' "$body" | grep -q "\"version\":\"$want\""; then
        return 0
      fi
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

# db_psql <database> [psql options...]   - run psql inside the database container
db_psql() {
  local database="$1"
  shift
  docker compose exec -T db psql -U "$POSTGRES_USER" -d "$database" -v ON_ERROR_STOP=1 "$@"
}

# set_env_var KEY VALUE   - change (or add) one line in .env
set_env_var() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}
