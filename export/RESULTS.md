# Results

Self-contained. Every number here came from a stored parquet under `data/results/`; per-seed values
are in `export/data/*.csv`. Nothing is estimated, interpolated, or carried over from an earlier run.

**Provenance.** `ladder` and `reference_rate`: commit `c1881d4f`, **clean tree**. `governance`
(S6 B2 comparison): commit `f40ca518` with an **uncommitted tree** — the uncommitted files were
`export/*`, `scripts/build_export.py` and `configs/experiments/governance.yaml`, and
`git diff f40ca51 -- src/ configs/estimators/ configs/stations/ configs/scenarios/` is empty, so the
simulation code that produced those numbers is exactly `f40ca51`. Station
`configs/stations/default.yaml` (contact-force), edge config `configs/estimators/default.yaml`,
seeds **1, 2, 3**. Real-data results: commit `f40ca51`, station `cintron_platform`, edge config
`cintron_platform`. Config hashes per run are in `export/data/manifest.json`.

**Which Page-Hinkley threshold each sweep ran at.** The shipped default was **15.0** for every
sweep in this export except the two named below, and moved to **7.5** afterwards, on the strength of
`detector_thresholds`. Nothing has been retrospectively re-run: the threshold curve is itself a
result, and re-running everything at one corrected point would hide how it was found. So this table
is not a footnote — it is part of the definition of every detection number here.

| sweep | Page-Hinkley threshold as run | note |
| --- | --- | --- |
| `ladder`, `ladder30` | 15.0 | inherited from the shipped default of the day |
| `reference_rate` | 15.0 | the governed-vs-ungoverned comparison |
| `reference_rate_ph75` | **7.5** | the same sweep at the corrected threshold |
| `governance` | 15.0 | |
| `cintron_ladder` (3 seeds) | 15.0 | |
| `cintron_ladder30` | **15.0, pinned explicitly** | held at the old value so the seed count is the only difference from `ladder30` |
| `theta2` | 15.0 | control disabled; detection scored but never acted on |
| `recal_coverage` | 15.0 | `confirm_sigma` is the swept knob, not the detector threshold |
| `detectors` | 15.0 | the Page-Hinkley arm; the CUSUM, ADWIN and KS arms do not run Page-Hinkley at all |
| `detector_thresholds` | 15.0, 7.5, 3.75, 1.875 | the sweep that found the correction |
| `reference_rate30` | **7.5, pinned explicitly** | the powered rate ladder; pinned so the shipped default moving again cannot change what the file means |
| `heldout30` | **7.5, pinned explicitly** | the shipped value. `ladder30`, whose comparisons it tests, ran at 15.0 -- the one difference between them, named in the config |
| `ablation` | **15.0, pinned explicitly** | held at the old value so its `S6_combined` arm is a ten-seed replicate of `cintron_ladder30`'s S6 cell |

**A reproducibility hazard this creates, stated plainly.** The experiment configs for the sweeps
above still say `edge_config: default`, and that default now resolves to 7.5. **Re-running them today
will not reproduce their stored numbers.** The mismatch is detectable rather than silent — every row
carries `edge_config_hash`, and it will differ — but a reader who re-runs `ladder30` and compares
against this document must expect different detection figures. `configs/estimators/detect_ph.yaml` is
pinned at 15.0 for the same reason: left inherited it would now equal `detect_ph_h7p5` and collapse
the threshold ladder's baseline into its own first step.

**Dispersion.** Median with [Q1, Q3] throughout, over whatever seeds the sweep ran. **The seed
count is not uniform and the sections are not interchangeable**, so it is stated at the head of
each:

| seeds | sweeps |
| ---: | --- |
| 30 | `ladder30`, `cintron_ladder30`, `theta2`, `heldout30` |
| 15 | `reference_rate30` |
| 10 | `detectors`, `detector_thresholds`, `recal_coverage`, `ablation` |
| 3 | `ladder`, `cintron_ladder`, `governance`, `reference_rate`, `reference_rate_ph75` |

**With n = 3 nothing can reach significance**: the smallest attainable two-sided Wilcoxon p is
0.25. Those five sweeps are descriptive and are labelled as such wherever they are quoted. At
n = 10 the floor is 0.00195, at n = 15 it is 6.1e-5 and at n = 30 below 1e-8, so every sweep above
three seeds can clear Holm correction. Where a powered sweep and a three-seed sweep disagree, **the
powered one is the result and the disagreement is reported as a finding** -- see A1 against B1
below, where two three-seed statements do not survive.

---

## Five sweeps added 2026-09-23, and what each settled

Commit `a2c70f37`, clean tree. Full per-seed values in `export/data/*_long.csv`; paired tests in
`*__comparisons.md`.

### 1. Thirty seeds and the first significance tests — `ladder30`

630 runs, 30 seeds, **none failed**, same grid as `ladder`. Run as three 10-seed shards and merged
by `wimsim.experiments.merge`, which refuses shards differing in anything but the seed. 37
core-hours.

| comparison | n | median A kg | median B kg | median diff | effect | p | p (Holm) | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S1_nominal / static_affine->kalman | 30 | 0.944 | 0.951 | +0.00673 | +0.47 | 0.0248 | 0.198 | not separated |
| S1_nominal / static_affine->rls | 30 | 0.944 | 0.94 | +0.001 | +0.05 | 0.808 | 1 | not separated |
| S2_thermal_cycle / static_affine->kalman | 30 | 139 | 139 | +0.629 | +0.15 | 0.477 | 1 | not separated |
| S2_thermal_cycle / static_affine->rls | 30 | 139 | 138 | -0.798 | -0.45 | 0.0293 | 0.198 | not separated |
| S3_zero_drift_walk / static_affine->kalman | 30 | 139 | 140 | +0.759 | +0.08 | 0.715 | 1 | not separated |
| S3_zero_drift_walk / static_affine->rls | 30 | 139 | 138 | -0.892 | -0.50 | 0.0155 | 0.139 | not separated |
| S4_step_fault / static_affine->kalman | 30 | 182 | 151 | -31.6 | -1.00 | 1.86e-09 | 2.61e-08 | better |
| S4_step_fault / static_affine->rls | 30 | 182 | 154 | -27.1 | -1.00 | 1.86e-09 | 2.61e-08 | better |
| S5_outage / static_affine->kalman | 30 | 139 | 143 | +0.701 | +0.29 | 0.164 | 0.657 | not separated |
| S5_outage / static_affine->rls | 30 | 139 | 138 | -0.811 | -0.42 | 0.0473 | 0.236 | not separated |
| S6_combined / static_affine->kalman | 30 | 697 | 707 | +12 | +0.46 | 0.0277 | 0.198 | not separated |
| S6_combined / static_affine->rls | 30 | 697 | 666 | -32.7 | -1.00 | 1.86e-09 | 2.61e-08 | better |
| S7_sparse_reference / static_affine->kalman | 30 | 179 | 163 | -14.2 | -0.97 | 3.54e-08 | 3.54e-07 | better |
| S7_sparse_reference / static_affine->rls | 30 | 179 | 162 | -14.1 | -1.00 | 1.86e-09 | 2.61e-08 | better |

**Five of fourteen survive Holm, all with effect sizes −0.97 to −1.00** — every seed moving the same
way. Adaptation wins where the plant moves (S4, S6, S7) and nowhere else. **Five more have a raw p
below 0.05 and none survives**; reported per-scenario they would have been findings. Where nothing
survives, the differences are under 1 kg against MAEs of 139–697 kg.

### 2. The scorable scenarios on the real instrument — `cintron_ladder`

63 runs, none failed, on `cintron_sim`: influence-line response, the measured influence length and
the estimated sensitivity, at 500 Hz. **This required correcting `k0`, which was wrong by a factor
of 1000** (see CONTRADICTIONS.md). The first attempt at this sweep failed all 63 runs with "0 events
detected".

| | default station | ST-CINTRON-1 |
| --- | ---: | ---: |
| S1 (no dynamic load) MAE | 0.97 kg | **12.0–12.4 kg** |
| all other scenarios | — | +6 % to +14 % |
| MAE / dynamic floor, median | 1.02 | **1.13** |
| coverage, median (nominal 0.95) | 0.95 | **0.947** |

The 12× on S1 against a sensitivity ratio of 13.9× is the model agreeing with itself. Everywhere
else the dynamic load floor dominates and the instrument barely matters. **Coverage holds within a
point of nominal on an instrument the conformal interval was not tuned on.**

*Not a sensor effect:* S6's 0.53 match rate is 0.531 on the default station and 0.533 here — S6's
clock skew breaking timestamp matching, on both.

### 3. Four detectors, one at a time — `detectors`

100 runs, ten seeds, none failed. **Median detection recall 0.000 in every cell.** The four-way
ensemble produces numbers identical to CUSUM alone. False alarms 0.00–0.06/h. Full table in
`detectors__detectors.md`; detail in CONTRADICTIONS.md §IV-G.

### 4. Does the third parameter earn its place? — `theta2`

180 runs, 30 seeds. **23 of 90 `affine_temp` runs produced no calibration at all**, failing the
non-positive-gain guard with fitted gains from −246 to −34,800; 9 of 30 on S2, 14 of 30 on S6, 0 of
30 on the flat-temperature control.

| scenario | static_affine | affine_temp | MAE / floor |
| --- | ---: | ---: | --- |
| S2_thermal_cycle | 138.8 kg [137.5, 142.7] | **4405.3 kg** [1008.9, 9844.6] | 1.02 → **32.4** |
| S3_zero_drift_walk | 138.9 kg [134.0, 144.5] | 150.5 kg [143.4, 162.0] | 1.02 → 1.11 |
| S6_combined | 722.3 kg [690.5, 760.4] | **2934.7 kg** [1909.6, 6213.4] | 3.78 → **15.4** |

Worse on all three after Holm (p = 1.9e-6, 2.8e-8, 3.1e-5; effect +1.00), and those tests are biased
*in its favour* because the 23 worst runs cannot be paired. **Why:** the interaction is identifiable
only as far as ΔT varies across the 60 references the fit sees — about three hours of a daily cycle.
Measured, S2 moves **2.59 °C inside the calibration window against 19.00 °C over the run**, a ratio
of 0.136. **This tests a batch-fitted third parameter, not §III-B's online-identified one**, and
online identification is exactly what would fix that lever arm.

