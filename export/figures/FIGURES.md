# Figures

**80 PNGs at 300 dpi.** Named `<sweep>__<figure>.png`. Nine figure kinds across fourteen sweeps;
a figure is drawn only for a sweep whose grid supports it, so the absence of a file is
informative rather than an omission. Each sweep's own captions are in
`data/results/<sweep>/figures/README.md`, generated beside the PNGs from the same source as the
descriptions here.

**PNG only.** Earlier versions of this export also carried PDF and SVG for three sweeps. Those
were renders produced by figure code that no longer exists and were therefore unverifiable
against the current parquets; the rebuild deletes them and records how many it removed in
`data/manifest.json`.

Common to all of them:

- **Markers are per run, never averaged.** Lines, where present, are medians across seeds.
- **Marker shape distinguishes the estimator** as well as colour, because these get printed.
- **The title carries the run count** — `[ladder30 -- 630 of 630 runs]` — so a figure pasted into
  a slide still says how many runs are behind it and how many failed.
- **No timestamp in the metadata**, so two renders of the same data diff as identical.
- A figure with nothing to draw is **not written at all**.

**Sample size varies by sweep and is not interchangeable.** `ladder30`, `cintron_ladder30`,
`heldout30` and `theta2` are 30 seeds; `reference_rate30` is 15; `ablation`, `detectors`,
`detector_thresholds` and `recal_coverage` are 10; `ladder`, `cintron_ladder`, `governance`,
`reference_rate` and `reference_rate_ph75` are 3. **Three seeds cannot produce a significant
result**, so markers from those five sweeps are dispersion and nothing more.

---

## `*__accuracy` — 14 sweeps

**Plotted:** MAE divided by the dynamic floor, log y-axis, against scenario on x.

- **y:** MAE ÷ dynamic floor, dimensionless. A dashed line at `1.0` is annotated *"the floor:
  error the vehicles brought with them"*. Ticks are labelled `1x`, `1.1x`, `1.25x`, …
- **x:** scenario, categorical, estimators offset within each scenario.
- **series:** one colour and marker per estimator.
- **n:** one marker per run; see the sweep's seed count above.

**The point.** The floor is the load error the vehicles brought with them, which no calibration
can remove, so the distance above `1.0` is the only part any method can compete for. Scenarios
with no dynamic load have no floor to divide by and are absent rather than drawn at zero.

## `*__coverage` — 14 sweeps

**Plotted:** empirical coverage of the prediction interval against its nominal target.

- **y:** fraction of events whose true mass fell inside the interval, dimensionless, 0–1. The
  dashed line is the configured nominal (0.95).
- **x:** scenario, categorical, estimators offset.
- **n:** one marker per run.

**The point.** Above the line is conservative; below it is an interval that promises more than it
delivers. An accuracy figure alone cannot distinguish a good estimate from a lucky one.

## `*__reconvergence` — 14 sweeps

**Plotted:** seconds from the first injected fault until the signed median error returned to its
pre-fault band and stayed there.

- **y:** seconds. **x:** scenario, categorical. **n:** one marker per run.

**The point.** The headline control metric. Scenarios with no faults are absent rather than drawn
at zero; runs that never reconverged are **counted in the axis label** rather than dropped,
because dropping them makes a system that never recovers look identical to one that was not
measured.

## `*__detectors` — 14 sweeps

**Plotted:** detection recall against false alarms per hour of simulated operation.

- **y:** recall, fraction of injected calibration faults answered inside the 1800 s horizon.
- **x:** false alarms per hour, 1/h. **n:** one marker per run.

**The point.** The trade-off an operator actually faces; either axis alone can be made perfect by
a detector that is useless in the other direction. Scenarios with no injected fault have
**undefined** recall and appear on the false-alarm axis only, as ticks *below* the zero line —
undefined is not zero.

## `*__recal_tradeoff` — 13 sweeps

**Plotted:** three panels against the number of recalibrations a run performed (count, x on all
three).

- **left y:** delivered coverage, fraction, with the nominal as a dashed line.
- **middle y:** share of events emitted on the estimator's fallback interval, fraction.
- **right y:** MAE ÷ dynamic floor, dimensionless.
- **n:** one marker per run.

