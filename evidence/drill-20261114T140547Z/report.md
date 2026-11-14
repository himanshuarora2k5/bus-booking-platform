# Proof drill report

**Result: 9 of 9 scenarios passed**

| | |
|---|---|
| When | 2026-11-14 14:05:47 UTC |
| Code version (git commit) | `` |
| Target | http://127.0.0.1:8000 |
| Machine | Linux 6.18.58.1-microsoft-standard-WSL2 (DESKTOP-1LA88PP) |
| Docker | Docker version 29.9.3, build 5457199 |

| # | Scenario | Result | Seconds |
|---|---|---|---|
| 1 | Service healthy before we start | PASS | 0.0 |
| 2 | HTTPS front door works, /metrics is hidden | PASS | 0.0 |
| 3 | Many people grab the SAME seat at once | PASS | 2.0 |
| 4 | Cancelling frees the seat for someone else | PASS | 0.0 |
| 5 | Database dies: detection, alert, recovery | PASS | 16.8 |
| 6 | Backup, total data loss, restore | PASS | 12.2 |
| 7 | A normal release goes live | PASS | 14.6 |
| 8 | A broken release is rolled back automatically | PASS | 35.8 |
| 9 | App crashes: Docker restarts it by itself | PASS | 3.7 |

## Evidence per scenario

### 1. Service healthy before we start - PASS

- /health/live = 200, /health/ready = 200, database up, running version `drill-20261114T135618Z-good`

### 2. HTTPS front door works, /metrics is hidden - PASS

- HTTPS `https://localhost:8443/health/ready` = 200
- `/metrics` through the front door = 404 (hidden from the public)
- local certificate (made by the proxy itself, so browsers warn about it)

### 3. Many people grab the SAME seat at once - PASS

- 50 clients tried to book seat 5B on trip 1 at the same instant
- result: 1 x HTTP 201 (winner, PNR WPMLJ38SGN), 49 x HTTP 409 (clean 'seat taken')
- database check: 1 new booking, 1 confirmed ticket for that seat (no duplicate PNR)
- response time: median 332 ms, slowest 470 ms

### 4. Cancelling frees the seat for someone else - PASS

- cancelled WPMLJ38SGN, seat 5B became free, rebooked as new PNR WTH3EM7686

### 5. Database dies: detection, alert, recovery - PASS

- database container stopped; `/health/ready` turned 503 after 2.0s while `/health/live` stayed 200
- a booking attempt during the outage got a clean HTTP 503 (no crash, no wrong data)
- Prometheus alert `DatabaseDown` was FIRING 14.6s after the failure
- database started again; service ready after 0.9s with NO restart of the app
- data intact: booking WTH3EM7686 is still there (CONFIRMED)

### 6. Backup, total data loss, restore - PASS

- backup `backups/busdb-20261114T140606Z.sql.gz` (5 KB), gzip test and SHA-256 fingerprint OK
- verification: a fresh backup restored into a SCRATCH database matched the live data exactly
- disaster: every booking deleted (booking WTH3EM7686 returned 404)
- restore from backup took 6.9s; booking WTH3EM7686 is back (CONFIRMED)

### 7. A normal release goes live - PASS

- deployed version `drill-20261114T140547Z-good`: built, started, passed the health gate and went live

### 8. A broken release is rolled back automatically - PASS

- broken release `drill-20261114T140547Z-bad` started but never became ready within the 25s health gate
- automatic rollback: `drill-20261114T140547Z-good` is serving traffic again (HTTP 200)
- deploy history is in `.deploy/history.log`

### 9. App crashes: Docker restarts it by itself - PASS

- app process terminated; Docker restarted the container by itself (restart count 0 -> 1) and the service became ready after 2.4s

## Deployment history (last entries)

```
2026-11-14T13:56:49Z DEPLOY start: version=drill-20261114T135618Z-good image=bus-booking-app:drill-20261114T135618Z-good previous=v1
2026-11-14T13:57:02Z DEPLOY OK: version drill-20261114T135618Z-good is live and ready
2026-11-14T13:57:02Z DEPLOY start: version=drill-20261114T135618Z-bad image=bus-booking-app:drill-20261114T135618Z-bad previous=drill-20261114T135618Z-good
2026-11-14T13:57:34Z DEPLOY FAILED: version drill-20261114T135618Z-bad did not become ready within 25s
2026-11-14T13:57:34Z ROLLING BACK to drill-20261114T135618Z-good (bus-booking-app:drill-20261114T135618Z-good)
2026-11-14T13:57:38Z ROLLED BACK to drill-20261114T135618Z-good: the service is healthy again
2026-11-14T14:06:19Z DEPLOY start: version=drill-20261114T140547Z-good image=bus-booking-app:drill-20261114T140547Z-good previous=drill-20261114T135618Z-good
2026-11-14T14:06:33Z DEPLOY OK: version drill-20261114T140547Z-good is live and ready
2026-11-14T14:06:33Z DEPLOY start: version=drill-20261114T140547Z-bad image=bus-booking-app:drill-20261114T140547Z-bad previous=drill-20261114T140547Z-good
2026-11-14T14:07:05Z DEPLOY FAILED: version drill-20261114T140547Z-bad did not become ready within 25s
2026-11-14T14:07:06Z ROLLING BACK to drill-20261114T140547Z-good (bus-booking-app:drill-20261114T140547Z-good)
2026-11-14T14:07:09Z ROLLED BACK to drill-20261114T140547Z-good: the service is healthy again
```
