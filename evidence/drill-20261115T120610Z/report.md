# Proof drill report

**Result: 3 of 3 scenarios passed**

| | |
|---|---|
| When | 2026-11-15 12:06:11 UTC |
| Code version (git commit) | `e098876` |
| Target | http://127.0.0.1:8000 |
| Machine | Linux 6.18.58.1-microsoft-standard-WSL2 (DESKTOP-1LA88PP) |
| Docker | Docker version 29.9.3, build 5457199 |

| # | Scenario | Result | Seconds |
|---|---|---|---|
| 1 | Service healthy before we start | PASS | 0.0 |
| 2 | Many people grab the SAME seat at once | PASS | 2.3 |
| 3 | Database dies: detection, alert, recovery | PASS | 19.2 |

## Evidence per scenario

### 1. Service healthy before we start - PASS

- /health/live = 200, /health/ready = 200, database up, running version `drill-20261114T140547Z-good`

### 2. Many people grab the SAME seat at once - PASS

- 50 clients tried to book seat 5D on trip 2 at the same instant
- result: 1 x HTTP 201 (winner, PNR 32HAX5W9DY), 49 x HTTP 409 (clean 'seat taken')
- database check: 1 new booking, 1 confirmed ticket for that seat (no duplicate PNR)
- response time: median 367 ms, slowest 507 ms

### 3. Database dies: detection, alert, recovery - PASS

- database container stopped; `/health/ready` turned 503 after 2.0s while `/health/live` stayed 200
- a booking attempt during the outage got a clean HTTP 503 (no crash, no wrong data)
- Prometheus alert `DatabaseDown` was FIRING 16.1s after the failure
- database started again; service ready after 1.3s with NO restart of the app
- data intact: booking 32HAX5W9DY is still there (CONFIRMED)

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