**The point.** A recalibration has a cost and a benefit and they are in different panels. The
left panel alone shows recalibration as pure cost, the right alone as pure benefit. The x axis is
the **measured consequence** of `confirm_sigma`, not the setting.

## `*__reference_rate` — 3 sweeps (`reference_rate`, `reference_rate_ph75`, `reference_rate30`)

**Plotted:** MAE ÷ dynamic floor against how often a reference vehicle arrives.

- **x:** reference interval, log scale, labelled `1 in N`. **y:** dimensionless.
- **series:** one colour per estimator; **solid** is the loop on, **dashed** is the loop off, over
  the identical sample stream.
- **n:** one marker per seed per rate.

**The point.** The gap between a solid and dashed pair of the same colour is what the control loop
is worth at that rate. Where they meet it is worth nothing and the estimator is doing the work
alone.

## `*__recall_vs_rate` — 3 sweeps *(new 2026-10-02)*

**Plotted:** two rows against reference interval (log x, labelled `1 in N`).

- **top y:** mean detection recall, fraction. One line per estimator plus a **heavy black line
  pooled over all of them**, labelled with its per-cell run count. Open grey circles are the
  per-run recalls, so the sample is visible rather than asserted.
- **bottom y:** detection delay in **seconds** from fault onset — median across the runs that
  detected anything, with the interquartile range as a band. A run that detected nothing
  contributes no delay rather than a zero.
- **n:** 9 runs per cell at 3 seeds, 45 at 15 seeds. Stated in the pooled line's label.
- **Governed arm only**: with the controller disabled the detectors are never constructed, so the
  ungoverned runs carry structural zeros rather than misses.

**The point.** Detection is not uniformly broken — it works at dense reference rates and degrades
with a *measurable* delay before it fails. On `reference_rate30` the bottom panel is the stronger
half: delay reaches 1697 s against an 1800 s horizon at one reference in twenty, i.e. detection
arrives at the moment it stops counting.

## `*__governance_vs_rate` — 3 sweeps *(new 2026-10-02)*

**Plotted:** two rows against reference interval (log x, labelled `1 in N`).

- **top y:** governed − ungoverned **MAE**, kg. Negative is the loop helping.
- **bottom y:** governed − ungoverned **signed bias**, kg. Drawn beside the error and never folded
  into it, because the loop can improve MAE while pushing bias through zero and out the far side.
- **series:** one colour and marker per estimator; the line runs through the per-seed medians and
  each open marker is one seed, so a median of zero over a cell that is not uniformly zero is
  visible as such.
- **A dashed line at zero** is annotated *"the loop changed nothing"*, which is where both adaptive
  estimators sit at every rate.
- **n:** one marker per seed; the legend states the count.

**The point.** The loop is worth tens of kilograms to frozen calibration at dense reference rates,
decays to nothing as references thin, and is worth nothing at any rate to an estimator that
already tracks.

## `*__detector_curve` — 2 sweeps (`detectors`, `detector_thresholds`)

**Plotted:** recall against false alarms per hour, with each detector's threshold stepped from the
shipped value through three more sensitive ones (four for ADWIN, whose knob is logarithmic).

- **x:** false alarms per hour, 1/h. **y:** recall, fraction. **n:** medians across 10 seeds.
- **series:** one line per detector, one marker per threshold, **ordered by the false-alarm rate
  actually measured** rather than by the setting — the knobs run in opposite directions, since a
  *lower* CUSUM threshold and a *higher* KS alpha are both more sensitive.

**The point.** The trade-off curve rather than the single point the shipped configuration sits on.
The detector each arm is drawn for is read from the detectors it **runs**, not from its name.

---

## What is *not* here

- **No error bars anywhere.** Markers are the dispersion. At three seeds an interval would be
  wider than the data.
- **No figure for the real recordings.** `sim_crossval.md` reports them as tables; eight
  sixty-second recordings do not support a figure that says more than the table does.
- **No footprint figure.** Three numbers per estimator on one host is a table.

---

# Paper figures (narrowed paper)

Nine figures for the paper that keeps the ladder comparisons, the instrument transfer, the
held-out set, the S2 bias result, the floor decomposition and the footprint, and drops the
detector work, the reference-rate curve, governance, conformal intervals and the design rule.

**The claim they serve:** *tracking reduces error where the recoverable excess is large relative
to the dynamic-load floor, and not otherwise.*

