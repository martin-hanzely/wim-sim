"""Ask Grafana to run every panel, the way the browser does.

    python scripts/check_dashboards.py

``tests/test_dashboards.py`` checks the half of the contract that needs no stack -- that every
panel names a declared metric and a provisioned datasource. This checks the other half, and it
needs the stack up: that Grafana can actually reach TimescaleDB and Prometheus, that the credentials
the container was handed work, and that each query returns rows. All three have gone wrong at least
once in this project, and each time the symptom was an empty graph rather than an error.

Empty panels are reported but are not failures. Several are legitimately empty: the drift detectors
and controller state arrive in phase 5, the sample stream is off unless a station is publishing
samples, and a clean run has no publish failures, no dead letters and no sample gaps to draw.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request

GRAFANA = "http://localhost:3000"
AUTH = base64.b64encode(b"admin:admin").decode()
DS_TYPES = {
    "wimsim-timescale": "grafana-postgresql-datasource",
    "wimsim-prometheus": "prometheus",
}


def call(path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{GRAFANA}{path}",
        data=data,
        headers={"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"_error": f"{exc.code} {exc.read()[:200].decode('utf-8', 'replace')}"}


def rows_of(result: dict) -> int:
    for frame in result.get("frames") or []:
        values = frame.get("data", {}).get("values") or []
        if values and values[0]:
            return len(values[0])
    return 0


STATIONS = "'ST-DEMO-01'"
TOLERANCE = "0.25"


def interpolate(sql: str) -> str:
    """Grafana interpolates template variables in the browser, before /api/ds/query sees them.

    Sending the raw `$station` gets a Postgres syntax error, which says nothing about the panel.
    """
    return sql.replace("($station)", f"({STATIONS})").replace("$tolerance", TOLERANCE)


def main() -> int:
    now = int(time.time() * 1000)
    # Wide enough to cover the demo run's own epoch as well as anything live.
    start = str(now - 3 * 365 * 24 * 3600 * 1000)
    # Prometheus refuses more than 11k points per query, so its panels get a live-sized window.
    prom_start = str(now - 3600 * 1000)

    failures = 0
    empty = 0
    for board in call("/api/search?type=dash-db"):
        full = call(f"/api/dashboards/uid/{board['uid']}")["dashboard"]
        print(f"\n=== {full['title']}")
        for panel in full["panels"]:
            for target in panel.get("targets", []):
                uid = (panel.get("datasource") or {}).get("uid")
                if uid not in DS_TYPES:
                    continue
                query = dict(target)
                query["datasource"] = {"type": DS_TYPES[uid], "uid": uid}
                query.setdefault("refId", "A")
                query["intervalMs"] = 60000
                query["maxDataPoints"] = 1000
                if uid == "wimsim-prometheus":
                    query["range"] = True
                if query.get("rawSql"):
                    query["rawSql"] = interpolate(query["rawSql"])
                window_start = prom_start if uid == "wimsim-prometheus" else start
                body = call(
                    "/api/ds/query", {"queries": [query], "from": window_start, "to": str(now)}
                )
                label = f"{panel['title']} [{query['refId']}]"
                if "_error" in body:
                    failures += 1
                    print(f"  FAIL   {label}: {body['_error']}")
                    continue
                result = next(iter(body.get("results", {}).values()), {})
                if result.get("error"):
                    failures += 1
                    print(f"  FAIL   {label}: {result['error'][:140]}")
                    continue
                n = rows_of(result)
                if n:
                    print(f"  ok     {label}: {n} points")
                else:
                    empty += 1
                    print(f"  EMPTY  {label}")
    print(f"\n{failures} failures, {empty} empty")
    return failures


if __name__ == "__main__":
    sys.exit(min(main(), 1))