### 5. What a recalibration costs the interval — `recal_coverage`

300 runs, `confirm_sigma` swept 1.5 → 6.0, ten seeds, none failed. Its own figure,
`recal_coverage__recal_tradeoff.png`.

- **The mechanism is real and sized:** 187 fallback events per recalibration on a 122-event
  intercept. Two recalibrations put 14.5 % of a run's events on the estimator's own band.
- **The cost it was supposed to carry is gone.** Coverage over only the events that got the
  *configured* interval is indistinguishable from coverage over all of them — 0.9353 vs 0.9343 at
  zero recalibrations, 0.9178 vs 0.9185 at one. The premise dated from when the Kalman analytic
  fallback ran at 0.0065 coverage; replacing it removed the cost.
- **The residual association is confounded** — recalibrations happen *because* a fault occurred.
  Compared arm to arm at fixed scenario, estimator and seed, nothing survives Holm on either metric,
  and the largest effect has recalibration improving **both** (S6/static_affine: −45.7 kg and
  +0.011 coverage).
- **The knob barely moves the system:** in 24 of 60 seed-cells, `confirm_sigma` 1.5 and 6.0 gave a
  byte-identical MAE, and the sweep only ever produced 0, 1 or 2 recalibrations in a run.

---

### 6. Spending the false-alarm budget — `detector_thresholds`

340 runs, seventeen arms, ten seeds, none failed, 21.8 core-hours. Commit `b675c9d5`. Figure
`detector_thresholds__detector_curve.png`; full table `detector_thresholds__detectors.md`.

| | shipped | best arm | most sensitive arm |
| --- | --- | --- | --- |
| S4 Page–Hinkley recall | 1/20 (0.05) | **5/20 (0.25)** at half the threshold | 1/20 (0.05) at an eighth |
| S4 false alarms/h | 0.062 | **0.062** — unchanged | 0.188 |
| S4 CUSUM recall | 3/20 (0.15) | 3/20 (0.15) at half | 1/20 (0.05) at an eighth |
| S6 best recall, any arm | 0/20 | **2/20 (0.10)** | 0/20 |

- **Halving Page–Hinkley's threshold multiplies S4 recall by five at an identical false-alarm rate.**
  Free, and the most actionable number here.
- **Past the optimum, sensitivity makes detection worse** — an inverted U, not what a threshold sweep
  should produce. Cause: `drift_detected` is emitted only from the MONITORING state, and an alarm
  holds the controller in DRIFT_SUSPECTED for `confirmation_passes = 60` residuals, which is **982 s
  at S4's 220 vehicles/h — 55 % of the 1800 s fault horizon**. Verified on seed 1: the most sensitive
  arm alarms 1239 s *before* the second fault and misses it. `confirmation_passes` is sized in
  vehicles and the horizon in seconds, and the two were never set against each other.
- **No arm reaches usable recall**: 0.25 on S4, 0.10 on S6.
- **The budget goes unspent because the detectors will not spend it.** At 8× sensitivity CUSUM only
  reaches 0.188 false alarms/h. The residual stream is quiet; a threshold cannot manufacture evidence
  that is not in it, which points at the reference rate.
- **Windowed KS detects nothing at any alpha** (0/20 both scenarios, across 1000× in `ks_alpha`);
  **ADWIN's `delta` is logarithmically weak** (450× moves its cut threshold about a third).

---

## Two reruns, 2026-09-24 — the last runs before Sections VI–VIII

Commit `f10cbd83` (cintron_ladder30) and `6523c7de` (reference_rate_ph75). Both merged from seed
shards; neither had a failed run.

### 7. The influence-line ladder at thirty seeds — `cintron_ladder30`

630 runs, 30 seeds, 35.6 core-hours. **Page-Hinkley pinned at 15.0**, the pre-correction value, so
the seed count is the only difference from `ladder30`. Median per-seed MAE difference in kg,
`static_affine` against the named estimator; ★ = significant at 0.05 after Holm within that run's
own family of fourteen.

| comparison | contact-force 30 seeds | influence-line 3 seeds | influence-line 30 seeds | p (Holm) |
| --- | ---: | ---: | ---: | ---: |
| S1_nominal / static_affine->kalman | +0.01 | -0.10 | +0.03 | 1 |
| S1_nominal / static_affine->rls | +0.00 | -0.14 | -0.04 | 0.261 |
| S2_thermal_cycle / static_affine->kalman | +0.63 | +1.24 | +0.48 | 1 |
| S2_thermal_cycle / static_affine->rls | -0.80 | -0.35 | -1.07 ★ | 0.03 |
| S3_zero_drift_walk / static_affine->kalman | +0.76 | +1.68 | +1.09 | 1 |
| S3_zero_drift_walk / static_affine->rls | -0.89 | +0.56 | -0.69 | 0.207 |
| S4_step_fault / static_affine->kalman | -31.61 ★ | -36.11 | -33.17 ★ | 2.61e-08 |
| S4_step_fault / static_affine->rls | -27.09 ★ | -33.76 | -31.83 ★ | 2.61e-08 |
| S5_outage / static_affine->kalman | +0.70 | +2.22 | +0.95 | 1 |
| S5_outage / static_affine->rls | -0.81 | -1.01 | -1.08 | 0.115 |
| S6_combined / static_affine->kalman | +12.05 | -13.66 | +9.60 ★ | 0.0269 |
| S6_combined / static_affine->rls | -32.74 ★ | -29.46 | -30.69 ★ | 2.61e-08 |
| S7_sparse_reference / static_affine->kalman | -14.18 ★ | -23.69 | -18.06 ★ | 3.73e-08 |
| S7_sparse_reference / static_affine->rls | -14.10 ★ | -23.53 | -18.20 ★ | 2.61e-08 |

**The transfer holds.** All five of `ladder30`'s significant effects reproduce on the real
instrument's physics at comparable magnitude and an identical effect size of −1.00: S4 kalman −33.2
(was −31.6), S4 rls −31.8 (−27.1), S6 rls −30.7 (−32.7), S7 kalman −18.1 (−14.2), S7 rls −18.2
(−14.1). Adaptation wins where the plant moves, on both instruments, at power.

**Two comparisons separate here that did not on the contact-force station** — 7 of 14 against 5:

- `S2_thermal_cycle` / rls, **−1.07 kg**, p_holm 0.030, effect −0.59. Real and negligible: 0.7 % of a
  152 kg MAE.
- `S6_combined` / kalman, **+9.60 kg WORSE**, p_holm 0.027, effect +0.60. On this instrument Kalman
  is significantly worse than the frozen baseline on the combined-fault scenario. The same cell on
  the contact-force station was +12.05 kg and did not reach significance.

**The three-seed run overstated what it found, and one cell had the wrong sign.** S4 −36.1/−33.8
became −33.2/−31.8; S7 −23.7/−23.5 became −18.1/−18.2, about 23 % smaller. And `S6_combined` /
kalman was −13.66 kg at three seeds — kalman apparently helping — against +9.60 and significantly
*worse* at thirty. Three seeds were not merely underpowered there; they pointed the wrong way.

### 8. Governance at the corrected threshold — `reference_rate_ph75`

180 runs, identical to `reference_rate` except Page-Hinkley at **7.5** instead of 15.0. Controller
on, both scenarios pooled, medians over three seeds:

| | Page-Hinkley 15.0 | Page-Hinkley 7.5 |
| --- | ---: | ---: |
| alarms raised | 207 | **382** (+85 %) |
| recalibrations completed | 20 | **40** (×2) |
| detection recall | 31/135 = 0.23 | 39/135 = 0.29 |
| median MAE, controller on | 159.34 kg | **159.50 kg** (+0.16) |
| median MAE difference, loop on − off | **+0.000 kg** | **+0.000 kg** |
| cells byte-identical between arms | 25 of 30 | **23 of 30** |

**The negative result survives, and this is its definitive form.** Given its best available
configuration the loop fired 85 % more often, recalibrated twice as many times, and moved the median
mean absolute error by a tenth of a percent, in the wrong direction. In 23 of 30 cells the two arms
produced identical numbers — not "no significant difference", but the loop changing nothing at all.

**The one exception is not an improvement.** `static_affine`'s MAE falls 4.10–7.17 kg at dense
reference rates while its **signed bias degrades sharply**: −12.33 → −34.64 kg at one reference in
two, and +4.18 → **−65.96 kg** at one in five. Recalibrating a frozen estimator more often trades a
little scatter for a lot of offset. Quoting the MAE gain without the bias would misdescribe it.

At one reference in twenty and one in fifty nothing changes anywhere — identical alarms, MAE and
bias. The loop cannot fire on references it does not have.

*Power:* three seeds, and most cells produce zero difference between arms, so the Wilcoxon floor is
1.0 and nothing here can be significant. These are descriptive, and what they describe is 23 of 30
cells in which nothing happened.

---

## The final sweep, 2026-10-02 — Parts A to D

Commit `a4b2962`. Part A is reanalysis of data already stored; it adds no runs. Parts B1, B3 and
B4 are new sweeps. B2 is a new analysis of the eight real recordings. C is blocked. D was not
started.

New artefacts: `export/reference_rate__reference_curve.md` and
`export/reference_rate_ph75__reference_curve.md` (the A1 and A2 tables per sweep),
`export/sim_crossval.md` (B2), figures `*__recall_vs_rate.png` and `*__governance_vs_rate.png`,
and per-seed CSVs `*__recall_by_rate.csv`, `*__governance_by_rate.csv`,
`*__governance_pairs_long.csv`, `sim_crossval_long.csv`, `sim_crossval_measured.csv`.

### A1 — detection recall against reference rate, measured rather than argued by elimination

> **Superseded in part by B1 below, which ran the same question at fifteen seeds.**
> Two statements in this section are three-seed artefacts: recall does **not** reach zero —
> on S7 it is 0.200 at one reference in twenty and 0.067 at one in fifty — and S4's curve is
> not monotone at power. The direction, the magnitude of the fall and the delay result all
> hold. The section is kept because it is what the three-seed sweeps say, and the gap between
> it and B1 is the clearest evidence in this export for why three seeds are not enough.