All nine are 300 dpi PNG, written by `scripts/paper_figures.py`, deterministic (bootstraps use a
fixed seed, no timestamp in the metadata). Every figure has a `.csv` of the exact numbers plotted
in `export/data/`.

**This supersedes the "No footprint figure" note above.** F13 exists because the paper needs it;
the earlier judgement that three numbers per estimator is a table stands as a judgement about the
*sweep* figures, not this set.

---

### F2 — `F2__error_decomposition.png` · the central figure

- **Upper panel.** x: the seven development scenarios. y: median absolute error, kg, linear.
  Two stacked bars per scenario — left frozen (`static_affine`), right the best tracked arm.
  Each bar stacks the **dynamic-load floor** (grey) under the **recoverable excess** (hatched
  grey frozen, blue tracked).
- **Lower panel.** Same x. y: the recoverable excess *alone*, kg, **log scale**, because S6's
  506 kg excess is 500× S1's and a linear axis hides every other scenario. Annotated with the
  fraction of the excess the tracked arm recovers and, under each tick, the excess as a multiple
  of that scenario's own floor.
- **Sample size:** 30 seeds per scenario per arm, `ladder30`; all points are medians over seeds.
- **The point:** the floor is most of the error nearly everywhere, and it is irreducible. What
  tracking can win is only the hatched part. Tracking recovers **67 %** of it on S4 and **82 %**
  on S7, where the excess is 0.34× and 0.13× the floor; it recovers **6 %** on S6, where the
  excess is 2.65× the floor but the disturbance is not of a kind a gain-and-zero model removes;
  and on S2, S3, S5 the excess is 0.02–0.03× the floor, so there is nothing to win and nothing
  is won.

### F4 — `F4__effect_sizes.png`

- x: matched-pairs rank-biserial correlation, dimensionless, −1 to +1; negative means the tracked
  arm beat the frozen one. y: the fourteen ladder comparisons, **ordered by that scenario's
  recoverable excess in kg**, largest at the top. Each label carries the excess in kg and as a
  multiple of the floor.
- Horizontal bars are **bootstrap 95 % CI, 5 000 resamples over seeds**, fixed RNG seed.
  A filled marker means the interval excludes zero. Blue square `rls`, red triangle `kalman`.
- **Sample size:** 30 seeds per comparison.
- **The point:** the ordering is the argument. The five comparisons whose intervals exclude zero
  in the favourable direction are the top of the list — S6/rls, S4/rls, S4/kalman, S7/rls,
  S7/kalman — and everything at the low-excess end straddles zero. **The one exception is
  honest and visible:** S6/kalman sits at +0.33, the wrong side, so a large excess is necessary
  for tracking to help and not sufficient.

### F6 — `F6__bias_by_scenario.png`

- Two panels sharing x (seven scenarios), three bars each (the three arms).
  Upper y: **signed** bias, kg, linear. Lower y: **absolute** bias, kg, symlog (linear below
  1 kg) because the values span 0.1–25 kg.
- Error bars are bootstrap 95 % CI of the median, 5 000 resamples over seeds.
- **Sample size:** 30 seeds.
- **The point:** S2. The frozen arm carries a median absolute bias of **23.7 kg** where the
  tracked arms carry **5.7 kg** (rls) and **5.6 kg** (kalman), both at p_holm < 1e-5 — a result
  invisible in MAE, where S2 does not separate at all, because S2's MAE is 98 % floor. Sign is
  kept in the upper panel because a bias that cancels inside an absolute error is still a bias.

### F7 — `F7__commissioning_anchor.png`

- x: sensor-body temperature, °C. y: probability density, 1/°C. Two overlaid histograms on
  shared bins: the whole 72 h run, and the commissioning window alone. Vertical lines at the run
  median and the window mean, with the gap annotated.
- **Sample size:** one representative run (`S2_thermal_cycle`, seed 1), plant grid at 50 Hz;
  the commissioning window is the 60 calibration passes at 180 veh/h.
- **Verified for this figure:** the window is **20.0 minutes** and its mean sensor temperature is
  **7.53 °C** against a run median of **14.59 °C**, i.e. **7.05 °C below**. The draft's "~20
  minutes" and "7 °C below the run median" are both correct and need no change.
