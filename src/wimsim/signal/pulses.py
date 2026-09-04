"""Axle pulse shapes phi(t - tau; w).

**Normalisation is a modelling decision, not a detail.** Every shape here is scaled to *unit
peak*. The physical argument: a strip sensor under a rolling tyre sees a force that is
approximately the axle load held constant for as long as the contact patch covers the sensor.
Peak force therefore tracks load and is independent of speed, while the pulse *duration* is
``contact_patch / speed`` and the pulse *area* is ``load * contact_patch / speed`` -- proportional
to load only after speed compensation.

That asymmetry is deliberately preserved because it is the experimental question the buildspec
refuses to pre-decide: peak is the speed-invariant feature but sees the full noise bandwidth,
area averages the noise down but needs a speed estimate. Which wins is measured in phase 2, not
argued here.

Three shapes, in increasing order of realism:

``gaussian``
    The idealisation. Symmetric, no tail. Use for sanity baselines.
``emg``
    Exponentially modified Gaussian: a Gaussian convolved with a one-sided exponential, giving the
    trailing tail that real pavement/pad sensors show as the structure relaxes behind the axle.
``ringing``
    Gaussian plus a damped sinusoid triggered at the impact instant, representing the structural
    mode the axle excites. This is the shape that makes naive peak-picking hard.
``influence_line``
    A clipped parabola. **This is a different instrument, not a different tyre.** The three shapes
    above model a sensor that measures contact force directly, so their width comes from the tyre
    footprint and is milliseconds wide. This one models a strain gauge on a structural member, whose
    response is the member's influence line: the width comes from the *influence length* of the
    structure -- metres, not centimetres -- and the two axles of a car may not be resolved at all.

    The parabola was chosen by fitting six real crossings, not by eye. Normalised RMS residuals:
    parabola 5.2 %, raised cosine 6.9 %, Gaussian 8.7 %, textbook triangular influence line 10.2 %.
    The remaining 5 % is real structure -- two overlapping axles and a member that is not an ideal
    simply-supported beam -- so this is a defensible primitive, not a claim of exactness.
"""

from __future__ import annotations

import numpy as np
from scipy import special

from wimsim.core.config import PulseConfig

__all__ = ["FWHM_TO_SIGMA", "fwhm_for", "pulse_area_factor", "pulse_waveform"]

#: FWHM = 2*sqrt(2*ln 2) * sigma
FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))

_peak_cache: dict[tuple, float] = {}


def fwhm_for(speed_mps: float, contact_patch_m: float) -> float:
    """Pulse width from vehicle kinematics. Speed variation is therefore a controllable factor."""
    if speed_mps <= 0:
        raise ValueError("speed must be positive")
    return contact_patch_m / speed_mps


def _gaussian(t: np.ndarray, sigma: float) -> np.ndarray:
    return np.exp(-0.5 * (t / sigma) ** 2)


def _emg(t: np.ndarray, sigma: float, tau: float) -> np.ndarray:
    """Unnormalised EMG.

    Written as ``exp(-u^2/2) * erfcx(z)`` rather than the textbook ``exp(...)* erfc(...)``: the two
    are algebraically identical (the ``exp(sigma^2/2tau^2)`` factor cancels exactly against
    ``exp(-z^2)``), but only this form survives small ``tau`` without overflowing.
    """
    u = t / sigma
    r = tau / sigma
    z = (1.0 / r - u) / np.sqrt(2.0)
    return np.exp(-0.5 * u**2) * special.erfcx(z)


def _ringing(
    t: np.ndarray, sigma: float, freq_hz: float, zeta: float, amplitude: float
) -> np.ndarray:
    """Gaussian impact plus the structural mode it excites, causal from the impact instant."""
    base = _gaussian(t, sigma)
    w_n = 2.0 * np.pi * freq_hz
    w_d = w_n * np.sqrt(max(1.0 - zeta**2, 1e-12))
    t_pos = np.maximum(t, 0.0)
    ring = amplitude * np.exp(-zeta * w_n * t_pos) * np.sin(w_d * t_pos)
    return base + np.where(t >= 0.0, ring, 0.0)


def _parabolic(t: np.ndarray, fwhm: float) -> np.ndarray:
    """Clipped parabola of unit peak. ``1 - (t/h)^2`` with ``h = fwhm/sqrt(2)``.

    The half-width follows from the FWHM convention the other shapes use: the parabola reaches half
    its peak at ``t = h/sqrt(2)``, so ``FWHM = h*sqrt(2)``.
    """
    half = fwhm / np.sqrt(2.0)
    u = t / half
    return np.clip(1.0 - u * u, 0.0, None)


def _raw(t: np.ndarray, fwhm: float, cfg: PulseConfig) -> np.ndarray:
    sigma = fwhm * FWHM_TO_SIGMA
    if cfg.shape == "influence_line":
        return _parabolic(t, fwhm)
    if cfg.shape == "gaussian":
        return _gaussian(t, sigma)
    if cfg.shape == "emg":
        return _emg(t, sigma, cfg.emg_tau_ratio * fwhm)
    if cfg.shape == "ringing":
        return _ringing(t, sigma, cfg.ring_freq_hz, cfg.ring_damping, cfg.ring_amplitude)
    raise ValueError(f"unknown pulse shape {cfg.shape!r}")


def _peak_scale(fwhm: float, cfg: PulseConfig) -> float:
    """Value by which the raw shape must be divided to make its peak exactly 1.

    Found on a dense grid rather than analytically, because the ringing composite has no closed
    form. Cached on the parameters that actually determine the shape; the grid is fixed, so the
    result is deterministic.
    """
    if cfg.shape in ("gaussian", "influence_line"):
        return 1.0
    key: tuple
    if cfg.shape == "emg":
        # self-similar in units of sigma, so only the ratio matters
        key = ("emg", round(cfg.emg_tau_ratio, 12))
    else:
        key = (
            "ringing",
            round(cfg.ring_freq_hz * fwhm, 9),
            round(cfg.ring_damping, 12),
            round(cfg.ring_amplitude, 12),
        )
    if key not in _peak_cache:
        grid = np.linspace(-2.0 * fwhm, 4.0 * fwhm, 20001)
        _peak_cache[key] = float(np.max(_raw(grid, fwhm, cfg)))
    return _peak_cache[key]


def pulse_waveform(t_rel: np.ndarray, fwhm: float, cfg: PulseConfig) -> np.ndarray:
    """phi(t_rel; fwhm), unit peak, zero outside the configured support."""
    support = cfg.support_widths * fwhm
    out = np.zeros_like(t_rel, dtype=np.float64)
    inside = (t_rel >= -support) & (t_rel <= support)
    if not inside.any():
        return out
    out[inside] = _raw(t_rel[inside], fwhm, cfg) / _peak_scale(fwhm, cfg)
    return out


def pulse_area_factor(fwhm: float, cfg: PulseConfig, *, samples: int = 20001) -> float:
    """Integral of the unit-peak shape, in seconds.

    For a Gaussian this is ``sigma*sqrt(2*pi) ~ 1.0645*FWHM``; the other shapes carry more area for
    the same peak. Used to predict a pass's true area without integrating the whole signal.
    """
    support = cfg.support_widths * fwhm
    grid = np.linspace(-support, support, samples)
    return float(np.trapezoid(pulse_waveform(grid, fwhm, cfg), grid))
