# Export — start here

This directory is self-contained. Everything needed to write Sections VI–VIII and revise III–V is
here; nothing below requires running the code.

## Read in this order

1. **[`CONTRADICTIONS.md`](CONTRADICTIONS.md)** — every claim in the drafted Sections III–V checked
   against the code, with a verdict and a file reference. **Read this before touching the
   manuscript.** Six claims are wrong in ways that change what the paper can say, and the block
   added 2026-10-03 at the top lists five more — two of which contradict what this export
   itself said a day earlier.
2. **[`RESULTS.md`](RESULTS.md)** — the numbers, organised by manuscript subsection. Opens with the
   B2 comparison, because the central claim does not survive it.
3. **[`OPEN.md`](OPEN.md)** — the constants actually used, what is missing, what is not implemented,
   and the results that overturned an earlier conclusion.
4. **[`figures/FIGURES.md`](figures/FIGURES.md)** — what is in each image, for writing captions
   without opening them.

## What is here

| | |
|---|---|
| `data/*.csv` | long format, **one observation per row, per seed** — aggregates can be recomputed and dispersion re-derived |
| `data/manifest.json` | commit and config hashes, package versions, per-file commands, wall-clock times |
| `figures/` | 80 PNGs at 300 dpi, nine figure kinds across fourteen sweeps. **PNG only** — the PDF and SVG files earlier versions carried were renders by figure code that no longer exists and are deleted on rebuild |

## What a clone of this repository does *not* contain

Three things are gitignored and will not be present:

- **`data/results/`** — the parquets the CSVs were built from. The CSVs here carry the same
  per-seed values, so nothing is lost, but `scripts/build_export.py` cannot be re-run from a fresh
  clone.
- **`data/real/`** — the eight recordings, except `EXAMPLE`. They are large and not ours to
  redistribute. The derived `reference.csv` files are absent with them.
- **`data/synthetic/`** — regenerable from config and seed by construction.

Everything in `export/` is tracked, CSVs included, precisely because of the above.

## Five things to know before writing

Revised 2026-10-03. Point 1 has changed since the previous export and the change is the reason to
re-read it.

1. **The governed loop does not beat B2 on MAE for an estimator that already tracks** — not on any
   scenario, at any reference rate, now at fifteen seeds and seven rates. The largest effect
   across fourteen adaptive cells is −0.36 kg. **But it does beat frozen calibration, and that is
   new:** `reference_rate30` / S4 / one reference in two / static_affine is −33.4 kg at
   p_holm = 0.0077 over a 42-test family, the first governed-versus-ungoverned result in this
   project to survive correction. The loop recovers about three quarters of what continuous
   tracking is worth, only down to one reference in three, and it **overshoots the bias through
   zero** rather than reducing it (−144.1 kg ungoverned to +28.2 kg governed at the dense end).
2. **The calibration map is two-parameter.** There is no `θ₂·(s·ΔT)`, no online temperature
   identification, and no recoverable `α`. Everything in §III-B that follows from `θ₂` has no
   implementation behind it.
3. **No reference mass has ever been measured.** Every real-data kilogram descends from published
   vehicle weights and an axle split inferred from the signal. No vehicle at the site was weighed,
   and the rig has been removed.
4. **Detection recall does not reach zero, and an earlier version of this document said it did.**
   At three seeds recall is 0.000 at one reference in twenty and fifty; at fifteen it is 0.200 and
   0.067 on S7. The three-seed zeros were sampling zeros. More importantly, recall does not reach
   *one* either: with **every vehicle a reference**, S4 answers 0.611 of its injected faults. That
   bounds any claim about what denser reference supply would buy.
5. **Three of §VI-B's five surviving comparisons reproduce on held-out scenarios; two do not**, and
   the two failures are confounded with difficulty — see §B4, which states the confound before
   drawing any conclusion. Separately, the Kalman estimator is reliably worse than its own frozen
   prior wherever there is nothing to track: +251 kg on a held-out no-fault thermal scenario with
   a rank-biserial of +1.00, and +29.3 kg in the ablation arm with the calibration faults
   removed.

## Reproducing anything here

Commands are in `data/manifest.json` per file. The sweeps:

```bash
# the four sweeps added 2026-10-02, sharded by seed because the seed axis is the one that
# concatenates exactly -- see src/wimsim/experiments/merge.py for what is checked before merging
wimsim experiment heldout30        --seeds 1,2,3 --out data/results/heldout30_s1   # x10 shards
wimsim experiment ablation         --seeds 1,2   --out data/results/ablation_s1    # x5  shards
wimsim experiment reference_rate30 --seeds 1,2,3 --out data/results/reference_rate30_s1  # x5
wimsim validate-sim data/real --channel Tenzo2 --out data/results/sim_crossval

# then, per merged sweep
wimsim compare          data/results/<sweep>     # comparisons.md and .json
wimsim reference-curve  data/results/<sweep>     # only for a sweep that varied the rate
python scripts/build_export.py                   # rebuilds data/ and figures/
```

Real data (needs `data/real/`, which is not in the clone):

```bash
wimsim score-corpus data/real        # leave-one-recording-out
wimsim check-channels data/real      # two-gauge cross-check
wimsim gap-report data/real/20260209_cintron1 --channel Tenzo1
```
