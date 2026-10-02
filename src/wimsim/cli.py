"""``wimsim`` -- the command line.

Command surface:

    wimsim scenarios                       list scenarios and stations
    wimsim pipelines                       list edge pipeline configs
    wimsim config-hash SCENARIO            resolve a config and print its hash
    wimsim generate SCENARIO --out DIR     generate a run
    wimsim inspect DIR                     what is in a run directory
    wimsim run DIR --edge default          run the edge pipeline and score it against truth
    wimsim control DIR                     close the loop: detect drift, recalibrate, verify
    wimsim recompute --from TS --profile P  re-derive stored history under another profile
    wimsim profiles FILE                   show a station's calibration history
    wimsim experiment NAME                 run a sweep and write the results table
    wimsim detect SCENARIO                 what the detector finds, synthetic or replayed
    wimsim gap-report REAL_DIR             where the simulator and the sensor disagree
    wimsim write-estimated-reference DIR   reference masses from inference, NOT a weighing
    wimsim score-real REAL_DIR             score a recording against its reference.csv
    wimsim score-corpus ROOT               leave-one-recording-out across the corpus
    wimsim check-channels ROOT             watch two gauges against each other, no references
    wimsim edge-run DIR                    stream a run to the broker, traced and measured
    wimsim ingest                          broker -> TimescaleDB, with a dead-letter queue
    wimsim load-truth DIR                  load a run's truth log into the truth.* schema
    wimsim plot-pass DIR --index 0         the phase-1 checkpoint figure
    wimsim plot-run DIR                    plant ground truth over the whole run
    wimsim verify-determinism DIR_A DIR_B  prove two runs are byte-identical
    wimsim validate-real-data DIR          check a dropped-in recording
    wimsim real-data-schema                print the schema real recordings must satisfy

Every command that resolves a config accepts ``--set path.to.key=value``, so an experiment sweep
never needs a generated YAML file.
"""

from __future__ import annotations

import contextlib
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from wimsim import __version__
from wimsim.core.config import CONFIG_ROOT, load_run_config
from wimsim.core.provenance import sha256_file

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Weigh-in-Motion self-calibration testbed. Not a metrological instrument.",
)

ScenarioArg = Annotated[str, typer.Argument(help="Scenario name (configs/scenarios) or a path.")]
StationOpt = Annotated[
    str | None, typer.Option("--station", help="Override the scenario's station config.")
]
SetOpt = Annotated[
    list[str] | None,
    typer.Option("--set", "-s", help="Override a config value: scenario.duration_s=600"),
]
SeedOpt = Annotated[int | None, typer.Option("--seed", help="Override the scenario seed.")]


def _resolve(scenario: str, station: str | None, sets: list[str] | None, seed: int | None):
    try:
        return load_run_config(scenario, station, overrides=list(sets or []), seed=seed)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _echo_kv(rows: list[tuple[str, object]], width: int = 24) -> None:
    for key, value in rows:
        typer.echo(f"  {key:<{width}} {value}")


# ------------------------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the version and schema version."""
    from wimsim import SCHEMA_VERSION

    typer.echo(f"wimsim {__version__} (event schema {SCHEMA_VERSION})")


@app.command()
def scenarios() -> None:
    """List available scenarios and stations."""
    typer.secho("stations", bold=True)
    for path in sorted(CONFIG_ROOT.joinpath("stations").glob("*.y*ml")):
        typer.echo(f"  {path.stem}")
    typer.secho("scenarios", bold=True)
    for path in sorted(CONFIG_ROOT.joinpath("scenarios").glob("*.y*ml")):
        if path.stem.startswith("_"):
            continue
        try:
            cfg = load_run_config(path.stem)
        except Exception as exc:  # a broken config should be visible here, not at run time
            typer.secho(f"  {path.stem:<22} BROKEN: {type(exc).__name__}", fg=typer.colors.RED)
            continue
        hours = cfg.scenario.duration_s / 3600.0
        typer.echo(
            f"  {path.stem:<22} {hours:6.1f} h  {cfg.station.sample_rate_hz:>6.0f} Hz  "
            f"{cfg.mode:<9} {len(cfg.scenario.faults)} faults  {cfg.scenario.description[:44]}"
        )


@app.command("config-hash")
def config_hash_cmd(
    scenario: ScenarioArg,
    station: StationOpt = None,
    set_: SetOpt = None,
    seed: SeedOpt = None,
    show: Annotated[
        bool, typer.Option("--show", help="Also print the resolved config as JSON.")
    ] = False,
) -> None:
    """Resolve a config and print its hash. The hash is what stamps every artifact."""
    cfg = _resolve(scenario, station, set_, seed)
    typer.echo(cfg.config_hash())
    if show:
        typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2, sort_keys=True))


