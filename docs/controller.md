# The controller

Phase 5 is the part the project exists for: a scale that notices it has become wrong and fixes
itself. Five pieces — two adaptive estimators, four drift detectors, a MAPE-K state machine,
conformal intervals, and an append-only profile store — plus the loop in `experiments/closed_loop.py`
where they meet.

Everything here stayed inside principle 6: `calibration/` imports nothing but the standard library,
numpy and `wimsim.core`, so the whole controller cross-deploys to a Pi unchanged.
`tests/test_architecture.py` fails the build if that stops being true.

---

## The checkpoint

Buildspec: *"`S4_step_fault` shows detection, recalibration, and reconvergence."* The full 16-hour
run, two arms on a byte-identical sample stream, controller the only difference:

```bash
wimsim generate S4_step_fault --out data/synthetic/S4_demo --samples none
wimsim control data/synthetic/S4_demo --reference-every 2 --calibration-passes 60 --no-control
wimsim control data/synthetic/S4_demo --reference-every 2 --calibration-passes 60
```

| | controller off | controller on |
|---|---|---|
| MAE | 191.59 kg | **154.99 kg** |
| MAPE | 3.231 % | 3.208 % |
| bias | −136.89 kg | **−9.44 kg** |
| empirical coverage | 0.8909 | 0.9123 |
| mean interval width | 904 kg | 1,048 kg |
| dynamic floor | 140.59 kg | 140.59 kg |

**Bias falls by 93 %.** That is the number to quote, because a sensitivity step makes the scale
*systematically* wrong and bias is what systematic error moves. MAE improves 19 %, which understates
it: MAE is dominated by the dynamic floor — the error the vehicle's own bounce contributed, which no
calibration can remove — so the honest reading is that the controller takes the scale from 36 % above
the irreducible floor to 10 % above it.

The sequence, with faults injected at 4 h and 9 h:

```
 + 4.04 h  DRIFT_SUSPECTED  cusum raised an alarm at 13.20
 + 4.70 h  RECALIBRATING    refitted from 61 reference observations postdating the drift
 + 5.17 h  MONITORING       the new profile verified; back to monitoring
 + 6.48 h  DRIFT_SUSPECTED  cusum raised an alarm at 14.48
 + 7.04 h  MONITORING       the alarm did not persist through the confirmation window
 + 8.42 h  DRIFT_SUSPECTED  cusum raised an alarm at 12.49
 + 9.03 h  MONITORING       the alarm did not persist through the confirmation window
 + 9.84 h  DRIFT_SUSPECTED  cusum raised an alarm at 12.74
 +10.33 h  RECALIBRATING    refitted from 61 reference observations postdating the drift
 +10.82 h  MONITORING       the new profile verified; back to monitoring
```

Both faults detected within minutes, confirmed, corrected and verified. The two alarms in between
were rejected by the confirmation gate — which is the gate doing its job, not a shortcoming.

`tests/test_checkpoint_control.py` asserts all of this on a four-hour window so it runs in a test
suite; it is marked `slow`.

The dashboard half of the checkpoint is pinned from both sides without needing the stack:
`tests/test_dashboards.py` checks every panel queries a metric the registry declares, and
`test_checkpoint_control.py` checks every metric the calibration dashboard queries is actually
emitted by a closed-loop run. The first catches a typo; the second catches a declared metric that
nothing ever produces, which renders exactly the same empty graph. `wim_cal_covariance_trace` is the
one panel `StaticAffine` cannot fill — correctly, since it never updates — and the Kalman arm fills
it. The only link left unverified offline is the live scrape, which is what
`scripts/check_dashboards.py` is for:

```bash
docker compose --profile full up -d
wimsim control data/synthetic/S4_demo --otlp http://localhost:4317 --reference-every 2
python scripts/check_dashboards.py
```

---

## Two sensitivity floors

The single most useful thing phase 5 produced is a straight answer to "how small a drift can this
system act on", and it is bounded twice.

**The detector's slack.** CUSUM's slack is what makes it a drift detector rather than an outlier
detector: deviations smaller than `slack` sigmas never accumulate, so they are invisible
*permanently*, not merely slowly. Measured against a 50 kg residual spread over twenty runs of five
hundred passes:

