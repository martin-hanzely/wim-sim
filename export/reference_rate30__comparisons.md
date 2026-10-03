# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

42 tests, 1 significant at 0.05 after correction. The smallest test in the family rests on 1 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

**No test in this family could have reached 0.05.** With 1 nonzero pair(s) the smallest attainable two-sided p is 1, so every null result below is a statement about the seed count and not about the system.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S4_step_fault / reference_every_n=1 / kalman / loop off->on | 14 | 142 | 142 | -0.189 | -0.52 | 0.0843 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=2 / kalman / loop off->on | 7 | 144 | 144 | +0 | -0.07 | 0.866 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=3 / kalman / loop off->on | 13 | 146 | 146 | +0.0646 | +0.36 | 0.249 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / kalman / loop off->on | 9 | 147 | 147 | +0 | +0.16 | 0.678 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / kalman / loop off->on | 2 | 150 | 150 | +0 | +1.00 | 0.18 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / kalman / loop off->on | 3 | 158 | 158 | +0 | +1.00 | 0.109 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / kalman / loop off->on | 15 | 176 | 176 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=1 / rls / loop off->on | 12 | 140 | 140 | -0.2 | -0.82 | 0.0121 | 0.47 | not separated (p_holm = 0.47) |
| S4_step_fault / reference_every_n=2 / rls / loop off->on | 12 | 143 | 142 | -0.364 | -0.79 | 0.015 | 0.556 | not separated (p_holm = 0.556) |
| S4_step_fault / reference_every_n=3 / rls / loop off->on | 12 | 145 | 144 | -0.0939 | -0.69 | 0.0342 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / rls / loop off->on | 8 | 147 | 147 | +0 | -0.61 | 0.123 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / rls / loop off->on | 9 | 152 | 154 | +0 | +0.69 | 0.0663 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / rls / loop off->on | 3 | 161 | 161 | +0 | +0.67 | 0.285 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / rls / loop off->on | 15 | 170 | 170 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=1 / static_affine / loop off->on | 13 | 191 | 156 | -40.3 | -1.00 | 0.00147 | 0.0604 | not separated (p_holm = 0.0604) |
| S4_step_fault / reference_every_n=2 / static_affine / loop off->on | 15 | 191 | 155 | -33.4 | -0.97 | 0.000183 | 0.00769 | better (p_holm = 0.00769) |
| S4_step_fault / reference_every_n=3 / static_affine / loop off->on | 12 | 191 | 157 | -31.4 | -0.97 | 0.00287 | 0.115 | not separated (p_holm = 0.115) |
| S4_step_fault / reference_every_n=5 / static_affine / loop off->on | 11 | 191 | 182 | -8.37 | -0.85 | 0.0128 | 0.486 | not separated (p_holm = 0.486) |
| S4_step_fault / reference_every_n=10 / static_affine / loop off->on | 14 | 191 | 182 | -8.63 | -0.58 | 0.0555 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / static_affine / loop off->on | 4 | 191 | 192 | +0 | -0.60 | 0.273 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / static_affine / loop off->on | 15 | 191 | 191 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=1 / kalman / loop off->on | 10 | 159 | 160 | +0.0245 | +0.85 | 0.0166 | 0.598 | not separated (p_holm = 0.598) |
| S7_sparse_reference / reference_every_n=2 / kalman / loop off->on | 3 | 160 | 161 | +0 | +1.00 | 0.109 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=3 / kalman / loop off->on | 5 | 160 | 161 | +0 | +0.87 | 0.0796 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / kalman / loop off->on | 3 | 162 | 162 | +0 | +0.67 | 0.285 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / kalman / loop off->on | 1 | 163 | 163 | +0 | +1.00 | 0.317 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / kalman / loop off->on | 1 | 167 | 167 | +0 | +1.00 | 0.317 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / kalman / loop off->on | 15 | 174 | 174 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=1 / rls / loop off->on | 4 | 160 | 160 | +0 | +0.40 | 0.465 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / rls / loop off->on | 7 | 160 | 160 | +0 | +0.36 | 0.398 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=3 / rls / loop off->on | 3 | 160 | 160 | +0 | +0.33 | 0.593 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / rls / loop off->on | 3 | 161 | 161 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=10 / rls / loop off->on | 1 | 162 | 162 | +0 | -1.00 | 0.317 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / rls / loop off->on | 1 | 166 | 165 | +0 | -1.00 | 0.317 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / rls / loop off->on | 15 | 173 | 173 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=1 / static_affine / loop off->on | 5 | 186 | 182 | +0 | -0.33 | 0.5 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / static_affine / loop off->on | 6 | 186 | 181 | +0 | -1.00 | 0.0277 | 0.942 | not separated (p_holm = 0.942) |
| S7_sparse_reference / reference_every_n=3 / static_affine / loop off->on | 4 | 186 | 182 | +0 | -1.00 | 0.0679 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / static_affine / loop off->on | 8 | 186 | 179 | +0 | -0.83 | 0.0357 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / static_affine / loop off->on | 7 | 186 | 178 | +0 | -1.00 | 0.018 | 0.629 | not separated (p_holm = 0.629) |
| S7_sparse_reference / reference_every_n=20 / static_affine / loop off->on | 4 | 186 | 182 | +0 | -0.80 | 0.144 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / static_affine / loop off->on | 15 | 186 | 186 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |

