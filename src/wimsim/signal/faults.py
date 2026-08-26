"""Fault injection.

Every fault is (a) independently toggleable from config and (b) *labelled in the truth log* over
the interval it is active. That second property is what makes drift-detector evaluation possible
at all: false-alarm and missed-detection rates need a reference answer for "was something actually
wrong at time t".

Faults act at two different places in the chain, and the distinction is not cosmetic:

* **Plant faults** change the physics -- ``gain_instability`` scales ``k``, ``sensor_displacement``
  steps both ``k0`` and ``q``. They are applied on the plant grid, *before* the axle pulses are
  scaled, so a pass during the fault genuinely weighs wrong.
* **Acquisition faults** change what the device reports without changing the physics --
  ``channel_dropout`` replaces samples, ``clock_skew`` corrupts timestamps. They are applied on the
  sample grid, after quantisation, because that is where they happen in a real station.

Pipeline faults (connectivity loss, publish delay, malformed schema, heartbeat loss) belong to the
transport and ingest layers and are not applied here; :class:`FaultSet` reports them as
``unapplied`` so a run manifest can say so out loud rather than silently ignoring config.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wimsim.core.clock import ClockModel
from wimsim.core.config import ScenarioConfig
from wimsim.signal.adc import Quantizer

__all__ = ["DropoutSpan", "FaultSet"]


@dataclass(frozen=True, slots=True)
class DropoutSpan:
    label: str
    t_start_s: float
    t_end_s: float
    mode: str
    stuck_value: float | None


def _window(t: np.ndarray, start: float, duration: float | None) -> np.ndarray:
    if duration is None:
        return t >= start
    return (t >= start) & (t < start + duration)


class FaultSet:
    """Compiled view of a scenario's faults, evaluable on any time grid."""

    def __init__(self, scenario: ScenarioConfig) -> None:
        self._faults = list(scenario.signal_faults)
        self.unapplied = [f.label for f in scenario.pipeline_faults]
        #: stable label order; bit i of the active mask corresponds to labels[i]
        self.labels: list[str] = [f.label for f in self._faults]
        if len(self.labels) > 32:
            raise ValueError("more than 32 signal faults in one scenario is not supported")
        self._index = {label: i for i, label in enumerate(self.labels)}

        self.dropouts: list[DropoutSpan] = [
            DropoutSpan(
                label=f.label,
                t_start_s=f.t_start_s,
                t_end_s=f.t_start_s + f.duration_s,
                mode=f.mode,
                stuck_value=f.stuck_value,
            )
            for f in self._faults
            if f.type == "channel_dropout"
        ]

        skews = [f for f in self._faults if f.type == "clock_skew"]
        if len(skews) > 1:
            raise ValueError("at most one clock_skew fault per scenario")
        self._skew = skews[0] if skews else None

    # -- plant-side effects ---------------------------------------------------------------

    def gain_multiplier(self, t_s: np.ndarray) -> np.ndarray:
        """Multiplicative factor applied to ``k``, from amplifier instability and displacement."""
        out = np.ones_like(t_s, dtype=np.float64)
        for f in self._faults:
            if f.type == "gain_instability":
                active = _window(t_s, f.t_start_s, f.duration_s)
                if f.ramp_s > 0.0:
                    frac = np.clip((t_s - f.t_start_s) / f.ramp_s, 0.0, 1.0)
                    factor = 1.0 + (f.factor - 1.0) * frac
                else:
                    factor = np.full_like(t_s, f.factor)
                out = np.where(active, out * factor, out)
            elif f.type == "sensor_displacement":
                out = np.where(t_s >= f.t_s, out * f.k_factor, out)
        return out

    def zero_offset(self, t_s: np.ndarray) -> np.ndarray:
        """Additive step in the zero line contributed by mechanical displacement."""
        out = np.zeros_like(t_s, dtype=np.float64)
        for f in self._faults:
            if f.type == "sensor_displacement":
                out = out + np.where(t_s >= f.t_s, f.q_delta, 0.0)
        return out

    # -- labelling ------------------------------------------------------------------------

    def active_mask(self, t_s: np.ndarray) -> np.ndarray:
        """Bitmask per time point; bit ``i`` set means ``self.labels[i]`` is active."""
        mask = np.zeros(t_s.shape, dtype=np.uint32)
        for f in self._faults:
            bit = np.uint32(1) << np.uint32(self._index[f.label])
            if f.type == "gain_instability":
                active = _window(t_s, f.t_start_s, f.duration_s)
            elif f.type == "sensor_displacement":
                active = t_s >= f.t_s
            elif f.type == "channel_dropout":
                active = _window(t_s, f.t_start_s, f.duration_s)
            elif f.type == "clock_skew":
                active = t_s >= f.t_start_s
            else:  # pragma: no cover - guarded by SIGNAL_FAULT_TYPES
                continue
            mask = np.where(active, mask | bit, mask)
        return mask

    def decode_mask(self, mask: np.ndarray) -> list[str]:
        """Bitmask array -> one ';'-joined label string per element ('' when quiet)."""
        out: list[str] = []
        cache: dict[int, str] = {0: ""}
        for value in mask.tolist():
            if value not in cache:
                cache[value] = ";".join(
                    label for i, label in enumerate(self.labels) if value & (1 << i)
                )
            out.append(cache[value])
        return out

    # -- acquisition-side effects ----------------------------------------------------------

    def clock_model(self, start_time_us: int) -> ClockModel:
        if self._skew is None:
            return ClockModel(start_time_us=start_time_us)
        return ClockModel(
            start_time_us=start_time_us,
            t_start_s=self._skew.t_start_s,
            offset_s=self._skew.offset_s,
            drift_ppm=self._skew.drift_ppm,
        )

    def apply_dropouts(
        self,
        t_s: np.ndarray,
        value: np.ndarray,
        counts: np.ndarray,
        valid: np.ndarray,
        *,
        quantizer: Quantizer,
        last_good: tuple[float, int] | None,
    ) -> tuple[float, int] | None:
        """Overwrite samples inside dropout spans, in place. Returns the new last-good sample.

        ``last_good`` is carried across blocks so a 'stuck' dropout holds the value the channel
        actually had when it failed, even when the failure straddles a block boundary.
        """
        for span in self.dropouts:
            sel = (t_s >= span.t_start_s) & (t_s < span.t_end_s)
            if not sel.any():
                continue
            first = int(np.argmax(sel))
            if span.mode == "stuck":
                if span.stuck_value is not None:
                    hold_c = int(quantizer.to_counts(span.stuck_value))
                elif first > 0:
                    hold_c = int(counts[first - 1])
                elif last_good is not None:
                    hold_c = last_good[1]
                else:
                    hold_c = int(counts[first])
                counts[sel] = hold_c
                value[sel] = float(quantizer.to_value(hold_c))
            elif span.mode == "zero":
                counts[sel] = quantizer.min_count
                value[sel] = float(quantizer.to_value(quantizer.min_count))
            elif span.mode == "saturate_high":
                counts[sel] = quantizer.max_count
                value[sel] = float(quantizer.to_value(quantizer.max_count))
            elif span.mode == "nan":
                value[sel] = np.nan
                counts[sel] = quantizer.min_count
            valid[sel] = False

        healthy = np.flatnonzero(valid)
        if healthy.size:
            i = int(healthy[-1])
            return float(value[i]), int(counts[i])
        return last_good

    def summary(self) -> list[dict]:
        return [f.model_dump(mode="json") for f in self._faults]

    def __len__(self) -> int:
        return len(self._faults)
