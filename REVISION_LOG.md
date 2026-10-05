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

## Stage C1 — blocking versus non-blocking: the hypothesis fails

Completed on `S4_step_fault` 2026-10-04. **`S6_combined` was NOT completed — see C1e.**

**Answer: no. Disabling the controller's blocking behaviour does not remove the sensitivity
inversion. The alarms blocking was swallowing were false alarms almost without exception, and the
mechanism section V-D offers for the inversion is not supported.**

### C1a. The sweep, and its internal control

340 runs on `S4_step_fault`: 17 threshold arms × blocking/non-blocking × 10 seeds, zero failures,
every arm at the full 10 seeds. Each `_nb` arm differs from its base in `control.blocking` and in
nothing else, verified field by field on the resolved configs before the sweep ran.

Two checks that the arm did what it was designed to do and only that:

| quantity | identical across the 170 paired cells |
|---|---|
| recalibrations | **170 / 170** |
| MAE | **170 / 170** |
| detections | 167 / 170 |

The non-blocking arm changes which events are *published* and touches no control action — exactly
the isolation the design required, confirmed rather than assumed.

And the blocking arm independently **reproduces the stored `detector_thresholds` sweep**, at a
different commit with different config hashes: CUSUM 3, 3, 2, 1; Page–Hinkley 1, 5, 5, 1; ADWIN
0, 1, 2, 2, 2; KS 0, 0, 0, 0 of 20. That reproduction is what makes the comparison below worth
anything.

### C1b. The shapes, with sensitivity increasing left to right

| detector | arm | recall by sensitivity | shape |
|---|---|---|---|
| CUSUM | blocking | 0.15, 0.15, 0.10, 0.05 | declines |
| CUSUM | **non-blocking** | 0.15, 0.15, 0.15, 0.10 | **still declines** |
| Page–Hinkley | blocking | 0.05, 0.25, 0.25, 0.05 | **inverts** |
| Page–Hinkley | **non-blocking** | 0.05, 0.25, 0.25, 0.10 | **still inverts** |
| ADWIN | blocking | 0.00, 0.05, 0.10, 0.10, 0.10 | rises |
| ADWIN | **non-blocking** | 0.00, 0.05, 0.10, 0.10, 0.10 | **identical** |
| KS | both | 0.00, 0.00, 0.00, 0.00 | flat |

**The non-blocking arm inverts exactly where the blocking arm inverts.** If blocking caused the
inversion, this is the table that would have shown it, and it does not.

### C1c. What unblocking actually bought

Pooled over all 17 arms × 10 seeds on `S4_step_fault`:

| | blocking | non-blocking | change |
|---|---|---|---|
| alarms published | 281 | 560 | **+279** |
| of which false alarms | 253 | 529 | **+276** |
| faults detected (of 340 opportunities) | 28 | 31 | **+3** |
| recall | 0.082 | 0.091 | +0.009 |
| recalibrations | 79 | 79 | 0 |
| median MAE (kg) | 151.70 | 151.70 | 0 |

**Unblocking published 279 more alarms. Three of them were real detections and 276 were false
alarms.** The events the controller was swallowing were, to within one percent, noise.

Paired per arm by seed, 10 seeds, exact Wilcoxon with Holm over the family of 17: **not one arm
separates**, every median difference is 0.0, and most paired cells are exactly equal. The
attainable p at n=10 is 0.00195, which after Holm ×17 is 0.0332 — so a unanimous difference
*would* have been detectable. There is no difference to detect.

### C1d. What this means

The mechanism in section V-D — a spurious alarm holds the controller in `DRIFT_SUSPECTED` and
consumes the window a real fault must be caught in — is **arithmetically real but causally
inert**. The window is as long as A0.3 and A1 say it is, 9,818 s against an 1,800 s horizon, and
the controller genuinely does swallow alarms during it. It is simply not swallowing the alarms
that would have been detections.

So the inversion's cause lies upstream of the controller, in the detectors or in the residual
signal they see. Combined with C2 — where no arm anywhere separated from its baseline, and the
inversion itself is a four-count difference at p = 0.18 — the defensible reading is that **the
Page–Hinkley "inversion" is noise in a 20-opportunity sample, and C1 has now failed to find a
mechanism for it because there may be no effect to explain.**

This is a negative result for the hypothesis and should be reported with the same prominence the
hypothesis was. It also makes the Stage D1 fix a matter of *semantics and comparability* rather
than of recovering lost detections: capping the window still removes a confound from the
reference-rate experiment, but it should not be expected to raise recall, and C1 is the reason to
say so in advance.

### C1e. What was not run, and why

**`S6_combined` was not completed.** The sweep was stopped by a wall-clock limit at 85 of 136
cells per shard. The grid runs scenario-major, so all 68 `S4_step_fault` cells completed at all
10 seeds while `S6_combined` reached 5 seeds on 16 of 17 arms and 3 seeds on the last. Those
partial S6 rows are retained in `data/results/blocking_partial/` and are **excluded from every
figure above**; the fragment is printed in the reduction output marked as incomplete, and no
claim rests on it.

