# Simulator cross-validation: leave one recording out

Commit `c8711871bd7ddd80975eb78d926abe2d83dcad89`. 8 folds over 8 recordings, 7 training recordings per fold, 25 kHz, 60 s each.

Section V-C concedes that no simulator parameter has ever been cross-validated. This is that test: fit the noise, drift and pulse parameters on every recording but one, synthesise a trace with the fitted values on the held-out recording's own sample grid, and compare their statistics. **The held-out columns are the result.** The in-sample columns are the same comparison with the recording's own fit, carried only so the gap between the two is visible.

Crossings are excised from both traces before any noise or drift statistic, by the same mask, because a one-second drive-over is a far larger excursion than the noise being measured and would dominate the low-frequency slope entirely. `quiescent` is the share of each recording left after that.

Agreement is `log2(synthetic / real)`: 0 is exact, +1 is the simulator twice the recording, -1 is half. Symmetric in direction, which a plain ratio is not.

## Measured on each recording

| recording | quiescent | white sigma | 50 Hz amp | drift slope | decades | increment sd | robust sd | white part | kurtosis | FWHM s | best shape | resid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 20260209_cintron1 | 0.73 | 0.000229 | 0.000772 | -2.77 | 1.4 | 1.93e-05 | 1.86e-05 | 1.45e-05 | +1.5 | 0.885 | triangle | 0.205 |
| 20260209_cintron2_spat | 0.48 | 0.000229 | 0.000767 | -2.34 | 1.4 | 2.38e-05 | 1.94e-05 | 1.45e-05 | +38.8 | 0.808 | raised_cosine | 0.083 |
| 20260209_cintron3 | 0.64 | 0.000229 | 0.000763 | -1.02 | 1.4 | 2.03e-05 | 1.88e-05 | 1.45e-05 | +9.4 | 0.747 | raised_cosine | 0.119 |
| 20260209_cintron4 | 0.35 | 0.000229 | 0.000775 | -2.18 | 1.4 | 0.000133 | 1.85e-05 | 1.45e-05 | +970.9 | 0.569 | parabola | 0.052 |
| 20260209_cintron5 | 0.36 | 0.000228 | 0.00077 | -1.99 | 1.4 | 2.05e-05 | 1.76e-05 | 1.44e-05 | +43.2 | 0.372 | triangle | 0.118 |
| 20260209_fabia1 | 0.60 | 0.000229 | 0.000774 | -2.31 | 1.4 | 0.000103 | 1.98e-05 | 1.45e-05 | +802.3 | 0.964 | triangle | 0.184 |
| 20260209_fabia2 | 0.80 | 0.000229 | 0.000778 | -2.64 | 1.4 | 8.41e-05 | 2.07e-05 | 1.45e-05 | +1697.5 | -- | -- | -- |
| 20260209_fabia3 | 0.59 | 0.000228 | 0.000783 | -1.13 | 1.4 | 2.17e-05 | 1.88e-05 | 1.44e-05 | +35.0 | 1.104 | triangle | 0.236 |

## Held-out agreement, per fold

| held out | white sigma | 50 Hz amp | increment sd | drift slope (diff) | kurtosis (diff) | influence length |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260209_cintron1 | -0.01 | -0.04 | +1.19 | +1.35 | -0 | -0.19 |
| 20260209_cintron2_spat | -0.00 | -0.02 | +1.05 | +0.76 | -37 | +0.01 |
| 20260209_cintron3 | -0.00 | -0.01 | +1.06 | -0.50 | -9 | +0.18 |
| 20260209_cintron4 | +0.00 | -0.04 | +1.09 | +0.49 | -968 | +0.57 |
| 20260209_cintron5 | -0.00 | -0.03 | +1.22 | +0.40 | -34 | +1.19 |
| 20260209_fabia1 | -0.00 | -0.04 | +1.07 | +0.77 | -792 | -0.31 |
| 20260209_fabia2 | -0.00 | -0.05 | +1.00 | +1.16 | -1697 | -- |
| 20260209_fabia3 | +0.00 | -0.06 | +1.10 | -0.39 | -29 | -0.51 |

## Held out against in sample

Median absolute disagreement across folds. If the two columns are close, the fit is not memorising the recording it was fitted on; if held-out is much worse, it is.

| statistic | held out | in sample |
| --- | ---: | ---: |
| white_sigma | 0.00 | 0.00 |
| mains_amplitude | 0.04 | 0.04 |
| increment_sd | 1.08 | 1.07 |
| drift_slope_diff | 0.63 | 0.62 |
| increment_kurtosis_diff | 35.82 | 32.73 |
| fwhm_s | 0.31 | 0.00 |

There is no pass mark here. A simulator agreeing to within a few per cent on every statistic would mean the statistics were not discriminating. What is reportable is the size and direction of the disagreement, and whether holding a recording out makes it worse than fitting on it.

The influence length inherits an inference rather than a measurement: it is the measured FWHM times a crossing speed of 0.78 m/s that was never measured and is not re-measurable. See the header of `configs/stations/cintron_platform.yaml`. Its fold-to-fold agreement is therefore a statement about FWHM reproducibility and not about length in metres.

