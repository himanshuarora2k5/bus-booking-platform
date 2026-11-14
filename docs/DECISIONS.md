# Design decisions (short)

| Decision | Why | Trade-off |
|---|---|---|
| The database enforces "one confirmed ticket per seat" (partial unique index) | Application checks can race; an index cannot | Rule lives in SQL, so tests must use a real PostgreSQL |
| One transaction per booking | PNR and tickets are saved together or not at all, so a conflict leaves no PNR | None worth noting |
| Docker Compose on one server | Simple, reproducible, easy to explain and recover | No automatic multi-server failover |
| Caddy as the front door | Automatic HTTPS with a tiny config | Fewer features than a full gateway |
| `/health/live` and `/health/ready` are separate | Distinguishes "process is up" from "can serve traffic" | Two endpoints to maintain |
| Prometheus + Grafana provisioned from files | Monitoring is reproducible, nothing is clicked by hand | Alerts are not delivered by email/chat |
| `deploy.sh` with a health gate | A bad release can never stay live; rollback is automatic | Brief interruption while the container is replaced (the front door waits up to 5 s) |
| Rollback uses images kept on the machine | Seconds, not minutes | Needs disk space for old images |
| Backups checked by restoring them | An untested backup is not a backup | Backup files live on the same disk unless copied off |
| `restart: always` on every service | Survives crashes and reboots | A crash loop restarts forever (monitoring shows it) |
| Actions pinned to commit IDs | Protects the pipeline from tampered tags | Updates are manual |
| Chaos switch `FAULT_READY_FAIL` (off by default, baked at build time) | Lets the drill ship a genuinely broken release | A test hook exists in the code; it is documented and disabled |
