# Sim-to-real: what the first recording says

One recording so far: `20260209_cintron1.csv`, 9 Feb 2026 09:38:25 local, 60.000 s, 25 kHz, four
channels (`Temp1`, `Temp2` in °C; `Tenzo1`, `Tenzo2` in strain).

```bash
wimsim import-csv 20260209_cintron1.csv --out data/real/20260209_cintron1 \
  --station-id ST-CINTRON-1 --gauge-factor 2.0
wimsim validate-real-data data/real/20260209_cintron1
```

175 MB of CSV becomes 9.1 MB of Parquet. The importer is reusable for the remaining drives.

> **This recording contains no vehicle passes.** The largest excursion is 13.6 noise deviations and
> lasts two seconds; an axle pulse is hundreds of deviations and lasts milliseconds. That makes it an
> excellent noise-and-drift characterisation and useless for calibration or scoring. The validator
> now says so at the door rather than letting someone fit a gain to nothing.

---

## Unit conversion, and what it rests on

The recording is in strain. The simulator works in mV/V. For a quarter bridge,

```
mV/V = (GF / 4) * epsilon * 1000        GF = 2.0 assumed  =>  mV/V = 500 * epsilon
```

**`gauge_factor` and the bridge configuration were not in the export**, so `GF = 2.0` and "quarter
bridge" are assumptions passed on the command line and recorded in `run.yaml`. Every mV/V figure
below scales linearly with `GF/4`; if the real bridge is half or full, divide accordingly. This is
the first thing to confirm.

| quantity | measured (strain) | as mV/V | as kg at `k0 = 2e-4` |
|---|---|---|---|
| baseline, Tenzo1 | 111.6 µε | 0.0558 | — |
| baseline, Tenzo2 | 120.8 µε | 0.0604 | — |
| total noise sd, Tenzo1 | 1.39 µε | 7.0e-4 | 3.5 |
| total noise sd, Tenzo2 | 1.88 µε | 9.4e-4 | 4.7 |

The **baseline is a good match to the model's `q0 = 0.05 mV/V`** — 0.056 measured against 0.050
assumed, which is closer than it had any right to be given the parameter was picked for plausibility.

---

## Finding 1: mains interference dominates, and the model had it switched off

| | Tenzo1 | Tenzo2 |
|---|---|---|
| 50 Hz above local floor | **+54.0 dB** | **+51.3 dB** |
| 100 Hz | +26.6 dB | +22.0 dB |
| 150 Hz | +11.9 dB | +22.1 dB |
| 250 Hz | +30.1 dB | +20.4 dB |
| sd in 10–100 Hz | 1.23 µε | 1.12 µε |
| sd, all bands | 1.39 µε | 1.88 µε |

**Nearly all of the in-band noise is mains and its harmonics.** The model treated mains as an
optional nuisance — `enabled: false` in five of eight scenarios, amplitude `1e-4 mV/V`. Measured
amplitude is `8.7e-4 mV/V`, roughly nine times larger, and it is the dominant term rather than a
minor one.

This matters more than its size suggests. Mains is *coherent*: unlike white noise it does not average
down over a pulse, so a 5 ms window sees a nearly constant offset drawn from a ±8.7e-4 mV/V
sinusoid — about ±4 kg — whose value depends on where in the mains cycle the axle happened to arrive.

Measured on `S1_nominal`, changing nothing but this switch:

| | MAE | MAPE | empirical coverage |
|---|---|---|---|
| mains off | 1.13 kg | 0.039 % | 0.906 |
| mains on, measured amplitude | **6.42 kg** | 0.237 % | **0.750** |

A 5.7× cost in accuracy, and coverage falls from near-nominal to 0.75 — because the error is
*structured*, not Gaussian, so the analytic interval misprices it. That makes the 50 Hz notch a real
design question for phase 6 rather than a box to tick, and it is a second concrete case for
conformal intervals.

Now enabled with the measured amplitude and harmonic ratios in every scenario **except
`S1_nominal`**, whose job is to be the floor where a non-zero error can only mean a bug.

## Finding 2: the white-noise level was about right

Above 200 Hz the spectrum is flat: PSD slope −0.03 (Tenzo1) and −0.02 (Tenzo2). Converting the
100–1000 Hz band to a 2 kHz-sampled equivalent gives a per-sample sd of **1.2e-4 mV/V** against the
model's assumed `2.0e-4`. Within a factor of two, and now set to the measured value.

