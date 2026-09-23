# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

No comparison in this family could be paired.

## every estimator against static_affine, every scenario  (`mae_kg`)

3 tests, 3 significant at 0.05 after correction. The smallest test in the family rests on 16 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S2_thermal_cycle / reference_every_n=10.0 / control_enabled=False / static_affine->affine_temp | 21 | 139 | 4.41e+03 | +4.27e+03 | +1.00 | 9.54e-07 | 1.91e-06 | worse (p_holm = 1.91e-06) |
| S3_zero_drift_walk / reference_every_n=10.0 / control_enabled=False / static_affine->affine_temp | 30 | 139 | 151 | +8.4 | +0.99 | 9.31e-09 | 2.79e-08 | worse (p_holm = 2.79e-08) |
| S6_combined / reference_every_n=10.0 / control_enabled=False / static_affine->affine_temp | 16 | 714 | 2.93e+03 | +2.28e+03 | +1.00 | 3.05e-05 | 3.05e-05 | worse (p_holm = 3.05e-05) |

