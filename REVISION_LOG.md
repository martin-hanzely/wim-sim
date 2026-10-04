# Revision log

Phase 0 audit and the revision that follows it. Entries are append-only and in execution order.
Where an entry contradicts `export/`, it says so in its first line.

---

## Pre-specified seed protocol

**Declared 2026-10-04, before any run in Stages C–F. Not to be altered afterwards.**

> Every new comparison runs at ten seeds. A comparison whose per-seed differences are unanimous in
> sign is reported at ten seeds and not escalated. A comparison whose signs are not unanimous is
> escalated to thirty seeds, and both stages are reported.

The arithmetic that justifies it. Ten unanimous pairs give an exact two-sided sign/Wilcoxon p of
`2/2^10 = 0.00195`, which survives Holm correction across a family of fourteen:
`0.00195 x 14 = 0.027 < 0.05`. The `p = 2.6e-8` figures in the current export are the floor of an
exact Wilcoxon at `n = 30` (`min_attainable_p(30) = 2/2^30 = 1.9e-9`); those twenty extra seeds
measured the test's resolution limit, not the effect.

Two conditions make this honest rather than optional stopping, and both are binding:

1. the rule is declared in advance — this entry, committed before the first Stage C run;
2. **both stages are reported** — a comparison escalated to thirty seeds reports its ten-seed
   stage as well, with the same prominence.

Never decide seed counts after seeing results. Never escalate only the comparisons that failed to
separate.

### What would cost integrity — these stay off the table

- Cutting seeds after seeing results, or escalating only comparisons that failed to separate.
- Carrying any pre-fix controller result into a post-fix claim.
- Dropping the held-out set.
- Running some scenarios and quietly not reporting the rest.
- Switching on temperature compensation to make section III-B true retrospectively.

---

## Stage A — analysis only, no simulation

Completed 2026-10-04. No run was executed for this stage; every figure below is a reduction of
results already in `data/results/`.

### A0. Corrections to the audit's own premises

Three of the audit's statements did not survive checking. They are recorded here first because
Stages C–F were scoped on them.

**A0.1 — `ladder30`, `cintron_ladder30`, `heldout30` and `ablation` DID run with the controller
active.** The audit's "do not rerun these" list rests on the claim that "`default.yaml` ships
`control.enabled: false`, and the comparison reports confirm the controller was not an axis in the
ladder sweeps". `default.yaml` does ship `enabled: false` — but every ladder sweep overrides it.
`ladder30`'s own spec carries `edge_overrides: ["edge.control.enabled=true"]`, and the recorded
`control_enabled` column is `True` on all 630 rows.

"Not an axis" and "not active" are different statements. The controller was not *varied* in those
sweeps; it was *pinned on*. What the runs recorded:

| sweep | runs | control active | alarms | recalibrations | degradations |
|---|---|---|---|---|---|
| `ladder` | 63 | yes (63/63) | 73 | 9 | 1 |
| `ladder30` | 630 | yes (630/630) | 798 | 117 | 27 |
| `cintron_ladder` | 63 | yes (63/63) | 71 | 8 | 0 |
| `cintron_ladder30` | 630 | yes (630/630) | 691 | 87 | 16 |
| `heldout30` | 360 | yes (360/360) | 1234 | 220 | 46 |
| `theta2` | 180 | **no (0/180)** | – | – | – |
| `ablation` | 150 | yes (150/150) | 244 | 50 | 6 |
| `recal_coverage` | 300 | yes (300/300) | 492 | 156 | 50 |

The controller did not merely run, it acted: 117 recalibrations in `ladder30` alone. Of the five
sweeps the audit lists as unaffected, **only `theta2` is**. Any change to confirmation-window
semantics touches the other four.

This does not by itself mean they must be rerun — the confirmation window is reached in these
sweeps, which is why recalibrations happened — but the reason given for exempting them is not a
fact about the data, and the exemption cannot stand on it.

**A0.2 — the thermal claim is right about the preprocessor and wrong as stated about the project.**
"No temperature compensation runs in any reported experiment" holds for the *upstream* mechanism and
only for it. Verified: `experiments/offline.py:97` bootstraps `temp_coeff=0.0`; `_estimator_for` in
`closed_loop.py` never passes `temp_coeff`, so every estimator keeps its constructor default of
`0.0`; no file under `configs/` sets the key at all; and `edge/preprocess.py:419` returns a thermal
factor of exactly `1.0` when the coefficient is zero. The upstream path is inert in every run.

But `theta2` runs the `affine_temp` estimator, which fits the section III-B interaction term
`m = theta0 + theta1*s + theta2*(s*dT)` online, and that sweep is reported. Section III-B describes
*that* map. So the correction to III-B is narrower than "the path never ran": the three-parameter
map was fitted and tested, and what never ran is the fixed-coefficient upstream compensation the
preprocessor implements. Both facts belong in the text; conflating them would replace one wrong
sentence with another.

**A0.3 — the confirmation window is worse than the audit states, by a factor of two.** The audit
counts `confirmation_passes` only. `drift.warmup` is also 60 and is also counted in *references*,
and the two are sequential: no detector can alarm before warm-up completes, and confirmation begins
only after an alarm. The earliest a recalibration can occur is therefore
`(warmup + confirmation_passes) * reference_every_n / rate`.

