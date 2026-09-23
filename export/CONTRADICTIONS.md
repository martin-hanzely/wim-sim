# Manuscript claims against the code — read this first

Every verdict below was checked against the repository at commit `f40ca51`. Where a claim is
contradicted, what is true instead is stated, with a file or test to check it.

**The six that matter most, before the detail:**

1. **The calibration map is two-parameter, not three.** There is no `θ₂·(s·ΔT)` term in any
   *shipped* estimator. Temperature is compensated upstream in the preprocessor from a *fixed*
   profile coefficient. **Since resolved as far as it can be by experiment:** a three-parameter
   estimator now exists and has been run, and it is worse than useless — 23 of 90 runs produce a
   negative sensor gain, and where it fits at all it is 32× the dynamic floor against the
   two-parameter map's 1.02×. The reason is that the calibration window spans a seventh of the
   thermal range it must extrapolate across. This does **not** test §III-B's *online* identification,
   which is the one thing that would fix that. (§III-B)
2. **Two detectors run, not four — and running all four changes nothing.** ADWIN and windowed KS
   were implemented and tested but absent from the shipped configuration. **Since run at scenario
   level:** each detector alone and the four-way ensemble, 100 runs. Median detection recall is
   0.000 in every cell; the four-way ensemble produces numbers identical to CUSUM alone. (§IV-G)
3. **Population mode is a label, not an implementation.** `reference_mode: population` changes the
   `source` string on a `ReferenceObservation` and nothing else; the mass still comes from the
   supervised reference. No vehicle classification exists. (§IV-F, §VI-G)
4. **No reference mass has ever been measured.** Every kilogram attributed to the real sensor
   descends from published vehicle weights, not a weighbridge. (§V-D)
5. **~~Three seeds, not thirty. No significance testing of any kind.~~ RESOLVED.** 630 runs at
   thirty seeds, Wilcoxon signed-rank paired by seed with Holm correction and rank-biserial effect
   sizes. Five of fourteen comparisons survive correction; five others have a raw p below 0.05 and
   do not. (§V-H)
6. **The experiments used the contact-force station.** The real instrument is an influence-line
   strain platform, and the two are different instruments, not two settings of one. **Since run on
   both:** the scorable scenarios now have results on the real instrument's physics, and it costs a
   factor of 12 on the clean scenario and 6–14 % elsewhere. (§III-A)
7. **The real platform's sensitivity constant was wrong by a factor of 1000**, and had been since it
   was derived. Found by running the scenario suite on it for the first time, which detected nothing
   at all. Corrected to `k0 = 1.44e-5` mV/V per kg. No previously reported number used it. (§III-A)

---

## Section III — problem formulation

### §III-A — contact-force sensor model

**PARTIALLY CONFIRMED.** All reported synthetic results (S1–S7) used
`configs/stations/default.yaml`, which *is* the contact-force model the section describes: pulse
width = tyre contact patch ÷ speed, milliseconds long, one pulse per axle, positive-going.

But the real hardware is not that instrument. `docs/sim-to-real.md` measures the recordings as a
structural **influence line**: a single smooth deflection 0.4–1.2 s long in which a car's two axles
are not resolved, and **negative-going**. `configs/stations/cintron_platform.yaml` models it
separately. Both models exist; the reported experiments exercise only the first.

*What is true instead:* the section should say which instrument each result belongs to. The
manuscript's synthetic results describe a contact-force sensor; the real-data results describe a
different sensor, and no synthetic result in the paper was produced on a model of the hardware that
the recordings came from.

### §III-B — three-parameter map with an online temperature interaction

**CONTRADICTED**, on every part of the claim.

| claim | reality | reference |
|---|---|---|
| `m = θ₀ + θ₁·s + θ₂·(s·ΔT)` | `m = gain·s + bias` | `_N_PARAMS = 2` in `calibration/static_affine.py:41` and `calibration/rls.py:54`; `_N_STATES = 2  # [q, k]` in `calibration/kalman.py:74` |
| `θ₂` identified online | no such parameter is fitted | the design matrix is `[s, 1]` — `static_affine.py:134` |
| temperature in the regressor | applied upstream in the preprocessor | `edge/preprocess.py:345` `_thermal_factor` divides by `1 + α(T_probe − T_ref)` **before** the feature is extracted |
| `α` from a fixed profile coefficient? | yes — `state.temp_coeff`, carried on the profile and never fitted | `preprocess.py:351` |
| `α = −θ₂/θ₁` recoverable | not recoverable | there is no `θ₂` |

