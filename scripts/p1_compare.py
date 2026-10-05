"""Paired comparisons across Phase 1 sweeps, under the pre-registered seed protocol.

An arm is ``experiment:estimator`` or ``experiment:estimator:edge_config``, or
``export:<sweep>:estimator`` for a stored sweep's arm read from ``export/data/<sweep>_long.csv``.
Two arms are paired by scenario and seed, over the seeds both have, -- legitimate across experiments because the plant stream is a function of the
scenario config and the seed alone -- and the script refuses a pair whose two experiments ran at
different commits or on a dirty tree, which is what that legitimacy rests on.

For every scenario it reports the median of the per-seed differences (b - a; decision A), the sign
counts the protocol's escalation rule reads, the exact two-sided Wilcoxon p, Holm over the family
the caller declares, and both rank-biserial forms: rank-weighted (``stats.py``) and sign-count (the
form F4 plots).

Usage:
  python scripts/p1_compare.py --family "1.2 dev" \
      --pair p1_r_dev:static_affine p1_r_dev_floor:kalman \
      --pair p1_r_dev:static_affine p1_r_dev:kalman
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from wimsim.experiments.stats import holm, wilcoxon_signed_rank

ROOT = Path("data/results")


def load(experiment: str) -> pd.DataFrame:
    d = ROOT / experiment
    if (d / "results.parquet").exists():
        return pd.read_parquet(d / "results.parquet")
    rows = [json.loads(line) for line in (d / "rows.partial.jsonl").read_text().splitlines()]
    return pd.DataFrame(rows)


def export_arm(sweep: str, est: str, metric: str) -> tuple[pd.Series, dict]:
    """A stored sweep's arm. Used where a control run at HEAD has reproduced it exactly."""
    df = pd.read_csv(Path("export/data") / f"{sweep}_long.csv")
    df = df[(df.estimator == est) & (df.metric == metric)]
    prov = {"commits": sorted(set(df.git_commit)), "dirty": False}
    return df.set_index(["scenario", "seed"])["value"], prov


def arm(spec: str, metric: str) -> tuple[pd.DataFrame, dict]:
    parts = spec.split(":")
    if parts[0] == "export":
        return export_arm(parts[1], parts[2], metric)
    exp, est = parts[0], parts[1]
    df = load(exp)
    df = df[(df.estimator == est) & (~df.failed.astype(bool))]
    if len(parts) > 2:
        df = df[df.edge_config == parts[2]]
    prov = {"commits": sorted(set(df.git_commit)), "dirty": bool(df.git_dirty.any())}
    return df.set_index(["scenario", "seed"])[metric], prov


def sign_rb(d: np.ndarray) -> float:
    nz = d[d != 0]
    return float((np.sum(nz > 0) - np.sum(nz < 0)) / nz.size) if nz.size else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", nargs=2, action="append", required=True, metavar=("A", "B"))
    ap.add_argument("--metric", default="mae_kg")
    ap.add_argument("--family", default="")
    ap.add_argument("--allow-cross-commit", action="store_true")
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args()

    tests, meta = [], []
    for a_spec, b_spec in args.pair:
        a, pa = arm(a_spec, args.metric)
        b, pb = arm(b_spec, args.metric)
        if pa["dirty"] or pb["dirty"]:
            raise SystemExit(f"{a_spec} / {b_spec}: a run on a dirty tree is not citable")
        if pa["commits"] != pb["commits"] and not args.allow_cross_commit:
            raise SystemExit(
                f"{a_spec} ran at {pa['commits']} and {b_spec} at {pb['commits']}; pairing across "
                "commits needs --allow-cross-commit and a reason"
            )
        joined = pd.concat({"a": a, "b": b}, axis=1).dropna()
        for scen, g in joined.groupby(level=0):
            d = (g.b - g.a).to_numpy()
            t = wilcoxon_signed_rank(
                list(g.a), list(g.b), label=f"{scen} / {a_spec} -> {b_spec}"
            )
            tests.append(t)
            meta.append(
                {
                    "n_pos": int((d > 0).sum()),
                    "n_neg": int((d < 0).sum()),
                    "seeds": len(d),
                    "unanimous": bool((d > 0).all() or (d < 0).all()),
                    "rb_sign": sign_rb(d),
                }
            )

    corrected = holm(tests)
    rows = []
    for t, m in zip(corrected, meta, strict=True):
        rows.append(
            {
                "family": args.family,
                "comparison": t.label,
                "seeds": m["seeds"],
                "median_a": round(t.median_a, 3),
                "median_b": round(t.median_b, 3),
                "median_paired_diff": round(t.median_difference, 3),
                "signs": f"+{m['n_pos']}/-{m['n_neg']}",
                "unanimous": m["unanimous"],
                "p": t.p_value,
                "p_holm": t.p_holm,
                "rb_rank": round(t.effect_size, 3),
                "rb_sign": round(m["rb_sign"], 3),
            }
        )
    out = pd.DataFrame(rows)
    with pd.option_context("display.width", 250, "display.max_colwidth", 80):
        print(f"family {args.family!r}: {len(out)} comparisons, Holm over all of them")
        print(out.drop(columns="family").to_string(index=False))
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.csv, index=False)


if __name__ == "__main__":
    main()
