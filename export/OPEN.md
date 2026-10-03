# State of the project

Commit `f40ca51`. Test suite last run with the full docker stack up.

---

## What the 2026-09-24 reruns superseded, and what they did not

Two sweeps were re-run after the rest of this export was generated: `cintron_ladder30` (the
influence-line ladder at thirty seeds) and `reference_rate_ph75` (the governance sweep at the
corrected Page-Hinkley threshold). Nothing else was re-run, deliberately. That leaves some artifacts
in this export superseded and most of them untouched, and the difference has to be explicit rather
than inferred from timestamps.

### Superseded — still present, no longer the best evidence

| artifact | superseded by | why |
| --- | --- | --- |
| `cintron_ladder__comparisons.md` | `cintron_ladder30__comparisons.md` | three seeds; every null verdict was a statement about seed count, the surviving effects were overstated by up to 23 %, and `S6_combined`/kalman had the **wrong sign** |
| `figures/cintron_ladder__*.png` (5) | `figures/cintron_ladder30__*.png` (5) | same data at three seeds instead of thirty |
| `data/cintron_ladder_long.csv` | `data/cintron_ladder30_long.csv` | superset: same grid, 630 rows against 63 |
| `figures/reference_rate__*.png` (15) | `figures/reference_rate_ph75__*.png` (6) | **for the governance question only.** The threshold-15 figures remain the record of what the *shipped* configuration did, which is a different and still-valid question |
| `reference_rate__comparisons.md` | `reference_rate_ph75` §8 in RESULTS.md | as above: superseded as evidence about governance's best configuration, not as evidence about the shipped one |

The superseded files are kept rather than deleted. The three-seed influence-line run is the reason
the thirty-seed one was commissioned, and the threshold-15 reference-rate sweep is what the
correction is measured against.

### Unaffected — nothing about these changed

`ladder`, `ladder30`, `governance`, `theta2`, `recal_coverage`, `detectors`, `detector_thresholds`,
and every figure, CSV and table derived from them. None of them shares a grid with either rerun.

Two points of care for anyone comparing across them:

* **`ladder30` and `cintron_ladder30` are directly comparable.** Both ran Page-Hinkley at 15.0 — the
  latter pins it explicitly for exactly this reason — so they differ in the instrument and in
  nothing else.
* **`reference_rate` and `reference_rate_ph75` differ in the threshold and nothing else.** Same
  scenarios, estimators, seeds, rates, arms and calibration budget.

### The shipped default has moved, so these configs no longer reproduce these numbers

The Page-Hinkley default is now 7.5. Every sweep in this export except `reference_rate_ph75` ran at
15.0, and the experiment configs mostly say `edge_config: default`, which now resolves to 7.5.
**Re-running them will not reproduce their stored numbers.** The mismatch is detectable rather than
silent — every row carries `edge_config_hash` — and RESULTS.md carries the table of which sweep ran
at which threshold. `configs/estimators/detect_ph.yaml` is pinned at 15.0 so the detector ladders
keep a fixed baseline.

## What the 2026-10-02 final sweep superseded, and what it did not

Part A is reanalysis of stored data and adds no runs, so it supersedes *readings* rather than
files. B2 is new analysis of the eight real recordings. C is blocked. D was not started.

### Superseded — still present, no longer the best evidence

