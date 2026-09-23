# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

14 tests, 0 significant at 0.05 after correction. Smallest family member: 3 pairs.

**No test in this family could have reached 0.05.** With 3 pairs the smallest attainable two-sided p is 0.25, so every null result below is a statement about the seed count and not about the system.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S1_nominal / static_affine->kalman | 3 | 0.969 | 0.975 | +1.32e-05 | +0.00 | 1 | 1 | not separated (p_holm = 1) |
| S1_nominal / static_affine->rls | 3 | 0.969 | 0.971 | -0.0055 | -0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->kalman | 3 | 136 | 138 | +2.16 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->rls | 3 | 136 | 137 | +0.373 | +0.33 | 0.75 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->kalman | 3 | 133 | 136 | +2.62 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->rls | 3 | 133 | 135 | +1.01 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / static_affine->kalman | 3 | 182 | 145 | -38.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / static_affine->rls | 3 | 182 | 153 | -29.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S5_outage / static_affine->kalman | 3 | 127 | 126 | +1.32 | +0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S5_outage / static_affine->rls | 3 | 127 | 126 | -0.09 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S6_combined / static_affine->kalman | 3 | 677 | 698 | +8.29 | +0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S6_combined / static_affine->rls | 3 | 677 | 653 | -52.6 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / static_affine->kalman | 3 | 182 | 161 | -22.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / static_affine->rls | 3 | 182 | 160 | -22.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |

