"""Merging a sweep that was run as seed shards.

A 630-run sweep takes about a day as one process and about seven hours as three, and the seed axis
is the one that shards cleanly: pairing is by seed, and the same seed gives a byte-identical sample
stream wherever it runs. So the shards concatenate to exactly what one process would have produced.

These tests are about the ways that stops being true. A merge that silently combines shards from
different code, different specs, or overlapping seed ranges produces a table that looks like one
experiment and is not, and every median in it would be over a mixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from wimsim.experiments.merge import merge_shards


def _shard(path: Path, seeds, *, commit="abc123", experiment_id="ladder30", spec=None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "run_id": f"S1__rls__seed{s}",
            "scenario": "S1_nominal",
            "estimator": "rls",
            "seed": s,
            "mae_kg": 100.0 + s,
            "failed": False,
        }
        for s in seeds
    ]
    pd.DataFrame(rows).to_parquet(path / "results.parquet")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "git_commit": commit,
                "git_dirty": False,
                "n_runs": len(rows),
                "n_failed": 0,
                "spec": spec or {"experiment_id": experiment_id, "estimators": ["rls"]},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_shards_concatenate_into_one_frame(tmp_path: Path) -> None:
    a = _shard(tmp_path / "a", [1, 2, 3])
    b = _shard(tmp_path / "b", [4, 5, 6])

    out = merge_shards([a, b], out_dir=tmp_path / "merged")
    frame = pd.read_parquet(out / "results.parquet")

    assert sorted(frame["seed"]) == [1, 2, 3, 4, 5, 6]
    assert len(frame) == 6


def test_an_overlapping_seed_is_refused_rather_than_duplicated(tmp_path: Path) -> None:
    """Two shards that both ran seed 3 would put that run in the table twice, and every median
    would be weighted towards it. Determinism makes the two rows identical, which is exactly what
    makes the duplication invisible."""
    a = _shard(tmp_path / "a", [1, 2, 3])
    b = _shard(tmp_path / "b", [3, 4, 5])

    with pytest.raises(ValueError, match="appears in more than one shard"):
        merge_shards([a, b], out_dir=tmp_path / "merged")


def test_shards_from_different_commits_are_refused(tmp_path: Path) -> None:
    """The point of the seed axis sharding cleanly is that the shards differ in the seed and in
    nothing else. Two commits is a different experiment wearing one name."""
    a = _shard(tmp_path / "a", [1, 2], commit="aaa")
    b = _shard(tmp_path / "b", [3, 4], commit="bbb")

    with pytest.raises(ValueError, match="different commits"):
        merge_shards([a, b], out_dir=tmp_path / "merged")


def test_shards_of_different_experiments_are_refused(tmp_path: Path) -> None:
    a = _shard(tmp_path / "a", [1, 2], experiment_id="ladder30")
    b = _shard(tmp_path / "b", [3, 4], experiment_id="theta2")

    with pytest.raises(ValueError, match="different experiments"):
        merge_shards([a, b], out_dir=tmp_path / "merged")


def test_shards_with_different_specs_are_refused(tmp_path: Path) -> None:
    """Same experiment id, same commit, different grid -- someone re-ran a shard with `--scenarios`
    and the merged table would be a mixture with no column saying so."""
    a = _shard(tmp_path / "a", [1, 2], spec={"experiment_id": "ladder30", "estimators": ["rls"]})
    b = _shard(
        tmp_path / "b", [3, 4], spec={"experiment_id": "ladder30", "estimators": ["rls", "kalman"]}
    )

    with pytest.raises(ValueError, match="different specs"):
        merge_shards([a, b], out_dir=tmp_path / "merged")


def test_shards_are_allowed_to_differ_in_the_seed_axis_which_is_the_point(tmp_path: Path) -> None:
    """The one spec field that must differ. `--seeds 1,...,10` and `--seeds 11,...,20` write
    different `spec.seeds`, and a spec check that did not exempt it would refuse every real shard --
    which is how this check failed the first time it met the three shards it was written for.
    """
    a = _shard(tmp_path / "a", [1, 2], spec={"experiment_id": "ladder30", "seeds": [1, 2]})
    b = _shard(tmp_path / "b", [3, 4], spec={"experiment_id": "ladder30", "seeds": [3, 4]})

    out = merge_shards([a, b], out_dir=tmp_path / "merged")
    assert len(pd.read_parquet(out / "results.parquet")) == 4


def test_the_merged_manifest_names_every_shard_it_came_from(tmp_path: Path) -> None:
    """A merged result is not a run, and a manifest that looks like one would be a provenance
    claim the directory cannot support."""
    a = _shard(tmp_path / "a", [1, 2])
    b = _shard(tmp_path / "b", [3, 4])

    out = merge_shards([a, b], out_dir=tmp_path / "merged")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["merged_from"] == ["a", "b"]
    assert manifest["n_runs"] == 4
    assert manifest["git_commit"] == "abc123"
    assert manifest["seeds"] == [1, 2, 3, 4]


def test_a_single_shard_merges_to_itself(tmp_path: Path) -> None:
    a = _shard(tmp_path / "a", [1, 2])
    out = merge_shards([a], out_dir=tmp_path / "merged")
    assert len(pd.read_parquet(out / "results.parquet")) == 2


def test_no_shards_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no shards"):
        merge_shards([], out_dir=tmp_path / "merged")
