"""Writing a run to disk.

A *run directory* is the unit of reproducibility. It holds

    manifest.json            provenance, the fully resolved config, row counts, output hash
    config.yaml              the resolved config again, in the form you would edit
    samples.parquet          the sample stream (subject to output.samples)
    truth_passes.parquet     one row per vehicle pass          <- truth domain
    truth_timeseries.parquet the plant state over time         <- truth domain

and nothing else. ``manifest.json`` carries an ``output_hash`` over the three data files, which is
the object the determinism test compares: two runs of the same config and seed must produce the
same hash, and the files themselves must be byte-identical.

``output.samples`` controls how much of the stream is kept:

``full``
    Every sample. Exact, and grows at ``sample_rate * duration`` -- 4 GB for 72 h at 2 kHz.
``windows`` (default)
    Only samples within ``window_pad_s`` of a pass. Keeps every waveform that matters plus enough
    quiet signal either side to estimate a zero line, and discards the empty road between them.
    Rows carry a ``segment_id`` so a consumer can tell contiguous stretches apart instead of
    inferring it from timestamp gaps.
``none``
    No sample file. For long experiment sweeps where only events and truth are scored.

Note that ``windows`` changes only what is *written*. The signal is always generated in full, so a
run's truth and its statistics do not depend on this setting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from wimsim.core.config import RunConfig
from wimsim.core.provenance import collect, hash_files
from wimsim.signal.generator import GeneratedBlock, SignalGenerator
from wimsim.signal.truth import PARQUET_OPTIONS, TruthLog

__all__ = ["SAMPLE_SCHEMA", "RunResult", "write_run"]

SAMPLE_SCHEMA = pa.schema(
    [
        pa.field("ts_us", pa.int64()),
        pa.field("t_s", pa.float64()),
        pa.field("channel_id", pa.string()),
        pa.field("raw_counts", pa.int32()),
        pa.field("raw_value", pa.float64()),
        pa.field("temperature_c", pa.float64()),
        pa.field("saturated", pa.bool_()),
        pa.field("valid", pa.bool_()),
        pa.field("segment_id", pa.int32()),
    ]
)


@dataclass(frozen=True, slots=True)
class RunResult:
    out_dir: Path
    manifest: dict
    generator: SignalGenerator


class _SampleWriter:
    """Streams the sample columns to parquet, applying the windowing policy."""

    def __init__(self, cfg: RunConfig, out_dir: Path, keep_windows: np.ndarray | None) -> None:
        self.cfg = cfg
        self.path = out_dir / "samples.parquet"
        self.keep_windows = keep_windows
        self.rows = 0
        self._segment = -1
        self._prev_kept_index: int | None = None
        self._writer = pq.ParquetWriter(self.path, SAMPLE_SCHEMA, **PARQUET_OPTIONS)

    def write(self, block: GeneratedBlock, global_offset: int) -> None:
        s = block.samples
        n = s.n
        if self.keep_windows is None:
            sel = np.ones(n, dtype=bool)
        else:
            starts, ends = self.keep_windows
            # a sample is kept when its time falls inside any pass window
            i = np.searchsorted(starts, s.t_s, side="right") - 1
            sel = np.zeros(n, dtype=bool)
            valid = i >= 0
            sel[valid] = s.t_s[valid] <= ends[i[valid]]
            if not sel.any():
                return

        idx = np.flatnonzero(sel)
        globals_ = idx + global_offset
        # a new segment starts wherever the kept indices are not consecutive
        breaks = np.ones(idx.size, dtype=bool)
        if idx.size:
            breaks[1:] = np.diff(globals_) != 1
            if self._prev_kept_index is not None and globals_[0] == self._prev_kept_index + 1:
                breaks[0] = False
            segment_ids = self._segment + np.cumsum(breaks)
            self._segment = int(segment_ids[-1])
            self._prev_kept_index = int(globals_[-1])
        else:
            return

        table = pa.table(
            {
                "ts_us": s.ts_us[idx],
                "t_s": s.t_s[idx],
                "channel_id": pa.array([s.channel_id] * idx.size, pa.string()),
                "raw_counts": s.raw_counts[idx].astype(np.int32),
                "raw_value": s.raw_value[idx],
                "temperature_c": s.temperature_c[idx],
                "saturated": s.saturated[idx],
                "valid": s.valid[idx],
                "segment_id": segment_ids.astype(np.int32),
            },
            schema=SAMPLE_SCHEMA,
        )
        self._writer.write_table(table)
        self.rows += table.num_rows

    def close(self) -> None:
        self._writer.close()


def _merge_windows(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Union of possibly overlapping intervals, sorted by start."""
    if starts.size == 0:
        return starts, ends
    order = np.argsort(starts, kind="stable")
    starts, ends = starts[order], ends[order]
    out_s = [starts[0]]
    out_e = [ends[0]]
    for s, e in zip(starts[1:].tolist(), ends[1:].tolist(), strict=True):
        if s <= out_e[-1]:
            out_e[-1] = max(out_e[-1], e)
        else:
            out_s.append(s)
            out_e.append(e)
    return np.asarray(out_s), np.asarray(out_e)


