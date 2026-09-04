"""Traffic: who crosses the sensor, when, how fast, and how heavy.

The whole population is resolved **up front**, before a single sample is generated. Two reasons,
both about reproducibility rather than convenience:

* pass scheduling must not depend on how the sample stream happens to be blocked; and
* the truth log has to exist as a complete object before generation starts, so the generator can be
  asked "which passes overlap this block" instead of discovering passes as it goes.

Distributions are chosen to be defensible rather than merely convenient:

* **arrivals** -- Poisson (memoryless headways) is the standard free-flow traffic model; a minimum
  headway is then enforced, which is both physically true and necessary for pulses to be separable.
* **axle loads** -- lognormal, parameterised by mean and coefficient of variation. Loads are
  positive and right-skewed; a Gaussian would generate negative axle loads in the tail.
* **speeds** -- *truncated* normal sampled by inverse CDF, not a clipped normal. Clipping piles
  probability mass onto the limits and would quietly create a population of vehicles all doing
  exactly 130 km/h.
* **dynamic load** -- one bounce oscillation per vehicle, shared across its axles (they share a
  body) with a random phase. This is what makes ``applied != static``.
"""

from __future__ import annotations

import uuid

import numpy as np
from scipy import stats

from wimsim.core.config import RunConfig, VehicleClass
from wimsim.core.rng import RngStreams
from wimsim.core.types import VehiclePass
from wimsim.signal.pulses import fwhm_for, pulse_waveform

__all__ = ["PASS_NAMESPACE", "pass_waveform", "schedule_passes"]

#: Fixed namespace so pass ids are stable across machines, processes and releases.
PASS_NAMESPACE = uuid.UUID("6f0a1c7e-2f4b-5a3d-9c11-8a7b6c5d4e3f")

_KMH_TO_MPS = 1.0 / 3.6


def _pass_id(station_id: str, sensor_id: str, t_entry_s: float) -> str:
    """Deterministic id from station, sensor and entry time, quantised to 1 us.

    Mirrors the ``event_id`` rule in the event schema (hash of station + ts_start + sensor) so the
    scoring layer has a stable key on both sides even though the two ids are not equal: the
    detector's ``ts_start`` is a threshold crossing, not the truth's peak time.
    """
    key = f"{station_id}|{sensor_id}|{int(round(t_entry_s * 1_000_000))}"
    return str(uuid.uuid5(PASS_NAMESPACE, key))


def _arrival_times(cfg: RunConfig, rng: np.random.Generator) -> np.ndarray:
    tc = cfg.scenario.traffic
    duration = cfg.scenario.duration_s
    if tc.mode == "fixed_interval":
        interval = 3600.0 / tc.rate_per_hour
        return np.arange(interval, duration, interval)

    mean_gap = 3600.0 / tc.rate_per_hour
    # generate generously, then trim: cheaper and more deterministic than growing in a loop
    n_guess = int(np.ceil(duration / mean_gap * 1.5)) + 32
    gaps = rng.exponential(mean_gap, n_guess)
    times = np.cumsum(gaps)
    while times[-1] < duration:
        extra = rng.exponential(mean_gap, n_guess)
        times = np.concatenate([times, times[-1] + np.cumsum(extra)])
    times = times[times < duration]

    # enforce the minimum headway by pushing late, then drop anything shoved past the end
    if tc.min_headway_s > 0 and times.size:
        for i in range(1, times.size):
            if times[i] - times[i - 1] < tc.min_headway_s:
                times[i] = times[i - 1] + tc.min_headway_s
        times = times[times < duration]
    return times


def _truncated_normal(
    rng: np.random.Generator, mean: float, std: float, lo: float, hi: float
) -> float:
    if std <= 0:
        return float(np.clip(mean, lo, hi))
    a, b = (lo - mean) / std, (hi - mean) / std
    u = rng.uniform()
    p = stats.norm.cdf(a) + u * (stats.norm.cdf(b) - stats.norm.cdf(a))
    return float(mean + std * stats.norm.ppf(np.clip(p, 1e-12, 1 - 1e-12)))


def _lognormal(rng: np.random.Generator, mean: float, cv: float) -> float:
    if cv <= 0:
        return float(mean)
    sigma = np.sqrt(np.log1p(cv**2))
    mu = np.log(mean) - 0.5 * sigma**2
    return float(rng.lognormal(mu, sigma))


def _pick_class(classes: list[VehicleClass], u: float) -> VehicleClass:
    weights = np.array([c.probability for c in classes], dtype=np.float64)
    cdf = np.cumsum(weights / weights.sum())
    return classes[int(np.searchsorted(cdf, u, side="right"))]


def pass_waveform(
    t_s: np.ndarray,
    axle_times: np.ndarray,
    axle_loads: np.ndarray,
    fwhm: float,
    pulse_cfg,
) -> np.ndarray:
    """Superposition of one vehicle's axle pulses, in kg. Multiply by ``k(t)`` for sensor units."""
    out = np.zeros_like(t_s, dtype=np.float64)
    for tau, load in zip(axle_times, axle_loads, strict=True):
        out += load * pulse_waveform(t_s - tau, fwhm, pulse_cfg)
    return out


