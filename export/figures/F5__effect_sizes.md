# F5 — Effect sizes at the shipped memory

**File:** `F5__effect_sizes.png`  
**Data:** `export/data/F5_effect_sizes.csv`.

**Statistic:** Rank-biserial correlation of the per-seed paired differences (tracked − frozen MAE), SIGN-COUNT form: (#positive − #negative) / #nonzero. Intervals: percentile bootstrap over seeds, 5 000 resamples, fixed RNG. The rank-weighted (Kerby) form that the Wilcoxon test carries is in the CSV as `rb_rank`; the median paired difference in kg is `median_paired_diff_kg`.

**Sample:** ladder30, 30 seeds, 7 scenarios × 2 tracked arms = 14 comparisons.

## Caption

Effect of tracking against the frozen arm for all fourteen comparisons AT ONE SETTING: RLS at the shipped forgetting factor λ = 0.99 and the Kalman at its shipped Q and R. Ordered by the scenario's excess over the floor, largest at the top. This figure shows where adaptation helps at one memory length, not where adaptation helps: F3 shows that on S2 the conclusion at λ = 0.99 (no separation) reverses at λ ≥ 0.995, and on S4 a shorter memory does better still. 6 of 14 intervals exclude zero. S6/kalman sits at +0.33 (+20/-10), its interval [+0.00, +0.67].

## Notes

- The x-axis label in the previous version read 'matched-pairs rank-biserial', which conventionally names the rank-weighted form; the plotted quantity has always been the sign-count form. Both are in the CSV; the article should name the one it quotes.