On `S4_step_fault` at one reference in ten, 220 veh/h: warm-up 9,818 s, confirmation 9,818 s,
earliest recalibration **19,636 s** — 10.9× the 1,800 s fault horizon, not 5.5×.

### A1. Configuration provenance

Every sweep was re-resolved using **the code and configs of the commit it actually ran on**, via a
detached worktree per commit, and the resulting `edge_config_hash` set compared against the hashes
recorded in its own `results.parquet`.

**All fourteen sweeps verify exactly** — resolved hash set equals recorded hash set in every case:

| sweep | commit | runs | distinct edge configs | hash verified | control active |
|---|---|---|---|---|---|
| `ladder` | c1881d4f | 63 | 3 | yes | yes |
| `ladder30` | a2c70f37 | 630 | 3 | yes | yes |
| `cintron_ladder` | 76cc3775 | 63 | 3 | yes | yes |
| `cintron_ladder30` | f10cbd83 | 630 | 3 | yes | yes |
| `heldout30` | ac1af03c | 360 | 3 | yes | yes |
| `theta2` | a2c70f37 | 180 | 2 | yes | no |
| `ablation` | da9ca44f | 150 | 3 | yes | yes |
| `reference_rate` | c1881d4f | 180 | 30 | yes | yes |
| `reference_rate_ph75` | 6523c7de | 180 | 30 | yes | yes |
| `reference_rate30` | 1d452935 | 1260 | 42 | yes | yes |
| `detectors` | 8cda5fd9 | 100 | 5 | yes | yes |
| `detector_thresholds` | b675c9d5 | 340 | 17 | yes | yes |
| `governance` | f40ca518 | 18 | 6 | yes | yes |
| `recal_coverage` | 76cc3775 | 300 | 15 | yes | yes |

**This verification step was load-bearing and changed a number.** Re-resolving the specs against
*today's* configs reports Page–Hinkley 7.5 for the older sweeps. That is wrong: commit `6523c7d`
("Ship Page-Hinkley at 7.5") changed the default from 15.0, and every sweep predating it ran at
**15.0**. The naive re-resolution disagreed with the recorded hashes on exactly the seven
pre-`6523c7d` sweeps, which is how the error was caught. The table below carries the thresholds
that were actually in force.

**`confirmation_passes` is 60 in every sweep without exception** — the audit's finding C is resolved
in favour of `default.yaml`. The dataclass default of 30 at `controller.py:120` is never reached by
any experiment, because every sweep loads a config file and every config file that sets the key sets
it to 60. The two values should still be reconciled, but no reported result depends on 30.

Full per-cell table in `export/data/provenance_long.csv`. The control-enabled cells:

