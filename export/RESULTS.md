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

**Dispersion.** Median with [Q1, Q3] over three seeds throughout. With n = 3 an IQR spans the whole
sample; it is reported because a bare figure is unusable, not because it is a confidence interval.
**No significance test was performed anywhere in this project.**

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
- ablation of the interaction term (§VI-J) — **not implementable**, the term does not exist
- peak-versus-area at scenario level (§VI-J)
- λ and Q sweeps (§VI-J)
- per-detector comparison; ADWIN and windowed KS at scenario level (§VI-J)
- any statistical significance test, anywhere