It was not resumed, and the reasons are recorded rather than left implicit:

- C2 established that every S6 detector ladder is noise — maximum 2 of 20 anywhere, every ladder
  non-monotone, smallest Fisher p 0.4872. There is no inversion on S6 for C1 to explain.
- The effect C1 exists to test lives on S4, and S4 is complete at full power.
- Completing S6 costs roughly 3.4 h of machine time, which is the whole remaining budget for
  Stages D1, E1 and F1, none of which had started.

**This is a deliberate omission of a planned cell, declared here and in `OPEN.md`.** If the S6
arm is later wanted, the configuration is committed and `wimsim experiment blocking --scenarios
S6_combined` reproduces it.

---

## Stage E1 — the sparse-rate tuning claim: it stands, and the reason is not the thresholds

Completed 2026-10-04. 160 runs on `S4_step_fault`, 8 arms × 2 rates × 10 seeds, zero failures.

**The claim holds. Across eight configurations spanning each detector's sensitivity range in both
directions, detection at one reference in twenty is 1 of 160 opportunities, and at one in fifty it
is 0 of 160.** The claim may now be stated as evidenced rather than asserted.

But the sweep also found *why*, and the reason is not threshold tuning at all.

### E1a. The result

| rate | best arm | detections | recall | 95 % CI (clustered by seed) | pooled over all 8 arms |
|---|---|---|---|---|---|
| 1 in 20 | ADWIN δ=0.05 | 1 / 20 | 0.050 | [0.000, 0.148] | **1 / 160 = 0.006** |
| 1 in 50 | — (all zero) | 0 / 20 | 0.000 | [0.000, 0.000] | **0 / 160 = 0.000** |

Zero recalibrations at both rates, in every arm. Every Fisher exact test of a tuned arm against
its shipped counterpart at the same rate gives **p = 1.0000** — because every cell is zero.

At one in fifty the detectors barely fire at all: **4 alarms in total across all 80 runs**, and
zero in seven of the eight arms. This is not a detector that alarms and misses; it is a detector
that never speaks.

### E1b. The mechanism — warm-up, not sensitivity

`drift.warmup` is **60 references**, and a reference exists only when a reference vehicle crosses.
So the time at which the detectors become ready scales with `reference_every_n`, exactly as the
confirmation window does:

```
t_ready = warmup * reference_every_n / traffic_rate
```

`S4_step_fault` injects its faults at **t = 14,400 s** and **t = 32,400 s**, each scored over an
1,800 s horizon. Against that:

| rate | t_ready | fault 1 horizon [14400, 16200] | fault 2 horizon [32400, 34200] | **attainable recall** |
|---|---|---|---|---|
| 1 in 10 | 9,818 s | reachable | reachable | **1.00** |
| 1 in 20 | 19,636 s | **closed before ready** | reachable | **0.50** |
| 1 in 50 | 49,091 s | **closed before ready** | **closed before ready** | **0.00** |

**At one reference in fifty the attainable recall on S4 is zero before the experiment runs.** The
detectors are still warming up when the last fault's scoring horizon closes. No threshold can
change that, because warm-up is a count of references and not a threshold — which is precisely
why "no tuning recovers detection" is true, and why it is true for a reason that has nothing to
do with tuning.

### E1c. This contradicts how the stored reference-rate curve has been read — flag at the top

The ceiling is a property of the scenario and the rate, so it applies to **every** reference-rate
sweep already in the export, not only to E1. Checking the stored `reference_rate30` governed arm
against it:

| rate | ceiling | max recall observed in any single run | consistent? |
|---|---|---|---|
| 1, 2, 3, 5 | 1.00 | 1.0 | yes |
| 10 | 1.00 | 0.5 | yes |
| 20 | **0.50** | **0.5** | yes — the ceiling binds exactly |
| 50 | **0.00** | **0.0** | yes — the ceiling binds exactly |

No run anywhere exceeds its ceiling, and at rates 20 and 50 the ceiling is attained exactly. So
the sparse end of the published curve is measuring the detector warm-up, not the feasibility of
self-calibration at a sparse reference supply.

Recomputed among **reachable** faults only, `reference_rate30`, governed arm:

| scenario | rate | reported recall | corrected recall |
|---|---|---|---|
| `S4_step_fault` | 20 | 0.022 | **0.044** |
| `S4_step_fault` | 50 | 0.000 | **undefined — no reachable fault** |
| `S7_sparse_reference` | all | unchanged | unchanged (ceiling 1.00 throughout) |

**"Recall 0.000 at one reference in fifty on S4" must not be reported as a detection result.** It
is a statement that the experiment presented no detectable fault. The honest cell is empty, with
the ceiling given beside it.

`S7_sparse_reference` is unaffected — one fault, late enough that the ceiling is 1.00 at every
rate — and it declines smoothly from 0.933 at one-in-one to 0.067 at one-in-fifty. **S7 is
therefore the scenario that actually measures what the reference-rate experiment claims to
measure, and the S4 sparse points should be withdrawn or re-plotted against the ceiling.**

