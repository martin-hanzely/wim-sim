# Paired comparisons

Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.
Median diff is the median of the per-seed differences (B - A), which is not the difference
of the medians. Effect is the matched-pairs rank-biserial correlation.

## control loop off vs on, every scenario and estimator  (`mae_kg`)

30 tests, 0 significant at 0.05 after correction. Smallest family member: 1 pairs.

**No test in this family could have reached 0.05.** With 1 pairs the smallest attainable two-sided p is 1, so every null result below is a statement about the seed count and not about the system.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S4_step_fault / reference_every_n=2 / kalman / loop off->on | 3 | 138 | 138 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=5 / kalman / loop off->on | 3 | 143 | 143 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=10 / kalman / loop off->on | 3 | 145 | 145 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=20 / kalman / loop off->on | 1 | 151 | 152 | +0 | +1.00 | 1 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / kalman / loop off->on | 3 | 156 | 156 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=2 / rls / loop off->on | 1 | 136 | 136 | +0 | +1.00 | 1 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / rls / loop off->on | 2 | 143 | 143 | +0.604 | +1.00 | 0.5 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / rls / loop off->on | 2 | 147 | 153 | +2.53 | +1.00 | 0.5 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / rls / loop off->on | 3 | 152 | 152 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=50 / rls / loop off->on | 3 | 159 | 159 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S4_step_fault / reference_every_n=2 / static_affine / loop off->on | 3 | 180 | 157 | -32.4 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / static_affine / loop off->on | 3 | 180 | 174 | -4.31 | -0.33 | 0.75 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / static_affine / loop off->on | 3 | 180 | 182 | -1.8 | -0.33 | 0.75 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / static_affine / loop off->on | 1 | 180 | 180 | +0 | -1.00 | 1 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / static_affine / loop off->on | 3 | 180 | 180 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=2 / kalman / loop off->on | 3 | 159 | 159 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=5 / kalman / loop off->on | 3 | 161 | 161 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=10 / kalman / loop off->on | 3 | 161 | 161 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=20 / kalman / loop off->on | 3 | 165 | 165 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=50 / kalman / loop off->on | 3 | 167 | 167 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=2 / rls / loop off->on | 3 | 159 | 159 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=5 / rls / loop off->on | 1 | 161 | 160 | +0 | -1.00 | 1 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / rls / loop off->on | 3 | 160 | 160 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=20 / rls / loop off->on | 3 | 163 | 163 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=50 / rls / loop off->on | 3 | 169 | 169 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=2 / static_affine / loop off->on | 1 | 182 | 179 | +0 | -1.00 | 1 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / static_affine / loop off->on | 1 | 182 | 179 | +0 | -1.00 | 1 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / static_affine / loop off->on | 3 | 182 | 182 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=20 / static_affine / loop off->on | 3 | 182 | 182 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |
| S7_sparse_reference / reference_every_n=50 / static_affine / loop off->on | 3 | 182 | 182 | +0 | +0.00 | 1 | 1 | identical -- the two arms produced the same numbers |

## every estimator against static_affine, every scenario  (`mae_kg`)

40 tests, 0 significant at 0.05 after correction. Smallest family member: 3 pairs.

**No test in this family could have reached 0.05.** With 3 pairs the smallest attainable two-sided p is 0.25, so every null result below is a statement about the seed count and not about the system.

| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S4_step_fault / reference_every_n=2 / control_enabled=False / static_affine->kalman | 3 | 180 | 138 | -44.5 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=2 / control_enabled=False / static_affine->rls | 3 | 180 | 136 | -45.5 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=2 / control_enabled=True / static_affine->kalman | 3 | 157 | 138 | -14.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=2 / control_enabled=True / static_affine->rls | 3 | 157 | 136 | -16.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / control_enabled=False / static_affine->kalman | 3 | 180 | 143 | -42.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / control_enabled=False / static_affine->rls | 3 | 180 | 143 | -41.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / control_enabled=True / static_affine->kalman | 3 | 174 | 143 | -37.9 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=5 / control_enabled=True / static_affine->rls | 3 | 174 | 143 | -36.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / control_enabled=False / static_affine->kalman | 3 | 180 | 145 | -35.3 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / control_enabled=False / static_affine->rls | 3 | 180 | 147 | -32.9 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / control_enabled=True / static_affine->kalman | 3 | 182 | 145 | -38.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=10 / control_enabled=True / static_affine->rls | 3 | 182 | 153 | -29.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / control_enabled=False / static_affine->kalman | 3 | 180 | 151 | -31.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / control_enabled=False / static_affine->rls | 3 | 180 | 152 | -32.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / control_enabled=True / static_affine->kalman | 3 | 180 | 152 | -31.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=20 / control_enabled=True / static_affine->rls | 3 | 180 | 152 | -32.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / control_enabled=False / static_affine->kalman | 3 | 180 | 156 | -22.6 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / control_enabled=False / static_affine->rls | 3 | 180 | 159 | -19.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / control_enabled=True / static_affine->kalman | 3 | 180 | 156 | -22.6 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S4_step_fault / reference_every_n=50 / control_enabled=True / static_affine->rls | 3 | 180 | 159 | -19.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=False / static_affine->kalman | 3 | 182 | 159 | -23.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=False / static_affine->rls | 3 | 182 | 159 | -23.9 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=True / static_affine->kalman | 3 | 179 | 159 | -22.8 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=2 / control_enabled=True / static_affine->rls | 3 | 179 | 159 | -22.4 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=False / static_affine->kalman | 3 | 182 | 161 | -22.4 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=False / static_affine->rls | 3 | 182 | 161 | -22.6 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=True / static_affine->kalman | 3 | 179 | 161 | -20.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=5 / control_enabled=True / static_affine->rls | 3 | 179 | 160 | -20.9 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=False / static_affine->kalman | 3 | 182 | 161 | -22.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=False / static_affine->rls | 3 | 182 | 160 | -22.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=True / static_affine->kalman | 3 | 182 | 161 | -22.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=10 / control_enabled=True / static_affine->rls | 3 | 182 | 160 | -22.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=False / static_affine->kalman | 3 | 182 | 165 | -17.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=False / static_affine->rls | 3 | 182 | 163 | -19.4 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=True / static_affine->kalman | 3 | 182 | 165 | -17.7 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=20 / control_enabled=True / static_affine->rls | 3 | 182 | 163 | -19.4 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=False / static_affine->kalman | 3 | 182 | 167 | -15.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=False / static_affine->rls | 3 | 182 | 169 | -13.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=True / static_affine->kalman | 3 | 182 | 167 | -15.2 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |
| S7_sparse_reference / reference_every_n=50 / control_enabled=True / static_affine->rls | 3 | 182 | 169 | -13.1 | -1.00 | 0.25 | 1 | not separated (p_holm = 1) |

