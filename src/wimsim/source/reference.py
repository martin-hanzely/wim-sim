"""Reading ``reference.csv`` into the frame the scoring path already understands.

The file has existed in the schema since phase 3 and ``replay.py`` has said since then that scoring
against it is phase 6 work. Nothing read it: every entry point took its masses from the truth log,
which a recording does not have, so a validated ``reference.csv`` sat beside eight recordings doing
nothing.

**A reference is not truth, and the difference is load-bearing.** Ground truth is what the simulator
knows because it generated it; a reference measurement is an observation with its own error, which
is exactly why :class:`~wimsim.calibration.base.ReferenceObservation` exists and why an estimator is
*allowed* to see one. Principle 1 is not weakened by this path -- it is the path principle 1 was
drawn around.

What that costs, concretely, is that two columns the synthetic truth log carries cannot be filled:

``applied_mass_kg``
    The dynamic load a vehicle actually delivered, as distinct from its static mass. A weighbridge
    reports the static mass and nothing else, so this is ``NaN`` -- and ``dynamic_floor_kg`` comes
    out ``NaN`` with it, rather than ``0.0``, which would read as "these vehicles bounced not at
    all" instead of "nobody knows".
``vehicle_class``
    Taken from the description, which is free text.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pandas as pd

__all__ = ["REFERENCE_FILE", "load_reference"]

REFERENCE_FILE = "reference.csv"


def _epoch_us(raw: str) -> int:
    """``t_approx`` is epoch microseconds or ISO 8601, per the schema."""
    text = str(raw).strip()
    try:
        return int(float(text))
    except ValueError:
        stamp = pd.Timestamp(text)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return int(stamp.timestamp() * 1e6)


def load_reference(
    run_dir: Path | str,
    *,
    t0_us: int,
    window_s: float = 1.5,
) -> pd.DataFrame:
    """Load ``reference.csv`` into the columns :func:`~wimsim.experiments.scoring.match_events`
    and :func:`~wimsim.experiments.offline.run_offline` expect of a truth frame.

    ``t0_us`` is the recording's first sample timestamp, which fixes the epoch: the file carries
    absolute times and the pipeline works in seconds since the run began.

    ``window_s`` is the half-width of the window each reference is given for matching. A reference
    records *approximately* when a vehicle crossed -- the column is called ``t_approx`` -- so it
    cannot supply the entry and exit times a generated pass has, and the window stands in for them.
    On the real recordings the crossings are about a second wide, so 1.5 s is a little over one
    crossing either side.
    """
    path = Path(run_dir) / REFERENCE_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist, so this recording can be replayed but not scored. "
            "`wimsim validate-real-data` reports the same thing."
        )

    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            ts_us = _epoch_us(row["t_approx"])
            t_peak_s = (ts_us - int(t0_us)) / 1e6
            rows.append(
                {
                    "pass_id": row.get("pass_id") or f"ref-{i:03d}",
                    "pass_index": i,
                    "vehicle_class": (row.get("vehicle_description") or "reference")[:60],
                    "t_entry_s": t_peak_s - window_s,
                    "t_exit_s": t_peak_s + window_s,
                    "t_peak_s": t_peak_s,
                    "ts_peak_us": ts_us,
                    "true_mass_kg": float(row["reference_mass_kg"]),
                    # A weighbridge reports the static mass and nothing else. NaN rather than a
                    # copy of it, so `dynamic_floor_kg` comes out NaN instead of 0.0 -- which would
                    # read as "these vehicles bounced not at all" rather than "nobody knows".
                    "applied_mass_kg": math.nan,
                    "axle_count": 1,
                    "speed_kmh": math.nan,
                }
            )

    if not rows:
        raise ValueError(f"{path} has a header but no rows; there is nothing to score against.")
    return pd.DataFrame(rows).sort_values("ts_peak_us").reset_index(drop=True)
