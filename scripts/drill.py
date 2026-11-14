#!/usr/bin/env python3
"""
PROOF DRILL - deliberately breaks the system in several ways and records evidence that it
notices the problem and recovers. Uses only the Python standard library (nothing to install).

Run it from the project folder while the stack is running:

    python3 scripts/drill.py                  full drill (about 4-6 minutes)
    python3 scripts/drill.py --video          same, but skips the extra "good release" step
    python3 scripts/drill.py --only race,db-outage
    python3 scripts/drill.py --public-url https://yourname.centralindia.cloudapp.azure.com

Evidence is written to evidence/drill-<time>/ (report.md, report.json, drill.log)
and copied to evidence/LATEST.md.
"""

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import pathlib
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
UTC = dt.UTC
STAMP = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
NAMES = ["Asha Rao", "Ravi Kumar", "Meera Singh", "Imran Khan"]
LOG_LINES: list[str] = []
CTX: dict = {}


# ----------------------------------------------------------------------------- small helpers
def read_env() -> dict:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = read_env()
COLOR = sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def say(message: str = "", style: str = "") -> None:
    line = f"{dt.datetime.now(UTC).strftime('%H:%M:%S')}  {message}"
    LOG_LINES.append(line)
    print(paint(line, style) if style else line, flush=True)