| drift | as σ | detected |
|---|---|---|
| 25 kg | 0.5 | 0/20 |
| 30 kg | 0.6 | 3/20 |
| 50 kg | 1.0 | 12/20 |
| 100 kg | 2.0 | 19/20 |

**The confirmation gate**, which at the shipped settings is the *tighter* of the two:

```
minimum confirmable shift = confirm_sigma × 1.2533 × σ / sqrt(confirmation_passes)
```

At `confirm_sigma = 3` that is 0.841 σ with a 20-pass window, 0.686 at 30, and 0.485 at 60. The
1.2533 is √(π/2), the median's efficiency penalty — paid deliberately, because the mean cannot tell
five potholes in forty passes from a step.

I originally documented the detector's slack as "a hard floor under the whole loop". That is wrong
at default settings, and S4 is what showed it. Its injected step is ≈ 0.74 σ, which straddles the
two window lengths, and the outcome follows the arithmetic exactly — the fault was detected five
times in every configuration:

| confirmation window | confirmable floor | recalibrations | resulting bias |
|---|---|---|---|
| 30 | 0.686 σ | 0 | −136.9 kg *(uncorrected, reported as MONITORING)* |
| 60 | 0.485 σ | 2 | **−9.4 kg** |
| 90 | 0.343 σ | 2 | −23.8 kg |

Hence the default of 60. Ninety is worse than sixty rather than better: a longer window confirms
still smaller drifts but delays the correction, so more passes are measured under the faulty
calibration. Both floors are re-measured in `tests/test_controller.py`.

**Every detection claim has to quote the residual spread beside it**, because both floors are
expressed in it.

---

## The ladder

Three estimators, each one step from the last, so a result can be attributed.

| | fits | adapts | direction | attenuated by feature noise |
|---|---|---|---|---|
| `StaticAffine` | once, frozen | no | mass on feature | yes |
| `RecursiveLeastSquares` | continuously | forgetting factor λ | mass on feature | yes |
| `KalmanCalibration` | continuously | random walk on `[q, k]` | feature on mass | **no** |

**RLS changes exactly one thing.** Same model, same objective, same prediction direction as the
baseline; only the fit is never finished. With `λ = 1` it *is* recursive OLS — order-invariant, and
converging on the batch answer — which is what makes it a credible baseline rather than a new model.

The residual gap to batch OLS turned out to be worth chasing: 6.5e-10 relative on the gain but
~1e-5 kg on the bias. The obvious suspect is catastrophic cancellation in the covariance update, a
real and well-known RLS failure, so I measured instead of guessing. The error is exactly
proportional to `1/P₀` — a finite prior is ridge with penalty `1/P₀` — and *shrinks* with more data,
which is the opposite of what cancellation does on both counts. A loose tolerance would have hidden
the difference between the benign explanation and the dangerous one.

**Covariance windup is where the textbook problem meets WiM traffic.** A fleet that is 95 %
identical cars tells the recursion almost nothing new about the slope, but `λ < 1` keeps discounting
what it already knew, so `P` grows without bound and the estimator eventually swings wildly on one
unusual pass. That is a rural site at 3am, not a hypothetical. The remedy is a bound on `trace(P)`
applied by *scaling* rather than clipping the diagonal: the shape of `P` says which direction is
poorly informed, which is the useful part, and only its size needs a ceiling.

**The Kalman filter is a model of the plant, not a curve fit of the data.** Its state is `[q, k]` —
exactly what the truth log records — so the dashboard overlay is a comparison rather than a
conversion, and drift is a random walk on the state instead of a moving target the fit has to chase.

It is also the only rung not biased by feature noise. Regression dilution comes from noise in the
*regressor*; here the regressor is the reference mass (comparatively accurate, from a weighbridge)
and the noise sits in the observation, which is where a Kalman filter expects it. Measured with a
deliberately noisy feature: the baseline's sensor gain reads 10 % high, the filter's under 3 %. The
honest caveat is in the docstring — this is unbiasedness with respect to *feature* noise only, and
an uncertain reference mass dilutes this filter the same way.

