#!/usr/bin/env bash
# Take a compressed backup of the database.
# Usage:  bash scripts/backup.sh          (prints the backup file name as its last line)
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

KEEP="${BACKUP_KEEP:-14}"            # how many recent backups to keep
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="backups/${POSTGRES_DB}-${stamp}.sql.gz"
tmp="${file}.partial"

log "backing up database '${POSTGRES_DB}' ..."
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner | gzip > "$tmp"
gzip -t "$tmp"                                   # is the compressed file readable?
if [ ! -s "$tmp" ]; then
  echo "ERROR: backup file is empty" >&2
  rm -f "$tmp"
  exit 1
fi
mv "$tmp" "$file"
sha256sum "$file" > "${file}.sha256"             # a fingerprint to detect damage later
log "backup OK: $file ($(du -h "$file" | cut -f1))"

# Delete the oldest backups beyond KEEP.
# shellcheck disable=SC2012
ls -1t backups/*.sql.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old" "${old}.sha256"
  log "removed old backup $old"
done

echo "$file"