def http(method: str, url: str, body=None, timeout: float = 10, verify: bool = True):
    """Returns (status_code, parsed_json_or_text). Status 0 means 'could not connect'."""
    data, headers = None, {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    context = None
    if url.startswith("https") and not verify:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw, status = response.read().decode(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read().decode(), error.code
    except Exception as error:  # refused, timed out, DNS...
        return 0, str(error)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def run(cmd: list[str], timeout: int = 600, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)


def compose(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    result = run(["docker", "compose", *args], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {result.stderr.strip()[-300:]}")
    return result


def sql(query: str) -> str:
    result = compose(
        "exec", "-T", "db", "psql", "-U", ENV["POSTGRES_USER"], "-d", ENV["POSTGRES_DB"], "-tA", "-c", query
    )
    return result.stdout.strip()


def wait_for(check, timeout: float, interval: float = 0.5):
    """Calls check() until it is true. Returns the seconds it took, or None on timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if check():
                return round(time.time() - start, 1)
        except Exception:
            pass
        time.sleep(interval)
    return None


def ready() -> bool:
    return http("GET", f"{BASE}/health/ready", timeout=4)[0] == 200


def alert_firing(name: str) -> bool:
    status, body = http("GET", f"{ARGS.prom_url}/api/v1/alerts", timeout=4)
    if status != 200:
        return False
    return any(
        a["labels"].get("alertname") == name and a["state"] == "firing" for a in body["data"]["alerts"]
    )


def pick_seat():
    status, trips = http("GET", f"{BASE}/trips?origin=Ludhiana&destination=Delhi")
    assert status == 200 and trips, "could not list trips"
    for trip in trips:
        _, seat_map = http("GET", f"{BASE}/trips/{trip['id']}/seats")
        free = [s["seat_no"] for s in seat_map["seats"] if not s["booked"]]
        if free:
            return trip, free[-1]
    raise AssertionError("no free seat found on any trip")


def booking_body(trip: dict, seat: str) -> dict:
    return {
        "trip_id": trip["id"],
        "travel_date": trip["departure"][:10],
        "boarding_stop": "Ludhiana",
        "drop_stop": "Delhi",
        "contact_phone": "9876543210",
        "passengers": [{"name": NAMES[0], "age": 30, "gender": "F", "seat_no": seat}],
    }


# ----------------------------------------------------------------------------- scenarios
def s_preflight():
    live_status, _ = http("GET", f"{BASE}/health/live")
    ready_status, body = http("GET", f"{BASE}/health/ready")
    assert live_status == 200, f"/health/live returned {live_status}"
    assert ready_status == 200 and body.get("database") == "up", (
        f"/health/ready returned {ready_status}: {body}"
    )
    CTX["start_version"] = body["version"]
    return [f"/health/live = 200, /health/ready = 200, database up, running version `{body['version']}`"]


def s_front_door():
    url = ARGS.public_url or ARGS.proxy_url
    verify = bool(ARGS.public_url)
    status, body = http("GET", f"{url}/health/ready", verify=verify, timeout=15)
    assert status == 200, f"HTTPS request to {url} returned {status}: {body}"
    metrics_status, _ = http("GET", f"{url}/metrics", verify=verify, timeout=15)
    assert metrics_status == 404, f"/metrics must be hidden from outside but returned {metrics_status}"
    details = [
        f"HTTPS `{url}/health/ready` = 200",
        "`/metrics` through the front door = 404 (hidden from the public)",
    ]
    if verify:
        parsed = urlparse(url)
        context = ssl.create_default_context()
        with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=parsed.hostname) as tls:
                cert = tls.getpeercert()
        issuer = dict(x[0] for x in cert["issuer"]).get("organizationName", "unknown")
        details.append(
            f"certificate is trusted by this computer, issued by {issuer}, valid until {cert['notAfter']}"
        )
    else:
        details.append("local certificate (made by the proxy itself, so browsers warn about it)")
    return details


def s_race():
    clients = ARGS.clients
    trip, seat = pick_seat()
    before = int(sql("SELECT count(*) FROM bookings"))
    body = booking_body(trip, seat)
    gate = threading.Barrier(clients)

    def one(_):
        gate.wait()  # everyone waits here, then all fire at the same instant
        start = time.perf_counter()
        status, js = http("POST", f"{BASE}/bookings", body, timeout=30)
        return status, js, time.perf_counter() - start

    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        results = list(pool.map(one, range(clients)))
    codes = [r[0] for r in results]
    assert codes.count(201) == 1, (
        f"expected exactly 1 winner, got {codes.count(201)} (all codes: {sorted(set(codes))})"
    )
    assert codes.count(409) == clients - 1, f"expected {clients - 1} clean conflicts, got {codes.count(409)}"
    pnr = next(r[1]["pnr"] for r in results if r[0] == 201)
    created = int(sql("SELECT count(*) FROM bookings")) - before
    confirmed = int(
        sql(
            f"SELECT count(*) FROM tickets WHERE trip_id={trip['id']} AND seat_no='{seat}' AND status='CONFIRMED'"
        )
    )
    assert created == 1, f"database gained {created} bookings, expected exactly 1 (no extra PNRs)"
    assert confirmed == 1, f"database has {confirmed} confirmed tickets for the seat, expected 1"
    latencies = sorted(r[2] for r in results)
    CTX.update(pnr=pnr, trip=trip, seat=seat)
    return [
        f"{clients} clients tried to book seat {seat} on trip {trip['id']} at the same instant",
        f"result: 1 x HTTP 201 (winner, PNR {pnr}), {codes.count(409)} x HTTP 409 (clean 'seat taken')",
        f"database check: {created} new booking, {confirmed} confirmed ticket for that seat (no duplicate PNR)",
        f"response time: median {latencies[len(latencies) // 2] * 1000:.0f} ms, slowest {latencies[-1] * 1000:.0f} ms",
    ]


def s_cancel_rebook():
    pnr, trip, seat = CTX["pnr"], CTX["trip"], CTX["seat"]
    status, cancelled = http("POST", f"{BASE}/bookings/{pnr}/cancel")
    assert status == 200 and cancelled["status"] == "CANCELLED", f"cancel returned {status}: {cancelled}"
    _, seat_map = http("GET", f"{BASE}/trips/{trip['id']}/seats")
    assert not next(s for s in seat_map["seats"] if s["seat_no"] == seat)["booked"], "seat was not freed"
    status, again = http("POST", f"{BASE}/bookings", booking_body(trip, seat))
    assert status == 201 and again["pnr"] != pnr, f"rebooking returned {status}: {again}"
    CTX["pnr"] = again["pnr"]
    return [f"cancelled {pnr}, seat {seat} became free, rebooked as new PNR {again['pnr']}"]


def s_db_outage():
    trip, seat = CTX["trip"], CTX["seat"]
    compose("stop", "db")
    stopped_at = time.time()
    say("    database stopped on purpose ...")
    detect = wait_for(lambda: http("GET", f"{BASE}/health/ready", timeout=4)[0] == 503, 30)
    assert detect is not None, "/health/ready never reported 503 while the database was down"
    live_status, _ = http("GET", f"{BASE}/health/live")
    assert live_status == 200, "/health/live should stay 200 (the process itself is fine)"
    book_status, book_body = http("POST", f"{BASE}/bookings", booking_body(trip, seat), timeout=20)
    assert book_status == 503, f"booking during outage should give a clean 503, got {book_status}"
    details = [
        f"database container stopped; `/health/ready` turned 503 after {detect}s while `/health/live` stayed 200",
        "a booking attempt during the outage got a clean HTTP 503 (no crash, no wrong data)",
    ]
    prom_status, _ = http("GET", f"{ARGS.prom_url}/api/v1/alerts", timeout=4)
    if prom_status == 200:
        fired = wait_for(lambda: alert_firing("DatabaseDown"), 60)
        assert fired is not None, "the DatabaseDown alert never fired within 60s"
        details.append(
            f"Prometheus alert `DatabaseDown` was FIRING {round(time.time() - stopped_at, 1)}s after the failure"
        )
    else:
        details.append("Prometheus not reachable from here - alert check skipped")
    compose("start", "db")
    started_at = time.time()
    recover = wait_for(ready, 90)
    assert recover is not None, "service did not become ready again after the database came back"
    status, booking = http("GET", f"{BASE}/bookings/{CTX['pnr']}")
    assert status == 200, f"booking {CTX['pnr']} was lost after the outage (status {status})"
    details.append(
        f"database started again; service ready after {round(time.time() - started_at, 1)}s with NO restart of the app"
    )
    details.append(f"data intact: booking {CTX['pnr']} is still there ({booking['status']})")
    return details


def s_backup_restore():
    pnr = CTX["pnr"]
    backup = run(["bash", "scripts/backup.sh"])
    assert backup.returncode == 0, f"backup failed: {backup.stderr[-300:]}"
    path = backup.stdout.strip().splitlines()[-1]
    size = (ROOT / path).stat().st_size
    assert size > 0, "backup file is empty"
    verify = run(["bash", "scripts/verify_backup.sh"])
    assert verify.returncode == 0 and "PASS" in verify.stdout, (
        f"backup verification failed: {verify.stderr[-300:]}"
    )
    sql("TRUNCATE tickets, bookings RESTART IDENTITY CASCADE")  # the "disaster"
    lost_status, _ = http("GET", f"{BASE}/bookings/{pnr}")
    assert lost_status == 404, f"expected the booking to be gone after the disaster, got {lost_status}"
    say("    all bookings deleted on purpose; restoring from backup ...")
    started = time.time()
    restore = run(["bash", "scripts/restore.sh", path, "--yes"])
    assert restore.returncode == 0, f"restore failed: {restore.stderr[-300:]}"
    status, booking = http("GET", f"{BASE}/bookings/{pnr}")
    assert status == 200, f"booking {pnr} did not come back after the restore (status {status})"
    return [
        f"backup `{path}` ({size // 1024 or 1} KB), gzip test and SHA-256 fingerprint OK",
        "verification: a fresh backup restored into a SCRATCH database matched the live data exactly",
        f"disaster: every booking deleted (booking {pnr} returned 404)",
        f"restore from backup took {round(time.time() - started, 1)}s; booking {pnr} is back ({booking['status']})",
    ]


def s_good_release():
    label = f"drill-{STAMP}-good"
    result = run(["bash", "scripts/deploy.sh", label])
    assert result.returncode == 0, f"deploy failed: {(result.stderr or result.stdout)[-400:]}"
    status, body = http("GET", f"{BASE}/health/ready")
    assert status == 200 and body["version"] == label, f"expected version {label}, got {body}"
    return [f"deployed version `{label}`: built, started, passed the health gate and went live"]


def s_bad_release():
    if not (ROOT / ".deploy" / "current").exists():
        run(["bash", "scripts/deploy.sh", f"drill-{STAMP}-baseline"])
    _, before = http("GET", f"{BASE}/health/ready")
    before_version = before["version"]
    label = f"drill-{STAMP}-bad"
    say(f"    shipping a deliberately broken release `{label}` ...")
    result = run(
        ["bash", "scripts/deploy.sh", label, "--simulate-bad-release"], env_extra={"READY_TIMEOUT": "25"}
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, "a broken release must make the deploy script report failure"
    assert "ROLLED BACK" in output, f"no rollback message found: {output[-400:]}"
    status, after = http("GET", f"{BASE}/health/ready")
    assert status == 200 and after["version"] == before_version, (
        f"expected {before_version} to be live again, got {after}"
    )
    return [
        f"broken release `{label}` started but never became ready within the 25s health gate",
        f"automatic rollback: `{before_version}` is serving traffic again (HTTP 200)",
        "deploy history is in `.deploy/history.log`",
    ]


def s_crash_restart():
    container = compose("ps", "-q", "app").stdout.strip()
    assert container, "app container not found"

    def restarts() -> int:
        return int(run(["docker", "inspect", "-f", "{{.RestartCount}}", container]).stdout.strip() or 0)

    before = restarts()
    # A real crash: the app's main process (PID 1 inside the container) is told to stop by itself.
    # (`docker kill` would count as a manual stop, and Docker deliberately does not restart those.)
    crash = run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "app",
            "python",
            "-c",
            "import os, signal; os.kill(1, signal.SIGTERM)",
        ]
    )
    assert crash.returncode == 0, f"could not crash the app: {crash.stderr[-200:]}"
    say("    app process terminated on purpose ...")

    # Docker may restart the container just after the API starts answering again.
    # Check the restart counter first, otherwise a fast health response can win
    # the race and produce a false failure even though Docker did restart it.
    restart_seen = wait_for(lambda: restarts() > before, 30)
    if restart_seen is None:
        compose("start", "app")  # never leave the system broken
        wait_for(ready, 60)
        raise AssertionError(
            "Docker did not increase the container restart count after the app process exited"
        )

    recover = wait_for(ready, 60)
    if recover is None:
        compose("start", "app")  # never leave the system broken
        wait_for(ready, 60)
        raise AssertionError(
            "Docker restarted the container, but the application did not become ready (it was started again by hand)"
        )

    after = restarts()
    assert after > before, "restart count did not increase after the application process exited"
    return [
        f"app process terminated; Docker restarted the container by itself (restart count {before} -> {after}) and the service became ready after {restart_seen + recover}s"
    ]


SCENARIOS = [
    ("preflight", "Service healthy before we start", s_preflight),
    ("front-door", "HTTPS front door works, /metrics is hidden", s_front_door),
    ("race", "Many people grab the SAME seat at once", s_race),
    ("cancel-rebook", "Cancelling frees the seat for someone else", s_cancel_rebook),
    ("db-outage", "Database dies: detection, alert, recovery", s_db_outage),
    ("backup-restore", "Backup, total data loss, restore", s_backup_restore),
    ("good-release", "A normal release goes live", s_good_release),
    ("bad-release", "A broken release is rolled back automatically", s_bad_release),
    ("crash-restart", "App crashes: Docker restarts it by itself", s_crash_restart),
]


# ----------------------------------------------------------------------------- main
def environment_facts() -> dict:
    def out(cmd):
        try:
            return run(cmd, timeout=20).stdout.strip()
        except Exception:
            return "unknown"

    return {
        "date_utc": dt.datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "git_commit": out(["git", "rev-parse", "--short", "HEAD"]),
        "host": f"{platform.system()} {platform.release()} ({socket.gethostname()})",
        "docker": out(["docker", "--version"]),
        "target": ARGS.public_url or BASE,
    }


def write_report(results: list[dict], facts: dict) -> pathlib.Path:
    folder = ROOT / "evidence" / f"drill-{STAMP}"
    folder.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if r["ok"])
    lines = [
        "# Proof drill report",
        "",
        f"**Result: {passed} of {len(results)} scenarios passed**",
        "",
        "| | |",
        "|---|---|",
        f"| When | {facts['date_utc']} |",
        f"| Code version (git commit) | `{facts['git_commit']}` |",
        f"| Target | {facts['target']} |",
        f"| Machine | {facts['host']} |",
        f"| Docker | {facts['docker']} |",
        "",
        "| # | Scenario | Result | Seconds |",
        "|---|---|---|---|",
    ]
    for number, r in enumerate(results, 1):
        lines.append(f"| {number} | {r['title']} | {'PASS' if r['ok'] else 'FAIL'} | {r['seconds']} |")
    lines += ["", "## Evidence per scenario", ""]
    for number, r in enumerate(results, 1):
        lines.append(f"### {number}. {r['title']} - {'PASS' if r['ok'] else 'FAIL'}")
        lines.append("")
        lines += [f"- {d}" for d in r["details"]]
        lines.append("")
    history = ROOT / ".deploy" / "history.log"
    if history.exists():
        tail = "\n".join(history.read_text().splitlines()[-12:])
        lines += ["## Deployment history (last entries)", "", "```", tail, "```", ""]
    (folder / "report.md").write_text("\n".join(lines))
    (folder / "report.json").write_text(json.dumps({"facts": facts, "results": results}, indent=2))
    (folder / "drill.log").write_text("\n".join(LOG_LINES) + "\n")
    shutil.copyfile(folder / "report.md", ROOT / "evidence" / "LATEST.md")
    return folder


def main() -> int:
    skip = set(filter(None, ARGS.skip.split(",")))
    only = set(filter(None, ARGS.only.split(",")))
    if ARGS.video:
        skip.add("good-release")
    chosen = [s for s in SCENARIOS if (not only or s[0] in only) and s[0] not in skip]
    if only and "preflight" not in only:
        chosen.insert(0, SCENARIOS[0])
    facts = environment_facts()
    say(f"PROOF DRILL against {facts['target']}  (commit {facts['git_commit']})", "1;36")
    say(f"{len(chosen)} scenarios. Nothing is faked: every step really breaks and repairs the system.", "36")
    results = []
    for number, (key, title, function) in enumerate(chosen, 1):
        say("")
        say(f"STEP {number}/{len(chosen)} - {title}", "1")
        started = time.time()
        try:
            details = function()
            ok = True
        except Exception as error:  # a failed check or an unexpected problem
            ok = False
            details = [f"{type(error).__name__}: {error}"]
            if not isinstance(error, AssertionError):
                details.append(traceback.format_exc().strip().splitlines()[-3])
        seconds = round(time.time() - started, 1)
        for detail in details:
            say(f"    {detail}", "32" if ok else "31")
        say(f"    => {'PASS' if ok else 'FAIL'} ({seconds}s)", "1;32" if ok else "1;31")
        results.append({"id": key, "title": title, "ok": ok, "seconds": seconds, "details": details})
        if not ok and key in ("preflight", "race"):
            say("    stopping early: later steps depend on this one", "31")
            break
    folder = write_report(results, facts)
    passed = sum(1 for r in results if r["ok"])
    say("")
    say(f"SUMMARY: {passed}/{len(results)} passed. Evidence saved in {folder.relative_to(ROOT)}/", "1;36")
    say("A copy of the report is in evidence/LATEST.md", "36")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Proof drill: break it, watch it recover, keep the evidence."
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8000"), help="API address (direct)"
    )
    port = ENV.get("HTTPS_PORT", "8443")
    parser.add_argument(
        "--proxy-url",
        default=f"https://localhost{'' if port == '443' else ':' + port}",
        help="front door address",
    )
    parser.add_argument(
        "--public-url", default="", help="public HTTPS address (checks the certificate properly)"
    )
    parser.add_argument("--prom-url", default="http://127.0.0.1:9090", help="Prometheus address")
    parser.add_argument("--clients", type=int, default=50, help="people in the seat race")
    parser.add_argument("--only", default="", help="comma list of scenario ids to run")
    parser.add_argument("--skip", default="", help="comma list of scenario ids to skip")
    parser.add_argument("--video", action="store_true", help="shorter run for screen recording")
    ARGS = parser.parse_args()
    BASE = ARGS.base_url.rstrip("/")
    sys.exit(main())
