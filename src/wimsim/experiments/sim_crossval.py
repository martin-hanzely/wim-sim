"""Cross-validating the simulator: fit its parameters on some recordings, test them on another.

Section V-C concedes that no simulator parameter has ever been cross-validated. Everything in
``docs/sim-to-real.md`` was fitted on the recordings and then reported against the recordings, so
nothing in the project distinguishes "the simulator reproduces this instrument" from "the
simulator was fitted to these eight minutes of it". That is a threat to construct validity and the
manuscript says so.

**Leave one recording out.** Fit the noise, drift and pulse parameters on every recording but one,
synthesise a signal with the fitted values, and compare its statistics against the recording that
was held out. Repeat over all folds. Held-out agreement is the number; in-sample agreement is
carried beside it only so the gap between the two is visible, never as a substitute.

Holding out a whole *recording* is the point. The crossings inside one recording share a vehicle, a
driver, a line across the platform and a minute of thermal state, so a split that mixed them would
leak all of that across the fold boundary -- the same reason ``pooled.py`` holds out recordings
rather than crossings.

**Three definitions decide what this measures, and each is stated rather than assumed.**

*Crossings are excised before any noise or drift statistic.* A sixty-second recording with four
one-second drive-overs in it has 7 % of its samples inside a pulse, and a pulse is a far larger
excursion than the noise being measured. Left in, it dominates the low-frequency slope and the
baseline increment distribution completely -- the drift statistic would be measuring the traffic.
The same mask is applied to the synthetic side, so the two are treated identically.

*The fit is method-of-moments, because that is how the station file was actually produced.* No
optimiser is involved anywhere in this project's sim-to-real work: ``docs/sim-to-real.md`` sets each
parameter to a measured statistic. Cross-validating that procedure means pooling the measured
statistic over the training recordings -- by median, so one anomalous recording cannot set the
parameter -- and asking what it predicts about a recording it never saw.

*There is no pass mark.* A simulator agreeing to within a few per cent on every statistic would
mean the statistics were not discriminating. What is reportable is the size and the direction of
the disagreement, and whether holding a recording out makes it worse.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "STRAIN_TO_MV_PER_V",
    "CrossValFold",
    "FittedParameters",
    "RecordingStats",
    "crossval_markdown",
    "fit_parameters",
    "leave_one_out",
    "measure",
    "quiescent_mask",
    "to_station_units",
]

#: The plant grid the simulator integrates its slow states on. Baseline increments are measured
#: after decimating to it, because that is the rate at which the model's zero line actually moves;
#: differencing at 25 kHz would measure the white noise twice and say nothing about drift.
PLANT_RATE_HZ = 50.0

#: How far either side of a detected crossing is excised, in seconds. The recorded drive-overs
#: have a mean FWHM near 0.77 s, so two seconds clears the pulse and its tails.
_EXCISE_PAD_S = 2.0

#: Length of the rolling-median window the local baseline is built from, seconds. Long
#: against a drive-over, short against the drift.
_BASELINE_WINDOW_S = 6.0

#: A sample is inside a crossing if it departs that baseline by more than this many robust sigmas.
#: The scale is the median absolute *successive difference*, never a standard deviation: a standard
#: deviation grows with the pulse it is being used to find, which is the phase-3 validator bug.
_EXCISE_SIGMA = 8.0

#: The speed the influence length is inferred through, m/s. INFERRED, not measured -- see the
#: header of configs/stations/cintron_platform.yaml. Any influence length this module reports
#: inherits that inference and is labelled as doing so.
_INFERRED_SPEED_MS = 0.78

#: Fewer quiescent samples than this and the recording cannot measure its own noise floor.
#: `gap_report` needs 1 << 13 to resolve its bands; four times that is a minute at 50 Hz.
_MIN_QUIESCENT = 1 << 15


#: Microstrain to mV/V at gauge factor 2.0 on a quarter bridge, times 1e6 strain per microstrain:
#: 1 ue = 5e-4 mV/V, so 1 strain = 500 mV/V. The bridge configuration is ASSUMED, not measured --
#: see the sensor block of configs/stations/cintron_platform.yaml, which calls it "the assumed
#: half of this". Every absolute comparison below carries that assumption; no comparison BETWEEN
#: folds does, because it is one constant applied identically to all of them.
STRAIN_TO_MV_PER_V = 500.0

#: Recording unit -> station unit -> multiplier. An explicit table rather than a passthrough,
#: because the first version of this module had no conversion at all and the error was invisible:
#: feeding a strain-valued white sigma into a mV/V-valued config key and then measuring the
#: result reproduces the input exactly, so the fold reported perfect agreement between two
#: numbers that were not the same quantity.
_UNIT_SCALE: dict[tuple[str, str], float] = {
    ("strain", "mV/V"): STRAIN_TO_MV_PER_V,
    ("mV/V", "strain"): 1.0 / STRAIN_TO_MV_PER_V,
    ("strain", "strain"): 1.0,
    ("mV/V", "mV/V"): 1.0,
}


def to_station_units(
    signal: np.ndarray, *, recording_unit: str, station_unit: str
) -> tuple[np.ndarray, float]:
    """Convert a recording into the units the simulator works in, or refuse.

    Refusing on an unknown pair is the point. A silent passthrough is what made the first run of
    this module report a white-sigma agreement of 0.02 between a strain figure and a mV/V figure
    that happened to share a mantissa.
    """
    key = (recording_unit, station_unit)
    if key not in _UNIT_SCALE:
        raise ValueError(
            f"no conversion from {recording_unit!r} to {station_unit!r} is declared, so these "
            "two signals cannot be compared. Add it to _UNIT_SCALE with the assumption it rests "
            "on written down, or convert before calling."
        )
    scale = _UNIT_SCALE[key]
    return np.asarray(signal, dtype=np.float64) * scale, scale


def _local_baseline(x: np.ndarray, *, fs: float) -> np.ndarray:
    """A slowly varying baseline: block medians at the plant rate, rolling-median smoothed.

    Against a *global* median the zero line is itself an excursion. On these recordings the
    baseline wanders by several sample-noise sigmas across a minute, so a global threshold marks
    most of the recording as a crossing -- which is exactly what the first version did, reporting
    a quiescent fraction of 0.00 on four of eight recordings and then silently falling back to
    measuring the noise on the crossings it had just tried to remove.

    The rolling window is long against a drive-over and short against the drift: a one-second
    pulse occupies a sixth of it and cannot move a median.
    """
    coarse = _decimate(x, fs=fs, to_hz=PLANT_RATE_HZ)
    if coarse.size < 3:
        return np.full(x.size, float(np.median(x)))
    window = max(int(round(_BASELINE_WINDOW_S * PLANT_RATE_HZ)) | 1, 3)
    if coarse.size <= window:
        return np.full(x.size, float(np.median(coarse)))
    # Sliding median over the coarse series, edges held at the nearest full window.
    strided = np.lib.stride_tricks.sliding_window_view(coarse, window)
    smooth = np.median(strided, axis=1)
    half = window // 2
    padded = np.concatenate(
        [np.full(half, smooth[0]), smooth, np.full(coarse.size - smooth.size - half, smooth[-1])]
    )
    grid = (np.arange(coarse.size) + 0.5) * (fs / PLANT_RATE_HZ)
    return np.interp(np.arange(x.size), grid, padded)


def quiescent_mask(signal: np.ndarray, *, fs: float) -> np.ndarray:
    """True where the signal is *not* inside a vehicle crossing.

    Measured against a local baseline, not a global median -- see :func:`_local_baseline`.
    Returns an all-true mask when nothing is detected, which is the right answer for a minute of
    empty road rather than an error.
    """
    x = np.asarray(signal, dtype=np.float64)
    mask = np.ones(x.size, dtype=bool)
    if x.size < 64:
        return mask

    step = max(x.size // 200_000, 1)
    sigma = float(np.median(np.abs(np.diff(x[::step])))) * 1.4826 / math.sqrt(2.0)
    if not (sigma > 0.0) or not np.isfinite(sigma):
        return mask

    inside = np.abs(x - _local_baseline(x, fs=fs)) > _EXCISE_SIGMA * sigma
    if not inside.any():
        return mask

    # Grow each detection by the pad. A boxcar over the indicator is enough and is O(n).
    pad = max(int(round(_EXCISE_PAD_S * fs)), 1)
    cumulative = np.concatenate(([0], np.cumsum(inside.astype(np.int64))))
    lo = np.maximum(np.arange(x.size) - pad, 0)
    hi = np.minimum(np.arange(x.size) + pad + 1, x.size)
    grown = (cumulative[hi] - cumulative[lo]) > 0
    return ~grown


def _decimate(signal: np.ndarray, *, fs: float, to_hz: float = PLANT_RATE_HZ) -> np.ndarray:
    """Block means down to ``to_hz``. Means rather than picks, so white noise averages down."""
    factor = max(int(round(fs / to_hz)), 1)
    usable = (signal.size // factor) * factor
    if usable < factor:
        return np.asarray([], dtype=np.float64)
    return signal[:usable].reshape(-1, factor).mean(axis=1)


@dataclass(frozen=True, slots=True)
class RecordingStats:
    """The signal statistics of one recording, or of one synthetic trace."""

    name: str
    n_samples: int
    duration_s: float
    sample_rate_hz: float
    quiescent_fraction: float
    """Share of samples left after the crossings were excised. A recording with little of itself
    left is a weak measurement of its own noise, and the number says so."""
    white_sigma: float
    """Broadband floor, in the recording's own units, measured above 300 Hz and away from the
    mains harmonics."""
    mains_amplitude: float
    baseline: float
    drift_slope: float
    """log-log PSD slope below 5 Hz. 0 is white, -1 flicker, -2 Brownian."""
    decades_resolved: float
    increment_sd: float
    """sd of successive differences of the quiescent signal decimated to the plant rate."""
    increment_robust_sd: float
    """The same spread from the median absolute deviation. Carried beside the sd and used for
    the fit, because the increments are heavily tailed: on three of the eight recordings the sd
    is five times the robust scale, so an sd-based fit would set the simulator's random walk from
    a handful of samples."""
    increment_white_part: float
    """How much of that spread is the white noise averaging down rather than the zero line
    moving. Subtracted in quadrature before the random-walk parameter is fitted; without it the
    fit is mostly a restatement of the white sigma."""
    increment_kurtosis: float
    """Excess kurtosis of the same increments. 0 is Gaussian, which is what the model assumes."""
    fwhm_s: float
    best_shape: str
    shape_residual: float
    """Normalised RMS residual of the best-fitting shipped pulse shape. NaN when no crossing was
    found, which is reported rather than imputed."""

    def to_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.__slots__}


def measure(signal: np.ndarray, *, fs: float, name: str) -> RecordingStats:
    """Every statistic this module compares, from one trace.

    Noise and drift come from the quiescent samples; the pulse shape comes from the crossing that
    was excised to produce them. A statistic that cannot be measured is NaN and an empty string,
    never a zero: a recording with no crossing in it has no event shape, and writing 0.0 s of FWHM
    into that cell would be a measurement of nothing.
    """
    from wimsim.experiments.gap_report import (
        compare_pulse_shape,
        estimate_drift_rate,
        find_pulse_window,
        fit_noise_parameters,
    )

    x = np.asarray(signal, dtype=np.float64)
    mask = quiescent_mask(x, fs=fs)
    quiet = x[mask]
    if quiet.size < _MIN_QUIESCENT:
        raise ValueError(
            f"{name}: only {quiet.size} of {x.size} samples ({mask.mean():.1%}) are outside a "
            f"crossing, which is too little to measure a noise spectrum on. The first version of "
            "this module fell back to the full signal here, which measured the noise on the "
            "crossings it had just excised and said nothing about it."
        )

    fit = fit_noise_parameters(quiet, fs=fs)
    drift = estimate_drift_rate(quiet, fs=fs)

    increments = np.diff(_decimate(quiet, fs=fs))
    if increments.size > 3:
        centred = increments - increments.mean()
        sd = float(centred.std(ddof=1))
        robust = float(1.4826 * np.median(np.abs(increments - np.median(increments))))
        kurtosis = float(np.mean(centred**4) / sd**4 - 3.0) if sd > 0 else float("nan")
    else:  # pragma: no cover - defensive
        sd = robust = kurtosis = float("nan")
    # White noise decimated by F averages down by sqrt(F), and differencing two such means
    # multiplies by sqrt(2). That part of the increment spread is not the zero line moving.
    white_part = fit.white_sigma * math.sqrt(2.0 * PLANT_RATE_HZ / fs)

    fwhm, shape, residual = float("nan"), "", float("nan")
    window = find_pulse_window(x, fs=fs)
    if window is not None:
        try:
            pulse = compare_pulse_shape(window, dt_s=1.0 / fs)
        except ValueError:
            pass
        else:
            fwhm = pulse.fwhm_s
            shape = pulse.best_shape
            residual = pulse.residuals[pulse.best_shape]

    return RecordingStats(
        name=name,
        n_samples=int(x.size),
        duration_s=float(x.size / fs),
        sample_rate_hz=float(fs),
        quiescent_fraction=float(mask.mean()),
        white_sigma=fit.white_sigma,
        mains_amplitude=fit.mains_amplitude,
        baseline=fit.baseline,
        drift_slope=drift.slope,
        decades_resolved=drift.decades_resolved,
        increment_sd=sd,
        increment_robust_sd=robust,
        increment_white_part=white_part,
        increment_kurtosis=kurtosis,
        fwhm_s=fwhm,
        best_shape=shape,
        shape_residual=residual,
    )


@dataclass(frozen=True, slots=True)
class FittedParameters:
    """Simulator parameters pooled over a set of recordings, by median."""

    n_train: int
    sources: tuple[str, ...]
    white_sigma: float
    mains_amplitude: float
    baseline: float
    random_walk_sigma_per_sqrt_s: float
    influence_length_m: float
    pulse_shape: str

    def as_overrides(self) -> list[str]:
        """``--set`` lines, so a fit is usable without anybody retyping a number out of a report."""
        return [
            f"scenario.noise.white_sigma={self.white_sigma:.4g}",
            "scenario.noise.mains.enabled=true",
            f"scenario.noise.mains.amplitude={self.mains_amplitude:.4g}",
            f"scenario.zero_drift.q0={self.baseline:.4g}",
            f"scenario.zero_drift.random_walk_sigma_per_sqrt_s="
            f"{self.random_walk_sigma_per_sqrt_s:.4g}",
        ]

    def to_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.__slots__}


def _median(values: Sequence[float]) -> float:
    finite = [v for v in values if v == v]
    return float(np.median(finite)) if finite else float("nan")


def fit_parameters(stats: Sequence[RecordingStats]) -> FittedParameters:
    """Pool measured statistics into simulator parameters, by median.

    Median rather than mean throughout, because the corpus is eight recordings and one of them
    being anomalous must not set the parameter for the rest. The pulse shape is pooled by majority
    for the same reason, and a tie resolves to the alphabetically first name so the fit is
    deterministic.

    The random walk is fitted from the ROBUST increment spread with the white-noise contribution
    subtracted in quadrature. Both corrections are load-bearing. Without the quadrature step the
    fitted walk is mostly a restatement of the white sigma -- on this corpus the white part is
    1.45e-5 of a total 1.9e-5, three quarters of it. Without the robust scale, three of the eight
    recordings fit a walk five times too large, because their increment sd is set by a handful of
    samples: their excess kurtosis is +800 to +1700 against the Gaussian 0 the model assumes.
    """
    if not stats:
        raise ValueError("no recordings to fit on")

    # The drift part of the increment spread, per recording, before pooling: subtracting the
    # white part after pooling would mix two quantities that differ between recordings.
    drift_increments = [
        math.sqrt(max(s.increment_robust_sd**2 - s.increment_white_part**2, 0.0))
        for s in stats
        if s.increment_robust_sd == s.increment_robust_sd
    ]
    increment_sd = _median(drift_increments) if drift_increments else float("nan")
    fwhm = _median([s.fwhm_s for s in stats])
    shapes = [s.best_shape for s in stats if s.best_shape]
    shape = min(sorted(set(shapes)), key=lambda n: (-shapes.count(n), n)) if shapes else ""

    return FittedParameters(
        n_train=len(stats),
        sources=tuple(s.name for s in stats),
        white_sigma=_median([s.white_sigma for s in stats]),
        mains_amplitude=_median([s.mains_amplitude for s in stats]),
        baseline=_median([s.baseline for s in stats]),
        # An increment over 1/50 s becomes a per-root-second random-walk scale.
        random_walk_sigma_per_sqrt_s=increment_sd * math.sqrt(PLANT_RATE_HZ),
        # INFERRED: the speed this multiplies by is not measured. See _INFERRED_SPEED_MS.
        influence_length_m=fwhm * _INFERRED_SPEED_MS,
        pulse_shape=shape,
    )


def _log2_ratio(predicted: float, observed: float) -> float:
    """``log2(predicted / observed)``: 0 is agreement, +-1 is a factor of two either way.

    Symmetric in the direction of the error, which a plain ratio is not -- 0.5x and 2x are the
    same size of disagreement and a table of ratios makes the first look smaller.
    """
    if not (predicted > 0 and observed > 0) or not np.isfinite(predicted * observed):
        return float("nan")
    return float(math.log2(predicted / observed))


#: The statistics compared, in the order the report prints them.
_AGREEMENT_KEYS = (
    "white_sigma",
    "mains_amplitude",
    "increment_sd",
    "drift_slope_diff",
    "increment_kurtosis_diff",
    "fwhm_s",
)


@dataclass(frozen=True, slots=True)
class CrossValFold:
    """One held-out recording, against a simulator fitted without it."""

    held_out: str
    fitted: FittedParameters
    observed: RecordingStats
    synthetic: RecordingStats | None
    """Statistics of a synthetic trace generated with the held-out fit's parameters, or None
    when that trace could not be measured -- which is a row saying so, not a dropped fold."""
    in_sample: RecordingStats | None
    """The same, with the held-out recording's own parameters. The ceiling, for contrast only."""
    error: str = ""

    def agreement(self) -> dict[str, float]:
        """``log2(synthetic / real)`` per statistic. Held out, which is the number that counts."""
        if self.synthetic is None:
            return dict.fromkeys(_AGREEMENT_KEYS, float("nan"))
        o, s = self.observed, self.synthetic
        return {
            "white_sigma": _log2_ratio(s.white_sigma, o.white_sigma),
            "mains_amplitude": _log2_ratio(s.mains_amplitude, o.mains_amplitude),
            "increment_sd": _log2_ratio(s.increment_robust_sd, o.increment_robust_sd),
            "drift_slope_diff": s.drift_slope - o.drift_slope,
            "increment_kurtosis_diff": s.increment_kurtosis - o.increment_kurtosis,
            "fwhm_s": _log2_ratio(self.fitted.influence_length_m, o.fwhm_s * _INFERRED_SPEED_MS),
        }

    def in_sample_agreement(self) -> dict[str, float]:
        if self.in_sample is None:
            return dict.fromkeys(_AGREEMENT_KEYS, float("nan"))
        o, s = self.observed, self.in_sample
        return {
            "white_sigma": _log2_ratio(s.white_sigma, o.white_sigma),
            "mains_amplitude": _log2_ratio(s.mains_amplitude, o.mains_amplitude),
            "increment_sd": _log2_ratio(s.increment_robust_sd, o.increment_robust_sd),
            "drift_slope_diff": s.drift_slope - o.drift_slope,
            "increment_kurtosis_diff": s.increment_kurtosis - o.increment_kurtosis,
            "fwhm_s": 0.0,
        }