| artifact | superseded by | why |
| --- | --- | --- |
| §VI-G "Detection collapses with the rate" | §A1 | at Page-Hinkley 15.0, and the corrected 7.5 changes the **shape** of the curve rather than only its level: `S7_sparse_reference` is non-monotone at 15.0 and monotone at 7.5, with one cell moving from 1 fault caught in 9 to 9 of 9. The old table also reports counts with no detection delay beside them, and the delay is what shows the mechanism |
| the elimination argument in §VII-C | §A1 | the reference rate is now *measured* as the binding constraint rather than reached by excluding everything else, and the measurement locates the failure between one reference in ten and one in twenty rather than merely attributing it |
| §V-C's "no simulator parameter has been cross-validated" | §B2 | eight folds; the noise parameters cross-validate and the event shape does not |
| **§A1's zero crossing** | **§B1** | **withdrawn.** At fifteen seeds recall is 0.200 at one reference in twenty and 0.067 at one in fifty on S7 — above zero at every rate run. The three-seed zeros were sampling zeros |
| **§A1's monotonicity** | **§B1** | holds on S7 at power and **not** on S4, whose one-in-ten cell sits above its one-in-five |
| **§A2's S7 governance effect** | **§B1** | the −17.62 kg at one reference in ten is 0.00 at fifteen seeds, with eight of fifteen pairs byte-identical |
| `reference_rate__*` and `reference_rate_ph75__*` figures and sidecars | `reference_rate30__*` | three seeds against fifteen, and five rates against seven. Kept: they are the record of what was run, and the gap between them and B1 is this export's clearest evidence for why three seeds are not enough |

### Unaffected — nothing about these changed

Every accuracy, coverage, reconvergence and footprint number in §VI-A to §VI-F and §VI-H is
untouched. `ladder30`, `cintron_ladder30`, `theta2`, `recal_coverage`, `detectors`,
`detector_thresholds` and `governance` are unaffected as results, as are their comparison files
and long-format CSVs.

No stored parquet was modified by any part of this sweep. Three sweeps were **added**
(`heldout30`, `ablation`, `reference_rate30`) and the `reference_rate` and `reference_rate_ph75`
directories gained two figures and three sidecar files each, all drawn from their existing rows.

**Every figure in the export was re-rendered** at 300 dpi from its stored parquet, because the
code wrote 150 while `figures/FIGURES.md` claimed 300. Only the rendering changed. Twenty-six
stale PDF and SVG files were deleted: they were produced by figure code that no longer exists and
could not be verified against the current parquets.

### A correctness note about every sweep run after 2026-10-03

`Preprocessor._track_zero` was made 1.6× faster on 2026-10-03. The change is **bit-identical**:
one partition now serves the four order statistics that two numpy calls used to compute, with
`_lerp` reproduced exactly including its branch. Verified over 4,000 random windows and against a
full 16 h run whose 48 result columns, config hash and edge-config hash all compare equal to the
pre-change run. Sweeps run before and after that commit are therefore directly comparable, which
is the only reason the change was made rather than deferred.

### Still not done, and what it would take

**`reference_rate30` ran fifteen seeds, not the thirty the brief asked for.** Compute, not
judgement: the sweep took 28.3 h for 1260 runs. At n = 15 the minimum attainable two-sided
Wilcoxon p is 6.1e-5, so it is powered rather than provisional, and the one comparison that
matters most cleared a 42-test Holm correction at p = 0.0077. Seeds 16–30 were not run.
`configs/experiments/reference_rate30.yaml` and the shard scripts are in place; running them and
merging requires re-running nothing, and `merge_shards` will refuse the merge if the commit has
moved.

**Where recall actually reaches zero is still not located.** B1 withdrew the three-seed answer
rather than replacing it. On S4 the crossing is now bracketed between one reference in twenty and
one in fifty, a factor of 2.5. On S7 it is **outside the grid entirely** — recall is still 0.067
at one in fifty, the sparsest rate run — so the ladder would have to be extended to one in a
hundred or beyond to find it, and at 0.067 a cell needs far more than fifteen seeds to separate
from zero. A rate of 15 would no longer help; the useful additions are at the sparse end.

**Why recall tops out at 0.611 on S4 with every vehicle a reference is unexplained.** That is a
property of the detector or of the confirmation gate, not of reference supply, and nothing in
this project isolates which. It bounds every claim about what more references would buy.

**The held-out set is not matched in difficulty to the development set.** H1 lands at 5.7× the
dynamic floor where its counterpart S2 is at 1.02×, and H3 at 2.5× against S7's 1.1×; H2 and H4
are comparable to theirs. The two classes whose comparisons fail to reproduce are exactly the two
drawn harder, so "does not generalise" is confounded with "does not extend to harder instances",
and B4 cannot separate them. **The experiment that would:** a second held-out draw for the thermal
and slow-ramp classes with parameters tuned to land at a comparable multiple of the floor, which
one pilot seed per candidate is enough to check before committing thirty. This is the single most
useful run this sweep leaves undone.

