# Experiments and real data

Phase 6. Everything before it produced numbers one command at a time, typed by hand and quoted from
a terminal into a document. That is the problem this phase exists to solve: a number quoted from a
terminal cannot be re-derived, disagreed with, or noticed to have changed.

Four things, and one honest gap:

| | what it is | command |
|---|---|---|
| **the runner** | a declarative grid of scenarios x estimators x seeds, one parquet out | `wimsim experiment ladder` |
| **the table** | the phase-6 checkpoint, in Markdown and LaTeX, beside the parquet | written by the above |
| **the figures** | four matplotlib figures, also beside the parquet | written by the above |
| **the gap report** | where the simulator and the real sensor disagree | `wimsim gap-report` |
| **replay** | the config decides where samples come from; the detector runs on real data | `wimsim detect` |

The gap: **nothing here weighs a real vehicle**, and nothing can until one is weighed. See
[the last section](#what-is-still-missing).

---

## The runner

```bash
wimsim experiment ladder --dry-run          # the grid and what it costs, running nothing
wimsim experiment ladder                    # -> data/results/ladder/
wimsim experiment ladder --seeds 1          # a table quickly; label it as such when quoting it
```

A sweep is `configs/experiments/*.yaml`: scenario axis, estimator axis, seed axis, an edge config,
and overrides. Three decisions in `runner.py` decide whether the output is trustworthy rather than
merely produced.

**A failed run is a row, not a gap.** Nineteen results and one exception is nineteen results *and
one recorded failure*. Dropping it silently changes what every mean in the table is a mean over, and
the failure is usually the interesting part. Failures carry their error text into the parquet and
appear in the table as a row saying `failed`.

**Every row carries its own provenance** -- config hash, edge config hash, git commit, dirty flag,
version. A table whose rows cannot each name what produced them is a table nobody can rebuild, and
principle 3 says that is not a result. A dirty tree is printed on the table itself, because a commit
that does not identify the code is worse than no commit at all.

**The grid is validated before anything runs.** Unknown estimator names, unknown YAML keys and
`scenario_overrides` naming a scenario not in the sweep are all refused at construction. A sweep is
expensive, and discovering a typo after the first hour is pure waste.

Runs are sequential on purpose. Same seed and config give a byte-identical stream by construction,
so parallelism would buy wall-clock time and cost the ability to say what happened when something
goes wrong.

### Why `scenario_overrides` exists

The scenarios differ in length by three hundred times: S1 ships at 15 minutes and S2 at 72 hours.
A single global override list cannot give both a sensible duration, and the first run of `ladder`
showed what that costs -- S1 produced 62 crossings, 60 of which went to the calibration window, so
its row was a mean over **two passes** and reported a coverage of exactly 0.5000.

Two things came out of that. `scenario_overrides` lets S1 run for six hours without changing what S1
*is* (it carries no drift, no faults and no dynamics at any length), and the table grew a `scored`
column -- first among the numbers, because everything to its right is only as good as it is. A row
built on two passes and a row built on four thousand are otherwise the same width on the page.

## The checkpoint: all estimators, all scenarios

`wimsim experiment ladder` -- 7 scenarios x 3 estimators x 3 seeds, 63 runs, 0 failed, 75 minutes,
one reference vehicle in ten, the controller enabled throughout. Full table and figures in
`data/results/ladder/`; commit `c1881d4f`, clean tree. Means over the three seeds:

| scenario | estimator | scored | MAE kg | x floor | bias kg | coverage |
|---|---|---|---|---|---|---|
| S1_nominal | static_affine | 1392 | 0.98 | -- | -0.14 | 0.958 |
| | rls | 1392 | 0.97 | -- | -0.06 | 0.957 |
| | kalman | 1392 | 0.97 | -- | -0.03 | 0.959 |
| S2_thermal_cycle | static_affine | 12951 | 136.66 | 1.01 | **-24.66** | 0.937 |
| | rls | 12951 | 137.03 | 1.01 | +0.96 | 0.946 |
| | kalman | 12951 | 138.24 | 1.02 | +2.38 | 0.959 |
| S3_zero_drift_walk | static_affine | 4751 | 132.63 | 1.00 | -14.77 | 0.939 |
| | rls | 4751 | 133.74 | 1.01 | +1.28 | 0.944 |
| | kalman | 4751 | 135.05 | 1.02 | +3.87 | 0.965 |
| S4_step_fault | static_affine | 3465 | 182.57 | **1.40** | +16.48 | 0.907 |
| | rls | 3465 | 153.29 | 1.17 | -10.79 | 0.939 |
| | **kalman** | 3465 | **147.42** | **1.13** | -8.79 | 0.973 |
| S5_outage | static_affine | 1388 | 127.70 | 1.01 | -19.58 | 0.922 |
| | rls | 1388 | 127.24 | 1.00 | -15.41 | 0.934 |
| | kalman | 1388 | 129.48 | 1.02 | -13.03 | 0.985 |
| S6_combined | static_affine | 5041 | 715.35 | 3.82 | -59.98 | 0.913 |
| | **rls** | 5041 | **667.21** | **3.56** | -41.45 | 0.914 |
| | kalman | 5041 | 724.92 | 3.87 | -3.64 | 0.919 |
| S7_sparse_reference | static_affine | 7147 | 181.50 | 1.16 | **-96.75** | 0.887 |
| | rls | 7147 | 159.17 | 1.02 | -24.29 | 0.937 |
| | kalman | 7147 | 159.30 | 1.02 | -14.92 | 0.955 |

`x floor` is MAE divided by the dynamic load error the vehicles brought with them. S1 has no
dynamic load, so it has no floor to divide by.

### Adaptation is worth nothing until the plant moves, and then it is worth a lot

**S1 and S5 separate all three estimators by less than 3 %.** S1 has no drift and no faults; S5's
three faults are transport and acquisition failures that never touch the scale. Nothing to adapt to,
and adaptation costs nothing -- which is the result worth having, because an adaptive estimator that
was *worse* under nominal conditions would be a bad trade at most sites.

**Where the plant moves slowly, adaptation removes the bias but not the error.** On S2 and S3 all
three estimators sit within 2 % of the floor and their MAE is indistinguishable. Their *bias* is not:
static carries -24.7 kg through a 72-hour thermal cycle and -14.8 kg through a Brownian zero walk,
while RLS and Kalman sit within 4 kg of zero. MAE is dominated by dynamic load the calibration
cannot touch; the bias is the part it can, and it is the part that matters for a scale.

**Where the plant steps, adaptation is the whole result.** S4 injects two sensitivity steps. Static
reaches 1.40x the floor; Kalman 1.13x, RLS 1.17x. Static also takes far longer to come back. All
three departed and reconverged on all three seeds; mean time from the first fault:

| | seed 1 | seed 2 | seed 3 | mean |
|---|---|---|---|---|
| kalman | 3406 s | 1744 s | 4996 s | **3382 s** |
| rls | 3919 s | 8651 s | 7923 s | 6831 s |
| static_affine | 12409 s | 9677 s | 11180 s | **11089 s** |

Static takes **3.3x** as long as Kalman to get the calibration back, and better than three hours of
it on every seed.

**S7 is the clearest case, and it was designed to be the hardest.** Its single fault is a 3 % gain
loss ramped over two hours, "slow enough to hide inside population variance". It succeeds at hiding:
the detectors catch it in 1 run of 9. Static carries **-96.7 kg** of bias through it and its coverage
falls to 0.887 -- an interval that promises 95 % and delivers 89 %, which is the specific failure
that makes a biased estimator dangerous rather than merely inaccurate. RLS and Kalman track it out
continuously, at 1.02x the floor and coverage 0.937-0.939.

The reconvergence column says the same thing in a different and sharper way. **On two of its three
seeds, the Kalman arm's error never departed its pre-fault band at all** -- there was no excursion
to recover from, because the filter absorbed a two-hour ramp as it happened. Static departed on all
three and got back on two. "Never departed" is the outcome a control metric should report for an
estimator that simply kept up, and it is not a fast recovery.

**S6 defeats everything.** Six overlapping mechanisms put every estimator 3.6-3.9x above its floor.
RLS is best at 3.56x and Kalman has the smallest bias at -3.6 kg, but no configuration here is
usable, and the scenario is doing its job by saying so.

### What the detectors did, and why recall is low

Across the sweep, **1 of 6 calibration faults on S4 was answered inside the 30-minute horizon, 0-1 of
6 on S6, and 0-1 of 3 on S7**. False alarms ran 0.03-0.19 per hour.

That is a real limitation of one reference vehicle in ten and it should not be read as a broken
detector. Two things are going on, and they pull in opposite directions:

* **The confirmation gate is a rate problem.** `docs/controller.md` measured the sensitivity floor as
  `confirm_sigma x 1.2533 x sigma / sqrt(passes)` -- it needs a run of reference passes to confirm,
  and at one reference in ten those passes take ten times as long to arrive. The phase-5 checkpoint
  that caught both S4 faults within 40 minutes ran at one reference in **two**. This sweep is the
  measurement of what the realistic rate costs, which is what the ladder's own description says it
  is for.
* **The detector and an adaptive estimator are partly redundant.** The detector watches residuals,
  and RLS and Kalman remove the drift from the residuals as it appears -- so there is less left to
  trip on. It shows in the alarm counts: on S4, static_affine raised 6 alarms and performed 4
  recalibrations, while Kalman raised 4 and performed **none at all** -- and Kalman was the more
  accurate of the two by a wide margin. The adaptive estimators reached 1.13x the floor *without a
  single discrete recalibration event*.

The honest summary is that at a realistic reference rate the discrete MAPE-K loop is a backstop for
the static estimator rather than the primary mechanism, and continuous adaptation does the work.
Whether the loop earns its complexity at 1-in-10 is a question this table asks and does not answer;
at 1-in-2 phase 5 showed it clearly does.

### The crossover: how often a reference vehicle has to arrive

The checkpoint above ended on a question it could not answer. `wimsim experiment reference_rate`
answers it: 180 runs, 0 failed, 135 minutes, commit `b0e98778`, clean tree. Five rates from one
vehicle in two to one in fifty, **each run twice on a byte-identical stream** with the control loop
enabled and disabled.

`static_affine` on `S4_step_fault` is the purest test, because static has no other adaptation
mechanism — anything it recovers, the loop recovered:

| reference rate | loop off | loop on | what the loop is worth | bias off → on | recalibrations |
|---|---|---|---|---|---|
| 1 in 2 | 1.412× floor | **1.199×** | **15.1 %** | −140.5 → +32.6 kg | 3 |
| 1 in 5 | 1.412× | 1.364× | 3.4 % | −140.5 → +56.7 kg | 3 |
| 1 in 10 | 1.412× | 1.396× | 1.1 % | −140.5 → +16.5 kg | 4 |
| 1 in 20 | 1.412× | 1.406× | 0.4 % | −140.5 → −138.1 kg | 1 |
| 1 in 50 | 1.412× | **1.412×** | **0 %** | −140.5 → −140.5 kg | **0** |

**The loop's value collapses between one reference in five and one in ten, and is exactly zero by
one in fifty**, where it never fires at all. That is the answer, and it is sharper than expected:
not a gentle decline but most of the benefit gone within one step of the phase-5 rate.

Detection follows the same curve. Faults answered inside the 30-minute horizon, out of six (two
faults × three seeds), with the loop on:

| | 1 in 2 | 1 in 5 | 1 in 10 | 1 in 20 | 1 in 50 |
|---|---|---|---|---|---|
| static_affine | 4 | 4 | 1 | 0 | 0 |
| rls | 4 | 3 | 1 | 0 | 0 |
| kalman | 4 | 3 | 1 | 0 | 0 |

This is the confirmation gate behaving exactly as `docs/controller.md` predicted it would. Its
sensitivity floor is `confirm_sigma × 1.2533 × σ / √passes`, so it needs a *run* of reference passes
to confirm — and at one in fifty they arrive fifty times more slowly than the faults do.

**The adaptive estimators barely use the loop at all.** On S4 at one in two, Kalman is at 1.063×
the floor with the loop and 1.063× without it — identical to three decimal places, with zero
recalibrations either way. What the loop buys them is *bias*, and only at middling rates: RLS at one
in ten goes from −29.5 kg to −10.8 kg with it enabled. Their MAE is set by how often they get a
reference to fit, not by whether a detector is watching.

So the honest statement of the controller's value is narrower than phase 5's checkpoint implied, and
it is a statement about sites rather than about algorithms:

> The discrete MAPE-K loop earns its complexity where reference vehicles are **frequent** — roughly
> one in five or better. Past one in ten it is insurance: it fires rarely, catches little, and the
> accuracy is being produced by whichever estimator is underneath. A site that cannot supply
> references at that rate should deploy an adaptive estimator and not expect the loop to save it.

### An interval that quietly stopped being an interval, and the repair

The reference-rate sweep turned up something nobody asked it for. Kalman on S4 at one reference in
fifty had the *best* MAE of the three estimators and coverage **0.754** — an interval promising 95 %
and delivering 75 %, with no warning from the point estimate.

**The first explanation offered here was wrong.** It read the narrow band as a small, stale conformal
calibration set. That was a plausible mechanism and it did not survive being checked. Splitting the
coverage by `interval_source` — a field the events had carried since phase 5 — said what actually
happened:

| 1 in 50, before the repair | n | coverage |
|---|---|---|
| `conformal_relative` | 2551 | 1.000 |
| `kalman_analytic` | 841 | **0.007** |
| pooled | 3392 | 0.754 |

Conformal was never the problem. 841 of 3392 events carried a band from a construction the
configuration did not ask for: `uncertainty.method` is `conformal`, conformal needs 19 scored
references before it can claim a 95 % quantile, and at one in fifty those take four hours to arrive.
Until then the pipeline fell back to the estimator's own analytic band — which for the Kalman filter
is the construction phase 5 measured at coverage 0.0065 and chose conformal *specifically to avoid*.
The system had a documented catastrophic failure mode, picked a default to avoid it, and fell back
to it whenever the default was not ready.

**So the construction was fixed rather than routed around.** The Kalman band was `J P J' + R/k²`.
Both terms are sensor-side — how well the two parameters are known, and how noisy one reading is —
while the dominant error in weigh-in-motion is the vehicle's own bounce, about 141 kg on these
scenarios, which the filter is never told about. The band is now the empirical prediction-error
spread, which contains everything the measurement model does not. It *replaces* the analytic terms
rather than adding to them: the residual is a prediction error against the prior state, so it
already carries the measurement noise and the parameter uncertainty.

| Kalman coverage | before | after |
|---|---|---|
| S4 at 1 in 50 | 0.754 | **0.980** |
| S4 (ladder, 1 in 10) | 0.940 | 0.973 |
| S5 | 0.902 | 0.985 |
| S7 | 0.939 | 0.955 |
| S6 | 0.895 | 0.919 |
| phase-5 checkpoint scenario | 0.0065 | 0.897 |

MAE and bias are unchanged everywhere, which is the check that only the band moved.

Two things bit on the way, both recorded in `calibration/kalman.py`. The residual has to be in
kilograms rather than feature units. And it must not be accumulated while the filter is still
converging — a fresh filter's first prediction errors describe its prior, not the plant, and at an
EWMA memory of 0.98 the first one still carries 3e-4 of its weight after 400 updates, which left a
filter whose true spread was 0.5 kg reporting 603 kg. The warm-up that fixes it then *caused* a
second hole, because ten updates at one reference in fifty is five hundred passes; `fit()` now seeds
the empirical term from its own batch residuals, which is information it already had and discarded.
Fallback coverage at that rate went 0.007 → 0.354 → **0.926**, in line with the residual-spread
estimators at 0.929 and 0.927.

### Recalibrating costs the interval, briefly

A column added for the investigation above measured something else nobody had looked at. The
fallback count on the ladder, at one reference in ten:

| estimator | recalibrations | events on a fallback interval |
|---|---|---|
| kalman | 0 | 121 |
| rls | 2 | 248 |
| static_affine | 4 | **345** |

121 is the conformal warm-up every run pays once. The rest is the loop: `run_closed_loop` calls
`conformal.reset()` on every recalibration, because — correctly — "the old residual quantiles
describe an estimator that no longer exists". Each recalibration therefore reopens the warm-up
window, and the estimator that recalibrates most pays most.

**Recalibrating improves the mass and degrades the interval**, temporarily and by an amount nobody
had measured. That trade is now small, because the construction it falls back to is no longer
catastrophic — which is the second reason the repair above was worth making rather than routing
around.

### What "reconverged" means, and what it cost to define

The headline control metric was wrong twice, and both errors were found by using it rather than by
reading it.

**It tracked the median of ``|error|``.** A calibration fault is a systematic *shift*, and the
median of the absolute error barely moves when a wide symmetric distribution slides sideways. On S7
it reported static_affine reconverging in 187-327 s while that estimator carried -96.7 kg of bias on
a 158 kg spread. The calibration had not recovered at all; the statistic could not see it. It is now
the **signed** median.

**It did not require the error to depart.** Fixing the statistic did not fix S7, because the
statistic was never the problem there. S7 ramps its fault over two hours, reconvergence is timed
from the fault's start, and 187 s in the error has not moved -- so the first window was trivially
back at baseline and the metric announced recovery from a disturbance that had not arrived.
Recovery now requires a departure first, and a departure has to be **sustained** for the same number
of windows a recovery does: a rolling median crosses a three-sigma band by chance somewhere in a few
hundred overlapping windows, so "went outside once" measures how long the run was rather than what
the plant did.

Every number moved, and all in the same direction:

| | old | corrected |
|---|---|---|
| S4 static_affine | 3758 s | 12409 s |
| S4 kalman | 870 s | 3406 s |
| S7 static_affine | 187 s | 5104 s |
| S7 kalman | 187 s | **never departed** |

The threshold is now the controller's own. Recovery means the signed median has come back inside
`tolerance_sigma` standard errors of its pre-fault value -- the same test
`RecalibrationController._displaced` applies when the loop decides that drift has *occurred*. The
metric and the loop agree on what "moved" means instead of each carrying a private definition, and
the default `tolerance_sigma` matches the loop's `confirm_sigma`.

**The resolution limit is stated rather than discovered.** The smallest bias the metric can see is

    tolerance_sigma x 1.2533 x sigma / sqrt(window)

about **0.59 sigma** at the defaults, tightening with the square root of the window. Resolving a
smaller shift costs passes and buys a coarser recovery *time* in exchange; that trade is the design.
A test pins the formula and checks that the implementation applies it.

Three outcomes are now reportable and none of them is a missing value: **reconverged**, **departed
but never came back**, and **never departed**. The last is not a fast recovery and must not be
averaged with one.

## The figures

Four, written to `data/results/<id>/figures/` with their captions in a `README.md` beside them,
because a figure separated from its caption is a shape.

| figure | question |
|---|---|
| `accuracy` | how far above the irreducible floor is each estimator? |
| `coverage` | does the interval deliver what it promises? |
| `reconvergence` | how long after a fault before the error comes back and stays back? |
| `detectors` | recall against false alarms per hour -- the trade-off an operator faces |

What `figures.py` is mostly about is the ways a figure can be *dishonest*, which is a different
failure from being wrong:

* **MAE is drawn as a multiple of the dynamic floor**, not in kilograms. The floor -- the load error
  the vehicles brought with them, which no calibration can remove -- spans two orders of magnitude
  across the scenario set, so a bare axis compares scenarios rather than estimators.
* **Coverage is drawn against its nominal target**, read from the config so the line moves when the
  shipped target does. 0.91 is a good number or a bad one depending entirely on what was promised.
* **Scenarios with no faults are absent from the reconvergence figure** rather than drawn at zero,
  which would read as "reconverged instantly" instead of "the question was never asked". They *do*
  appear on the detector figure, with recall undefined rather than 1.0: a scenario with nothing to
  detect is the cleanest measurement of what a false alarm costs.
* **Seeds are drawn, not averaged.** Three seeds exist to give a number an error bar.
* **Failed runs are counted in the title.** A bar absent because a run crashed looks exactly like a
  bar absent because the value was zero.
* **The same frame draws the same bytes**, so a figure can be diffed and a reviewer can tell a
  re-render from a new result.

A figure with nothing to draw is not written at all. An axis with no data on it is not a result.

## The sim-to-real gap report

```bash
wimsim gap-report data/real/20260209_cintron1 --channel Tenzo1
wimsim gap-report data/real/20260209_cintron1 --channel Tenzo1 -o data/results/gap/c1_t1.md
```

Compares a real recording against a synthetic stream generated *at the recording's own sample rate*
-- PSDs computed on two different grids differ in ways that are entirely an artefact of the grids --
in three parts, and ends with the `--set` lines that move the model towards it.

It is a comparison, not a verdict. There is no pass mark, because a simulator that matched a real
sensor on every statistic would mean the statistics were not discriminating.

`docs/sim-to-real.md` holds the findings, including where the command disagrees with the hand
analysis done in phase 3 and why neither supersedes the other. Two things worth repeating here:

* The white noise floor is a property of the **channel**: Tenzo1 at 4.44-4.47e-7 and Tenzo2 at
  4.57-4.59e-7 across eight independent recordings, ranges that do not overlap.
* The pulse width is reported only when **at least two window half-widths independently find it**.
  The window decides the answer in both directions -- too narrow and the fit measures the window,
  too wide and the Brownian baseline dominates -- and on `cintron1/Tenzo1` the widths from 0.75 s to
  4 s disagree about whether a fit is possible at all, while every one that succeeds returns
  890-942 ms. That agreement is the evidence the number means anything. Four of sixteen channel-runs
  are refused outright, with the widths that were tried named in the refusal.

## Replay: the config decides where samples come from

`configs/scenarios/S8_replay_real.yaml` was written in phase 1 so that switching to real data would
be one config change and nothing else. Until phase 6 it was a document nothing read: `source.kind`
was consulted by no code, and every caller constructed `SyntheticSource(cfg)` directly.

`build_source(cfg)` closes that, and `wimsim detect` is the command it makes possible:

```bash
wimsim detect S8_replay_real --edge cintron_platform \
  --set scenario.source.replay.run_dir=data/real/20260209_cintron1 \
  --set scenario.source.replay.channel=Tenzo1
```

Detection is the one part of the pipeline a real recording can drive end to end, because it needs no
truth. It prints crossings, widths and axle counts, and deliberately prints **no masses** -- a mass
here would imply a calibration that does not exist.

### Three reasons the default pipeline found nothing

With `configs/estimators/default.yaml`, `detect` finds nothing on any of the eight recordings at any
threshold. Each reason was measured on `20260209_cintron1/Tenzo1`, and each is a different kind of
mistake:

1. **Scale.** `start_threshold: 0.05` is four orders of magnitude above a 7e-6 strain excursion.
   `default` models a sensor measuring contact force in mV/V; this one is a strain gauge in
   microstrain.
2. **Bandwidth.** `default` applies no low-pass, so at 25 kHz the compensated signal is dominated by
   per-sample noise and by mains -- it crosses any workable threshold about 90,000 times in a 60 s
   recording. The crossing is real and about 900 ms wide; it is simply not visible one sample at a
   time.
3. **The zero line.** A 2 s trailing median against a 1.7 s crossing *is* mostly vehicle, so the
   tracker follows the pulse and subtracts it. This is the phase-3 validator bug's family again: a
   statistic contaminated by the thing it is measuring.

And a fourth, which is not a tuning question: **the crossings pull the signal down.** The detector
opens on a rise above the zero line, by design -- a detector needs exactly one definition of "above"
-- so `preprocess.invert` handles it, because which way a crossing goes is a property of the wiring
rather than of the algorithm.

`configs/estimators/cintron_platform.yaml` sets all four, with the measured reason for each value.
The result, over all eight recordings and both strain channels:

| | Tenzo1 | Tenzo2 |
|---|---|---|
| `20260209_cintron1` | 1 event, 1347 ms | 1 event, 1865 ms |
| `20260209_cintron2_spat` | 5, 932 ms | 3, 1069 ms |
| `20260209_cintron3` | 3, 986 ms | 4, 1033 ms |
| `20260209_cintron4` | 6, 865 ms | 5, 874 ms |
| `20260209_cintron5` | 7, 731 ms | 7, 818 ms |
| `20260209_fabia1` | 2, 727 ms | 2, 793 ms |
| `20260209_fabia2` | **0** | **0** |
| `20260209_fabia3` | 4, 901 ms | 4, 1160 ms |

Fourteen of sixteen channel-runs yield crossings, at widths consistent with the low-speed
drive-overs the recordings describe. On `cintron1/Tenzo1` the detected event is the same event, at
the same time and the same width, that `wimsim gap-report` fits by a completely independent method.

`fabia2` yields nothing on either channel, and `gap-report` also refuses to fit a shape there. Two
independent methods agreeing that there is nothing in a recording is a more useful result than
either alone.

## Estimated reference masses

No vehicle at this site has been weighed and the rig is gone, so `S8_replay_real` was never
scorable. `wimsim write-estimated-reference` closes that gap the only way left — by inference:

```bash
wimsim write-estimated-reference data/real/20260209_cintron1 --vehicle citroen
```

It detects the crossings, classifies each as a front or a rear wheel from the bimodal peak
amplitude, and writes the wheel loads derived in `docs/sim-to-real.md`. Over the corpus: **7 of 8
recordings got reference rows**, 1 to 6 each, and all 8 still satisfy the real-data schema.
`20260209_fabia2` has no crossings — which is what `gap-report` independently concludes about it.

**This is an estimate standing where the pipeline expects a measurement, and that is a real cost.**
Principle 1 says ground truth is an output and never an estimator input; here the input was itself
derived from the signal. Scoring against this file measures whether the pipeline reproduces *the
inference*, not whether it weighs vehicles, and nothing derived from it is a metrological claim.

So the warning travels with the data rather than living in a document beside it: every row's
description begins `ESTIMATED, not weighed`, a `reference.ESTIMATED.md` sidecar records the whole
derivation, and the writer **refuses to overwrite a `reference.csv` that has no sidecar beside it** —
an estimated file can always be regenerated and a measured one cannot, and that asymmetry decides
which way the default falls.

## Scoring the real corpus, honestly

`wimsim score-real` fits and scores inside one recording. On this corpus that proves very little:
60 s each, one to seven crossings, and the calibration and the test come from the same minute of the
same drive-over. It reported MAE of 2.3 to 22.4 kg, and those numbers were optimistic.

`wimsim score-corpus` holds out a whole recording, fits on the other six, and predicts it. A whole
recording rather than random crossings, because crossings within one share a vehicle, a driver, a
line across the platform and a minute of thermal state — a random split leaks all of that across the
fold boundary.

7 recordings, 23 matched crossings, `static_affine` on Tenzo2:

| | held out |
|---|---|
| MAE | **42.9 kg** |
| MAPE | **13.23 %** |
| bias | +0.2 kg |
| coverage | 0.783 |
| gain spread across folds | **50.4 %** |

### The pooled bias is a lie, and the folds are what say so

| | |
|---|---|
| pooled bias | **+0.2 kg** |
| mean \|fold bias\| | **40.5 kg** |

Every fold is systematically wrong and they cancel. Broken down by vehicle, the sign splits cleanly:

| | folds | mean bias |
|---|---|---|
| Citroën | 5 | **−30.8 kg** |
| Fabia | 2 | **+59.4 kg** |

**The two vehicles do not sit on one calibration line.** A calibration fitted mostly on Citroëns
over-reads the Fabia by 59 kg; one fitted with the Fabia in it under-reads the Citroëns by 31.

Two explanations fit, and this corpus cannot separate them. Either the platform's response genuinely
differs between the two vehicles — different track widths, different tyre contact, a different line
across the plate — or the Citroën's inferred mass is simply wrong, since it came from the measured
peak ratio against the Fabia rather than from a weighing. **One weighbridge ticket distinguishes
them**, and nothing else here will.

The cross-validated fit also lands above the sensitivity inferred earlier: **3.67–5.53 × 10⁻⁸
strain/kg** against 2.70–3.06 × 10⁻⁸. That inference assumed proportionality — mass through the
origin — while a two-parameter fit prefers a different slope with an intercept. The intercept is not
obviously spurious: a plate with a preload, or a zero-line the compensation does not fully remove,
would produce one.

### What this is and is not

It is a measurement of whether a calibration *transfers between recordings*, which is a real
property of the installation and one a 50 % gain spread answers clearly: not well, on 23 crossings.

It is not a weighing. The reference masses are the inference in `docs/sim-to-real.md`, so a
systematic error in that inference appears here as a systematic error in the pipeline, and the two
cannot be told apart from inside. `data/real/EXAMPLE` is reported as skipped rather than dropped —
it carries a `reference.csv` but its channel is `S1`.

## What is still missing

**No real vehicle has been weighed**, and the leave-one-out result above is the sharpest argument
yet for why that matters: the per-vehicle bias split cannot be attributed to the platform or to the
inference without one known mass. Everything else in this section is reproducible; that is not.

This is the same conclusion `docs/sim-to-real.md` reached in phase 3, and the list at the end of that
document -- gauge separation in metres, one weighed vehicle, a recording at road speed, the bridge
configuration -- is unchanged.

**The two-sensor question is still open.** The station model, the source adapter and the detector all
assume one measurement channel, and the real installation has two gauges separated along the
direction of travel. `wimsim detect` runs them one at a time, which is why the table above has two
columns rather than one result per recording.
