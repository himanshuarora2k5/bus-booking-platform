#!/usr/bin/env bash
# Proves backups are USABLE: takes a fresh backup, restores it into a separate scratch
# database, and compares row counts with the live database. Live data is never touched.
# Usage:  bash scripts/verify_backup.sh
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

SCRATCH="restore_check"
file="$(bash scripts/backup.sh | tail -n 1)"

log "restoring $file into scratch database '$SCRATCH' ..."
db_psql postgres -q -c "DROP DATABASE IF EXISTS ${SCRATCH}" -c "CREATE DATABASE ${SCRATCH}" > /dev/null
gunzip -c "$file" | db_psql "$SCRATCH" -q > /dev/null

counts() {
  db_psql "$1" -tA -F ' ' -c "SELECT (SELECT count(*) FROM routes), (SELECT count(*) FROM trips), (SELECT count(*) FROM seats), (SELECT count(*) FROM bookings), (SELECT count(*) FROM tickets)"
}
live="$(counts "$POSTGRES_DB")"
copy="$(counts "$SCRATCH")"
db_psql postgres -q -c "DROP DATABASE IF EXISTS ${SCRATCH}" > /dev/null

log "live     (routes trips seats bookings tickets): $live"
log "restored (routes trips seats bookings tickets): $copy"
if [ "$live" = "$copy" ]; then
  log "VERIFY PASS: the backup restores to identical data"
  echo "PASS $file"
else
  echo "VERIFY FAIL: restored data differs from live data" >&2
  exit 1
fi