**Why the Kalman filter adds variance is not established.** B3 and B4 agree that it is a fixed
cost paid wherever there is nothing to track, and they differ eightfold on its size (+29 kg
against +251 kg) on different instruments and thermal amplitudes. Nothing here varies the filter's
Q or R, which is where the answer would be.

**No single-component explanation for the S6 divergence exists, and the ablation could not have
found a partial one.** All eight difference-in-differences came back null at ten seeds with
inconsistent per-seed signs. A twenty- or thirty-seed ablation would resolve shifts of the size
observed (~20 kg); ten did not.

**`estimator_cost` has no CLI entry point.** The footprint figures in §VI-H were produced by
calling `wimsim.experiments.control_scoring.estimator_cost` directly. "Run the existing footprint
harness on the board" therefore means writing a short script on the board rather than running a
shipped command, which is friction between the project and the one measurement §IV-K needs. A
`wimsim footprint` command would remove it; it was not added because the brief said to stop at
BLOCKED.

**`gap-report`'s fitted `--set` lines are in the recording's units, not the station's.** See
`CONTRADICTIONS.md`. A latent factor of 500 on this corpus. No reported number went through that
path and `sim_crossval.py` converts explicitly, so this is a hazard rather than an error, and it
is reported rather than fixed per the working agreement.

**The baseline increment distribution has no model.** B2 measured excess kurtosis from +1.5 to
+1698 in the real recordings against the Gaussian 0 the simulator produces. `zero_drift` offers a
Gaussian walk, a linear slope and a Poisson step process; nothing in a sixty-second recording
separates a settling step from a residual crossing edge, so the step process could not be fitted
here either. Closing this needs longer recordings, not a different estimator.

**The simulator's zero-line fit overshoots by 2.1× and the procedure is still in use.**
`docs/sim-to-real.md` assigns the whole measured increment spread to the random walk, and the
model also moves its zero line through 1/f noise and thermal coupling. The correction is
arithmetic — subtract the other contributions in quadrature — but applying it would change the
shipped scenario parameters and therefore every stored result, so it is recorded and not applied.

**Population mode is still a label.** D1 is a scoping note in `RESULTS.md` and nothing else; no
code was written for it.

**No board.** §IV-K and §V-G are unchanged.

---

## Constants

The values actually in the code, not the intended ones.

### Reconvergence — what §V-F calls ε

There is **no fractional tolerance ε**. Reconvergence is defined on the *signed* median of the mass
error, and the threshold is a statistical one:

```
recovered  when  |rolling signed median − pre-fault signed median|  ≤  tolerance_sigma × 1.2533 × σ / √window
```

| constant | value | where |
|---|---|---|
| `tolerance_sigma` | **3.0** | `experiments/control_scoring.py`, `time_to_reconverge` |
| `window` | **40 passes** | same |
| `hold` | **40 windows** (defaults to `window`) | same |
| implied smallest resolvable shift | **≈ 0.59 σ** of the residual spread | `1.2533 × 3.0 / √40` |

`tolerance_sigma` is deliberately the same test the controller uses to decide drift has *occurred*
(`RecalibrationController._displaced`), so the metric and the loop agree on what "moved" means. The
default matches the loop's `confirm_sigma`.

**Recovery also requires a departure first**, sustained for `hold` windows. Without that, a fault
that ramps over hours is trivially "back at baseline" in its first window.

### Confirmation window — §V-F's W_c

| constant | value | where |
|---|---|---|
| `confirmation_passes` | **60** | `edge.control` in `configs/estimators/default.yaml` |
| `confirm_sigma` | **3.0** | same |
| `min_reference_observations` | **10** | same |
| `cooldown_s` | **3600** | same |
| `drift.warmup` | **60** references | `edge.drift` |
| detectors actually enabled | **`cusum`, `page_hinkley`** | `edge.drift.detectors` |

### Detection horizon — §V-F's H