Section VII-C reaches the reference rate by exclusion: nothing else that was varied moved the
result, so the rate must be what binds. Both `reference_rate` sweeps already contained the direct
measurement and neither this document nor any figure reported it.

**The definition actually used.** Recall is `detected / (detected + missed)` over the calibration
faults the scenario injects, crediting only alarms that fired *after* a fault and inside the
1800 s scoring horizon. It is read from the **governed arm only**: with `edge.control.enabled`
false the detectors are never constructed, and all 90 ungoverned runs in each sweep report
`alarms 0, detected 0, recall 0.000`. Those are structural zeros. Pooling the two arms would halve
every figure below and would present "the detector was not running" as "the detector missed".

Nine runs per cell (three estimators × three seeds), pooled over estimators. Per-estimator rows are
in the sidecar files.

**Mean recall, Page-Hinkley at the corrected 7.5** (`reference_rate_ph75`, n = 9 per cell):

| scenario | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| S4_step_fault | 0.611 | 0.444 | 0.333 | **0.000** | **0.000** |
| S7_sparse_reference | 1.000 | 0.333 | 0.222 | **0.000** | **0.000** |

**The same at the shipped-at-the-time 15.0** (`reference_rate`, n = 9 per cell):

| scenario | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| S4_step_fault | 0.667 | 0.556 | 0.167 | **0.000** | **0.000** |
| S7_sparse_reference | 0.111 | 0.444 | 0.111 | **0.000** | **0.000** |

Both are monotone at 7.5. At 15.0, S7 is not: 0.111 at one reference in two is *below* its value at
one in five, and the corrected threshold moves that same cell to 1.000. One cell of nine runs
moving from 1 fault caught in 9 to 9 of 9 is the largest single effect the threshold correction has
produced anywhere in this project, and it is on the scenario the detector is worst at.

**Where recall crosses zero.** Between **one reference in ten and one in twenty**, in all four
combinations of scenario and threshold. That is four independent brackets agreeing, which is the
strongest part of the result. It is located to **within a factor of two and no better**: no rate was
run between 10 and 20, and interpolating a point inside the bracket would assume a curve shape
nothing here measures. See `OPEN.md` for the one rate that would halve the interval.

**Detection delay roughly doubles over the same span**, which is new and is not in any previous
table. Pooled medians with IQR, S4 at the corrected threshold, over the runs that detected anything
(a run that detected nothing contributes no delay rather than a zero):

| scenario | 1 in 2 | 1 in 5 | 1 in 10 |
|---|---|---|---|
| S4_step_fault | 544 s [451, 544], n=9 | 580 s [566, 593], n=6 | 1123 s [959, 1181], n=6 |
| S7_sparse_reference | 874 s [297, 1406], n=9 | 993 s [977, 993], n=3 | 1424 s [1424, 1424], n=2 |

So detection does not fail abruptly at the crossing: it gets slower first, and the delay at one in
ten is already most of the 1800 s horizon. Both effects have the same cause — the confirmation gate
needs a *run* of reference passes — and the delay is the part that shows the mechanism rather than
only its endpoint.

**What this changes in the argument.** The elimination argument concludes "the reference rate is
what binds". The measurement says something narrower and more usable: detection is not broken, it
works at dense reference rates and ceases between one reference in ten and one in twenty, and the
approach to that point is visible as a doubling of delay. A site that supplies references more often
than the crossing gets drift detection; one that does not gets an estimator with a detector
attached that never fires.

**Statistical status: descriptive.** Three seeds. The smallest two-sided p Wilcoxon can produce at
n = 3 is 0.25, so no comparison here can reach 0.05 however large the effect. B1 is the powered
version.

### A2 — the governance effect against reference rate

> **Superseded in part by B1 below.** The S4 static-calibration effect holds and becomes
> the project's first governed-versus-ungoverned result to survive Holm correction. The S7
> effect does not: the −17.62 kg at one reference in ten is 0.00 at fifteen seeds.

**The definition actually used.** Governed minus ungoverned over a byte-identical stream, **paired
by seed**: the median of the per-seed differences, which is not the difference of the medians. Both
are in the sidecar so the two can be seen not to be the same number. Negative is the loop helping.
Three pairs per cell.

**MAE difference, kg, Page-Hinkley 7.5, S4_step_fault** (median [Q1, Q3] of per-seed differences):

| estimator | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| static_affine | **−40.51** [−43.90, −40.38] | **−29.97** [−33.56, −14.98] | **−3.08** [−5.86, −1.04] | 0.00 [−1.32, 0.00] | 0.00 |
| rls | −0.72 [−0.98, −0.36] | 0.00 [−1.59, +0.33] | **+1.72** [+0.86, +3.39] | 0.00 [0.00, +0.16] | 0.00 |
| kalman | 0.00 [0.00, +0.33] | 0.00 [−1.51, +2.03] | 0.00 | **+0.90** [+0.45, +2.68] | 0.00 |

On S7_sparse_reference the static column is 0.00, 0.00, **−17.62** [−18.22, −8.81], 0.00, 0.00 and
both adaptive columns are 0.00 at every rate. The S7 zeros at one in two and one in five are two of
three seeds identical and one seed moving by about 9 kg — at three seeds that is a median of zero
over a cell that is not uniformly zero, which is exactly the kind of cell B1 exists to resolve.

**Signed bias, carried beside the error and never folded into it.** The brief for this sweep
expected the static-calibration error gain to come with a bias degradation. **It does not, and the
contradiction is flagged here rather than buried.** On S4 the ungoverned static arm sits at
−140.06 kg of bias at every rate; the governed arm is −29.88 kg at one in two, −20.48 kg at one in
five and **+17.89 kg** at one in ten. The magnitude improves by a factor of 4.7 at the dense end.

What does happen, and is worth the manuscript's attention, is that **the loop drives the bias
through zero and out the other side**: at one reference in ten it has overcorrected from −140 kg to
+18 kg while leaving MAE essentially unmoved (−3.08 kg). A table of `|bias|`, or of error alone,
would show that as a small improvement. The sign flip is the finding, not a degradation in
magnitude.

**Is the loop a coarse approximation of what recursive estimation does continuously?** The brief
asks this reading to be tested rather than asserted. The evidence runs both ways and is reported
that way.

*For.* The benefit is confined entirely to the estimator with no tracking of its own. Both adaptive
estimators are at 0.00 kg in 17 of 20 scenario × rate cells, and at one reference in two the
governed static arm reaches 137.59 kg against rls 135.56 and kalman 138.30 — within 2 kg of
estimators that track continuously. The benefit also decays monotonically as recalibration
opportunities thin, which is what a discrete approximation of a continuous process should do.

*Against.* Three things. First, where the loop does fire on an adaptive estimator it is not neutral
but mildly **adverse** — +1.72 kg for rls at one in ten, +0.90 kg for kalman at one in twenty — and
redundancy should cost nothing rather than a kilogram. Second, the approximation degrades faster
than the recalibration count does: between one in two and one in five the loop still performs two
recalibrations in the median run, yet the governed static arm falls from 137.59 kg to 148.13 kg
while rls moves by 4.6 kg. Third, the overcorrection above has no counterpart in the recursive
estimators, whose bias moves smoothly; a discrete corrector that overshoots is not a coarse version
of a continuous one, it is a different mechanism with a different failure.

The supportable statement is therefore narrower than the reading offered: **the loop substitutes for
tracking only where recalibration opportunities are dense, and it substitutes badly rather than
partially where they are not.** Three seeds; see B1 for the powered version.

### B1 — the reference-rate ladder at power

**Read this before A1 and A2 above. The powered run contradicts the three-seed run on the single
claim A1 rests on, and the contradiction is the finding.**

`configs/experiments/reference_rate30.yaml`, **1260 runs, 0 failed**, commit `1d45293`, clean
tree, 28.3 h of compute, Page-Hinkley pinned at the shipped 7.5. Seven rates — one in one and one
in three added at the dense end — two scenarios, three estimators, both control arms.

**Fifteen seeds, not thirty.** The brief said thirty; this is half of it, and the reason is
compute rather than judgement about what is needed. At n = 15 the smallest attainable two-sided
Wilcoxon p is 6.1e-5, so every comparison below can clear Holm correction over a 42-test family —
the sweep is powered, not provisional. Seeds 16–30 were not run; the config and shard scripts are
in place and merging them later requires re-running nothing. Every figure below says n = 15.

#### A1 at power: the recall floor is not zero, and two of the three-seed statements fail

Mean recall, governed arm, **45 runs per cell** (three estimators × fifteen seeds), against the
three-seed figures from `reference_rate_ph75` in brackets:

| scenario | 1 in 1 | 1 in 2 | 1 in 3 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| S4_step_fault | 0.611 | 0.422 *(0.611)* | 0.367 | 0.244 *(0.444)* | 0.322 *(0.333)* | **0.022** *(0.000)* | 0.000 *(0.000)* |
| S7_sparse_reference | 0.933 | 0.711 *(1.000)* | 0.311 | 0.267 *(0.333)* | 0.222 *(0.222)* | **0.200** *(0.000)* | **0.067** *(0.000)* |

**1. "Recall reaches zero between one reference in ten and one in twenty" does not survive.** On
S7 recall is above zero at **every rate run**, including 0.200 at one in twenty and 0.067 at one
in fifty. On S4 the crossing moves out by a factor of 2.5, to between one in twenty and one in
fifty. The three-seed zeros were **sampling zeros**: with nine runs and two injected faults per
run, a cell is eighteen chances, and a true rate of 0.022 produces an expected 0.4 hits — observing
none is unremarkable. A1 above now reads as a statement about three seeds and should be cited as
superseded.

**2. Recall does not saturate at 1.0, which was the reason the dense rates were added.** At one
reference in *one* — every vehicle a reference vehicle, the densest configuration the system can
have — S4 detects **0.611** of its injected faults and S7 detects **0.933**. Supplying infinite
references does not make this detector reliable on an abrupt sensitivity step; 39 % of them go
unanswered inside the horizon. That is a ceiling on the detector, not on the reference supply, and
it is the sharpest thing this sweep found.