---

## Stage F1 (part 2) — the Kalman Q sweep: the label is removed

Completed 2026-10-04. 50 runs on `H1_warm_front`, 5 values of `process_noise_gain` × 10 seeds,
zero failures.

### F1e. The control passed

The shipped-Q arm reproduces `heldout30`'s Kalman on H1 at seeds 1–10 to within **2.3e-13 kg** on
MAE and **3.6e-15 kg** on bias — identical. So the cross-sweep pairing against `heldout30`'s
static arm is valid, and as a by-product the determinism guarantee survives the `control.blocking`
and `control.confirmation_max_s` additions intact.

### F1f. The penalty does not behave as a variance cost

`kalman − static_affine` on the same 10 seeds; static reference MAE 1128.3, \|bias\| 117.7,
spread 1038.8 kg:

| `process_noise_gain` | ΔMAE | Δ\|bias\| | Δspread | signs | p |
|---|---|---|---|---|---|
| 1e-13 (stiffest) | **+266.6** | −36.6 | +281.2 | +10/−0 | 0.00195 |
| 1e-12 | +266.0 | −36.5 | +281.8 | +10/−0 | 0.00195 |
| **1e-11 (shipped)** | **+256.8** | −42.4 | +294.6 | +10/−0 | 0.00195 |
| 1e-10 | +243.3 | −43.3 | +249.7 | +10/−0 | 0.00195 |
| 1e-09 (loosest) | **+150.6** | +37.8 | +120.1 | +10/−0 | 0.00195 |

All five are unanimous at ten seeds, so under the pre-registered protocol they are reported at ten
and not escalated. Holm over the family of five puts every one at p_holm = 0.0098.

**The penalty is monotone in Q and runs the wrong way.** The "fixed variance cost" account says
the gain state is free to wander and that this costs variance; it predicts that *stiffening* Q
shrinks the penalty. Stiffening Q by two decades makes the penalty **worse** (+256.8 → +266.6),
and loosening it by two decades makes it **better** (+256.8 → +150.6). Whatever the Kalman is
paying for on H1, it is not a gain state that is too free.

### F1g. And Q does not explain the magnitude either

Across four decades the penalty moves by 116 kg, from +266.6 to +150.6. It never approaches the
ablation's **+29.3 kg**, and at the most favourable Q tested it is still **five times** that
figure and unanimous across all ten seeds.

**So the "fixed variance cost" label is unsupported and is removed.** What survives, and should be
reported in its place:

- The H1 penalty is real, large and unanimous: +251 kg over 30 seeds in `heldout30`, +257 kg over
  10 seeds here.
- It is a **spread** cost, not a bias cost (F1 part 1): the Kalman's zero is in fact better.
- It is **not** explained by the Kalman's own process noise, and the direction of the Q
  dependence rules out the mechanism the label names.
- The Kalman makes the same bias-for-spread trade on all four held-out scenarios; H1 is
  distinguished only by the size of the spread cost.

**The mechanism is unexplained, and that is the honest report.** An unexplained observation
stated as unexplained is more credible than an explanation the evidence contradicts — and here
the evidence does not merely fail to support the label, it points the other way.

---

## Stage C1 (amended) — `S6_combined` completed after all, and it agrees

**This amends the Stage C1 entry above, which states that `S6_combined` was not completed. That
statement was true when written and is now false. The entry is left standing and corrected here,
because this log is append-only and a silently edited record of what was run is worth nothing.**

### How it happened — a process failure worth recording

When a background job is killed, **its worker processes are not killed with it.** The C1 shards
were reported stopped at 85 of 136 cells; in fact five workers kept running for a further four
hours and finished the grid. Two consequences, both mine:

1. Every runtime estimate made after that point was wrong, because roughly half the machine was
   occupied by a sweep believed to be dead. That is why Stages F1, E1 and D1 all ran slower than
   predicted.
2. Relaunching `reference_rate_fixed` while the first set was still alive put **two worker sets
   on the same output directories**, which is why its partial file held 333 rows for a 280-cell
   grid. No result was corrupted — identical `run_id` at identical commit is byte-identical by
   the determinism guarantee, and every duplicate carried the same commit — but half that compute
   was wasted. The older set was stopped and the survivor finalised cleanly.

**The rule, alongside the Stage D1 one: after a job is reported killed, check for surviving
workers before concluding anything about the machine or relaunching into the same directory.**

### The completed result

`blocking` is now **680 runs, 0 failed**: 17 threshold arms × 2 control arms × 2 scenarios × 10
seeds. The isolation checks now cover the whole grid — recalibrations and MAE are identical in
**340 of 340** paired cells.

`S6_combined`, pooled over all 17 arms × 10 seeds:

