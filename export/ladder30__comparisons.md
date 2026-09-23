# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

14 tests, 5 significant at 0.05 after correction. The smallest test in the family rests on 30 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S1_nominal / static_affine->kalman | 30 | 0.944 | 0.951 | +0.00673 | +0.47 | 0.0248 | 0.198 | not separated (p_holm = 0.198) |
| S1_nominal / static_affine->rls | 30 | 0.944 | 0.94 | +0.001 | +0.05 | 0.808 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->kalman | 30 | 139 | 139 | +0.629 | +0.15 | 0.477 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->rls | 30 | 139 | 138 | -0.798 | -0.45 | 0.0293 | 0.198 | not separated (p_holm = 0.198) |
| S3_zero_drift_walk / static_affine->kalman | 30 | 139 | 140 | +0.759 | +0.08 | 0.715 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->rls | 30 | 139 | 138 | -0.892 | -0.50 | 0.0155 | 0.139 | not separated (p_holm = 0.139) |
| S4_step_fault / static_affine->kalman | 30 | 182 | 151 | -31.6 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S4_step_fault / static_affine->rls | 30 | 182 | 154 | -27.1 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S5_outage / static_affine->kalman | 30 | 139 | 143 | +0.701 | +0.29 | 0.164 | 0.657 | not separated (p_holm = 0.657) |
| S5_outage / static_affine->rls | 30 | 139 | 138 | -0.811 | -0.42 | 0.0473 | 0.236 | not separated (p_holm = 0.236) |
| S6_combined / static_affine->kalman | 30 | 697 | 707 | +12 | +0.46 | 0.0277 | 0.198 | not separated (p_holm = 0.198) |
| S6_combined / static_affine->rls | 30 | 697 | 666 | -32.7 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S7_sparse_reference / static_affine->kalman | 30 | 179 | 163 | -14.2 | -0.97 | 3.54e-08 | 3.54e-07 | better (p_holm = 3.54e-07) |
| S7_sparse_reference / static_affine->rls | 30 | 179 | 162 | -14.1 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |

