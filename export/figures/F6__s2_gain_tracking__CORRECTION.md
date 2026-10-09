# F6 (CORRECTION) — Estimated against true gain on S2

**File:** `F6__s2_gain_tracking__CORRECTION.png`  
**Replaces:** `s2__gain_tracking.png`, which plotted k̂ against 1/k_true.  
**Data:** `export/data/s2_gain_trajectory_long.csv`, `export/data/F8_s2_seed1_trajectory.csv`; statistics in `export/data/F6_correction_stats.csv`.

**Statistic:** descriptive, one run: each series as a deviation from its own median; Pearson correlation of k̂ with k_true and rms distance between their relative deviations, from t = 1 h (after the Kalman start-up transient).

**Sample:** S2_thermal_cycle, seed 1, ladder30's configuration.

## Caption

Estimated sensor gain k̂ for the frozen, RLS and Kalman arms against the true gain k_true, both in the sensor direction and both as deviations from their own medians. On this seed k̂ correlates with k_true at +0.35 (RLS) and +0.30 (Kalman): weakly positive, not negative. The adaptive estimates sit 0.44 % (RLS) and 0.57 % (Kalman) rms from the true trajectory, against 0.12 % for a constant: their motion is mostly noise, not tracking. Over ten seeds (item 1.5, instrumented runs) the correlation is +0.03 to +0.21 by arm and the distance 2–7 times a constant's.

## Notes

- The original figure's anti-correlation is the sign of a direction mismatch: on the same data, corr(k̂, 1/k_true) is -0.35 (RLS) and -0.30 (Kalman).
- The script that drew the original was never committed; this one is `scripts/f6_gain_tracking_correction.py`.
