#!/usr/bin/env bash
# Schedules automatic backups: every night at 02:00, plus a weekly restore test on Sundays.
# Usage (on the server, from anywhere):   bash infra/install-cron.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/backups"
{
  crontab -l 2> /dev/null | grep -v "busbook-backup" || true
  echo "0 2 * * * cd $ROOT && bash scripts/backup.sh >> backups/cron.log 2>&1 # busbook-backup"
  echo "30 2 * * 0 cd $ROOT && bash scripts/verify_backup.sh >> backups/cron.log 2>&1 # busbook-backup"
} | crontab -
echo "Scheduled. Current schedule:"
crontab -l | grep busbook-backup
