"""Build `export/` from the stored sweep results.

A script rather than a notebook or a shell pipeline so the export can be rebuilt from the same
inputs and diffed. Reads only `data/results/*/results.parquet` and the repository's own metadata;
invents nothing. Anything absent is written as NOT RUN by the caller, not filled in here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "export"
DATA = EXPORT / "data"
FIGS = EXPORT / "figures"

#: Sweeps to draw on, and what each one is for.
SWEEPS = {
    "ladder": "every estimator across every scorable scenario, 3 seeds, 1 reference in 10",
    "ladder30": "the same grid at THIRTY seeds, which is what makes significance testing possible",
    "reference_rate": "reference rate 1-in-2..1-in-50 x controller on/off, S4 and S7",
    "governance": "controller on/off on S6_combined, the B2 comparison",
    "cintron_ladder": "the scorable scenarios on the REAL instrument's physics, not the "
    "contact-force model every other sweep used",
    "detectors": "CUSUM, Page-Hinkley, ADWIN and windowed KS each alone, plus the four-way "
    "ensemble section IV-G describes",
    "recal_coverage": "recalibration frequency via confirm_sigma, against interval coverage and "
    "fallback-event count",
    "theta2": "the three-parameter map against the two-parameter one, 30 seeds",
    "detector_thresholds": "each detector's threshold stepped from the shipped value to three more "
    "sensitive ones, to measure the rest of the recall/false-alarm curve",
    "cintron_ladder30": "the influence-line ladder at THIRTY seeds, testing whether ladder30's "
    "result transfers to the real instrument; Page-Hinkley pinned at the pre-correction 15.0",
    "reference_rate_ph75": "the governed-vs-ungoverned sweep at the CORRECTED Page-Hinkley "
    "threshold of 7.5 -- governance's best available configuration",
}

#: Analysis products written beside a sweep's parquet. Copied into the export because they are the
#: result, not a rendering of it: `comparisons.md` carries the only p-values the project has.
SIDECARS = ("comparisons.md", "detectors.md")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:  # pragma: no cover
        return "unknown"


def load(name: str) -> pd.DataFrame | None:
    path = ROOT / "data" / "results" / name / "results.parquet"
    if not path.is_file():
        return None
    frame = pd.read_parquet(path)
    frame.insert(0, "sweep", name)
    return frame


def tidy(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Long format: one observation per row. Per-seed values, never only aggregates."""
    id_cols = [
        "sweep",
        "scenario",
        "estimator",
        "seed",
        "reference_every_n",
        "control_enabled",
        "run_id",
        "config_hash",
        "edge_config_hash",
        "git_commit",
    ]
    units = {
        "mae_kg": "kg",
        "rmse_kg": "kg",
        "bias_kg": "kg",
        "dynamic_floor_kg": "kg",
        "mean_interval_width_kg": "kg",
        "baseline_error_kg": "kg",
        "final_error_kg": "kg",
        "mape": "fraction",
        "coverage": "fraction",
        "coverage_expected": "fraction",
        "recall": "fraction",
        "false_positive_rate": "fraction",
        "axle_count_accuracy": "fraction",
        "reconverge_s": "s",
        "mean_detection_delay_s": "s",
        "duration_s": "s",
        "elapsed_s": "s",
        "false_alarms_per_hour": "1/h",
        "n_truth": "count",
        "n_matched": "count",
        "n_detected": "count",
        "n_references": "count",
        "alarms": "count",
        "recalibrations": "count",
        "degradations": "count",
        "n_profiles": "count",
        "detected": "count",
        "missed": "count",
        "false_alarms": "count",
        "reconverge_passes": "count",
        "n_interval_fallback": "count",
        "n_interval_expected": "count",
    }
    rows = []
    for frame in frames.values():
        present_id = [c for c in id_cols if c in frame.columns]
        for metric, unit in units.items():
            if metric not in frame.columns:
                continue
            block = frame[present_id].copy()
            block["metric"] = metric
            block["value"] = pd.to_numeric(frame[metric], errors="coerce")
            block["unit"] = unit
            rows.append(block)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def median_iqr(values: np.ndarray) -> tuple[float, float, float, int]:
    """Median, q1, q3, n -- ignoring NaN. The export reports dispersion, never a bare figure."""
    clean = np.asarray([v for v in values if pd.notna(v)], dtype=np.float64)
    if clean.size == 0:
        return (np.nan, np.nan, np.nan, 0)
    return (
        float(np.median(clean)),
        float(np.percentile(clean, 25)),
        float(np.percentile(clean, 75)),
        int(clean.size),
    )