*What is true instead:* the system is a two-parameter affine map on a temperature-compensated
feature, with the thermal coefficient supplied by the active calibration profile rather than
estimated. Any claim about tracking `α` online, or about recovering thermal sensitivity from the
fit, has to be withdrawn or the estimator has to gain a third parameter.

### §III-C — random walk plus abrupt-change alternative

**CONFIRMED.** `S3_zero_drift_walk` sets `random_walk_sigma_per_sqrt_s: 8.0e-5` with no steps;
`S4_step_fault` injects two abrupt `gain_instability` faults. Both regimes are exercised and
reported separately.

### §III-E — single channel, ΔT constant within an event window

**CONFIRMED for the synthetic results**, and the single-channel assumption is enforced rather than
merely assumed: `edge/estimate.py:142` sets `speed_mps=None` with the comment "a single sensor
cannot measure speed".

**Contradicted by the hardware**, which has two channels at one cross-section, 126 mm apart with one
gauge rotated 90°. Nothing in the reported pipeline uses the second channel; it is used only by
`wimsim check-channels`, which is a fault monitor and not part of the estimator.

---

## Section IV — method

### §IV-B — peak versus area chosen empirically

**CONFIRMED.** Peak won, and `docs/edge-pipeline.md` carries the evidence: 1.43 kg MAE on
`S1_nominal` with the peak feature. The real recordings confirmed it a second time and for a
different reason — peak amplitude is speed-independent there (correlation +0.13 Citroën, −0.31
Fabia), so the peak is a load measurement rather than a rate measurement.

**One caveat the manuscript must carry:** the shipped configuration is `feature: peak`, and the
`area` config exists but no reported sweep varies the feature. The comparison is a phase-2
measurement, not part of the phase-6 results.

### §IV-C — RLS with forgetting, windup guarded by excitation gating and a trace bound

**PARTIALLY CONFIRMED.** The trace bound exists and is the documented mechanism:
`_bound_covariance()` in `calibration/rls.py:251` scales `trace(P)` rather than clipping the
diagonal, deliberately, so the *shape* of `P` is preserved.

**There is no excitation gating.** No check defers or damps an update when the regressor is poorly
exciting. Searching the package for `excitation` returns only unrelated hits (a CLI option for
bridge excitation voltage).

*What is true instead:* windup is bounded by the trace cap alone.

### §IV-D — Kalman with per-parameter Q and an analytical predictive variance

**PARTIALLY CONFIRMED, and the second half is now false.**

Per-parameter process noise is real: `process_noise_bias` and `process_noise_gain` are separate
(`calibration/kalman.py:116`), scaled by elapsed *seconds* because a plant drifts on a clock rather
than on traffic.

The analytical predictive variance was **removed during this work**, because it was wrong. It was
`J P Jᵀ + R/k²` — both terms sensor-side — while the dominant error is the vehicle's own dynamics,
about 141 kg, which the filter is never told about. Measured empirical coverage was **0.0065 against
a nominal 0.95**, with a band 2.3 kg wide on a twenty-tonne vehicle. The interval is now the
empirical prediction-error spread; coverage on the same scenario is **0.897**.

*What is true instead:* the Kalman observer reports an empirical interval. The analytical
construction survives only as a compatibility path for profiles stored before the change, and is
labelled `kalman_analytic` where it appears.

### §IV-E — persistent excitation; bounded-error tracking rather than asymptotic convergence

**NOT TESTED.** No persistent-excitation condition is stated, checked, or enforced anywhere in the
package, and no test establishes a bounded-error tracking result. The empirical tracking behaviour
is reported (S2, S3, S4) but no formal claim is supported by the code.

### §IV-F — four pluggable residual sources combined by confidence weighting

**CONTRADICTED.**

| claimed source | status |
|---|---|
| supervised pass | implemented and used — the only one |
| zero-line | not implemented as a residual source |
| cross-channel ratio | implemented **as a standalone fault monitor** (`calibration/channel_ratio.py`), not as a residual feeding the estimator |
| population statistic | **not implemented** |

