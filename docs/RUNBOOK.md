# Operations runbook

Everything below is run from the project folder on the server (or WSL). `docker compose` = the Compose plugin.

## Quick reference

| I want to... | Command |
|---|---|
| See what is running | `docker compose ps` |
| Is it healthy? | `curl -s http://127.0.0.1:8000/health/ready` |
| Follow the app logs | `docker compose logs -f --tail 50 app` |
| Follow the front-door logs | `docker compose logs -f --tail 50 proxy` |
| Release a new version | `bash scripts/deploy.sh <version>` |
| Go back to an older version | `cat .deploy/history.log` then `bash scripts/deploy.sh <older-version>` |
| Back up now | `bash scripts/backup.sh` |
| Check backups really restore | `bash scripts/verify_backup.sh` |
| Restore (replaces live data) | `bash scripts/restore.sh backups/<file>.sql.gz` |
| Restart only the app | `docker compose restart app` |
| Something is wrong, I do not know what | `bash scripts/doctor.sh` (prints fixes, saves `doctor-report.txt`) |
| Try a booking by hand | `bash scripts/try_booking.sh 3C` |
| Prove everything works | `python3 scripts/drill.py` |

**Never** run `docker compose down -v` on a live system: `-v` deletes the database volume.

## Start / stop

- Start or refresh everything: `bash scripts/deploy.sh <version>` (first time: `v1`).
- Stop everything but keep data: `docker compose stop`. Start again: `docker compose start`.
- After a server reboot nothing needs doing: Docker starts on boot and every service has `restart: always`.

## Deploy a new version

1. `git pull` (or copy the new code) and make sure tests pass in CI.
2. `bash scripts/deploy.sh v<next>`.
3. The script waits up to 40 s for **that version** to report ready. Success prints `DEPLOY OK`.
4. Failure prints `DEPLOY FAILED` followed by `ROLLED BACK to <old>`; the service stays on the old version.
   Read the printed log lines, fix the problem, deploy again.

## Roll back (manual)

1. `cat .deploy/history.log` - find the last version that was good.
2. `bash scripts/deploy.sh <that-version>` - the image is still on the machine, so this takes seconds.
3. Confirm: `curl -s http://127.0.0.1:8000/health/ready` shows that version.

## Logs

JSON, one object per line. Useful filters: `docker compose logs app | grep '"status": 5'` (server errors),
`... | grep seat_conflict` (double-booking attempts), `... | grep "database unavailable"`.
Every response carries an `x-request-id` header; search the logs for that id to follow one request.

## Backup and restore

- Backups: `backups/<db>-<time>.sql.gz` plus a `.sha256` file. Nightly at 02:00 if `infra/install-cron.sh` was run.
- Restore: `bash scripts/restore.sh <file>`. It checks the fingerprint, stops the app, restores, starts the app,
  and waits for readiness. Type `YES` when asked.
- Test it without risk: `bash scripts/verify_backup.sh` (uses a scratch database).
- Copy backups off the server regularly (`scp`), because they live on the same disk.

## Incident response

### API down
Alert `ApiDown`: Prometheus cannot reach the app.
1. `docker compose ps` - is `app` running? If it says `Restarting`, read `docker compose logs --tail 50 app`.
2. If the last deploy caused it: `bash scripts/deploy.sh <previous-version>`.
3. `docker compose restart app`, then check `/health/ready`.

### Database down
Alert `DatabaseDown`: the app runs but cannot reach PostgreSQL. `/health/ready` returns 503 and bookings return 503 (no data is lost).
1. `docker compose ps db` and `docker compose logs --tail 50 db`.
2. `docker compose start db` (or `docker compose restart db`). The app reconnects by itself within seconds.
3. If the data is damaged: `bash scripts/restore.sh <latest backup>`.
4. Check disk space: `df -h`.

### High error rate
Alert `HighServerErrorRate`: more than one 5xx every two seconds.
1. Look at the dashboard (Grafana, Requests by status) and `docker compose logs app | grep '"status": 5'`.
2. Started right after a release? Roll back (above).
3. Otherwise check the database (previous section) and server resources: `docker stats --no-stream`.

### Disk full
`df -h`, then remove old backups (`ls -lh backups/`) or old images (`docker image prune`). Never delete the `pgdata` volume.

### Certificate / HTTPS problem
`docker compose logs proxy`. On a public server make sure ports 80 and 443 are open and `SITE_ADDRESS` is the exact public name.