| | blocking | non-blocking | change |
|---|---|---|---|
| alarms published | 363 | 726 | **+363** |
| of which false alarms | 358 | 721 | +363 |
| faults detected (of 340) | **5** | **5** | **0** |
| recalibrations | 44 | 44 | 0 |
| median MAE (kg) | 658.77 | 658.77 | 0 |

**On S6 the non-blocking arm doubles the alarms and detects exactly nothing more — not one
additional fault in 340 opportunities.** Every S6 ladder has the identical shape in both arms.

### The properly powered test

With 34 arms the per-arm family is underpowered: the attainable p at ten seeds after Holm×34 is
**0.0664**, above 0.05, so no single arm *could* reach significance and the per-arm table should
not be leaned on. Pooling across arms within each scenario gives a family of two, which is
powered (Holm×2 floor = 0.0039):

| scenario | metric | blocking | non-blocking | diff | signs | p | p_holm |
|---|---|---|---|---|---|---|---|
| `S4_step_fault` | false alarms | 253 | 529 | **+276** | +10/−0 | 0.00195 | **0.0078** |
| `S6_combined` | false alarms | 358 | 721 | **+363** | +10/−0 | 0.00195 | **0.0078** |
| `S4_step_fault` | detections | 28 | 31 | +3 | +1/−0 | 1.0 | 1.0 |
| `S6_combined` | detections | 5 | 5 | **0** | +0/−0 | 1.0 | 1.0 |

**Unblocking the controller more than doubles the false-alarm rate, unanimously across all ten
seeds on both scenarios, and does not improve detection on either.** The C1 conclusion stands and
is now carried by the full grid rather than half of it.

---

## Stage D1 (part 2) — the reference-rate rerun with the window capped

Completed 2026-10-04. 280 runs, 0 failed: 7 rates × 2 scenarios × `rls` × 10 seeds × 2 control
arms, with `control.confirmation_max_s = 1800.0`.

### D1d. The question, answered explicitly

> *Was the 39 % miss at the every-vehicle rate caused by false alarms blocking the controller?*

**No.**

| | recall | **miss** | false alarms/h | recalibrations/run |
|---|---|---|---|---|
| stored, uncapped window (15 seeds) | 0.600 | **40.0 %** | 1.0000 | 1.00 |
| rerun, window capped at one horizon (10 seeds) | 0.600 | **40.0 %** | 0.9688 | 1.10 |

The miss rate is unchanged to three figures. The false-alarm rate at one reference in one is
indeed ≈ 1.00/h as the audit noted, and the controller is indeed blocked for 55 % of the horizon
there — but removing that blocking (C1) and shortening it (here) both leave the miss rate exactly
where it was. **The 39–40 % miss at the every-vehicle rate is not a controller-blocking effect.**

This was predicted in advance from C1 and recorded in commit `fe74a0d` before this sweep ran.

### D1e. Recall against reference rate, with the ceiling beside it

Governed arm, 10 seeds, interval clustered by seed rather than treating fault opportunities as
independent:

| scenario | rate | ceiling | recall | 95 % CI | corrected | stored | recals/run |
|---|---|---|---|---|---|---|---|
| S4 | 1 | 1.00 | 0.600 | [0.356, 0.844] | 0.600 | 0.600 | 1.10 |
| S4 | 2 | 1.00 | 0.450 | [0.221, 0.679] | 0.450 | 0.433 | 0.60 |
| S4 | 3 | 1.00 | 0.500 | [0.247, 0.753] | 0.500 | 0.367 | 0.60 |
| S4 | 5 | 1.00 | 0.350 | [0.141, 0.559] | 0.350 | 0.267 | 0.30 |
| S4 | 10 | 1.00 | 0.400 | [0.156, 0.644] | 0.400 | 0.300 | 0.00 |
| S4 | 20 | **0.50** | 0.000 | [0.000, 0.000] | 0.000 | 0.033 | 0.00 |
| S4 | 50 | **0.00** | 0.000 | [0.000, 0.000] | **undefined** | 0.000 | 0.00 |
| S7 | 1 | 1.00 | 0.900 | [0.704, 1.000] | 0.900 | 0.933 | 0.10 |
| S7 | 2 | 1.00 | 0.700 | [0.401, 0.999] | 0.700 | 0.800 | 0.60 |
| S7 | 3 | 1.00 | 0.200 | [0.000, 0.461] | 0.200 | 0.200 | 0.30 |
| S7 | 5 | 1.00 | 0.300 | [0.001, 0.599] | 0.300 | 0.200 | 0.30 |
| S7 | 10 | 1.00 | 0.200 | [0.000, 0.461] | 0.200 | 0.267 | 0.10 |
| S7 | 20 | 1.00 | 0.200 | [0.000, 0.461] | 0.200 | 0.200 | 0.00 |
| S7 | 50 | 1.00 | 0.000 | [0.000, 0.000] | 0.000 | 0.067 | 0.00 |

**The intervals are wide and they overlap almost everywhere.** At ten seeds and one or two faults
per run, a recall point on this curve carries roughly ±0.25. The capped curve sits a little above
the stored one at rates 3, 5 and 10 on S4 and a little below on S7, and **none of those
differences is interpretable** — the two sweeps also differ in seed count (10 against 15), so they
are not paired and no test is offered.