**3. S4's recall is not monotone.** 0.611, 0.422, 0.367, 0.244, **0.322**, 0.022, 0.000 — the
one-in-ten cell sits above one-in-five. S7 is monotone across all seven rates. So the monotonicity
claimed in A1 holds for one of the two scenarios at power and not the other.

**What does survive, and is strengthened.** Recall falls steeply with reference rate on both
scenarios — by a factor of 28 on S4 and 14 on S7 between the densest and sparsest rate — and
detection delay rises as references thin, reaching 1697 s on S4 at one in twenty against an 1800 s
horizon, i.e. detection arrives essentially at the moment it stops counting. The *direction* and
the operational reading of A1 are intact. The specific claim that recall reaches zero is not.

#### A2 at power: the first governed-versus-ungoverned result in this project to survive correction

Governed minus ungoverned, paired by seed, median [Q1, Q3] of the per-seed differences, kg.
**S4_step_fault:**

| estimator | 1 in 1 | 1 in 2 | 1 in 3 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| static_affine | **−40.34** | **−33.38** | **−31.43** | −8.37 | −8.63 | 0.00 | 0.00 |
| rls | −0.20 | −0.36 | −0.09 | 0.00 | 0.00 | 0.00 | 0.00 |
| kalman | −0.19 | 0.00 | +0.06 | 0.00 | 0.00 | 0.00 | 0.00 |

`S4 / one in two / static_affine` is **−33.4 kg, p_holm = 0.00769** over a family of 42 tests —
**the first governed-versus-ungoverned comparison anywhere in this project to survive correction.**
One in one is larger at −40.3 kg but reaches only p_holm = 0.0604, because Wilcoxon discards the
two pairs that came out identical and the test runs on thirteen.

On **S7_sparse_reference every static_affine median is 0.00** at all seven rates. The three-seed
−17.62 kg at one in ten does not survive: at fifteen seeds that cell is 0.00 with eight of fifteen
pairs byte-identical. Several S7 cells have a rank-biserial of −1.00 — every nonzero pair pointing
the same way — but with four to eight nonzero pairs they do not clear a 42-test correction. S7's
governance effect is **unresolved**, not absent.

**The governance effect does not keep growing at the dense end.** That was the other reason for
adding one in one and one in three: −40.34 kg against −33.38 kg at one in two is a plateau, not a
continuing rise.

**Both adaptive estimators remain at zero everywhere.** The largest effect across all fourteen
adaptive cells is −0.36 kg. Governance does not move MAE for an estimator that already tracks, at
any reference rate, at power. The project's central negative result holds.

#### How much of the gap the loop closes — the A2 reading, quantified

Comparing the governed static arm against the ungoverned adaptive arms on S4 gives the
"approximation" reading a number rather than a direction:

| rate | gap, frozen → kalman, ungoverned | gap, governed static → kalman | gap closed |
|---|---:|---:|---:|
| 1 in 1 | 49.4 kg | 14.0 kg | **72 %** |
| 1 in 2 | 46.7 kg | 10.8 kg | **77 %** |
| 1 in 3 | 45.2 kg | 10.9 kg | **76 %** |
| 1 in 5 | 44.1 kg | 34.8 kg | 21 % |
| 1 in 10 | 40.9 kg | 31.4 kg | 23 % |
| 1 in 20 | 33.3 kg | 34.2 kg | **−3 %** |
| 1 in 50 | 15.3 kg | 15.3 kg | 0 % |

**The loop recovers about three quarters of what continuous tracking is worth, and only while
references arrive at least one vehicle in three.** It never recovers all of it: even at one
reference in one, frozen calibration under governance is still 14 kg behind an estimator that
tracks. That is the supportable form of "a coarse approximation of what recursive estimation does
continuously" — coarse by about a quarter at the dense end, worthless by one in twenty, and very slightly negative there.

**The bias overshoot is confirmed and is larger at power.** On S4 the ungoverned static arm sits
at −144.10 kg at every rate; the governed arm is **+28.21 kg** at one in one and +13.11 kg at one
in two. The loop does not reduce the bias towards zero, it crosses it.

#### Statistical note

42 tests in the control-arm family, Holm-corrected together. The report states, correctly, that
the smallest test in the family rests on a single nonzero pair, so some null verdicts in it are
statements about the number of pairs that moved rather than about the system — which is precisely
why the per-cell `identical` counts are in `reference_rate30__reference_curve.md` beside every
median.

### B2 — simulator cross-validation, leave one recording out

§V-C concedes that no simulator parameter has ever been cross-validated: everything in
`docs/sim-to-real.md` was fitted on the recordings and then reported against the recordings, so
nothing distinguished "the simulator reproduces this instrument" from "the simulator was fitted to
these eight minutes of it". This is that test. Full report in `export/sim_crossval.md`, per-fold
values in `export/data/sim_crossval_long.csv`.

**Eight recordings, eight folds, seven training recordings each.** The brief said six and a
seventh; there are eight 60 s recordings at 25 kHz in `data/real/`, all carrying `Tenzo2`.
`data/real/EXAMPLE` is the schema sample, carries a synthetic channel `S1`, and is excluded by
name on screen rather than silently. `20260209_fabia2` has no detectable crossing and so has no
event shape, which is reported as missing rather than as a zero; it contributes to every other
statistic.

**The construction.** Fit the noise, drift and pulse parameters on seven recordings by
method-of-moments pooling (median), synthesise a trace carrying those parameters **on the held-out
recording's own sample grid**, and compare the two sets of statistics. The grid matters:
`noise.white_sigma` is a per-sample quantity, so comparing PSDs computed on different grids would
show differences that are an artefact of the grids. Agreement is `log2(synthetic / real)` — 0 is
exact, ±1 is a factor of two — because a plain ratio makes 0.5× look smaller than 2×.

**Three definitions, each stated because each could flatter the result.**

*Crossings are excised from both traces before any noise or drift statistic*, by the same mask,
against a **local** baseline rather than a global median. The quiescent share of each recording is
reported (0.35 to 0.80) so a weak measurement is visible.

*The random walk is fitted from a robust increment spread with the white-noise contribution
subtracted in quadrature.* Both corrections are load-bearing. The white part is 1.45e-5 of a total
1.9e-5 — three quarters of the increment spread is the white noise averaging down, not the zero
line moving. And three of the eight recordings have an increment **sd** five times their robust
scale, so an sd-based fit would set the simulator's random walk from a handful of samples.

*The recordings are in strain and the simulator works in mV/V*, a factor of 500 at gauge factor
2.0 on a quarter bridge. The bridge configuration is **assumed, not measured** — see the sensor
block of `configs/stations/cintron_platform.yaml`. Every absolute agreement below carries that
assumption; no comparison *between* folds does, because it is one constant applied identically to
all eight.

#### Held-out agreement, median absolute `log2(sim/real)` across the eight folds

| statistic | held out | in sample | reading |
|---|---|---|---|
| white noise floor | **0.00** | 0.00 | agrees to within 1 % on every fold |
| 50 Hz line amplitude | **0.04** | 0.04 | agrees to within 4 % on every fold |
| baseline increment spread (robust) | 1.08 | 1.07 | simulator 2.1× the recording, **on every fold including in-sample** |
| low-frequency slope (difference, not ratio) | 0.63 | 0.62 | |
| increment excess kurtosis (difference) | 35.8 | 32.7 | simulator Gaussian; recordings +1.5 to +1698 |
| influence length | 0.31 | **0.00** | the only statistic where holding out costs anything |

**The noise model transfers and is not memorising.** The white floor and the mains line agree held
out as well as in sample, to 1 % and 4 %. One recording's noise statistics predict another
recording's as well as they predict their own. That is the result §V-C was missing, and it is a
positive one.

**The increment disagreement is a fit bias, not a generalisation failure, and the in-sample column
is what proves it.** Held out 1.08 against in sample 1.07: fitting on the very recording being
predicted does not help at all. So the simulator is not failing to generalise — the method-of-moments
round trip overshoots by a constant factor of about 2.1 on every fold. The cause is identifiable
from the model: the simulator moves its zero line through 1/f noise and temperature coupling as
well as through the random walk, and a fit that attributes all of the measured increment spread to
the walk double-counts the rest. **This is a defect in the fitting procedure that
`docs/sim-to-real.md` uses, not in the simulator**, and it would have been invisible without the
held-out/in-sample contrast.

**The simulator cannot produce the baseline the instrument has.** Excess kurtosis of the real
increments runs from +1.5 to +1698 against the Gaussian 0 the model generates — three recordings
(`cintron4`, `fabia1`, `fabia2`) are above +800. The real zero line does not wander, it jumps. The
model has no mechanism for that: `zero_drift` offers a Gaussian random walk, a linear slope and a
Poisson step process, and the step process was not fitted here because nothing in the corpus
separates a settling step from a residual crossing edge at this length. **This is the clearest
simulator/instrument mismatch the project has measured**, and it is a limitation to state rather
than a parameter to retune.

**The event shape is the one parameter that does not transfer.** Held out 0.31 against in sample
0.00 — in sample is perfect by construction, since the fit is that recording's own FWHM. The
measured FWHM spans 0.372 s to 1.104 s across the eight recordings, a factor of three, and the
best-fitting shape family is not even constant: triangle on four recordings, raised cosine on two,
parabola on one, undefined on one. Predicting one recording's event shape from the other seven is
good to about 25 % typically and wrong by a factor of 2.3 at worst (`cintron5`).

Note that the influence length inherits an inference rather than a measurement: it is FWHM × a
crossing speed of 0.78 m/s that was never measured and is not re-measurable. Its fold-to-fold
agreement is a statement about FWHM reproducibility, not about length in metres.

**Nothing was refitted in response to any of this.** The brief is explicit that poor agreement is a
finding and not a reason to refit, and no station or scenario parameter was changed.

### B3 — mechanism ablation for the estimator divergence

**The question.** Under combined disturbances on the influence-line instrument the two adaptive
estimators go opposite ways against frozen calibration: `cintron_ladder30` puts
`S6_combined / static→kalman` at **+9.60 kg** (worse) and `static→rls` at **−30.71 kg** (better),
both at thirty seeds. The manuscript says the mechanism is unestablished.