There is no confidence weighting into the Kalman measurement noise from multiple sources. `R` is
augmented by a single term, `observation.sigma_kg`, when a reference carries its own uncertainty
(`kalman.py` update step) — that is per-observation weighting, not multi-source fusion.

On population mode specifically: `edge.control.reference_mode` accepts `"population"`, and
`experiments/closed_loop.py:257` passes it through to `ReferenceObservation.source`. The mass on
line 246 still comes from `references.mass_at(...)`, the supervised reference. **The flag changes a
string and nothing else.** No vehicle classification exists anywhere in the repository.

### §IV-G — four detectors in parallel

**CONTRADICTED as reported.** All four are implemented and tested (`DETECTORS` in
`calibration/drift.py:435`, 63 tests in `tests/test_drift.py`), but the shipped configuration runs
**two**: `detectors: ('cusum', 'page_hinkley')`.

*What is true instead:* every detection number reported before 2026-09-23 — delay, false-alarm
rate, recall — is the behaviour of CUSUM and Page–Hinkley in parallel.

**UPDATE — the per-detector table now exists** (`detectors__detectors.md`, 100 runs, ten seeds, two
scenarios, none failed), and it does not say what §IV-G assumes:

- **Median detection recall is 0.000 in every cell.** CUSUM catches 3 of 20 injected calibration
  faults on `S4_step_fault`, Page–Hinkley 1 of 20, ADWIN and windowed KS none at all on either
  scenario.
- **The four-way ensemble is CUSUM.** `detect_all4` and `detect_cusum` produce identical detections,
  false alarms and delays on S4. Adding three detectors changed no detection in 100 runs.
- **Not a scoring-horizon artefact.** The detectors alarm 1–2 times per run against 2 injected
  faults, so scoring *every* alarm as a hit would cap recall at 0.20–0.95 against a measured
  0.00–0.15.
- **False alarms run at 0.00–0.06 per hour**, one per 17 hours at worst, so the operating point is
  far too conservative and there is a large unspent budget on that axis.

So §IV-G can be written, with four detectors and scenario-level evidence. What it cannot claim is
that running four helps.

### §IV-H — five-state machine with confirmation, minimum references, verification, cool-down, DEGRADED

**CONFIRMED**, in full. `STATES` in `calibration/controller.py:107` is exactly
`MONITORING, DRIFT_SUSPECTED, RECALIBRATING, VERIFYING, DEGRADED`. Defaults in the shipped config:
confirmation window 60 passes, `confirm_sigma` 3.0, minimum 10 reference observations, cool-down
3600 s. `DEGRADED` keeps measuring and flags output rather than guessing a correction, and
`docs/controller.md` records that a DEGRADED retry loop was a measured bug (nine recalibrations)
fixed by gating on buffer growth.

### §IV-I — split conformal over a sliding window, reset on activation, reported alongside the analytical interval

**PARTIALLY CONFIRMED.** Split conformal over a sliding window is real
(`calibration/conformal.py`, `max_calibration` 500), and it is reset on profile activation
(`experiments/closed_loop.py:297`, `conformal.reset()`).

**"Alongside" is wrong.** Conformal *replaces* the estimator's own band when it is calibrated and
falls back to it when it is not (`_conformal_interval` returns `None` to keep the analytic one).
One interval is emitted per event, never two. Which construction produced it is recorded in
`interval_source`, and the results now report coverage per construction.

This distinction turned out to matter: at one reference in fifty, **841 of 3392 events** silently
carried the fallback band, and the pooled coverage figure of 0.754 was an average over a broken
quarter and a working three quarters.

### §IV-J — retrospective recomputation verified by test

**CONFIRMED.** `experiments/recompute.py`, with `tests/test_recompute.py` — **13 tests, all
passing**, including that events re-derived under a new profile match a direct computation.

### §IV-K — numpy-only estimator core, deployed unchanged on embedded hardware

**PARTIALLY CONFIRMED.** The numpy-only property is enforced by static import-graph tests, not
asserted: `tests/test_architecture.py` — 4 tests passing, including a negative control that the
check would actually fail if violated.

**"Deployed unchanged on embedded hardware" is untested.** `SerialSource` is an explicit,
documented stub. No code has run on a board. See §V-G.

---

## Section V — methods

### §V-C — simulator parameters fitted from real recordings, validated leave-one-out

**PARTIALLY CONFIRMED, with the two halves belonging to different things.**

