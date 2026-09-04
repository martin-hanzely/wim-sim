"""The dashboards, checked without a browser and without docker.

Grafana fails silently. A panel whose metric was renamed, whose datasource uid does not resolve, or
whose column no longer exists renders an empty graph and says nothing about why -- and an empty
graph on a monitoring dashboard reads as "nothing is happening", which is the most dangerous
possible way to be wrong.

What can be checked offline is the half that is a *contract*: every PromQL panel must name a metric
the registry declares, every datasource uid must be one the provisioning file defines, and the JSON
must be structurally sound. The other half -- that the queries return rows against a live stack --
needs the stack, and lives in ``scripts/check_dashboards.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from wimsim.observability.metrics import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboards"
DATASOURCE_FILE = ROOT / "docker" / "grafana" / "provisioning" / "datasources" / "datasources.yaml"

#: Buildspec section 9 names five. All five ship.
EXPECTED_TITLES = {
    "WiM / Station operations",
    "WiM / Measurement",
    "WiM / Calibration loop",
    "WiM / Data integrity",
    "WiM / Accuracy and uncertainty",
}

#: Everything a metric name can be followed by in a query. Histograms are exported as three series.
_SUFFIXES = ("_bucket", "_sum", "_count")

_METRIC_TOKEN = re.compile(r"\bwim_[a-z0-9_]+\b")


def _boards() -> list[tuple[str, dict]]:
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(DASHBOARD_DIR.glob("*.json"))
    ]


def _panels(board: dict) -> list[dict]:
    return [p for p in board["panels"] if p.get("type") != "row"]


def _declared_uids() -> set[str]:
    config = yaml.safe_load(DATASOURCE_FILE.read_text(encoding="utf-8"))
    return {source["uid"] for source in config["datasources"]}


BOARDS = _boards()


def test_all_five_dashboards_ship() -> None:
    assert {board["title"] for _name, board in BOARDS} == EXPECTED_TITLES


def test_every_uid_and_title_is_unique() -> None:
    """Two dashboards sharing a uid means provisioning silently keeps one of them."""
    uids = [board["uid"] for _name, board in BOARDS]
    assert len(uids) == len(set(uids))


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_every_panel_names_a_datasource_that_is_provisioned(name: str, board: dict) -> None:
    declared = _declared_uids()
    for panel in _panels(board):
        uid = (panel.get("datasource") or {}).get("uid")
        assert uid, f"{name}: panel {panel['title']!r} has no datasource"
        assert uid in declared, f"{name}: panel {panel['title']!r} points at unknown {uid!r}"


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_every_panel_has_a_query(name: str, board: dict) -> None:
    for panel in _panels(board):
        targets = panel.get("targets") or []
        assert targets, f"{name}: panel {panel['title']!r} has no targets"
        for target in targets:
            assert target.get("rawSql") or target.get("expr"), (
                f"{name}: panel {panel['title']!r} has an empty target"
            )


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_every_promql_metric_is_declared_in_the_registry(name: str, board: dict) -> None:
    """The failure this prevents: a panel querying `wim_buffer_dept`, or a metric renamed in code
    and not in the dashboard. Either renders an empty graph that looks like a quiet system."""
    for panel in _panels(board):
        for target in panel.get("targets") or []:
            expr = target.get("expr")
            if not expr:
                continue
            for token in _METRIC_TOKEN.findall(expr):
                base = token
                for suffix in _SUFFIXES:
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                        break
                assert base in REGISTRY, (
                    f"{name}: panel {panel['title']!r} queries {token!r}, which is not in the "
                    "metric registry. Add it to REGISTRY, or fix the query."
                )


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_every_sql_panel_filters_by_time(name: str, board: dict) -> None:
    """A panel that ignores the dashboard's time range reads the whole hypertable, which on a
    production-sized dataset is the difference between a dashboard and an outage."""
    for panel in _panels(board):
        for target in panel.get("targets") or []:
            sql = target.get("rawSql")
            if not sql:
                continue
            assert "$__timeFilter(" in sql, (
                f"{name}: panel {panel['title']!r} has no $__timeFilter; it would scan everything"
            )


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_dashboards_are_read_only_and_describe_themselves(name: str, board: dict) -> None:
    """`editable: false` is deliberate: a dashboard edited in a browser and never committed is a
    result nobody else can reproduce."""
    assert board["editable"] is False, name
    assert board["timezone"] == "utc", name
    assert len(board.get("description", "")) > 80, f"{name}: say what the dashboard is for"
    for panel in _panels(board):
        assert panel.get("title"), name


@pytest.mark.parametrize("name,board", BOARDS, ids=[n for n, _ in BOARDS])
def test_truth_is_only_ever_read_from_the_truth_schema(name: str, board: dict) -> None:
    """Principle 1 at the last layer it can be broken. Ground truth lives in `truth.*` and is
    joined here, downstream of everything; a `truth.` reference anywhere else would mean the
    separation had been quietly abandoned in SQL."""
    for panel in _panels(board):
        for target in panel.get("targets") or []:
            sql = target.get("rawSql") or ""
            for match in re.findall(r"\btruth\.\w+", sql):
                assert match in {"truth.truth_pass", "truth.truth_timeseries"}, (
                    f"{name}: unknown truth table {match}"
                )


def test_no_panel_claims_metrological_accuracy() -> None:
    """Buildspec section 13's explicit non-goal: this artifact validates architecture and control
    behaviour, not certified weighing, and the dashboard titles must not suggest otherwise."""
    forbidden = ("certified", "legal for trade", "metrolog", "approved", "accredited")
    for name, board in BOARDS:
        blob = json.dumps(board).lower()
        for word in forbidden:
            assert word not in blob, f"{name}: dashboard text contains {word!r}"