@app.command()
def generate(
    scenario: ScenarioArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Run directory to write.")],
    station: StationOpt = None,
    set_: SetOpt = None,
    seed: SeedOpt = None,
    samples: Annotated[
        str | None, typer.Option("--samples", help="Override output.samples: full|windows|none")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Write more rows than max_sample_rows.")
    ] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")] = False,
) -> None:
    """Generate a synthetic run into a run directory."""
    sets = list(set_ or [])
    if samples is not None:
        sets.append(f"scenario.output.samples={samples}")
    cfg = _resolve(scenario, station, sets, seed)

    if cfg.mode != "synthetic":
        typer.secho(
            f"scenario {cfg.scenario.name!r} has source.kind={cfg.mode!r}. Generation is for "
            "synthetic scenarios; replay is driven by the pipeline from phase 6.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    from wimsim.signal.writer import write_run

    if not quiet:
        typer.secho(f"{cfg.scenario.name}", bold=True)
        _echo_kv(
            [
                ("station", f"{cfg.station.station_id}/{cfg.station.sensor_id}"),
                (
                    "duration",
                    f"{cfg.scenario.duration_s:,.0f} s ({cfg.scenario.duration_s / 3600:.2f} h)",
                ),
                (
                    "sample rate",
                    f"{cfg.station.sample_rate_hz:,.0f} Hz -> {cfg.sample_count:,} samples",
                ),
                ("plant grid", f"{cfg.scenario.plant_rate_hz:,.0f} Hz"),
                ("seed", cfg.scenario.seed),
                ("config hash", cfg.config_hash()[:16]),
                ("samples policy", cfg.scenario.output.samples),
                ("faults", ", ".join(f.label for f in cfg.scenario.faults) or "none"),
            ]
        )

    last = [0.0]

    def progress(done: int, total: int) -> None:
        now = time.perf_counter()
        if quiet or (now - last[0] < 0.4 and done != total):
            return
        last[0] = now
        bar = int(30 * done / max(total, 1))
        sys.stderr.write(f"\r  [{'#' * bar}{'.' * (30 - bar)}] block {done}/{total}")
        sys.stderr.flush()
        if done == total:
            sys.stderr.write("\n")

    t0 = time.perf_counter()
    try:
        result = write_run(cfg, out, force=force, progress=progress)
    except ValueError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    elapsed = time.perf_counter() - t0

    if not quiet:
        counts = result.manifest["counts"]
        typer.secho(f"wrote {out}", fg=typer.colors.GREEN)
        _echo_kv(
            [
                ("elapsed", f"{elapsed:.1f} s"),
                ("passes", counts["passes_scheduled"]),
                ("sample rows", f"{counts['sample_rows']:,}"),
                ("truth rows", f"{counts['truth_timeseries_rows']:,}"),
                ("output hash", result.manifest["output_hash"][:16]),
            ]
        )
        if result.manifest["faults_unapplied"]:
            typer.secho(
                "  note: these faults belong to later phases and were NOT applied: "
                + ", ".join(result.manifest["faults_unapplied"]),
                fg=typer.colors.YELLOW,
            )
        if result.manifest["provenance"]["git_dirty"]:
            typer.secho(
                "  note: working tree is dirty, so git_commit does not identify the code that ran",
                fg=typer.colors.YELLOW,
            )


@app.command()
def inspect(run_dir: Annotated[Path, typer.Argument(help="A run directory.")]) -> None:
    """Summarise a run directory: provenance, counts, faults, truth statistics."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        typer.secho(f"{run_dir} has no manifest.json", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prov = manifest["provenance"]

    typer.secho(f"{manifest['scenario']}  ({manifest['run_id']})", bold=True)
    _echo_kv(
        [
            ("station", f"{manifest['station_id']}/{manifest['sensor_id']}"),
            ("mode", prov["mode"]),
            ("duration", f"{manifest['duration_s']:,.0f} s"),
            ("sample rate", f"{manifest['sample_rate_hz']:,.0f} Hz"),
            ("seed", prov["seed"]),
            ("config hash", prov["config_hash"]),
            ("output hash", manifest["output_hash"]),
            ("schema version", prov["schema_version"]),
            (
                "git",
                f"{prov['git_commit'] or 'not a checkout'}{' (dirty)' if prov['git_dirty'] else ''}",
            ),
            ("created", prov["created_at"]),
            ("wimsim", f"{prov['wimsim_version']} on python {prov['python_version']}"),
        ]
    )
    typer.secho("counts", bold=True)
    _echo_kv([(k, f"{v:,}") for k, v in manifest["counts"].items()])
    typer.secho("files", bold=True)
    _echo_kv([(k, f"{v / 1e6:,.1f} MB") for k, v in manifest["files"].items()])

    if manifest["faults_applied"]:
        typer.secho("faults applied", bold=True)
        for f in manifest["faults_applied"]:
            typer.echo(f"  {f['label']:<22} {f['type']}")
    if manifest["faults_unapplied"]:
        typer.secho("faults NOT applied (later phases)", bold=True, fg=typer.colors.YELLOW)
        _echo_kv([(label, "") for label in manifest["faults_unapplied"]])

    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return
    passes_path = run_dir / "truth_passes.parquet"
    if passes_path.exists():
        p = pd.read_parquet(passes_path)
        typer.secho("truth passes", bold=True)
        _echo_kv(
            [
                (
                    "classes",
                    ", ".join(f"{k}={v}" for k, v in p.vehicle_class.value_counts().items()),
                ),
                (
                    "mass kg",
                    f"min {p.true_mass_kg.min():,.0f}  mean {p.true_mass_kg.mean():,.0f}  max {p.true_mass_kg.max():,.0f}",
                ),
                (
                    "speed km/h",
                    f"min {p.speed_kmh.min():.0f}  mean {p.speed_kmh.mean():.0f}  max {p.speed_kmh.max():.0f}",
                ),
                (
                    "dynamic error kg",
                    f"sd {p.dynamic_error_kg.std():,.1f}  max |{p.dynamic_error_kg.abs().max():,.0f}|",
                ),
                ("truncated", int(p.truncated.sum())),
            ]
        )
    ts_path = run_dir / "truth_timeseries.parquet"
    if ts_path.exists():
        t = pd.read_parquet(ts_path)
        k0 = manifest["config"]["station"]["sensor"]["k0"]
        typer.secho("truth plant state", bold=True)
        _echo_kv(
            [
                ("q range", f"{t.q_true.min():.5f} .. {t.q_true.max():.5f}"),
                (
                    "k/k0 - 1",
                    f"{100 * (t.k_true.min() / k0 - 1):+.3f} % .. {100 * (t.k_true.max() / k0 - 1):+.3f} %",
                ),
                ("T sensor", f"{t.t_sensor_true.min():.1f} .. {t.t_sensor_true.max():.1f} degC"),
                ("T ambient", f"{t.t_ambient_true.min():.1f} .. {t.t_ambient_true.max():.1f} degC"),
                ("faulted time", f"{100 * (t.active_faults.fillna('') != '').mean():.1f} %"),
            ]
        )


@app.command("plot-pass")
def plot_pass_cmd(
    run_dir: Annotated[Path, typer.Argument(help="A run directory.")],
    index: Annotated[int, typer.Option("--index", "-i", help="Pass index within the run.")] = 0,
    pass_id: Annotated[
        str | None, typer.Option("--pass-id", help="Select by pass_id instead.")
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
) -> None:
    """Plot one vehicle pass with its ground truth. The phase-1 checkpoint."""
    from wimsim.plots import plot_pass

    path = plot_pass(run_dir, index=index, pass_id=pass_id, out_path=out)
    typer.secho(f"wrote {path}", fg=typer.colors.GREEN)


@app.command("plot-run")
def plot_run_cmd(
    run_dir: Annotated[Path, typer.Argument(help="A run directory.")],
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
) -> None:
    """Plot the plant ground truth over a whole run."""
    from wimsim.plots import plot_run

    path = plot_run(run_dir, out_path=out)
    typer.secho(f"wrote {path}", fg=typer.colors.GREEN)


@app.command("verify-determinism")
def verify_determinism(
    a: Annotated[Path, typer.Argument(help="First run directory.")],
    b: Annotated[Path, typer.Argument(help="Second run directory.")],
) -> None:
    """Compare two run directories. Same seed + same config must mean byte-identical output."""
    names = ["samples.parquet", "truth_passes.parquet", "truth_timeseries.parquet"]
    ok = True
    for name in names:
        pa, pb = a / name, b / name
        if pa.exists() != pb.exists():
            typer.secho(f"  {name:<26} MISSING on one side", fg=typer.colors.RED)
            ok = False
            continue
        if not pa.exists():
            continue
        ha, hb = sha256_file(pa), sha256_file(pb)
        same = ha == hb
        ok &= same
        colour = typer.colors.GREEN if same else typer.colors.RED
        typer.secho(f"  {name:<26} {'identical' if same else 'DIFFERS'}  {ha[:16]}", fg=colour)

    for path in (a, b):
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        typer.echo(
            f"  {path!s:<26} config {manifest['provenance']['config_hash'][:16]}  "
            f"output {manifest['output_hash'][:16]}"
        )
    if not ok:
        typer.secho("determinism check FAILED", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho("determinism check passed", fg=typer.colors.GREEN)


@app.command("validate-real-data")
def validate_real_data(
    run_dir: Annotated[Path, typer.Argument(help="A directory under data/real/.")],
    gap_tolerance: Annotated[
        float, typer.Option("--gap-tolerance", help="Flag gaps beyond this many sample intervals.")
    ] = 3.0,
) -> None:
    """Check a dropped-in real recording against the expected schema, before it reaches the pipeline."""
    from wimsim.source.real_schema import validate_run

    report = validate_run(run_dir, gap_tolerance=gap_tolerance)

    if report.stats:
        typer.secho("stats", bold=True)
        _echo_kv(list(report.stats.items()), width=26)
    if report.warnings:
        typer.secho("warnings", bold=True, fg=typer.colors.YELLOW)
        for w in report.warnings:
            typer.echo(f"  - {w}")
    if report.errors:
        typer.secho("errors", bold=True, fg=typer.colors.RED)
        for e in report.errors:
            typer.echo(f"  - {e}")
        typer.secho(f"{run_dir} does NOT satisfy the schema", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(f"{run_dir} satisfies the real-data schema", fg=typer.colors.GREEN)


@app.command("import-csv")
def import_csv_cmd(
    src: Annotated[Path, typer.Argument(help="A multichannel CSV export from the logger.")],
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Run directory to write under data/real/.")
    ],
    station_id: Annotated[str, typer.Option("--station-id", help="Station this was recorded at.")],
    gauge_factor: Annotated[
        float | None, typer.Option("--gauge-factor", help="Strain gauge factor, e.g. 2.0.")
    ] = None,
    excitation_v: Annotated[
        float | None, typer.Option("--excitation-v", help="Bridge excitation voltage.")
    ] = None,
    bridge: Annotated[str | None, typer.Option("--bridge", help="quarter | half | full.")] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", help="Zone the source's naive timestamp is in.")
    ] = "Europe/Bratislava",
    notes: Annotated[
        str, typer.Option("--notes", help="Anything unusual about this recording.")
    ] = "",
    inspect_only: Annotated[
        bool, typer.Option("--inspect-only", help="Parse the header and stop.")
    ] = False,
) -> None:
    """Convert a logger CSV export into the drop-in schema, then validate it.

    Prints the timezone it assumed, because the source timestamp carries none and a wrong guess
    shifts every timestamp in the recording by the offset with nothing downstream able to notice.
    """
    from wimsim.source.import_csv import import_csv, parse_header

    try:
        header = parse_header(src)
    except (OSError, ValueError) as exc:
        typer.secho(f"cannot read {src}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    typer.secho(f"{src.name}", bold=True)
    _echo_kv(
        [
            ("source timestamp", f"{header.start_time_local:%Y-%m-%d %H:%M:%S} (naive, local)"),
            ("assumed timezone", timezone),
            ("interval", f"{header.interval_s * 1e6:.1f} us -> {header.sample_rate_hz:,.0f} Hz"),
            ("channels", ", ".join(f"{c.name}[{c.unit}]={c.role}" for c in header.channels)),
        ]
    )
    unknown = [c.name for c in header.channels if c.role == "auxiliary"]
    if unknown:
        typer.secho(
            f"  note: {', '.join(unknown)} have unrecognised units and will be ignored",
            fg=typer.colors.YELLOW,
        )
    if inspect_only:
        return

    t0 = time.perf_counter()
    try:
        result = import_csv(
            src,
            out,
            station_id=station_id,
            gauge_factor=gauge_factor,
            excitation_v=excitation_v,
            bridge=bridge,
            timezone=timezone,
            notes=notes,
        )
    except (OSError, ValueError) as exc:
        typer.secho(f"import failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    _echo_kv(
        [
            ("start (UTC)", result.start_time_utc.isoformat()),
            ("duration", f"{result.duration_s:,.3f} s"),
            ("strain channels", ", ".join(result.strain_channels)),
            ("temperature pairing", ", ".join(f"{k}<-{v}" for k, v in result.pairing.items())),
            ("sample rows", f"{result.sample_rows:,}"),
            ("elapsed", f"{time.perf_counter() - t0:.1f} s"),
        ]
    )
    typer.secho(f"wrote {out}", fg=typer.colors.GREEN)

    from wimsim.source.real_schema import validate_run

    report = validate_run(out)
    if report.warnings:
        typer.secho("warnings", bold=True, fg=typer.colors.YELLOW)
        for w in report.warnings:
            typer.echo(f"  - {w}")
    if report.errors:
        typer.secho("errors", bold=True, fg=typer.colors.RED)
        for e in report.errors:
            typer.echo(f"  - {e}")
        raise typer.Exit(1)
    typer.secho("satisfies the real-data schema", fg=typer.colors.GREEN)


@app.command("real-data-schema")
def real_data_schema() -> None:
    """Print the schema a real recording must satisfy. Fixed before the data exists, on purpose."""
    from wimsim.source import real_schema as rs

    def block(title: str, required: dict[str, str], optional: dict[str, str]) -> None:
        typer.secho(title, bold=True)
        for name, desc in required.items():
            typer.echo(f"  {name:<22} required   {desc}")
        for name, desc in optional.items():
            typer.echo(f"  {name:<22} optional   {desc}")

    typer.echo("data/real/<run_id>/")
    block("  samples.parquet", rs.REQUIRED_SAMPLE_COLUMNS, rs.OPTIONAL_SAMPLE_COLUMNS)
    block("  run.yaml", rs.REQUIRED_RUN_KEYS, rs.OPTIONAL_RUN_KEYS)
    block("  reference.csv", rs.REQUIRED_REFERENCE_COLUMNS, rs.OPTIONAL_REFERENCE_COLUMNS)
    typer.echo("\nSee docs/real-data-schema.md for the reasoning behind each field.")


@app.command("pipelines")
def pipelines() -> None:
    """List available edge pipeline configurations."""
    from wimsim.core.config import load_edge_config

    typer.secho("pipelines (configs/estimators)", bold=True)
    for path in sorted(CONFIG_ROOT.joinpath("estimators").glob("*.y*ml")):
        if path.stem.startswith("_"):
            continue
        try:
            edge = load_edge_config(path.stem)
        except Exception as exc:
            typer.secho(f"  {path.stem:<17} BROKEN: {type(exc).__name__}", fg=typer.colors.RED)
            continue
        typer.echo(
            f"  {path.stem:<17} {edge.estimate.feature:<5} {edge.preprocess.filter:<13}"
            f" {edge.estimate.estimator:<14} {edge.description[:44]}"
        )


@app.command()
def run(
    run_dir: Annotated[Path, typer.Argument(help="A run directory produced by `generate`.")],
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config name.")] = "default",
    set_: SetOpt = None,
    calibration_passes: Annotated[
        int | None,
        typer.Option("--calibration-passes", help="Passes reserved to fit the profile."),
    ] = None,
    write: Annotated[
        bool, typer.Option("--write/--no-write", help="Write events.parquet and score.json.")
    ] = True,
) -> None:
    """Run the edge pipeline over a run and score it against the truth log.

    The sample stream is regenerated from the run's config rather than read back, so this works even
    when the run kept no samples -- same seed and config give a byte-identical stream by
    construction.
    """
    from wimsim.core.config import load_edge_config
    from wimsim.experiments.offline import load_run, run_offline

    try:
        cfg, truth, _manifest = load_run(run_dir)
        edge_cfg = load_edge_config(edge, overrides=list(set_ or []))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    t0 = time.perf_counter()
    try:
        result = run_offline(cfg, truth, edge_cfg, calibration_passes=calibration_passes)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    elapsed = time.perf_counter() - t0

    s = result.score
    typer.secho(f"{cfg.scenario.name} x {edge_cfg.name}", bold=True)
    _echo_kv(
        [
            ("feature", f"{edge_cfg.estimate.feature} / {edge_cfg.estimate.axle_summation}"),
            ("preprocessing", edge_cfg.preprocess.filter),
            ("estimator", result.profile.state.estimator),
            ("profile", result.profile.profile_id),
            ("fitted from", f"{result.calibration_passes} reference passes"),
            ("sensor gain", f"{result.profile.state.sensor_gain:.6g} units/kg"),
            ("elapsed", f"{elapsed:.1f} s"),
        ]
    )
    typer.secho("detection", bold=True)
    _echo_kv(
        [
            ("matched", f"{s.n_matched}/{s.n_truth}"),
            ("recall", f"{s.recall:.4f}"),
            ("false positives", f"{s.n_false_positive} ({100 * s.false_positive_rate:.2f} %)"),
            ("axle count accuracy", f"{s.axle_count_accuracy:.4f}"),
        ]
    )
    typer.secho("accuracy", bold=True)
    _echo_kv(
        [
            ("MAE", f"{s.mae_kg:,.2f} kg"),
            ("MAPE", f"{100 * s.mape:.3f} %"),
            ("RMSE", f"{s.rmse_kg:,.2f} kg"),
            ("bias", f"{s.bias_kg:+,.2f} kg"),
            ("vs applied load", f"{s.mae_vs_applied_kg:,.2f} kg"),
            ("dynamic floor", f"{s.dynamic_floor_kg:,.2f} kg"),
        ]
    )
    typer.secho("uncertainty", bold=True)
    _echo_kv(
        [
            ("empirical coverage", f"{s.coverage:.4f}"),
            ("nominal", f"{edge_cfg.estimate.coverage_target:.2f}"),
            ("mean interval width", f"{s.mean_interval_width_kg:,.1f} kg"),
        ]
    )
    if s.per_class:
        typer.secho("by vehicle class", bold=True)
        for name, stats in sorted(s.per_class.items()):
            typer.echo(
                f"  {name:<16} n={stats['n']:<5} MAE {stats['mae_kg']:>9,.2f} kg"
                f"   MAPE {100 * stats['mape']:>6.3f} %   bias {stats['bias_kg']:+9,.2f} kg"
            )

    if write:
        out = Path(run_dir)
        (out / f"score.{edge_cfg.name}.json").write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_events(out / f"events.{edge_cfg.name}.parquet", result.events)
        typer.secho(
            f"wrote score.{edge_cfg.name}.json and events.{edge_cfg.name}.parquet",
            fg=typer.colors.GREEN,
        )


@app.command("edge-run")
def edge_run(
    run_dir: Annotated[Path, typer.Argument(help="A run directory produced by `generate`.")],
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config name.")] = "default",
    broker: Annotated[str, typer.Option("--broker", help="MQTT broker host:port.")] = (
        "localhost:1883"
    ),
    otlp: Annotated[
        str | None,
        typer.Option(
            "--otlp",
            help="OTLP collector endpoint. Defaults to $OTEL_EXPORTER_OTLP_ENDPOINT; "
            "without either, the run is unobserved but still correct.",
        ),
    ] = None,
    spool: Annotated[
        Path | None, typer.Option("--spool", help="Persistent queue file. Default: DIR/spool.db")
    ] = None,
    speed: Annotated[
        float | None,
        typer.Option(
            "--speed",
            help="Replay speed multiplier. 1.0 is real time. Omit to run flat out, which is "
            "right for a smoke test and wrong for looking at a dashboard.",
        ),
    ] = None,
    calibration_passes: Annotated[
        int | None, typer.Option("--calibration-passes", help="Passes reserved to fit the profile.")
    ] = None,
    set_: SetOpt = None,
) -> None:
    """Stream a run through the edge pipeline and out to the broker, with spans and metrics.

    This is the phase-4 checkpoint made runnable: a pass published this way can be selected in Tempo
    and followed from `acquire` through to `persist`. It is not a scoring command -- use `run` for
    that -- and it deliberately leaves the truth log alone. `load-truth` puts truth in the database,
    where the dashboards join it.
    """
    from wimsim.core.config import load_edge_config
    from wimsim.experiments.live import run_live
    from wimsim.experiments.offline import load_run
    from wimsim.observability.logging import configure_logging
    from wimsim.observability.metrics import build_metrics
    from wimsim.observability.tracing import build_tracing
    from wimsim.transport import PersistentQueue, Publisher
    from wimsim.transport.mqtt import MqttTransport

    try:
        cfg, truth, _manifest = load_run(run_dir)
        edge_cfg = load_edge_config(edge, overrides=list(set_ or []))
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    station_id = cfg.station.station_id
    run_id = f"{cfg.scenario.name}-{cfg.config_hash()[:12]}"
    host, _, port = broker.partition(":")

    configure_logging(station_id=station_id, run_id=run_id, endpoint=otlp)
    metrics = build_metrics(station_id=station_id, run_id=run_id, endpoint=otlp)
    tracing = build_tracing(station_id=station_id, run_id=run_id, endpoint=otlp)

    transport = MqttTransport(host=host, port=int(port or 1883), client_id=f"wimsim-{station_id}")
    queue = PersistentQueue(spool or Path(run_dir) / "spool.db")
    publisher = Publisher(
        transport, queue=queue, station_id=station_id, metrics=metrics, tracing=tracing
    )

    typer.secho(f"{cfg.scenario.name} -> {broker}", bold=True)
    _echo_kv(
        [
            ("station", station_id),
            ("run id", run_id),
            ("collector", otlp or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "(none)"),
            ("traced", "yes" if tracing.enabled else "no"),
            ("metrics", "yes" if metrics.enabled else "no"),
            ("speed", f"{speed}x" if speed else "unpaced"),
        ]
    )

    try:
        transport.connect()
    except Exception as exc:
        typer.secho(f"cannot reach the broker at {broker}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from exc

    t0 = time.perf_counter()
    try:
        result = run_live(
            cfg,
            truth,
            edge_cfg,
            publisher=publisher,
            metrics=metrics,
            tracing=tracing,
            calibration_passes=calibration_passes,
            speed=speed,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    finally:
        publisher.close()
        transport.disconnect()
    elapsed = time.perf_counter() - t0

    metrics.flush()
    typer.secho("published", bold=True)
    _echo_kv(
        [
            ("profile", result.profile_id),
            ("events", result.published),
            ("still buffered", result.buffered),
            ("elapsed", f"{elapsed:.1f} s"),
            ("worst pacing lag", f"{result.max_lag_s:.3f} s" if speed else "n/a"),
        ]
    )
    if result.buffered:
        typer.secho(
            f"{result.buffered} events are still spooled in {queue.path}; they will be replayed "
            "the next time this station publishes.",
            fg=typer.colors.YELLOW,
        )

    metrics.shutdown()


@app.command()
def ingest(
    broker: Annotated[str, typer.Option("--broker", help="MQTT broker host:port.")] = (
        "localhost:1883"
    ),
    database: Annotated[
        str | None, typer.Option("--database", help="SQLAlchemy URL. Default: the local stack.")
    ] = None,
    station: Annotated[
        str, typer.Option("--station", help="Station filter; '+' subscribes to all.")
    ] = "+",
    otlp: Annotated[str | None, typer.Option("--otlp", help="OTLP collector endpoint.")] = None,
    seconds: Annotated[
        float | None,
        typer.Option("--seconds", help="Stop after this long. Omit to run until interrupted."),
    ] = None,
) -> None:
    """Subscribe, validate, and write to TimescaleDB, dead-lettering whatever cannot be accepted.

    The other half of `edge-run`: it continues each pass's trace from the context in the payload,
    so `ingest` and `persist` land in the same Tempo trace as the `publish` that produced them.
    """
    from wimsim.ingest import IngestConsumer
    from wimsim.observability.logging import configure_logging, get_logger
    from wimsim.observability.metrics import build_metrics
    from wimsim.observability.tracing import build_tracing
    from wimsim.storage import EventWriter

    host, _, port = broker.partition(":")
    configure_logging(station_id=station, endpoint=otlp)
    log = get_logger("ingest")
    metrics = build_metrics(station_id=station, endpoint=otlp)
    tracing = build_tracing(station_id=station, service_name="wimsim-ingest", endpoint=otlp)

    writer = EventWriter(database)
    consumer = IngestConsumer(
        writer,
        host=host,
        port=int(port or 1883),
        station_filter=station,
        metrics=metrics,
        tracing=tracing,
    )

    typer.secho(f"ingest {broker} -> {database or 'the local stack'}", bold=True)
    _echo_kv([("stations", station), ("traced", "yes" if tracing.enabled else "no")])

    deadline = None if seconds is None else time.monotonic() + seconds
    try:
        consumer.start()
    except Exception as exc:
        typer.secho(f"cannot subscribe: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from exc

    try:
        while deadline is None or time.monotonic() < deadline:
            consumer.poll()
            time.sleep(0.1)
    except KeyboardInterrupt:
        typer.echo("")
    finally:
        consumer.stop()
        stats = consumer.stats.as_dict()
        writer.dispose()

    metrics.flush()
    log.info("ingest finished", extra=stats)
    typer.secho("ingested", bold=True)
    _echo_kv(
        [
            ("accepted", stats["accepted"]),
            ("written", stats["written"]),
            ("rejected", stats["rejected"]),
            ("by reason", stats["by_reason"] or "none"),
        ]
    )


@app.command("load-truth")
def load_truth_cmd(
    run_dir: Annotated[Path, typer.Argument(help="A run directory produced by `generate`.")],
    database: Annotated[
        str | None, typer.Option("--database", help="SQLAlchemy URL. Default: the local stack.")
    ] = None,
) -> None:
    """Load a run's truth log into the ``truth.*`` schema, where the dashboards join it.

    Kept as its own command rather than folded into `edge-run`, because the separation is the point:
    a station never writes truth, and in replay mode there is none to write. The dashboards degrade
    to showing only what was measured, which is the correct behaviour for real data.
    """
    from wimsim.experiments.live import load_truth
    from wimsim.experiments.offline import load_run
    from wimsim.storage import EventWriter

    try:
        cfg, _truth, _manifest = load_run(run_dir)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    run_id = f"{cfg.scenario.name}-{cfg.config_hash()[:12]}"
    writer = EventWriter(database)
    try:
        passes, series = load_truth(
            writer, run_dir, run_id=run_id, station_id=cfg.station.station_id
        )
    except Exception as exc:
        typer.secho(f"database error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from exc
    finally:
        writer.dispose()

    typer.secho(
        f"loaded {passes} truth passes and {series} plant states as run {run_id}",
        fg=typer.colors.GREEN,
    )


@app.command()
def control(
    run_dir: Annotated[Path, typer.Argument(help="A run directory produced by `generate`.")],
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config name.")] = "default",
    estimator: Annotated[
        str | None,
        typer.Option("--estimator", help="Override the estimator: static_affine, rls, kalman."),
    ] = None,
    reference_every: Annotated[
        int | None,
        typer.Option(
            "--reference-every",
            help="One pass in N is a reference vehicle. In the field this is the transponder or "
            "weighbridge supply rate, and it decides whether self-calibration is possible at all.",
        ),
    ] = None,
    uncertainty: Annotated[
        str | None, typer.Option("--uncertainty", help="analytic or conformal.")
    ] = None,
    no_control: Annotated[
        bool,
        typer.Option(
            "--no-control", help="Run the same loop with the controller off: the control arm."
        ),
    ] = False,
    profiles_out: Annotated[
        Path | None,
        typer.Option(
            "--profiles", help="Append the calibration history here. Default: DIR/profiles.jsonl"
        ),
    ] = None,
    otlp: Annotated[
        str | None,
        typer.Option(
            "--otlp",
            help="OTLP collector endpoint. With one, the controller's own series -- drift "
            "statistics, the state one-hot, residuals, recalibration counts -- reach the "
            "calibration dashboard's phase-5 panels, which are otherwise empty. Defaults to "
            "$OTEL_EXPORTER_OTLP_ENDPOINT; without either the run is unobserved but identical.",
        ),
    ] = None,
    broker: Annotated[
        str | None,
        typer.Option(
            "--broker",
            help="Publish the resulting events to this MQTT broker (host:port), so the "
            "calibration dashboard has per-profile masses to draw the gain overlay from. Omit to "
            "keep the run entirely local.",
        ),
    ] = None,
    calibration_passes: Annotated[
        int | None,
        typer.Option("--calibration-passes", help="Passes reserved for the initial fit."),
    ] = None,
    set_: SetOpt = None,
    write: Annotated[
        bool, typer.Option("--write/--no-write", help="Write control.json and events parquet.")
    ] = True,
) -> None:
    """Run the edge pipeline with the phase-5 controller in the loop.

    The phase-5 checkpoint: on `S4_step_fault` this should show a detection, a recalibration and a
    reconvergence. `--no-control` runs the identical pipeline with the controller disabled, which is
    the arm every claim about the controller has to be measured against.
    """
    from wimsim.calibration import ProfileStore
    from wimsim.core.config import load_edge_config
    from wimsim.experiments.closed_loop import run_closed_loop
    from wimsim.experiments.offline import load_run

    sets = list(set_ or [])
    sets.append(f"edge.control.enabled={'false' if no_control else 'true'}")
    if estimator:
        sets.append(f"edge.estimate.estimator={estimator}")
    if reference_every:
        sets.append(f"edge.control.reference_every_n={reference_every}")
    if uncertainty:
        sets.append(f"edge.uncertainty.method={uncertainty}")

    try:
        cfg, truth, _manifest = load_run(run_dir)
        edge_cfg = load_edge_config(edge, overrides=sets)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    store_path = profiles_out or Path(run_dir) / f"profiles.{edge_cfg.name}.jsonl"
    store = None
    if write:
        # One `control` invocation is one experiment, and its calibration history belongs to that
        # experiment -- so the file starts empty rather than appending to whatever a previous run
        # left, which would collide on the bootstrap profile every time. The store itself stays
        # strictly append-only: a real station accumulates across restarts, and truncating here is
        # the CLI's decision about experiment scope, not a hole in that invariant.
        if store_path.exists():
            store_path.unlink()
        store = ProfileStore(store_path)

    from wimsim.observability.metrics import build_metrics

    metrics = build_metrics(
        station_id=cfg.station.station_id,
        run_id=f"{cfg.scenario.name}-{cfg.config_hash()[:12]}",
        endpoint=otlp,
    )

    typer.secho(f"{cfg.scenario.name} x {edge_cfg.name}", bold=True)
    _echo_kv(
        [
            ("estimator", edge_cfg.estimate.estimator),
            ("controller", "off" if no_control else "on"),
            ("detectors", ", ".join(edge_cfg.drift.detectors)),
            ("interval", edge_cfg.uncertainty.method),
            ("reference supply", f"1 pass in {edge_cfg.control.reference_every_n}"),
            ("metrics", "yes" if metrics.enabled else "no"),
        ]
    )

    t0 = time.perf_counter()
    try:
        result = run_closed_loop(
            cfg,
            truth,
            edge_cfg,
            calibration_passes=calibration_passes,
            profile_store=store,
            metrics=metrics,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    elapsed = time.perf_counter() - t0

    s = result.score
    typer.secho("control loop", bold=True)
    _echo_kv(
        [
            ("passes detected", result.n_detected),
            ("reference vehicles", result.n_references),
            (
                "detectors ready after",
                "never"
                if result.detectors_ready_after_references is None
                else f"{result.detectors_ready_after_references} references",
            ),
            ("drift alarms", result.alarms),
            ("recalibrations", result.recalibrations),
            ("degradations", result.degradations),
            ("profiles activated", len(result.profiles)),
            ("final state", result.to_dict()["final_state"]),
            ("elapsed", f"{elapsed:.1f} s"),
        ]
    )
    typer.secho("accuracy", bold=True)
    _echo_kv(
        [
            ("MAE", f"{s.mae_kg:,.2f} kg"),
            ("MAPE", f"{100 * s.mape:.3f} %"),
            ("bias", f"{s.bias_kg:+,.2f} kg"),
            ("dynamic floor", f"{s.dynamic_floor_kg:,.2f} kg"),
            ("empirical coverage", f"{s.coverage:.4f}"),
            ("nominal", f"{edge_cfg.estimate.coverage_target:.2f}"),
            ("mean interval width", f"{s.mean_interval_width_kg:,.1f} kg"),
        ]
    )

    if result.controller_events:
        # Relative to the run start: the epoch microseconds these carry are the station clock, and
        # "1748750867.5s" tells a reader nothing about when in a 16-hour scenario it happened.
        origin_us = min(e.ts_us for e in result.controller_events)
        origin_us = min(origin_us, result.events[0].ts_start if result.events else origin_us)
        typer.secho("what the controller did", bold=True)
        for event in result.controller_events:
            hours = (event.ts_us - origin_us) / 1e6 / 3600.0
            typer.echo(
                f"  +{hours:>5.2f} h  {event.state:<16} {event.kind:<18} {event.reason[:58]}"
            )

    # Before anything else that could fail: the periodic exporter drops its current interval on
    # exit, so a command that returns without this loses the tail of the run -- or all of it, if
    # the run was shorter than one interval.
    metrics.flush()

    if broker:
        _publish_events(
            result.events, broker=broker, station_id=cfg.station.station_id, metrics=metrics
        )

    if write:
        out = Path(run_dir)
        (out / f"control.{edge_cfg.name}.json").write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_events(out / f"events.control.{edge_cfg.name}.parquet", result.events)
        typer.secho(
            f"wrote control.{edge_cfg.name}.json, events and {store_path.name}",
            fg=typer.colors.GREEN,
        )

    metrics.shutdown()


@app.command()
def profiles(
    path: Annotated[Path, typer.Argument(help="A profiles.jsonl written by `control`.")],
) -> None:
    """Show a station's calibration history: what was activated, when, and why."""
    from wimsim.calibration import ProfileStore

    store = ProfileStore(path)
    if not len(store):
        typer.secho(f"no profiles in {path}", fg=typer.colors.YELLOW)
        return

    typer.secho(f"{len(store)} profiles in {path}", bold=True)
    typer.echo(
        f"  {'profile':<24} {'activated (s)':>14} {'estimator':<14} {'sensor gain':>13}  reason"
    )
    for profile in store:
        state = profile.state
        typer.echo(
            f"  {profile.profile_id:<24} {profile.activated_ts_us / 1e6:>14.1f} "
            f"{state.estimator:<14} {state.sensor_gain:>13.6g}  {profile.reason}"
            + ("" if profile.superseded_by else "   <- active")
        )


@app.command()
def recompute(
    profile_id: Annotated[str, typer.Option("--profile", help="Profile id to re-derive under.")],
    from_ts: Annotated[
        str,
        typer.Option(
            "--from",
            help="Recompute events at or after this time: an ISO-8601 instant, or integer "
            "microseconds since the epoch.",
        ),
    ],
    store_path: Annotated[
        Path, typer.Option("--profiles", help="The profiles.jsonl holding that profile.")
    ],
    station: Annotated[str | None, typer.Option("--station", help="Limit to one station.")] = None,
    database: Annotated[
        str | None, typer.Option("--database", help="SQLAlchemy URL. Default: the local stack.")
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply/--dry-run",
            help="Dry run by default. Recompute is an in-place rewrite of stored measurements, "
            "so it asks before doing it.",
        ),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Most events to pull in one pass.")
    ] = 100_000,
) -> None:
    """Re-derive stored events under a different calibration profile.

    Buildspec section 6. The rewrite is in place: `event_id` is a UUIDv5 of station, sensor and
    `ts_start` and of nothing else, so a recomputed event keeps its id and the upsert replaces the
    row rather than inserting a second opinion about the same vehicle.

    Dry run unless `--apply` is given, because there is no undo.
    """
    from datetime import datetime

    from wimsim.calibration import ProfileStore
    from wimsim.experiments.recompute import recompute_rows
    from wimsim.storage import EventWriter

    try:
        from_ts_us = int(from_ts)
    except ValueError:
        try:
            from_ts_us = int(datetime.fromisoformat(from_ts).timestamp() * 1e6)
        except ValueError as exc:
            typer.secho(
                f"--from {from_ts!r} is neither an ISO-8601 instant nor integer microseconds",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2) from exc

    try:
        profile = ProfileStore(store_path).get(profile_id)
    except (KeyError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    writer = EventWriter(database)
    try:
        rows = writer.read_events(station_id=station, from_ts_us=from_ts_us, limit=limit)
        result = recompute_rows(rows, profile, from_ts_us=from_ts_us)

        typer.secho(f"recompute under {profile.profile_id}", bold=True)
        _echo_kv(
            [
                ("estimator", profile.state.estimator),
                ("sensor gain", f"{profile.state.sensor_gain:.6g} units/kg"),
                ("events read", len(rows)),
                ("recomputed", result.n_recomputed),
                ("skipped (no raw peak)", result.n_skipped),
                ("no temperature", result.n_without_temperature),
            ]
        )
        if result.n_recomputed and rows:
            before = {r["event_id"]: r["mass_kg"] for r in rows}
            deltas = [r["mass_kg"] - before[r["event_id"]] for r in result.rows]
            typer.secho("mass change", bold=True)
            _echo_kv(
                [
                    ("mean", f"{sum(deltas) / len(deltas):+,.2f} kg"),
                    ("largest", f"{max(deltas, key=abs):+,.2f} kg"),
                ]
            )

        if not apply:
            typer.secho(
                "dry run: nothing written. Re-run with --apply to rewrite these rows in place.",
                fg=typer.colors.YELLOW,
            )
            return
        written = writer.write_events(result.rows)
        typer.secho(f"rewrote {written} events in place", fg=typer.colors.GREEN)
    except Exception as exc:
        typer.secho(f"database error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from exc
    finally:
        writer.dispose()


@app.command()
def experiment(
    name: Annotated[
        str, typer.Argument(help="An experiment in configs/experiments, or a path to one.")
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Where to write results. Default: data/results/<id>"),
    ] = None,
    seeds: Annotated[
        str | None,
        typer.Option(
            "--seeds",
            help="Override the seed axis, comma-separated. The shipped sweeps use three, which is "
            "what gives a number an error bar; one is for getting a table quickly and should be "
            "labelled as such when quoted.",
        ),
    ] = None,
    scenarios: Annotated[
        str | None, typer.Option("--scenarios", help="Override the scenario axis, comma-separated.")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the grid and what it will cost, and run nothing."),
    ] = False,
) -> None:
    """Run a declarative sweep and write results.parquet, results.md and results.tex.

    The phase-6 checkpoint: a results table comparing all estimators across all scenarios. A cell
    that fails becomes a row saying so rather than taking the sweep down or quietly disappearing --
    dropping it would change what every mean in the table is a mean over.
    """
    from wimsim.core.config import CONFIG_ROOT
    from wimsim.experiments.runner import load_experiment, run_experiment

    path = Path(name)
    if not path.exists():
        for candidate in (
            CONFIG_ROOT / "experiments" / f"{name}.yaml",
            CONFIG_ROOT / "experiments" / f"{name}.yml",
        ):
            if candidate.exists():
                path = candidate
                break
        else:
            available = sorted(p.stem for p in (CONFIG_ROOT / "experiments").glob("*.y*ml"))
            typer.secho(
                f"no experiment {name!r}; available: {available}", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(2)

    try:
        spec = load_experiment(path)
    except (ValueError, TypeError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    if seeds:
        spec = replace(spec, seeds=[int(v) for v in seeds.split(",") if v.strip()])
    if scenarios:
        spec = replace(spec, scenarios=[v.strip() for v in scenarios.split(",") if v.strip()])

    cells = list(spec.grid())
    typer.secho(f"{spec.experiment_id}", bold=True)
    _echo_kv(
        [
            ("scenarios", ", ".join(spec.scenarios)),
            ("estimators", ", ".join(spec.estimators)),
            ("seeds", ", ".join(str(s) for s in spec.seeds)),
            # Named only when they are axes. A sweep summary that omits an axis misreports what is
            # about to run for two hours.
            *(
                [("reference rates", ", ".join(str(r) for r in spec.reference_rates))]
                if spec.reference_rates
                else []
            ),
            *(
                [("controller", ", ".join("on" if a else "off" for a in spec.control_arms))]
                if spec.control_arms
                else []
            ),
            ("runs", len(cells)),
            ("edge config", spec.edge_config),
        ]
    )
    if spec.description:
        typer.echo(f"  {spec.description.strip()}")

    if dry_run:
        typer.secho("grid", bold=True)
        for cell in cells:
            typer.echo(f"  {cell.run_id}")
        typer.secho("dry run: nothing was executed.", fg=typer.colors.YELLOW)
        return

    started = time.perf_counter()

    def progress(index: int, total: int, cell) -> None:
        elapsed = time.perf_counter() - started
        rate = elapsed / max(index - 1, 1)
        remaining = rate * (total - index + 1) if index > 1 else 0.0
        sys.stderr.write(
            f"\r  [{index:>3}/{total}] {cell.run_id:<44} "
            f"{elapsed / 60:5.1f} min elapsed, ~{remaining / 60:5.1f} left   "
        )
        sys.stderr.flush()

    result = run_experiment(spec, out_dir=out, progress=progress)
    sys.stderr.write("\n")

    typer.secho("results", bold=True)
    _echo_kv(
        [
            ("runs", result.n_runs),
            ("failed", result.n_failed),
            ("elapsed", f"{(time.perf_counter() - started) / 60:.1f} min"),
            ("written", str(result.out_dir)),
        ]
    )
    if result.n_failed:
        typer.secho(
            f"{result.n_failed} of {result.n_runs} runs failed; they are rows in the table with "
            "their error text, not omissions.",
            fg=typer.colors.YELLOW,
        )
    typer.secho(
        "wrote results.parquet, results.md, results.tex and manifest.json",
        fg=typer.colors.GREEN,
    )


@app.command()
def compare(
    results: Annotated[
        Path, typer.Argument(help="A results directory written by `experiment`, or its parquet.")
    ],
    metric: Annotated[
        str, typer.Option("--metric", help="Column to compare. Lower is better is assumed.")
    ] = "mae_kg",
    baseline: Annotated[
        str, typer.Option("--baseline", help="Estimator the others are compared against.")
    ] = "static_affine",
) -> None:
    """Paired significance tests over a finished sweep: Wilcoxon signed-rank with Holm correction.

    Runs are paired by seed, because the same seed gives a byte-identical sample stream and the two
    arms of a comparison then differ in exactly one thing. Two families are corrected separately and
    labelled as such -- the controller's two arms, and every estimator against a baseline -- because
    correcting them together is a different claim and should have to be asked for.

    Writes `comparisons.md` and `comparisons.json` into the results directory. Three seeds cannot
    produce a significant result however large the effect (the smallest attainable two-sided p is
    0.25), and the table says so in place of the p-values rather than beside them.
    """
    import pandas as pd

    from wimsim.experiments.compare import write_comparison
    from wimsim.experiments.stats import min_attainable_p

    path = Path(results)
    parquet = path if path.is_file() else path / "results.parquet"
    if not parquet.exists():
        typer.secho(f"no results at {parquet}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    frame = pd.read_parquet(parquet)
    if metric not in frame.columns:
        typer.secho(
            f"no column {metric!r}; available: {sorted(frame.columns)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    out_dir = parquet.parent
    try:
        written = write_comparison(
            frame,
            out_dir=out_dir,
            experiment_id=out_dir.name,
            baseline=baseline,
            metric=metric,
        )
    except ValueError as exc:
        # An axis the pairing does not account for. Refused rather than resolved: see compare.py.
        typer.secho(f"cannot pair these runs: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    seeds = sorted(set(frame["seed"])) if "seed" in frame else []
    typer.secho(f"{out_dir.name}", bold=True)
    _echo_kv([("metric", metric), ("seeds", len(seeds)), ("runs", len(frame))])
    if len(seeds) < 6:
        typer.secho(
            f"{len(seeds)} seeds: the smallest attainable two-sided p is "
            f"{min_attainable_p(len(seeds)):.3g}, so nothing here can reach 0.05.",
            fg=typer.colors.YELLOW,
        )
    for path_ in written:
        typer.secho(f"wrote {path_}", fg=typer.colors.GREEN)


@app.command("detector-table")
def detector_table_cmd(
    results: Annotated[
        Path, typer.Argument(help="A results directory written by `experiment`, or its parquet.")
    ],
    by: Annotated[
        str, typer.Option("--by", help="The column that names the detector arm.")
    ] = "edge_config",
) -> None:
    """One row per scenario and detector arm, from a sweep that varied the detectors.

    Section IV-G describes four detectors in parallel; the shipped pipeline runs two, so every
    detection number reported before `configs/experiments/detectors.yaml` was the behaviour of that
    pair. This turns that sweep into `detectors.md`.

    Refused on a sweep that ran one arm, because pooled on scenario alone the arms become a single
    row describing the ensemble under a heading claiming to compare them.
    """
    import pandas as pd

    from wimsim.experiments.table import detector_table

    path = Path(results)
    parquet = path if path.is_file() else path / "results.parquet"
    if not parquet.exists():
        typer.secho(f"no results at {parquet}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    frame = pd.read_parquet(parquet)
    commit = "unknown"
    manifest = parquet.parent / "manifest.json"
    if manifest.exists():
        with contextlib.suppress(Exception):
            commit = json.loads(manifest.read_text(encoding="utf-8")).get("git_commit", "unknown")

    try:
        text = detector_table(frame, experiment_id=parquet.parent.name, git_commit=commit, by=by)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    out_path = parquet.parent / "detectors.md"
    out_path.write_text(f"{text}\n", encoding="utf-8")
    typer.secho(f"wrote {out_path}", fg=typer.colors.GREEN)


@app.command(name="reference-curve")
def reference_curve_cmd(
    results: Annotated[
        Path, typer.Argument(help="A results directory written by `experiment`, or its parquet.")
    ],
) -> None:
    """Detection recall and the governance effect against reference rate, from a rate sweep.

    Section VII-C argues the reference rate is the binding constraint by elimination. Both
    relationships are measurable directly from any sweep that varied `reference_rates`, and were
    in none of the project's outputs until this command existed.

    Writes `reference_curve.md` beside the parquet, the per-cell CSVs, the per-seed paired
    differences in long format, and redraws `recall_vs_rate.png` and `governance_vs_rate.png`
    into `figures/` -- the last of these so a sweep run before the figures existed can be brought
    up to date without re-running it.
    """
    import pandas as pd

    from wimsim.experiments.figures import write_figures
    from wimsim.experiments.reference_curve import write_reference_curve

    path = Path(results)
    parquet = path if path.is_file() else path / "results.parquet"
    if not parquet.exists():
        typer.secho(f"no results at {parquet}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    frame = pd.read_parquet(parquet)
    commit = "unknown"
    manifest = parquet.parent / "manifest.json"
    if manifest.exists():
        with contextlib.suppress(Exception):
            commit = json.loads(manifest.read_text(encoding="utf-8")).get("git_commit", "unknown")

    try:
        out = write_reference_curve(
            frame,
            out_dir=parquet.parent,
            experiment_id=parquet.parent.name,
            git_commit=commit,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    drawn = write_figures(frame, out_dir=parquet.parent, experiment_id=parquet.parent.name)
    typer.secho(f"wrote {out} and {len(drawn)} figure files", fg=typer.colors.GREEN)


@app.command("validate-sim")
def validate_sim_cmd(
    root: Annotated[
        Path, typer.Argument(help="Directory of real recordings, one run directory each.")
    ],
    channel: Annotated[
        str | None, typer.Option("--channel", help="Which channel to analyse. Default: the only.")
    ] = None,
    scenario: Annotated[
        str, typer.Option("--scenario", help="Synthetic scenario the fitted trace is generated on.")
    ] = "S1_nominal",
    station: StationOpt = "cintron_platform",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report here. Default: stdout.")
    ] = None,
) -> None:
    """Cross-validate the simulator parameters: fit on every recording but one, test on that one.

    Section V-C concedes that no simulator parameter has ever been cross-validated -- everything
    in docs/sim-to-real.md was fitted on the recordings and reported against them. This is the
    leave-one-recording-out version, which is the construction that answers whether the simulator
    reproduces the instrument or merely reproduces the minutes it was fitted on.

    Writes the measured statistics, the held-out agreement per fold, and the in-sample contrast.
    There is no pass mark: a simulator matching on every statistic would mean the statistics were
    not discriminating.
    """
    import pandas as _pd
    import pandas as pd

    from wimsim.experiments.sim_crossval import crossval_markdown, leave_one_out

    candidates = sorted(
        d for d in Path(root).iterdir() if d.is_dir() and (d / "run.yaml").is_file()
    )
    # A run directory that does not carry the channel being analysed is not a short recording of
    # it, it is a different instrument -- `data/real/EXAMPLE` is the schema sample and carries a
    # synthetic channel. Skipped by name on screen rather than silently, so the fold count in the
    # report is always a count of something a reader can check.
    runs, skipped = [], []
    for run in candidates:
        try:
            channels = set(
                _pd.read_parquet(run / "samples.parquet", columns=["channel_id"])[
                    "channel_id"
                ].unique()
            )
        except (OSError, KeyError, ValueError) as exc:
            skipped.append(f"{run.name}: {exc}")
            continue
        if channel is not None and channel not in channels:
            skipped.append(f"{run.name}: carries {sorted(channels)}, not {channel!r}")
            continue
        runs.append(run)
    for line in skipped:
        typer.secho(f"  skipped  {line[:90]}", fg=typer.colors.YELLOW)

    if len(runs) < 3:
        typer.secho(
            f"{root} holds {len(runs)} recording(s); leave-one-out needs at least three",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    typer.secho(f"{len(runs)} recordings, {len(runs)} folds", bold=True)
    for run in runs:
        typer.echo(f"  {run.name}")

    try:
        folds = leave_one_out(runs, channel=channel, scenario=scenario, station=station)
    except (OSError, KeyError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    text = crossval_markdown(folds, git_commit=_git_commit())
    if out is None:
        typer.echo(text)
        return

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sim_crossval.md").write_text(f"{text}\n", encoding="utf-8")

    rows = []
    for fold in folds:
        held = fold.agreement()
        own = fold.in_sample_agreement()
        for statistic, value in held.items():
            rows.append(
                {
                    "held_out_recording": fold.held_out,
                    "n_train": fold.fitted.n_train,
                    "statistic": statistic,
                    "held_out_log2_ratio": value,
                    "in_sample_log2_ratio": own.get(statistic),
                }
            )
    pd.DataFrame(rows).to_csv(out / "sim_crossval_long.csv", index=False)
    pd.DataFrame([f.observed.to_dict() for f in folds]).to_csv(
        out / "sim_crossval_measured.csv", index=False
    )
    typer.secho(f"wrote {out / 'sim_crossval.md'} and two CSVs", fg=typer.colors.GREEN)


@app.command()
def detect(
    scenario: ScenarioArg,
    station: StationOpt = None,
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config name.")] = "default",
    show: Annotated[
        int, typer.Option("--show", "-n", help="How many events to list. 0 lists none.")
    ] = 10,
    set_: SetOpt = None,
    seed: SeedOpt = None,
) -> None:
    """Acquire, preprocess and detect -- and stop there.

    Detection is the one part of the pipeline a real recording can drive end to end, because it
    needs no truth. Everything past it bootstraps its calibration from a truth log, and a recording
    has none; see docs/sim-to-real.md, which has said since phase 3 that turning this sensor's
    response into kilograms needs one weighed vehicle.

    So this prints crossings, widths and axle counts, and deliberately prints no masses. A mass
    here would imply a calibration that does not exist.

    The source comes from `scenario.source.kind`, which is what makes `S8_replay_real` a scenario
    rather than a document:

        wimsim detect S8_replay_real --set scenario.source.replay.run_dir=20260209_cintron1
    """
    from wimsim.core.config import load_edge_config
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _provenance_for
    from wimsim.source import build_source

    cfg = _resolve(scenario, station, set_, seed)
    # `--set` goes to the scenario here. `load_edge_config` applies overrides to its own tree, so
    # one list cannot serve both; pick a pipeline with `--edge` instead.
    try:
        edge_cfg = load_edge_config(edge)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    try:
        source = build_source(cfg)
    except (OSError, KeyError, ValueError) as exc:
        typer.secho(f"cannot read the source: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    meta = source.metadata
    pipeline = OfflinePipeline(
        edge_cfg,
        source=source,
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
    )
    events = list(pipeline.detect_only())

    typer.secho(f"{cfg.scenario.name} via {meta.mode}", bold=True)
    _echo_kv(
        [
            ("source", meta.extra.get("run_dir", "generator")),
            ("channel", meta.sensor_id),
            ("unit", meta.unit),
            ("sample rate", f"{meta.sample_rate_hz:,.0f} Hz"),
            ("events", len(events)),
            ("saturated", sum(1 for e in events if e.saturated)),
            ("with invalid samples", sum(1 for e in events if e.has_invalid)),
            ("during warm-up", sum(1 for e in events if e.warming_up)),
        ]
    )
    if not events:
        typer.secho(
            "No crossings detected. On a real recording that is a finding about the detector as "
            "much as about the road -- `wimsim gap-report` shows whether there is a pulse in "
            "there at all.",
            fg=typer.colors.YELLOW,
        )
        return

    widths = [e.t_end_s - e.t_start_s for e in events]
    axles = [len(e.axles) for e in events]
    _echo_kv(
        [
            ("median width", f"{statistics.median(widths) * 1e3:,.0f} ms"),
            ("width range", f"{min(widths) * 1e3:,.0f} - {max(widths) * 1e3:,.0f} ms"),
            ("axles per event", f"median {statistics.median(axles):.0f}, max {max(axles)}"),
        ]
    )

    if show:
        typer.secho("events", bold=True)
        typer.echo(f"  {'t_peak_s':>10}  {'width_ms':>9}  {'axles':>5}  {'peak':>12}  flags")
        for event in events[:show]:
            flags = ",".join(
                name
                for name, on in (
                    ("saturated", event.saturated),
                    ("invalid", event.has_invalid),
                    ("warming-up", event.warming_up),
                )
                if on
            )
            typer.echo(
                f"  {event.t_peak_s:10.3f}  "
                f"{(event.t_end_s - event.t_start_s) * 1e3:9.1f}  "
                f"{len(event.axles):5d}  {event.peak:12.4g}  {flags}"
            )
        if len(events) > show:
            typer.echo(f"  ... {len(events) - show} more")


@app.command("write-estimated-reference")
def write_estimated_reference_cmd(
    real_dir: Annotated[Path, typer.Argument(help="A real recording under data/real/.")],
    vehicle: Annotated[str, typer.Option("--vehicle", help="Which car crossed: fabia | citroen.")],
    channel: Annotated[str, typer.Option("--channel", help="Channel to detect on.")] = "Tenzo2",
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config.")] = (
        "cintron_platform"
    ),
) -> None:
    """Write a `reference.csv` from INFERRED wheel loads. This is not a weighing.

    No vehicle at ST-CINTRON-1 has been weighed and the rig is gone, so `S8_replay_real` has never
    been scorable. This detects the crossings, classifies each as a front or a rear wheel from the
    bimodal peak amplitude, and writes the masses `docs/sim-to-real.md` infers for them.

    What it costs is real and is stated in every row and in a sidecar beside the file: principle 1
    says ground truth is an output and never an estimator input, and here an estimate stands where
    the pipeline expects a measurement. Scoring against it measures whether the pipeline reproduces
    *the inference*, not whether it weighs vehicles.

    Refuses to overwrite a `reference.csv` with no sidecar beside it -- an estimated file can always
    be regenerated and a measured one cannot.
    """
    from wimsim.core.config import RunConfig, load_edge_config, load_run_config
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _provenance_for
    from wimsim.source import build_source
    from wimsim.source.estimated_reference import VEHICLES, write_estimated_reference

    if vehicle not in VEHICLES:
        typer.secho(
            f"unknown vehicle {vehicle!r}; known: {sorted(VEHICLES)}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)

    tree = load_run_config("S8_replay_real").model_dump(mode="json")
    tree["scenario"]["source"] = {
        "kind": "replay",
        "replay": {
            "run_dir": str(real_dir),
            "channel": channel,
            "rate": "accelerated",
            "speed_multiplier": None,
        },
    }
    try:
        cfg = RunConfig.model_validate(tree)
        edge_cfg = load_edge_config(edge)
        source = build_source(cfg)
    except (OSError, KeyError, ValueError) as exc:
        typer.secho(f"cannot read {real_dir}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    pipeline = OfflinePipeline(
        edge_cfg,
        source=source,
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
    )
    crossings = [
        (e.t_peak_s, e.peak)
        for e in pipeline.detect_only()
        if 0.3 < (e.t_end_s - e.t_start_s) < 3.0
    ]
    if not crossings:
        typer.secho(
            f"no crossings detected in {real_dir.name} on {channel}; nothing to write.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    try:
        n = write_estimated_reference(
            real_dir, crossings, vehicle=vehicle, t0_us=source.metadata.start_time_us
        )
    except (FileExistsError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    spec = VEHICLES[vehicle]
    typer.secho(f"{real_dir.name}: wrote {n} ESTIMATED reference rows", fg=typer.colors.YELLOW)
    _echo_kv(
        [
            ("vehicle", spec.name),
            ("front wheel", f"{spec.front_kg:.0f} kg  (inferred, not weighed)"),
            ("rear wheel", f"{spec.rear_kg:.0f} kg  (inferred, not weighed)"),
            ("axle split at", f"{spec.axle_cut_strain:.3g} strain"),
            ("sidecar", "reference.ESTIMATED.md"),
        ]
    )
    typer.secho(
        "These are not measurements. Scoring against them measures whether the pipeline "
        "reproduces the inference.",
        fg=typer.colors.YELLOW,
    )


@app.command("score-real")
def score_real(
    real_dir: Annotated[Path, typer.Argument(help="A real recording under data/real/.")],
    channel: Annotated[str, typer.Option("--channel", help="Channel to score.")] = "Tenzo2",
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config.")] = (
        "cintron_platform"
    ),
    calibration_passes: Annotated[
        int, typer.Option("--calibration-passes", help="Crossings reserved to fit the profile.")
    ] = 2,
    window_s: Annotated[
        float, typer.Option("--window", help="Half-width of a reference's matching window, s.")
    ] = 1.5,
    tolerance_s: Annotated[
        float, typer.Option("--tolerance", help="Event-to-reference match tolerance, s.")
    ] = 1.0,
) -> None:
    """Run the pipeline over a real recording and score it against its `reference.csv`.

    The first command in this project that produces kilograms from the real sensor. What it is
    scoring against matters: a reference measurement, not ground truth. Where the reference file
    was written by `write-estimated-reference`, the masses are an INFERENCE, and this measures
    whether the pipeline reproduces that inference rather than whether it weighs vehicles. The
    output says so when it finds the sidecar.

    A pass used to fit the calibration is never also scored.
    """
    import pandas as pd

    from wimsim.core.config import RunConfig, load_edge_config, load_run_config
    from wimsim.experiments.offline import run_offline
    from wimsim.source import build_source
    from wimsim.source.estimated_reference import SIDECAR
    from wimsim.source.reference import load_reference

    tree = load_run_config("S8_replay_real").model_dump(mode="json")
    tree["scenario"]["source"] = {
        "kind": "replay",
        "replay": {
            "run_dir": str(real_dir),
            "channel": channel,
            "rate": "accelerated",
            "speed_multiplier": None,
        },
    }
    try:
        cfg = RunConfig.model_validate(tree)
        edge_cfg = load_edge_config(edge)
        meta = build_source(cfg).metadata
        reference = load_reference(real_dir, t0_us=meta.start_time_us, window_s=window_s)
    except (OSError, KeyError, ValueError, FileNotFoundError) as exc:
        typer.secho(f"cannot score {real_dir}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    estimated = (real_dir / SIDECAR).is_file()
    typer.secho(f"{real_dir.name} / {channel}", bold=True)
    if estimated:
        typer.secho(
            "The reference masses here are ESTIMATED, not weighed. This scores whether the "
            "pipeline reproduces the inference, not whether it weighs vehicles.",
            fg=typer.colors.YELLOW,
        )

    try:
        result = run_offline(
            cfg,
            reference,
            edge_cfg,
            calibration_passes=calibration_passes,
            match_tolerance_s=tolerance_s,
        )
    except ValueError as exc:
        typer.secho(f"cannot score: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    sc = result.score
    _echo_kv(
        [
            ("references", len(reference)),
            ("detected", len(result.events)),
            ("reserved to calibrate", result.calibration_passes),
            ("matched and scored", sc.n_matched),
            ("recall", f"{sc.recall:.3f}"),
            ("MAE", f"{sc.mae_kg:,.1f} kg" if not pd.isna(sc.mae_kg) else "--"),
            ("MAPE", f"{sc.mape:.2%}" if not pd.isna(sc.mape) else "--"),
            ("bias", f"{sc.bias_kg:+,.1f} kg" if not pd.isna(sc.bias_kg) else "--"),
            ("coverage", f"{sc.coverage:.3f}" if not pd.isna(sc.coverage) else "--"),
            ("interval width", f"{sc.mean_interval_width_kg:,.0f} kg"),
            ("sensor gain", f"{result.profile.state.sensor_gain:.4g}"),
        ]
    )
    if sc.coverage_by_source:
        typer.secho("interval by construction", bold=True)
        for src, (n, cov) in sorted(sc.coverage_by_source.items()):
            typer.echo(f"  {src:<24} n={n:<4d} coverage {cov:.3f}")
    typer.secho(
        "`dynamic_floor_kg` is NaN here on purpose: a reference records a static mass and says "
        "nothing about what the vehicle's own bounce added.",
        dim=True,
    )


@app.command("score-corpus")
def score_corpus(
    root: Annotated[
        Path, typer.Argument(help="Directory holding the recordings, e.g. data/real.")
    ] = Path("data/real"),
    channel: Annotated[str, typer.Option("--channel", help="Channel to score.")] = "Tenzo2",
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config.")] = (
        "cintron_platform"
    ),
    estimator: Annotated[str, typer.Option("--estimator", help="Which estimator to fit.")] = (
        "static_affine"
    ),
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the result as JSON.")
    ] = None,
) -> None:
    """Leave-one-recording-out across every recording that has a `reference.csv`.

    `score-real` fits and scores inside one 60-second recording, where the calibration and the test
    come from the same minute of the same drive-over. This fits on every other recording and
    predicts the held-out one, which is the question actually worth asking: does a calibration
    fitted here transfer *there*.

    A whole recording is held out rather than random crossings. Crossings within a recording share
    a vehicle, a driver, a line across the platform and a minute of thermal state, and splitting
    them randomly leaks all of it across the fold boundary.
    """
    import json

    from wimsim.core.config import load_edge_config
    from wimsim.experiments.pooled import run_pooled
    from wimsim.source.estimated_reference import SIDECAR
    from wimsim.source.reference import REFERENCE_FILE

    runs = (
        sorted(d for d in root.iterdir() if (d / REFERENCE_FILE).is_file()) if root.is_dir() else []
    )
    if len(runs) < 2:
        typer.secho(
            f"{root} holds {len(runs)} recording(s) with a reference.csv; leave-one-out needs at "
            "least two.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    try:
        edge_cfg = load_edge_config(edge)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    if any((d / SIDECAR).is_file() for d in runs):
        typer.secho(
            "Reference masses in this corpus are ESTIMATED, not weighed. What follows measures "
            "whether a calibration transfers between recordings, not whether it weighs vehicles.",
            fg=typer.colors.YELLOW,
        )

    result = run_pooled(runs, edge_cfg, channel=channel, estimator=estimator)
    if not result.folds:
        typer.secho(
            f"{result.n_recordings} recording(s) yielded matched crossings; nothing to cross-"
            "validate.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    typer.secho(f"{root} / {channel} / {estimator}", bold=True)
    _echo_kv(
        [
            ("recordings", result.n_recordings),
            ("crossings matched", result.n_observations),
            ("MAE (held out)", f"{result.mae_kg:,.1f} kg"),
            ("MAPE (held out)", f"{result.mape:.2%}"),
            ("bias (held out)", f"{result.bias_kg:+,.1f} kg"),
            ("coverage (held out)", f"{result.coverage:.3f}"),
            ("gain spread across folds", f"{result.gain_spread:.1%}"),
        ]
    )
    if result.skipped:
        typer.secho("skipped", bold=True)
        for name, why in sorted(result.skipped.items()):
            typer.echo(f"  {name:<24} {_one_line(why, 60)}")
    typer.secho("per held-out recording", bold=True)
    typer.echo(f"  {'recording':<24} {'fit':>4} {'n':>3} {'MAE kg':>8} {'MAPE':>7} {'bias kg':>9}")
    for f in result.folds:
        if f.error:
            typer.echo(f"  {f.run_id:<24} {f.n_calibration:>4} {'--':>3}  {_one_line(f.error, 46)}")
            continue
        typer.echo(
            f"  {f.run_id:<24} {f.n_calibration:>4} {f.n_scored:>3} {f.mae_kg:>8,.1f} "
            f"{f.mape:>7.2%} {f.bias_kg:>+9,.1f}"
        )

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        typer.secho(f"wrote {out}", fg=typer.colors.GREEN)


def _git_commit() -> str:
    """HEAD, for stamping a report. Unknown rather than a guess when git is not available."""
    import subprocess

    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
    except OSError:  # pragma: no cover
        return "unknown"
    return done.stdout.strip() or "unknown"


def _one_line(text: object, limit: int = 60) -> str:
    joined = " ".join(str(text).split())
    return joined if len(joined) <= limit else joined[: limit - 1] + "..."


@app.command("check-channels")
def check_channels(
    root: Annotated[
        Path, typer.Argument(help="Directory holding the recordings, e.g. data/real.")
    ] = Path("data/real"),
    channel_a: Annotated[str, typer.Option("--a", help="Reference channel.")] = "Tenzo1",
    channel_b: Annotated[str, typer.Option("--b", help="Channel compared against it.")] = "Tenzo2",
    edge: Annotated[str, typer.Option("--edge", "-e", help="Pipeline config.")] = (
        "cintron_platform"
    ),
    threshold_sigma: Annotated[
        float, typer.Option("--sigma", help="Robust sigmas before a crossing counts as outside.")
    ] = 3.0,
) -> None:
    """Watch two gauges against each other. Needs no reference vehicle at all.

    Every drift detector in `calibration/` watches the residual against a known mass, so all of them
    need reference vehicles -- and the reference-rate sweep measured what that costs when references
    are scarce. Two channels viewing the same load sit at a fixed amplitude ratio, and that costs
    nothing to watch.

    It detects without diagnosing: a ratio that moves means one channel moved, and two channels give
    one equation, so which one is not recoverable from the ratio. It is also blind to anything
    common to both -- a platform losing stiffness, a temperature moving both gauges -- so it
    complements the residual detectors rather than replacing them.
    """
    import numpy as np

    from wimsim.calibration import ChannelRatioMonitor
    from wimsim.core.config import RunConfig, load_edge_config, load_run_config
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _provenance_for
    from wimsim.source import build_source

    if not root.is_dir():
        typer.secho(f"{root} is not a directory", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    try:
        edge_cfg = load_edge_config(edge)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    base = load_run_config("S8_replay_real").model_dump(mode="json")

    def crossings(run_dir: Path, channel: str):
        tree = dict(base)
        tree["scenario"] = dict(base["scenario"])
        tree["scenario"]["source"] = {
            "kind": "replay",
            "replay": {
                "run_dir": str(run_dir),
                "channel": channel,
                "rate": "accelerated",
                "speed_multiplier": None,
            },
        }
        cfg = RunConfig.model_validate(tree)
        pipeline = OfflinePipeline(
            edge_cfg,
            source=build_source(cfg),
            profile=_bootstrap_profile(edge_cfg),
            provenance=_provenance_for(cfg),
        )
        return [
            (e.t_peak_s, abs(e.peak))
            for e in pipeline.detect_only()
            if 0.3 < (e.t_end_s - e.t_start_s) < 3.0
        ]

    monitor = ChannelRatioMonitor(threshold_sigma=threshold_sigma)
    rows: list[tuple[str, float, float]] = []
    skipped: list[str] = []

    for run_dir in sorted(d for d in root.iterdir() if d.is_dir()):
        try:
            a_peaks, b_peaks = crossings(run_dir, channel_a), crossings(run_dir, channel_b)
        except (OSError, KeyError, ValueError) as exc:
            skipped.append(f"{run_dir.name}: {exc}")
            continue
        if not a_peaks or not b_peaks:
            continue
        for t_b, peak_b in b_peaks:
            j = int(np.argmin([abs(t_a - t_b) for t_a, _ in a_peaks]))
            if abs(a_peaks[j][0] - t_b) > 0.5:
                continue
            peak_a = a_peaks[j][1]
            monitor.observe(peak_a, peak_b)
            rows.append((run_dir.name, peak_b / peak_a, monitor.last_z))

    if not rows:
        typer.secho(f"no paired crossings found in {root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    median, sigma = monitor.baseline()
    typer.secho(f"{root}  {channel_b} / {channel_a}", bold=True)
    _echo_kv(
        [
            ("paired crossings", len(rows)),
            ("baseline ratio", f"{median:.3f}" if median == median else "-- (warming up)"),
            ("robust sigma", f"{sigma:.3f}" if sigma == sigma else "--"),
            (
                "resolution",
                f"~{threshold_sigma * sigma / median:.0%} single-channel change"
                if median == median and median > 0
                else "--",
            ),
            ("alarmed", "YES" if monitor.alarmed else "no"),
        ]
    )
    for line in skipped:
        typer.echo(f"  skipped  {line[:70]}")

    typer.secho("per crossing", bold=True)
    for name, ratio, z in rows:
        flag = "  <-- outside" if z > threshold_sigma else ""
        typer.echo(f"  {name:<26} {ratio:6.3f}  z={z:5.2f}{flag}")

    typer.secho(
        "Detects without diagnosing: two channels give one equation, so which gauge moved is not "
        "recoverable from the ratio. Blind to anything common to both.",
        dim=True,
    )


@app.command("gap-report")
def gap_report_cmd(
    real_dir: Annotated[Path, typer.Argument(help="A real recording, as `import-csv` writes it.")],
    scenario: Annotated[
        str, typer.Option("--scenario", help="Synthetic scenario to compare against.")
    ] = "S1_nominal",
    station: StationOpt = None,
    channel: Annotated[
        str | None, typer.Option("--channel", help="Which channel to analyse. Default: the only.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report here. Default: stdout.")
    ] = None,
    set_: SetOpt = None,
) -> None:
    """Compare a real recording against the simulator: noise, drift, and pulse shape.

    A comparison, not a verdict. There is no pass mark: a simulator that matched a real sensor on
    every statistic would mean the statistics were not discriminating. The output is where the two
    differ, by how much, and the `--set` lines that move the model towards the recording.

    docs/sim-to-real.md contains this analysis done by hand in phase 3. A hand-run analysis is a
    claim about one afternoon; this is the same analysis as something that can be re-run.
    """
    import numpy as np

    from wimsim.experiments.gap_report import (
        GapReport,
        compare_noise,
        estimate_drift_rate,
        fit_crossing,
        fit_noise_parameters,
    )
    from wimsim.source import ReplaySource, SyntheticSource

    try:
        replay = ReplaySource(real_dir, channel=channel)
        real = np.concatenate([b.raw_value for b in replay.stream_blocks()])
    except (OSError, KeyError, ValueError) as exc:
        typer.secho(f"cannot read {real_dir}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    meta = replay.metadata
    fs = float(meta.sample_rate_hz)
    duration_s = real.size / fs

    # The synthetic side is generated at the *recording's* sample rate. Comparing PSDs computed on
    # two different grids would show differences that are entirely an artefact of the grids, and
    # `noise.white_sigma` is a per-sample quantity, so its implied PSD depends on the rate too.
    synthetic_cfg = _resolve(
        scenario,
        station,
        [
            *(set_ or []),
            f"station.sample_rate_hz={fs}",
            f"scenario.duration_s={duration_s:.6f}",
            f"scenario.block_seconds={min(duration_s, 10.0):.6f}",
        ],
        None,
    )
    synthetic = np.concatenate(
        [b.raw_value for b in SyntheticSource(synthetic_cfg).stream_blocks()]
    )

    typer.secho(f"{real_dir.name} against {scenario}", bold=True)
    _echo_kv(
        [
            ("channel", meta.sensor_id),
            ("unit", meta.unit),
            ("sample rate", f"{fs:,.0f} Hz"),
            ("duration", f"{duration_s:,.1f} s"),
            ("synthetic samples", f"{synthetic.size:,}"),
        ]
    )

    notes: list[str] = []
    if meta.unit != "mV/V":
        notes.append(
            f"**The recording is in {meta.unit} and the model's sensor units are mV/V.** Every "
            f"amplitude below -- sigma, the 50 Hz line, the fitted overrides -- is in {meta.unit}, "
            "so the sigma *ratio* compares two different quantities and means nothing; read it as "
            "a reminder that the conversion is missing, not as a result. What does survive the "
            "unit mismatch is everything dimensionless: the 50 Hz excess over its own local floor "
            "in dB, the spectral slope, and the pulse-shape residuals. Converting would need the "
            "bridge configuration, which this recording does not declare, and guessing it is the "
            "class of unit error `raw_value_kind` exists to prevent."
        )
    notes += [str(w) for w in meta.extra.get("validation_warnings", [])]

    crossing = fit_crossing(real, fs=fs)
    notes.append(crossing.note)

    if duration_s < 300:
        notes.append(
            f"This recording is {duration_s:.0f} s long. Every number here is a property of that "
            "minute, not of the installation."
        )

    report = GapReport(
        real_run=real_dir.name,
        scenario=scenario,
        noise=compare_noise(synthetic, real, fs=fs),
        drift=estimate_drift_rate(real, fs=fs),
        fit=fit_noise_parameters(real, fs=fs),
        pulse=crossing.comparison,
        notes=notes,
    )

    text = report.to_markdown()
    if out is None:
        typer.echo("")
        typer.echo(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.secho(f"wrote {out}", fg=typer.colors.GREEN)


def _publish_events(events: list, *, broker: str, station_id: str, metrics) -> None:
    """Spool and publish a finished run's events.

    After the fact rather than inside the loop: the closed loop is offline by construction -- it
    re-runs the same detections under successive profiles -- so there is no live trace for a publish
    span to join. The events carry the scenario's own timestamps either way, which is what the
    dashboards join on. `edge-run` is the traced streaming path.
    """
    import tempfile

    from wimsim.transport import PersistentQueue, Publisher
    from wimsim.transport.mqtt import MqttTransport

    host, _, port = broker.partition(":")
    transport = MqttTransport(host=host, port=int(port or 1883), client_id=f"wimsim-{station_id}")
    try:
        transport.connect()
    except Exception as exc:
        typer.secho(f"cannot reach the broker at {broker}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from exc

    with tempfile.TemporaryDirectory() as tmp:
        publisher = Publisher(
            transport,
            queue=PersistentQueue(Path(tmp) / "spool.db"),
            station_id=station_id,
            metrics=metrics,
        )
        try:
            for event in events:
                publisher.publish_model(event)
            drained = publisher.flush(timeout_s=60.0)
        finally:
            publisher.close()
            transport.disconnect()

    if drained:
        typer.secho(f"published {len(events)} events to {broker}", fg=typer.colors.GREEN)
    else:
        typer.secho(
            f"published to {broker} but the spool did not drain; some events were lost with the "
            "temporary queue",
            fg=typer.colors.YELLOW,
        )


def _write_events(path: Path, events: list) -> None:
    """Flatten measurement events to a table. Nested blocks become dotted columns."""
    import pandas as pd

    rows = []
    for ev in events:
        payload = ev.model_dump(mode="json")
        flat = {k: v for k, v in payload.items() if not isinstance(v, dict)}
        for block in ("calibration", "preprocessing", "provenance"):
            for key, value in payload[block].items():
                flat[f"{block}.{key}"] = value
        rows.append(flat)
    pd.DataFrame(rows).to_parquet(path, compression="zstd", index=False)


def _configure_console() -> None:  # pragma: no cover
    """Force UTF-8 output.

    Real recordings carry non-ASCII in places the pipeline has to echo back -- channel units are
    ``degC`` and ``epsilon`` as actual Unicode, and station names may be accented. A Windows console
    defaults to cp1252 and raises ``UnicodeEncodeError`` rather than mangling, which turns printing a
    channel list into a crash. ``errors="replace"`` is the right fallback here: a substituted glyph
    in a human-readable summary is harmless, and the data files themselves are always UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main() -> None:  # pragma: no cover
    _configure_console()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
