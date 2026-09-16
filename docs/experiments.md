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
`data/results/ladder/`; commit `d05a9451`, clean tree. Means over the three seeds:

| scenario | estimator | scored | MAE kg | x floor | bias kg | coverage |
|---|---|---|---|---|---|---|
| S1_nominal | static_affine | 1392 | 0.98 | -- | -0.14 | 0.958 |
| | rls | 1392 | 0.97 | -- | -0.06 | 0.957 |
| | kalman | 1392 | 0.97 | -- | -0.03 | 0.927 |
| S2_thermal_cycle | static_affine | 12951 | 136.66 | 1.01 | **-24.66** | 0.937 |
| | rls | 12951 | 137.03 | 1.01 | +0.96 | 0.946 |
| | kalman | 12951 | 138.24 | 1.02 | +2.38 | 0.950 |
| S3_zero_drift_walk | static_affine | 4751 | 132.63 | 1.00 | -14.77 | 0.939 |
| | rls | 4751 | 133.74 | 1.01 | +1.28 | 0.944 |
| | kalman | 4751 | 135.05 | 1.02 | +3.87 | 0.941 |
| S4_step_fault | static_affine | 3465 | 182.57 | **1.40** | +16.48 | 0.907 |
| | rls | 3465 | 153.29 | 1.17 | -10.79 | 0.939 |
| | **kalman** | 3465 | **147.42** | **1.13** | -8.79 | 0.940 |
| S5_outage | static_affine | 1388 | 127.70 | 1.01 | -19.58 | 0.922 |
| | rls | 1388 | 127.24 | 1.00 | -15.41 | 0.934 |
| | kalman | 1388 | 129.48 | 1.02 | -13.03 | 0.902 |
| S6_combined | static_affine | 5041 | 715.35 | 3.82 | -59.98 | 0.913 |
| | **rls** | 5041 | **667.21** | **3.56** | -41.45 | 0.914 |
| | kalman | 5041 | 724.92 | 3.87 | -3.64 | 0.895 |
| S7_sparse_reference | static_affine | 7147 | 181.50 | 1.16 | **-96.75** | 0.887 |
| | rls | 7147 | 159.17 | 1.02 | -24.29 | 0.937 |
| | kalman | 7147 | 159.30 | 1.02 | -14.92 | 0.939 |

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
reaches 1.40x the floor; Kalman 1.13x, RLS 1.17x. Static also takes far longer to come back: mean
time to reconverge 4767 s against 1331 s for RLS and 953 s for Kalman, with one static run taking
8679 s -- more than two hours.

**S7 is the clearest case, and it was designed to be the hardest.** Its single fault is a 3 % gain
loss ramped over two hours, "slow enough to hide inside population variance". It succeeds at hiding:
the detectors catch it in 1 run of 9. Static carries **-96.7 kg** of bias through it and its coverage
falls to 0.887 -- an interval that promises 95 % and delivers 89 %, which is the specific failure
that makes a biased estimator dangerous rather than merely inaccurate. RLS and Kalman track it out
continuously, at 1.02x the floor and coverage 0.937-0.939.

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

### An interval that quietly stops being an interval

The sweep turned up something nobody asked it for. On S4 with the loop on, as references get rarer:

| estimator | coverage at 1 in 2 | at 1 in 50 | interval width at 1 in 50 | bias at 1 in 50 |
|---|---|---|---|---|
| kalman | 0.951 | **0.758** | 916 kg | −41.7 kg |
| rls | 0.948 | 0.971 | 1089 kg | −92.4 kg |
| static_affine | 0.917 | 0.961 | 1112 kg | −140.5 kg |

**Kalman has by far the smallest bias at one in fifty and by far the worst coverage.** An interval
promising 95 % and delivering 76 % is the specific failure mode that makes a confident estimator
more dangerous than an inaccurate one, and the point estimate gives no warning of it — MAE at that
rate is 1.186× the floor, the best of the three.

The mechanism is visible in the widths. The conformal interval reads its quantile off residuals
actually seen, and at one in fifty there are only **71 reference observations in a sixteen-hour
run**. RLS and static have large residuals throughout, so their intervals widen and over-cover.
Kalman's residuals stay small because it tracks — so its calibration set is tight, and when drift
does arrive the interval it produces is too narrow for it. `min_calibration` is 19, so the guard
never trips; the set is large enough to compute a quantile and too small and too stale for that
quantile to mean anything.

That is a hypothesis with the widths behind it, not an established result. It is the next thing this
sweep says to measure, and it belongs to the uncertainty layer rather than the control loop.

### A limit of the reconvergence metric

`time_to_reconverge` tracks a rolling median of |error| and calls it recovered when it returns to
within 1.5x its pre-fault level and stays there. That is deliberately hard to game upward -- one
lucky pass cannot move a median over forty. It is also **blind to a bias shift smaller than about
half the error spread**: on S7 it reports static_affine reconverging in 187-327 s while that estimator
is carrying -96.7 kg of bias, because on a spread of 158 kg a 97 kg shift does not move the median of
|error| by 50 %.

So on S7 the reconvergence column should be read as "the error never visibly departed", not as
"the calibration recovered". The bias column is what shows the truth there. Tracking the signed
median instead would make the metric sensitive to exactly this, and would change the definition of
the headline control metric, so it is written down here rather than changed quietly.

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

## What is still missing

**No real vehicle has been weighed, so nothing here produces a kilogram from the real sensor.** Every
pipeline entry point past detection bootstraps its calibration from a truth log, and a recording has
none. `wimsim run` and `wimsim control` on a replay scenario will fail for want of one, and that
failure is correct: the alternative is a mass emitted under a calibration nobody fitted.

This is the same conclusion `docs/sim-to-real.md` reached in phase 3, and the list at the end of that
document -- gauge separation in metres, one weighed vehicle, a recording at road speed, the bridge
configuration -- is unchanged.

**The two-sensor question is still open.** The station model, the source adapter and the detector all
assume one measurement channel, and the real installation has two gauges separated along the
direction of travel. `wimsim detect` runs them one at a time, which is why the table above has two
columns rather than one result per recording.