def main() -> int:
    EXPORT.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    FIGS.mkdir(exist_ok=True)

    frames = {name: f for name in SWEEPS if (f := load(name)) is not None}
    missing = sorted(set(SWEEPS) - set(frames))

    # -- per-family CSVs, long format, per-seed -------------------------------------------------
    long = tidy(frames)
    if not long.empty:
        long.to_csv(DATA / "all_metrics_long.csv", index=False)
        for name in frames:
            sub = long[long["sweep"] == name]
            sub.to_csv(DATA / f"{name}_long.csv", index=False)

    # -- figures ---------------------------------------------------------------------------------
    copied = []
    for name in frames:
        src = ROOT / "data" / "results" / name / "figures"
        if not src.is_dir():
            continue
        for png in sorted(src.glob("*.png")):
            target = FIGS / f"{name}__{png.name}"
            shutil.copy2(png, target)
            copied.append(target.name)

    # -- analysis sidecars -----------------------------------------------------------------------
    for name in frames:
        for sidecar in SIDECARS:
            src = ROOT / "data" / "results" / name / sidecar
            if src.is_file():
                target = EXPORT / f"{name}__{sidecar}"
                shutil.copy2(src, target)
                copied.append(target.name)

    # -- manifest ---------------------------------------------------------------------------------
    manifest = {
        "generated_utc": datetime.now(tz=UTC).isoformat(),
        "git_commit": _run(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(_run(["git", "status", "--porcelain"])),
        "python": sys.version.split()[0],
        "packages": {},
        "sweeps": {},
        "missing_sweeps": missing,
        "figures": copied,
        "container_digest": "not applicable -- runs are local, not containerised",
    }
    for pkg in ("numpy", "pandas", "scipy", "pyarrow", "matplotlib", "pydantic"):
        try:
            manifest["packages"][pkg] = __import__(pkg).__version__
        except Exception:  # pragma: no cover
            manifest["packages"][pkg] = "not installed"

    for name, frame in frames.items():
        manifest["sweeps"][name] = {
            "purpose": SWEEPS[name],
            "command": f"wimsim experiment {name} --out data/results/{name}",
            "n_runs": int(len(frame)),
            "n_failed": int(frame["failed"].fillna(False).sum()) if "failed" in frame else 0,
            "git_commit": str(frame["git_commit"].iloc[0]) if "git_commit" in frame else "unknown",
            "git_dirty": bool(frame["git_dirty"].any()) if "git_dirty" in frame else None,
            "scenarios": sorted(frame["scenario"].dropna().unique().tolist()),
            "estimators": sorted(frame["estimator"].dropna().unique().tolist()),
            "seeds": sorted(int(s) for s in frame["seed"].dropna().unique()),
            "config_hashes": sorted(frame["config_hash"].dropna().unique().tolist()),
            "edge_config_hashes": sorted(frame["edge_config_hash"].dropna().unique().tolist()),
            "wall_clock_s": float(frame["elapsed_s"].sum()) if "elapsed_s" in frame else None,
        }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"sweeps loaded : {sorted(frames)}")
    print(f"missing       : {missing or 'none'}")
    print(f"long rows     : {len(long)}")
    print(f"figures       : {len(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
