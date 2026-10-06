"""Thirty-seed stages for every Phase 1 comparison that split at ten seeds (protocol, 459d583).

Both stages are reported, side by side: the ten-seed stage (seeds 1-10) as first measured, and the
thirty-seed stage (seeds 1-30). Holm is applied within each family at each stage, over the
escalated comparisons of that family.

Arm sources. A new arm's seeds 1-10 come from its Phase 1 sweep and seeds 11-30 from its
escalation sweep (``*_esc_s*``, merged here). Comparator arms -- static, RLS 0.99, shipped-R Kalman
-- come from the stored 30-seed sweeps for all thirty seeds: at HEAD they reproduce those sweeps
exactly (55/55 rows at 2e8c788 for static and Kalman; 8/8 at fdcb53f for static and RLS).

Writes export/data/p1/p1_escalations.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from wimsim.experiments.merge import merge_shards
from wimsim.experiments.stats import holm, wilcoxon_signed_rank

R = Path("data/results")


def merged(prefix: str) -> pd.DataFrame:
    shards = sorted(R.glob(f"{prefix}_s*"))
    out = R / prefix
    if not (out / "results.parquet").exists():
        merge_shards(shards, out_dir=out)
    return pd.read_parquet(out / "results.parquet")


def runs(df: pd.DataFrame, est: str, edge: str | None = None) -> pd.Series:
    d = df[(df.estimator == est) & ~df.failed.astype(bool)]
    if edge is not None:
        d = d[d.edge_config == edge]
    return d.set_index(["scenario", "seed"]).mae_kg


def stored(sweep: str, est: str) -> pd.Series:
    d = pd.read_csv(f"export/data/{sweep}_long.csv")
    d = d[(d.estimator == est) & (d.metric == "mae_kg")]
    return d.set_index(["scenario", "seed"]).value


def both(stage1: pd.Series, esc: pd.Series) -> pd.Series:
    return pd.concat([stage1, esc]).sort_index()


def main() -> None:
    lad_s, lad_r, lad_k = stored("ladder30", "static_affine"), stored("ladder30", "rls"), stored("ladder30", "kalman")
    hel_s, hel_r, hel_k = stored("heldout30", "static_affine"), stored("heldout30", "rls"), stored("heldout30", "kalman")
    cin_s, cin_k = stored("cintron_ladder30", "static_affine"), stored("cintron_ladder30", "kalman")

    kr_dev = both(runs(pd.read_parquet(R / "p1_r_dev_floor/results.parquet"), "kalman"),
                  runs(merged("p1_r_dev_floor_esc"), "kalman"))
    kr_held = both(runs(pd.read_parquet(R / "p1_r_held_floor/results.parquet"), "kalman"),
                   runs(merged("p1_r_held_floor_esc"), "kalman"))
    kr_cin = both(runs(pd.read_parquet(R / "p1_r_cin_floor/results.parquet"), "kalman"),
                  runs(merged("p1_r_cin_floor_esc"), "kalman"))
    mem_dev = pd.read_parquet(R / "p1_mem_dev/results.parquet")
    mem_held = pd.read_parquet(R / "p1_mem_held/results.parquet")
    per_dev = both(runs(mem_dev, "periodic_refit"), runs(merged("p1_esc_periodic_dev"), "periodic_refit"))
    per_held = both(runs(mem_held, "periodic_refit"), runs(merged("p1_esc_periodic_held"), "periodic_refit"))
    l1_dev = both(runs(pd.read_parquet(R / "p1_mem_dev_l1/results.parquet"), "rls"),
                  runs(merged("p1_mem_dev_l1_esc"), "rls"))
    l1_held = both(runs(pd.read_parquet(R / "p1_mem_held_l1/results.parquet"), "rls"),
                   runs(merged("p1_mem_held_l1_esc"), "rls"))
    lam = pd.read_parquet(R / "p1_lambda/results.parquet")
    esc_lam, esc_095 = merged("p1_esc_lambda"), merged("p1_esc_lambda095")
    l0995 = both(runs(lam, "rls", "rls_l0995"), runs(esc_lam, "rls", "rls_l0995"))
    l0999 = both(runs(lam, "rls", "rls_l0999"), runs(esc_lam, "rls", "rls_l0999"))
    l095 = both(runs(lam, "rls", "rls_l095"), runs(esc_095, "rls"))

    families = {
        "1.2 dev": [(s, "static", "kalman corrected R", lad_s, kr_dev)
                    for s in ("S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S5_outage", "S6_combined")]
        + [(s, "kalman shipped R", "kalman corrected R", lad_k, kr_dev)
           for s in ("S1_nominal", "S5_outage", "S7_sparse_reference")],
        "1.2 held-out": [(s, "static", "kalman corrected R", hel_s, kr_held) for s in ("H3_slow_fade", "H4_pileup")]
        + [(s, "kalman shipped R", "kalman corrected R", hel_k, kr_held)
           for s in ("H1_warm_front", "H3_slow_fade", "H4_pileup")],
        "1.2 front end B": [(s, "static", "kalman corrected R", cin_s, kr_cin)
                            for s in ("S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S5_outage",
                                      "S6_combined", "S7_sparse_reference")]
        + [(s, "kalman shipped R", "kalman corrected R", cin_k, kr_cin)
           for s in ("S1_nominal", "S5_outage", "S6_combined")],
        "1.3 dev": [(s, "static", "periodic", lad_s, per_dev)
                    for s in ("S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S5_outage", "S6_combined")]
        + [(s, "rls 0.99", "periodic", lad_r, per_dev)
           for s in ("S1_nominal", "S4_step_fault", "S5_outage", "S6_combined")]
        + [(s, "static", "rls 1.0", lad_s, l1_dev)
           for s in ("S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S5_outage", "S6_combined")]
        + [(s, "rls 0.99", "rls 1.0", lad_r, l1_dev) for s in ("S1_nominal", "S3_zero_drift_walk", "S5_outage")],
        "1.3 held-out": [(s, "static", "periodic", hel_s, per_held) for s in ("H1_warm_front", "H3_slow_fade", "H4_pileup")]
        + [(s, "rls 0.99", "periodic", hel_r, per_held) for s in ("H1_warm_front", "H2_gain_jolt", "H4_pileup")]
        + [(s, "static", "rls 1.0", hel_s, l1_held)
           for s in ("H1_warm_front", "H2_gain_jolt", "H3_slow_fade", "H4_pileup")]
        + [(s, "rls 0.99", "rls 1.0", hel_r, l1_held) for s in ("H1_warm_front", "H3_slow_fade")],
        "1.3 lambda": [("S2_thermal_cycle", "static", "rls 0.995", lad_s, l0995),
                       ("S2_thermal_cycle", "static", "rls 0.999", lad_s, l0999),
                       ("S7_sparse_reference", "static", "rls 0.95", lad_s, l095),
                       ("S4_step_fault", "rls 0.99", "rls 0.95", lad_r, l095)],
    }

    rows = []
    for fam, comps in families.items():
        for stage, seeds in (("10 seeds", range(1, 11)), ("30 seeds", range(1, 31))):
            tests, meta = [], []
            for scen, a_name, b_name, a, b in comps:
                j = pd.concat({"a": a.loc[scen], "b": b.loc[scen]}, axis=1).loc[list(seeds)].dropna()
                d = j.b - j.a
                tests.append(wilcoxon_signed_rank(list(j.a), list(j.b), label=f"{scen} / {a_name} -> {b_name}"))
                meta.append((len(j), int((d > 0).sum()), int((d < 0).sum())))
            for t, (n, pos, neg) in zip(holm(tests), meta, strict=True):
                rows.append({"family": fam, "stage": stage, "comparison": t.label, "seeds": n,
                             "median_paired_diff": round(t.median_difference, 3),
                             "signs": f"+{pos}/-{neg}", "p": t.p_value, "p_holm": t.p_holm,
                             "rb_rank": round(t.effect_size, 3)})
    out = pd.DataFrame(rows)
    out.to_csv("export/data/p1/p1_escalations.csv", index=False)
    wide = out.pivot_table(index=["family", "comparison"], columns="stage",
                           values=["median_paired_diff", "signs", "p_holm"], aggfunc="first")
    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.max_colwidth", 70):
        print(wide.to_string())


if __name__ == "__main__":
    main()