| sweep | scenario | ref_n | conf_passes | warmup_refs | PH | CUSUM | veh/h | horizon_s | conf_s | earliest_recal_s | conf/horizon |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ladder | S1_nominal | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| ladder | S2_thermal_cycle | 10 | 60 | 60 | 15.0 | 12.0 | 180.0 | 1800.0 | 12000 | 24000 | 6.67 |
| ladder | S3_zero_drift_walk | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ladder | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| ladder | S5_outage | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| ladder | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ladder | S7_sparse_reference | 10 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| ladder30 | S1_nominal | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| ladder30 | S2_thermal_cycle | 10 | 60 | 60 | 15.0 | 12.0 | 180.0 | 1800.0 | 12000 | 24000 | 6.67 |
| ladder30 | S3_zero_drift_walk | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ladder30 | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| ladder30 | S5_outage | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| ladder30 | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ladder30 | S7_sparse_reference | 10 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| cintron_ladder | S1_nominal | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| cintron_ladder | S2_thermal_cycle | 10 | 60 | 60 | 15.0 | 12.0 | 180.0 | 1800.0 | 12000 | 24000 | 6.67 |
| cintron_ladder | S3_zero_drift_walk | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| cintron_ladder | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| cintron_ladder | S5_outage | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| cintron_ladder | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| cintron_ladder | S7_sparse_reference | 10 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| cintron_ladder30 | S1_nominal | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| cintron_ladder30 | S2_thermal_cycle | 10 | 60 | 60 | 15.0 | 12.0 | 180.0 | 1800.0 | 12000 | 24000 | 6.67 |
| cintron_ladder30 | S3_zero_drift_walk | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| cintron_ladder30 | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| cintron_ladder30 | S5_outage | 10 | 60 | 60 | 15.0 | 12.0 | 240.0 | 1800.0 | 9000 | 18000 | 5.0 |
| cintron_ladder30 | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| cintron_ladder30 | S7_sparse_reference | 10 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| heldout30 | H1_warm_front | 10 | 60 | 60 | 7.5 | 12.0 | 310.0 | 1800.0 | 6968 | 13935 | 3.87 |
| heldout30 | H2_gain_jolt | 10 | 60 | 60 | 7.5 | 12.0 | 275.0 | 1800.0 | 7855 | 15709 | 4.36 |
| heldout30 | H3_slow_fade | 10 | 60 | 60 | 7.5 | 12.0 | 450.0 | 1800.0 | 4800 | 9600 | 2.67 |
| heldout30 | H4_pileup | 10 | 60 | 60 | 7.5 | 12.0 | 155.0 | 1800.0 | 13935 | 27871 | 7.74 |
| ablation | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ablation | S6_ablate_thermal | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ablation | S6_ablate_zero_walk | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ablation | S6_ablate_outage | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| ablation | S6_ablate_calibration_fault | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| reference_rate | S4_step_fault | 2 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 1964 | 3927 | 1.09 |
| reference_rate | S4_step_fault | 5 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 4909 | 9818 | 2.73 |
| reference_rate | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| reference_rate | S4_step_fault | 20 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 19636 | 39273 | 10.91 |
| reference_rate | S4_step_fault | 50 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 49091 | 98182 | 27.27 |
| reference_rate | S7_sparse_reference | 2 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 720 | 1440 | 0.4 |
| reference_rate | S7_sparse_reference | 5 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 1800 | 3600 | 1.0 |
| reference_rate | S7_sparse_reference | 10 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| reference_rate | S7_sparse_reference | 20 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 7200 | 14400 | 4.0 |
| reference_rate | S7_sparse_reference | 50 | 60 | 60 | 15.0 | 12.0 | 600.0 | 1800.0 | 18000 | 36000 | 10.0 |
| reference_rate_ph75 | S4_step_fault | 2 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 1964 | 3927 | 1.09 |
| reference_rate_ph75 | S4_step_fault | 5 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 4909 | 9818 | 2.73 |
| reference_rate_ph75 | S4_step_fault | 10 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| reference_rate_ph75 | S4_step_fault | 20 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 19636 | 39273 | 10.91 |
| reference_rate_ph75 | S4_step_fault | 50 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 49091 | 98182 | 27.27 |
| reference_rate_ph75 | S7_sparse_reference | 2 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 720 | 1440 | 0.4 |
| reference_rate_ph75 | S7_sparse_reference | 5 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 1800 | 3600 | 1.0 |
| reference_rate_ph75 | S7_sparse_reference | 10 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| reference_rate_ph75 | S7_sparse_reference | 20 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 7200 | 14400 | 4.0 |
| reference_rate_ph75 | S7_sparse_reference | 50 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 18000 | 36000 | 10.0 |
| reference_rate30 | S4_step_fault | 1 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 982 | 1964 | 0.55 |
| reference_rate30 | S4_step_fault | 2 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 1964 | 3927 | 1.09 |
| reference_rate30 | S4_step_fault | 3 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 2945 | 5891 | 1.64 |
| reference_rate30 | S4_step_fault | 5 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 4909 | 9818 | 2.73 |
| reference_rate30 | S4_step_fault | 10 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| reference_rate30 | S4_step_fault | 20 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 19636 | 39273 | 10.91 |
| reference_rate30 | S4_step_fault | 50 | 60 | 60 | 7.5 | 12.0 | 220.0 | 1800.0 | 49091 | 98182 | 27.27 |
| reference_rate30 | S7_sparse_reference | 1 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 360 | 720 | 0.2 |
| reference_rate30 | S7_sparse_reference | 2 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 720 | 1440 | 0.4 |
| reference_rate30 | S7_sparse_reference | 3 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 1080 | 2160 | 0.6 |
| reference_rate30 | S7_sparse_reference | 5 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 1800 | 3600 | 1.0 |
| reference_rate30 | S7_sparse_reference | 10 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 3600 | 7200 | 2.0 |
| reference_rate30 | S7_sparse_reference | 20 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 7200 | 14400 | 4.0 |
| reference_rate30 | S7_sparse_reference | 50 | 60 | 60 | 7.5 | 12.0 | 600.0 | 1800.0 | 18000 | 36000 | 10.0 |
| detectors | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| detectors | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| detector_thresholds | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| detector_thresholds | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| governance | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |
| recal_coverage | S4_step_fault | 10 | 60 | 60 | 15.0 | 12.0 | 220.0 | 1800.0 | 9818 | 19636 | 5.45 |
| recal_coverage | S6_combined | 10 | 60 | 60 | 15.0 | 12.0 | 200.0 | 1800.0 | 10800 | 21600 | 6.0 |

### A2. Held-out hygiene

**Seed counts are consistent.** `heldout30` ran seeds 1–30 for every one of the four scenarios and
all three estimators — 30/30/30/30, no gaps, 360 runs.

**The H ↔ S mapping**, taken from the declarations in the held-out scenario files themselves:

| held-out | development | class | floor H | floor S | static MAE H | static MAE S | H MAE/floor | S MAE/floor | **drawn harder by** |
|---|---|---|---|---|---|---|---|---|---|
| `H1_warm_front` | `S2_thermal_cycle` | thermal | 197.1 | 136.1 | 1124 | 139 | 5.71× | 1.02× | **5.6×** |
| `H2_gain_jolt` | `S4_step_fault` | abrupt fault | 248.4 | 136.4 | 322 | 182 | 1.30× | 1.34× | **1.0×** |
| `H3_slow_fade` | `S7_sparse_reference` | slow ramp | 111.3 | 158.3 | 308 | 179 | 2.77× | 1.13× | **2.4×** |
| `H4_pileup` | `S6_combined` | combined | 340.9 | 191.2 | 941 | 697 | 2.76× | 3.65× | **0.8×** |