`configs/experiments/ablation.yaml`, 150 runs, **0 failed**, commit `da9ca44`, clean tree, ten
seeds, 8.9 h of compute. Same station, edge config, reference rate and pulse overrides as
`cintron_ladder30`, with Page-Hinkley pinned at the pre-correction 15.0 so the `S6_combined` arm
is a ten-seed replicate of the cell being explained. **It replicates: +7.80 kg and −30.69 kg
against +9.60 and −30.71.** The pinning worked and the arms are comparable to the result they
explain.

Four arms remove one disturbance class each; the clock skew is in every arm because it belongs to
none of the four and a disturbance present everywhere cannot explain a difference between them.

#### The answer: no single component accounts for it

| arm | kalman − static | rls − static | verdict on kalman |
|---|---:|---:|---|
| `S6_combined` (reference) | **+7.80** | −30.69 | not separated (p_holm 0.393) |
| `S6_ablate_thermal` | +8.49 | −33.58 | not separated (p_holm 0.465) |
| `S6_ablate_zero_walk` | +5.16 | −34.82 | not separated (p_holm 0.465) |
| `S6_ablate_outage` | **+27.43** | −34.39 | **worse** (p_holm 0.0234) |
| `S6_ablate_calibration_fault` | **+29.28** | −11.54 | **worse** (p_holm 0.0195) |

Medians of per-seed paired differences, kg, n = 10.

**Not one arm brings the divergence back to zero.** Two of them make it three to four times
larger. And the difference-in-differences — each arm's divergence against the reference arm's,
paired by seed — is **not significant anywhere**: p_holm = 1 on seven of eight tests and 0.078 on
the eighth. That is a real null rather than an absence of power in the obvious sense: the smallest
attainable corrected p over these eight tests is 0.0156, so a shift that every seed agreed on
would have been detected. What the data show is arm-to-arm shifts that are large in the point
estimate (+21.7 kg for the calibration-fault arm) and **inconsistent across seeds** (rank-biserial
+0.31).

So the answer the brief allowed for is the one that came back: **the divergence is a product of
the overlap, and no single disturbance class carries it.** S6 exists because its failure modes
overlap in time, and this says that overlap is doing the work.

#### What the ablation does establish, from the per-estimator tests

Testing each estimator against *itself* across arms is more informative than the divergence, and
one row carries the mechanism. Removing the calibration faults:

| estimator | change in its own MAE | effect | p (Holm) |
|---|---:|---:|---:|
| static_affine | **−33.47 kg** | **−1.00** | 0.0234 |
| rls | −15.01 kg | −0.93 | 0.0527 |
| kalman | −12.79 kg | −0.35 | 1 |

Frozen calibration improves by 33.5 kg on **every one of ten seeds** when the gain fault is taken
away — it was being hurt by exactly the thing it cannot track. Kalman improves by an unreliable
12.8 kg with no consistency across seeds. The gap therefore widens to +29.3 kg, and in that arm
Kalman is **significantly worse than frozen calibration** where in the full scenario it is not
separated.

**The reading, and it is the same one B4 arrived at independently.** Kalman's penalty is not a
response to a particular disturbance. It is a fixed cost in added estimation variance, and whether
it loses to frozen calibration depends on whether there is a real gain change to recover that cost
against. In full S6 the calibration faults pay most of it back and the net is +7.8 kg, not
separated. Remove them and the cost stands exposed at +29.3 kg, significant.

B4 reached the same shape from the other direction: on `H1_warm_front`, a held-out thermal
scenario **with no injected fault at all**, Kalman is +251 kg worse than frozen calibration with a
rank-biserial of +1.00. Two experiments on different instruments, different scenarios and
different seeds, agreeing that Kalman is reliably worse exactly where there is nothing to track.

**What this does not establish.** That the cost is a constant. The two figures differ by a factor
of eight (+29 kg against +251 kg) on different instruments and at different thermal amplitudes, and
two experiments agreeing in sign is not a measurement of scale. Nor does it establish *why* the
variance is added — that is a property of the filter's Q and R against this plant, and nothing
here varies them.

#### Reading notes

`S6_ablate_calibration_fault` has no calibration fault, so its detection recall is **undefined
rather than zero** and its reconvergence is unmeasurable; only the accuracy comparison is
interpretable in that arm, which is the one the ablation is about. Every other arm reports recall
0.000 over 2 injected faults, which is the `detectors` result at this threshold and not an
ablation effect. All five arms sit at 3.37–3.74× the dynamic floor, so no ablation changed the
difficulty of the scenario much — which is what makes the arms comparable and is worth stating,
given that B4's held-out draw did not have that property.

### B4 — the held-out scenario set

**This addresses the most serious methodological weakness in the study.** §V-E concedes that every
estimator hyperparameter, detector threshold and controller setting was chosen from development
measurements on S1–S8, and that S1–S8 are then the evaluation set, with no disjoint seeds and no
equalised tuning budget. Nothing measured before this sweep distinguished "these estimators work"
from "these estimators have been fitted to these eight scenarios".

`configs/experiments/heldout30.yaml`, 360 runs, **0 failed**, commit `ac1af03`, clean tree, thirty
seeds, one `edge_config_hash` per estimator across all 360 rows. 22.8 h of compute. Per-seed values
in `export/data/heldout30_long.csv`; paired tests in `export/heldout30__comparisons.md`.