Its process noise accrues with **elapsed time, not pass count**. A plant drifts on a clock, so two
passes an hour apart must admit more drift than two a second apart; without that, a filter tuned on
a motorway is mistuned on a quiet road and one config file means different things at different
sites. Gaps are clamped, because station clocks jump and a single sample stamped a year into the
future would otherwise inflate the covariance until the next pass overwrote everything the filter
knew.

The third state `[q, k, α]` the buildspec offers is deliberately absent. The obstacle is not the
algebra but a loop: the preprocessor compensates using the *active profile's* coefficient, so an
estimator fitting its own changes the features it is fitted on, and `offline.py`'s single pass stops
being valid. Adding the state without the two-pass structure would produce a number that looks like
a temperature coefficient and is not one.

### One thing the tests caught that nothing else would have

The adaptive estimators were **silently inert**. The loop folded every reference observation into
its own estimator with `update()`, while the pipeline rebuilt a separate instance from the profile
*state* — so an RLS run reported the same gain on every emitted event and was indistinguishable from
the static baseline. Nothing failed. `set_profile` now accepts a live instance, which also draws the
right distinction: continuous adaptation refines the law and keeps the profile id, while a wholesale
refit *is* a new profile with its own id, activation time and row in the store.

---

## Drift detectors

Four, because they fail differently and the experiment reports both false-alarm and
missed-detection rates — either alone is easy to make look good.

| detector | built to see | how it fails |
|---|---|---|
| CUSUM | a persistent shift in the mean | a spread change trips it, for the wrong reason |
| Page-Hinkley | the same, against a running mean | slower on a ramp that drags its own reference |
| ADWIN | any change in mean, self-chosen window | needs the buffer to span the change |
| KS window | any change in *distribution* | needs two full windows; slowest of the four |

**The defaults were measured, not inherited.** Each is the loosest setting whose false-alarm count
over thirty stationary runs of 800 observations is at most two:

| detector | default | false alarms | median delay to a 3σ step |
|---|---|---|---|
| CUSUM | `threshold=12, slack=0.5` | 2/30 | 5 |
| Page-Hinkley | `threshold=15, tolerance=0.5` | 0/30 | 6 |
| ADWIN | `delta=0.002` | 0/30 | 10 |
| KS | `window=60, alpha=1e-4` | 0/30 | 24 |

At CUSUM's conventional `h = 5` the false-alarm count was **25/30** — a station recalibrating
several times a day for no reason. The ordering is the expected one: cumulative sums fastest, ADWIN
paying a little to choose its own window, the distribution test paying most because it cannot speak
until it holds two full windows.

Three shared properties, each from a way this would go wrong in the field:

- **They learn their reference from the stream.** Residuals are not centred on zero — a slightly
  miscalibrated scale is biased from its first pass — so a detector assuming zero would call that
  drift.
- **They clip.** One pothole is one pothole. A 40σ pass puts a 40σ increment into a cumulative sum
  and trips CUSUM on the spot; clipping bounds a single bad pass while a persistent shift still
  accumulates without limit.
- **They latch.** ADWIN naturally raises its alarm only on the single update where it cuts its
  window, so a controller polling once per pass would miss it entirely. All four now hold the alarm
  until `reset()` acknowledges it.

### The folklore was wrong

I asserted the standard claim that CUSUM and Page-Hinkley are blind to a change in *spread*. They
are not: on a fourfold variance increase all four fire and CUSUM is the **fastest**, for the wrong
reason — a wider distribution random-walks the cumulative sum across the threshold sooner.

What genuinely separates them is a change that leaves *both* moments alone: Gaussian to two-point at
the same mean and variance, which is a fleet that has become two fleets, or a second failure mode
adding large errors that cancel on average. KS detects it 20/20; the three mean-based detectors
0/20. That is the real argument for the KS test, and measuring it replaced one wrong test with two
right ones.

---

## The MAPE-K machine

