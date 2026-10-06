# F2 — Error decomposition

**File:** `F2__error_decomposition.png`  
**Data:** `export/data/F2_decomposition.csv` (best arm and both arms, per scenario).

**Statistic:** Recovered share = −(median over seeds of the per-seed paired difference, tracked − frozen MAE) / frozen excess. Frozen excess = median frozen MAE − median dynamic-load floor. The difference of medians is not used.

**Sample:** ladder30, 30 seeds per scenario per arm, seven development scenarios.

## Caption

Upper panel: median absolute error per scenario, drawn as the dynamic-load floor (the error of an estimator that knew each vehicle's static mass exactly) with the excess over it stacked above, for the frozen arm (left) and for the frozen arm plus the best tracked arm's median paired difference (right). The excess is a DIFFERENCE, MAE_total − MAE_floor, not a component: mean absolute error is not additive, and the stacked bar shows where the floor sits, not a partition of the error. Lower panel: the excess alone on a log axis, with the excess share (excess / frozen MAE) and the share of it the best tracked arm recovers. S4 68.7 % (kalman); S7 68.4 % (kalman). S1 is shown deliberately: its floor is 0.0 kg, so its excess share is 100 % — the largest possible — on an excess of 0.9 kg, and the best arm recovers -0.1 % of it. A large share is not a sufficient condition for adaptation to help.

## Notes

- Both arms' recovered shares are in the CSV (`rls_recovered_pct`, `kalman_recovered_pct`); the figure draws the arm with the more negative median paired difference.
- The S1 share is 100 % by construction (floor 0); it is not a rounding artefact.