def _read_recording(
    run_dir: Path, channel: str | None, *, station_unit: str
) -> tuple[np.ndarray, float, float]:
    """The recording, converted into the simulator's units. Refuses an undeclared unit pair."""
    from wimsim.source import ReplaySource

    replay = ReplaySource(run_dir, channel=channel)
    raw = np.concatenate([b.raw_value for b in replay.stream_blocks()])
    meta = replay.metadata
    signal, scale = to_station_units(raw, recording_unit=str(meta.unit), station_unit=station_unit)
    return signal, float(meta.sample_rate_hz), scale


def _synthesise(
    params: FittedParameters,
    *,
    fs: float,
    duration_s: float,
    scenario: str,
    station: str | None,
    seed: int,
) -> np.ndarray:
    """A synthetic trace carrying the fitted parameters, on the recording's own sample grid.

    The grid matters: ``noise.white_sigma`` is a *per-sample* quantity, so its implied spectral
    density depends on the rate. Comparing PSDs computed on two different grids would show
    differences that are an artefact of the grids.
    """
    from wimsim.core.config import load_run_config
    from wimsim.source import SyntheticSource

    cfg = load_run_config(
        scenario,
        station,
        overrides=[
            f"station.sample_rate_hz={fs}",
            f"scenario.duration_s={duration_s:.6f}",
            f"scenario.block_seconds={min(duration_s, 10.0):.6f}",
            "scenario.output.samples=full",
            *params.as_overrides(),
        ],
        seed=seed,
    )
    return np.concatenate([b.raw_value for b in SyntheticSource(cfg).stream_blocks()])


