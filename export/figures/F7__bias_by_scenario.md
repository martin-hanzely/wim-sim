# F7 — Bias by scenario and arm

**File:** `F7__bias_by_scenario.png`  
**Data:** `export/data/F7_bias.csv`.

**Statistic:** Per run, bias = mean signed error (estimated − static mass) over the run's vehicles. Upper panel: MEDIAN over seeds of that signed bias. Lower panel: MEDIAN over seeds of its absolute value. Intervals: bootstrap 95 % CI of the median, 5 000 resamples. Means over seeds of both are in the CSV and are not plotted.

**Sample:** ladder30, 30 seeds, 7 scenarios × 3 arms.

## Caption

Two statistics, labelled, because an earlier draft conflated them. On S2 the frozen arm's median absolute bias is 23.67 kg against 5.74 kg (rls) and 5.62 kg (kalman); its median signed bias is -17.56 kg (rls -3.22, kalman -1.86). The absolute and signed medians differ because the sign of a run's bias varies across seeds: a median of |b| is not |median of b|.

## Notes

- The brief calls 23.67 / 5.74 / 5.62 the 'mean absolute bias'. They are the MEDIAN over seeds of |run bias| (the run bias itself being a mean over vehicles). The MEAN over seeds of |run bias| is 25.76 / 5.95 / 5.97 kg. Suggested wording: 'median absolute bias'.
- The p_holm < 1e-5 annotation is carried from the Phase 0 bias tests (ladder30, frozen vs each tracked arm on |bias|), not recomputed here.
