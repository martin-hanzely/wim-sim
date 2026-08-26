"""Principle 4: same seed + same config => byte-identical output.

Three claims, tested separately because they can fail separately:

1. **Byte identity.** Two runs of the same config produce parquet files with identical bytes. This
   is the strong claim and the one the buildspec asks for.
2. **Value invariance to block size.** Changing ``block_seconds`` changes how the run is chopped up
   for generation but must not change a single number. The files are *not* byte-identical in this
   case, because the block size also sets the parquet row-group layout -- so this is checked on
   values, not bytes.
3. **Seed sensitivity.** A different seed must actually produce different data. Without this, the
   first two tests would also pass on a generator that emits zeros.

Test 4 covers the reason the RNG is organised as named streams: adding a draw to one component must
not shift any other component's numbers.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from wimsim.core.config import RunConfig, load_run_config
from wimsim.core.provenance import sha256_file
from wimsim.core.rng import streams
from wimsim.signal.writer import write_run

DATA_FILES = ("samples.parquet", "truth_passes.parquet", "truth_timeseries.parquet")


def _write(cfg: RunConfig, path: Path):
    return write_run(cfg, path)


def test_byte_identical_for_same_config(tmp_path: Path, short_cfg: RunConfig) -> None:
    a = _write(short_cfg, tmp_path / "a")
    b = _write(
        load_run_config(
            "S1_nominal",
            overrides=[
                "scenario.duration_s=60.0",
                "scenario.block_seconds=10.0",
                "scenario.output.samples=full",
            ],
        ),
        tmp_path / "b",
    )

    assert a.manifest["provenance"]["config_hash"] == b.manifest["provenance"]["config_hash"]
    assert a.manifest["output_hash"] == b.manifest["output_hash"]
    for name in DATA_FILES:
        assert sha256_file(tmp_path / "a" / name) == sha256_file(tmp_path / "b" / name), name


def test_manifest_excludes_wall_clock_from_the_hash(tmp_path: Path, short_cfg: RunConfig) -> None:
    """``created_at`` is the one field allowed to differ between two reproductions."""
    a = _write(short_cfg, tmp_path / "a")
    b = _write(short_cfg, tmp_path / "b")
    assert a.manifest["output_hash"] == b.manifest["output_hash"]
    assert "created_at" in a.manifest["provenance"]


@pytest.mark.parametrize("block_seconds", [5.0, 10.0, 20.0, 60.0])
def test_values_invariant_to_block_size(
    tmp_path: Path, short_cfg: RunConfig, block_seconds: float
) -> None:
    ref = _write(short_cfg, tmp_path / "ref")
    alt_cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            f"scenario.block_seconds={block_seconds}",
            "scenario.output.samples=full",
        ],
    )
    _write(alt_cfg, tmp_path / "alt")
    for name in DATA_FILES:
        left = pd.read_parquet(ref.out_dir / name)
        right = pd.read_parquet(tmp_path / "alt" / name)
        pd.testing.assert_frame_equal(left, right, check_exact=True, obj=name)


def test_different_seed_changes_the_data(tmp_path: Path, short_cfg: RunConfig) -> None:
    a = _write(short_cfg, tmp_path / "a")
    other = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=full",
        ],
        seed=short_cfg.scenario.seed + 1,
    )
    b = _write(other, tmp_path / "b")
    assert a.manifest["output_hash"] != b.manifest["output_hash"]

    left = pd.read_parquet(a.out_dir / "truth_passes.parquet")
    right = pd.read_parquet(b.out_dir / "truth_passes.parquet")
    assert not left.true_mass_kg.equals(right.true_mass_kg)


def test_named_streams_are_independent() -> None:
    """Drawing from one stream must not perturb another. This is why RngStreams exists."""
    s1 = streams(7)
    first = s1.get("noise.white").standard_normal(5).tolist()

    s2 = streams(7)
    s2.get("traffic.arrivals").standard_normal(1000)  # burn a different stream hard
    s2.get("noise.pink").standard_normal(1000)
    second = s2.get("noise.white").standard_normal(5).tolist()

    assert first == second


def test_stream_names_map_to_distinct_streams() -> None:
    s = streams(11)
    a = s.get("noise.white").standard_normal(64)
    b = s.fresh("noise.pink").standard_normal(64)
    assert not (a == b).all()
