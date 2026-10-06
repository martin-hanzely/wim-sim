# F14 — H1 process-noise sweep

**File:** `F14__h1_process_noise.png`  
**Data:** `export/data/kalman_q_ladder.csv` (sweep); `export/data/F14_q_rescaled_vs_shipped.csv` (check).

**Statistic:** y: median over seeds of the per-seed paired difference, Kalman − frozen MAE, on H1, one point per Q₁₁. The sweep's p_holm is over its five Q values.

**Sample:** H1_warm_front, 10 seeds per Q value; the shipped-vs-rescaled check: 30 seeds where escalated, 10 where ten were unanimous (S6).

## Caption

The H1 Kalman penalty against the gain's process noise over four decades. Stiffening Q makes the penalty worse, loosening it makes it smaller, and across the whole range it never approaches the ablation's +29.3 kg: the sweep does not explain the result. An earlier draft allowed that the penalty might be an artefact of a misspecified observation noise R; that explanation is withdrawn. With R corrected and Q rescaled to keep the shipped Q/R ratio, the filter differs from the shipped one by at most 4.3 kg on any scenario (H3 -4.3, H4 -3.0, S5 -2.1), all 11 of 11 in the rescaled filter's favour, and on H1 by -0.7 kg (+9/-21, p_holm 0.68). The penalty therefore depends on neither R nor the adaptation rate, and remains unexplained. The Q/R equivalence is approximate over a finite run from a finite initial covariance, not exact.

## Notes

- The plot is unchanged; only the caption is.
- 'Within 1.2 kg on every scenario' was a ten-seed, development-only figure and is superseded.