`MONITORING → DRIFT_SUSPECTED → RECALIBRATING → VERIFYING → MONITORING`, with `DEGRADED` whenever
the loop cannot close. It does no IO and holds no persistence — it returns events for the edge to
publish.

**`DEGRADED` is the point of the machine, not an error path.** A confirmed drift with no reference
vehicle to recalibrate against is the normal case on a real road, and the honest response is to say
so and keep saying so. A controller without it either recalibrates on nothing or pretends the alarm
never happened; both leave a scale weighing while it knows it is wrong, and only one of them tells
anyone. Verification failing lands there too — the most dangerous outcome available, because the
station has just announced that it fixed itself.

**Confirmation is a second opinion, not a wait.** The detectors are deliberately tuned to allow a
couple of false alarms per thirty runs, because tightening them further costs detection delay; the
confirmation window is what makes that trade affordable. It uses the **median** rather than the
mean, because a window spanning the alarm contains the bad passes that caused it and the mean cannot
tell five potholes from a step — with a 16σ blip in a forty-pass window the mean lands at 2σ and
confirms a drift that is not there. Scaled by the standard error rather than the raw spread, so the
gate still catches slow drift.

`confirm_sigma` is 3, not 1. At one sigma the gate is decorative — a 32 % false-confirmation rate by
construction. At three, measured: 0/30 blips confirmed.

**A refit uses only references from after the drift began.** Handing the whole buffer to the fit does
not work: measured on S4, a confirmed recalibration then removed only about a third of the bias, and
stayed there even after the loop declared itself reconverged. The buffer spans both sides of the
fault — 200 references at one in two passes is 400 passes of history — so the new profile was a
compromise between a plant that exists and one that does not. Filtering from the onset of the
suspicion is right for a ramp too, where it keeps the recent observations. When there are not yet
enough post-drift references the controller *waits* rather than fitting across the fault: a profile
fitted on a mixture is confidently wrong and passes verification often enough to hide it.

**`DEGRADED` retries only on new evidence.** A refit from the same observations is deterministic, so
a failed attempt fails identically; with a short cool-down the controller sat in a loop
recalibrating nine times, each time announcing it had fixed itself.

**The cool-down is on the station clock.** An hour is an hour whether forty vehicles crossed in it
or four.

**Arbitration is a switch because it is a deployment question.** A systematic error across twenty
stations is a fleet problem, and twenty stations independently recalibrating away from it destroys
the evidence that it was systematic.

---

## Uncertainty

Split conformal prediction, with two nonconformity scores. Coverage is guaranteed in *finite
samples* under exchangeability, and the `(n+1)` in the quantile index is what turns an asymptotic
statement into that guarantee — it only visibly matters at small `n`, which is exactly where a
station with a handful of reference vehicles permanently lives. Verified as an identity, and
separately over 200 draws: mean conditional coverage 0.9497 against a theoretical 190/200.

**The textbook justification is wrong, and measuring it gave a better one.** "A Gaussian interval
under-covers on non-Gaussian residuals" is false as a general claim: over sixty calibration draws
per shape it lands within 0.001 of nominal on Student-t(3) and within 0.006 on a lognormal —
essentially by luck, since the standard deviation is inflated by the same tail that produces the
extreme residuals and the two errors cancel. Where it fails it fails badly and in **both**
directions: 0.936 on a Laplace, and **1.000** on a bimodal residual stream, where a standard
deviation inflated by the hole in the middle gives a band so wide it can no longer distinguish an
overloaded truck from a legal one. Over-covering is not the safe failure it sounds like. So the claim
worth making is about *reliability*, not direction.

**The relative score answers a gap phase 4 found.** Once the Kalman filter converges, over 95 % of
its interval variance is `R/k²` — the sensor's own noise mapped into kilograms — which for an
additive noise does not depend on load at all. So the analytic interval is nearly constant-width, and
so is anything built from a residual spread. But weighing error is largely *proportional* to what is
being weighed, so a constant band over-covers cars and under-covers trucks while averaging out to
something that looks nominal. Normalising the score by the prediction fixes the shape without giving
up the guarantee, and turns marginal coverage into coverage that holds at every load.

