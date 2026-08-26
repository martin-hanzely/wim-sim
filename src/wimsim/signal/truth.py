"""The ground-truth log.

**This module is quarantined.** It is the only place that knows the true mass of a vehicle, the
true gain, the true zero line and the true sensor temperature. Nothing under ``wimsim/calibration``
or ``wimsim/edge`` may import it -- or indeed anything else under ``wimsim.signal`` --  and
``tests/test_truth_isolation.py`` fails the build if that ever changes. Principle 1 is enforced by
the import graph, not by good intentions.

Two artifacts are produced:

``truth_passes.parquet``
    One row per vehicle pass: the static mass to be estimated, the load actually applied (they
    differ whenever body bounce is enabled), the plant state the pass met, and the noise-free peak
    and area it contributed. The last two exist so the phase-2 event detector can be scored against
    what was really there rather than against another estimate.

``truth_timeseries.parquet``
    The plant state sampled at ``output.truth_rate_hz``: ``q``, ``k``, ``alpha``, both temperatures,
    the clock offset, and the set of faults active at that instant. This is what the truth exporter
    of phase 4 publishes as ``source="truth"`` metric series, so estimated gain can be drawn on the
    same axes as real gain.

Pass ids are deterministic, so re-running a scenario produces the same keys and a replay is
idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from wimsim.core.config import RunConfig
from wimsim.core.types import VehiclePass, to_epoch_us
from wimsim.signal.faults import FaultSet
from wimsim.signal.generator import GeneratedBlock

__all__ = ["PARQUET_OPTIONS", "TruthLog"]

#: Fixed so that two runs of the same config produce byte-identical files. Do not "tune" these.
PARQUET_OPTIONS = {
    "compression": "zstd",
    "compression_level": 3,
    "version": "2.6",
    "write_statistics": True,
    "store_schema": True,
}


def _f64(name: str) -> pa.Field:
    return pa.field(name, pa.float64())


TIMESERIES_SCHEMA = pa.schema(
    [
        pa.field("t_s", pa.float64()),
        pa.field("ts_us", pa.int64()),
        _f64("q_true"),
        _f64("k_true"),
        _f64("alpha_true"),
        _f64("t_sensor_true"),
        _f64("t_ambient_true"),
        _f64("clock_offset_s"),
        pa.field("active_faults", pa.string()),
    ]
)

PASS_SCHEMA = pa.schema(
    [
        pa.field("pass_id", pa.string()),
        pa.field("pass_index", pa.int32()),
        pa.field("vehicle_class", pa.string()),
        _f64("t_entry_s"),
        _f64("t_exit_s"),
        _f64("t_peak_s"),
        pa.field("ts_peak_us", pa.int64()),
        _f64("speed_mps"),
        _f64("speed_kmh"),
        pa.field("axle_count", pa.int32()),
        pa.field("axle_times_s", pa.list_(pa.float64())),
        pa.field("axle_static_kg", pa.list_(pa.float64())),
        pa.field("axle_applied_kg", pa.list_(pa.float64())),
        _f64("pulse_fwhm_s"),
        _f64("true_mass_kg"),
        _f64("applied_mass_kg"),
        _f64("dynamic_error_kg"),
        _f64("peak_load_kg"),
        _f64("area_load_kg_s"),
        _f64("k_at_peak"),
        _f64("q_at_peak"),
        _f64("alpha_at_peak"),
        _f64("t_sensor_at_peak"),
        _f64("true_peak_units"),
        _f64("true_area_units"),
        pa.field("faults_at_peak", pa.string()),
        pa.field("truncated", pa.bool_()),
    ]
)


@dataclass
class TruthLog:
    """Accumulates truth while the generator runs, then writes it.

    Timeseries rows stream straight to disk; pass rows are held in memory, which is fine -- a 72 h
    run at realistic traffic is under ten thousand passes.
    """

    cfg: RunConfig
    faults: FaultSet
    passes: list[VehiclePass]
    out_dir: Path

    _writer: pq.ParquetWriter | None = field(default=None, init=False, repr=False)
    _rows: dict[str, list] = field(default_factory=dict, init=False, repr=False)
    _seen: set[int] = field(default_factory=set, init=False, repr=False)
    _n_timeseries: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._rows = {f.name: [] for f in PASS_SCHEMA}
        self._writer = pq.ParquetWriter(
            self.out_dir / "truth_timeseries.parquet", TIMESERIES_SCHEMA, **PARQUET_OPTIONS
        )
        self._peak_times = (
            np.array([p.t_peak_s for p in self.passes]) if self.passes else np.empty(0)
        )
        self._start_us_value = to_epoch_us(self.cfg.scenario.start_time)

    # -- ingestion -----------------------------------------------------------------------

    def observe(self, block: GeneratedBlock, *, global_offset: int) -> None:
        """Record everything truth-side from one generated block."""
        self._write_timeseries(block, global_offset)
        self._stamp_passes(block)

    def _write_timeseries(self, block: GeneratedBlock, global_offset: int) -> None:
        ratio = self.cfg.truth_ratio
        t = block.truth
        n = t.t_s.shape[0]
        # global sample indices divisible by the ratio, so rows land on exact truth-grid ticks
        first = (-global_offset) % ratio
        if first >= n:
            return
        sel = slice(first, n, ratio)
        ts_us = block.samples.ts_us[sel] - np.rint(t.clock_offset_s[sel] * 1_000_000).astype(
            np.int64
        )
        table = pa.table(
            {
                "t_s": t.t_s[sel],
                "ts_us": ts_us,
                "q_true": t.q_true[sel],
                "k_true": t.k_true[sel],
                "alpha_true": t.alpha_true[sel],
                "t_sensor_true": t.t_sensor_true[sel],
                "t_ambient_true": t.t_ambient_true[sel],
                "clock_offset_s": t.clock_offset_s[sel],
                "active_faults": self.faults.decode_mask(t.fault_mask[sel]),
            },
            schema=TIMESERIES_SCHEMA,
        )
        assert self._writer is not None
        self._writer.write_table(table)
        self._n_timeseries += table.num_rows

    def _stamp_passes(self, block: GeneratedBlock) -> None:
        """Attach the plant state each pass actually met, at its peak."""
        if not self.passes:
            return
        t = block.truth
        t0, t1 = float(t.t_s[0]), float(t.t_s[-1])
        idx = np.flatnonzero((self._peak_times >= t0) & (self._peak_times <= t1))
        for i in idx.tolist():
            p = self.passes[i]
            if p.index in self._seen:
                continue
            self._seen.add(p.index)
            self._append_row(p, t, truncated=False)

    def _append_row(self, p: VehiclePass, t, *, truncated: bool) -> None:
        tp = p.t_peak_s
        k = float(np.interp(tp, t.t_s, t.k_true)) if not truncated else float("nan")
        q = float(np.interp(tp, t.t_s, t.q_true)) if not truncated else float("nan")
        alpha = float(np.interp(tp, t.t_s, t.alpha_true)) if not truncated else float("nan")
        temp = float(np.interp(tp, t.t_s, t.t_sensor_true)) if not truncated else float("nan")
        if truncated:
            labels = ""
        else:
            mask = self.faults.active_mask(np.array([tp]))
            labels = self.faults.decode_mask(mask)[0]

        row = {
            "pass_id": p.pass_id,
            "pass_index": p.index,
            "vehicle_class": p.vehicle_class,
            "t_entry_s": p.t_entry_s,
            "t_exit_s": p.t_exit_s,
            "t_peak_s": tp,
            "ts_peak_us": int(round(tp * 1_000_000)) + self._start_us_value,
            "speed_mps": p.speed_mps,
            "speed_kmh": p.speed_mps * 3.6,
            "axle_count": p.axle_count,
            "axle_times_s": list(p.axle_times_s),
            "axle_static_kg": list(p.axle_static_kg),
            "axle_applied_kg": list(p.axle_applied_kg),
            "pulse_fwhm_s": p.pulse_fwhm_s[0],
            "true_mass_kg": p.true_mass_kg,
            "applied_mass_kg": p.applied_mass_kg,
            "dynamic_error_kg": p.applied_mass_kg - p.true_mass_kg,
            "peak_load_kg": p.peak_load_kg,
            "area_load_kg_s": p.area_load_kg_s,
            "k_at_peak": k,
            "q_at_peak": q,
            "alpha_at_peak": alpha,
            "t_sensor_at_peak": temp,
            "true_peak_units": k * p.peak_load_kg,
            "true_area_units": k * p.area_load_kg_s,
            "faults_at_peak": labels,
            "truncated": truncated,
        }
        for key, value in row.items():
            self._rows[key].append(value)

    # -- finalisation --------------------------------------------------------------------

    def close(self) -> dict[str, int]:
        """Flush both files. Returns row counts."""
        # passes whose peak fell past the end of the run never got stamped
        for p in self.passes:
            if p.index not in self._seen:
                self._seen.add(p.index)
                self._append_row(p, None, truncated=True)

        if self._writer is not None:
            self._writer.close()
            self._writer = None

        order = np.argsort(np.asarray(self._rows["pass_index"], dtype=np.int64), kind="stable")
        columns = {name: [self._rows[name][i] for i in order.tolist()] for name in self._rows}
        table = pa.table(columns, schema=PASS_SCHEMA)
        pq.write_table(table, self.out_dir / "truth_passes.parquet", **PARQUET_OPTIONS)
        return {"truth_timeseries_rows": self._n_timeseries, "truth_pass_rows": table.num_rows}
