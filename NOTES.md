# How to explain this project (plain words)

Keep this open before the walkthrough. Read the "why" lines out loud until they feel natural.
This file is for YOU. It is fine to keep it in the repo, but you do not have to submit it.

## The one-minute story
"It is a small bus-booking API. The app is intentionally small. The work is in making it repeatable to build,
safe to release, easy to watch, and able to recover from failure - and in proving each of those with evidence.
One command, `scripts/drill.py`, deliberately breaks the system and writes a report showing it recovered."

## The 15-minute walkthrough (a safe running order)
1. (3 min) Open the architecture diagram in the README. Walk left to right: browser -> front door -> app -> database;
   Prometheus watches the app; GitHub Actions builds and scans the image; `deploy.sh` ships it.
2. (6 min) Run `python3 scripts/drill.py --video` while you talk. For each step say: what I break, what you should see,
   why it is safe. (Race: only one winner. Database down: ready turns 503, alarm fires, it heals. Backup: wipe and restore.
   Bad release: automatic rollback. Crash: Docker restarts it.)
3. (4 min) Pick three decisions from "Why-decisions" below and explain them.
4. (2 min) Say honestly what is NOT done (the "Known limitations" list in the README) and what you would do next.

## File by file
- `app/main.py` - the web API. Each function = one endpoint. `create_booking` runs inside ONE database transaction.
  Also `/health/*`, `/metrics`, request logging and metrics counters.
- `app/schemas.py` - rules for incoming data. Bad data is rejected with 422 before touching the database.
- `app/db.py` - keeps a small pool of database connections; reconnects by itself if the database restarts.
- `app/logging_conf.py` - prints each log line as JSON.
- `db/schema.sql` - the tables. The key line is the partial unique index `uq_tickets_confirmed_seat`.
- `db/seed.sql` - demo routes, trips (dated relative to today) and seats.
- `tests/` - 25 tests on a real database, including 25 people booking one seat at once.
- `Dockerfile` - three stages: `base` (libraries), `test` (adds test tools), `runtime` (what we ship; non-root).
- `docker-compose.yml` - app, database, front door (Caddy), Prometheus, Grafana; saved-data volumes; health checks.
- `deploy/Caddyfile` - HTTPS, security headers, hides `/metrics`, waits up to 5 s during restarts.
- `deploy/prometheus/` - what to measure and the alarm rules. `deploy/grafana/` - the dashboard as a file.
- `scripts/deploy.sh` - build -> start -> health gate -> (rollback if not ready). Remembers the live release.
- `scripts/backup.sh`, `restore.sh`, `verify_backup.sh` - dump + fingerprint, restore, prove-by-restoring.
- `scripts/drill.py` - the proof drill; writes `evidence/`.
- `.github/workflows/ci.yml` - secret scan -> lint/tests/dependency audit -> build -> image scan -> SBOM -> publish.
- `infra/` - scripts that create/delete the Azure server and install Docker and the backup schedule.

## Why-decisions (likely questions)
- **Why does the database enforce "no double booking" and not the Python code?**
  Python checks can race: two requests both see "seat free" and both book. The database index cannot be raced;
  it lets exactly one through.
- **Why a partial index (`WHERE status='CONFIRMED'`)?** So a cancelled seat can be booked again.
- **Why does a failed booking leave no PNR?** The PNR row and ticket rows are one transaction; the failure undoes both.
- **Why `/health/live` AND `/health/ready`?** Live = the program runs. Ready = it can really serve (database reachable).
  If the database dies, live stays 200 and ready becomes 503.
- **Why 503 when the database is down?** It tells callers "try again shortly", and the service heals by itself later.
- **Why a health gate in `deploy.sh`?** A release that starts but cannot work must never stay live. The script checks the
  NEW version's answer (it compares the version number), not just "something answers".
- **Why test backups by restoring?** A backup you have never restored is a hope, not a backup.
- **Why Caddy?** Automatic HTTPS with a tiny config file. On a public name it fetches a real certificate by itself.
- **Why non-root, read-only, no published database port, hidden /metrics?** If someone breaks in, they get as little as possible.
- **Why pinned versions and pinned Actions?** Same build today and next month; protects against tampered updates.
- **What is the chaos switch?** `FAULT_READY_FAIL` makes `/health/ready` fail. It is off by default; the drill builds one
  release with it on to imitate a broken release.

## Live-change practice (do these BEFORE the interview; each takes 5-10 minutes)
1. Change the maximum passengers per booking from 6 to 4 (`schemas.py`), fix the test, run the tests.
2. Add `GET /trips/{id}` returning one trip. Add a test.
3. Add a new alert in `deploy/prometheus/alerts.yml` (for example "no bookings for 10 minutes"); restart Prometheus.
4. Put a wrong database password in `.env`, restart the app, watch `/health/ready` fail, read the log line, fix it.
5. Change `HTTPS_PORT` in `.env`, redeploy, prove the new port works.
6. Break a test on purpose, push, read the failing CI run, fix it.
7. Restore a backup by hand and prove a deleted booking is back.
8. Roll back by hand to an earlier version and prove it with `/health/ready`.
