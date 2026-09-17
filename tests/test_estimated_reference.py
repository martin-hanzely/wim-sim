"""Writing a `reference.csv` from inferred wheel loads.

The eight real recordings have no reference masses. Nothing has been weighed, and the rig is gone,
so nothing will be. `docs/sim-to-real.md` infers the wheel loads from the Fabia's published
operating weight and the front/rear split measured off the bimodal peak amplitudes, and this turns
that inference into the file the pipeline expects.

**These are estimates standing where the pipeline expects a weighing, and that is a real cost.**
Principle 1 says ground truth is an output, never an estimator input; here it becomes an input that
was itself derived from the signal. Scoring `S8_replay_real` against this file measures whether the
pipeline reproduces *the inference*, not whether it weighs vehicles. The tests below are mostly
about making that impossible to forget:

* every row says ESTIMATED in its description, and names the chain it came from;
* a sidecar records the assumptions, so a reader of the directory cannot miss them;
* the writer refuses to overwrite a real reference file, because a measured one is not
  reproducible and an estimated one is.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from wimsim.source.estimated_reference import (
    FABIA_FRONT_KG,
    VEHICLES,
    write_estimated_reference,
)


def _crossings():
    """(t_peak_s, peak_strain) as `wimsim detect` reports them: front wheels heavier."""
    return [(4.07, 14.19e-6), (6.91, 10.18e-6), (17.09, 9.11e-6), (21.32, 14.03e-6)]


def test_a_reference_row_is_written_for_every_crossing(tmp_path: Path) -> None:
    out = tmp_path / "20260209_cintron1"
    out.mkdir()
    n = write_estimated_reference(out, _crossings(), vehicle="citroen")

    assert n == 4
    rows = list(csv.DictReader((out / "reference.csv").open(encoding="utf-8")))
    assert len(rows) == 4
    assert {"pass_id", "reference_mass_kg", "t_approx"} <= set(rows[0])


def test_front_and_rear_wheels_get_different_masses(tmp_path: Path) -> None:
    """The bimodal peak amplitude is what identifies the axle, and it is the only thing that does.
    Giving every crossing the same mass would throw away the one distinction the data supports."""
    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, _crossings(), vehicle="citroen")

    masses = sorted(
        {
            float(r["reference_mass_kg"])
            for r in csv.DictReader((out / "reference.csv").open(encoding="utf-8"))
        }
    )
    assert len(masses) == 2
    assert masses[1] / masses[0] == pytest.approx(VEHICLES["citroen"].front_rear_ratio, rel=0.01)


def test_the_fabia_masses_are_the_documented_inference(tmp_path: Path) -> None:
    """The Fabia is the identified vehicle and anchors everything. If this number drifts from
    `docs/sim-to-real.md` and `configs/stations/cintron_platform.yaml`, they disagree silently."""
    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, [(1.0, 11.11e-6)], vehicle="fabia")

    row = next(csv.DictReader((out / "reference.csv").open(encoding="utf-8")))
    assert float(row["reference_mass_kg"]) == pytest.approx(FABIA_FRONT_KG, abs=1.0)


def test_every_row_says_it_is_an_estimate(tmp_path: Path) -> None:
    """A reference file is consumed as ground truth. The word has to travel with the rows, not sit
    in a document beside them."""
    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, _crossings(), vehicle="citroen")

    for row in csv.DictReader((out / "reference.csv").open(encoding="utf-8")):
        assert "ESTIMATED" in row["vehicle_description"]
        assert "not weighed" in row["vehicle_description"].lower()


def test_a_sidecar_records_the_whole_chain(tmp_path: Path) -> None:
    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, _crossings(), vehicle="citroen")

    note = (out / "reference.ESTIMATED.md").read_text(encoding="utf-8")
    assert "operating weight" in note
    assert "not a weighing" in note.lower()
    assert "sim-to-real" in note


def test_it_refuses_to_overwrite_a_reference_file_it_did_not_write(tmp_path: Path) -> None:
    """A measured reference file cannot be regenerated and an estimated one always can, so the
    asymmetry decides: refuse, and make the caller delete it on purpose."""
    out = tmp_path / "run"
    out.mkdir()
    (out / "reference.csv").write_text("pass_id,reference_mass_kg,t_approx\nx,1000,0\n", "utf-8")

    with pytest.raises(FileExistsError, match=r"reference\.csv"):
        write_estimated_reference(out, _crossings(), vehicle="citroen")


def test_it_replaces_a_reference_file_it_did_write(tmp_path: Path) -> None:
    """Regenerating after the inference changes is the point of having a writer at all."""
    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, _crossings(), vehicle="citroen")
    assert write_estimated_reference(out, _crossings()[:2], vehicle="citroen") == 2


def test_an_unknown_vehicle_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "run"
    out.mkdir()
    with pytest.raises(ValueError, match="vehicle"):
        write_estimated_reference(out, _crossings(), vehicle="lada")


def test_the_written_file_satisfies_the_real_data_schema(tmp_path: Path) -> None:
    """It has to be the file the rest of the system already knows how to read."""
    from wimsim.source.real_schema import REQUIRED_REFERENCE_COLUMNS

    out = tmp_path / "run"
    out.mkdir()
    write_estimated_reference(out, _crossings(), vehicle="citroen")
    header = next(csv.reader((out / "reference.csv").open(encoding="utf-8")))
    assert set(REQUIRED_REFERENCE_COLUMNS) <= set(header)