The honest summary of the curve: **recall falls with reference sparsity on both scenarios, and
everything past one reference in ten is at or near zero.** That much survives the intervals.

### D1f. What the cap cost — reported because it is a cost

Capping the window reduces recalibrations on the low-traffic scenario, exactly as the sqrt(n)
gate predicts: a window closed at 1800 s on S4 at one reference in ten holds 11 residuals instead
of 60, so confirmation demands a displacement 2.3× larger.

| S4 rate | recals/run, uncapped | recals/run, capped |
|---|---|---|
| 1 | 1.00 | 1.10 |
| 5 | 0.53 | 0.30 |
| **10** | **0.73** | **0.00** |
| **20** | **0.20** | **0.00** |

On S7 (600 veh/h, so references are dense in *time* even when sparse in *vehicles*) the cap is
roughly neutral.

**So the fix buys commensurability and costs confirmations at sparse rates on low-traffic sites.**
That trade is the direct consequence of the mechanism chosen in part 1, it was visible in the
design arithmetic before the run, and it is the reason the cap is set at one full horizon rather
than half of one.

### D1g. Governance effect: nothing, anywhere

Median of per-seed differences, governed minus ungoverned, at every rate on both scenarios:

**0 of 14 cells separate after Holm.** Most cells are exactly `+0.00 kg` with signs `+0/−0` —
governed and ungoverned produced *identical* MAE in every seed, because with the capped window the
controller never acted at all at those rates. The largest effect anywhere is −0.15 kg on S4 at one
reference in one (p = 0.109).

Reported with the signed bias alongside, as the standing rule requires: `dbias` is likewise
±0.00 kg everywhere except S4 rate 1, at −1.07 kg.

**With a horizon-commensurable confirmation window, governance has no measurable effect on error
at any reference rate tested.** That is a negative result about the controller as configured, and
it belongs beside the headline rather than in a limitation.

---

## Summary of the revision — what changes the abstract, the contributions or the conclusion

Written last, appended last. Every figure here is carried by a stage entry above; nothing new is
asserted in this section. **The manuscript has not been rewritten — this is a report, not a
revision of the narrative.**

### Stages completed

| stage | what it was | status |
|---|---|---|
| A1 | configuration provenance | done — all 14 sweeps hash-verified at their own commits |
| A2 | held-out hygiene | done |
| A3 | floor corrections | done — all seven confirmed |
| B3 | why tracking does not help on S2 | done — 5 plant walks, 3 closed-loop runs, 1 figure |
| C1 | blocking versus non-blocking | done — 680 runs, 0 failed |
| C2 | downgrade section V-D | done — analysis only |
| D1 | fix the window, rerun the reference rate | done — 280 runs, 0 failed |
| E1 | the sparse-rate tuning claim | done — 160 runs, 0 failed |
| F1 | Kalman Q and the bias/variance split | done — 50 runs, 0 failed |

1,170 new runs, **zero failures**. Every new comparison was unanimous in sign at ten seeds, so
under the pre-registered protocol none was escalated to thirty and both-stage reporting never
became due.

### Six results that change what the paper can claim

**1. Section V-D's design rule must be withdrawn, and the mechanism with it.** The observation is
1 of 20 against 5 of 20, Fisher exact **p = 0.1818**. Across all 26 arm-versus-baseline
comparisons in the stored threshold sweep the smallest p is 0.1818 on S4 and 0.4872 on S6 —
nothing separates anywhere. The direct causal test (C1, 680 runs) then **exonerates the proposed
mechanism**: unblocking the controller doubles the alarms, unanimously at p_holm = 0.0078, and
improves detection by 3 of 680 on S4 and 0 of 340 on S6. The honest reading is that the
Page–Hinkley "inversion" is noise in a 20-opportunity sample. CUSUM must also be described as
**declining monotonically** (3, 3, 2, 1), not inverting.

**2. The sparse end of the reference-rate curve measures the detector warm-up, not reference
availability.** `drift.warmup` is 60 *references*, so readiness scales with `reference_every_n`.
On `S4_step_fault` the attainable recall is **0.50 at one reference in twenty and 0.00 at one in
fifty** — faults whose 1,800 s horizons close before the detectors are ready. Checked against the
stored `reference_rate30`: no run anywhere exceeds its ceiling and at both sparse rates the
ceiling binds exactly. **"Recall 0.000 at one in fifty on S4" is not a detection result** and must
not be reported as one. `S7_sparse_reference` has a ceiling of 1.00 throughout and is the
scenario that measures what the experiment claims to.

**3. Governance has no measurable effect on error at any reference rate.** With a
horizon-commensurable confirmation window, **0 of 14 rate × scenario cells separate** after Holm,
and most are exactly 0.00 kg with per-seed signs +0/−0 because the controller never acted. This
belongs beside the headline, not in a limitations paragraph.

