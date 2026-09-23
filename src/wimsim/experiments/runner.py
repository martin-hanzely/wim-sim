"""The experiment runner: a declarative grid in, one results table out.

Buildspec section 10 asks for "scenario set x estimator set x seeds -> runs -> results Parquet in
``data/results/<experiment_id>/``", every artifact stamped with config hash and git commit. This is
what turns a testbed into a paper: until now every number in this project was measured one scenario
at a time, by hand, and quoted from a terminal.

Three decisions that decide whether the output is trustworthy rather than merely produced.

**A failed run is a row, not a gap.** Nineteen results and one exception is nineteen results *and
one recorded failure* -- because dropping it silently changes what every mean in the table is a mean
over, and the failure is usually the interesting part. Failures carry their error text into the
parquet and are marked in the table.

**Every row carries its own provenance.** Config hash, edge config hash, git commit, dirty flag,
version. A results table whose rows cannot each name what produced them is a table nobody can
rebuild, and principle 3 says that is not a result.

**The grid is validated before anything runs.** A sweep is expensive; discovering a typo in an
estimator name after the first hour is pure waste, so unknown names are refused at construction.

Runs are independent by construction -- same seed and config give a byte-identical stream -- so the
loop is deliberately sequential and boring. Parallelism would buy wall-clock time and cost the
ability to say what happened when something goes wrong; if it becomes necessary, it belongs behind
a flag rather than in the default path.
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from wimsim import __version__
from wimsim.calibration import ESTIMATORS
from wimsim.core.config import load_edge_config, load_run_config
from wimsim.core.provenance import collect

__all__ = [
    "ExperimentResult",
    "ExperimentSpec",
    "RunSpec",
    "load_experiment",
    "run_experiment",
]

#: Where sweeps land unless told otherwise, per buildspec section 10.
RESULTS_ROOT = Path("data/results")

#: Fault types a drift detector is supposed to catch, because they move the calibration.
#:
#: Everything else the scenarios inject -- connectivity loss, publish delay, clock skew, channel
#: dropout, malformed schema, heartbeat loss -- is a transport or acquisition failure. None of them
#: makes the scale wrong, so a detector that stays quiet through one is behaving correctly, and
#: scoring it as a missed detection measures the wrong thing. `S5_outage` injects three faults and
#: not one of them is of this kind.
CALIBRATION_FAULTS = frozenset({"gain_instability", "sensor_displacement"})


#: Every column a results row can carry, in order, with its null value. Rows start from this so
#: the parquet's schema does not depend on how many cells happened to succeed -- a sweep where
#: everything failed produced a frame with no ``mae_kg`` column at all, which breaks every consumer
#: at exactly the moment they most need to look.
_ROW_TEMPLATE: dict[str, Any] = {
    # what the run was
    "experiment_id": None,
    "run_id": None,
    "scenario": None,
    "estimator": None,
    "seed": None,
    "edge_config": None,
    "config_hash": None,
    "edge_config_hash": None,
    "duration_s": None,
    "elapsed_s": None,
    "control_enabled": None,
    "uncertainty": None,
    "conformal_score": None,
    "reference_every_n": None,
    # what happened
    "n_detected": None,
    "n_references": None,
    "alarms": None,
    "recalibrations": None,
    "degradations": None,
    "n_profiles": None,
    # accuracy
    "n_truth": None,
    "n_matched": None,
    # Vehicle matching: n_matched / n_truth. Named apart from `recall` because `_control_row` emits
    # a `recall` of its own -- fault DETECTION recall -- and it is merged second, so a shared name
    # silently destroyed this one. Everything downstream reads `recall` as the detection one.
    "match_recall": None,
    "recall": None,
    "false_positive_rate": None,
    "mae_kg": None,
    "mape": None,
    "rmse_kg": None,
    "bias_kg": None,
    "dynamic_floor_kg": None,
    "coverage": None,
    "coverage_expected": None,
    "n_interval_fallback": None,
    "mean_interval_width_kg": None,
    "axle_count_accuracy": None,
    # the control loop
    "detected": None,
    "missed": None,
    "false_alarms": None,
    "false_alarms_per_hour": None,
    "mean_detection_delay_s": None,
    "reconverge_measurable": None,
    "reconverge_departed": None,
    "reconverged": None,
    "reconverge_s": None,
    "reconverge_passes": None,
    "baseline_error_kg": None,
    "final_error_kg": None,
    # provenance and outcome
    "git_commit": None,
    "git_dirty": None,
    "wimsim_version": None,
    "failed": False,
    "error": None,
}


@dataclass(frozen=True, slots=True)
class RunSpec:
    """One cell of the grid."""

    scenario: str
    estimator: str
    seed: int
    run_id: str
    reference_every_n: int | None = None
    """How often a reference vehicle arrives, for this cell. ``None`` leaves the edge config's own."""
    control: bool | None = None
    """Whether the MAPE-K loop runs. ``None`` leaves the edge config's own setting."""
    edge_config: str = "default"
    """Which pipeline config this cell runs."""


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """A declarative sweep. Everything an experiment needs and nothing about how it is executed."""

    experiment_id: str
    scenarios: Sequence[str]
    estimators: Sequence[str]
    seeds: Sequence[int]
    description: str = ""
    edge_config: str = "default"
    edge_configs: Sequence[str] = field(default_factory=tuple)
    """The pipeline config as an axis.

    Two things need it. The detectors live in the edge config, so a per-detector comparison is a
    sweep over configs and nothing else -- and only two of the four are enabled by default, so every
    detection number reported before this is the behaviour of that pair. And recalibration frequency
    is driven by `confirm_sigma`, which is also an edge setting.
    """
    station: str | None = None
    """Station to run every scenario on. None keeps whichever the scenario names.

    Every sweep before this ran on `default`, the contact-force model, while the hardware
    the real recordings came from is an influence-line strain platform -- so no synthetic
    result corresponded to the instrument the simulator was validated against."""
    overrides: Sequence[str] = field(default_factory=tuple)
    """Scenario overrides, applied to every run: ``scenario.duration_s=600``."""
    edge_overrides: Sequence[str] = field(default_factory=tuple)
    """Pipeline overrides, applied to every run: ``edge.control.enabled=true``."""
    scenario_overrides: Mapping[str, Sequence[str]] = field(default_factory=dict)
    """Extra scenario overrides for one scenario only, applied after :attr:`overrides`.

    The scenarios in one sweep differ in length by three hundred times -- S1 ships at 15 minutes
    and S2 at 72 hours -- so a single global list cannot give both a sensible duration. Without
    this, `ladder` scored S1 on two passes: 62 crossings, 60 of them spent on the calibration
    window, and the resulting row sat in the table looking exactly like a row built on thousands.
    """
    calibration_passes: int | None = None
    reference_every_n: int | None = None
    """One rate for the whole sweep. Use :attr:`reference_rates` to sweep it instead."""
    reference_rates: Sequence[int] = field(default_factory=tuple)
    """The reference rate as a fourth axis.

    The `ladder` checkpoint asked a question it could not answer. At one reference vehicle in ten
    the discrete MAPE-K loop behaves as a backstop -- on `S4_step_fault` the Kalman arm performed
    *zero* recalibrations and was still the most accurate of the three -- while the phase-5
    checkpoint at one-in-two showed the loop clearly earning its keep. Somewhere between those two
    rates the discrete loop stops being the mechanism and starts being insurance, and that
    crossover is the central claim of the whole controller. It was unmeasurable while the rate was
    a scalar setting.
    """
    control_arms: Sequence[bool] = field(default_factory=tuple)
    """The controller on and off, as an axis, over the identical stream.

    "Does the loop earn its keep at this reference rate" is a two-arm question. The README calls
    the controller-off run "the arm every claim about the controller has to be measured against",
    and phase 5 ran S4 both ways by hand to make its headline claim. Without it a rate sweep shows
    how accuracy varies with reference rate but not how much of that accuracy came from the loop.
    """
    fault_horizon_s: float = 1800.0
    """How long after an injected fault an alarm still counts as having detected it."""

    def __post_init__(self) -> None:
        for name, values in (
            ("scenarios", self.scenarios),
            ("estimators", self.estimators),
            ("seeds", self.seeds),
        ):
            if not values:
                raise ValueError(f"{name} is empty, so the grid has no cells")
        stray = sorted(set(self.scenario_overrides) - set(self.scenarios))
        if stray:
            raise ValueError(
                f"scenario_overrides names {stray}, not in this sweep's scenarios "
                f"{sorted(self.scenarios)}; a typo here is a setting that silently does nothing."
            )
        if self.edge_configs and self.edge_config != "default":
            raise ValueError(
                "both edge_config and edge_configs are set; one of them would be silently ignored. "
                "Name the axis or the scalar, not both."
            )
        if self.reference_rates and self.reference_every_n is not None:
            raise ValueError(
                "both reference_every_n and reference_rates are set; one of them would be "
                "silently ignored. Name the axis or the scalar, not both."
            )
        bad = [r for r in self.reference_rates if not isinstance(r, int) or r < 1]
        if bad:
            raise ValueError(f"reference_rates must be positive integers; got {bad}")
        if len(set(self.control_arms)) != len(self.control_arms):
            raise ValueError(f"control_arms repeats an arm: {list(self.control_arms)}")
        unknown = [e for e in self.estimators if e not in ESTIMATORS]
        if unknown:
            raise ValueError(
                f"unknown estimators {unknown}; the registry holds {sorted(ESTIMATORS)}. Refused "
                "before the sweep starts rather than after the first hour of it."
            )

    def overrides_for(self, scenario: str) -> list[str]:
        """The overrides one scenario runs with. Its own come last, so they win."""
        return [*self.overrides, *self.scenario_overrides.get(scenario, ())]

    def grid(self) -> Iterator[RunSpec]:
        """Every cell, in a stable order."""
        rates: tuple[int | None, ...] = tuple(self.reference_rates) or (self.reference_every_n,)
        arms: tuple[bool | None, ...] = tuple(self.control_arms) or (None,)
        edges: tuple[str, ...] = tuple(self.edge_configs) or (self.edge_config,)
        # A suffix appears only where the axis actually varies: a run id should name what separates
        # a cell from its neighbours, and `__ref10` on every row of `ladder` names nothing.
        label_rate, label_arm = len(rates) > 1, len(arms) > 1
        label_edge = len(edges) > 1
        for scenario, estimator, seed, rate, arm, edge in itertools.product(
            self.scenarios, self.estimators, self.seeds, rates, arms, edges
        ):
            run_id = f"{scenario}__{estimator}__seed{seed}"
            if label_rate:
                run_id += f"__ref{rate}"
            if label_arm:
                run_id += "__control" if arm else "__open"
            if label_edge:
                run_id += f"__{edge}"
            yield RunSpec(
                scenario=scenario,
                estimator=estimator,
                seed=seed,
                run_id=run_id,
                reference_every_n=rate,
                control=arm,
                edge_config=edge,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "description": self.description,
            "scenarios": list(self.scenarios),
            "estimators": list(self.estimators),
            "seeds": list(self.seeds),
            "edge_config": self.edge_config,
            "station": self.station,
            "edge_configs": list(self.edge_configs),
            "overrides": list(self.overrides),
            "scenario_overrides": {k: list(v) for k, v in self.scenario_overrides.items()},
            "edge_overrides": list(self.edge_overrides),
            "calibration_passes": self.calibration_passes,
            "reference_every_n": self.reference_every_n,
            "reference_rates": list(self.reference_rates),
            "control_arms": list(self.control_arms),
            "fault_horizon_s": self.fault_horizon_s,
        }


