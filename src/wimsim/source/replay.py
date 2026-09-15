"""``ReplaySource`` -- the same interface, fed from a recording.

This is where principle 2 either holds or does not. The class reads ``data/real/<run_id>/`` as
specified in :mod:`wimsim.source.real_schema` and emits exactly the same
:class:`~wimsim.core.types.SampleBlock` objects the generator emits. Downstream code cannot tell
the difference and must not try.

Two conversions happen here and nowhere else:

* **counts to sensor units.** If ``run.yaml`` declares ``raw_value_kind: counts``, the ADC range and
  bit depth from ``run.yaml`` are used to map counts onto the declared unit. If it declares
  ``mv_per_v``, the values are taken as given and counts are reconstructed for the record.
* **channel selection.** A recording may carry several channels; a replay run streams one, named by
  ``channel``, defaulting to the single channel present.

Ground truth does not exist in replay mode. ``reference.csv`` is a *reference measurement*, not a
truth log: it is sparse, it has its own uncertainty, and it is consumed by the scoring layer and by
supervised calibration -- never by this class. Dashboards that overlay true gain therefore degrade
gracefully to empty in replay mode, which is the correct behaviour rather than a defect.

Scoring against ``reference.csv`` and the sim-to-real gap report are phase 6.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import yaml

from wimsim.core.clock import Pacer
from wimsim.core.types import SampleBlock, SourceMetadata
from wimsim.source.base import BaseSource
from wimsim.source.real_schema import validate_run

__all__ = ["ReplaySource"]


#: `raw_value_kind` -> the unit the values are in. One entry per `real_schema.RAW_VALUE_KINDS`;
#: a kind not listed there cannot reach this far, because `validate_run` rejects it.
_UNITS = {"counts": "counts", "mv_per_v": "mV/V", "strain": "strain"}


class ReplaySource(BaseSource):
    def __init__(
        self,
        run_dir: Path | str,
        *,
        channel: str | None = None,
        pacing: str = "accelerated",
        speed_multiplier: float | None = None,
        block_seconds: float = 30.0,
        strict: bool = True,
    ) -> None:
        self.run_dir = Path(run_dir)
        report = validate_run(self.run_dir)
        if strict and not report.ok:
            raise ValueError(
                f"{self.run_dir} does not satisfy the real-data schema:\n  - "
                + "\n  - ".join(report.errors)
                + "\nRun `wimsim validate-real-data` for the full report."
            )
        self.report = report

        self.run = yaml.safe_load((self.run_dir / "run.yaml").read_text(encoding="utf-8")) or {}
        self.sample_rate_hz = float(self.run["sample_rate_hz"])
        self.block_size = max(int(round(block_seconds * self.sample_rate_hz)), 1)
        self._pacer = Pacer(None if pacing == "accelerated" else (speed_multiplier or 1.0))

        table = pq.read_table(self.run_dir / "samples.parquet")
        names = set(table.schema.names)
        chans = table.column("channel_id").to_pylist()
        available = sorted(set(chans))
        if channel is None:
            if len(available) != 1:
                raise ValueError(
                    f"{self.run_dir} carries channels {available}; name one with channel=..."
                )
            channel = available[0]
        elif channel not in available:
            raise ValueError(f"channel {channel!r} not in {available}")
        self.channel = channel

        sel = np.array([c == channel for c in chans])
        ts = table.column("ts").to_numpy(zero_copy_only=False).astype(np.int64)[sel]
        raw = table.column("raw_value").to_numpy(zero_copy_only=False).astype(np.float64)[sel]
        temp = (
            table.column("temperature_c").to_numpy(zero_copy_only=False).astype(np.float64)[sel]
            if "temperature_c" in names
            else np.full(ts.size, np.nan)
        )
        order = np.argsort(ts, kind="stable")
        self._ts = ts[order]
        self._temp = temp[order]

        # `adc_bits` and `adc_range` are required only for `raw_value_kind: counts`; a strain or
        # mV/V export is already a physical quantity, so there is nothing to invert. Reading them
        # unconditionally is what kept this class from opening a single one of the project's real
        # recordings -- the schema said optional and its only consumer said required.
        self.kind = str(self.run["raw_value_kind"])
        declared = self.run.get("adc_range")
        self._adc_range = (float(declared[0]), float(declared[1])) if declared is not None else None
        self._bits = int(self.run["adc_bits"]) if self.run.get("adc_bits") is not None else None

        if self.kind == "counts":
            if self._adc_range is None or self._bits is None:
                raise ValueError(
                    f"{self.run_dir}: raw_value_kind 'counts' needs adc_bits and adc_range to "
                    "become a physical quantity, and neither is declared"
                )
            lo, hi = self._adc_range
            lsb = (hi - lo) / ((1 << self._bits) - 1)
            self._counts = raw[order].astype(np.int64)
            self._value = lo + self._counts * lsb
        else:
            self._value = raw[order]
            if self._adc_range is not None and self._bits is not None:
                lo, hi = self._adc_range
                lsb = (hi - lo) / ((1 << self._bits) - 1)
                self._counts = np.clip(
                    np.rint((self._value - lo) / lsb), 0, (1 << self._bits) - 1
                ).astype(np.int64)
            else:
                # There are no counts. Zeros are a placeholder, not a measurement, which is why
                # `metadata.extra['raw_counts']` says so rather than leaving a reader of the
                # database to conclude the channel was stuck at the bottom of its range.
                self._counts = np.zeros(self._value.size, dtype=np.int64)

        if self._adc_range is not None and self._bits is not None:
            self._saturated = (self._counts <= 0) | (self._counts >= (1 << self._bits) - 1)
        else:
            # Saturation cannot be checked without a range. `validate_run` already warns about
            # exactly this; the source has to agree with it rather than assert every sample is in
            # a range nobody declared.
            self._saturated = np.zeros(self._value.size, dtype=bool)
        self._t0_us = int(self._ts[0]) if self._ts.size else 0

    @property
    def metadata(self) -> SourceMetadata:
        cmap = self.run.get("channel_map") or {}
        entry = cmap.get(self.channel, {}) if isinstance(cmap, dict) else {}
        return SourceMetadata(
            mode="replay",
            sample_rate_hz=self.sample_rate_hz,
            channels=(self.channel,),
            station_id=str(self.run.get("station_id", "unknown")),
            sensor_id=str(entry.get("sensor_id", self.channel)),
            unit=_UNITS.get(self.kind, self.kind),
            adc_bits=self._bits,
            adc_range=self._adc_range,
            start_time_us=self._t0_us,
            run_id=self.run_dir.name,
            extra={
                "source": "replay",
                "run_dir": str(self.run_dir),
                "notes": self.run.get("notes", ""),
                "validation_warnings": list(self.report.warnings),
                "raw_counts": (
                    "recovered from adc_range"
                    if self._adc_range is not None
                    else "absent: this recording declares no adc_range, so the counts column is a "
                    "placeholder and carries no information"
                ),
            },
        )

    def stream_blocks(self) -> Iterator[SampleBlock]:
        n = self._ts.size
        for i0 in range(0, n, self.block_size):
            sl = slice(i0, min(i0 + self.block_size, n))
            t_s = (self._ts[sl] - self._t0_us) / 1e6
            self._pacer.wait_until(float(t_s[-1]))
            yield SampleBlock(
                ts_us=self._ts[sl],
                t_s=t_s,
                raw_value=self._value[sl],
                raw_counts=self._counts[sl],
                temperature_c=self._temp[sl],
                saturated=self._saturated[sl],
                # a real recording carries no validity flag; a stuck or missing channel has to be
                # inferred downstream, which is exactly the harder problem replay is here to pose
                valid=np.ones(self._ts[sl].size, dtype=bool),
                channel_id=self.channel,
            )