**4. "Fixed variance cost" is unsupported and is removed.** The H1 penalty is genuinely a spread
cost and not a bias cost — the Kalman's zero is *twice as good* as the static arm's — but the
dependence on `process_noise_gain` **runs the wrong way**: stiffening Q two decades makes the
penalty worse, loosening it two decades makes it better. Across four decades it never approaches
the ablation's +29.3 kg. The observation stands and is reported as **unexplained**. The Kalman
makes the same bias-for-spread trade on all four held-out scenarios; H1 differs only in size.

**5. The section III-B correction is narrower than the audit stated.** No run exercises the
*upstream, fixed-coefficient* temperature compensation — verified four ways. But `theta2` does fit
the III-B interaction term online and is reported, so III-B describes a map that **was** tested.
Conflating the two would replace one wrong sentence with another.

**6. Tracking does help on `S2_thermal_cycle` — in bias, not in error.** S2's MAE is 98 % dynamic
load floor and the thermal disturbance contributes 0.2 kg of it, so no estimator can win there.
But absolute bias falls **23.7 → 5.7 kg** for RLS and 23.7 → 5.6 for Kalman, both at p_holm below
1e-5. The mechanism is the bootstrap anchor: `static_affine` is fitted in the first 20 minutes and
frozen for three days, and on seed 1 that window sits 7 °C below the run median. And the
uncomfortable half: both adaptive arms sit four to five times *further* from the required gain
trajectory than a constant does, and are anti-correlated with it.

### Two corrections to the audit's own premises

- **`ladder30`, `cintron_ladder30`, `heldout30` and `ablation` all ran with the controller active
  and acting** — 117 recalibrations in `ladder30` alone. The "do not rerun" exemption rests on the
  claim that the controller was not an axis, which is true but is not the same statement. Of the
  five sweeps listed as unaffected, only `theta2` is. Nothing was rerun, but the exemption cannot
  stand on that reason.
- **The confirmation window is twice as long as stated.** `drift.warmup` is also 60 references and
  runs first, so the earliest possible recalibration on S4 at one reference in ten is **19,636 s**,
  10.9× the fault horizon, not 5.5×.

### What was not done

- **Part C (hardware):** `BLOCKED — no hardware`. Not simulated, not estimated.
- **Part D (gated):** not started; no confirmation was given.
- `S6_combined` in E1, and the estimator × rate interaction in D1 — both trimmed deliberately,
  with reasons recorded in the configs and in `OPEN.md`.
- The ablation that would settle B3's anti-correlation reading (S2 with the thermal zero coupling
  disabled) has not been run.

---

## Paper figures and the two computations

For the narrowed paper. Nine figures at 300 dpi from `scripts/paper_figures.py`, each with a
sidecar entry in `export/figures/FIGURES.md` and a CSV of the plotted numbers in `export/data/`.
No new runs: everything here is a reduction of stored results.

### Verification of the three numbers the draft carries

**All three are correct as stated. Nothing needs changing.**

| claim | drafted | measured | verdict |
|---|---|---|---|
| S2 is "98 % dynamic load floor" | 98 % | floor 136.09 / frozen MAE 138.82 = **98.0 %** | correct |
| "the thermal disturbance contributes 0.2 kg" | 0.2 kg | **0.23 kg** in quadrature | correct |
| S6 frozen above floor | 505.7 kg | **505.77 kg** | correct |
| S6 best tracked above floor | ~475 kg | **474.59 kg** (rls) | correct |
| S6 recovery | ~6 % | **6.2 %** | correct |
| S2 bias, frozen → rls | 23.7 → 5.7 kg | **23.67 → 5.74 kg** | correct |
| S2 bias, frozen → kalman | 23.7 → 5.6 kg | **23.67 → 5.62 kg** | correct |
| S2 bias p_holm | < 1e-5 | **7.7e-07** and **2.0e-06** | correct |

One qualification worth carrying into the text, because the two numbers are easy to conflate:
the thermal disturbance contributes **0.23 kg** of a frozen excess that is itself only
**2.73 kg**. So thermal explains about **8 %** of S2's already negligible recoverable excess, and
"98 % floor" and "thermal contributes 0.2 kg" are consistent but describe different denominators.

Separately verified for F7, and also correct: the commissioning window is **20.0 minutes**
(60 calibration passes at 180 veh/h) and its mean sensor temperature is **7.53 °C** against a run
median of **14.59 °C** — **7.05 °C below**. The draft's "~20 minutes" and "7 °C" both stand.

### C-a. Relative accuracy — the [X] in §V-B

Median MAE over 30 seeds as a percentage of **mean gross vehicle weight**. Both denominators are
given because they differ by a factor of four and the choice is not neutral: the simulated fleet
has a median mass of 1 555 kg and is car-dominated, while WiM accuracy classes are written for
trucks.