def _peak_and_area(
    axle_times: np.ndarray, axle_loads: np.ndarray, fwhm: float, pulse_cfg
) -> tuple[float, float, float]:
    """(t_peak, peak_load_kg, area_load_kg_s) of the superposed waveform.

    Evaluated numerically because overlapping axles have no closed-form maximum. Two stages: a
    coarse pass over the whole vehicle for the area and to bracket the maximum, then a local refine
    around that bracket for the peak. The refinement matters -- these are the reference values every
    later phase is scored against, and a coarse grid alone undershoots a Gaussian maximum by
    ``(h/2sigma)^2/2``, which at 100 points per FWHM is a systematic 1e-5 error in the wrong
    direction. Both grids are fixed relative to the pulse width, so the result is reproducible.
    """
    support = pulse_cfg.support_widths * fwhm
    step = fwhm / 100.0
    grid = np.arange(axle_times[0] - support, axle_times[-1] + support + step, step)
    y = pass_waveform(grid, axle_times, axle_loads, fwhm, pulse_cfg)
    area = float(np.trapezoid(y, grid))

    i = int(np.argmax(y))
    lo = grid[max(i - 1, 0)]
    hi = grid[min(i + 1, grid.size - 1)]
    fine = np.linspace(lo, hi, 2001)
    yf = pass_waveform(fine, axle_times, axle_loads, fwhm, pulse_cfg)
    j = int(np.argmax(yf))
    return float(fine[j]), float(yf[j]), area


def schedule_passes(cfg: RunConfig, rngs: RngStreams) -> list[VehiclePass]:
    """Resolve the complete traffic population for a run."""
    sc = cfg.scenario
    tc = sc.traffic
    station = cfg.station

    rng_arr = rngs.get("traffic.arrivals")
    rng_cls = rngs.get("traffic.class")
    rng_speed = rngs.get("traffic.speed")
    rng_load = rngs.get("traffic.load")
    rng_dyn = rngs.get("traffic.dynamic")

    arrivals = _arrival_times(cfg, rng_arr)
    passes: list[VehiclePass] = []

    for index, t0 in enumerate(arrivals.tolist()):
        vc = _pick_class(tc.classes, float(rng_cls.uniform()))
        sp = vc.speed
        speed_mps = (
            _truncated_normal(rng_speed, sp.mean_kmh, sp.std_kmh, sp.min_kmh, sp.max_kmh)
            * _KMH_TO_MPS
        )
        static = np.array([_lognormal(rng_load, spec.mean_kg, spec.cv) for spec in vc.axle_load_kg])

        offsets = np.concatenate([[0.0], np.cumsum(vc.axle_spacing_m)]) / speed_mps
        axle_times = t0 + offsets

        dl = tc.dynamic_load
        if dl.enabled and dl.amplitude > 0:
            freq = max(float(rng_dyn.normal(dl.freq_hz_mean, dl.freq_hz_std)), 0.2)
            phase = float(rng_dyn.uniform(0.0, 2.0 * np.pi))
            applied = static * (1.0 + dl.amplitude * np.sin(2.0 * np.pi * freq * offsets + phase))
            applied = np.maximum(applied, 0.0)
        else:
            # keep the stream aligned so toggling dynamic load does not reshuffle later passes
            rng_dyn.normal(dl.freq_hz_mean, dl.freq_hz_std)
            rng_dyn.uniform(0.0, 2.0 * np.pi)
            applied = static.copy()

        if sc.pulse.width_source == "influence_length":
            # A structural response is a property of the member, not of the tyre, so the per-class
            # contact patch is deliberately ignored here rather than blended in.
            length = station.sensor.influence_length_m
        else:
            length = vc.contact_patch_m or station.sensor.contact_patch_m
        fwhm = fwhm_for(speed_mps, length)
        t_peak, peak_load, area_load = _peak_and_area(axle_times, applied, fwhm, sc.pulse)

        passes.append(
            VehiclePass(
                pass_id=_pass_id(station.station_id, station.sensor_id, float(axle_times[0])),
                index=index,
                vehicle_class=vc.name,
                t_entry_s=float(axle_times[0]),
                t_exit_s=float(axle_times[-1]),
                speed_mps=speed_mps,
                axle_count=vc.axle_count,
                axle_times_s=tuple(axle_times.tolist()),
                axle_static_kg=tuple(static.tolist()),
                axle_applied_kg=tuple(applied.tolist()),
                pulse_fwhm_s=tuple([fwhm] * vc.axle_count),
                true_mass_kg=float(static.sum()),
                applied_mass_kg=float(applied.sum()),
                # Peak and area are recorded in the *load* domain. The generator converts them to
                # sensor units with k at the moment of the pass, because k is not constant.
                t_peak_s=t_peak,
                peak_load_kg=peak_load,
                area_load_kg_s=area_load,
            )
        )
    return passes
