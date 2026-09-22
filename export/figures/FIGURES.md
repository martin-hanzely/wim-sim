# Figures

Thirteen figures, each in PNG (300 dpi), PDF and SVG. Named `<sweep>__<figure>.{png,pdf,svg}`.

Common to all of them:

- **Markers are per seed**, never averaged. Three seeds per configuration, so three markers per
  series per x position. Lines, where present, are medians.
- **Marker shape distinguishes the estimator** as well as colour, because these get printed.
- **The title carries the run count** — `[ladder -- 63 of 63 runs]` — so a figure pasted into a slide
  still says how many runs are behind it and how many failed.
- A figure with nothing to draw is **not written at all**, so the absence of a file is informative.
  `governance__reference_rate.png` does not exist because that sweep holds the rate fixed.

**No error bars anywhere.** With three seeds, markers *are* the dispersion.

---

## `ladder__accuracy` · `reference_rate__accuracy` · `governance__accuracy`

**Plotted:** MAE divided by the dynamic floor, on a **log y-axis**, against scenario on x.

- **y:** MAE ÷ dynamic floor, dimensionless. Ticks are labelled `1x`, `1.1x`, `1.25x`, … A dashed
  line at `1.0` is annotated *"the floor: error the vehicles brought with them"*.
- **x:** scenario, categorical, with estimators offset within each scenario.
- **series:** one colour and marker per estimator — kalman (circle), rls (square), static_affine
  (triangle).
- **n:** 3 markers per estimator per scenario.

**The point:** how far above the irreducible error each estimator sits. MAE in kilograms would
compare *scenarios* rather than estimators, because the floor spans two orders of magnitude across
the set. The log axis exists because S6 reaches 3.9× while everything else lies between 1.00 and
1.40 — on a linear axis the comparison the figure is for is a few pixels tall.

**Scenarios with a zero floor are absent** (S1 has no dynamic load, so the ratio is a division by
zero, not an impressive number).

---

## `ladder__coverage` · `reference_rate__coverage` · `governance__coverage`

**Plotted:** empirical coverage of the prediction interval against scenario.

- **y:** empirical coverage, fraction in [0, 1]. A dashed line marks the **nominal 0.95**, read from
  the config rather than hard-coded so the line moves if the target does.
- **x:** scenario, categorical, estimators offset within.
- **n:** 3 markers per estimator per scenario.

**The point:** whether the interval delivers what it promises. Above the line is conservative; below
it is an interval that promises more than it delivers. 0.91 is a good number or a bad one depending
entirely on what was promised, which is why the promise is drawn.

**Watch for:** static_affine on S7 at 0.89 — it under-covers exactly where it is biased (−96.8 kg),
because the interval does not know about a bias it was not shown.

---

## `ladder__reconvergence` · `governance__reconvergence`

**Plotted:** seconds from the first injected fault until the signed median error returned to within
3 standard errors of its pre-fault value and stayed there.

- **y:** time to reconverge, **seconds**, linear from 0.
- **x:** scenario, categorical, estimators offset within.
- **n:** up to 3 markers per estimator; fewer where a seed never reconverged.

**The point:** how long the site is wrong after a fault. On S4: kalman median 3406 s, rls 7923 s,
static_affine 11180 s — static takes 3.3× as long and over three hours on every seed.

**Two things to know before writing a caption:**

- **Scenarios with no calibration fault are absent entirely**, not drawn at zero. A zero bar would
  read as "reconverged instantly" rather than "the question was never asked". Only S4, S6 and S7
  appear.
- **Runs that never reconverged are counted in the x-axis label**, not dropped — dropping them would
  make a system that never recovers look identical to one that was not measured.

---

## `ladder__detectors` · `reference_rate__detectors` · `governance__detectors`

**Plotted:** detector recall against false-alarm rate, as a scatter.

- **x:** false alarms per hour of simulated operation, **1/h**.
- **y:** recall, fraction of injected calibration faults answered inside the 30-minute horizon.
- **series:** colour and marker per estimator.
- **n:** 3 markers per estimator per scenario, pooled across scenarios on one pair of axes.

**The point:** the trade-off an operator faces. Either axis alone can be made perfect by a detector
that is useless in the other direction, so they belong together.

**Critical for the caption:** the **tick marks below the zero line** are runs where recall is
*undefined* — scenarios with no calibration-affecting fault, where there was nothing to detect and
every alarm is a pure false alarm. They are drawn below the axis rather than at y = 0 because at
zero they would be pixel-for-pixel identical to a detector that missed everything, which is the one
confusion this figure exists to avoid.

**Also for the caption:** only **two detectors** are enabled (CUSUM and Page–Hinkley). This is not a
per-detector figure and cannot be read as one.

---

## `reference_rate__reference_rate` — the most informative figure in the set

**Plotted:** MAE ÷ dynamic floor against how often a reference vehicle arrives. **Two panels**, one
per scenario (S4_step_fault, S7_sparse_reference), sharing a y-axis.

- **x:** reference rate, **log scale**, ticks labelled `1 in 2`, `1 in 5`, `1 in 10`, `1 in 20`,
  `1 in 50`.
- **y:** MAE ÷ dynamic floor, dimensionless, with a dotted line at 1.0 annotated *"the floor"*.
- **series:** **solid = control loop on, dashed = control loop off**, colour per estimator. Six lines
  per panel. Faint markers behind the lines are the individual seeds; the lines are medians.
- **n:** 3 seeds per point; 180 runs across the figure.

**The point:** *the vertical gap between a matched solid/dashed pair is what the control loop is
worth at that reference rate.* Where the pair meets, the loop is worth nothing and the estimator
underneath is carrying the run.

**What to look for:** in the S4 panel the green (static_affine) pair separates widely at `1 in 2`
and converges completely by `1 in 10`, meeting exactly at `1 in 50`. The blue and orange pairs
(kalman, rls) are **coincident throughout** — the loop does not change their MAE at any rate. This
figure is the single clearest statement of the B2 result in `RESULTS.md`.

**Panels are separate for a reason worth stating**: an earlier version pooled S4 and S7 into one
median, and since static_affine sits at 1.41× its floor on S4 and 1.16× on S7, the pooled line came
out at 1.27× — a number describing neither scenario.

---

## What is *not* here

- **No figure of the real-data results.** The leave-one-recording-out numbers in `RESULTS.md` §VI-I
  are tabular only; with 23 observations across 7 folds, a plot would be decoration.
- **No per-detector figure.** Only two detectors ran.
- **No parameter-tracking figure** for §VI-B — that analysis does not exist (see `RESULTS.md`).
- **No computational-footprint figure** — three numbers do not need one.