- **The point:** the frozen fit is taken in a 20-minute window that happens to sit near the
  night-time minimum, where the gain is **+0.146 %** from the run median. That is **+9.2 kg on
  the mean vehicle**, carried as a bias for three days because the fit is then frozen. It is the
  mechanism behind F6's S2 result.

### F9 — `F9__instrument_transfer.png`

- x: effect size on the contact-force instrument (`ladder30`). y: the same comparison on the
  influence-line instrument (`cintron_ladder30`). Both rank-biserial, −1 to +1. Identity line
  dashed; one point per comparison, labelled by scenario, shaped and coloured by estimator.
- **Sample size:** 30 seeds on each instrument, 14 comparisons.
- **The point:** a point on the identity line is a result that transferred between two physically
  different instruments. Distance from the line is the transfer gap.

### F11 — `F11__development_vs_heldout.png`

- x: effect size on the development scenario. y: the same comparison on its held-out counterpart,
  matched by the H ↔ S disturbance-class mapping (H1↔S2 thermal, H2↔S4 abrupt, H3↔S7 slow ramp,
  H4↔S6 combined). Identity line dashed. The two off-sign quadrants are shaded.
- A **red ring and red label** marks a pair whose effect changed sign — the non-reproducing ones.
- **Sample size:** 30 seeds on each side, 8 matched pairs.
- **The point:** three of the eight change sign (H1/rls, H3/kalman, H4/kalman) and are visually
  identifiable. **This figure must be read with the difficulty confound stated beside it:** H1 was
  drawn 5.6× and H3 2.4× further above their own floors than their development counterparts,
  while H2 and H4 were drawn at comparable difficulty — so non-reproduction is not separable from
  a harder draw.

### F12 — `F12__accuracy_vs_gvw.png`

- x: seven scenarios, three bars each. y: median absolute error as a **percentage of mean gross
  vehicle weight**. Horizontal shaded regions are the COST 323 accuracy classes A(5) to D(25).
- **Sample size:** 30 seeds; the mass denominator is each scenario's own fleet, 3 seeds of the
  scheduler (≈1 500–13 000 vehicles per run).
- **Two caveats printed on the figure, both load-bearing.** COST 323 classes are defined on a
  confidence interval for the mean, not on MAE, so the comparison is indicative. And they apply
  to **trucks**, whereas this fleet has a median mass of 1 555 kg and is car-dominated: against
  the ≥3.5 t subset (mean ≈24 700 kg) every bar falls by about a factor of four. Both
  denominators are in `F12_relative_accuracy.csv`.
- **The point:** in relative terms, and on the whole-fleet denominator, every scenario except S6
  sits at or below **2.95 %** — inside the band drawn for class A(5) — while **S6 reaches
  11.2 %**, inside the band drawn for class C(15). On the ≥3.5 t denominator the same figures are
  0.74 % and 2.81 %. The spread between scenarios, not the absolute class, is what the figure
  supports, for the two reasons printed on it.

### F13 — `F13__estimator_cost.png`

- Two panels, three bars each. Left y: mean time per update, µs. Right y: persisted state, bytes.
- **Sample size:** mean over 2 000 updates, **on an x86 laptop — not a board.**
- **The point:** the ladder costs 1.4 → 17.3 → 24.2 µs per update and 199 → 403 → 456 bytes of
  state. Adaptivity costs about 12× the update time of a frozen fit and roughly twice the state,
  and all three are negligible against a per-vehicle budget. The absolute numbers are not a
  deployment claim; the ratio between arms is what the figure supports.

### F14 — `F14__h1_process_noise.png`

- x: Kalman gain process noise `Q₁₁`, sd per second, **log scale**, four decades around the
  shipped 1.0e-11. y: the H1 MAE penalty against the frozen arm, kg. The ablation's **+29.3 kg**
  is drawn as a dashed horizontal reference line; the shipped Q is marked.
- **Sample size:** 10 seeds per Q value, `H1_warm_front`; all five points unanimous across seeds,
  p_holm = 0.0098.
- **The point:** the dependence **runs the wrong way**. The "fixed variance cost" account predicts
  that stiffening Q shrinks the penalty; stiffening it two decades makes the penalty *worse*
  (+256.8 → +266.6 kg) and loosening it two decades makes it *better* (+150.6 kg). Across four
  decades the penalty never approaches the ablation's reference line. The label is unsupported
  and the observation is reported as unexplained.
