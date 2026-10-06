# F12 — Development against held out

**File:** `F12__development_vs_heldout.png`  
**Data:** `export/data/F12_heldout.csv` (a); `export/data/F12_tuned_transfer.csv` (b).

**Statistic:** (a) rank-biserial of the per-seed paired differences (tracked − frozen MAE), sign-count form, on each side. (b) per-seed paired differences in kg and their median. No difference of medians anywhere.

**Sample:** (a) ladder30 and heldout30, 30 seeds each, 8 matched pairs. (b) development side 30 seeds; H2 10 seeds (unanimous at ten, not escalated); H1 30 seeds.

## Caption

(a) 3 of 8 matched pairs change sign (H1/rls, H3/kalman, H4/kalman), ringed in red. Read with the difficulty confound: H1 was drawn 5.6× and H3 2.4× further above their own floors than their development counterparts, while H2 and H4 were drawn at comparable difficulty, so non-reproduction is not separable from a harder draw. (b) A memory chosen on a development scenario, applied unchanged to its held-out pair. λ = 0.95, chosen on S4, beats frozen on H2 by 57.8 kg (+0/-10) and the shipped λ = 0.99 by 15.0 kg (+0/-10). λ = 0.999, chosen on S2, does not transfer to H1: +12.6 kg against frozen (+18/-12), -8.4 kg against λ = 0.99 (+10/-20, p_holm 0.32 at thirty seeds).

## Notes

- Panel (b) is separate because its points are kg, not rank-biserial; on (a)'s axes the H2 points would sit at (−1, −1) on top of the shipped-RLS point.
- The 5.6× and 2.4× difficulty ratios are carried from the Phase 0 audit.
- H1 p_holm 0.32 is from `export/data/p1/p1_escalations.csv` (family '1.3 held-out tuned lambda').