All figures are medians over 30 seeds, `static_affine` arm, kg. "Drawn harder by" is the ratio of
the two MAE/floor columns: how much further above its own dynamic load floor the held-out scenario
sits than its development counterpart does.

On what dimension each pair differs:

- **H1 vs S2** — warmer site, daily swing half again as large, cooling rather than warming across
  the days, slower probe, twice-as-fast alpha walk, denser traffic with heavier dynamic load at a
  higher frequency, markedly less symmetric pulse.
- **H2 vs S4** — three faults rather than two; the first is a gain *rise*, where every injected
  sensitivity fault in S1–S8 reduces the gain; the displacement moves the zero line down while
  reducing the gain, where S4's moves it up while raising the gain; cold near-isothermal site.
- **H3 vs S7** — a three-hour ramp rather than two; a 4.2 % rise rather than a 3 % loss; the zero
  line walks and slopes underneath the fault, where S7 holds it nearly still.
- **H4 vs S6** — cold site with the largest daily swing in the suite; sparse traffic (155 vs
  200 veh/h); heavy low-frequency dynamic load; faster zero walk sloping the other way; louder
  mains; ringing pulse; gain fault rises where S6's falls.

Station is **not** a confound: both sets run on `endurance`.

**The difficulty confound, stated plainly: the two classes that fail to reproduce are exactly the
two drawn several times harder.** H1 at 5.6× and H3 at 2.4× are the two that do not reproduce;
H2 at 1.0× and H4 at 0.8× are the two that do. This belongs beside the held-out results, not only
in the discussion, because without it the natural reading — that the thermal and slow-ramp classes
fail to transfer — is not separable from the reading that those two draws were simply harder.

**The "sign flip" description of H3 Kalman is withdrawn.** The measured difference is
`static_affine -> kalman` **+28.0 kg**, rank-biserial **+0.13**, exact Wilcoxon **p = 0.556**,
**p_holm = 1**, with per-seed signs **18 positive / 12 negative** over 30 seeds and an IQR of
[−53.8, +54.3] kg straddling zero. That is an unseparated result in the opposite direction, which
is not a sign flip. For contrast, the two differences that *are* separated on this set are
unanimous: H1 at +251.4 kg with 30/30 positive signs, H2 at −47.4 kg with 30/30 negative.

### A3. Floor corrections

**Confirmed, all seven, to within rounding.** Medians over 30 seeds from `ladder30_long.csv`:

| scenario | median floor (kg) | quoted | delta | IQR (kg) |
|---|---|---|---|---|
| `S1_nominal` | 0.0 | 0.0 | 0.00 | [0.0, 0.0] |
| `S2_thermal_cycle` | 136.1 | 136.1 | −0.01 | [134.8, 137.7] |
| `S3_zero_drift_walk` | 135.7 | 135.7 | +0.03 | [132.4, 138.8] |
| `S4_step_fault` | 136.4 | 136.4 | −0.04 | [132.3, 140.5] |
| `S5_outage` | 136.2 | 136.2 | +0.04 | [131.4, 140.2] |
| `S6_combined` | 191.2 | 191.2 | −0.04 | [185.5, 193.5] |
| `S7_sparse_reference` | 158.3 | 158.3 | +0.02 | [155.5, 161.5] |

The floor is **identical across all three estimators** within each scenario and seed, which is the
property that makes it a floor rather than an error figure: it is a function of the scenario draw
and the seed, and no calibration can move it. Every reported floor must be labelled as such.

**For section V-A, on `S6_combined`** (medians over 30 seeds, floor 191.2 kg):

| arm | median MAE | above floor | IQR |
|---|---|---|---|
| `static_affine` | 696.9 | **505.8** | [660.8, 743.3] |
| `rls` | 665.7 | **474.6** | [628.2, 700.9] |
| `kalman` | 707.3 | 516.2 | [673.4, 759.2] |

Tracking recovers **31.2 kg of 505.8 kg, or 6.2 % of the excess over the floor**. The audit's 505.7
and ~475 are confirmed; the recovered fraction is 6.2 %, matching its ~6 %.

---

## Stage B3 — why tracking does not help on S2

Completed 2026-10-04. Cost: a plant-only walk at five seeds (no samples generated), one
closed-loop S2 run per estimator at seed 1, and a reduction of `ladder30`.

**Headline: the claim is wrong as stated. Tracking does not help S2's *MAE*, and it halves its
*bias* four times over. The two were separated, and in this project they must not be.**

### B3a. The thermal amplitude actually realised

Medians over seeds 1–5, peak-to-peak across the 72 h run. All three are modelled with separate
lags, so all three are reported:

| quantity | peak-to-peak | min | max |
|---|---|---|---|
| ambient `T_air` | **20.44 °C** | 4.38 | 25.00 |
| sensor body `T_sensor` | **19.22 °C** | 4.83 | 24.28 |
| probe `T_probe` | **19.63 °C** | 4.63 | 24.50 |

The sensor body swings least and the probe sits between it and ambient — the probe is not a
proxy for the sensor, which is the premise `S2` exists to exercise.

Per-seed figures in `export/data/s2_thermal_amplitude_long.csv`.

### B3b. The gain excursion it causes

| quantity | value |
|---|---|
| gain peak-to-peak | **0.388 %** (median over 5 seeds; 0.379 % on seed 1) |
| mean \|relative deviation\| | 0.111 % |
| rms relative deviation | 0.124 % |
| on a 20 t vehicle | **77.7 kg** peak-to-peak, 22.2 kg mean |