| scenario | mean GVW (kg) | frozen kg | rls kg | kalman kg | frozen % | rls % | kalman % |
|---|---|---|---|---|---|---|---|
| S1_nominal | 6 075 | 0.94 | 0.94 | 0.95 | 0.016 | 0.015 | 0.016 |
| S2_thermal_cycle | 6 283 | 138.82 | 138.10 | 139.19 | 2.210 | 2.198 | 2.215 |
| S3_zero_drift_walk | 6 242 | 139.18 | 138.21 | 139.60 | 2.230 | 2.214 | 2.236 |
| S4_step_fault | 6 192 | 182.39 | 154.37 | 151.49 | **2.945** | 2.493 | **2.447** |
| S5_outage | 6 075 | 138.88 | 138.18 | 143.10 | 2.286 | 2.275 | 2.356 |
| S6_combined | 6 228 | 696.94 | 665.75 | 707.32 | 11.190 | 10.689 | 11.357 |
| S7_sparse_reference | 6 202 | 179.04 | 162.10 | 162.98 | 2.887 | 2.614 | 2.628 |

Against the ≥3.5 t subset (mean ≈24 700 kg) every percentage falls by about a factor of four —
S4 frozen 0.738 %, S6 frozen 2.814 %. Full table in `export/data/F12_relative_accuracy.csv`.

**The S4 improvement, in the terms §V-B asks for:**

- absolute **182.4 → 151.5 kg**, a reduction of **30.9 kg** or **16.9 % relative**
- as a share of mean fleet GVW: **2.95 % → 2.45 %**, i.e. **0.50 percentage points**
- as a share of mean truck GVW: **0.738 % → 0.613 %**, i.e. **0.125 percentage points**

The best tracked arm on S4 is `kalman` (151.5 kg) rather than `rls` (154.4 kg).

### C-b. Table I parameter values

Resolved through `runner._edge_for` **in a worktree at `ladder30`'s own commit `a2c70f37`**, not
from today's defaults. The three resolved `edge_config_hash` values match the three recorded in
`data/results/ladder30/results.parquet` exactly, which is what makes these the values actually in
force:

