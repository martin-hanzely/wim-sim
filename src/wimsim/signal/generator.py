"""The generative model, assembled.

    x(t)     = q(t) + k(t) * sum_j L_j * phi(t - tau_j; w_j) + n(t)
    x_adc(t) = quantize(x(t), adc_bits, adc_range)

Two grids are in play, and keeping them straight is what makes long runs tractable:

* the **plant grid** (``plant_rate_hz``, default 50 Hz) carries ``q``, ``k``, ``alpha``, the three
  temperatures and the 1/f noise. All of these are band-limited well below it.
* the **sample grid** (``sample_rate_hz``) carries the axle pulses, white noise, mains hum and the
  ADC. Plant quantities are linearly interpolated onto it.

Fault effects are *not* interpolated: they are evaluated directly on the sample grid, so a step
fault is a step rather than a ramp one plant interval wide.

Each block comes back as a :class:`GeneratedBlock` with two clearly separated halves:
``.samples``, which is everything a downstream stage is entitled to see, and ``.truth``, which is
everything it is not. ``SyntheticSource`` yields the first and drops the second on the floor; only
the truth writer touches ``.truth``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from wimsim.core.config import RunConfig
from wimsim.core.rng import RngStreams, streams
from wimsim.core.types import SampleBlock, VehiclePass, to_epoch_us
from wimsim.signal.adc import Quantizer
from wimsim.signal.faults import FaultSet
from wimsim.signal.noise import MainsInterference, WhiteNoise
from wimsim.signal.plant import PlantModel
from wimsim.signal.pulses import pulse_waveform
from wimsim.signal.vehicles import schedule_passes

__all__ = ["GeneratedBlock", "SignalGenerator", "TruthBlock"]


@dataclass(frozen=True, slots=True)
class TruthBlock:
    """Ground truth over one block, on the sample grid. Never reaches an estimator."""

    t_s: np.ndarray
    q_true: np.ndarray
    k_true: np.ndarray
    alpha_true: np.ndarray
    t_sensor_true: np.ndarray
    t_ambient_true: np.ndarray
    clock_offset_s: np.ndarray
    fault_mask: np.ndarray
    load_kg: np.ndarray
    """The noise-free applied load waveform, kg. What a perfect sensor would see."""
    x_clean: np.ndarray
    """The analog signal before noise and before quantisation."""


@dataclass(frozen=True, slots=True)
class GeneratedBlock:
    samples: SampleBlock
    truth: TruthBlock
    index: int


class SignalGenerator:
    """Deterministic block-wise generator for one run.

    A generator instance is single-use: :meth:`blocks` walks the run once, because the plant
    carries state. Call :meth:`reset`, or build a new instance, to walk it again.
    """

    def __init__(self, cfg: RunConfig) -> None:
        self.cfg = cfg
        self.reset()

    # -- lifecycle -----------------------------------------------------------------------

    def reset(self) -> None:
        cfg = self.cfg
        self.rngs: RngStreams = streams(cfg.scenario.seed)
        self.faults = FaultSet(cfg.scenario)
        self.plant = PlantModel(cfg, self.rngs, self.faults)
        self.passes: list[VehiclePass] = schedule_passes(cfg, self.rngs)
        self.quantizer = Quantizer(cfg.station.adc)
        self.white = WhiteNoise(cfg.scenario.noise.white_sigma, self.rngs)
        self.mains = MainsInterference(cfg.scenario.noise, self.rngs)
        self.start_time_us = to_epoch_us(cfg.scenario.start_time)
        self.clock = self.faults.clock_model(self.start_time_us)

        self._fs = cfg.station.sample_rate_hz
        self._n_total = cfg.sample_count
        self._plant_ratio = cfg.plant_ratio
        self._block = cfg.block_size
        self._last_good: tuple[float, int] | None = None
        self._plant_tail: dict[str, float] | None = None
        self._consumed = False

        # pass support windows, for "which passes touch this block"
        support = cfg.scenario.pulse.support_widths
        if self.passes:
            self._win_start = np.array(
                [p.t_entry_s - support * p.pulse_fwhm_s[0] for p in self.passes]
            )
            self._win_end = np.array(
                [p.t_exit_s + support * p.pulse_fwhm_s[-1] for p in self.passes]
            )
        else:
            self._win_start = np.empty(0)
            self._win_end = np.empty(0)

    # -- plant grid ----------------------------------------------------------------------

    def _plant_for(self, i0: int, n: int):
        """Plant-grid arrays spanning the sample range ``[i0, i0+n)``, inclusive of both ends."""
        r = self._plant_ratio
        p_lo = i0 // r
        p_hi = (i0 + n - 1) // r + 1

        if self._plant_tail is None:
            grid = np.arange(p_lo, p_hi + 1, dtype=np.float64) / self.cfg.scenario.plant_rate_hz
            pb = self.plant.advance(grid)
            arrays = {
                "t": pb.t_s,
                "q": pb.q,
                "k": pb.k,
                "alpha": pb.alpha,
                "ts": pb.t_sensor_c,
                "ta": pb.t_ambient_c,
                "tp": pb.t_probe_c,
                "pink": pb.pink,
            }
        else:
            grid = np.arange(p_lo + 1, p_hi + 1, dtype=np.float64) / self.cfg.scenario.plant_rate_hz
            pb = self.plant.advance(grid)
            tail = self._plant_tail
            arrays = {
                "t": np.concatenate([[tail["t"]], pb.t_s]),
                "q": np.concatenate([[tail["q"]], pb.q]),
                "k": np.concatenate([[tail["k"]], pb.k]),
                "alpha": np.concatenate([[tail["alpha"]], pb.alpha]),
                "ts": np.concatenate([[tail["ts"]], pb.t_sensor_c]),
                "ta": np.concatenate([[tail["ta"]], pb.t_ambient_c]),
                "tp": np.concatenate([[tail["tp"]], pb.t_probe_c]),
                "pink": np.concatenate([[tail["pink"]], pb.pink]),
            }
        self._plant_tail = {key: float(arr[-1]) for key, arr in arrays.items()}
        return arrays

    # -- pulses --------------------------------------------------------------------------

    def _load_waveform(self, t_s: np.ndarray) -> np.ndarray:
        """Superposed applied load over the block, kg."""
        out = np.zeros_like(t_s)
        if not self.passes:
            return out
        t0, t1 = float(t_s[0]), float(t_s[-1])
        touching = np.flatnonzero((self._win_end >= t0) & (self._win_start <= t1))
        pulse_cfg = self.cfg.scenario.pulse
        for idx in touching.tolist():
            p = self.passes[idx]
            for tau, load, fwhm in zip(
                p.axle_times_s, p.axle_applied_kg, p.pulse_fwhm_s, strict=True
            ):
                out += load * pulse_waveform(t_s - tau, fwhm, pulse_cfg)
        return out

    # -- iteration -----------------------------------------------------------------------

    def blocks(self) -> Iterator[GeneratedBlock]:
        if self._consumed:
            raise RuntimeError(
                "SignalGenerator.blocks() is single-use because the plant carries state; "
                "call reset() or construct a new generator"
            )
        self._consumed = True

        channel = self.cfg.station.sensor_id
        for bi, i0 in enumerate(range(0, self._n_total, self._block)):
            n = min(self._block, self._n_total - i0)
            t_s = (np.arange(i0, i0 + n, dtype=np.float64)) / self._fs

            pg = self._plant_for(i0, n)
            q_base = np.interp(t_s, pg["t"], pg["q"])
            k_base = np.interp(t_s, pg["t"], pg["k"])
            alpha = np.interp(t_s, pg["t"], pg["alpha"])
            t_sensor = np.interp(t_s, pg["t"], pg["ts"])
            t_ambient = np.interp(t_s, pg["t"], pg["ta"])
            t_probe = np.interp(t_s, pg["t"], pg["tp"])
            pink = np.interp(t_s, pg["t"], pg["pink"])

            q, k = self.plant.effective(t_s, q_base, k_base)
            load = self._load_waveform(t_s)

            x_clean = q + k * load
            x = x_clean + pink + self.white.advance(n) + self.mains.evaluate(t_s)

            counts, value, saturated = self.quantizer.quantize(x)
            valid = np.ones(n, dtype=bool)
            self._last_good = self.faults.apply_dropouts(
                t_s, value, counts, valid, quantizer=self.quantizer, last_good=self._last_good
            )

            samples = SampleBlock(
                ts_us=self.clock.to_epoch_us(t_s),
                t_s=t_s,
                raw_value=value,
                raw_counts=counts,
                temperature_c=t_probe,
                saturated=saturated,
                valid=valid,
                channel_id=channel,
            )
            truth = TruthBlock(
                t_s=t_s,
                q_true=q,
                k_true=k,
                alpha_true=alpha,
                t_sensor_true=t_sensor,
                t_ambient_true=t_ambient,
                clock_offset_s=np.asarray(self.clock.offset_at(t_s), dtype=np.float64),
                fault_mask=self.faults.active_mask(t_s),
                load_kg=load,
                x_clean=x_clean,
            )
            yield GeneratedBlock(samples=samples, truth=truth, index=bi)