The audit's estimate — "roughly 0.38 % over 19 °C, about 76 kg on a 20 t vehicle" — is confirmed
to three significant figures.

**But 20 t is not a representative vehicle on this scenario.** The S2 population over 12,930
passes has a median mass of **1.56 t** and a mean of **6.33 t**; 20 t sits above its 90th
percentile (22.1 t). On the actual population the thermal gain error is an rms of **7.8 kg**.

### B3c. The error budget, and why MAE cannot see it

| term | kg |
|---|---|
| dynamic load floor | 136.1 |
| thermal rms contribution | 7.8 |
| floor and thermal in quadrature | 136.3 |
| **predicted excess over floor** | **0.2** |
| measured `static_affine` excess over floor | 2.9 |

Quadrature is the right combination: the dynamic load wobble and the thermal gain excursion are
independent and neither is a bias over the population. A disturbance that is 5.7 % of the floor
contributes 0.2 kg to a 136 kg MAE. **There is nothing in S2's MAE for tracking to recover, and
that is a property of the scenario rather than of the estimators.** Any ladder comparison on S2
measured in MAE alone is a null by construction.

### B3d. Reference density, and where the static fit is anchored

| quantity | value |
|---|---|
| traffic rate | 180 veh/h |
| `reference_every_n` | 10 |
| one reference every | 200 s |
| references over 72 h | ~1,293 (1,293 observed on seed 1) |
| bootstrap fit | the first 60 detections, **all** of which carry a reference mass |
| bootstrap spans | 1,200 s = 0.33 h |

Density is ample for the fit itself. What matters is **where in the thermal cycle those 20
minutes fall**, because `static_affine` is fitted there once and then frozen for three days.

On seed 1 the bootstrap window sits at a mean sensor temperature of **7.53 °C** against a run
median of **14.59 °C** — seven degrees cold, near the first night's minimum. The gain there is
**+0.146 %** above the run median, which is **+9.2 kg on the mean vehicle** and +29.2 kg on a
20 t one. A static fit anchored away from the median gain carries that offset as a **bias** for
the whole run, where the swing itself is zero-mean. The two are different errors and only one of
them is recoverable by refitting.

### B3e. What the measurement shows — bias, not error

`ladder30`, `S2_thermal_cycle`, 30 seeds, paired by seed. Bias rows compare **absolute** bias,
because the question is whether tracking moves the zero towards zero; the signed medians are
given underneath, because the sign must never be folded into the error.

| comparison | metric | median | → | median diff | signs | p (exact) | p_holm | verdict |
|---|---|---|---|---|---|---|---|---|
| static → rls | \|bias\| | 23.67 | **5.74** | −16.33 | +4/−26 | 3.86e-07 | 7.71e-07 | **separated** |
| static → kalman | \|bias\| | 23.67 | **5.62** | −16.67 | +3/−27 | 9.98e-07 | 2.00e-06 | **separated** |
| static → rls | MAE | 138.82 | 138.10 | −0.80 | +11/−19 | 0.0293 | 0.0587 | not separated |
| static → kalman | MAE | 138.82 | 139.19 | +0.63 | +17/−13 | 0.4771 | 0.4771 | not separated |

Signed median bias, 30 seeds: `static_affine` **−17.6 kg** (IQR [−34.4, +6.9]), `rls` −3.2 kg
(IQR [−7.8, +1.6]), `kalman` −1.9 kg (IQR [−6.9, +2.8]).

Holm is over this family of four. Both separated p-values sit **three orders of magnitude above**
the n=30 attainable floor of 1.9e-9, so these are measured effects and not the test's resolution
limit — unlike the `2.6e-8` figures elsewhere in the export.

### B3f. The trajectory figure, and the inconvenient part

`export/figures/s2__gain_tracking.png`, with per-event data in
`export/data/s2_gain_trajectory_long.csv`.

On seed 1, against a **required** gain trajectory (∝ 1/k_true) whose peak-to-peak is 0.379 % and
whose rms is 0.1240 %:

| arm | θ̂₁ swing | vs required | rms(θ̂₁ − required) | correlation with required |
|---|---|---|---|---|
| `static_affine` | **0.000 %** | 0.0× | 0.1245 % | — (constant) |
| `rls` | 2.009 % | **5.3×** | **0.5245 %** | **−0.348** |
| `kalman` | 8.118 % | **21.4×** | **0.6854 %** | **−0.266** |

Three things follow, and the second and third are not what the ladder's story predicts.

1. `static_affine` is genuinely frozen on this run — zero recalibrations, a gain that never
   moves. Its distance from the required trajectory is 0.1245 %, which is just the size of the
   target itself.
2. **Both adaptive arms sit four to five times further from the required trajectory than doing
   nothing does.** Tracking the thermal cycle is not what they are doing.
3. **Both are anti-correlated with it.** They do not lag the required trajectory, they move
   against it.

The anti-correlation is consistent with the two-parameter fit trading gain against zero: `S2`
couples the zero line to temperature as well as the gain (`temp_coupling_per_c: 1.2e-4`), and in
an affine fit a thermally-driven zero shift can be absorbed into the slope with the opposite
sign. **That is a mechanism the data is consistent with, not one this experiment establishes** —
separating it would need the zero coupling switched off, which is an ablation nobody has run.