def load_experiment(path: Path | str) -> ExperimentSpec:
    """Read a sweep from YAML."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    known = set(ExperimentSpec.__dataclass_fields__)
    unknown = set(payload) - known
    if unknown:
        raise ValueError(
            f"unknown keys in {path}: {sorted(unknown)}. Known keys are {sorted(known)}; a typo "
            "here would otherwise be a setting that silently did nothing."
        )
    return ExperimentSpec(**payload)


#: Appended to as each cell finishes, and deleted once the sweep writes its real output. Its
#: PRESENCE therefore means a sweep did not finish -- a stale one left behind would be a lie.
PARTIAL_LOG = "rows.partial.jsonl"


def _append_partial(out_dir: Path, row: dict[str, Any]) -> None:
    """Record one finished cell immediately.

    A sweep that writes nothing until its last cell loses everything if it is interrupted, which is
    not hypothetical: the first reference-rate run was killed at cell 30 of 180, after 99 minutes,
    and left an empty directory.

    Failures here are swallowed on purpose. This is a progress log; taking down an otherwise fine
    two-hour sweep because one row would not serialise is the opposite of what it is for.
    """
    try:
        with (out_dir / PARTIAL_LOG).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:  # pragma: no cover - a full or read-only disk
        pass


@dataclass
class ExperimentResult:
    out_dir: Path
    results_path: Path
    n_runs: int
    n_failed: int
    git_commit: str
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def run_experiment(
    spec: ExperimentSpec,
    *,
    out_dir: Path | str | None = None,
    progress: Any = None,
) -> ExperimentResult:
    """Execute every cell of the grid and write the results, manifest, table and figures."""
    from wimsim.experiments.figures import write_figures
    from wimsim.experiments.table import write_table

    out = Path(out_dir) if out_dir is not None else RESULTS_ROOT / spec.experiment_id
    out.mkdir(parents=True, exist_ok=True)

    provenance = collect(config_hash="", seed=0, mode="synthetic")
    started = datetime.now(tz=UTC)

    rows: list[dict[str, Any]] = []
    cells = list(spec.grid())
    for index, cell in enumerate(cells, start=1):
        if progress is not None:
            progress(index, len(cells), cell)
        row = _run_one(spec, cell, provenance)
        rows.append(row)
        _append_partial(out, row)

    finished = datetime.now(tz=UTC)
    frame = pd.DataFrame(rows, columns=list(_ROW_TEMPLATE))
    results_path = out / "results.parquet"
    frame.to_parquet(results_path, index=False)

    n_failed = int(frame["failed"].sum()) if "failed" in frame else 0
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "experiment_id": spec.experiment_id,
                "spec": spec.to_dict(),
                "n_runs": len(rows),
                "n_failed": n_failed,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "elapsed_s": (finished - started).total_seconds(),
                "git_commit": provenance.git_commit,
                "git_dirty": provenance.git_dirty,
                "wimsim_version": __version__,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = ExperimentResult(
        out_dir=out,
        results_path=results_path,
        n_runs=len(rows),
        n_failed=n_failed,
        git_commit=provenance.git_commit or "unknown",
        rows=rows,
    )
    write_table(result, spec)
    write_figures(result.frame, out_dir=result.out_dir, experiment_id=spec.experiment_id)
    # The real output exists now, so the progress log has served its purpose and must go: left
    # behind, it would claim the sweep had been interrupted.
    (out / PARTIAL_LOG).unlink(missing_ok=True)
    return result


# ----------------------------------------------------------------------------------------------
# one cell
# ----------------------------------------------------------------------------------------------


def _run_one(spec: ExperimentSpec, cell: RunSpec, provenance) -> dict[str, Any]:
    """Run one cell. Never raises: a failure becomes a row that says so."""
    row: dict[str, Any] = dict(_ROW_TEMPLATE)
    row.update(
        {
            "experiment_id": spec.experiment_id,
            "run_id": cell.run_id,
            "scenario": cell.scenario,
            "estimator": cell.estimator,
            "seed": cell.seed,
            "edge_config": cell.edge_config,
            "git_commit": provenance.git_commit or "unknown",
            "git_dirty": bool(provenance.git_dirty),
            "wimsim_version": __version__,
        }
    )

    try:
        cfg, truth, edge_cfg, elapsed, result = _execute(spec, cell)
    except Exception as exc:  # a failed cell must not take the sweep down
        row["failed"] = True
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["config_hash"] = _config_hash_of(spec, cell)
        row["edge_config_hash"] = _edge_hash_of(spec, cell)
        return row

    row.update(
        {
            "config_hash": cfg.config_hash(),
            "edge_config_hash": edge_cfg.config_hash(),
            "duration_s": cfg.scenario.duration_s,
            "elapsed_s": elapsed,
            "control_enabled": edge_cfg.control.enabled,
            "uncertainty": edge_cfg.uncertainty.method,
            "conformal_score": edge_cfg.uncertainty.conformal_score,
            "reference_every_n": edge_cfg.control.reference_every_n,
            "n_detected": result.n_detected,
            "n_references": result.n_references,
            "alarms": result.alarms,
            "recalibrations": result.recalibrations,
            "degradations": result.degradations,
            "n_profiles": len(result.profiles),
        }
    )
    row.update(_score_row(result))
    row.update(_control_row(spec, cfg, truth, result))
    return row


def _execute(spec: ExperimentSpec, cell: RunSpec):
    import tempfile

    from wimsim.experiments.closed_loop import run_closed_loop
    from wimsim.experiments.offline import load_run
    from wimsim.signal.writer import write_run

    cfg = load_run_config(
        cell.scenario,
        spec.station,
        overrides=spec.overrides_for(cell.scenario),
        seed=cell.seed,
    )
    edge_cfg = _edge_for(spec, cell)

    # The run directory is a temporary: a sweep of forty cells does not need forty truth logs on
    # disk, and everything that has to survive is in the results row.
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        out = write_run(cfg, Path(tmp) / "run")
        cfg, truth, _manifest = load_run(out.out_dir)
        result = run_closed_loop(cfg, truth, edge_cfg, calibration_passes=spec.calibration_passes)
    return cfg, truth, edge_cfg, time.perf_counter() - started, result


def _edge_for(spec: ExperimentSpec, cell: RunSpec):
    overrides = [*spec.edge_overrides, f"edge.estimate.estimator={cell.estimator}"]
    if cell.reference_every_n is not None:
        overrides.append(f"edge.control.reference_every_n={cell.reference_every_n}")
    if cell.control is not None:
        overrides.append(f"edge.control.enabled={str(cell.control).lower()}")
    return load_edge_config(cell.edge_config, overrides=overrides)


def _config_hash_of(spec: ExperimentSpec, cell: RunSpec) -> str:
    """The scenario hash, even for a cell that failed -- so the failure is attributable."""
    try:
        return load_run_config(
            cell.scenario,
            spec.station,
            overrides=spec.overrides_for(cell.scenario),
            seed=cell.seed,
        ).config_hash()
    except Exception:  # pragma: no cover - a config that will not even load
        return "unknown"


def _edge_hash_of(spec: ExperimentSpec, cell: RunSpec) -> str:
    try:
        return _edge_for(spec, cell).config_hash()
    except Exception:  # pragma: no cover
        return "unknown"


def _score_row(result) -> dict[str, Any]:
    if result.score is None:  # pragma: no cover - run_closed_loop always scores
        return {}
    s = result.score
    return {
        "n_truth": s.n_truth,
        "n_matched": s.n_matched,
        # NOT "recall": `_control_row` is merged after this one and emits fault-detection recall
        # under that name. Sharing it meant this value was computed on every run and reached no
        # output at all.
        "match_recall": s.recall,
        "false_positive_rate": s.false_positive_rate,
        "mae_kg": s.mae_kg,
        "mape": s.mape,
        "rmse_kg": s.rmse_kg,
        "bias_kg": s.bias_kg,
        "dynamic_floor_kg": s.dynamic_floor_kg,
        "coverage": s.coverage,
        "coverage_expected": s.coverage_expected,
        "n_interval_fallback": s.n_interval_fallback,
        "mean_interval_width_kg": s.mean_interval_width_kg,
        "axle_count_accuracy": s.axle_count_accuracy,
    }


def _control_row(spec: ExperimentSpec, cfg, truth, result) -> dict[str, Any]:
    """The control-loop metrics, which need the injected fault times.

    Truth-side by definition -- a scenario's fault schedule is exactly what the estimator must not
    see -- which is why this lives here and not in ``calibration/``.
    """
    from wimsim.experiments.control_scoring import detector_rates, time_to_reconverge

    fault_ts_us = _fault_times_us(cfg, truth)
    alarm_ts_us = [e.ts_us for e in result.controller_events if e.kind == "drift_detected"]

    rates = detector_rates(
        fault_ts_us=fault_ts_us,
        alarm_ts_us=alarm_ts_us,
        horizon_s=spec.fault_horizon_s,
        duration_s=cfg.scenario.duration_s,
    )
    row = dict(rates.to_dict())

    errors = _matched_errors(truth, result)
    if fault_ts_us and errors:
        # The first fault is the one the headline metric is about; later ones land on a plant that
        # has already been disturbed, so their recovery is not a clean measurement.
        row.update(time_to_reconverge(errors, fault_ts_us=fault_ts_us[0]).to_dict())
    return row


def _fault_times_us(cfg, truth) -> list[int]:
    """When each injected fault began, on the same clock the events carry.

    Faults are declared in scenario seconds; the truth log fixes the epoch. Only faults in
    :data:`CALIBRATION_FAULTS` are counted -- an outage does not make the scale wrong, so a detector
    that stays quiet through one is correct rather than blind.

    This docstring said exactly that before the code did, and the first `ladder` sweep is what
    caught the difference: all nine `S5_outage` runs reported `recall 0.000, missed 3`, which reads
    off the table as "the drift detectors caught nothing" when in fact they were scored against
    three events they are not built to see.
    """
    if truth.empty:
        return []
    epoch_us = float(truth["ts_peak_us"].iloc[0]) - float(truth["t_peak_s"].iloc[0]) * 1e6

    times: list[int] = []
    for fault in cfg.scenario.faults:
        if fault.type not in CALIBRATION_FAULTS:
            continue
        start = getattr(fault, "t_start_s", None)
        if start is None:
            start = getattr(fault, "t_s", None)
        if start is None:
            continue
        times.append(int(epoch_us + float(start) * 1e6))
    return sorted(times)


def _matched_errors(truth, result) -> list[tuple[int, float]]:
    """``(ts_us, signed error)`` for every event matched to a reference pass."""
    from wimsim.experiments.scoring import match_events

    matched, _missed, _spurious = match_events(result.events, truth)
    if matched.empty:
        return []
    return [
        (int(row.ts_peak_us), float(row.mass_kg) - float(row.true_mass_kg))
        for row in matched.itertuples(index=False)
    ]