The honest limitation is exchangeability, which drift breaks. The design is a bounded sliding
window, so coverage degrades into "recent history" rather than resting on a guarantee that has
quietly stopped applying; the controller resets it on recalibration, since old residuals describe an
estimator that no longer exists.

---

## The profile store, and `recompute`

Append-only, and that word decides how `superseded_by` works. The obvious implementation sets that
field on the previous row when a new profile activates — which means rewriting a line, which means a
calibration history that can be edited. An audit trail you can edit is not one. So the link is
*derived* from the sequence on read and never written, and a test checks the first line is
byte-identical after two more appends.

JSON Lines, stdlib only: a calibration history readable only by the program that wrote it is not
provenance, and a Pi with no database still needs a durable one across reboots.

`recompute --from <ts> --profile <id>` works because of three earlier decisions, none of which looked
like they were for this:

- **`event_id` is a UUIDv5 of station, sensor and `ts_start` and of nothing else** — not the mass,
  not the profile. A recomputed event keeps its id, so the phase-3 upsert updates the row in place
  instead of inserting a second opinion about the same vehicle.
- **`raw_peak` is stored before thermal compensation.** Recomputing from `compensated_peak` would
  leave the old profile's correction in place and put the new estimator on top of it — small,
  systematic, very hard to find.
- **`temperature_c` is stored per event**, which it was not until phase 4 noticed the column was
  always null. Without it the compensation could not be redone at all.

The strongest test is the identity one: recomputing under the profile that produced a row reproduces
its mass and interval to 1e-12. That is also what would catch the thermal-factor arithmetic drifting
away from the preprocessor's, since the two are deliberately separate — one works on numpy blocks,
one on a single stored row.

Refusals rather than guesses: an unfitted profile, or an estimator this build cannot construct, is
rejected *before any row is touched*, because half a recompute leaves a window holding masses from
two different laws with no way to tell them apart.

---

## Where the truth enters

The controller needs residuals and a residual needs a reference mass. In the field that comes from a
transponder-equipped fleet vehicle or a weighbridge up the road; here it is read from the truth log
by `_TruthReferences` in `experiments/closed_loop.py`, a class whose only job is to be the single
greppable boundary. What crosses into `calibration/` is a `ReferenceObservation` — a mass and a
feature — exactly what a weighbridge supplies.

`tests/test_truth_isolation.py` proves the import graph. `tests/test_closed_loop.py` adds an AST test
pinning the read sites: the truth mass columns are subscripted in one place, and the timestamp reads
elsewhere are for locating the calibration split, which is a time and not a mass.

**`reference_every_n` is the experiment, not a constant.** It is the supply rate of known masses, and
it decides whether self-calibration is possible at a site at all — a motorway with a co-located
weighbridge and a rural road with none are the same code and completely different problems.
`S7_sparse_reference` exists to push it to zero.

It also sets how long the *detectors* take to become usable, which is less obvious and cost an
afternoon. A detector's warm-up is counted in residuals, residuals arrive only on reference passes,
so readiness costs `drift.warmup × reference_every_n` passes. On S4 at the old default that was
33,144 s of a 57,600 s run — past both injected faults, which the detector had by then learned as
normal, reporting zero alarms and looking entirely healthy while doing it.
`detectors_ready_after_references` is on the result so that a run which could not have detected
anything says so.

---

## What is still open

- **Population reference mode.** `supervised` ships; `population` — self-calibration from the
  statistics of an assumed axle-load distribution, the classical WiM assumption — is phase 6 and is
  what `S7_sparse_reference` is for.
- **`[q, k, α]`**, blocked on the two-pass structure described above.
- **Directional forgetting** for RLS, in place of the trace bound.
- **The experiment runner**, which is what turns these paired runs into the results table phase 6
  asks for. Everything here has been measured one scenario at a time.
- **A real kilogram.** Nothing in this document has been validated against a weighed vehicle. The
  controller is measured against a simulator whose ground truth it cannot see, which establishes
  control behaviour and says nothing about metrological accuracy — see the note at the top of the
  README, which is not boilerplate.
