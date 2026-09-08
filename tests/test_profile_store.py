"""The estimator registry, and the append-only profile store.

Buildspec section 6: "Append-only, versioned. Every profile: ``profile_id``, estimator type,
parameters, activation timestamp, provenance, ``superseded_by``. Historical events must be
recomputable under a different profile."

Append-only is the load-bearing word. A store that rewrote a row to set ``superseded_by`` would be
a store in which the history of a calibration could be edited, which is exactly what provenance
exists to prevent -- so the link is *derived* from the sequence on read and never written. The test
below checks that by reading the file back as text.
"""

from __future__ import annotations

import json

import pytest

from wimsim.calibration import (
    ESTIMATORS,
    CalibrationProfile,
    EstimatorState,
    KalmanCalibration,
    ProfileStore,
    RecursiveLeastSquares,
    StaticAffine,
    build_estimator,
    estimator_from_state,
)

SECOND = 1_000_000


def _profile(profile_id: str, ts_s: int, *, estimator: str = "static_affine", gain: float = 5000.0):
    state = EstimatorState(estimator=estimator, gain=gain, bias=0.0, fitted=True, residual_sd=10.0)
    return CalibrationProfile.from_state(
        state,
        profile_id=profile_id,
        activated_ts_us=SECOND * ts_s,
        reason="test",
        provenance={"config_hash": "a" * 64, "n_reference_observations": 12},
    )


# -- the registry ------------------------------------------------------------------------------


def test_the_registry_holds_every_estimator_the_buildspec_names() -> None:
    """Profiles name their estimator as a string, so this mapping is what makes a stored profile
    reconstructible at all. A profile naming an estimator nothing can build is a mass nobody can
    ever reproduce."""
    assert set(ESTIMATORS) == {"static_affine", "rls", "kalman"}
    assert ESTIMATORS["static_affine"] is StaticAffine
    assert ESTIMATORS["rls"] is RecursiveLeastSquares
    assert ESTIMATORS["kalman"] is KalmanCalibration


def test_every_registered_estimator_reports_the_name_it_is_registered_under() -> None:
    for name, cls in ESTIMATORS.items():
        assert cls.estimator_name == name


def test_an_unknown_estimator_is_refused_with_the_list() -> None:
    with pytest.raises(KeyError, match="static_affine"):
        build_estimator("kalmen")


def test_an_estimator_can_be_rebuilt_from_a_state_it_produced() -> None:
    """The round trip the profile store depends on."""
    for name in ESTIMATORS:
        original = build_estimator(name, coverage_target=0.9)
        state = original.state()
        rebuilt = estimator_from_state(state)
        assert type(rebuilt) is type(original)
        assert rebuilt.state().coverage_target == pytest.approx(0.9)


# -- appending ----------------------------------------------------------------------------------


def test_a_profile_survives_a_round_trip_through_the_file(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 100))

    reopened = ProfileStore(tmp_path / "profiles.jsonl")
    restored = reopened.get("p-1")
    assert restored.profile_id == "p-1"
    assert restored.activated_ts_us == SECOND * 100
    assert restored.state.gain == pytest.approx(5000.0)
    assert restored.provenance["n_reference_observations"] == 12


def test_the_file_is_json_lines_so_it_can_be_read_without_this_code(tmp_path) -> None:
    """A calibration history that can only be read by the program that wrote it is not provenance.
    One JSON object per line means `jq` and a text editor both work."""
    path = tmp_path / "profiles.jsonl"
    store = ProfileStore(path)
    store.append(_profile("p-1", 100))
    store.append(_profile("p-2", 200))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["profile_id"] for line in lines] == ["p-1", "p-2"]


def test_appending_never_rewrites_an_earlier_line(tmp_path) -> None:
    """The property the whole store exists for. If setting `superseded_by` rewrote the previous
    row, a calibration history would be editable -- and an audit trail you can edit is not one."""
    path = tmp_path / "profiles.jsonl"
    store = ProfileStore(path)
    store.append(_profile("p-1", 100))
    first_line = path.read_text(encoding="utf-8").splitlines()[0]

    store.append(_profile("p-2", 200))
    store.append(_profile("p-3", 300))
    assert path.read_text(encoding="utf-8").splitlines()[0] == first_line