`fault_horizon_s = 1800` (30 minutes), set per sweep in `configs/experiments/*.yaml`. An alarm
counts as answering a fault only if it lands after the fault and inside this horizon; an alarm
before the fault is a false alarm, never a prophecy.

### Seeds

**Three: 1, 2, 3.** Not thirty. Every reported figure is over three runs.

### Were these fixed before the runs, or chosen afterwards?

**Honestly: several were chosen afterwards, and the paper cannot claim otherwise.**

| constant | when set | how |
|---|---|---|
| `confirm_sigma = 3.0` | **after** measurement | started at 1.0, which gave a 32 % false-confirmation rate by construction; raised to 3.0 after measuring 0/30 blips confirmed. `docs/controller.md` |
| `confirmation_passes = 60` | **after** measurement | window 30 gave 0 recalibrations and −136.9 kg bias on S4; 60 gave 2 and −9.4 kg; 90 gave −23.8 kg. Chosen from that sweep. |
| `drift.warmup = 60` | **after** measurement | was 200, which at `reference_every_n=10` made detectors ready only 33,144 s into a 57,600 s run — zero alarms on S4 |
| Kalman prior `(1.0, 1.0e-2)` | **after** measurement | the original `(1e-2, 1e-6)` was ~200 σ too tight |
| `tolerance_sigma = 3.0`, `window = 40` | **after** — the metric was rewritten twice during this work | see Surprises below |
| `fault_horizon_s = 1800` | before | stated as deliberately generous when the sweep was written |
| seeds 1, 2, 3 | before | fixed in the experiment YAML |

All of the tuning above used the same scenarios later used for evaluation. **There is no
tuning/evaluation split.** This is the most serious threat to validity in the project.

---

## Instrument

**All reported synthetic results (S1–S7) used `configs/stations/default.yaml`** — the contact-force
model: pulse width = tyre contact patch ÷ speed, milliseconds long, positive-going.

`configs/stations/cintron_platform.yaml` models the real instrument — a strain platform whose
response is an influence line, ~770 ms wide, negative-going — and is used only by the real-data
commands (`detect`, `score-real`, `score-corpus`, `check-channels`). **No synthetic scenario has
been run on it.** Both models exist; only one was exercised in the reported experiments.

---

## Missing measurements

| | status |
|---|---|
| gauge separation | **obtained** — 126 mm, supplied by the station owner, with one gauge parallel to the road and one rotated 90° |
| a weighed vehicle | **still missing.** None exists, the rig has been removed, and none can now be obtained |
| road-speed recording | **still missing.** Speed is *inferred* at 0.62–0.95 m/s from the front-to-rear axle interval and the Fabia's known 2.470 m wheelbase |
| gauge factor and excitation | gauge factor 2.0 is declared in the export; **bridge configuration is not**, so strain → mV/V remains an assumption |

The two inferred quantities — wheel loads and speed — are used throughout and are labelled
`ESTIMATED` at every point of use. They were adopted on explicit instruction and are not revisited.

---

## The two-channel question

**Speed from inter-gauge delay is NOT used, and the earlier claim that it could be has been
withdrawn.**

Phase 3 reported an inter-gauge offset of 162–739 ms measured by differencing the two channels'
*peak times*, and read it as a direct speed measurement. On a ~770 ms pulse `argmax` wanders by
hundreds of milliseconds while the pulse has not moved, and its wander scales with the pulse width —
which is exactly the `r = +0.965` correlation phase 3 read as geometry.

Cross-correlating the whole crossing instead, over 26 crossings:

| | mean | correlation with pulse FWHM |
|---|---|---|
| \|peak-time difference\| | 345 ms | **+0.88** — argmax jitter, tracking the width it is measured on |
| \|cross-correlation lag\| | **9.6 ms** | +0.19 — no 1/speed scaling |

126 mm along the direction of travel would be 227 ms at 2 km/h; the measured lag implies 47 km/h,
which the one-second pulses rule out. The gauges are side by side *across* the road.

