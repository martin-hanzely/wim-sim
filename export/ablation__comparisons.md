# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

The controller was not an axis in this sweep: every run is on the same arm, so there is no off-against-on comparison to make here.

## every estimator against static_affine, every scenario  (`mae_kg`)

10 tests, 7 significant at 0.05 after correction. The smallest test in the family rests on 10 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S6_ablate_calibration_fault / static_affine->kalman | 10 | 640 | 689 | +29.3 | +1.00 | 0.00195 | 0.0195 | worse (p_holm = 0.0195) |
| S6_ablate_calibration_fault / static_affine->rls | 10 | 640 | 630 | -11.5 | -1.00 | 0.00195 | 0.0195 | better (p_holm = 0.0195) |
| S6_ablate_outage / static_affine->kalman | 10 | 678 | 698 | +27.4 | +0.93 | 0.00586 | 0.0234 | worse (p_holm = 0.0234) |
| S6_ablate_outage / static_affine->rls | 10 | 678 | 635 | -34.4 | -1.00 | 0.00195 | 0.0195 | better (p_holm = 0.0195) |
| S6_ablate_thermal / static_affine->kalman | 10 | 689 | 689 | +8.49 | +0.45 | 0.232 | 0.465 | not separated (p_holm = 0.465) |
| S6_ablate_thermal / static_affine->rls | 10 | 689 | 648 | -33.6 | -1.00 | 0.00195 | 0.0195 | better (p_holm = 0.0195) |
| S6_ablate_zero_walk / static_affine->kalman | 10 | 680 | 680 | +5.16 | +0.42 | 0.275 | 0.465 | not separated (p_holm = 0.465) |
| S6_ablate_zero_walk / static_affine->rls | 10 | 680 | 644 | -34.8 | -1.00 | 0.00195 | 0.0195 | better (p_holm = 0.0195) |
| S6_combined / static_affine->kalman | 10 | 678 | 689 | +7.8 | +0.56 | 0.131 | 0.393 | not separated (p_holm = 0.393) |
| S6_combined / static_affine->rls | 10 | 678 | 649 | -30.7 | -1.00 | 0.00195 | 0.0195 | better (p_holm = 0.0195) |

