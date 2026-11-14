-- Schema is idempotent: safe to run on every start.

CREATE TABLE IF NOT EXISTS routes (
    id          SERIAL PRIMARY KEY,
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL
);

-- Ordered stops on a route. seq 1 is the origin, the highest seq is the destination.
CREATE TABLE IF NOT EXISTS route_stops (
    route_id INT  NOT NULL REFERENCES routes(id),
    seq      INT  NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY (route_id, seq),
    UNIQUE (route_id, name)
);

CREATE TABLE IF NOT EXISTS trips (
    id             SERIAL PRIMARY KEY,
    route_id       INT  NOT NULL REFERENCES routes(id),
    departure      TIMESTAMPTZ NOT NULL,
    bus_type       TEXT NOT NULL,
    price_inr      INT  NOT NULL CHECK (price_inr > 0),
    UNIQUE (route_id, departure)
);

-- One row per physical seat on a trip (the seat map).
CREATE TABLE IF NOT EXISTS seats (
    trip_id INT  NOT NULL REFERENCES trips(id),
    seat_no TEXT NOT NULL,
    PRIMARY KEY (trip_id, seat_no)
);

CREATE TABLE IF NOT EXISTS bookings (
    id             SERIAL PRIMARY KEY,
    pnr            TEXT NOT NULL UNIQUE,
    trip_id        INT  NOT NULL REFERENCES trips(id),
    status         TEXT NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    contact_phone  TEXT NOT NULL,
    boarding_stop  TEXT NOT NULL,
    drop_stop      TEXT NOT NULL,
    total_inr      INT  NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at   TIMESTAMPTZ
);

-- One row per passenger/seat inside a booking.
CREATE TABLE IF NOT EXISTS tickets (
    id             SERIAL PRIMARY KEY,
    booking_id     INT  NOT NULL REFERENCES bookings(id),
    trip_id        INT  NOT NULL,
    seat_no        TEXT NOT NULL,
    passenger_name TEXT NOT NULL,
    passenger_age  INT  NOT NULL CHECK (passenger_age BETWEEN 1 AND 120),
    gender         TEXT NOT NULL CHECK (gender IN ('M', 'F', 'O')),
    status         TEXT NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    FOREIGN KEY (trip_id, seat_no) REFERENCES seats(trip_id, seat_no)
);

-- THE core rule, enforced by the database itself:
-- a seat on a trip can have at most ONE confirmed ticket.
-- Cancelled tickets are ignored by this index, so a cancelled seat can be rebooked.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_confirmed_seat
    ON tickets (trip_id, seat_no)
    WHERE status = 'CONFIRMED';