**The construction.** Four scenarios drawn over the same disturbance classes, with parameters
written without consulting any tuning result and no value of any key repeating an S1–S8 value of
that key. Evaluated with the shipped configuration and **nothing retuned**. H1 is the thermal class
(S2's counterpart), H2 the abrupt-fault class (S4's), H3 the slow-ramp class (S7's) and H4 the
combined class (S6's). Three of the four inject a gain **rise**; every sensitivity fault in S1–S8
is a gain loss.

**One difference from `ladder30`, stated rather than assumed away.** `ladder30` ran at Page-Hinkley
15.0, the shipped default of the time; this runs at the shipped 7.5, pinned explicitly. A2 measures
what the loop firing is worth to an adaptive estimator — nothing, at any reference rate — so the
estimator comparison is not expected to move with it, but that is an expectation and the difference
is real.

#### Do the five surviving comparisons of §VI-B reproduce?

**Three of five do. Two do not, and both failures are on the same disturbance class.**

| `ladder30` comparison | its median diff | held-out counterpart | median diff | p (Holm) | reproduces? |
|---|---:|---|---:|---:|---|
| S4 / static→kalman | −31.6 kg | H2_gain_jolt | **−47.4 kg** | 1.49e-08 | **yes**, and larger |
| S4 / static→rls | −27.1 kg | H2_gain_jolt | **−39.1 kg** | 1.49e-08 | **yes**, and larger |
| S6 / static→rls | −32.7 kg | H4_pileup | **−29.5 kg** | 2.86e-06 | **yes** |
| S7 / static→kalman | −14.2 kg | H3_slow_fade | **+28.0 kg** | 1 | **no — sign flips** |
| S7 / static→rls | −14.1 kg | H3_slow_fade | −21.7 kg | 0.231 | **no** — direction holds, significance does not |

Wilcoxon signed-rank paired by seed, Holm-corrected within the family of eight tests, n = 30 pairs
each.

#### A new result the development suite never showed

| comparison | median A (static) | median B | median diff | effect | p (Holm) | verdict |
|---|---:|---:|---:|---:|---:|---|
| H1_warm_front / static→kalman | 1124 kg | 1366 kg | **+251 kg** | **+1.00** | 1.49e-08 | **worse** |
| H1_warm_front / static→rls | 1124 kg | 1131 kg | +26.7 kg | +0.29 | 0.493 | not separated |

**On a held-out thermal scenario with no injected fault, the Kalman estimator is 22 % worse than
frozen calibration, on every one of thirty seeds.** The rank-biserial effect size is +1.00, which
means not one seed went the other way. `ladder30`'s thermal counterpart, S2, put the same
comparison at **+0.629 kg, not separated** — so this is not a weaker version of a known effect, it
is an effect the development suite did not contain.

It is specific to the Kalman filter: rls on the same scenario is +26.7 kg and not separated. And it
is a variance effect rather than a bias one — median signed bias is −27.15 kg for kalman against
−25.17 kg for static, essentially the same, while MAE differs by 251 kg. On a scenario where the
gain never actually changes, an adaptive filter can only add variance, and here it adds a great
deal of it. The mechanism is not isolated by this experiment: H1 differs from S2 in daily amplitude
(13.5 against 9.0 °C), trend (−1.1 against +0.4 °C/day), alpha walk (5.5e-8 against 3.0e-8) and the
zero line's temperature coupling (1.9e-4 against 1.2e-4), and which of those is responsible is not
separable here. B3 ablates the thermal component on S6 and is the place to read that against.

#### The caveat that decides how much this is worth, stated before the conclusion

**The held-out scenarios are not matched in difficulty to their development counterparts, and the
two classes that fail to reproduce are exactly the two where the draw came out much harder.** As a
multiple of the dynamic floor:

| class | development | held out |
|---|---:|---:|
| abrupt fault | S4: 1.11–1.34× | H2: **1.09–1.30×** — comparable |
| combined | S6: 3.48–3.70× | H4: **2.57–2.76×** — slightly easier |
| thermal | S2: 1.01–1.02× | H1: **5.71–6.93×** — several times harder |
| slow ramp | S7: 1.02–1.13× | H3: **2.52–2.79×** — more than twice as hard |

This was a deliberate design choice and it has a cost. The scenario headers say a held-out set is
only evidence if it could have failed, so the parameters were drawn wide rather than tight around
S1–S8. The consequence is that a failure to reproduce is **confounded with difficulty**: H3 and H1
are not merely different draws of their classes, they are harder instances of them.

So the supportable reading is narrower than "the five results do not generalise":

**Where the held-out draw lands at a comparable difficulty — H2 against S4, H4 against S6 — the
effects reproduce, and on H2 they reproduce at 1.4 to 1.5 times the magnitude.** That is three of
the five, including both headline S4 comparisons, on scenarios nothing was tuned on. It is real
evidence against the overfitting worry.

**Where the draw is several times harder, they do not.** That is consistent with overfitting and
equally consistent with the effects simply holding over the difficulty range they were measured at
and not beyond it. This sweep does not separate those two, and nothing else in the project does
either.

**What would separate them** is one more sweep: a held-out draw for the thermal and slow-ramp
classes with parameters chosen to land at a comparable multiple of the dynamic floor, which is
measurable from a single pilot seed before committing thirty. That is recorded in `OPEN.md`. It is
the one experiment this sweep makes obviously necessary and did not run.

#### What did not change

The matching, coverage and reference supply all behave as on the development suite. Coverage is
0.89–0.96 against a 0.95 nominal across all twelve cells; `n_matched` equals `n_truth` on H1, H2 and
H3; H4 matches 1982 of 4887, which is the clock-skew fault doing to H4 what `ntp_slip` does to S6
(5003 of 9498) and not a new failure. Detection recall is 0.00–0.33 on the two scenarios with
abrupt faults and 0.00 on the slow ramp, which is the A1 result at one reference in ten and not a
held-out effect.

### C1 — embedded bench

**BLOCKED — no hardware.**

No Raspberry Pi or comparable board is available to this session. The machine is an x86 Windows
workstation; the only remote hosts configured in `~/.ssh` are x86 cloud instances, which would not
answer the question §IV-K asks — portability to an embedded board is not portability to another
x86 host, and running the harness on a cloud VM and reporting it beside the workstation figures
would be a number that looks like evidence and is not.

Nothing was simulated, extrapolated or estimated. Table I keeps its partial mark and §IV-K keeps
its structural claim.

**What would close it**, recorded so the measurement is one command away when a board exists. The
harness is `wimsim.experiments.control_scoring.estimator_cost(estimator, observations)`, which
returns mean microseconds per `update()` and the serialised state size in bytes — the state as the
JSON the profile store would write, which is the form that actually has to survive a restart. The
existing figures (x86 laptop, Intel64 Family 6 Model 154 Stepping 4, Python 3.13.13, numpy 2.5.2,
2000 sequential updates) are static_affine 1.44 µs / 199 B, rls 17.29 µs / 403 B, kalman
24.24 µs / 456 B. To be comparable, a board run needs the same 2000 updates, the board thermally
settled and otherwise unloaded, and the board, OS, Python and numpy versions recorded alongside.

One obstacle is worth naming because it is not visible from the brief: **`estimator_cost` has no
CLI entry point.** The x86 figures were produced by calling it directly, so "run the existing
footprint harness on the board" currently means writing a short script on the board rather than
running a shipped command. That is recorded in `OPEN.md` rather than fixed here, because building
tooling was not part of this brief and the brief said to stop.

### D1 — population-based residual source: scoping note only, not started

**Not started, by instruction.** The brief gates this and asks only for a scoping note if Parts A–C
complete. Nothing in `src/` was changed for it and no run was made.

*What would be implemented.* A residual source that calibrates from the vehicle population rather
than from identified reference vehicles. The lever the manuscript identifies is steering-axle
invariance: across a large enough sample of a vehicle class the front-axle load distribution is
stable, so the mean of the measured steering-axle feature over a window is an estimate of a known
quantity, and the ratio of the two estimates the gain. `vehicles.py` already carries per-axle loads
in truth, so the invariance is simulatable without new plant physics; what does not exist is the
estimator-side half — axle classification from the event stream, a windowed population statistic
with a convergence criterion, and the interface by which it supplies a `ReferenceObservation`
without ever seeing truth.

*What it would be evaluated against.* The A1 curve is the natural benchmark, because the claim is
precisely that it relieves the binding constraint. The test is whether detection recall at one
reference in twenty and one in fifty — currently 0.000 at every threshold tried — becomes nonzero,
and whether the governed-minus-ungoverned MAE difference for static calibration extends past the
one-in-ten point where it currently reaches zero. S7_sparse_reference exists for this and is
already in the grid.

*What could go wrong.* Three things, in order of how likely they are to sink it. The population
statistic is a mean over a class whose composition drifts, so a fleet-composition shift is
indistinguishable from a gain change — and no scenario in this project varies fleet composition, so
the failure mode cannot currently be measured at all. Second, the invariance is a property of a
population the simulator generates from a configured distribution, so a result on synthetic data
would partly be a measurement of that configuration rather than of the method; the real corpus is
eight minutes of two cars and cannot check it. Third, principle 1 is at risk in a way the reference
path is not: the per-axle loads this would exploit are truth-side, and an implementation that
reaches them through anything but a configured prior would be estimating from the answer.

*Cost.* Multi-week, and a different order of work from Parts A–C. It is an implementation project
with its own validation problem, not an experiment.

---

## Read this first: did the method beat B2?

**No — not on mean absolute error, on any scenario tested, at any reference rate.**

B2 is recursive tracking without governance: `rls` or `kalman` with `edge.control.enabled=false`,
on a byte-identical sample stream. The governed arm is the same estimator with the full MAPE-K loop.

### S4_step_fault — two abrupt sensitivity steps

MAE in kg, median [Q1, Q3] over seeds 1–3:

| estimator | reference rate | B2 (loop off) | governed (loop on) | Δ MAE | bias off → on |
|---|---|---|---|---|---|
| kalman | 1 in 2 | 137.6 [137, 140] | 137.6 [137, 140] | **0.0 %** | +1.7 → +1.7 |
| kalman | 1 in 10 | 145.1 [144, 149] | 145.1 [144, 149] | **0.0 %** | −16.7 → −16.7 |
| kalman | 1 in 50 | 156.3 [146, 165] | 156.3 [146, 165] | **0.0 %** | −42.5 → −42.5 |
| rls | 1 in 2 | 135.6 [135, 138] | 135.6 [135, 138] | 0.0 % | −1.8 → −7.4 |
| rls | 1 in 10 | 147.5 [147, 152] | 152.7 [150, 156] | **+3.5 % worse** | −41.0 → **−8.8** |
| rls | 1 in 50 | 159.0 [157, 169] | 159.0 [157, 169] | 0.0 % | −81.6 → −81.6 |
| static_affine (B0) | 1 in 2 | 180.4 [179, 188] | 157.5 [152, 162] | **−12.7 %** | −140.1 → +40.9 |
| static_affine (B0) | 1 in 10 | 180.4 [179, 188] | 182.5 [177, 188] | +1.2 % worse | −140.1 → **+16.4** |
| static_affine (B0) | 1 in 50 | 180.4 [179, 188] | 180.4 [179, 188] | 0.0 % | −140.1 → −140.1 |

### S7_sparse_reference — a 3 % gain loss ramped over two hours

| estimator | reference rate | B2 (loop off) | governed | Δ MAE |
|---|---|---|---|---|
| kalman | 1 in 2 / 10 / 50 | 159.2 / 160.8 / 166.9 | identical | **0.0 %** |
| rls | 1 in 2 / 10 / 50 | 159.4 / 160.3 / 169.0 | identical | **0.0 %** |
| static_affine | 1 in 2 | 182.0 [181, 183] | 179.0 [174, 181] | −1.7 % |

### S6_combined — six overlapping fault mechanisms, one reference in ten

n = 5054 scored passes, dynamic floor 185.1 kg:

| estimator | B2 (loop off) | governed (loop on) | Δ MAE | bias off → on | recalibrations |
|---|---|---|---|---|---|
| kalman | 698.0 [691, 745] | 698.0 [691, 745] | **0.0 %** | +30.2 → +30.2 | 0 |
| rls | 652.8 [639, 689] | 652.8 [638, 689] | **0.0 %** | −32.5 → **−16.6** | 1 |
| static_affine (B0) | 722.2 [714, 758] | 676.7 [677, 735] | **−6.3 %** | −141.7 → **−70.9** | 2 |

Coverage: static 0.902 → 0.916, rls 0.911 → 0.911, kalman 0.920 → 0.920.

Same pattern as S4 and S7, on the hardest scenario: **the loop does not move MAE for either adaptive
estimator**, halves the residual bias on RLS, and rescues the static baseline by 6.3 % MAE and half
its bias.

### What this means for the manuscript

**The loop's measured value is entirely in rescuing the static baseline.** Against B2 — the adaptive
estimators with governance disabled — it changes MAE by **0.0 % in 13 of the 17 tested cells**, and
makes it *worse* in two. It never improves the MAE of an adaptive estimator on any scenario, at any
reference rate.

There is one real effect and it is on **bias**, not MAE. RLS on S4 at one reference in ten goes from
−41.0 kg to **−8.8 kg** with the loop enabled, a 4.7× reduction, while MAE worsens by 3.5 %; RLS on
S6 goes from −32.5 kg to −16.6 kg with MAE unchanged; static_affine on S6 from −141.7 kg to −70.9 kg. That is
not a contradiction — MAE on these scenarios is dominated by the dynamic load floor (128.9 kg on S4),
which no calibration can remove, so a large bias correction moves MAE very little. For a *scale*,
bias is the quantity that matters.

**The honest claim available to the paper is narrower than the one drafted**: the governed loop
removes systematic error that ungoverned recursive tracking leaves in place, at middling reference
rates, without improving aggregate accuracy. The claim "the proposed method beats recursive tracking
without governance" is not supported on MAE and must be rewritten or restricted to bias.

**Practical consequence**: an 8.8 kg residual bias against a 41 kg one, on vehicles of 20–40 t, is
0.02–0.04 % of gross weight either way. Whether that is of practical consequence is a question about
the application, not about the data, and this project cannot answer it.

---

## Scenario coverage

| | what it is | ran? | seeds | notes |
|---|---|---|---|---|
| S1_nominal | clean baseline, no drift/faults/dynamics | ✓ | 1,2,3 | run at 6 h, not its shipped 15 min — see below |
| S2_thermal_cycle | 72 h daily thermal cycle | ✓ | 1,2,3 | |
| S3_zero_drift_walk | 24 h Brownian zero walk | ✓ | 1,2,3 | |
| S4_step_fault | 16 h, two abrupt sensitivity steps at 4 h and 9 h | ✓ | 1,2,3 | also swept over 5 reference rates × 2 control arms |
| S5_outage | 6 h, connectivity loss + publish delay + ADC dropout | ✓ | 1,2,3 | **no calibration-affecting fault** — see VI-E |
| S6_combined | 48 h, six overlapping mechanisms | ✓ | 1,2,3 | |
| S7_sparse_reference | 12 h, 3 % gain ramp over 2 h | ✓ | 1,2,3 | also swept over rates × control arms |
| S8_replay_real | replay of the eight recordings | **partially** | n/a | see VI-I |

S1 is run at 6 h rather than its shipped 900 s. At 900 s it produced 62 crossings, 60 of which went
to the calibration window, leaving a row that was a mean over **two passes** with a coverage of
exactly 0.5000. `scenario_overrides` in `configs/experiments/ladder.yaml` lengthens it; nothing else
about S1 changes with length, since it carries no drift, faults, or dynamics.

---

## VI-A — nominal (S1)

MAE in kg, median [Q1, Q3], n ≈ 1396 scored passes per run:

| estimator | MAE kg | bias kg | coverage |
|---|---|---|---|
| static_affine (B0) | 0.97 [0.96, 1.00] | −0.14 [−0.15, −0.13] | 0.96 [0.95, 0.97] |
| rls | 0.97 [0.94, 0.99] | −0.07 [−0.07, −0.06] | 0.96 [0.95, 0.97] |
| kalman | 0.97 [0.94, 1.00] | −0.04 [−0.05, −0.02] | 0.97 [0.95, 0.97] |

Dynamic floor 0.0 kg — S1 carries no dynamic load, so there is no irreducible component and MAE is
the whole error.

**All three estimators are indistinguishable at 0.97 kg.** With nothing to adapt to, adaptation
costs nothing, which is the result worth having: an adaptive estimator that was *worse* under
nominal conditions would be a bad trade at most sites.

---

## VI-B — thermal cycle (S2)

72 h, n ≈ 12955 scored passes, dynamic floor 134.5 kg:

| estimator | MAE kg | × floor | bias kg | coverage |
|---|---|---|---|---|
| static_affine | 136.25 [135.76, 137.36] | 1.01 | **−20.95 [−27.95, −19.51]** | 0.94 [0.93, 0.95] |
| rls | 136.82 [136.13, 137.83] | 1.01 | −0.51 [−1.61, +2.80] | 0.94 [0.94, 0.95] |
| kalman | 137.68 [137.05, 139.16] | 1.02 | +4.29 [+0.95, +4.76] | 0.96 [0.96, 0.96] |

**MAE is indistinguishable; bias is not.** Static carries −21 kg through a 72-hour thermal cycle
while RLS and Kalman sit within 5 kg of zero. MAE is dominated by the dynamic load the calibration
cannot touch; bias is the part it can.

**Per-parameter tracking error against truth: NOT RUN.** The truth log records the plant's `q` and
`k` at 1 Hz and the estimator state is stored on each profile, but no analysis joins them. The
manuscript's §VI-B request for per-parameter tracking error cannot be answered from what exists.
Producing it needs a new comparison, not a new run.

**How the static baseline diverges**: by a systematic −21 kg offset, not by growth — S2's temperature
returns to its starting point each day, so the error oscillates rather than accumulating. The
divergence is visible in bias and invisible in MAE.

---

## VI-C — baseline drift (S3)

24 h Brownian zero walk, n ≈ 4775, floor 132.8 kg:

| estimator | MAE kg | × floor | bias kg | coverage |
|---|---|---|---|---|
| static_affine | 132.91 [131.90, 133.49] | 1.00 | −15.64 [−16.43, −13.54] | 0.94 [0.93, 0.95] |
| rls | 134.57 [133.24, 134.66] | 1.01 | +1.33 [−3.35, +5.94] | 0.94 [0.94, 0.95] |
| kalman | 135.53 [134.18, 136.16] | 1.02 | +4.95 [−0.85, +9.13] | 0.96 [0.96, 0.97]

Same shape as S2: the closed loop removes a −16 kg systematic offset and leaves MAE where it was.

**Error growth over time: NOT RUN.** No analysis bins error by elapsed time. The aggregate is over
the whole run.

**Detector activity**: 2–3 alarms across three seeds per estimator, **zero recalibrations**, no
injected calibration fault to detect. The drift is tracked continuously by the adaptive estimators
rather than being caught and corrected discretely.

---

## VI-D — abrupt fault (S4) — headline

Two `gain_instability` faults at **4.0 h** and **9.0 h** of a 16 h run. n ≈ 3484 scored passes.
Dynamic floor 128.9 kg.

### Accuracy

| estimator | MAE kg | × floor | bias kg | coverage |
|---|---|---|---|---|
| static_affine | 182.49 [176.97, 188.14] | **1.40** | +16.44 [+15.37, +17.57] | 0.91 [0.90, 0.92] |
| rls | 152.71 [150.09, 156.20] | 1.17 | −8.78 [−24.86, +4.30] | 0.95 [0.93, 0.95] |
| **kalman** | **145.07 [144.43, 149.24]** | **1.13** | −16.74 [−18.68, −2.88] | 0.98 [0.97, 0.99] |

### Detection and reconvergence

Faults answered inside the horizon, summed over 3 seeds × 2 faults = **6 opportunities**:

| estimator | alarms | recalibrations | detected | missed | false alarms/h | reconvergence (s, per seed) |
|---|---|---|---|---|---|---|
| static_affine | 6 | 4 | 1 | 5 | 0.125 | 12409, 9677, 11180 |
| rls | 5 | 2 | 1 | 5 | 0.062 | 3919, 8651, 7923 |
| kalman | 4 | 0 | 1 | 5 | 0.062 | 3406, 1744, 4996 |

Median time to reconverge: **kalman 3406 s, rls 7923 s, static_affine 11180 s**. Static takes 3.3×
as long as Kalman, and over three hours on every seed.

**Detection recall is 1/6 for every estimator**, at one reference vehicle in ten.

### The ε and W_c actually used, and sensitivity

- **ε is not a fractional tolerance.** Reconvergence is `tolerance_sigma = 3.0` standard errors of
  the signed median over a 40-pass window, held for 40 further windows. The smallest resolvable
  shift is ≈ **0.59 σ** of the residual spread.
- **W_c = `confirmation_passes` = 60 passes**, with `confirm_sigma = 3.0`.
- **H = 1800 s.**

**Sensitivity to W_c is large and was measured** (`docs/controller.md`): on S4, window 30 → 0
recalibrations and −136.9 kg bias; window 60 → 2 recalibrations and −9.4 kg; window 90 → −23.8 kg.
The shipped 60 was chosen from that sweep, on the same scenario used to evaluate it.

**Sensitivity to ε: NOT RUN.** `tolerance_sigma` was never swept. Its effect is analytic — the
resolvable shift scales as `tolerance_sigma / √window` — but no empirical sensitivity exists.

### The two faults separately

**NOT RUN.** `time_to_reconverge` measures from the **first** fault only, by construction: later
faults land on a plant that has already been disturbed, so their recovery is not a clean
measurement. `detector_rates` counts both faults but does not attribute a delay to each. The
manuscript's request to cover both S4 faults separately **cannot be answered from the stored
results**; it needs a per-fault scoring pass that does not exist.

What *is* known about the two faults separately comes from the phase-5 checkpoint at a much denser
reference rate (1 in 2), recorded in `docs/controller.md`: fault 1 at 4.00 h detected 4.04 h,
recalibrated 4.70 h, verified 5.17 h; fault 2 at 9.00 h detected 9.84 h, recalibrated 10.33 h,
verified 10.82 h. Two alarms in between were correctly rejected.

---

## VI-E — outage (S5)

6 h with three faults: a 20-minute connectivity loss at 2 h, a 15-minute publish delay at 2.33 h,
and a 45-second ADC dropout at 3.5 h. n ≈ 1392, floor 126.5 kg.

| estimator | MAE kg | × floor | bias kg | coverage |
|---|---|---|---|---|
| static_affine | 127.04 [126.05, 129.03] | 1.00 | −19.47 | 0.91 [0.90, 0.93] |
| rls | 125.78 [125.39, 128.35] | 1.00 | −15.91 | 0.95 [0.92, 0.96] |
| kalman | 126.38 [126.25, 131.15] | 1.02 | −12.36 | 0.99 [0.98, 0.99] |

**None of S5's faults touches the calibration.** All three are transport or acquisition failures, so
recall is *undefined* rather than zero, and 0 recalibrations occurred. This was itself a finding:
the scoring code originally counted all three as missed detections, and reported `recall 0.000,
missed 3` on all nine runs — which reads as "the detectors caught nothing" when there was nothing
to catch. Fixed; see `CONTRADICTIONS.md`.

**Buffer behaviour and replay ordering: NOT MEASURED IN THIS SWEEP.** The offline path does not
exercise the transport. Ordering-preservation and no-loss-across-disconnection are covered by
integration tests (`tests/test_transport.py`, `tests/test_live.py`) which pass, but no scenario-level
measurement of buffer depth or replay latency exists in the results.

**Edge-local versus centrally arbitrated correction: NOT RUN.** `ARBITRATION_MODES = ("local",
"cloud")` exists in `calibration/controller.py` and the config accepts both, but no sweep varies it.
There is no measured difference to report.

---

## VI-F — uncertainty

Empirical coverage against a nominal **0.95**, and mean interval width, stratified by regime. All
with the shipped `conformal` / `relative` construction unless stated.

| scenario (regime) | estimator | coverage | mean width kg |
|---|---|---|---|
| S1 (no drift) | static / rls / kalman | 0.96 / 0.96 / 0.97 | 20 / 20 / 19 |
| S2 (slow thermal) | static / rls / kalman | 0.94 / 0.94 / 0.96 | 761 / 724 / 736 |
| S3 (random walk) | static / rls / kalman | 0.94 / 0.94 / 0.96 | 746 / 698 / 713 |
| S4 (abrupt steps) | static / rls / kalman | 0.91 / 0.95 / **0.98** | 891 / 817 / 910 |
| S6 (combined) | static / rls / kalman | 0.92 / 0.91 / 0.92 | 1516 / 1273 / 1293 |
| S7 (slow ramp) | static / rls / kalman | **0.89** / 0.93 / 0.96 | 924 / 847 / 827 |

**Conformal versus analytical, stratified by reference rate** (S4, controller on):

| reference rate | conformal coverage | fallback coverage | events on the fallback |
|---|---|---|---|
| 1 in 2 | 0.951 | — | 0 |
| 1 in 10 | 0.974 | — | 121 |
| 1 in 50 | **0.998** | — | 841 |

The two constructions cannot be compared head-to-head at a fixed rate, because **conformal replaces
the analytic band rather than running alongside it** (see `CONTRADICTIONS.md` §IV-I). What can be
reported is the fallback: until conformal has its 19 calibration references, the estimator's own
band is used.

**The analytical Kalman interval, as originally implemented, achieved empirical coverage 0.0065
against a nominal 0.95**, with a mean width of 2.3 kg on vehicles of tens of tonnes. It has been
replaced by an empirical construction; coverage on the same scenario is now 0.897. This is a
headline negative result and is documented in `CONTRADICTIONS.md` §IV-D.

**Static_affine under-covers where it is biased**: 0.89 on S7, where it carries −96.8 kg. The
interval does not know about a bias it was not shown.

---

## VI-G — sparse reference (S7 and the rate sweep)

### Degradation as references thin — S4, controller on, MAE in kg

| estimator | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| kalman | 137.6 | 139.7 | 145.1 | 148.1 | 156.3 |
| rls | 135.6 | 140.6 | 152.7 | 150.5 | 159.0 |
| static_affine | 157.5 | 176.0 | 182.5 | 181.4 | 180.4 |

As a multiple of the dynamic floor, kalman goes 1.06 → 1.19 and rls 1.05 → 1.26 between one
reference in two and one in fifty.

### Detection collapses with the rate

Faults answered inside the 30-minute horizon, out of 6, controller on, S4:

| | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| static_affine | 4 | 4 | 1 | 0 | 0 |
| rls | 4 | 3 | 1 | 0 | 0 |
| kalman | 4 | 3 | 1 | 0 | 0 |

This is the confirmation gate behaving as its sensitivity floor predicts —
`confirm_sigma × 1.2533 × σ / √passes` needs a *run* of reference passes, and at one in fifty they
arrive fifty times more slowly than the faults do.

**Superseded in two ways by A1 above; the table is kept because it is what `reference_rate` ran.**
It is at Page-Hinkley **15.0**, and at the corrected 7.5 the same cells read 0.611, 0.444, 0.333,
0.000, 0.000 as a recall — one in ten goes from 1 fault in 18 to 6. It also reports counts without
the detection delay beside them, and the delay is what shows that detection degrades before it
stops: it doubles between one reference in two and one in ten, to 1123 s against an 1800 s
horizon.

### Crossover where population mode overtakes sparse supervised

**NOT RUN, and cannot be run.** Population mode is not implemented (see `CONTRADICTIONS.md` §IV-F).

### Fleet-composition shift

**NOT RUN.** No scenario varies fleet composition.

---

## VI-H — computational footprint

**Bench measurement on an x86 laptop, not a board.** Intel64 Family 6 Model 154 Stepping 4,
Python 3.13.13, numpy 2.5.2. 2000 sequential `update()` calls.

| estimator | µs per update | state bytes |
|---|---|---|
| static_affine (B0) | **1.44** | 199 |
| rls | 17.29 | 403 |
| kalman | 24.24 | 456 |

Kalman costs **17×** the static baseline per update and 2.3× its persisted state. The state is the
quantity that has to survive a restart, and the difference is the covariance matrix.

**Per-board latency, CPU, memory, and added end-to-end latency: NOT RUN.** No code in this project
has executed on embedded hardware; `SerialSource` is a stub. The `wimsim edge-run` path measures
end-to-end latency through the transport, but only on this host and it was not part of any sweep.

---

## VI-I — real data

**Stated conservatively, because the conservative statement is the true one.**

### Could S8 be scored at all?

**Yes, but only against inferred masses.** `S8_replay_real` was not scorable at the start of this
work: no reference file existed and nothing read one. It can now be scored end to end, against a
`reference.csv` written from *published vehicle operating weights* and an axle split measured from
the signal's own bimodal peak amplitudes. **No vehicle at the site has been weighed.**

Scoring against these files measures whether the pipeline reproduces the inference, **not whether it
weighs vehicles**.

### What the recordings support

Eight 60-second recordings at 25 kHz, two strain channels each. After detection: **23 matched
crossings across 7 usable recordings**; `20260209_fabia2` contains no detectable crossing.

**Within-recording scoring** (calibration and test from the same minute of the same drive-over —
optimistic, and reported only to show it is optimistic): MAE 2.3 to 22.4 kg across four recordings;
two could not be scored because every crossing was needed to fit.

**Leave-one-recording-out** — fit on six recordings, predict the seventh:

| | value |
|---|---|
| MAE | **42.9 kg** |
| MAPE | **13.23 %** |
| bias | +0.18 kg |
| coverage | 0.783 |
| gain spread across folds | **50.4 %** |

Per fold:

| held out | n fit | n scored | MAE kg | bias kg | coverage |
|---|---|---|---|---|---|
| 20260209_cintron1 | 22 | 1 | 25.5 | −25.5 | 1.00 |
| 20260209_cintron2_spat | 20 | 3 | 40.5 | −40.5 | 1.00 |
| 20260209_cintron3 | 20 | 3 | 69.7 | −69.7 | 0.67 |
| 20260209_cintron4 | 19 | 4 | 23.4 | −23.4 | 1.00 |
| 20260209_cintron5 | 17 | 6 | 19.4 | +5.3 | 1.00 |
| 20260209_fabia1 | 21 | 2 | 26.5 | +26.5 | 1.00 |
| 20260209_fabia3 | 19 | 4 | 92.3 | +92.3 | 0.00 |

`data/real/EXAMPLE` is skipped: it carries a `reference.csv` but its channel is `S1`.

### The finding that matters

**The pooled bias of +0.18 kg is an artefact of cancellation.** Mean |fold bias| is **40.5 kg**, and
the sign splits cleanly by vehicle: Citroën folds **−30.8 kg**, Fabia folds **+59.4 kg**. The two
vehicles do not sit on one calibration line.

Two explanations fit and the corpus cannot separate them: the platform responds differently to the
two vehicles, or the Citroën's inferred mass is wrong. The channel-ratio measurement narrows it —
the Tenzo2/Tenzo1 ratio is **2.98 ± 0.37 (Citroën)** and **2.78 ± 0.34 (Fabia)**, one ratio within
the noise, and one gauge is transverse to the other, so a vehicle sitting differently on the plate
would move it. It does not. That removes the geometric explanation and leaves the inferred mass as
the better candidate, but is not proof: the ratio is mass-independent by construction.

**One weighbridge ticket would settle it. Nothing else in this project will.**

### Sensitivity

The cross-validated fit implies **3.67–5.53 × 10⁻⁸ strain/kg**, against the **2.70–3.06 × 10⁻⁸**
inferred in `docs/sim-to-real.md`. The inference assumed proportionality through the origin; a
two-parameter fit prefers a different slope with an intercept.

---

## VI-J — ablations

| ablation requested | status |
|---|---|
| interaction term `θ₂` | **NOT RUN — the term does not exist.** See `CONTRADICTIONS.md` §III-B |
| drift trigger | **partially** — controller on/off is swept on S4, S6, S7 (the B2 comparison above) |
| governance | **as above** |
| conformal intervals | **partially** — conformal vs the estimator's own band is observable through the fallback, not as a controlled arm |
| estimator choice | ✓ static / rls / kalman across all 7 scenarios |
| feature choice (peak vs area) | **NOT RUN at scenario level.** Decided in phase 2; `configs/estimators/area.yaml` exists but no sweep varies it |
| λ sweep (RLS forgetting) | **NOT RUN** |
| Q sweep (Kalman process noise) | **NOT RUN** |
| detector choice | **NOT RUN.** Only CUSUM and Page–Hinkley are enabled; ADWIN and KS have unit tests only |

Two further ablations exist that the manuscript did not request and that produced the strongest
results in this work: the **reference-rate sweep** (5 rates × 2 control arms × 3 estimators × 3
seeds, 180 runs) and the **leave-one-recording-out** real-data cross-validation. Both are reported
above.


---

## Where each number lives

| file | contents |
|---|---|
| `export/data/ladder_long.csv` | 63 runs × 7 scenarios × 3 estimators × 3 seeds, one metric per row |
| `export/data/reference_rate_long.csv` | 180 runs: 5 reference rates × 2 control arms × 3 estimators × 3 seeds, S4 and S7 |
| `export/data/governance_long.csv` | 18 runs: the S6 B2 comparison |
| `export/data/all_metrics_long.csv` | the three above, concatenated |
| `export/data/real_corpus_leave_one_out_long.csv` | the 7 real-data folds and the pooled figures |
| `export/data/footprint_long.csv` | per-update cost and state size, bench not board |
| `export/data/channel_ratio_long.csv` | 20 paired crossings, Tenzo2/Tenzo1 peak ratio |
| `export/data/manifest.json` | commit and config hashes, package versions, per-file commands |

Every CSV is long format with per-seed values, so any aggregate here can be recomputed and any
dispersion re-derived.

## Everything reported as NOT RUN, collected

So that none of it has to be hunted for:

- per-parameter tracking error against truth (§VI-B)
- error growth binned by elapsed time (§VI-C)
- the two S4 faults scored separately (§VI-D)
- sensitivity of reconvergence to ε / `tolerance_sigma` (§VI-D)
- buffer depth and replay latency at scenario level (§VI-E)
- edge-local versus centrally arbitrated correction (§VI-E)
- population mode, and any crossover against sparse supervised (§VI-G) — **not implementable**
- fleet-composition shift (§VI-G)
- per-board latency, CPU, memory, added end-to-end latency (§VI-H)
- ~~ablation of the interaction term (§VI-J)~~ — **now run**, see `theta2` above
- peak-versus-area at scenario level (§VI-J)
- λ and Q sweeps (§VI-J)
- ~~per-detector comparison; ADWIN and windowed KS at scenario level (§VI-J)~~ — **now run**, see
  `detectors` above
- ~~any statistical significance test, anywhere~~ — **now run on `ladder30`**; the three-seed sweeps
  remain descriptive
- ~~the detector grid at lower thresholds~~ — **now run**, see `detector_thresholds` above
- detection at a higher reference rate, which is where that sweep points instead
- `confirmation_passes` sized against the fault horizon rather than in vehicles
- an *online*-identified interaction term, which is what §III-B actually specifies
