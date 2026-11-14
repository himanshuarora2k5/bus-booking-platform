-- Demo data. Trips are generated relative to today so the seed never goes stale.
INSERT INTO routes (origin, destination) VALUES
    ('Ludhiana', 'Delhi'),
    ('Chandigarh', 'Manali'),
    ('Jalandhar', 'Amritsar');

INSERT INTO route_stops (route_id, seq, name)
SELECT r.id, s.seq, s.name
FROM routes r
JOIN (VALUES
    ('Ludhiana',   1, 'Ludhiana'),
    ('Ludhiana',   2, 'Phagwara'),
    ('Ludhiana',   3, 'Ambala'),
    ('Ludhiana',   4, 'Delhi'),
    ('Chandigarh', 1, 'Chandigarh'),
    ('Chandigarh', 2, 'Bilaspur'),
    ('Chandigarh', 3, 'Kullu'),
    ('Chandigarh', 4, 'Manali'),
    ('Jalandhar',  1, 'Jalandhar'),
    ('Jalandhar',  2, 'Beas'),
    ('Jalandhar',  3, 'Amritsar')
) AS s(origin, seq, name) ON s.origin = r.origin;

-- Two departures per day for the next 10 days (starting tomorrow), per route.
-- Times are Indian Standard Time.
INSERT INTO trips (route_id, departure, bus_type, price_inr)
SELECT r.id,
       ((now() AT TIME ZONE 'Asia/Kolkata')::date + d.day_offset + t.dep_time) AT TIME ZONE 'Asia/Kolkata',
       t.bus_type,
       t.price
FROM routes r
CROSS JOIN generate_series(1, 10) AS d(day_offset)
CROSS JOIN (VALUES
    (TIME '06:30', 'AC Seater', 650),
    (TIME '21:00', 'AC Sleeper', 900)
) AS t(dep_time, bus_type, price);

-- 20 seats per trip: rows 1-5, columns A-D.
INSERT INTO seats (trip_id, seat_no)
SELECT tr.id, rw.n::text || c.col
FROM trips tr
CROSS JOIN generate_series(1, 5) AS rw(n)
CROSS JOIN (VALUES ('A'), ('B'), ('C'), ('D')) AS c(col);
