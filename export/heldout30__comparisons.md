# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

8 tests, 4 significant at 0.05 after correction. The smallest test in the family rests on 30 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H1_warm_front / static_affine->kalman | 30 | 1.12e+03 | 1.37e+03 | +251 | +1.00 | 1.86e-09 | 1.49e-08 | worse (p_holm = 1.49e-08) |
| H1_warm_front / static_affine->rls | 30 | 1.12e+03 | 1.13e+03 | +26.7 | +0.29 | 0.164 | 0.493 | not separated (p_holm = 0.493) |
| H2_gain_jolt / static_affine->kalman | 30 | 322 | 272 | -47.4 | -1.00 | 1.86e-09 | 1.49e-08 | better (p_holm = 1.49e-08) |
| H2_gain_jolt / static_affine->rls | 30 | 322 | 278 | -39.1 | -1.00 | 1.86e-09 | 1.49e-08 | better (p_holm = 1.49e-08) |
| H3_slow_fade / static_affine->kalman | 30 | 308 | 310 | +28 | +0.13 | 0.556 | 1 | not separated (p_holm = 1) |
| H3_slow_fade / static_affine->rls | 30 | 308 | 281 | -21.7 | -0.40 | 0.0577 | 0.231 | not separated (p_holm = 0.231) |
| H4_pileup / static_affine->kalman | 30 | 941 | 918 | -4.02 | -0.14 | 0.529 | 1 | not separated (p_holm = 1) |
| H4_pileup / static_affine->rls | 30 | 941 | 876 | -29.5 | -0.92 | 5.72e-07 | 2.86e-06 | better (p_holm = 2.86e-06) |

