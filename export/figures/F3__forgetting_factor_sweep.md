# F3 — The forgetting-factor sweep

**File:** `F3__forgetting_factor_sweep.png`  
**Data:** `export/data/F3_lambda_sweep.csv` (cells, both stages); `export/data/F3_kalman_corrected_R.csv` (Kalman, table only).

**Statistic:** Per seed: RLS MAE at λ minus frozen MAE on the same seed. Plotted: the distribution of those paired differences over 30 seeds; labelled: their median, the sign count, and Wilcoxon signed-rank p, Holm-corrected over the fifteen cells. The difference of medians is not used.

**Sample:** 30 seeds per cell, 5 λ × 3 scenarios. Frozen and λ = 0.99 from ladder30 (seeds 1–30); other λ: seeds 1–10 from p1_lambda / p1_mem_dev_l1, seeds 11–30 from the thirty-seed stages. Cells unanimous at ten seeds (S2 at 0.95; S4 and S7 at 0.995, 0.999, 1.0) were escalated for figure uniformity, not because the protocol required it. Both stages are in the CSV (`stage`).

## Caption

RLS against the frozen arm across the forgetting factor, with the frozen arm as the zero line and the floor drawn where the whole of the scenario's recoverable excess would be recovered (S2 2.7, S4 46.0, S7 20.7 kg). The argument is excess against misadjustment. On S2 the sign changes between λ = 0.95 (+4.13 kg, +25/-5) and λ = 0.99: a short memory costs more than the whole excess. The At the shipped λ = 0.99 the difference is -0.80 kg (+11/-19, raw p 0.029); whether that separates depends on the correction family: p_holm 0.198 in ladder30's pre-registered 14-test family (not separated), 0.029 in this figure's 15-cell family (separated). At 0.995 it is -1.22 kg (+7/-23, p_holm 2.4e-04) and at 0.999 -1.47 kg (+6/-24). [PENDING: the article's inference sentence for S2 at 0.99 depends on which family it adopts; see the notes.] On S4 the ordering is reversed: λ = 0.95 is best (-35.5 kg against frozen) and beats λ = 0.99 by 7.2 kg on 29 of 30 seeds (p 3.7e-09). On S7 the best cell is λ = 0.99 (-14.1 kg).

## Notes

- The Kalman with R corrected is NOT drawn: it has no forgetting factor, and its effective memory changes with its covariance through the run, so no position on the λ axis is defined. Its values are in `F3_kalman_corrected_R.csv`: S2 -1.44 kg (+4/-26, 30 seeds); S4 -18.19 kg (+0/-10, 10 seeds); S7 -5.29 kg (+2/-28, 30 seeds).
- Choosing the best λ from this sweep and reporting it on the same scenarios is in-sample; the held-out check is F12(b).
- Holm here is over this figure's fifteen cells; the p_holm values in the escalation tables are over their own families and differ.
- The dashed floor line is drawn at minus the MEDIAN frozen excess. Each seed has its own excess, so individual seeds can fall below the line without recovering more than that seed's own excess.
- FAMILY DEPENDENCE, S2 at λ = 0.99: raw p 0.029. Holm over ladder30's 14 shipped-setting comparisons (the pre-registered family the single-setting benchmark used) gives 0.198, not separated; Holm over this figure's 15 cells, where the other fourteen p are all small, leaves it at 0.029, separated. 'At 0.99 the evidence is null' is true of the single-setting benchmark's own correction, not of the data.
