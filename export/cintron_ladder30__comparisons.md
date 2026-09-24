# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

14 tests, 7 significant at 0.05 after correction. The smallest test in the family rests on 30 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S1_nominal / static_affine->kalman | 30 | 12.3 | 12.3 | +0.0325 | +0.04 | 0.855 | 1 | not separated (p_holm = 1) |
| S1_nominal / static_affine->rls | 30 | 12.3 | 12.2 | -0.0358 | -0.41 | 0.0523 | 0.261 | not separated (p_holm = 0.261) |
| S2_thermal_cycle / static_affine->kalman | 30 | 152 | 153 | +0.48 | -0.04 | 0.871 | 1 | not separated (p_holm = 1) |
| S2_thermal_cycle / static_affine->rls | 30 | 152 | 152 | -1.07 | -0.59 | 0.00374 | 0.03 | better (p_holm = 0.03) |
| S3_zero_drift_walk / static_affine->kalman | 30 | 152 | 154 | +1.09 | +0.19 | 0.382 | 1 | not separated (p_holm = 1) |
| S3_zero_drift_walk / static_affine->rls | 30 | 152 | 152 | -0.687 | -0.44 | 0.0345 | 0.207 | not separated (p_holm = 0.207) |
| S4_step_fault / static_affine->kalman | 30 | 198 | 166 | -33.2 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S4_step_fault / static_affine->rls | 30 | 198 | 168 | -31.8 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S5_outage / static_affine->kalman | 30 | 153 | 155 | +0.952 | +0.23 | 0.271 | 1 | not separated (p_holm = 1) |
| S5_outage / static_affine->rls | 30 | 153 | 151 | -1.08 | -0.50 | 0.0164 | 0.115 | not separated (p_holm = 0.115) |
| S6_combined / static_affine->kalman | 30 | 685 | 710 | +9.6 | +0.60 | 0.00299 | 0.0269 | worse (p_holm = 0.0269) |
| S6_combined / static_affine->rls | 30 | 685 | 663 | -30.7 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |
| S7_sparse_reference / static_affine->kalman | 30 | 192 | 174 | -18.1 | -1.00 | 3.73e-09 | 3.73e-08 | better (p_holm = 3.73e-08) |
| S7_sparse_reference / static_affine->rls | 30 | 192 | 174 | -18.2 | -1.00 | 1.86e-09 | 2.61e-08 | better (p_holm = 2.61e-08) |

