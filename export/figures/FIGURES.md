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

# Paper figures (article numbering)

Written by `scripts/paper_figures.py`; 300 dpi, deterministic (fixed bootstrap seed, no
timestamps). **Each figure has a sidecar `export/figures/<stem>.md`** with its caption, the
statistic it plots, its sample and its data file. The sidecars are generated by the script from the
same numbers the figure draws, so this index carries no numbers of its own.

**Statistic, everywhere:** the median of per-seed paired differences (decision A). The difference of
medians is not used in any figure, caption, sidecar or CSV.

| Article | File | Status |
|---|---|---|
| F1 | — | pipeline diagram, to draw (not data) |
| F2 | `F2__error_decomposition.png` | regenerated: per-arm recovered %, S1 share 100 %, excess called a difference |
| **F3** | `F3__forgetting_factor_sweep.png` | **new, primary figure**: λ sweep on S2, S4, S7, 30 seeds per cell |
| F4 | `ladder30__accuracy.png` | carried over unchanged |
| F5 | `F5__effect_sizes.png` | regenerated (was F4): caption restricted to the shipped memory |
| F6 | `s2__gain_tracking.png` | carried over unchanged |
| F7 | `F7__bias_by_scenario.png` | regenerated (was F6): median signed and median absolute bias, labelled |
| F8 | `F8__fitting_window.png` | regenerated (was F7): no "covariate shift"; input trajectory now stored in `export/data` |
| F9 | `cintron_ladder30__accuracy.png` | carried over unchanged |
| F10 | `F10__instrument_transfer.png` | regenerated (was F9) |
| F11 | `heldout30__accuracy.png` | carried over unchanged |
| F12 | `F12__development_vs_heldout.png` | regenerated (was F11): adds panel (b), tuned-memory transfer |
| F13 | `F13__estimator_cost.png` | unchanged |
| F14 | `F14__h1_process_noise.png` | plot unchanged, caption rewritten |

The repo's former F12 (accuracy against GVW and COST 323 bands) is not in the article and is no
longer generated; it is in git history at 311101d.
