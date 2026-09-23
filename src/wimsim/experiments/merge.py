"""Merging a sweep that was run as seed shards.

`ladder30` is 630 runs, about a day as one process and about seven hours as three. The seed axis is
the one that shards cleanly: the same seed gives a byte-identical sample stream wherever it runs, so
three shards of ten seeds concatenate to exactly what one process would have produced. Nothing else
shards this way -- splitting by scenario or estimator would produce shards that are not comparable
to each other, and splitting by nothing at all is the sequential run.

That guarantee holds only while the shards differ in the seed and in nothing else, which is what
this module checks before concatenating. A merge that silently combines shards from different code,
different grids, or overlapping seed ranges produces a table that looks like one experiment and is
not, and every median in it is over a mixture. Determinism makes a duplicated run *identical*, which
is precisely what makes a double-counted seed invisible in the output.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

__all__ = ["merge_shards"]


def _manifest(path: Path) -> dict[str, Any]:
    file = path / "manifest.json"
    if not file.exists():
        raise ValueError(f"{path.name} has no manifest.json, so its provenance cannot be checked")
    return json.loads(file.read_text(encoding="utf-8"))


def merge_shards(shards: Sequence[Path | str], *, out_dir: Path | str) -> Path:
    """Concatenate seed shards of one sweep into a single results directory.

    Refuses rather than merges when the shards are not the same experiment at the same commit with
    the same grid, or when a seed appears in more than one of them. The merged manifest records
    every shard it came from: a merged result is not a run, and a manifest that looked like one
    would be a provenance claim the directory cannot support.
    """
    paths = [Path(p) for p in shards]
    if not paths:
        raise ValueError("no shards to merge")

    manifests = [_manifest(p) for p in paths]
    names = [p.name for p in paths]

    ids = {m.get("experiment_id") for m in manifests}
    if len(ids) > 1:
        raise ValueError(f"shards are of different experiments: {sorted(map(str, ids))}")

    commits = {m.get("git_commit") for m in manifests}
    if len(commits) > 1:
        raise ValueError(
            f"shards were produced at different commits: {sorted(map(str, commits))}. They differ "
            "in more than the seed, so concatenating them would describe no single version."
        )

    # Everything but the seed axis, which is the axis being sharded and is *expected* to differ.
    specs = {
        json.dumps({k: v for k, v in (m.get("spec") or {}).items() if k != "seeds"}, sort_keys=True)
        for m in manifests
    }
    if len(specs) > 1:
        raise ValueError(
            "shards were run with different specs, so the merged table would be a mixture with no "
            "column saying so"
        )

    frames = [pd.read_parquet(p / "results.parquet") for p in paths]
    owner: dict[Any, str] = {}
    for name, frame in zip(names, frames, strict=True):
        for seed in frame["seed"].unique():
            if seed in owner:
                raise ValueError(
                    f"seed {seed} appears in more than one shard ({owner[seed]} and {name}); "
                    "merging would count those runs twice and determinism makes the duplicates "
                    "identical, so nothing downstream would show it"
                )
            owner[seed] = name

    merged = pd.concat(frames, ignore_index=True).sort_values(
        ["scenario", "estimator", "seed"], kind="stable"
    )
    if "dirty" in merged:  # pragma: no cover - defensive
        merged = merged.drop(columns=["dirty"])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out / "results.parquet", index=False)

    failed = int(merged["failed"].fillna(False).sum()) if "failed" in merged else 0
    manifest = {
        "experiment_id": manifests[0].get("experiment_id"),
        "git_commit": manifests[0].get("git_commit"),
        "git_dirty": any(bool(m.get("git_dirty")) for m in manifests),
        "n_runs": len(merged),
        "n_failed": failed,
        "spec": manifests[0].get("spec"),
        "merged_from": names,
        "seeds": sorted(int(s) for s in merged["seed"].unique()),
        "elapsed_s": sum(float(m.get("elapsed_s") or 0.0) for m in manifests),
        "note": (
            "Merged from seed shards of one sweep. The shards differ in the seed axis only; "
            "see wimsim.experiments.merge for what was checked before concatenating."
        ),
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out