### B3g. What this means for the text

The honest statement is not "tracking does not help on S2". It is:

- S2's MAE is **98 % dynamic load floor**, and the thermal disturbance it was built to exercise
  contributes 0.2 kg of it. No estimator can win there and none does.
- Tracking nonetheless removes most of a **−17.6 kg** frozen-anchor bias, four times over, at
  p_holm < 1e-5.
- It does so **without tracking the thermal cycle at all** — its gain trajectory is further from
  the required one than a constant is, and anti-correlated with it.

An unexplained null in a headline result is a reviewer's first question; this one now has an
answer, and the answer is partly unflattering to the ladder.

---

## Stage C2 — section V-D downgraded

Completed 2026-10-04. Analysis only, over the stored `detector_thresholds` sweep (340 runs, ten
seeds, 20 fault opportunities per arm per scenario).

**The audit's arithmetic is confirmed, and the sweep is weaker than even the audit's reading of
it.** Not one of the twenty-six threshold arms separates from its own ladder's shipped baseline.

### C2a. The specific claim

1 of 20 against 5 of 20 gives **Fisher exact two-sided p = 0.1818** (one-sided 0.0909), exactly
the ≈ 0.18 the audit states. **This is an observation, not a design rule, and must not be
written as one.** No mechanism argument changes a p of 0.18; a mechanism explains an effect that
has been established, and this one has not been.

### C2b. The shape of each ladder — `S4_step_fault`

Sensitivity increases down each block. False alarms are medians over ten seeds.

| detector | knob | caught | of | recall | false alarms/h | alarms |
|---|---|---|---|---|---|---|
| CUSUM | 12.0 (shipped) | 3 | 20 | 0.150 | 0.0625 | 15 |
| CUSUM | 6.0 | 3 | 20 | 0.150 | 0.1250 | 21 |
| CUSUM | 3.0 | 2 | 20 | 0.100 | 0.1875 | 30 |
| CUSUM | 1.5 | 1 | 20 | 0.050 | 0.1875 | 30 |
| Page–Hinkley | 15.0 (shipped) | 1 | 20 | 0.050 | 0.0625 | 9 |
| Page–Hinkley | 7.5 | 5 | 20 | 0.250 | 0.0625 | 17 |
| Page–Hinkley | 3.75 | 5 | 20 | 0.250 | 0.1250 | 25 |
| Page–Hinkley | 1.875 | 1 | 20 | 0.050 | 0.1875 | 30 |
| ADWIN | 0.002 (shipped) | 0 | 20 | 0.000 | 0.0625 | 12 |
| ADWIN | 0.01 | 1 | 20 | 0.050 | 0.0625 | 13 |
| ADWIN | 0.05 | 2 | 20 | 0.100 | 0.0625 | 13 |
| ADWIN | 0.25 | 2 | 20 | 0.100 | 0.0625 | 16 |
| ADWIN | 0.9 | 2 | 20 | 0.100 | 0.1250 | 19 |
| KS | 1e-4 (shipped) | 0 | 20 | 0.000 | 0.0000 | 4 |
| KS | 1e-3 | 0 | 20 | 0.000 | 0.0625 | 7 |
| KS | 1e-2 | 0 | 20 | 0.000 | 0.0625 | 9 |
| KS | 1e-1 | 0 | 20 | 0.000 | 0.0625 | 11 |

**CUSUM declines monotonically: 3, 3, 2, 1. It does not invert.** Calling the CUSUM result an
inversion is wrong and the text must say "declines".

**Page–Hinkley is the only arm that inverts: 1, 5, 5, 1.** ADWIN in fact *rises* monotonically
(0, 1, 2, 2, 2). KS is flat at zero across a thousandfold range of alpha.

The knobs are not inert — the alarm counts and false-alarm rates climb with sensitivity exactly
as they should (CUSUM 15 → 30 alarms, 0.0625 → 0.1875 per hour). What does not climb is
detections.

### C2c. `S6_combined` — every ladder is noise

| detector | sequence (sensitivity increasing) | shape |
|---|---|---|
| CUSUM | 0, 2, 0, 0 | not monotone |
| Page–Hinkley | 0, 0, 2, 0 | not monotone |
| ADWIN | 0, 1, 0, 0, 0 | not monotone |
| KS | 0, 0, 0, 0 | flat |

Maximum 2 of 20 anywhere. There is no curve here to describe in either direction.

### C2d. Nothing separates, anywhere

Fisher exact, each arm against its own ladder's shipped baseline, both scenarios, 26 comparisons:

| scenario | smallest p | which arm |
|---|---|---|
| `S4_step_fault` | **0.1818** | Page–Hinkley 7.5 and 3.75, each 5/20 vs 1/20 |
| `S6_combined` | **0.4872** | CUSUM 6.0 and PH 3.75, each 2/20 vs 0/20 |

Every other comparison is at p ≥ 0.4872, and most are at p = 1.0. Holm over the family of 26
leaves nothing within reach of 0.05 — the smallest corrected value would be 0.1818 × 26 ≈ 4.7,
capped at 1.

