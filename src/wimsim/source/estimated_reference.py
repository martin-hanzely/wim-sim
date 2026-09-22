"""A ``reference.csv`` built from inferred wheel loads rather than from a weighbridge.

The eight real recordings carry no reference masses. Nothing was weighed, the rig is gone, and
nothing will be. ``docs/sim-to-real.md`` infers the loads instead, and this writes that inference
into the file the rest of the system already knows how to read.

**What this costs, stated once and plainly.** Principle 1 says ground truth is an output and never
an estimator input. A file written from published kerb weights and a split measured off the signal
is an estimate standing exactly where the pipeline expects a measurement. Scoring
``S8_replay_real`` against it measures whether the pipeline reproduces *the inference* -- not
whether it weighs vehicles. Nothing derived from it is a metrological claim, and the word
``ESTIMATED`` travels in every row and in a sidecar beside the file so that a reader who never
opens the docs still cannot miss it.

**The chain.** Skoda's published *operating weight* already includes a 75 kg driver, 90 % fuel and
the toolkit -- the condition a car being driven over a platform is in -- and is 1081-1204 kg across
Fabia petrol variants, centrally 1140 kg. The front/rear split is not assumed: the peak amplitudes
are bimodal in two tight clusters whose ratio is 1.39 (Citroen, n=16) and 1.41 (Fabia, n=4), and
two different cars agreeing on that ratio makes it a property of cars rather than of where a wheel
landed. 1.39-1.41 is 58-59 % on the front axle. With one wheel on the platform at a time, that puts
the Fabia's front wheel at 336 kg and its rear at 234 kg.

The Citroen was never identified, so its loads come from the measured peak ratio against the Fabia
rather than from a lookup: 1542-1603 kg with driver, which fits a C5 Aircross, Berlingo or C4 and
excludes a C3 at 958-1090 kg.

Which wheel produced a given crossing is read from the same bimodal amplitude, because it is the
only thing in the data that distinguishes them.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FABIA_FRONT_KG",
    "FABIA_REAR_KG",
    "VEHICLES",
    "Vehicle",
    "write_estimated_reference",
]

#: Marker file. Its presence is what licenses overwriting a `reference.csv`: an estimated file can
#: always be regenerated and a measured one cannot, so the writer refuses any file it did not
#: write itself.
SIDECAR = "reference.ESTIMATED.md"

#: The Fabia is the identified vehicle and anchors everything. Operating weight 1140 kg central,
#: 58.5 % on the front axle, one wheel at a time. Keep in step with
#: `configs/stations/cintron_platform.yaml` and `docs/sim-to-real.md`.
FABIA_FRONT_KG = 1140.0 * 0.585 / 2.0
FABIA_REAR_KG = 1140.0 * 0.415 / 2.0


@dataclass(frozen=True, slots=True)
class Vehicle:
    """Inferred wheel loads for one of the two cars."""

    name: str
    front_kg: float
    rear_kg: float
    axle_cut_strain: float
    """Peak amplitude separating the front cluster from the rear one.

    Taken across the whole corpus rather than per recording, because several recordings contain a
    single crossing and one point has no bimodality to read. Measured on Tenzo2: the Citroen's
    clusters sit at 13.52 and 9.73 microstrain, the Fabia's at 11.11 and 7.86."""
    note: str

    @property
    def front_rear_ratio(self) -> float:
        return self.front_kg / self.rear_kg


VEHICLES: dict[str, Vehicle] = {
    "fabia": Vehicle(
        name="Skoda Fabia",
        front_kg=FABIA_FRONT_KG,
        rear_kg=FABIA_REAR_KG,
        axle_cut_strain=9.5e-6,
        note="operating weight 1140 kg incl. 75 kg driver; 58.5 % front, measured from the "
        "bimodal peak amplitudes",
    ),
    "citroen": Vehicle(
        name="Citroen (model not identified)",
        # From the measured Citroen/Fabia peak ratio rather than a lookup: the model is unknown.
        front_kg=1573.0 * 0.585 / 2.0,
        rear_kg=1573.0 * 0.415 / 2.0,
        axle_cut_strain=11.5e-6,
        note="1573 kg with driver, inferred from the measured peak ratio against the Fabia; "
        "consistent with a C5 Aircross, Berlingo or C4, and excludes a C3",
    ),
}