## Finding 3: low-frequency drift is Brownian, not flicker

PSD slope over 0.05–20 Hz is **−1.96** (Tenzo1) and **−2.65** (Tenzo2). A slope of −1 is flicker
(1/f); −2 is a random walk. The model carries both — a `pink_sigma` at slope −1 and a
`random_walk_sigma_per_sqrt_s` at slope −2 — and the measurement says the random walk is doing the
work and the flicker term is not what dominates.

Taking the 0.02–1 Hz content as a random walk over 60 s gives σ ≈ **2.2e-5** (Tenzo1) and **7.1e-5**
(Tenzo2) mV/V per √s. The shipped scenarios use 2e-5 (`S4`) to 8e-5 (`S3`), so **the drift model was
already in the right range.**

**Not changed, deliberately.** Sixty seconds gives about one and a half decades of low-frequency
resolution and cannot separate a random walk from a slow deterministic trend, nor from the single
two-second event described below. Re-deriving the drift model from it would be over-fitting one
minute of data. *A quiet recording of an hour or more would settle this*, and it is cheap to make.

## Finding 4: an event that is not a vehicle, and I cannot tell what it is

Between t ≈ 14.0 s and 16.0 s **both channels deflect downward together** and return:

| | quiet | trough at ~15.1 s | change |
|---|---|---|---|
| Tenzo1 | 112.9 µε | 108.7 µε | −4.2 µε |
| Tenzo2 | 120.3 µε | 107.5 µε | −12.8 µε |

Correlation between the channels rises from +0.28 over the whole run to **+0.71** inside this window,
so it is a common cause rather than coincidence, and Tenzo2 responds about three times as strongly as
Tenzo1.

It is **not an axle pulse**: it is three orders of magnitude too slow. Two seconds at any credible
road speed is tens of metres.

What it is consistent with is a **slow structural load** — something that puts weight on the
structure, stays for a second or two, and comes off. Which raises a question the recording cannot
answer, and it is the most consequential open question in the project right now:

> **What do Tenzo1 and Tenzo2 measure, and where are they mounted?**

* If they are **strip or bending-plate sensors under the tyre path**, the measurement is a contact
  force and the model's pulse shape (`FWHM = contact_patch / speed`, milliseconds) is right. This
  event is then something else — a person, a cable, a thermal transient.
* If they are **strain gauges on a structural member**, the measurement is the structure's deflection
  under load. A vehicle then produces a smooth envelope lasting as long as it is on the span, not a
  per-axle pulse, and **the generative model's pulse shape is the wrong shape** — which would
  invalidate the peak-versus-area conclusion from phase 2, since both features assume a pulse.

Nothing has been changed on the strength of this. It is one event in one minute with no reference
data, and rewriting the signal model on that basis would be exactly the over-fitting this document
exists to avoid.

---

## What the model got right, and what is still unverified

**Right:** baseline level (0.056 vs 0.050 mV/V), white-noise level (within 2×), drift magnitude
(within the shipped range), and the two-temperature arrangement — the real station has a probe per
sensor, and the model already distinguishes true sensor temperature from what a probe reports.

**Wrong:** mains treated as optional when it dominates; flicker weighted more heavily than the
random walk.

**Still unverified, because this recording cannot speak to it:**

* **pulse shape** — no passes. The single most important thing to check, and the thing that
  determines whether the phase-2 feature comparison holds.
* **sensitivity `k0`** — needs a known mass. Nothing here relates strain to kilograms.
* **temperature coefficient `alpha` and the thermal time constant** — the recording spans 60 s and
  0.23 °C. Establishing a thermal model needs hours across a day.
* **speed observability** — there are **two strain channels**, so if they are at a known spacing,
  speed *is* measurable, and the phase-2 finding that area cannot be speed-normalised may not apply
  to this installation. The channel separation is not in the export.

## What would help most, in order

1. **A recording with vehicle passes**, even a handful, even without reference masses. This settles
   the pulse-shape question, which everything downstream rests on.
2. **The station geometry**: what the sensors are, where they are mounted, and the distance between
   Tenzo1 and Tenzo2. Speed observability depends entirely on this.
3. **Gauge factor, bridge type and excitation**, so the strain-to-mV/V conversion stops being an
   assumption.
4. **One long quiet recording** (an hour or more) to pin the drift model properly.
5. **Reference masses** for at least a few passes, which is what turns the rest into an accuracy
   figure rather than a characterisation.