def test_superseded_by_is_derived_from_the_sequence_not_stored(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.jsonl")
    for i, ts in enumerate([100, 200, 300], start=1):
        store.append(_profile(f"p-{i}", ts))

    history = store.history()
    assert [p.profile_id for p in history] == ["p-1", "p-2", "p-3"]
    assert [p.superseded_by for p in history] == ["p-2", "p-3", None]

    raw = json.loads((tmp_path / "profiles.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert raw.get("superseded_by") is None, "superseded_by must not be written to the file"


def test_a_duplicate_profile_id_is_refused(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 100))
    with pytest.raises(ValueError, match="p-1"):
        store.append(_profile("p-1", 200))


def test_activation_timestamps_must_not_go_backwards(tmp_path) -> None:
    """A profile activated before the one it replaces makes `active_at` ambiguous, and every
    recompute of that window would depend on the order the file happened to be written in."""
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 200))
    with pytest.raises(ValueError, match="activation"):
        store.append(_profile("p-2", 100))


# -- reading ------------------------------------------------------------------------------------


def test_active_at_returns_the_profile_in_force_at_a_moment(tmp_path) -> None:
    """What a recompute needs: not the latest profile, but the one that was live then."""
    store = ProfileStore(tmp_path / "profiles.jsonl")
    for i, ts in enumerate([100, 200, 300], start=1):
        store.append(_profile(f"p-{i}", ts))

    assert store.active_at(SECOND * 150).profile_id == "p-1"
    assert store.active_at(SECOND * 200).profile_id == "p-2"
    assert store.active_at(SECOND * 250).profile_id == "p-2"
    assert store.active_at(SECOND * 9999).profile_id == "p-3"


def test_before_the_first_activation_there_is_no_profile(tmp_path) -> None:
    """Rather than silently handing back the first one. Events from before any calibration existed
    cannot be recomputed, and pretending otherwise would produce masses from a law that was not in
    force when they were measured."""
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 100))
    assert store.active_at(SECOND * 50) is None


def test_latest_and_len_and_iteration(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.jsonl")
    assert store.latest() is None
    assert len(store) == 0

    for i, ts in enumerate([100, 200], start=1):
        store.append(_profile(f"p-{i}", ts))
    assert store.latest().profile_id == "p-2"
    assert len(store) == 2
    assert [p.profile_id for p in store] == ["p-1", "p-2"]


def test_an_unknown_profile_id_is_refused_rather_than_returning_none(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(_profile("p-1", 100))
    with pytest.raises(KeyError, match="p-9"):
        store.get("p-9")


def test_a_missing_file_is_an_empty_store_not_an_error(tmp_path) -> None:
    """A station's first boot. It has no profiles yet and that is not a fault."""
    store = ProfileStore(tmp_path / "nothing-here.jsonl")
    assert len(store) == 0
    assert store.latest() is None


def test_a_corrupt_line_is_reported_with_its_line_number(tmp_path) -> None:
    """Silently skipping it would mean a station quietly weighing under the wrong calibration."""
    path = tmp_path / "profiles.jsonl"
    store = ProfileStore(path)
    store.append(_profile("p-1", 100))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    with pytest.raises(ValueError, match="line 2"):
        ProfileStore(path).history()


def test_blank_lines_are_tolerated(tmp_path) -> None:
    """A file that was appended to by a shell script, or truncated mid-write and repaired."""
    path = tmp_path / "profiles.jsonl"
    ProfileStore(path).append(_profile("p-1", 100))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
    assert len(ProfileStore(path)) == 1


# -- the profiles the estimators actually produce -------------------------------------------------


@pytest.mark.parametrize("name", sorted(ESTIMATORS))
def test_a_profile_from_every_estimator_round_trips_and_predicts_identically(
    name: str, tmp_path
) -> None:
    """Including the covariance, which RLS and the Kalman filter both carry. A station that
    restarts and comes back with a fresh prior has forgotten how confident it was."""
    import numpy as np

    from wimsim.calibration import ReferenceObservation

    rng = np.random.default_rng(0)
    masses = rng.uniform(1000.0, 40000.0, 60)
    observations = [
        ReferenceObservation(
            ts_us=SECOND * i,
            feature=float(0.05 + 2.0e-4 * m + 1e-5 * rng.standard_normal()),
            temp_c=20.0,
            reference_mass_kg=float(m),
        )
        for i, m in enumerate(masses)
    ]

    estimator = build_estimator(name, coverage_target=0.95)
    estimator.fit(observations)
    original = estimator.predict(0.35, 20.0)

    store = ProfileStore(tmp_path / "profiles.jsonl")
    store.append(
        CalibrationProfile.from_state(
            estimator.state(), profile_id=f"p-{name}", activated_ts_us=SECOND * 100, reason="test"
        )
    )

    restored = estimator_from_state(
        ProfileStore(tmp_path / "profiles.jsonl").get(f"p-{name}").state
    )
    again = restored.predict(0.35, 20.0)
    assert again.mass_kg == pytest.approx(original.mass_kg, rel=1e-9)
    assert again.width == pytest.approx(original.width, rel=1e-9)
