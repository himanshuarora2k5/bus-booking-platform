import pytest

from tests.conftest import booking_body


def test_health(client):
    assert client.get("/health/live").json()["status"] == "ok"
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "up"


def test_routes_and_trips(client):
    routes = client.get("/routes").json()
    assert {r["origin"] for r in routes} == {"Ludhiana", "Chandigarh", "Jalandhar"}
    assert routes[0]["stops"][0] == "Ludhiana"

    trips = client.get("/trips", params={"origin": "ludhiana"}).json()  # case-insensitive
    assert trips and all(t["origin"] == "Ludhiana" for t in trips)
    assert trips[0]["available_seats"] == 20

    day = trips[0]["departure"][:10]
    same_day = client.get("/trips", params={"origin": "Ludhiana", "date": day}).json()
    assert same_day and all(t["departure"].startswith(day) for t in same_day)
    assert client.get("/trips", params={"date": "2026-13-45"}).status_code == 422


def test_seat_map(client, trip):
    seats = client.get(f"/trips/{trip['id']}/seats").json()["seats"]
    assert len(seats) == 20
    assert seats[0] == {"seat_no": "1A", "booked": False}
    assert client.get("/trips/999999/seats").status_code == 404


def test_create_booking(client, trip):
    r = client.post("/bookings", json=booking_body(trip, seats=("1A", "1B")))
    assert r.status_code == 201
    b = r.json()
    assert len(b["pnr"]) == 10 and b["status"] == "CONFIRMED"
    assert b["total_inr"] == trip["price_inr"] * 2
    assert [p["seat_no"] for p in b["passengers"]] == ["1A", "1B"]

    seats = {s["seat_no"]: s["booked"] for s in client.get(f"/trips/{trip['id']}/seats").json()["seats"]}
    assert seats["1A"] and seats["1B"] and not seats["1C"]
    assert client.get(f"/bookings/{b['pnr'].lower()}").json()["pnr"] == b["pnr"]  # PNR lookup ignores case


def test_conflicting_seat_fails_safely(client, trip):
    first = client.post("/bookings", json=booking_body(trip, seats=("2A",)))
    assert first.status_code == 201

    second = client.post("/bookings", json=booking_body(trip, seats=("2A",)))
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "SEAT_ALREADY_BOOKED"

    # Nothing extra was created: still exactly one booking with a PNR.
    assert client.get(f"/bookings/{first.json()['pnr']}").status_code == 200


def test_booking_is_all_or_nothing(client, trip):
    client.post("/bookings", json=booking_body(trip, seats=("3A",)))
    # Wants 3B (free) and 3A (taken): the whole booking must fail, and 3B must stay free.
    r = client.post("/bookings", json=booking_body(trip, seats=("3B", "3A")))
    assert r.status_code == 409
    seats = {s["seat_no"]: s["booked"] for s in client.get(f"/trips/{trip['id']}/seats").json()["seats"]}
    assert seats["3A"] is True and seats["3B"] is False


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"travel_date": "2030-01-01"}, "TRAVEL_DATE_MISMATCH"),
        ({"boarding_stop": "Delhi", "drop_stop": "Ludhiana"}, "STOP_ORDER"),
        ({"boarding_stop": "Atlantis"}, "UNKNOWN_STOP"),
    ],
)
def test_business_validation(client, trip, change, code):
    r = client.post("/bookings", json=booking_body(trip, **change))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == code


def test_unknown_seat(client, trip):
    r = client.post("/bookings", json=booking_body(trip, seats=("9Z",)))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "UNKNOWN_SEAT"


def test_past_trip_rejected(client, past_trip):
    body = {
        "trip_id": past_trip["id"],
        "travel_date": past_trip["date"],
        "boarding_stop": "Ludhiana",
        "drop_stop": "Delhi",
        "contact_phone": "9876543210",
        "passengers": [{"name": "Asha Rao", "age": 30, "gender": "F", "seat_no": "1A"}],
    }
    r = client.post("/bookings", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TRIP_DEPARTED"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.update(contact_phone="12345"),
        lambda b: b["passengers"][0].update(age=0),
        lambda b: b["passengers"][0].update(age=121),
        lambda b: b["passengers"][0].update(name="X"),
        lambda b: b["passengers"][0].update(name="Robert'); DROP TABLE tickets;--"),
        lambda b: b["passengers"][0].update(gender="Z"),
        lambda b: b.update(passengers=[]),
        lambda b: b.update(passengers=b["passengers"] * 2),  # same seat twice
    ],
)
def test_passenger_validation(client, trip, mutation):
    body = booking_body(trip)
    mutation(body)
    assert client.post("/bookings", json=body).status_code == 422


def test_cancel_frees_the_seat(client, trip):
    pnr = client.post("/bookings", json=booking_body(trip, seats=("4A",))).json()["pnr"]

    cancelled = client.post(f"/bookings/{pnr}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["passengers"][0]["status"] == "CANCELLED"

    # Seat is free again and can be booked by someone else, under a different PNR.
    again = client.post("/bookings", json=booking_body(trip, seats=("4A",)))
    assert again.status_code == 201 and again.json()["pnr"] != pnr


def test_cancel_errors(client, trip):
    pnr = client.post("/bookings", json=booking_body(trip, seats=("4B",))).json()["pnr"]
    client.post(f"/bookings/{pnr}/cancel")
    assert client.post(f"/bookings/{pnr}/cancel").status_code == 409  # already cancelled
    assert client.post("/bookings/NOSUCHPNR1/cancel").status_code == 404


def test_database_outage_returns_503_not_a_crash(client, trip, monkeypatch):
    from psycopg_pool import PoolTimeout

    from app import db

    def no_connection(*args, **kwargs):
        raise PoolTimeout("simulated outage")

    monkeypatch.setattr(db.pool, "connection", no_connection)
    r = client.post("/bookings", json=booking_body(trip))
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "DB_UNAVAILABLE"
    assert client.get("/health/live").status_code == 200  # process is alive...
    assert client.get("/health/ready").status_code == 503  # ...but not ready


def _metric(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "{"):
            if line.split()[0] == name:
                return float(line.split()[-1])
    return 0.0


def test_metrics_report_bookings_and_conflicts(client, trip):
    before = client.get("/metrics").text
    confirmed0 = _metric(before, 'bookings_total{outcome="confirmed"}')
    conflicts0 = _metric(before, 'bookings_total{outcome="seat_conflict"}')

    assert client.post("/bookings", json=booking_body(trip, seats=("2C",))).status_code == 201
    assert client.post("/bookings", json=booking_body(trip, seats=("2C",))).status_code == 409

    after = client.get("/metrics").text
    assert _metric(after, 'bookings_total{outcome="confirmed"}') == confirmed0 + 1
    assert _metric(after, 'bookings_total{outcome="seat_conflict"}') == conflicts0 + 1
    assert _metric(after, "app_database_up") == 1.0
    assert 'route="/trips/{trip_id}/seats"' in after or "http_requests_total" in after


def test_fault_switch_makes_service_not_ready(client, monkeypatch):
    monkeypatch.setenv("FAULT_READY_FAIL", "true")
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["reason"] == "fault injected"
    assert client.get("/health/live").status_code == 200