| | value | hash-verified |
|---|---|---|
| λ, RLS forgetting factor | **0.99** | yes |
| R, Kalman measurement noise | **1.0 × 10⁻⁸** (sensor units²) | yes |
| Q₀₀, Kalman process noise, zero line | **1.0 × 10⁻⁷** | yes |
| Q₁₁, Kalman process noise, gain | **1.0 × 10⁻¹¹** | yes |
| τ_th, ambient → sensor-body lag | **1 800 s** | yes |
| probe lag behind sensor body | **120 s** | yes |
| α₀, nominal thermal coefficient | **−2.0 × 10⁻⁴ /°C** | yes |
| coverage target | 0.95 | yes |
| bootstrap passes | 50 (overridden to 60 by the sweep's `calibration_passes`) | yes |

`edge_config_hash`: `535f10e6…` static_affine, `f54c1734…` rls, `2dcdf942…` kalman.

**Q₀₀ and Q₁₁ are standard deviations per second, not variances.** The filter squares them
internally (`q_rate = Q²`), so a table that prints them as variances would be wrong by a square.

**There is no "covariance trace bound" in the code, and the draft's `[X]` for it cannot be
filled as written.** What actually bounds the covariance is two different things, and the text
should name whichever it meant:

- the **initial** covariance `P₀ = diag(1.0², 0.01²)`, given as standard deviations; and
- `max_gap_s = 3 600 s`, which caps the time increment used to propagate process noise, so an
  arbitrarily long gap between passes cannot inflate the covariance without limit.

Neither is a bound on the trace. If the manuscript needs a single number here, `max_gap_s` is the
one doing the work the sentence describes.

### What could not be produced from stored data

**One item.** F12 normalises an all-vehicle MAE by an all-vehicle mean GVW. A **truck-only** MAE —
error computed over vehicles ≥3.5 t, which is the population COST 323 is written for — needs
per-event errors, and the export carries per-run aggregates only. Both denominators are reported
against the same all-vehicle MAE, and the figure says so on its face.

---

## Phase 1 — confirmed decisions A–C, and items 1.1–1.7

Run order as instructed: 1.2, then 1.3, then the rest. Every new comparison family runs under the
seed protocol at the top of this log.

### Decision A applied — the median of paired differences, everywhere

`scripts/paper_figures.py` F2 now computes the tracked excess as *frozen excess + median over seeds
of (tracked − frozen)*, and the recovered share as −(median paired difference) / frozen excess. The
best tracked arm is the one with the more negative median paired difference. `F2_decomposition.csv`
is regenerated and gains two columns, `reducible_share_pct` = frozen excess / (floor + frozen
excess) and `median_paired_diff_kg`. No other export file changed.

| scenario | arm | median paired Δ (kg) | recovered, was (diff. of medians) | recovered, now |
|---|---|---:|---:|---:|
| S1 | rls | +0.00 | 0.4 % | **−0.1 %** |
| S2 | rls | −0.80 | 26.3 % | 29.2 % |
| S3 | rls | −0.89 | 28.0 % | 25.9 % |
| S4 | kalman | −31.61 | 67.1 % | 68.7 % |
| S5 | rls | −0.81 | 26.7 % | 30.7 % |
| S6 | rls | −32.74 | 6.2 % | **6.5 %** |
| S7 | **kalman** (was rls) | −14.18 | 81.8 % | 68.4 % |

Three things the brief did not already list:

- **S1 under decision A recovers −0.1 %, not 0.4 %.** The 0.4 % in decision B is a
  difference-of-medians figure. On the paired basis the median difference is +0.003 kg: adaptation
  recovers nothing, marginally less than nothing. Decision B's point stands and is sharper.
- **S7's best tracked arm changes from RLS to Kalman** (−14.18 kg against −14.10 kg). The two are
  0.08 kg apart and the choice is immaterial to the share (68.4 % against 68.0 %), but the
  `best_tracked_arm` column changes.
- S2, S3 and S5 move by 2–4 points each; all three remain below a third.

S6/RLS on the paired basis: **−32.7 kg, 6.5 %**.

## Item 1.2 — the Kalman observation noise, corrected

### 1.2a. R, derived from the station's own scale

`scripts/derive_kalman_r.py`; output in `data/results/revision_p1/R_default.json`.

R is the variance of the observation `z` (feature units) about `q + k·m_static`. Its irreducible
part is the dynamic load, `k²·E[(m_applied − m_static)²]`. Each factor is measured:

| quantity | value | source |
|---|---|---|
| `E[(m_applied − m_static)²]` | **7.276 × 10⁴ kg²** (rms **269.7 kg**) | every vehicle `schedule_passes` draws on S2–S5, seeds 1–10, 227 k vehicles |
| mean \|m_applied − m_static\| | 134.3–136.4 kg by scenario | same — agrees with the `dynamic_floor_kg` the scorer reports |
| `k` | **2.0079 × 10⁻⁴ /kg** (six fits, 2.0034–2.0140) | the Kalman arm's own commissioning seed fit, S4 and S5, seeds 1–3 |
| **R** | **2.933 × 10⁻³ feature units²** | product |
| commissioning batch residual variance | 2.1–3.7 × 10⁻³ | same six fits — the total the data itself shows; consistent |

**The audit's conversion is confirmed for k and corrected for σ.** k = 2.0 × 10⁻⁴ per kg holds to
0.4 %. But the floor is 136 kg as an **MAE** and 270 kg as an **rms**: the dynamic error is
proportional to mass, the fleet is heavy-tailed, and the squares are dominated by trucks. Against
an rms of 270 kg, the shipped R = 1 × 10⁻⁸ (σ = 0.50 kg) is overconfident by **≈ 540× in standard
deviation**, 2.9 × 10⁵ in variance — not 270×.

**One R per station, applied to all scenarios** (confirmed with the author). H1–H4 did not inform
it. A constant R remains a misspecification of a noise whose standard deviation grows with mass;
that is recorded, not fixed — the filter's model has one R.

**Q unchanged** (confirmed with the author). Adaptation speed is governed by Q/R, so raising R by
2.9 × 10⁵ at fixed Q also makes the filter adapt more slowly. The 1.2 comparison therefore cannot
separate "correctly specified noise" from "stiffer filter"; it answers the question as asked.

### 1.2b. The control arms reproduce the stored sweeps exactly — and were stopped

`p1_r_dev`, `p1_r_held`, `p1_r_cin` rerun static and shipped-R Kalman at seeds 1–10, each with its
original sweep's Page-Hinkley pin, at commit `2e8c788`, clean tree. On the first **55 rows** they
matched `ladder30`, `heldout30` and `cintron_ladder30` to **max |Δ MAE| = 1.8 × 10⁻¹⁵ kg** — every
row, all three families.

They were then stopped. Rerunning 305 more cells to reproduce numbers already shown to reproduce
bit for bit buys nothing; the corrected-R arm is paired against the stored arms at seeds 1–10
instead (`p1_compare.py export:<sweep>:<arm>`, with `--allow-cross-commit` and this entry as the
reason). The partial rows stay in `data/results/p1_r_*/rows.partial.jsonl` as the evidence.

### 1.2c. The corrected-R arm

`p1_r_dev_floor` (S1–S7) and `p1_r_held_floor` (H1–H4), kalman at `kr_floor`, ten seeds, five seed
shards each, commit `93fd0ac`, clean tree. The transfer arm follows once the influence-line
station's R is derived.

**The influence-line station** (`R_cintron.json`): the same vehicles, so the same
`E[(m_applied − m_static)²]`; `k = 1.4459 × 10⁻⁵ /kg`; **R = 1.521 × 10⁻⁵**. The shipped R there is
σ = 6.9 kg — overconfident by ≈ 39× in standard deviation rather than 540×. **The two stations
were misspecified by very different amounts**, fourteen-fold apart, which any reading of the
transfer comparison (F9) under the shipped R has to allow for. `kr_floor_cintron`; transfer arm
`p1_r_cin_floor`, five seed shards.
