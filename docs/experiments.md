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