def _trace(
    params: FittedParameters,
    label: str,
    observed: RecordingStats,
    *,
    scenario: str,
    station: str | None,
    seed: int,
) -> tuple[RecordingStats | None, str]:
    """A synthetic trace carrying ``params``, measured on the held-out recording's own grid.

    A trace the statistics cannot be measured on is itself a result -- it means the fitted
    parameters produce a signal unlike anything the measurement was designed for. Returning a
    reason beats losing the other seven folds to one exception.
    """
    try:
        return (
            measure(
                _synthesise(
                    params,
                    fs=observed.sample_rate_hz,
                    duration_s=observed.duration_s,
                    scenario=scenario,
                    station=station,
                    seed=seed,
                ),
                fs=observed.sample_rate_hz,
                name=f"{label}/{observed.name}",
            ),
            "",
        )
    except ValueError as exc:
        return None, str(exc)


def leave_one_out(
    run_dirs: Sequence[Path | str],
    *,
    channel: str | None = None,
    scenario: str = "S1_nominal",
    station: str | None = "cintron_platform",
    seed: int = 20261101,
    with_in_sample: bool = True,
) -> list[CrossValFold]:
    """One fold per recording: fit on the others, synthesise, compare against the held-out one."""
    paths = [Path(p) for p in run_dirs]
    if len(paths) < 3:
        raise ValueError(
            f"leave-one-out over {len(paths)} recording(s) is not a cross-validation: the "
            "training set would be one or two recordings and the pooled median meaningless"
        )

    from wimsim.core.config import load_run_config

    station_unit = str(load_run_config(scenario, station).station.adc.unit)

    measured: list[RecordingStats] = []
    for path in paths:
        signal, fs, _scale = _read_recording(path, channel, station_unit=station_unit)
        measured.append(measure(signal, fs=fs, name=path.name))

    folds: list[CrossValFold] = []
    for index, observed in enumerate(measured):
        training = [s for i, s in enumerate(measured) if i != index]
        fitted = fit_parameters(training)
        synthetic, error = _trace(
            fitted, "sim", observed, scenario=scenario, station=station, seed=seed + index
        )
        in_sample = None
        if with_in_sample:
            in_sample = _trace(
                fit_parameters([observed]),
                "sim-in-sample",
                observed,
                scenario=scenario,
                station=station,
                seed=seed + index,
            )[0]
        folds.append(
            CrossValFold(
                held_out=observed.name,
                fitted=fitted,
                observed=observed,
                synthetic=synthetic,
                in_sample=in_sample,
                error=error,
            )
        )
    return folds


