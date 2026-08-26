"""Additive noise: white, 1/f, and mains interference.

**White** noise is drawn per sample. ``white_sigma`` is the per-sample standard deviation, so the
equivalent one-sided PSD is ``white_sigma**2 / (fs/2)`` -- changing the sample rate changes the
noise *density* implied by a fixed sigma. Say which you mean when you quote a number.

**1/f (pink)** noise is built as a superposition of Ornstein-Uhlenbeck relaxation processes with
octave-spaced correlation times. This is not a curve-fitting trick: flicker noise in strain gauges,
amplifiers and adhesives is conventionally modelled exactly this way, as an ensemble of relaxation
processes with a broad distribution of time constants. Octave spacing of unit-variance sections
yields ``S(f) ~ 8/(pi f)`` across the band ``[f_min, f_max]``, flattening outside it -- which is the
physically correct behaviour, since no real process is 1/f down to DC.

Because pink noise is by construction band-limited to ``f_max`` (default 20 Hz), it is generated on
the coarse *plant grid* and interpolated onto the sample grid. Generating it at 2 kHz would cost an
order of magnitude more and add nothing above 20 Hz.

**Mains** interference is a fixed-frequency sinusoid plus harmonics with a per-run random phase.
Its frequency is exactly constant, which is the point: it is the one interferer a notch filter can
remove, and phase 2 will have to decide whether to bother.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps

from wimsim.core.config import NoiseConfig
from wimsim.core.rng import RngStreams

__all__ = ["MainsInterference", "PinkNoise", "WhiteNoise"]


class WhiteNoise:
    """Per-sample Gaussian noise on the sample grid."""

    __slots__ = ("_rng", "sigma")

    def __init__(self, sigma: float, rngs: RngStreams) -> None:
        self.sigma = float(sigma)
        self._rng = rngs.get("noise.white")

    def advance(self, n: int) -> np.ndarray:
        if self.sigma <= 0.0:
            return np.zeros(n)
        return self.sigma * self._rng.standard_normal(n)


class PinkNoise:
    """Band-limited 1/f noise as a sum of octave-spaced OU relaxation processes.

    Runs on the plant grid. Each section is ``x[n] = a*x[n-1] + s*eps[n]`` with ``a = exp(-dt/tau)``
    and ``s = sqrt(1 - a**2)``, giving unit stationary variance; the sum of ``M`` such sections is
    scaled by ``sigma / sqrt(M)``.

    Sections are initialised from their stationary distribution rather than from zero, so there is
    no warm-up transient at the start of a run.
    """

    __slots__ = ("_a", "_rng", "_s", "_scale", "_zi", "sigma", "taus")

    def __init__(
        self,
        sigma: float,
        *,
        dt: float,
        f_min_hz: float,
        f_max_hz: float,
        rngs: RngStreams,
    ) -> None:
        self.sigma = float(sigma)
        self._rng = rngs.get("noise.pink")

        if f_max_hz <= f_min_hz:
            raise ValueError("pink noise needs f_max > f_min")
        nyquist = 0.5 / dt
        f_max_hz = min(f_max_hz, 0.4 * nyquist)
        n_sections = max(int(np.ceil(np.log2(f_max_hz / f_min_hz))) + 1, 1)
        freqs = f_min_hz * 2.0 ** np.arange(n_sections)
        self.taus = 1.0 / (2.0 * np.pi * freqs)

        self._a = np.exp(-dt / self.taus)
        self._s = np.sqrt(np.maximum(1.0 - self._a**2, 0.0))
        self._scale = self.sigma / np.sqrt(n_sections)
        # stationary start: each unit-variance section begins at a standard normal draw
        self._zi = self._rng.standard_normal(n_sections) * self._a

    @property
    def n_sections(self) -> int:
        return int(self.taus.shape[0])

    def advance(self, n: int) -> np.ndarray:
        if self.sigma <= 0.0 or n == 0:
            return np.zeros(n)
        # (n, M) C-order draw: concatenating two blocks gives the same numbers as one big block,
        # which is what makes output invariant to block size.
        eps = self._rng.standard_normal((n, self.n_sections))
        out = np.zeros(n)
        for m in range(self.n_sections):
            y, zf = sps.lfilter(
                [self._s[m]], [1.0, -self._a[m]], eps[:, m], zi=np.array([self._zi[m]])
            )
            self._zi[m] = zf[0]
            out += y
        return out * self._scale


class MainsInterference:
    """Deterministic mains hum on the sample grid: fundamental plus configured harmonics."""

    __slots__ = ("_phase", "cfg")

    def __init__(self, cfg: NoiseConfig, rngs: RngStreams) -> None:
        self.cfg = cfg.mains
        rng = rngs.get("noise.mains")
        # one phase for the whole run, drawn up front so it does not depend on block boundaries
        self._phase = float(rng.uniform(0.0, 2.0 * np.pi))

    def evaluate(self, t_s: np.ndarray) -> np.ndarray:
        c = self.cfg
        if not c.enabled or c.amplitude <= 0.0:
            return np.zeros_like(t_s)
        out = c.amplitude * np.sin(2.0 * np.pi * c.freq_hz * t_s + self._phase)
        for i, rel in enumerate(c.harmonics, start=2):
            if rel:
                out += (
                    c.amplitude * rel * np.sin(2.0 * np.pi * c.freq_hz * i * t_s + self._phase * i)
                )
        return out