def _wheel(peak_strain: float, vehicle: Vehicle, cut: float) -> tuple[float, str]:
    """Front or rear, from the bimodal peak amplitude -- the only thing that distinguishes them."""
    if abs(peak_strain) >= cut:
        return vehicle.front_kg, "front"
    return vehicle.rear_kg, "rear"


def write_estimated_reference(
    run_dir: Path | str,
    crossings: list[tuple[float, float]],
    *,
    vehicle: str,
    t0_us: int,
) -> int:
    """Write ``reference.csv`` and its sidecar from detected crossings.

    ``crossings`` is ``(t_peak_s, peak_strain)`` per crossing, as ``wimsim detect`` reports them,
    and ``t0_us`` is the recording's own first sample timestamp. Returns the rows written.

    ``t0_us`` is required rather than defaulted. It was a default once -- one recording's start time,
    quietly applied to all eight -- and the seven files that got the wrong epoch were placed 300 to
    400 seconds before their own recordings began. Nothing complained, because nothing read the
    files yet; the error surfaced only when `score-real` matched zero of them.

    Refuses to overwrite a ``reference.csv`` that has no sidecar beside it. A measured reference
    file cannot be regenerated and an estimated one always can, and that asymmetry decides: the
    caller has to delete a real one on purpose.
    """
    if vehicle not in VEHICLES:
        raise ValueError(f"unknown vehicle {vehicle!r}; known: {sorted(VEHICLES)}")
    spec = VEHICLES[vehicle]

    out = Path(run_dir)
    target = out / "reference.csv"
    if target.exists() and not (out / SIDECAR).exists():
        raise FileExistsError(
            f"{target} exists and was not written by this command, so it may be a real weighing. "
            "An estimated reference can always be regenerated; a measured one cannot. Delete it "
            "deliberately if you mean to replace it."
        )

    # The corpus-wide cut, not a per-run one. Several recordings hold a single crossing, and one
    # point has no bimodality to read -- a midpoint computed from it would classify by rounding.
    cut = spec.axle_cut_strain

    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["pass_id", "reference_mass_kg", "t_approx", "vehicle_description", "axle_reference_kg"]
        )
        for i, (t_peak_s, peak) in enumerate(crossings):
            mass, which = _wheel(peak, spec, cut)
            writer.writerow(
                [
                    f"est-{i:03d}",
                    f"{mass:.1f}",
                    int(t0_us + t_peak_s * 1e6),
                    f"ESTIMATED, not weighed -- {spec.name}, {which} wheel. {spec.note}",
                    f"{mass:.1f}",
                ]
            )

    (out / SIDECAR).write_text(_sidecar(spec, len(crossings), cut), encoding="utf-8")
    return len(crossings)


def _sidecar(spec: Vehicle, n: int, cut: float) -> str:
    return f"""# `reference.csv` here is ESTIMATED, not measured

**No vehicle at this site has been weighed.** This file was generated by
`wimsim write-estimated-reference` from published vehicle weights and from the signal itself. It is
not a weighing, and nothing derived from it is a metrological claim.

Scoring against it measures whether the pipeline reproduces **the inference below** -- not whether
it weighs vehicles. Principle 1 says ground truth is an output and never an estimator input; here
an estimate stands where the pipeline expects a measurement, and that is a known and deliberate
compromise rather than an oversight.

## The chain

Skoda publishes an *operating weight* that already includes a 75 kg driver, 90 % fuel and the
toolkit -- the condition a car being driven over a platform is in. That anchors the Fabia; the
Citroen, never identified, is inferred from the measured peak ratio against it.

* {spec.name}
* {spec.note}
* front wheel **{spec.front_kg:.0f} kg**, rear wheel **{spec.rear_kg:.0f} kg**
* {n} crossings, split front/rear at a peak amplitude of {cut:.3g} strain -- the midpoint of the
  two amplitude clusters, which is the only thing in the data that distinguishes the axles

Full derivation, with its uncertainties and the ways it could be wrong, is in `docs/sim-to-real.md`
under "Wheel loads, estimated" and "Speed, inferred from the wheelbase".

## What would replace it

One weighbridge ticket for either car. The axle split is now measured rather than assumed, so a
single known mass would collapse most of what remains.

Delete this file and `reference.csv` together if a real reference ever arrives -- the writer refuses
to overwrite a `reference.csv` that has no sidecar beside it, precisely so a measured file cannot be
clobbered by an estimated one.
"""