## every estimator against static_affine, every scenario  (`mae_kg`)

56 tests, 56 significant at 0.05 after correction. The smallest test in the family rests on 15 pair(s) with a nonzero difference -- pairs that came out exactly equal carry no information about a difference and are Wilcoxon's own discards, so that count and not the seed count is what sets the power.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S4_step_fault / reference_every_n=1 / control_enabled=False / static_affine->kalman | 15 | 191 | 142 | -47.7 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=1 / control_enabled=False / static_affine->rls | 15 | 191 | 140 | -48.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=1 / control_enabled=True / static_affine->kalman | 15 | 156 | 142 | -12.6 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=1 / control_enabled=True / static_affine->rls | 15 | 156 | 140 | -15.4 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=2 / control_enabled=False / static_affine->kalman | 15 | 191 | 144 | -46.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=2 / control_enabled=False / static_affine->rls | 15 | 191 | 143 | -46.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=2 / control_enabled=True / static_affine->kalman | 15 | 155 | 144 | -12.5 | -0.85 | 0.00201 | 0.0121 | better (p_holm = 0.0121) |
| S4_step_fault / reference_every_n=2 / control_enabled=True / static_affine->rls | 15 | 155 | 142 | -15.3 | -0.97 | 0.000183 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=3 / control_enabled=False / static_affine->kalman | 15 | 191 | 146 | -44.4 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=3 / control_enabled=False / static_affine->rls | 15 | 191 | 145 | -45.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=3 / control_enabled=True / static_affine->kalman | 15 | 157 | 146 | -7.68 | -0.77 | 0.00671 | 0.0336 | better (p_holm = 0.0336) |
| S4_step_fault / reference_every_n=3 / control_enabled=True / static_affine->rls | 15 | 157 | 144 | -8.82 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=5 / control_enabled=False / static_affine->kalman | 15 | 191 | 147 | -42.2 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=5 / control_enabled=False / static_affine->rls | 15 | 191 | 147 | -41.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=5 / control_enabled=True / static_affine->kalman | 15 | 182 | 147 | -29.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=5 / control_enabled=True / static_affine->rls | 15 | 182 | 147 | -30.5 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=10 / control_enabled=False / static_affine->kalman | 15 | 191 | 150 | -38.8 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=10 / control_enabled=False / static_affine->rls | 15 | 191 | 152 | -36.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=10 / control_enabled=True / static_affine->kalman | 15 | 182 | 150 | -31.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=10 / control_enabled=True / static_affine->rls | 15 | 182 | 154 | -27.7 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=20 / control_enabled=False / static_affine->kalman | 15 | 191 | 158 | -31.8 | -0.98 | 0.000122 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=20 / control_enabled=False / static_affine->rls | 15 | 191 | 161 | -33.6 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=20 / control_enabled=True / static_affine->kalman | 15 | 192 | 158 | -30.9 | -0.98 | 0.000122 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=20 / control_enabled=True / static_affine->rls | 15 | 192 | 161 | -32.4 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=50 / control_enabled=False / static_affine->kalman | 15 | 191 | 176 | -17.1 | -0.77 | 0.00671 | 0.0336 | better (p_holm = 0.0336) |
| S4_step_fault / reference_every_n=50 / control_enabled=False / static_affine->rls | 15 | 191 | 170 | -19.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S4_step_fault / reference_every_n=50 / control_enabled=True / static_affine->kalman | 15 | 191 | 176 | -17.1 | -0.77 | 0.00671 | 0.0336 | better (p_holm = 0.0336) |
| S4_step_fault / reference_every_n=50 / control_enabled=True / static_affine->rls | 15 | 191 | 170 | -19.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=1 / control_enabled=False / static_affine->kalman | 15 | 186 | 159 | -24.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=1 / control_enabled=False / static_affine->rls | 15 | 186 | 160 | -23.6 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=1 / control_enabled=True / static_affine->kalman | 15 | 182 | 160 | -21.8 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=1 / control_enabled=True / static_affine->rls | 15 | 182 | 160 | -21.2 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=False / static_affine->kalman | 15 | 186 | 160 | -24.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=False / static_affine->rls | 15 | 186 | 160 | -24.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=True / static_affine->kalman | 15 | 181 | 161 | -22.8 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=True / static_affine->rls | 15 | 181 | 160 | -22.4 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=3 / control_enabled=False / static_affine->kalman | 15 | 186 | 160 | -23.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=3 / control_enabled=False / static_affine->rls | 15 | 186 | 160 | -23.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=3 / control_enabled=True / static_affine->kalman | 15 | 182 | 161 | -21.1 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=3 / control_enabled=True / static_affine->rls | 15 | 182 | 160 | -22.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=False / static_affine->kalman | 15 | 186 | 162 | -23.4 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=False / static_affine->rls | 15 | 186 | 161 | -23.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=True / static_affine->kalman | 15 | 179 | 162 | -19.8 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=True / static_affine->rls | 15 | 179 | 161 | -19.9 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=False / static_affine->kalman | 15 | 186 | 163 | -22.5 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=False / static_affine->rls | 15 | 186 | 162 | -22.7 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=True / static_affine->kalman | 15 | 178 | 163 | -11.3 | -0.98 | 0.000122 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=True / static_affine->rls | 15 | 178 | 162 | -11.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=False / static_affine->kalman | 15 | 186 | 167 | -17.7 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=False / static_affine->rls | 15 | 186 | 166 | -20.2 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=True / static_affine->kalman | 15 | 182 | 167 | -14.5 | -0.98 | 0.000122 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=True / static_affine->rls | 15 | 182 | 165 | -17.3 | -1.00 | 6.1e-05 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=False / static_affine->kalman | 15 | 186 | 174 | -6.59 | -0.67 | 0.0215 | 0.0431 | better (p_holm = 0.0431) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=False / static_affine->rls | 15 | 186 | 173 | -14.5 | -0.97 | 0.000183 | 0.00342 | better (p_holm = 0.00342) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=True / static_affine->kalman | 15 | 186 | 174 | -6.59 | -0.67 | 0.0215 | 0.0431 | better (p_holm = 0.0431) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=True / static_affine->rls | 15 | 186 | 173 | -14.5 | -0.97 | 0.000183 | 0.00342 | better (p_holm = 0.00342) |

