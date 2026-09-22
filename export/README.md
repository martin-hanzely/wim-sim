# Export — start here

This directory is self-contained. Everything needed to write Sections VI–VIII and revise III–V is
here; nothing below requires running the code.

## Read in this order

1. **[`CONTRADICTIONS.md`](CONTRADICTIONS.md)** — every claim in the drafted Sections III–V checked
   against the code, with a verdict and a file reference. **Read this before touching the
   manuscript.** Six claims are wrong in ways that change what the paper can say.
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
| `figures/` | 13 figures × PNG (300 dpi) / PDF / SVG |

## What a clone of this repository does *not* contain

Three things are gitignored and will not be present:

- **`data/results/`** — the parquets the CSVs were built from. The CSVs here carry the same
  per-seed values, so nothing is lost, but `scripts/build_export.py` cannot be re-run from a fresh
  clone.
- **`data/real/`** — the eight recordings, except `EXAMPLE`. They are large and not ours to
  redistribute. The derived `reference.csv` files are absent with them.
- **`data/synthetic/`** — regenerable from config and seed by construction.

Everything in `export/` is tracked, CSVs included, precisely because of the above.

## Three things to know before writing

1. **The governed loop does not beat B2 on MAE** — not on any scenario, at any reference rate. It
   changes MAE by 0.0 % in 13 of 17 tested cells and makes it worse in two. It removes systematic
   *bias* (RLS on S4: −41.0 → −8.8 kg), which is the defensible claim, and it is narrower than the
   one drafted.
2. **The calibration map is two-parameter.** There is no `θ₂·(s·ΔT)`, no online temperature
   identification, and no recoverable `α`. Everything in §III-B that follows from `θ₂` has no
   implementation behind it.
3. **No reference mass has ever been measured.** Every real-data kilogram descends from published
   vehicle weights and an axle split inferred from the signal. No vehicle at the site was weighed,
   and the rig has been removed.

## Reproducing anything here

Commands are in `data/manifest.json` per file. The sweeps:

```bash
wimsim experiment ladder          --out data/results/ladder          # 63 runs, ~65 min
wimsim experiment reference_rate  --out data/results/reference_rate  # 180 runs, ~105 min
wimsim experiment governance      --out data/results/governance      # 18 runs, ~55 min
python scripts/build_export.py                                       # rebuilds data/ and figures/
```

Real data (needs `data/real/`, which is not in the clone):

```bash
wimsim score-corpus data/real        # leave-one-recording-out
wimsim check-channels data/real      # two-gauge cross-check
wimsim gap-report data/real/20260209_cintron1 --channel Tenzo1
```
