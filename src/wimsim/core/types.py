"""Domain types shared across the whole chain.

Deliberately plain: dataclasses and numpy arrays, no pydantic and no I/O. These types travel from
the source adapter through the edge pipeline into the estimator, which must stay importable on a
Raspberry Pi with nothing but numpy (principle 6).

Two granularities exist on purpose:

* :class:`Sample` -- one scalar reading. This is what ``SourceAdapter.stream()`` yields, because a
  sample-at-a-time interface is what real acquisition hardware presents.
* :class:`SampleBlock` -- a contiguous run of readings as numpy arrays. This is what the generator
  actually produces and what every stage should prefer; iterating 2000 Python objects per second
  of simulated time is not free. ``stream()`` is a thin unpacking of ``stream_blocks()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

__all__ = [
    "US_PER_S",
    "PlantState",
    "Sample",
    "SampleBlock",
    "SourceMetadata",
    "VehiclePass",
    "from_epoch_us",
    "to_epoch_us",
]

#: All timestamps on the wire are integer microseconds since the Unix epoch, UTC. Floats are used
#: only for "seconds since run start", which is a plotting and modelling convenience.
US_PER_S = 1_000_000


def to_epoch_us(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(round(dt.timestamp() * US_PER_S))


def from_epoch_us(us: int) -> datetime:
    return datetime.fromtimestamp(us / US_PER_S, tz=UTC)


@dataclass(frozen=True, slots=True)
class Sample:
    """One reading, as the acquisition layer sees it."""

    ts_us: int
    """Station-clock timestamp, microseconds since epoch. Subject to clock-skew faults."""
    channel_id: str
    raw_value: float
    """Analog value in station units *after* ADC quantisation, i.e. what the device reports."""
    raw_counts: int
    """The underlying integer ADC code. Kept because saturation is only visible here."""
    temperature_c: float | None = None
    """Co-located temperature reading, if the station has one. Not the true sensor temperature:
    it carries its own noise and its own lag."""
    saturated: bool = False
    valid: bool = True
    """False during a channel dropout. Downstream stages must not treat these as measurements."""


@dataclass(frozen=True, slots=True)
class SampleBlock:
    """A contiguous block of readings. Arrays are parallel and all of length ``n``."""

    ts_us: np.ndarray  # int64
    t_s: np.ndarray  # float64, seconds since run start, true (unskewed) time
    raw_value: np.ndarray  # float64
    raw_counts: np.ndarray  # int64
    temperature_c: np.ndarray  # float64
    saturated: np.ndarray  # bool
    valid: np.ndarray  # bool
    channel_id: str = "ch0"

    @property
    def n(self) -> int:
        return int(self.ts_us.shape[0])

    def __iter__(self):
        for i in range(self.n):
            yield Sample(
                ts_us=int(self.ts_us[i]),
                channel_id=self.channel_id,
                raw_value=float(self.raw_value[i]),
                raw_counts=int(self.raw_counts[i]),
                temperature_c=float(self.temperature_c[i]),
                saturated=bool(self.saturated[i]),
                valid=bool(self.valid[i]),
            )


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Everything a downstream stage may know about where samples come from.

    Note what is *absent*: nothing here reveals ground truth. A stage cannot tell a synthetic
    stream from a replayed real one except by reading ``mode``, and no stage is entitled to
    branch on that for anything but labelling.
    """

    mode: str  # "synthetic" | "replay" | "serial"
    sample_rate_hz: float
    channels: tuple[str, ...]
    station_id: str
    sensor_id: str
    unit: str = "mV/V"
    adc_bits: int = 16
    adc_range: tuple[float, float] = (0.0, 1.0)
    start_time_us: int = 0
    run_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VehiclePass:
    """The ground-truth description of one vehicle crossing the sensor.

    Lives in the truth domain. It is produced by the generator and written to the truth log; it
    must never reach an estimator. See ``tests/test_truth_isolation.py``.
    """

    pass_id: str
    index: int
    vehicle_class: str
    t_entry_s: float
    """Time the first axle's pulse peaks, seconds since run start."""
    t_exit_s: float
    """Time the last axle's pulse peaks."""
    speed_mps: float
    axle_count: int
    axle_times_s: tuple[float, ...]
    axle_static_kg: tuple[float, ...]
    """Static load per axle: the quantity a perfect weighbridge would report."""
    axle_applied_kg: tuple[float, ...]
    """Load actually applied at the instant of crossing, including body bounce. The gap between
    this and ``axle_static_kg`` is the irreducible dynamic error of any WiM system."""
    pulse_fwhm_s: tuple[float, ...]
    true_mass_kg: float
    """Sum of static axle loads. The estimation target."""
    applied_mass_kg: float
    t_peak_s: float
    """Time of the maximum of this pass's noise-free load waveform. Not necessarily an axle time:
    on a closely spaced bogie the axle pulses overlap and the maximum falls between them."""
    peak_load_kg: float
    """Maximum of the superposed unit-peak axle pulses, in kg. Equals the heaviest axle only when
    the axles are far enough apart not to overlap."""
    area_load_kg_s: float
    """Integral of the same waveform, kg*s. Proportional to mass / speed, not to mass."""


@dataclass(frozen=True, slots=True)
class PlantState:
    """Sampled ground-truth state of the measurement plant."""

    t_s: np.ndarray
    q_true: np.ndarray
    k_true: np.ndarray
    alpha_true: np.ndarray
    t_sensor_true: np.ndarray
    t_ambient_true: np.ndarray
    clock_offset_s: np.ndarray
    active_faults: list[str]
    """One ';'-joined label string per row; empty string when nothing is active."""