**So the sweep's honest summary is: across a thousandfold range on four detectors, no threshold
setting changed detection recall by a statistically distinguishable amount on either scenario,
while false alarms roughly tripled.** The shipped thresholds are not demonstrably better or worse
than any of the alternatives tested. That is a clean negative result and should be reported as
one.

### C2e. The mechanism paragraph, with the corrected arithmetic

The mechanism that section V-D offers for the inversion — that a spurious alarm holds the
controller in `DRIFT_SUSPECTED` and consumes the window a real fault must be caught in — is
arithmetically understated wherever it is quoted at 982 s. From A0.3 and A1, on
`S4_step_fault` at one reference in ten and 220 veh/h:

- confirmation window: 60 residuals × 10 passes ÷ 220 veh/h = **9,818 s**
- detector warm-up ahead of it: 60 references × 10 passes ÷ 220 veh/h = **9,818 s**
- earliest possible recalibration: **19,636 s**, against an 1,800 s fault horizon — **10.9×**

982 s is the figure for one reference in **one**, not one in ten, and even there it is 55 % of
the horizon.

**This mechanism remains a hypothesis.** It is directly tested in C1, and C1 must be read in the
light of C2: it is testing the cause of an effect — the Page–Hinkley inversion — that is itself
only a four-count difference at p = 0.18. The C1 design is paired by seed, which is more
powerful than the unpaired Fisher comparison above, but no outcome of C1 can retrospectively
establish the inversion it was built to explain.

---

## Stage D1 (part 1) — the controller-semantics decision

Decided and implemented 2026-10-04, commit `d520cb6`. The rerun it enables is part 2.

### The defect, stated precisely

`confirmation_passes` counts **residuals**, and a residual exists only when a reference vehicle
crosses. The confirmation window therefore lasts

```
confirmation_passes * reference_every_n / traffic_rate
```

which **scales with the reference supply — the very thing the reference-rate experiment sweeps.**
The controller's own time constant moved with the independent variable. That is worse than the
window merely being long: it means the reference-rate curve confounds two effects that cannot be
separated after the fact, because every point on it ran a differently-tuned controller.

The magnitudes, from A1 (`S4_step_fault`, 220 veh/h, 60 passes, warm-up 60 references):

| reference rate | warm-up | confirmation | earliest recalibration | vs 1,800 s horizon |
|---|---|---|---|---|
| 1 in 1 | 982 s | 982 s | 1,964 s | 1.1× |
| 1 in 10 | 9,818 s | 9,818 s | 19,636 s | **10.9×** |
| 1 in 50 | 49,091 s | 49,091 s | 98,182 s | **54.5×** |

### The mechanism chosen, and why

**A count with a wall-clock cap.** `control.confirmation_max_s`; the window closes at whichever
comes first, the count or the clock, and the decision is taken on the residuals that arrived.

The three candidates, against the two things the window has to do at once — be commensurable with
the horizon, and have enough evidence to decide on:

- **Seconds alone.** Makes the duration right and the statistical power vary with reference rate.
  The project already knows what a decorative gate costs: the `confirmation_passes` field
  documents that at thirty passes a real sensitivity fault was detected five times, confirmed
  never, and left the station reporting itself healthy. Rejected.
- **A residual count derived from the reference rate.** Holds power constant and leaves the
  duration unbounded — which is the present defect restated. Rejected.
- **A count with a time cap.** Full power where references are dense; a bounded window where they
  are sparse. Chosen.

**What makes the truncated decision honest is already in the code.** `_displaced` scales its
threshold by `1/sqrt(n)`:

```
confirm_sigma * 1.2533 * scale / sqrt(n)
```

so a window cut to a third of its residuals automatically demands a displacement `sqrt(3)` larger
to confirm. The cap trades detection power for timeliness, and the gate charges for the trade
instead of hiding it. No second knob, and no risk of the gate quietly becoming decorative.

Below **two** residuals there is no median worth testing, so a window the clock closes that early
returns to MONITORING **undecided**, with a reason that says so, rather than confirming on noise.

**The controller is given seconds, not a fraction of the fault horizon.** The horizon is a scoring
concept that belongs to `experiments/` — `calibration/` must not know how it is being marked, and
it has to cross-deploy to a Pi that has no notion of a sweep. The sweep converts.

**Default is `None`, meaning no cap** — exactly what every sweep before this ran with, so no
stored result changes meaning.

### A process note worth recording

The first launch of the Stage C1 sweep was destroyed by this change: `confirmation_max_s` was
added to `configs/estimators/default.yaml` **while that sweep was running**, and the worker
processes were still holding the previously-imported `config.py`, whose `EdgeConfig` forbids
extra keys. 126 of 136 cells per shard failed with

```
ValidationError: control.confirmation_max_s — Extra inputs are not permitted
```

Nothing was silently corrupted: every failed cell became a row carrying its own error text, which
is exactly what that design decision in `runner._run_one` is for, and the loss was visible in
`failed` the moment the shards were inspected. The shards were discarded and the sweep relaunched
against a committed, frozen tree.

**The rule this establishes: commit first, then run, and change nothing under `configs/` or
`src/` while a sweep is in flight.** A sweep reads its configs per cell but imports its code once,
so the two can disagree halfway through.

---

## Stage F1 (part 1) — the bias/variance decomposition on H1

