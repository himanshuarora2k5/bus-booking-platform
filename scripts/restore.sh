#!/usr/bin/env bash
# Restore the LIVE database from a backup file. This REPLACES all current data.
# Usage:  bash scripts/restore.sh backups/<file>.sql.gz [--yes]
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

file="${1:-}"
if [ -z "$file" ]; then echo "usage: bash scripts/restore.sh <backup.sql.gz> [--yes]" >&2; exit 2; fi
if [ ! -f "$file" ]; then echo "ERROR: no such file: $file" >&2; exit 1; fi

if [ "${2:-}" != "--yes" ]; then
  read -r -p "This REPLACES all current data in '${POSTGRES_DB}'. Type YES to continue: " answer
  if [ "$answer" != "YES" ]; then echo "cancelled"; exit 1; fi
fi

gzip -t "$file"
if [ -f "${file}.sha256" ]; then
  sha256sum -c "${file}.sha256" > /dev/null || { echo "ERROR: checksum mismatch - the backup file is damaged" >&2; exit 1; }
  log "checksum OK"
fi

log "stopping the app so nothing writes during the restore ..."
docker compose stop app > /dev/null
log "restoring $file ..."
gunzip -c "$file" | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q > /dev/null
log "starting the app again ..."
docker compose start app > /dev/null
if wait_ready 60; then
  log "RESTORE COMPLETE: service is ready"
else
  echo "ERROR: service did not become ready after the restore - see docs/RUNBOOK.md" >&2
  exit 1
fi
