# Sim-to-real: what the real recordings say

Eight recordings from 2026-02-09, plus eleven photographs of the rig. 60.000 s each at 25 kHz, four
channels (`Temp1`, `Temp2` in °C; `Tenzo1`, `Tenzo2` in strain). Five runs with a Citroën
(09:38–09:44), a nine-minute vehicle swap, then three with a Škoda Fabia (09:53–09:56). One file is
named `..._spat` — Slovak for *back* — which turns out to matter.

```bash
for f in WiM-Data/*.csv; do
  wimsim import-csv "$f" --out "data/real/$(basename "$f" .csv)" \
    --station-id ST-CINTRON-1 --gauge-factor 2.0
done
```

1.4 GB of CSV becomes 71 MB of Parquet. The importer, written against one file, handled all eight
without modification.

---

## The headline: this is not the sensor the buildspec assumes

The model — and the buildspec's whole framing — assumes a sensor that **measures contact force under
a tyre**: an axle pulse whose width is the tyre footprint divided by speed, milliseconds long, one
pulse per axle.

The hardware is **two strain gauges on a structural member**. A crossing produces the member's
*influence line*: a single smooth deflection **0.4–1.2 seconds** long in which the two axles of a car
are barely resolved. The photographs show why — a row of paving slabs with an instrumented steel
element set into it, a blue junction box, and a car driven over the line at walking-to-jogging pace.

| | contact-force model (what was built) | structural response (what exists) |
|---|---|---|
| width set by | tyre footprint ÷ speed | influence length ÷ speed |
| typical width | ~5 ms | ~700 ms at test speed |
| axles | one pulse each, resolved | overlapped into one envelope |
| polarity | positive-going | **negative-going** (compressive) |

Neither is wrong; they are different instruments. The simulator now models both —
`pulse.shape: influence_line` with `pulse.width_source: influence_length`, and
`configs/stations/cintron_platform.yaml` — with the contact-force stations left exactly as they were.

---

## What 22 clean crossings establish

Events were extracted from all eight recordings by low-passing at 25 Hz and thresholding the
stronger channel; crossings longer than 2 s were set aside as parked or creeping vehicles.

### 1. Peak amplitude is load-dependent — the prerequisite for weighing

| | Tenzo1 | Tenzo2 |
|---|---|---|
| Citroën (n=16) | −4.50 ± 0.60 µε | −13.06 ± 1.50 µε |
| Fabia (n=6) | −3.20 ± 0.54 µε | −9.07 ± 1.68 µε |
| ratio | **1.405** | **1.440** |
| Welch *p* | 6.2 × 10⁻⁴ | 8.6 × 10⁻⁴ |

The two channels agree on the ratio to within 3 % despite differing by a factor of three in
sensitivity. The sensor measures load.

### 2. Peak amplitude is speed-independent — which validates the peak feature

Correlation between peak amplitude and the speed proxy: **+0.13** (Citroën), **−0.31** (Fabia), both
weak. The response is quasi-static in this speed range, so the peak is a load measurement and not a
rate measurement. That is exactly the property phase 2 concluded made `peak` the better feature, now
confirmed on the real instrument for a different reason.

### 3. Speed *is* observable here — which overturns a phase-2 conclusion

Phase 2 concluded that a single sensor cannot measure speed, so the `area` feature cannot be
speed-normalised. **That does not apply to this installation.** The two gauges are separated along
the direction of travel, and the interval between their peaks is a direct speed measurement:

| direction | n | peak-time offset | mean duration |
|---|---|---|---|
| Tenzo1 first | 11 | +236 ms (Citroën), +225 ms (Fabia) | 0.5–0.6 s |
| Tenzo2 first | 11 | −386 ms (Citroën), −521 ms (Fabia) | 0.9–1.0 s |

Eleven each way — the vehicle was driven back and forth, exactly as the `_spat` filename implies.
**The sign of the offset is the direction of travel.** The magnitude is larger in the direction
where the crossing also lasted longer, i.e. the slower direction, as it must be if both scale as
1/speed.

That last point is worth stating as a check rather than an observation, because it is what makes the
interpretation safe:

```
pulse FWHM = 1.84 x |peak-time offset|      r = +0.965  (n = 22)
duration   = 2.09 x |peak-time offset|      r = +0.924
```