**What changed as a result:** phase 2's conclusion stands after all — a single measurement point
cannot measure speed. `peak` remains the feature for its original reason. The influence length is
unknown in metres except through the *inferred* speed. And the two-sensor work that was scoped as
"speed from delay, then speed-normalised area" has no basis; what the pair does offer is a fixed
amplitude ratio usable as a fault check, which is now implemented.

---

## Test suite

**882 passed, 17 skipped, 0 failed** (17 skips are docker-dependent and pass with the stack up —
854 passed / 0 skipped in that configuration).

| family | result |
|---|---|
| truth isolation | **8 passed** — static check that `calibration/` never imports the truth module |
| architecture | **4 passed** — numpy-only estimator core by import graph, including a negative control that the check would fail if violated |
| determinism | **9 passed** — same seed + config ⇒ byte-identical output |
| recompute correctness | **13 passed** — events re-derived under a new profile match a direct computation |
| phase-5 checkpoint | **14 passed** |

---

## Not implemented

- **Hardware in the loop.** `SerialSource` is a typed stub. No code has run on a board.
- **The temperature interaction term** `θ₂·(s·ΔT)`. The map is two-parameter.
- **Population mode.** A configuration string with no implementation behind it; no vehicle
  classification exists.
- **Zero-line and cross-channel residual *sources*.** The cross-channel monitor exists as a
  standalone fault detector, not as an estimator input.
- **ADWIN and windowed KS at scenario level.** Implemented and unit-tested; not enabled in any
  sweep.
- **Statistical testing.** No Wilcoxon, Holm, or effect sizes.
- **Kafka.** A build-spec non-goal before phase 6; still absent.
- **Simulator-parameter leave-one-out.** Fitting from recordings exists; cross-validating the fitted
  simulator parameters does not.

---

## Surprises

The results that overturned something, in the order they bit. Each of these changed a conclusion,
and several were found by the system's own measurements rather than by inspection.

### The headline control metric was measuring the wrong thing, twice

It tracked a rolling median of **|error|** against 1.5× its pre-fault level. A calibration fault is
a systematic *shift*, and the median of the absolute error barely moves when a wide symmetric
distribution slides sideways. On `S7_sparse_reference` it reported `static_affine` reconverging in
187 s while that estimator carried **−96.7 kg of bias on a 158 kg spread**. The calibration had not
recovered at all.

Switching to the signed median did not fix S7. The statistic was never the problem there: S7 ramps
its fault over two hours, reconvergence is timed from the fault's start, and 187 s in the error has
not moved — so the first window was trivially "back at baseline" and the metric announced recovery
from a disturbance that had not arrived. Recovery now requires a departure first, sustained.

Every number moved, and all in the same direction:

| | old | corrected |
|---|---|---|
| S4 static_affine | 3758 s | 12409 s |
| S4 kalman | 870 s | 3406 s |
| S7 static_affine | 187 s | 5104 s |
| S7 kalman | 187 s | **never departed** |

Kalman never departing on S7 is the informative one: it absorbed a two-hour ramp as it happened, so
there was no excursion to recover from. The old definition called that a fast recovery.

### An interval that stopped being an interval, and the first explanation was wrong

The reference-rate sweep found Kalman at one reference in fifty with the **best MAE of the three
estimators and coverage 0.754**. The first hypothesis recorded here was a small, stale conformal
calibration set. That was plausible and it did not survive being checked.

Splitting coverage by `interval_source` — a field the events had carried since phase 5 — said what
actually happened: **841 of 3392 events carried a construction the configuration had not asked
for**, at coverage 0.007, while the configured conformal interval covered at 1.000. Conformal was
never the problem. The pipeline falls back to the estimator's own analytic band until conformal has
its 19 references, and for the Kalman filter that band is the one phase 5 had already measured at
0.0065 and chosen conformal *specifically to avoid*. A default picked to avoid a known failure was
silently reinstating it.

Fixing the construction rather than routing around it took two more corrections, both found by
measurement: the residual must be in kilograms rather than feature units, and it must not be
accumulated while the filter is still converging — at an EWMA memory of 0.98 the first residual
still carries 3e-4 of its weight after 400 updates, which left a filter whose true spread was 0.5 kg
reporting **603 kg**. The warm-up that fixed that then caused a second hole at sparse reference
rates, closed by seeding from the batch fit's own residuals. Fallback coverage went
**0.007 → 0.354 → 0.926**.