Fitting is real: `wimsim gap-report` fits `white_sigma`, `mains.amplitude` and `zero_drift.q0` from
a recording and emits them as `--set` lines that load.

**Leave-one-out was never applied to simulator parameters.** The leave-one-recording-out procedure
that exists (`wimsim score-corpus`) cross-validates the *calibration*, not the simulator. No
simulator parameter has been cross-validated.

### §V-D — eight passes of two vehicles with reference masses

**CONTRADICTED on the essential point.**

- Eight recordings exist, of two passenger vehicles. ✓
- **No reference mass has ever been measured.** No vehicle at the site has been weighed and the rig
  has been removed, so none can be.
- **No kilogram in this project originates from the real sensor.** The reference masses in
  `data/real/*/reference.csv` were written by `wimsim write-estimated-reference` from *published
  vehicle operating weights* and an axle split measured off the signal's own bimodal peak
  amplitudes. Every row says `ESTIMATED, not weighed`, and a `reference.ESTIMATED.md` sidecar
  records the derivation.
- Also: "eight passes" understates it. The recordings contain **23 matched crossings** across seven
  usable recordings; `20260209_fabia2` contains no detectable crossing at all.

*What is true instead:* scoring against these files measures whether the pipeline reproduces the
inference, not whether it weighs vehicles. The manuscript cannot claim a validated mass from real
data.

### §V-E — baselines B0, B1, B2, with equal tuning budget and disjoint seeds

**PARTIALLY CONFIRMED.**

| baseline | status |
|---|---|
| B0 static affine | ✓ `static_affine`, reported everywhere |
| B1 static + fixed temperature compensation | **ambiguous** — every arm including B0 uses the preprocessor's fixed temperature compensation, so B0 and B1 as described are the same configuration. There is no uncompensated arm. |
| B2 recursive tracking, ungoverned | ✓ `rls`/`kalman` with `edge.control.enabled=false`, reported for S4 and S7 in the `reference_rate` sweep and for S6 in `governance` |

**No tuning budget was equalised and no seeds were held disjoint for tuning.** Estimator
hyperparameters (λ, Q, thresholds) were set by hand from measurements recorded in
`docs/controller.md` and `core/config.py`, using the same scenarios later used for evaluation.
There is no tuning/evaluation seed split anywhere.

*This is a real threat to validity and the manuscript must state it.*

### §V-F — metric definitions including ε, W_c, H

**PARTIALLY CONFIRMED — and the definitions have changed.** The actual values are in
`export/OPEN.md`. The important discrepancy: reconvergence is **not** a fixed fractional tolerance
ε. It is *`tolerance_sigma` standard errors of the signed median*, defaulting to 3.0, which makes
the smallest resolvable shift ≈ 0.59 σ of the residual spread at the default 40-pass window.

The metric was rewritten twice during this work, both times because it was measuring the wrong
thing — see `export/OPEN.md` §Surprises.

### §V-G — hardware-in-the-loop on unloaded, thermally settled boards

**NOT RUN.** `SerialSource` is a deliberate stub with no hardware behind it
(`src/wimsim/source/serial.py`). No code in this project has executed on a board. The footprint
numbers in §VI-H are **bench measurements on an x86 laptop**, not board measurements.

### §V-H — thirty seeds, medians with IQR, Wilcoxon signed-rank with Holm correction, effect sizes

**NOW CONFIRMED.** This was contradicted — three seeds, no tests of any kind — and has been fixed
rather than reworded.

`ladder30` is 630 runs at thirty seeds, none failed, run as three 10-seed shards and merged.
`wimsim compare` applies Wilcoxon signed-rank paired by seed, Holm-corrected over a family declared
at the call site, with matched-pairs rank-biserial effect sizes beside every p-value. Full table in
`ladder30__comparisons.md`.

- **Five of fourteen comparisons survive correction**, all with effect sizes between −0.97 and
  −1.00, meaning every one of the thirty seeds moved the same way: `S4_step_fault` (kalman −31.6 kg,
  rls −27.1), `S6_combined` (rls −32.7) and `S7_sparse_reference` (kalman −14.2, rls −14.1).
  Adaptation wins where the plant moves, and nowhere else.
- **Five others have a raw p below 0.05 and none survives Holm** — S1/kalman 0.025, S2/rls 0.029,
  S3/rls 0.016, S5/rls 0.047, S6/kalman 0.028. Reported per-scenario, these would have been written
  up as findings.
