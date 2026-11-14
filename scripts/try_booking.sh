#!/usr/bin/env bash
# Try a booking by hand against the running service.
# Usage:  bash scripts/try_booking.sh [seat]        (default seat: 1A)
# Run it twice with the same seat: the first call books it (HTTP 201), the second is refused (HTTP 409).
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:8000}"
SEAT="${1:-1A}"

trip="$(curl -fsS "$BASE/trips?origin=Ludhiana&destination=Delhi" \
  | python3 -c 'import sys, json; t = json.load(sys.stdin)[0]; print(t["id"], t["departure"][:10])')"
read -r TRIP_ID DAY <<< "$trip"

body="$(python3 - "$TRIP_ID" "$DAY" "$SEAT" << 'PY'
import json, sys
trip_id, day, seat = sys.argv[1:4]
print(json.dumps({
    "trip_id": int(trip_id), "travel_date": day,
    "boarding_stop": "Ludhiana", "drop_stop": "Delhi", "contact_phone": "9876543210",
    "passengers": [{"name": "Asha Rao", "age": 30, "gender": "F", "seat_no": seat}],
}))
PY
)"

echo "Booking seat $SEAT on trip $TRIP_ID (departs $DAY) ..."
curl -sS -w '\nHTTP status: %{http_code}\n' -X POST "$BASE/bookings" -H 'content-type: application/json' -d "$body"
