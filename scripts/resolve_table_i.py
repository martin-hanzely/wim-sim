"""C-b — Table I, resolved through the runner's own _edge_for so the hash proves it."""
import json, sys, dataclasses
from wimsim.core.config import load_run_config
from wimsim.experiments.runner import ExperimentSpec, _edge_for

man = json.load(open(sys.argv[1], encoding="utf-8"))
d = dict(man["spec"])
d["scenario_overrides"] = {k: tuple(v) for k, v in (d.get("scenario_overrides") or {}).items()}
for k in ("scenarios","estimators","seeds","edge_configs","overrides","edge_overrides",
          "reference_rates","control_arms"):
    if k in d and d[k] is not None: d[k] = tuple(d[k])
known = {f.name for f in dataclasses.fields(ExperimentSpec)}
spec = ExperimentSpec(**{k: v for k, v in d.items() if k in known})

out, seen = {}, set()
for cell in spec.grid():
    if cell.estimator in seen: continue
    seen.add(cell.estimator)
    ec = _edge_for(spec, cell); e = ec.estimate
    out[cell.estimator] = {
        "lambda_forgetting": e.forgetting,
        "R_measurement_noise": e.measurement_noise,
        "Q00_process_noise_bias": e.process_noise_bias,
        "Q11_process_noise_gain": e.process_noise_gain,
        "coverage_target": e.coverage_target,
        "bootstrap_passes": e.bootstrap_passes,
        "reference_every_n": ec.control.reference_every_n,
        "edge_config_hash": ec.config_hash(),
    }
from wimsim.calibration import kalman as K
out["_kalman_internals"] = {"P0_sd": list(K._DEFAULT_P0), "max_gap_s": K._DEFAULT_MAX_GAP_S}
cfg = load_run_config("S2_thermal_cycle", spec.station,
                      overrides=spec.overrides_for("S2_thermal_cycle"), seed=1)
out["_thermal_S2"] = {"tau_thermal_s": cfg.station.thermal.tau_thermal_s,
                      "probe_lag_s": cfg.station.temperature_probe.lag_s,
                      "alpha0_per_c": cfg.station.sensor.alpha0_per_c,
                      "k0": cfg.station.sensor.k0}
print(json.dumps(out, indent=2, default=str))
