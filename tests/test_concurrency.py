"""The headline test: many people grab the same seat at the same instant."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg

from tests.conftest import TEST_URL, booking_body

PEOPLE = 25


def test_simultaneous_bookings_for_one_seat(client, trip):
    start_line = Barrier(PEOPLE)  # everyone waits here, then all fire together

    def try_to_book(_: int) -> int:
        body = booking_body(trip, seats=("5D",))
        start_line.wait()
        return client.post("/bookings", json=body).status_code

    with ThreadPoolExecutor(max_workers=PEOPLE) as pool:
        codes = list(pool.map(try_to_book, range(PEOPLE)))

    assert codes.count(201) == 1, f"expected exactly one winner, got {codes}"
    assert codes.count(409) == PEOPLE - 1, f"all others must get a clean conflict, got {codes}"

    # Check the database itself, not just the HTTP answers.
    with psycopg.connect(TEST_URL) as conn:
        bookings = conn.execute("SELECT count(*) FROM bookings").fetchone()[0]
        confirmed = conn.execute(
            "SELECT count(*) FROM tickets WHERE trip_id=%s AND seat_no='5D' AND status='CONFIRMED'",
            (trip["id"],),
        ).fetchone()[0]
        distinct_pnrs = conn.execute("SELECT count(DISTINCT pnr) FROM bookings").fetchone()[0]
    assert (bookings, confirmed, distinct_pnrs) == (1, 1, 1)
