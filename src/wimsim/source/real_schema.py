"""The drop-in schema for real recordings, and the validator that enforces it.

Fixed **before** the data exists, on purpose. A schema negotiated after the recordings arrive is a
schema shaped by whatever the logger happened to emit; a schema fixed beforehand is a specification
the recording either meets or does not. Full prose in ``docs/real-data-schema.md``.

    data/real/<run_id>/samples.parquet    ts, channel_id, raw_value[, temperature_c]
    data/real/<run_id>/run.yaml           station, sample rate, ADC, excitation, gauge factor, map
    data/real/<run_id>/reference.csv      pass_id, reference_mass_kg, t_approx, vehicle description

:func:`validate_run` reports the four things that actually go wrong with field recordings, in the
order they hurt:

1. **timestamp gaps** -- dropped blocks, which silently shorten integration windows;
2. **clock jumps** -- non-monotonic or backwards time, usually an NTP step mid-recording;
3. **saturation** -- samples pinned at an ADC rail, where the peak is unrecoverable;
4. **dropouts** -- runs of identical values, i.e. a channel that stopped reporting.

It reports rather than repairs. A recording that fails is a fact about the recording, and deciding
what to do about it is not the validator's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import yaml

__all__ = [
    "OPTIONAL_SAMPLE_COLUMNS",
    "REQUIRED_REFERENCE_COLUMNS",
    "REQUIRED_RUN_KEYS",
    "REQUIRED_SAMPLE_COLUMNS",
    "ValidationReport",
    "validate_run",
]

#: ``ts`` is UTC microseconds since epoch, int64. Not a float, not a local-time string: both lose
#: resolution or ordering, and both have cost real projects their event alignment.
REQUIRED_SAMPLE_COLUMNS: dict[str, str] = {
    "ts": "int64 -- UTC microseconds since the Unix epoch",
    "channel_id": "string -- must appear in run.yaml channel_map",
    "raw_value": "int64 (ADC counts) or float64 (mV/V) -- declare which in run.yaml raw_value_kind",
}

OPTIONAL_SAMPLE_COLUMNS: dict[str, str] = {
    "temperature_c": "float64 -- co-located probe reading, degC",
}

REQUIRED_RUN_KEYS: dict[str, str] = {
    "station_id": "str",
    "sample_rate_hz": "float",
    "raw_value_kind": "'counts' or 'mv_per_v' -- which of the two raw_value is",
    "adc_bits": "int",
    "adc_range": "[min, max] in the unit implied by raw_value_kind",
    "channel_map": "mapping channel_id -> {sensor_id, lane, role}",
}

OPTIONAL_RUN_KEYS: dict[str, str] = {
    "excitation_v": "float -- bridge excitation voltage",
    "gauge_factor": "float",
    "start_time": "ISO 8601 UTC -- informational; ts is authoritative",
    "notes": "str",
}

REQUIRED_REFERENCE_COLUMNS: dict[str, str] = {
    "pass_id": "str -- unique within the run",
    "reference_mass_kg": "float -- static mass from a weighbridge or a known load",
    "t_approx": "ISO 8601 UTC or epoch microseconds -- approximate crossing time, used to match",
}

OPTIONAL_REFERENCE_COLUMNS: dict[str, str] = {
    "axle_reference_kg": "semicolon-separated per-axle static loads",
    "vehicle_description": "str",
    "speed_kmh": "float",
}


@dataclass
class ValidationReport:
    run_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _validate_run_yaml(path: Path, report: ValidationReport) -> dict[str, Any]:
    if not path.exists():
        report.add_error(f"missing {path.name}")
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        report.add_error(f"{path.name}: expected a YAML mapping")
        return {}
    for key in REQUIRED_RUN_KEYS:
        if key not in data:
            report.add_error(f"{path.name}: missing required key {key!r}")
    kind = data.get("raw_value_kind")
    if kind is not None and kind not in {"counts", "mv_per_v"}:
        report.add_error(
            f"{path.name}: raw_value_kind must be 'counts' or 'mv_per_v', got {kind!r}"
        )
    rng = data.get("adc_range")
    if rng is not None and (
        not isinstance(rng, (list, tuple)) or len(rng) != 2 or rng[1] <= rng[0]
    ):
        report.add_error(f"{path.name}: adc_range must be [min, max] with max > min")
    if not isinstance(data.get("channel_map", {}), dict):
        report.add_error(f"{path.name}: channel_map must be a mapping")
    return data


def _validate_samples(
    path: Path, run: dict[str, Any], report: ValidationReport, *, gap_tolerance: float
) -> None:
    if not path.exists():
        report.add_error(f"missing {path.name}")
        return

    schema = pq.read_schema(path)
    names = set(schema.names)
    for col in REQUIRED_SAMPLE_COLUMNS:
        if col not in names:
            report.add_error(f"{path.name}: missing required column {col!r}")
    if report.errors:
        return

    table = pq.read_table(
        path, columns=[c for c in ("ts", "channel_id", "raw_value") if c in names]
    )
    ts = table.column("ts").to_numpy(zero_copy_only=False).astype(np.int64)
    channels = table.column("channel_id").to_pylist()
    raw = table.column("raw_value").to_numpy(zero_copy_only=False).astype(np.float64)

    report.stats["rows"] = int(ts.size)
    report.stats["channels"] = sorted(set(channels))
    if ts.size == 0:
        report.add_error(f"{path.name}: no rows")
        return
    report.stats["t_start_us"] = int(ts.min())
    report.stats["t_end_us"] = int(ts.max())
    report.stats["duration_s"] = float((ts.max() - ts.min()) / 1e6)

    declared = run.get("channel_map")
    if isinstance(declared, dict):
        unknown = sorted(set(channels) - set(declared))
        if unknown:
            report.add_error(
                f"{path.name}: channel_id values not in run.yaml channel_map: {unknown}"
            )

    # per-channel timing, because interleaved channels look non-monotonic when pooled
    for ch in sorted(set(channels)):
        sel = np.array([c == ch for c in channels])
        t = ts[sel]
        order = np.argsort(t, kind="stable")
        if not np.array_equal(order, np.arange(t.size)):
            report.add_warning(f"channel {ch}: rows are not stored in timestamp order")
        t = t[order]
        d = np.diff(t)
        if (d <= 0).any():
            back = int((d < 0).sum())
            dup = int((d == 0).sum())
            report.add_error(
                f"channel {ch}: clock is not strictly increasing "
                f"({back} backwards steps, {dup} duplicate timestamps)"
            )
        if d.size:
            fs = run.get("sample_rate_hz")
            nominal = float(np.median(d))
            report.stats[f"median_dt_us[{ch}]"] = nominal
            if fs:
                expected = 1e6 / float(fs)
                if abs(nominal - expected) > 0.02 * expected:
                    report.add_error(
                        f"channel {ch}: median sample interval {nominal:.1f} us disagrees with "
                        f"declared sample_rate_hz {fs} ({expected:.1f} us)"
                    )
            gaps = np.flatnonzero(d > gap_tolerance * nominal)
            if gaps.size:
                worst = float(d[gaps].max() / 1e3)
                report.add_warning(
                    f"channel {ch}: {gaps.size} timestamp gaps beyond {gap_tolerance}x the sample "
                    f"interval; largest {worst:.1f} ms"
                )
                report.stats[f"gaps[{ch}]"] = int(gaps.size)

        v = raw[sel][order]
        rng = run.get("adc_range")
        bits = run.get("adc_bits")
        # The rails live in whichever domain raw_value is expressed in. Comparing counts against a
        # mV/V range (or the reverse) would flag an entire recording as saturated, which is exactly
        # the class of unit error `raw_value_kind` exists to prevent -- including here.
        if run.get("raw_value_kind") == "counts" and bits:
            lo, hi = 0.0, float((1 << int(bits)) - 1)
        elif isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
        else:
            lo = hi = None
        if lo is not None and hi is not None:
            span = hi - lo
            pinned = int(((v <= lo + 1e-9 * span) | (v >= hi - 1e-9 * span)).sum())
            if pinned:
                report.add_warning(
                    f"channel {ch}: {pinned} samples ({100 * pinned / v.size:.2f} %) sit at an "
                    f"ADC rail; peaks in those windows are unrecoverable"
                )
                report.stats[f"saturated[{ch}]"] = pinned

        # a run of identical values longer than ~10 ms is a stuck channel, not real signal
        if v.size > 1:
            changes = np.flatnonzero(np.diff(v) != 0)
            edges = np.concatenate([[-1], changes, [v.size - 1]])
            runs = np.diff(edges)
            fs = float(run.get("sample_rate_hz") or 0.0)
            threshold = max(int(0.01 * fs), 8) if fs else 8
            stuck = int((runs > threshold).sum())
            if stuck:
                report.add_warning(
                    f"channel {ch}: {stuck} runs of >{threshold} identical samples "
                    f"(longest {int(runs.max())}); looks like a dropout, not signal"
                )
                report.stats[f"stuck_runs[{ch}]"] = stuck


def _validate_reference(path: Path, report: ValidationReport) -> None:
    if not path.exists():
        report.add_warning(
            "no reference.csv -- the run can be replayed but not scored, and cannot drive "
            "supervised calibration"
        )
        return
    header_line = path.read_text(encoding="utf-8").splitlines()
    if not header_line:
        report.add_error("reference.csv is empty")
        return
    header = [h.strip() for h in header_line[0].split(",")]
    for col in REQUIRED_REFERENCE_COLUMNS:
        if col not in header:
            report.add_error(f"reference.csv: missing required column {col!r}")
    report.stats["reference_rows"] = max(len(header_line) - 1, 0)
    if len(header_line) <= 1:
        report.add_warning("reference.csv has a header but no rows")


def validate_run(run_dir: Path, *, gap_tolerance: float = 3.0) -> ValidationReport:
    """Check a dropped-in recording against the schema. Reports; never modifies."""
    run_dir = Path(run_dir)
    report = ValidationReport(run_dir=run_dir)
    if not run_dir.is_dir():
        report.add_error(f"{run_dir} is not a directory")
        return report

    run = _validate_run_yaml(run_dir / "run.yaml", report)
    _validate_samples(run_dir / "samples.parquet", run, report, gap_tolerance=gap_tolerance)
    _validate_reference(run_dir / "reference.csv", report)
    return report
