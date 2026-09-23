# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

14 tests, 0 significant at 0.05 after correction. The smallest test in the family rests on 3 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

**No test in this family could have reached 0.05.** With 3 nonzero pair(s) the smallest attainable two-sided p is 0.25, so every null result below is a statement about the seed count and not about the system.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S1_nominal / static_affine->kalman | 3 | 12.4 | 12 | -0.0981 | -0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S1_nominal / static_affine->rls | 3 | 12.4 | 12 | -0.14 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->kalman | 3 | 149 | 151 | +1.24 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->rls | 3 | 149 | 150 | -0.347 | +0.00 | 1 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->kalman | 3 | 149 | 151 | +1.68 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->rls | 3 | 149 | 150 | +0.561 | +1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / static_affine->kalman | 3 | 194 | 160 | -36.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / static_affine->rls | 3 | 194 | 167 | -33.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S5_outage / static_affine->kalman | 3 | 144 | 143 | +2.22 | +0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S5_outage / static_affine->rls | 3 | 144 | 143 | -1.01 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S6_combined / static_affine->kalman | 3 | 683 | 668 | -13.7 | -0.67 | 0.5 | 1 | not separated (p_holm = 1) |
| S6_combined / static_affine->rls | 3 | 683 | 661 | -29.5 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / static_affine->kalman | 3 | 196 | 172 | -23.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / static_affine->rls | 3 | 196 | 172 | -23.5 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |

