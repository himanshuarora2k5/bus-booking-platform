#!/usr/bin/env bash
# Safe release: build a new version, start it, check that it is healthy, and if it is NOT,
# automatically go back to the previous version.
#
# Usage:   bash scripts/deploy.sh <version-label> [--simulate-bad-release] [--image <registry-image>]
# Examples:
#   bash scripts/deploy.sh v1
#   bash scripts/deploy.sh v2
#   bash scripts/deploy.sh v3-bad --simulate-bad-release       (demo: proves the automatic rollback)
#   bash scripts/deploy.sh sha-1a2b3c4 --image ghcr.io/you/bus-booking-platform:sha-1a2b3c4
set -uo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

READY_TIMEOUT="${READY_TIMEOUT:-40}"        # seconds to wait for the new version to become ready
VERSION="${1:-}"
if [ -z "$VERSION" ]; then sed -n '2,11p' "$0" >&2; exit 2; fi
shift
if ! [[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: the version label may only contain letters, digits, dot, underscore, dash" >&2
  exit 2
fi

BAD=false
REG_IMAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --simulate-bad-release) BAD=true ;;
    --image) REG_IMAGE="${2:-}"; shift ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p .deploy
STATE=.deploy/current                      # remembers: <image> <version> of the live release
OLD_IMAGE=""
OLD_VERSION=""
if [ -f "$STATE" ]; then read -r OLD_IMAGE OLD_VERSION < "$STATE"; fi
NEW_IMAGE="${REG_IMAGE:-bus-booking-app:$VERSION}"

note() { log "$*"; printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> .deploy/history.log; }

note "DEPLOY start: version=$VERSION image=$NEW_IMAGE previous=${OLD_VERSION:-none}"

# 1. The database must be up first.
log "making sure the database is up ..."
if ! docker compose up -d --wait db > /dev/null; then
  note "DEPLOY failed: the database did not start"
  exit 1
fi

# 2. Get the new image: build it here, or pull one that CI built.
if [ -n "$REG_IMAGE" ]; then
  if ! docker pull "$REG_IMAGE"; then note "DEPLOY failed: cannot pull $REG_IMAGE (nothing changed)"; exit 1; fi
else
  log "building the image (simulate bad release: $BAD) ..."
  if ! APP_IMAGE="$NEW_IMAGE" APP_VERSION="$VERSION" BAKE_FAULT="$BAD" docker compose build app; then
    note "DEPLOY failed: build error (nothing changed, the old version is still running)"
    exit 1
  fi
fi

# 3. Switch the app over to the new image.
log "starting version $VERSION ..."
APP_IMAGE="$NEW_IMAGE" APP_VERSION="$VERSION" docker compose up -d --no-deps --no-build app > /dev/null

# 4. Health gate: is the NEW version really answering "ready"?
if wait_ready "$READY_TIMEOUT" "$VERSION"; then
  printf '%s %s\n' "$NEW_IMAGE" "$VERSION" > "$STATE"
  set_env_var APP_IMAGE "$NEW_IMAGE"       # so later plain "docker compose" commands keep this release
  set_env_var APP_VERSION "$VERSION"
  # Start / refresh the rest of the stack (proxy, monitoring). The NEW release values must be passed
  # here too, otherwise Compose would use the old ones from .env and put the old version back.
  APP_IMAGE="$NEW_IMAGE" APP_VERSION="$VERSION" docker compose up -d > /dev/null
  note "DEPLOY OK: version $VERSION is live and ready"
  exit 0
fi

# 5. It did not become ready: go back.
note "DEPLOY FAILED: version $VERSION did not become ready within ${READY_TIMEOUT}s"
log "last log lines of the failed version:"
docker compose logs --tail 15 app >&2 || true
if [ -z "$OLD_IMAGE" ]; then
  note "there is no previous release to go back to"
  exit 1
fi
note "ROLLING BACK to $OLD_VERSION ($OLD_IMAGE)"
APP_IMAGE="$OLD_IMAGE" APP_VERSION="$OLD_VERSION" docker compose up -d --no-deps --no-build app > /dev/null
if wait_ready 60 "$OLD_VERSION"; then
  note "ROLLED BACK to $OLD_VERSION: the service is healthy again"
else
  note "ROLLBACK FAILED: $OLD_VERSION is not ready either - see docs/RUNBOOK.md"
fi
exit 1