### A diagnostic column, added for the above, measured something nobody had looked at

`n_interval_fallback` showed that **every recalibration reopens the conformal warm-up window**,
because `conformal.reset()` is called on activation — correctly, since the old quantiles describe an
estimator that no longer exists. On the ladder at one reference in ten: kalman 0 recalibrations and
121 fallback events, static_affine 4 recalibrations and 345. **Recalibrating improves the mass and
degrades the interval**, by an amount that had never been measured.

### Two columns full of NaN

`coverage_expected` and `n_interval_fallback` were added to the row template and not to the row
*builder*, so a 180-run sweep produced the evidence columns for a finding, empty. A column that is
always null is worse than a missing one, because it looks measured. A test now asserts every
declared column is filled.

### The real recordings detected nothing, for four separate reasons

With the shipped pipeline, `detect` found zero crossings in all eight recordings. Measured on
`20260209_cintron1/Tenzo1`:

1. **Scale** — `start_threshold: 0.05` is four orders of magnitude above a 7 µε excursion.
2. **Bandwidth** — no low-pass, so at 25 kHz the compensated signal crosses any workable threshold
   ~90,000 times in 60 s.
3. **Zero line** — a 2 s trailing median against a 1.7 s crossing *is* mostly vehicle, so the
   tracker followed the pulse and subtracted it.
4. **Polarity** — the crossings pull the signal *down*, and the detector opens on a rise.

The third is the same class of error as a phase-3 bug in the real-data validator: a statistic
contaminated by the thing it is measuring. With all four addressed, the detector finds crossings on
14 of 16 channel-runs, and on cintron1/Tenzo1 it is the same event, at the same time and width, that
`gap-report` fits by a completely independent method.

### The pooled real-data bias is a lie, and the folds are what say so

Leave-one-recording-out over the corpus: **pooled bias +0.2 kg, mean |fold bias| 40.5 kg**. Every
fold is systematically wrong and they cancel. By vehicle: Citroën −30.8 kg, Fabia +59.4 kg. The two
vehicles do not sit on one calibration line.

The channel-ratio measurement then narrowed it: the ratio is **2.98 ± 0.37 on the Citroën and
2.78 ± 0.34 on the Fabia**, one ratio within the noise. One gauge is transverse to the other, so a
vehicle sitting differently on the plate would move it — it does not. The two cars load the platform
the same way, which removes a geometric explanation and leaves an error in the Citroën's inferred
mass as the better candidate. Not proof: the ratio is mass-independent by construction.

### Smaller ones, each of which changed a number

- **`ReplaySource` could not open a single real recording.** It read `adc_range` unconditionally;
  the schema makes it optional for anything that is not raw counts, which is what `import-csv`
  writes. The schema said one thing and its only consumer said another.
- **`scipy.signal.group_delay` is the inaccurate one** at low cutoff-to-rate ratios — 0.19 % out at
  2 Hz on 25 kHz, and noisy about it. The closed form `Σnb/Σb − Σna/Σa` is exact and silent.
- **`StaticAffine` returned a gain of −8.03 × 10⁶** on two crossings with nearly identical features:
  a scale reporting heavier vehicles as lighter, emitted without complaint. The degeneracy guard
  caught *exactly* identical features and this pair merely came close.
- **A hardcoded default epoch** in the estimated-reference writer placed seven of eight files
  300–400 s before their own recordings began. Nothing complained because nothing read them yet.
- **The pulse-shape fitter identified a Gaussian as a raised cosine**, because it subtracted the
  median of a window that was mostly pulse.
- **Every Prometheus metric was silently renamed by the exporter** (`wim_buffer_depth` →
  `wim_buffer_depth_ratio`), so every dashboard panel queried a series that did not exist.
- **`measurement_event.temperature_c` was always null** — the estimator took a `temp_c` nobody
  passed.
