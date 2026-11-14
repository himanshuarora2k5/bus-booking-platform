"""Test setup. Tests run against a REAL PostgreSQL (not a fake), because the
most important rule - no double booking - is enforced by the database itself."""

import os
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

TEST_URL = os.environ.get("DATABASE_URL", "")


def _require_test_database() -> None:
    # Safety lock: the tests wipe the database, so refuse anything not named *test*.
    name = TEST_URL.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name:
        pytest.exit(
            f"Refusing to run: DATABASE_URL must point at a database with 'test' in its name "
            f"(got '{name or 'none'}'). The tests erase all data.",
            returncode=2,
        )


@pytest.fixture(scope="session")
def client():
    _require_test_database()
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    from app.main import app  # imported late so DATABASE_URL is already set

    with TestClient(app) as c:  # starting the client runs the app's startup: schema + seed
        yield c


@pytest.fixture(autouse=True)
def clean_bookings(client):
    """Every test starts with zero bookings (trips/seats from the seed stay)."""
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE tickets, bookings RESTART IDENTITY CASCADE")
        conn.execute("DELETE FROM seats WHERE trip_id IN (SELECT id FROM trips WHERE departure < now())")
        conn.execute("DELETE FROM trips WHERE departure < now()")
    yield


@pytest.fixture()
def trip(client):
    """The first upcoming Ludhiana -> Delhi trip."""
    rows = client.get("/trips", params={"origin": "Ludhiana", "destination": "Delhi"}).json()
    return rows[0]


@pytest.fixture()
def past_trip():
    """A trip that already departed (inserted directly, since the API only lists future trips)."""
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        trip_id = conn.execute(
            "INSERT INTO trips (route_id, departure, bus_type, price_inr) "
            "VALUES (1, now() - interval '1 day', 'AC Seater', 500) RETURNING id"
        ).fetchone()[0]
        conn.execute("INSERT INTO seats (trip_id, seat_no) VALUES (%s, '1A')", (trip_id,))
        departure = conn.execute("SELECT departure FROM trips WHERE id=%s", (trip_id,)).fetchone()[0]
    return {"id": trip_id, "date": (departure + timedelta(hours=5, minutes=30)).date().isoformat()}


NAMES = ["Asha Rao", "Ravi Kumar", "Meera Singh", "Imran Khan", "Joseph Dsouza", "Priya Nair"]


def booking_body(trip, seats=("1A",), **overrides):
    body = {
        "trip_id": trip["id"],
        "travel_date": trip["departure"][:10],
        "boarding_stop": "Ludhiana",
        "drop_stop": "Delhi",
        "contact_phone": "9876543210",
        "passengers": [
            {"name": NAMES[i], "age": 30, "gender": "M", "seat_no": s} for i, s in enumerate(seats)
        ],
    }
    body.update(overrides)
    return body