Completed 2026-10-04. Analysis only, over the stored `heldout30` sweep (30 seeds). The Kalman Q
sweep is part 2.

**The "fixed variance cost" label has the right direction and the wrong size. It is a spread
cost, not a bias cost — but the ablation accounts for one eleventh of it.**

### F1a. The squared-error decomposition is not usable here

`rmse² = bias² + variance` is arithmetically true, but on H1 it describes the tails rather than
the width:

| estimator | RMSE/MAE (median over 30 seeds) |
|---|---|
| `static_affine` | 2.27 |
| `rls` | 2.28 |
| `kalman` | 1.99 |

A normal error distribution gives 1.25. At 2.3 the squared error is dominated by a handful of
passes per run, so a "variance" term read off RMSE is a tail statistic. The decomposition matched
to the metric the claim is stated in — MAE — is the one reported below. The RMSE split is given
afterwards for completeness and disagrees with itself, which is the point.

Note in passing that the Kalman's ratio is the *lowest* of the three: it has relatively lighter
tails and a wider body.

### F1b. The MAE-matched decomposition

Per seed, `MAE = |bias| + (MAE − |bias|)`. Medians over 30 seeds, kg:

| estimator | MAE | \|bias\| | MAE − \|bias\| |
|---|---|---|---|
| `static_affine` | 1124.5 | 139.1 | 983.5 |
| `rls` | 1130.7 | 35.5 | 1090.9 |
| `kalman` | 1366.1 | 57.4 | 1309.8 |

`kalman − static_affine`, paired by seed, exact Wilcoxon, Holm over the family of three:

| term | static | → kalman | difference | signs | p | p_holm |
|---|---|---|---|---|---|---|
| MAE | 1124.5 | 1366.1 | **+251.4** | +30/−0 | 1.9e-09 | 5.6e-09 |
| \|bias\| | 139.1 | 57.4 | **−61.7** | +6/−24 | 2.7e-05 | 2.7e-05 |
| MAE − \|bias\| | 983.5 | 1309.8 | **+323.2** | +30/−0 | 1.9e-09 | 5.6e-09 |

**The +251 kg penalty is +323 kg of spread offset by −62 kg of bias.** The Kalman's zero is
*better* than the static arm's on H1 — by a factor of two and at p_holm = 2.7e-05 — and it pays
for that with width. So the label's direction is supported: this is a spread cost and not a bias
cost, and the text may say so.

The MAE p-values sit at the n=30 attainable floor of 1.9e-09, so those two are resolution-limited
and only the unanimity (30/30) is meaningful. The bias comparison at 2.7e-05 is a measured value.

### F1c. The magnitude is not explained

The ablation that the "fixed variance cost" label rests on measures **+29.3 kg**. The spread term
on H1 is **+323.2 kg** — a factor of **11**, not the eightfold gap the audit estimated from the
MAE figure. Correcting the comparison to the right term made the gap larger, not smaller.

So the position going into part 2 is:

- *that* the H1 penalty is a spread cost: **established**, p_holm = 5.6e-09, 30 of 30 seeds.
- *why it is eleven times the ablation's figure*: **unexplained**.

Part 2 sweeps `process_noise_gain` two decades either side of the shipped 1.0e-11 to test whether
the Kalman's own answer to "how fast may the gain move" accounts for the magnitude. If the
penalty tracks Q, the mechanism is identified. If it does not, the label is removed and the
observation is reported as unexplained — which, on the evidence so far, is the outcome to expect.

### F1d. The same decomposition on the other three held-out scenarios

Reporting only the scenario that fails would be the selective reporting this revision exists to
avoid — and running the same decomposition on all four turns out to say more than H1 alone does.
`kalman − static_affine`, medians over 30 seeds, kg, with exact Wilcoxon p per term:

| scenario | ΔMAE | p | Δ\|bias\| | p | Δspread | p |
|---|---|---|---|---|---|---|
| `H1_warm_front` | **+251.4** | 1.9e-09 | **−61.7** | 2.7e-05 | **+323.2** | 1.9e-09 |
| `H2_gain_jolt` | **−47.4** | 1.9e-09 | **−70.8** | 6.9e-06 | +16.2 | 0.119 |
| `H3_slow_fade` | +28.0 | 0.556 | **−46.1** | 4.2e-04 | **+62.7** | 2.0e-06 |
| `H4_pileup` | −4.0 | 0.529 | **−25.3** | 0.021 | **+42.1** | 9.5e-04 |

**The sign pattern is the same on all four, and it is the real finding here.** The Kalman
improves bias on every held-out scenario (−61.7, −70.8, −46.1, −25.3; separated on all four) and
costs spread on every one (+323.2, +16.2, +62.7, +42.1; separated on three of four). It is
making the same trade everywhere.

What distinguishes H1 is not the *kind* of failure but its size: the spread cost there is five to
twenty times the cost on the other three, while the bias credit is unexceptional. So the question
part 2 has to answer is narrower than "why does the Kalman lose on H1" — it is **why the spread
cost is an order of magnitude larger on H1 than on the other three draws of the same estimator**.

This also disposes of the reading that H1 and H2 are opposite results. They are the same result:
the Kalman buys roughly 60–70 kg of bias in both. H2 looks like a win only because its spread
cost happens to be 16 kg and does not separate.

---