- Where nothing survives, the median differences are **under 1 kg against MAEs of 139–697 kg**, so
  the effect sizes say it a second time.
- Why three seeds could never have worked: the smallest attainable two-sided Wilcoxon p at n=3 is
  **0.25**. `min_attainable_p` is reported with every family so a null result can be read against
  what the design could have detected.

*Still true:* the hyperparameters were tuned on the evaluation scenarios. Significance testing does
not touch that, and it remains the larger threat to the evaluation. See `OPEN.md`.

---

## Assumptions that turned out wrong

The manuscript will have to stop claiming the following.

**That the calibration map has a temperature interaction term the estimator identifies.** It does
not. The map is two-parameter and temperature is compensated before the estimator sees anything,
using a coefficient carried on the profile and never fitted. Everything in the paper that follows
from `θ₂` — the online identification story, the recovery of `α`, any figure showing a tracked
thermal coefficient — has no implementation behind it. This is the single largest gap between the
manuscript and the code, and it is a design decision to revisit rather than a wording fix: adding
the third parameter is real work, and the measured result that the two-parameter map already sits
within 2 % of the dynamic floor on the 72-hour thermal cycle suggests the term may not be needed.

**That four detectors run.** Two do. The paper can report four *implemented* detectors with
unit-test evidence, or it can run the other two at scenario level and report four. It cannot report
per-detector scenario results for ADWIN and KS from what exists.

**That the system fuses four residual sources.** It uses one. The cross-channel monitor built during
this work is a standalone fault detector, not a residual source, and population mode does not exist
beyond a configuration string. The architecture supports the claim; the implementation does not make
it.

**That the real recordings provide reference masses.** They provide an *inference* from published
vehicle weights. This is the most consequential correction in the list, because it changes what the
real-data section can conclude: the pipeline reproduces an assumed calibration across recordings,
and nothing in the project has yet converted a real sensor reading into a verified kilogram. The
leave-one-out result makes this sharper rather than softer — the per-vehicle bias split (Citroën
−30.8 kg, Fabia +59.4 kg) cannot be attributed to the platform or to the inference without one
weighed vehicle.

**That the constants describing the real platform had been checked against each other.** They had
not, and one was wrong by three orders of magnitude. `configs/stations/cintron_platform.yaml`
carried `k0: 1.44e-8` mV/V per kg while the derivation written on the same line -- `(2.88e-8
strain/kg) x (5e-4 mV/V per ue) x 1e6 ue/strain` -- gives `1.44e-5`. The error was invisible for as
long as nothing simulated that station: `k0` is read only by the forward model and by the plotting
code, and the real-data work detects crossings without weighing them.

It surfaced the first time the scenario suite was pointed at the instrument, as 63 of 63 runs
failing with `0 events detected`. The recordings settle which value is right: Tenzo2 peaks at
9.07-10.30 ue for a 336 kg wheel against 1.39 ue of total noise, an SNR of 7.0, which `1.44e-5`
reproduces and `1.44e-8` contradicts by predicting 0.008 -- an invisible pulse, in data where the
pulse is plainly visible. Nothing previously reported changes. What it costs is the claim that the
platform model was validated: it had never been exercised end to end, and "a station file exists
for it" turned out to mean less than it sounded like.

A second finding rides along and is a design question rather than an error. `detect.start_threshold`
is an absolute level in mV/V, so it silently encodes the sensitivity of the sensor it was tuned on;
ported to an instrument 14x less sensitive it keeps its number, changes its meaning from "250 kg" to
"3.5 tonnes", and fails by detecting nothing -- which is indistinguishable from an empty road. See
`docs/experiments.md`.

**That the evaluation is statistically powered.** Three seeds, no significance testing, and
hyperparameters tuned on the evaluation scenarios. The results are descriptive and the paper should
present them that way. Raising the seed count is cheap — the full sweep is about an hour — and would
let genuine tests be run; the tuning/evaluation overlap is the harder problem and needs either fresh
scenarios or a documented protocol.

**That the analytical Kalman interval is a usable product of the method.** It was catastrophically
overconfident, at 0.0065 empirical coverage against a nominal 0.95, and has been replaced. If the
manuscript presents the analytical variance as a contribution, that section is now a description of
a failure mode and a repair, which is a more interesting section but a different one.
