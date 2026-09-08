"""``recompute --from <ts> --profile <id>``: re-deriving stored history under a different profile.

Buildspec section 6: "Historical events must be recomputable under a different profile -- implement
``recompute --from <ts> --profile <id>`` and prove it in a test."

This is the payoff for three earlier decisions, and it is worth naming them because none of them
looked like they were for this:

* ``event_id`` is a UUIDv5 of station, sensor and ``ts_start`` and of *nothing else* -- not the
  mass, not the profile. So a recomputed event has the same id and the phase-3 upsert updates it in
  place rather than inserting a second opinion.
* ``raw_peak`` is stored *before* thermal compensation. So a recompute can redo the compensation
  under the new profile's coefficient, rather than being stuck with the old profile's.
* ``temperature_c`` is stored per event -- which it was not until phase 4 noticed the column was
  always null. Without it the compensation could not be redone at all, and recompute would silently
  be exact only for profiles that share a temperature coefficient.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    CalibrationProfile,
    EstimatorState,
    ProfileStore,
    ReferenceObservation,
    StaticAffine,
)
from wimsim.experiments.recompute import RecomputeResult, recompute_rows

SECOND = 1_000_000


def _state(gain: float = 5000.0, bias: float = 0.0, temp_coeff: float = 0.0) -> EstimatorState:
    return EstimatorState(
        estimator="static_affine",
        gain=gain,
        bias=bias,
        temp_coeff=temp_coeff,
        t_ref_c=20.0,
        residual_sd=12.0,
        fitted=True,
    )


def _profile(profile_id: str, ts_s: int, **kwargs) -> CalibrationProfile:
    return CalibrationProfile.from_state(
        _state(**kwargs), profile_id=profile_id, activated_ts_us=SECOND * ts_s, reason="test"
    )


def _row(ts_s: int, *, raw_peak: float = 0.30, temp: float = 20.0, mass: float = 1500.0) -> dict:
    """A stored ``wim.measurement_event`` row, as the writer would hand it back."""
    return {
        "event_id": f"e-{ts_s}",
        "station_id": "ST-1",
        "sensor_id": "S1",
        "ts_start": SECOND * ts_s,
        "ts_peak": SECOND * ts_s + 5000,
        "raw_peak": raw_peak,
        "compensated_peak": raw_peak,
        "temperature_c": temp,
        "mass_kg": mass,
        "mass_ci_low": mass - 20.0,
        "mass_ci_high": mass + 20.0,
        "profile_id": "p-old",
        "axle_count": 2,
    }


# -- the core claim ------------------------------------------------------------------------------


def test_the_mass_is_re_derived_under_the_named_profile() -> None:
    rows = [_row(ts_s) for ts_s in (100, 200, 300)]
    result = recompute_rows(rows, _profile("p-new", 0, gain=6000.0))

    assert isinstance(result, RecomputeResult)
    assert [r["mass_kg"] for r in result.rows] == pytest.approx([1800.0, 1800.0, 1800.0])
    assert all(r["profile_id"] == "p-new" for r in result.rows)
    assert result.n_recomputed == 3


def test_the_event_id_is_unchanged_so_the_upsert_updates_in_place() -> None:
    """The whole reason ``event_id`` was derived from the crossing's identity and nothing else. A
    recompute that changed the id would insert a second opinion about the same vehicle."""
    rows = [_row(100)]
    result = recompute_rows(rows, _profile("p-new", 0, gain=6000.0))
    assert result.rows[0]["event_id"] == rows[0]["event_id"]
    assert result.rows[0]["ts_start"] == rows[0]["ts_start"]


def test_the_interval_is_re_derived_too_not_carried_over() -> None:
    """An interval from the old profile attached to a mass from the new one would be a confidence
    statement about a number that was never computed."""
    rows = [_row(100)]
    old = rows[0]["mass_ci_high"] - rows[0]["mass_ci_low"]
    result = recompute_rows(rows, _profile("p-new", 0, gain=6000.0))
    new_row = result.rows[0]
    assert new_row["mass_ci_low"] <= new_row["mass_kg"] <= new_row["mass_ci_high"]
    assert new_row["mass_ci_high"] - new_row["mass_ci_low"] != pytest.approx(old)


def test_recomputing_under_the_same_profile_reproduces_the_stored_mass() -> None:
    """The identity check, and the strongest evidence that recompute is a re-derivation rather than
    a different calculation that happens to look similar. Same profile in, same kilograms out."""
    estimator = StaticAffine()
    rng = np.random.default_rng(0)
    masses = rng.uniform(1000.0, 40000.0, 40)
    estimator.fit(
        [
            ReferenceObservation(
                ts_us=SECOND * i, feature=float(2.0e-4 * m), temp_c=20.0, reference_mass_kg=float(m)
            )
            for i, m in enumerate(masses)
        ]
    )
    profile = CalibrationProfile.from_state(
        estimator.state(), profile_id="p-same", activated_ts_us=0, reason="test"
    )

    rows = []
    for i, feature in enumerate((0.20, 0.35, 0.80, 4.0)):
        estimate = estimator.predict(feature, 20.0)
        rows.append(
            _row(100 + i, raw_peak=feature, mass=estimate.mass_kg)
            | {
                "mass_ci_low": estimate.mass_ci_low,
                "mass_ci_high": estimate.mass_ci_high,
                "profile_id": "p-same",
            }
        )

    result = recompute_rows(rows, profile)
    for original, again in zip(rows, result.rows, strict=True):
        assert again["mass_kg"] == pytest.approx(original["mass_kg"], rel=1e-12)
        assert again["mass_ci_low"] == pytest.approx(original["mass_ci_low"], rel=1e-12)


# -- thermal compensation, which is the part that could quietly be wrong ----------------------------


def test_the_thermal_compensation_is_redone_from_the_raw_peak() -> None:
    """The subtle one. ``compensated_peak`` was divided by ``1 + alpha*(T - T_ref)`` using the
    *old* profile's coefficient, so recomputing from it would apply the old correction and then the
    new estimator on top. Starting from ``raw_peak`` and redoing the division is exact.
    """
    row = _row(100, raw_peak=0.30, temp=40.0)
    # The old profile compensated at alpha = 0, so compensated_peak == raw_peak.
    result = recompute_rows([row], _profile("p-new", 0, gain=5000.0, temp_coeff=1.0e-3))

    factor = 1.0 + 1.0e-3 * (40.0 - 20.0)
    assert result.rows[0]["compensated_peak"] == pytest.approx(0.30 / factor)
    assert result.rows[0]["mass_kg"] == pytest.approx(5000.0 * 0.30 / factor)


def test_a_row_with_no_temperature_is_compensated_at_the_reference() -> None:
    """Events emitted before phase 4 populated the column. Compensating at the reference is a
    no-op, which is the only defensible assumption -- and it is recorded rather than hidden."""
    row = _row(100) | {"temperature_c": None}
    result = recompute_rows([row], _profile("p-new", 0, gain=5000.0, temp_coeff=1.0e-3))
    assert result.rows[0]["mass_kg"] == pytest.approx(1500.0)
    assert result.n_without_temperature == 1


def test_a_row_with_no_raw_peak_is_skipped_rather_than_guessed() -> None:
    """Without it the compensation cannot be redone, so the recompute would silently be exact only
    for profiles sharing a coefficient. Better to leave the event alone and say how many."""
    rows = [_row(100), _row(200) | {"raw_peak": None}]
    result = recompute_rows(rows, _profile("p-new", 0, gain=6000.0))
    assert result.n_recomputed == 1
    assert result.n_skipped == 1
    assert [r["event_id"] for r in result.rows] == ["e-100"]


# -- the window ------------------------------------------------------------------------------------


def test_only_rows_at_or_after_the_cutoff_are_recomputed() -> None:
    rows = [_row(ts_s) for ts_s in (100, 200, 300, 400)]
    result = recompute_rows(rows, _profile("p-new", 0, gain=6000.0), from_ts_us=SECOND * 250)
    assert [r["event_id"] for r in result.rows] == ["e-300", "e-400"]
    assert result.n_recomputed == 2


def test_an_empty_window_is_reported_rather_than_treated_as_success() -> None:
    """`recompute --from` with a timestamp past the end of the data is a typo far more often than
    it is a request, and silently reporting "0 events updated, done" hides it."""
    rows = [_row(100)]
    result = recompute_rows(rows, _profile("p-new", 0), from_ts_us=SECOND * 9999)
    assert result.n_recomputed == 0
    assert result.rows == []


# -- provenance -------------------------------------------------------------------------------------


def test_the_recomputed_row_names_the_profile_and_the_state_that_produced_it() -> None:
    """A mass whose provenance still points at the profile it *used* to be computed under is worse
    than no provenance: it is provenance that is confidently wrong."""
    result = recompute_rows([_row(100)], _profile("p-new", 0, gain=6000.0))
    row = result.rows[0]
    assert row["profile_id"] == "p-new"
    assert row["estimator"] == "static_affine"
    assert row["cal_gain"] == pytest.approx(1.0 / 6000.0)
    assert row["cal_state_hash"]


def test_an_estimator_this_build_cannot_construct_is_refused_loudly() -> None:
    state = EstimatorState(estimator="residual_learner", gain=1.0, bias=0.0, fitted=True)
    profile = CalibrationProfile.from_state(
        state, profile_id="p-future", activated_ts_us=0, reason="test"
    )
    with pytest.raises(KeyError, match="residual_learner"):
        recompute_rows([_row(100)], profile)


def test_an_unfitted_profile_is_refused_before_any_row_is_touched() -> None:
    """Half a recompute is worse than none: the window would then hold masses from two different
    laws with no way to tell which is which."""
    state = EstimatorState(estimator="static_affine", gain=0.0, bias=0.0, fitted=False)
    profile = CalibrationProfile.from_state(
        state, profile_id="p-unfitted", activated_ts_us=0, reason="test"
    )
    with pytest.raises(ValueError, match="fitted"):
        recompute_rows([_row(100)], profile)


# -- through the store ------------------------------------------------------------------------------


def test_a_profile_can_be_taken_straight_from_the_store(tmp_path) -> None:
    """The command's actual shape: ``--profile <id>`` is looked up, not constructed."""
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 100, gain=5000.0))
    store.append(_profile("p-2", 200, gain=6000.0))

    result = recompute_rows([_row(300)], store.get("p-2"))
    assert result.rows[0]["mass_kg"] == pytest.approx(1800.0)
    assert result.rows[0]["profile_id"] == "p-2"