def _fmt(value: float, spec: str = "{:.3g}") -> str:
    return "--" if value != value else spec.format(value)


def crossval_markdown(folds: Sequence[CrossValFold], *, git_commit: str = "unknown") -> str:
    """The held-out table, the in-sample contrast, and what the disagreement means."""
    if not folds:
        raise ValueError("no folds to report")

    first = folds[0]
    lines = [
        "# Simulator cross-validation: leave one recording out",
        "",
        f"Commit `{git_commit}`. {len(folds)} folds over {len(folds)} recordings, "
        f"{first.fitted.n_train} training recordings per fold, "
        f"{first.observed.sample_rate_hz / 1000:.0f} kHz, "
        f"{first.observed.duration_s:.0f} s each.",
        "",
        "Section V-C concedes that no simulator parameter has ever been cross-validated. This is "
        "that test: fit the noise, drift and pulse parameters on every recording but one, "
        "synthesise a trace with the fitted values on the held-out recording's own sample grid, "
        "and compare their statistics. **The held-out columns are the result.** The in-sample "
        "columns are the same comparison with the recording's own fit, carried only so the gap "
        "between the two is visible.",
        "",
        "Crossings are excised from both traces before any noise or drift statistic, by the same "
        "mask, because a one-second drive-over is a far larger excursion than the noise being "
        "measured and would dominate the low-frequency slope entirely. `quiescent` is the share "
        "of each recording left after that.",
        "",
        "Agreement is `log2(synthetic / real)`: 0 is exact, +1 is the simulator twice the "
        "recording, -1 is half. Symmetric in direction, which a plain ratio is not.",
        "",
        "## Measured on each recording",
        "",
        "| recording | quiescent | white sigma | 50 Hz amp | drift slope | decades | "
        "increment sd | robust sd | white part | kurtosis | FWHM s | best shape | resid |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for fold in folds:
        o = fold.observed
        lines.append(
            f"| {o.name} | {o.quiescent_fraction:.2f} | {_fmt(o.white_sigma)} | "
            f"{_fmt(o.mains_amplitude)} | {o.drift_slope:+.2f} | {o.decades_resolved:.1f} | "
            f"{_fmt(o.increment_sd)} | {_fmt(o.increment_robust_sd)} | "
            f"{_fmt(o.increment_white_part)} | {_fmt(o.increment_kurtosis, '{:+.1f}')} | "
            f"{_fmt(o.fwhm_s, '{:.3f}')} | {o.best_shape or '--'} | "
            f"{_fmt(o.shape_residual, '{:.3f}')} |"
        )

    lines += [
        "",
        "## Held-out agreement, per fold",
        "",
        "| held out | white sigma | 50 Hz amp | increment sd | drift slope (diff) | "
        "kurtosis (diff) | influence length |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fold in folds:
        if fold.synthetic is None:
            lines.append(
                f"| {fold.held_out} | FAILED | FAILED | FAILED | FAILED | FAILED | FAILED |"
            )
            continue
        a = fold.agreement()
        lines.append(
            f"| {fold.held_out} | {_fmt(a['white_sigma'], '{:+.2f}')} | "
            f"{_fmt(a['mains_amplitude'], '{:+.2f}')} | "
            f"{_fmt(a['increment_sd'], '{:+.2f}')} | "
            f"{_fmt(a['drift_slope_diff'], '{:+.2f}')} | "
            f"{_fmt(a['increment_kurtosis_diff'], '{:+.0f}')} | "
            f"{_fmt(a['fwhm_s'], '{:+.2f}')} |"
        )
    failures = [f for f in folds if f.synthetic is None]
    if failures:
        lines += ["", "Folds that could not be measured, with the reason:", ""]
        lines += [f"- **{f.held_out}**: {f.error}" for f in failures]

    keys = _AGREEMENT_KEYS
    lines += [
        "",
        "## Held out against in sample",
        "",
        "Median absolute disagreement across folds. If the two columns are close, the fit is not "
        "memorising the recording it was fitted on; if held-out is much worse, it is.",
        "",
        "| statistic | held out | in sample |",
        "| --- | ---: | ---: |",
    ]
    for key in keys:
        held = _median([abs(f.agreement()[key]) for f in folds])
        own = _median([abs(f.in_sample_agreement().get(key, float("nan"))) for f in folds])
        lines.append(f"| {key} | {_fmt(held, '{:.2f}')} | {_fmt(own, '{:.2f}')} |")

    lines += [
        "",
        "There is no pass mark here. A simulator agreeing to within a few per cent on every "
        "statistic would mean the statistics were not discriminating. What is reportable is the "
        "size and direction of the disagreement, and whether holding a recording out makes it "
        "worse than fitting on it.",
        "",
        "The influence length inherits an inference rather than a measurement: it is the measured "
        "FWHM times a crossing speed of "
        f"{_INFERRED_SPEED_MS} m/s that was never measured and is not re-measurable. See the "
        "header of `configs/stations/cintron_platform.yaml`. Its fold-to-fold agreement is "
        "therefore a statement about FWHM reproducibility and not about length in metres.",
        "",
    ]
    return "\n".join(lines)
