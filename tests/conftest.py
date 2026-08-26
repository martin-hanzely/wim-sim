"""Shared fixtures.

Everything here is small on purpose: the tests exist to check behaviour, and a 900-second run at
2 kHz is not needed to establish that a filter is causal. ``short_cfg`` is a 60 s S1 with the same
physics and one-fifteenth the cost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wimsim.core.config import RunConfig, load_run_config

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "wimsim"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def src_root() -> Path:
    return SRC_ROOT


@pytest.fixture
def short_cfg() -> RunConfig:
    """S1_nominal, 60 s, full sample retention."""
    return load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=full",
        ],
    )


@pytest.fixture
def short_run(tmp_path: Path, short_cfg: RunConfig):
    from wimsim.signal.writer import write_run

    return write_run(short_cfg, tmp_path / "run")