def write_run(
    cfg: RunConfig,
    out_dir: Path,
    *,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> RunResult:
    """Generate a run and write it to ``out_dir``. Returns the manifest and the generator used."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gen = SignalGenerator(cfg)
    out_cfg = cfg.scenario.output

    keep = None
    if out_cfg.samples == "windows":
        pad = out_cfg.window_pad_s
        if gen.passes:
            keep = _merge_windows(
                np.array([p.t_entry_s - pad for p in gen.passes]),
                np.array([p.t_exit_s + pad for p in gen.passes]),
            )
        else:
            keep = (np.empty(0), np.empty(0))

    if out_cfg.samples == "full" and cfg.sample_count > out_cfg.max_sample_rows and not force:
        raise ValueError(
            f"writing {cfg.sample_count:,} sample rows exceeds output.max_sample_rows "
            f"({out_cfg.max_sample_rows:,}); pass force=True, lower the duration, or use "
            f"output.samples: windows"
        )

    sample_writer = None if out_cfg.samples == "none" else _SampleWriter(cfg, out_dir, keep)
    truth = TruthLog(cfg=cfg, faults=gen.faults, passes=gen.passes, out_dir=out_dir)

    offset = 0
    total_blocks = -(-cfg.sample_count // cfg.block_size)
    for block in gen.blocks():
        truth.observe(block, global_offset=offset)
        if sample_writer is not None:
            sample_writer.write(block, offset)
        offset += block.samples.n
        if progress is not None:
            progress(block.index + 1, total_blocks)

    counts = truth.close()
    if sample_writer is not None:
        sample_writer.close()
        counts["sample_rows"] = sample_writer.rows
    else:
        counts["sample_rows"] = 0

    (out_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )

    data_files = [
        p
        for p in (
            out_dir / "samples.parquet",
            out_dir / "truth_passes.parquet",
            out_dir / "truth_timeseries.parquet",
        )
        if p.exists()
    ]
    prov = collect(config_hash=cfg.config_hash(), seed=cfg.scenario.seed, mode=cfg.mode)

    manifest = {
        "run_id": out_dir.name,
        "scenario": cfg.scenario.name,
        "station_id": cfg.station.station_id,
        "sensor_id": cfg.station.sensor_id,
        "provenance": prov.as_dict(),
        "output_hash": hash_files(data_files),
        "files": {p.name: p.stat().st_size for p in data_files},
        "counts": {**counts, "passes_scheduled": len(gen.passes)},
        "duration_s": cfg.scenario.duration_s,
        "sample_rate_hz": cfg.station.sample_rate_hz,
        "samples_policy": out_cfg.samples,
        "faults_applied": gen.faults.summary(),
        "faults_unapplied": gen.faults.unapplied,
        "config": cfg.model_dump(mode="json"),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return RunResult(out_dir=out_dir, manifest=manifest, generator=gen)
