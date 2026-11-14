"""Database access: a small pool of reusable connections + schema/seed setup."""

import logging
import os
import time
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("app.db")
DB_DIR = Path(__file__).resolve().parent.parent / "db"

pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    """Create the pool. It reconnects by itself if the database restarts."""
    global pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    pool = ConnectionPool(
        url,
        min_size=1,
        max_size=int(os.environ.get("DB_POOL_MAX", "10")),
        kwargs={"row_factory": dict_row},
        check=ConnectionPool.check_connection,  # test a connection before handing it out
        timeout=5,  # how long a request waits for a free connection before giving up
        open=False,
    )
    pool.open()
    return pool


def close_pool() -> None:
    if pool is not None:
        pool.close()


def init_db(retries: int = 30, delay: float = 1.0) -> None:
    """Create tables (and demo data on an empty database). Retries while the DB is starting."""
    schema_sql = (DB_DIR / "schema.sql").read_text()
    seed_sql = (DB_DIR / "seed.sql").read_text()
    seed_enabled = os.environ.get("SEED_DEMO_DATA", "true").lower() == "true"

    for attempt in range(1, retries + 1):
        try:
            with pool.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(727001)")  # one initialiser at a time
                conn.execute(schema_sql)
                n = conn.execute("SELECT count(*) AS n FROM routes").fetchone()["n"]
                if n == 0 and seed_enabled:
                    conn.execute(seed_sql)
                    log.info("seeded demo data")
            log.info("database ready")
            return
        except Exception as exc:
            log.warning(
                "database not ready, retrying",
                extra={"fields": {"attempt": attempt, "error": str(exc)[:200]}},
            )
            time.sleep(delay)
    raise RuntimeError("database never became ready")


def ping() -> bool:
    """True if we can run a trivial query within 2 seconds."""
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