Both quantities scale as 1/*v*, so their ratio is pure geometry and **contains no speed at all**:
the sensor's influence length is 1.84 × the gauge separation, measured, with no assumptions.

### 4. What cannot be pinned without the station geometry

Speed is `L / Δt` where `L` is the gauge separation, and `L` is not in the data. The observed
offsets span 162–739 ms, a factor of 4.6 in speed. For scale:

| if the mean crossing were | then L is |
|---|---|
| 5 km/h | 0.46 m |
| 10 km/h | 0.91 m |
| 15 km/h | 1.37 m |

One number — the gauge separation, or the speed of any single run — fixes all of it, including the
influence length via the 1.84 ratio. **This is the single most valuable missing measurement.**

---

## Corrections the recordings forced

### Mains dominates the noise, and the model had it switched off

50 Hz sits **+54 dB** above the local noise floor with harmonics to 250 Hz; 1.23 of the 1.39 µε total
noise lives in the 10–100 Hz band. The model treated mains as an optional nuisance at
`1.0e-4 mV/V`; measured amplitude is `8.7e-4`.

Mains is *coherent*, so unlike white noise it does not average down over a pulse. Measured on
`S1_nominal`, changing nothing else: **MAE 1.13 → 6.42 kg, empirical coverage 0.906 → 0.750** —
because the error is structured, not Gaussian, and the analytic interval misprices it. A second
concrete case for conformal intervals in phase 5, and it makes the 50 Hz notch a real design
question.

Now enabled with measured values everywhere except `S1_nominal`, which stays the clean floor.

### The pulse shape: chosen by fitting, not by eye

Six clean crossings, four candidate shapes, normalised RMS residual:

| shape | residual |
|---|---|
| **parabola** `1 − u²` | **5.2 %** |
| raised cosine (Hann) | 6.9 % |
| Gaussian | 8.7 % |
| triangle (textbook influence line) | 10.2 % |

The parabola wins on five of six events. The residual 5 % is real structure — two overlapping axles,
and a member that is not an ideal simply-supported beam — so this is a defensible primitive, not a
claim of exactness.

### The validator was wrong on seven of eight recordings

It reported "no vehicle passes" for recordings containing several. Two independent bugs, both
instances of the same mistake — **using a contaminated statistic to detect its own contamination**:

* The noise scale came from the *low quantiles*, which is precisely where a compressive excursion
  lives. The excursion inflated the scale it was being measured against. Now the scale is the median
  absolute **successive difference**, which is blind to any signal slower than the sample rate and
  sees only sample-to-sample noise.
* The baseline was a *rolling* median. A window narrow enough to reject drift is narrower than a car
  parked on the sensor for a third of the recording, so it tracked the loaded level and subtracted
  the event away. A plain median is unbiased while under half the record is loaded, which is the
  regime these recordings are in — and the cost, that a very large slow drift would read as a pass,
  is written down rather than left implicit.

After the fix all eight report excursions of 11–34 σ. Four regression tests cover the negative-going
case, the mostly-loaded case, and the drift-is-not-a-pass control.

### What the model already had right

Baseline 0.056 vs 0.050 mV/V assumed. White noise within a factor of two. Drift magnitude inside the
shipped range. A temperature probe per sensor, distinct from the true sensor temperature. The
low-frequency slope is −1.96 to −2.65, i.e. Brownian rather than flicker — the random walk is doing
the work and the pink term is not what dominates.

**The drift model was deliberately not re-derived.** Sixty seconds gives about a decade and a half of
low-frequency resolution and cannot separate a random walk from a slow trend. Re-fitting it would be
over-fitting one minute.

---

## What this does and does not change

**Phase 2's peak-over-area conclusion survives, for a better reason than it was made.** It was
argued from "a single sensor cannot measure speed". Here speed *can* be measured — and peak still
wins, because peak amplitude is speed-independent while area is not. Two different routes, same
answer.

**The `S8_replay_real` scenario still cannot be scored.** No reference masses have been weighed. The
recordings establish that the sensor responds to load repeatably and discriminates two vehicles by
44 %; turning that into kilograms needs one known mass.

**The two-sensor question is now open and is a scope decision, not a bug.** The station model, the
source adapter and the detector all assume one measurement channel. Supporting a sensor *pair* —
speed from the inter-gauge delay, then genuinely speed-normalised area, then a peak-versus-area
comparison that is fair to both — is a real piece of work and it belongs in phase 6 alongside the
experiment runner. Worth doing: it is the configuration the hardware actually is.

## What would help most, in order

1. **The gauge separation in metres**, or the speed of any single run. One number fixes speed,
   influence length, and the width scale of the whole model.
2. **One weighed vehicle.** Without it there is no kilogram anywhere in this project that came from
   the real sensor.
3. **A recording at road speed**, if the deployment is meant to be a road. Everything here is
   walking-to-jogging pace, and whether the response stays quasi-static at 90 km/h is exactly the
   question a WiM system turns on.
4. **Gauge factor, bridge type and excitation**, so the strain-to-mV/V conversion stops being an
   assumption.
5. **Axle-level reference** — which axle weighed what — if per-axle estimation is ever in scope.
   At the observed influence length the two axles of a car are barely resolved, so this may be
   physically unavailable rather than merely unmeasured.
