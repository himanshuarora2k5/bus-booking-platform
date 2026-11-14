"""Bus trip & seat reservation API."""

import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from psycopg import OperationalError
from psycopg import errors as pg_errors
from psycopg_pool import PoolTimeout

from app import db
from app.logging_conf import setup_logging
from app.schemas import BookingRequest

setup_logging()
log = logging.getLogger("app")

VERSION = os.environ.get("APP_VERSION", "dev")
IST = timezone(timedelta(hours=5, minutes=30))  # Indian Standard Time
PNR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to read out loud
SEAT_CONFLICT_CONSTRAINT = "uq_tickets_confirmed_seat"
PNR_CONSTRAINT = "bookings_pnr_key"

# ---- numbers the service reports about itself (read by Prometheus at /metrics) ----
REQUESTS = Counter("http_requests_total", "HTTP requests handled", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "How long requests take",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
BOOKINGS = Counter("bookings_total", "Booking outcomes", ["outcome"])
DB_UP = Gauge("app_database_up", "1 if the database answers, 0 if not")
APP_INFO = Gauge("app_info", "Which version is running", ["version"])
APP_INFO.labels(VERSION).set(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    db.init_db()
    log.info("service started", extra={"fields": {"version": VERSION}})
    yield
    db.close_pool()


app = FastAPI(title="Bus Booking API", version=VERSION, lifespan=lifespan)


@app.exception_handler(PoolTimeout)
@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: Exception):
    """Database down or unreachable: answer quickly with 503 (try again later), not a crash."""
    log.error("database unavailable", extra={"fields": {"error": type(exc).__name__}})
    body = {"detail": {"code": "DB_UNAVAILABLE", "message": "database temporarily unavailable"}}
    return JSONResponse(body, status_code=503, headers={"Retry-After": "5"})


def problem(status: int, code: str, message: str) -> HTTPException:
    """Business-rule errors always look the same: {"detail": {"code": ..., "message": ...}}."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------------------------------------------------------------- request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        log.exception("unhandled error", extra={"fields": {"request_id": request_id}})
        return JSONResponse({"detail": "internal error", "request_id": request_id}, status_code=500)
    finally:
        elapsed = time.perf_counter() - start
        route = getattr(request.scope.get("route"), "path", "unmatched")  # e.g. /trips/{trip_id}/seats
        if request.url.path != "/metrics":
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(route).observe(elapsed)
        if request.url.path not in ("/health/live", "/health/ready", "/metrics"):  # keep logs readable
            log.info(
                "request",
                extra={
                    "fields": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "ms": round(elapsed * 1000, 1),
                    }
                },
            )


# ---------------------------------------------------------------- health
@app.get("/health/live")
def live():
    """Is the process running? (Does NOT check the database.)"""
    return {"status": "ok", "version": VERSION}


@app.get("/health/ready")
def ready():
    """Can we actually serve traffic? Needs the database."""
    if os.environ.get("FAULT_READY_FAIL", "false").lower() == "true":
        # Chaos switch used by the rollback drill to imitate a broken release. Off by default.
        body = {"status": "not_ready", "reason": "fault injected", "version": VERSION}
        return JSONResponse(body, 503)
    if db.ping():
        return {"status": "ready", "database": "up", "version": VERSION}
    return JSONResponse({"status": "not_ready", "database": "down", "version": VERSION}, 503)


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Numbers for Prometheus. The reverse proxy hides this page from the public internet."""
    DB_UP.set(1 if db.ping() else 0)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------- read endpoints
@app.get("/routes")
def list_routes():
    with db.pool.connection() as conn:
        routes = conn.execute("SELECT id, origin, destination FROM routes ORDER BY id").fetchall()
        stops = conn.execute("SELECT route_id, name FROM route_stops ORDER BY route_id, seq").fetchall()
    for r in routes:
        r["stops"] = [s["name"] for s in stops if s["route_id"] == r["id"]]
    return routes


@app.get("/trips")
def list_trips(
    origin: str | None = None,
    destination: str | None = None,
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Upcoming trips, optionally filtered by origin, destination and travel date (YYYY-MM-DD)."""
    sql = """
        SELECT t.id, r.origin, r.destination, t.departure, t.bus_type, t.price_inr,
               (SELECT count(*) FROM seats s WHERE s.trip_id = t.id) AS total_seats,
               (SELECT count(*) FROM tickets k
                 WHERE k.trip_id = t.id AND k.status = 'CONFIRMED') AS booked_seats
        FROM trips t JOIN routes r ON r.id = t.route_id
        WHERE t.departure > now()
          AND (%(origin)s::text IS NULL OR lower(r.origin) = lower(%(origin)s::text))
          AND (%(destination)s::text IS NULL OR lower(r.destination) = lower(%(destination)s::text))
          AND (%(day)s::date IS NULL
               OR (t.departure AT TIME ZONE 'Asia/Kolkata')::date = %(day)s::date)
        ORDER BY t.departure
        LIMIT 100
    """
    try:
        with db.pool.connection() as conn:
            rows = conn.execute(sql, {"origin": origin, "destination": destination, "day": date}).fetchall()
    except pg_errors.DatetimeFieldOverflow as exc:
        raise problem(422, "BAD_DATE", "date is not a real calendar date") from exc
    for row in rows:
        row["departure"] = row["departure"].astimezone(IST).isoformat()
        row["available_seats"] = row["total_seats"] - row["booked_seats"]
    return rows


@app.get("/trips/{trip_id}/seats")
def seat_map(trip_id: int):
    with db.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM trips WHERE id = %s", (trip_id,)).fetchone():
            raise problem(404, "TRIP_NOT_FOUND", "no such trip")
        seats = conn.execute(
            """
            SELECT s.seat_no, (k.id IS NOT NULL) AS booked
            FROM seats s
            LEFT JOIN tickets k ON k.trip_id = s.trip_id AND k.seat_no = s.seat_no
                               AND k.status = 'CONFIRMED'
            WHERE s.trip_id = %s
            ORDER BY regexp_replace(s.seat_no, '[^0-9]', '', 'g')::int, s.seat_no
            """,
            (trip_id,),
        ).fetchall()
    return {"trip_id": trip_id, "seats": seats}


# ---------------------------------------------------------------- bookings
def _new_pnr() -> str:
    return "".join(secrets.choice(PNR_ALPHABET) for _ in range(10))


def _booking_view(conn, pnr: str) -> dict:
    booking = conn.execute(
        """
        SELECT b.pnr, b.status, b.trip_id, r.origin, r.destination, t.departure,
               b.boarding_stop, b.drop_stop, b.contact_phone, b.total_inr,
               b.created_at, b.cancelled_at
        FROM bookings b
        JOIN trips t ON t.id = b.trip_id
        JOIN routes r ON r.id = t.route_id
        WHERE b.pnr = %s
        """,
        (pnr,),
    ).fetchone()
    if not booking:
        raise problem(404, "PNR_NOT_FOUND", "no booking with that PNR")
    booking["passengers"] = conn.execute(
        """
        SELECT k.passenger_name AS name, k.passenger_age AS age, k.gender, k.seat_no, k.status
        FROM tickets k JOIN bookings b ON b.id = k.booking_id
        WHERE b.pnr = %s ORDER BY k.id
        """,
        (pnr,),
    ).fetchall()
    for key in ("departure", "created_at", "cancelled_at"):
        if booking[key] is not None:
            booking[key] = booking[key].astimezone(IST).isoformat()
    return booking


@app.post("/bookings", status_code=201)
def create_booking(req: BookingRequest):
    # Everything inside this `with` is ONE transaction: it all happens, or none of it does.
    with db.pool.connection() as conn:
        trip = conn.execute(
            "SELECT id, route_id, departure, price_inr FROM trips WHERE id = %s", (req.trip_id,)
        ).fetchone()
        if not trip:
            raise problem(404, "TRIP_NOT_FOUND", "no such trip")

        departure = trip["departure"].astimezone(IST)
        if departure.date() != req.travel_date:
            raise problem(422, "TRAVEL_DATE_MISMATCH", f"this trip departs on {departure.date()}")
        if departure <= datetime.now(UTC):
            raise problem(422, "TRIP_DEPARTED", "this trip has already departed")

        stops = {
            r["name"]: r["seq"]
            for r in conn.execute(
                "SELECT name, seq FROM route_stops WHERE route_id = %s", (trip["route_id"],)
            ).fetchall()
        }
        for stop in (req.boarding_stop, req.drop_stop):
            if stop not in stops:
                raise problem(422, "UNKNOWN_STOP", f"'{stop}' is not a stop on this route")
        if stops[req.boarding_stop] >= stops[req.drop_stop]:
            raise problem(422, "STOP_ORDER", "boarding stop must come before the drop stop")

        wanted = [p.seat_no for p in req.passengers]
        found = {
            r["seat_no"]
            for r in conn.execute(
                "SELECT seat_no FROM seats WHERE trip_id = %s AND seat_no = ANY(%s)",
                (req.trip_id, wanted),
            ).fetchall()
        }
        if missing := sorted(set(wanted) - found):
            raise problem(422, "UNKNOWN_SEAT", f"seats not on this bus: {', '.join(missing)}")

        total = trip["price_inr"] * len(req.passengers)

        for _attempt in range(5):  # retry only if we randomly generate a PNR that already exists
            pnr = _new_pnr()
            try:
                with conn.transaction():  # a "savepoint": undo just this block if it fails
                    booking_id = conn.execute(
                        """
                        INSERT INTO bookings (pnr, trip_id, status, contact_phone,
                                              boarding_stop, drop_stop, total_inr)
                        VALUES (%s, %s, 'CONFIRMED', %s, %s, %s, %s) RETURNING id
                        """,
                        (pnr, req.trip_id, req.contact_phone, req.boarding_stop, req.drop_stop, total),
                    ).fetchone()["id"]
                    for p in req.passengers:
                        conn.execute(
                            """
                            INSERT INTO tickets (booking_id, trip_id, seat_no, passenger_name,
                                                 passenger_age, gender, status)
                            VALUES (%s, %s, %s, %s, %s, %s, 'CONFIRMED')
                            """,
                            (booking_id, req.trip_id, p.seat_no, p.name, p.age, p.gender),
                        )
                break
            except pg_errors.UniqueViolation as exc:
                constraint = exc.diag.constraint_name
                if constraint == SEAT_CONFLICT_CONSTRAINT:
                    # The database refused a second confirmed ticket for the same seat.
                    # The savepoint was undone, so no booking row / PNR was kept.
                    BOOKINGS.labels("seat_conflict").inc()
                    log.warning("seat conflict", extra={"fields": {"trip_id": req.trip_id, "seats": wanted}})
                    raise problem(409, "SEAT_ALREADY_BOOKED", "one or more seats were just booked") from exc
                if constraint != PNR_CONSTRAINT:
                    raise
        else:
            raise problem(500, "PNR_GENERATION_FAILED", "could not generate a unique PNR")

        view = _booking_view(conn, pnr)
    BOOKINGS.labels("confirmed").inc()  # counted only after the transaction has been saved
    return view


@app.get("/bookings/{pnr}")
def get_booking(pnr: str):
    with db.pool.connection() as conn:
        return _booking_view(conn, pnr.upper())


@app.post("/bookings/{pnr}/cancel")
def cancel_booking(pnr: str):
    pnr = pnr.upper()
    with db.pool.connection() as conn:
        row = conn.execute(
            """
            SELECT b.id, b.status, t.departure
            FROM bookings b JOIN trips t ON t.id = b.trip_id
            WHERE b.pnr = %s
            FOR UPDATE OF b          -- lock this booking so two cancels can't race
            """,
            (pnr,),
        ).fetchone()
        if not row:
            raise problem(404, "PNR_NOT_FOUND", "no booking with that PNR")
        if row["status"] == "CANCELLED":
            raise problem(409, "ALREADY_CANCELLED", "this booking is already cancelled")
        if row["departure"] <= datetime.now(UTC):
            raise problem(409, "TRIP_DEPARTED", "cannot cancel after departure")
        conn.execute("UPDATE bookings SET status='CANCELLED', cancelled_at=now() WHERE id=%s", (row["id"],))
        conn.execute("UPDATE tickets SET status='CANCELLED' WHERE booking_id=%s", (row["id"],))
        log.info("booking cancelled", extra={"fields": {"pnr": pnr}})
        view = _booking_view(conn, pnr)
    BOOKINGS.labels("cancelled").inc()
    return view
