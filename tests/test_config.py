"""Configuration: composition, validation, hashing.

The config layer is load-bearing for principles 3 and 4 -- an artifact is only reproducible if the
thing that produced it can be named exactly. So these tests care as much about *rejecting* bad
config as about accepting good config: a silently ignored typo in a YAML key is a run whose
provenance lies.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from wimsim.core.config import CONFIG_ROOT, RunConfig, load_run_config


def _scenario_names() -> list[str]:
    return sorted(
        p.stem
        for p in CONFIG_ROOT.joinpath("scenarios").glob("*.yaml")
        if not p.stem.startswith("_")
    )


@pytest.mark.parametrize("name", _scenario_names())
def test_every_shipped_scenario_validates(name: str) -> None:
    """A broken scenario must fail here, not four hours into an experiment sweep."""
    cfg = load_run_config(name)
    assert cfg.scenario.name
    assert cfg.scenario.duration_s > 0
    assert len(cfg.config_hash()) == 64


@pytest.mark.parametrize("name", _scenario_names())
def test_every_shipped_scenario_has_a_description(name: str) -> None:
    cfg = load_run_config(name)
    assert cfg.scenario.description.strip(), f"{name} needs a description; it appears in listings"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "configs"
    (root / "stations").mkdir(parents=True)
    (root / "scenarios").mkdir()
    (root / "stations" / "s.yaml").write_text("station_id: X\n", encoding="utf-8")
    (root / "scenarios" / "x.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "x",
                "duration_s": 10.0,
                "station": "s",
                "smaple_rate_hz": 100,  # deliberate typo
                "traffic": {
                    "classes": [
                        {
                            "name": "c",
                            "probability": 1.0,
                            "axle_spacing_m": [],
                            "axle_load_kg": [{"mean_kg": 1000.0}],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="smaple_rate_hz"):
        load_run_config("x", root=root)


def test_extends_composes_and_child_wins() -> None:
    base = load_run_config("_base_traffic") if False else None  # not runnable directly
    cfg = load_run_config("S1_nominal")
    assert cfg.scenario.traffic.classes, "traffic must be inherited from _base_traffic"
    assert cfg.scenario.duration_s == 900.0, "the child's duration must win"
    assert cfg.scenario.traffic.dynamic_load.enabled is False
    assert base is None


def test_station_overrides_apply_without_forking_the_station_file() -> None:
    plain = load_run_config("S3_zero_drift_walk")  # uses endurance as-is
    patched = load_run_config("S2_thermal_cycle")  # same station, alpha ageing
    assert plain.station.station_id == patched.station.station_id
    assert plain.station.sensor.alpha_walk_sigma_per_sqrt_s == 0.0
    assert patched.station.sensor.alpha_walk_sigma_per_sqrt_s > 0.0


def test_dotted_overrides() -> None:
    cfg = load_run_config(
        "S1_nominal",
        overrides=["scenario.duration_s=42.0", "station.sensor.k0=1.0e-4"],
    )
    assert cfg.scenario.duration_s == 42.0
    assert cfg.station.sensor.k0 == 1.0e-4


def test_override_to_a_missing_key_is_an_error() -> None:
    with pytest.raises(KeyError):
        load_run_config("S1_nominal", overrides=["scenario.no_such_key=1"])
    with pytest.raises(ValueError):
        load_run_config("S1_nominal", overrides=["scenario.duration_s"])


def test_seed_override_changes_the_hash() -> None:
    a = load_run_config("S1_nominal", seed=1)
    b = load_run_config("S1_nominal", seed=2)
    assert a.config_hash() != b.config_hash()


def test_hash_is_insensitive_to_key_order_in_yaml(tmp_path: Path) -> None:
    """Canonicalisation must be real, or two identical configs will look different."""
    cfg = load_run_config("S1_nominal")
    reordered = RunConfig.model_validate(
        {
            "scenario": cfg.scenario.model_dump(mode="json"),
            "station": cfg.station.model_dump(mode="json"),
        }
    )
    assert reordered.config_hash() == cfg.config_hash()


def test_start_time_is_fixed_not_now() -> None:
    """A run's timestamps must not depend on when it was executed."""
    a = load_run_config("S1_nominal")
    b = load_run_config("S1_nominal")
    assert a.scenario.start_time == b.scenario.start_time
    assert a.scenario.start_time.tzinfo is not None


def test_grid_ratios_must_be_integral() -> None:
    # 2000 / 60 is not an integer, so a block boundary could not land on a plant-grid point
    with pytest.raises(ValidationError, match="integer multiple"):
        load_run_config("S1_nominal", overrides=["scenario.plant_rate_hz=60.0"])
    with pytest.raises(ValidationError, match="whole number"):
        load_run_config("S1_nominal", overrides=["scenario.block_seconds=0.3"])


def test_plant_rate_must_cover_the_pink_band() -> None:
    with pytest.raises(ValidationError, match="1/f noise"):
        load_run_config(
            "S1_nominal",
            overrides=["scenario.plant_rate_hz=10.0", "scenario.noise.pink_f_max_hz=20.0"],
        )


def test_axle_spacing_must_match_axle_count(tmp_path: Path) -> None:
    from wimsim.core.config import VehicleClass

    with pytest.raises(ValidationError, match="axle_spacing_m"):
        VehicleClass.model_validate(
            {
                "name": "bad",
                "probability": 1.0,
                "axle_spacing_m": [2.0, 3.0],
                "axle_load_kg": [{"mean_kg": 1000.0}, {"mean_kg": 1000.0}],
            }
        )


def test_fault_after_the_end_of_the_run_is_rejected() -> None:
    with pytest.raises(ValidationError, match="after the run ends"):
        load_run_config("S4_step_fault", overrides=["scenario.duration_s=100.0"])


def test_duplicate_fault_labels_are_rejected() -> None:
    cfg = load_run_config("S4_step_fault")
    payload = cfg.scenario.model_dump(mode="json")
    payload["faults"][1]["label"] = payload["faults"][0]["label"]
    with pytest.raises(ValidationError, match="unique"):
        RunConfig.model_validate(
            {"station": cfg.station.model_dump(mode="json"), "scenario": payload}
        )


def test_signal_and_pipeline_faults_are_separated() -> None:
    cfg = load_run_config("S5_outage")
    signal_labels = {f.label for f in cfg.scenario.signal_faults}
    pipeline_labels = {f.label for f in cfg.scenario.pipeline_faults}
    assert signal_labels == {"adc_stuck"}
    assert pipeline_labels == {"link_down", "slow_link"}
    assert not signal_labels & pipeline_labels


def test_missing_scenario_names_the_alternatives() -> None:
    with pytest.raises(FileNotFoundError, match="Available"):
        load_run_config("does_not_exist")
