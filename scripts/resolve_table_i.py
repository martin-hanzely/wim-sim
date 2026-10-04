"""Resolve a sweep's estimator parameters as they were actually in force when it ran.

Table I of the manuscript names lambda, Q00, Q11, R and the thermal time constants. Reading them
off today's configs would be wrong: `6523c7d` moved the shipped Page-Hinkley threshold, and the
same class of drift can touch any default. The values a sweep ran with are recoverable only from
the code and configs of its own commit.

Run this inside a detached worktree at that commit, with the worktree's `src` on the path, and
point it at the ORIGINAL results manifest (the worktree has no results of its own):

    git worktree add --detach /tmp/wt <commit>
    cd /tmp/wt && PYTHONPATH=$PWD/src python scripts/resolve_table_i.py \\
        <repo>/data/results/<sweep>/manifest.json

The resolved `edge_config_hash` values are printed so they can be checked against the hashes
recorded in that sweep's own `results.parquet`. If they do not match, the resolution is wrong and
the numbers must not be used -- that check is the whole point of doing it this way.
"""

from __future__ import annotations

import dataclasses
import json
import sys

from wimsim.calibration import kalman as kalman_module
from wimsim.core.config import load_run_config
from wimsim.experiments.runner import ExperimentSpec, _edge_for

_SEQUENCE_FIELDS = (
    "scenarios", "estimators", "seeds", "edge_configs", "overrides",
    "edge_overrides", "reference_rates", "control_arms",
)


def spec_from_manifest(path: str) -> ExperimentSpec:
    """Rebuild the sweep's spec, dropping any key this older ExperimentSpec does not know."""
    raw = dict(json.loads(open(path, encoding="utf-8").read())["spec"])
    raw["scenario_overrides"] = {
        k: tuple(v) for k, v in (raw.get("scenario_overrides") or {}).items()
    }
    for key in _SEQUENCE_FIELDS:
        if raw.get(key) is not None:
            raw[key] = tuple(raw[key])
    known = {f.name for f in dataclasses.fields(ExperimentSpec)}
    return ExperimentSpec(**{k: v for k, v in raw.items() if k in known})


def main(manifest_path: str, thermal_scenario: str = "S2_thermal_cycle") -> None:
    spec = spec_from_manifest(manifest_path)

    out: dict[str, object] = {}
    seen: set[str] = set()
    for cell in spec.grid():
        if cell.estimator in seen:
            continue
        seen.add(cell.estimator)
        edge = _edge_for(spec, cell)
        est = edge.estimate
        out[cell.estimator] = {
            "lambda_forgetting": est.forgetting,
            "R_measurement_noise": est.measurement_noise,
            "Q00_process_noise_bias_sd_per_s": est.process_noise_bias,
            "Q11_process_noise_gain_sd_per_s": est.process_noise_gain,
            "coverage_target": est.coverage_target,
            "bootstrap_passes": est.bootstrap_passes,
            "reference_every_n": edge.control.reference_every_n,
            "edge_config_hash": edge.config_hash(),
        }

    # Not config fields, so they cannot be reached through the spec.
    out["_kalman_internals"] = {
        "P0_initial_covariance_sd": list(kalman_module._DEFAULT_P0),
        "max_gap_s": kalman_module._DEFAULT_MAX_GAP_S,
        "note": "there is no covariance TRACE bound; max_gap_s caps the propagation interval",
    }

    cfg = load_run_config(
        thermal_scenario, spec.station,
        overrides=spec.overrides_for(thermal_scenario), seed=1,
    )
    out["_thermal"] = {
        "scenario": thermal_scenario,
        "tau_thermal_s": cfg.station.thermal.tau_thermal_s,
        "probe_lag_s": cfg.station.temperature_probe.lag_s,
        "alpha0_per_c": cfg.station.sensor.alpha0_per_c,
        "k0": cfg.station.sensor.k0,
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
