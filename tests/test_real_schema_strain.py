"""Schema gaps that only real data could reveal.

The schema was fixed before the recordings existed, on purpose. The first recording then showed
three places where it had been fixed *wrong*, all in the same way: it assumed the logger would hand
over ADC counts from a converter whose properties were known.

1. The channel unit is **strain**, not counts and not mV/V. A strain export is a physical quantity
   already, and converting it at import would discard the instrument's own numbers.
2. There is therefore **no ADC metadata at all** -- no bit depth, no input range. Requiring them
   forced a real recording to invent them, which is exactly the kind of fiction a schema is supposed
   to prevent.
3. The export carries **temperature channels alongside strain channels**, so ``channel_map`` needs a
   ``role`` to tell a consumer which is which rather than leaving it to guess from the name.

Fixing the schema rather than mangling the data is the right way round: the recording is the fact.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from wimsim.source.real_schema import validate_run


def _write(
    dir_: Path,
    *,
    run_overrides: dict | None = None,
    drop_keys: tuple[str, ...] = (),
    values: np.ndarray | None = None,
    n: int = 5000,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    ts = 1_770_000_000_000_000 + np.arange(n, dtype=np.int64) * 40  # 25 kHz
    raw = (
        110e-6 + 1.4e-6 * np.random.default_rng(0).standard_normal(n) if values is None else values
    )
    pq.write_table(
        pa.table(
            {
                "ts": ts,
                "channel_id": pa.array(["Tenzo1"] * n, pa.string()),
                "raw_value": raw,
                "temperature_c": np.full(n, 22.9),
            }
        ),
        dir_ / "samples.parquet",
    )
    run = {
        "station_id": "ST-CINTRON-1",
        "sample_rate_hz": 25000.0,
        "raw_value_kind": "strain",
        "gauge_factor": 2.0,
        "channel_map": {"Tenzo1": {"sensor_id": "S1", "lane": 1, "role": "strain"}},
    }
    run.update(run_overrides or {})
    for key in drop_keys:
        run.pop(key, None)
    (dir_ / "run.yaml").write_text(yaml.safe_dump(run, allow_unicode=True), encoding="utf-8")
    return dir_


def test_a_strain_export_validates_without_any_adc_metadata(tmp_path: Path) -> None:
    """The gap the real recording found: it has no converter to describe."""
    report = validate_run(_write(tmp_path / "strain"))
    assert report.ok, report.errors
    assert report.stats["raw_value_kind"] == "strain"


def test_counts_still_require_the_adc_description(tmp_path: Path) -> None:
    """Counts are meaningless without a bit depth and a range, so those stay mandatory there."""
    run = _write(
        tmp_path / "counts",
        run_overrides={"raw_value_kind": "counts"},
    )
    report = validate_run(run)
    assert not report.ok
    assert any("adc_bits" in e for e in report.errors)
    assert any("adc_range" in e for e in report.errors)


def test_strain_requires_a_gauge_factor_to_be_interpretable(tmp_path: Path) -> None:
    """Strain alone cannot be turned into a bridge output without knowing the gauge factor.

    A warning rather than an error: the run can still be replayed and characterised, it just cannot
    be expressed in the simulator's units.
    """
    report = validate_run(_write(tmp_path / "nogf", drop_keys=("gauge_factor",)))
    assert report.ok
    assert any("gauge_factor" in w for w in report.warnings)


def test_an_unknown_raw_value_kind_is_rejected(tmp_path: Path) -> None:
    report = validate_run(_write(tmp_path / "bad", run_overrides={"raw_value_kind": "newtons"}))
    assert not report.ok
    assert any("raw_value_kind" in e for e in report.errors)


def test_channel_roles_are_reported_and_validated(tmp_path: Path) -> None:
    run = _write(
        tmp_path / "roles",
        run_overrides={
            "channel_map": {
                "Tenzo1": {"sensor_id": "S1", "lane": 1, "role": "strain"},
                "Temp1": {"sensor_id": "T1", "role": "temperature"},
            }
        },
    )
    report = validate_run(run)
    assert report.ok, report.errors
    assert report.stats["roles"] == {"Tenzo1": "strain", "Temp1": "temperature"}


def test_an_unknown_channel_role_is_rejected(tmp_path: Path) -> None:
    run = _write(
        tmp_path / "badrole",
        run_overrides={"channel_map": {"Tenzo1": {"sensor_id": "S1", "role": "vibration"}}},
    )
    report = validate_run(run)
    assert not report.ok
    assert any("role" in e for e in report.errors)


def test_saturation_is_skipped_and_said_to_be_skipped_when_no_range_is_declared(
    tmp_path: Path,
) -> None:
    """Silently not checking is worse than not checking."""
    report = validate_run(_write(tmp_path / "norange"))
    assert report.ok
    assert any("saturation" in w.lower() for w in report.warnings)


def test_a_quiet_recording_with_no_passes_is_flagged_as_such(tmp_path: Path) -> None:
    """The first real recording had no vehicles in it at all.

    That is a perfectly good noise-characterisation run and a useless calibration run, and the
    difference is worth stating at the door rather than discovering after fitting a gain to nothing.
    """
    n = 25_000
    quiet = 110e-6 + 1.4e-6 * np.random.default_rng(1).standard_normal(n)
    report = validate_run(_write(tmp_path / "quiet", values=quiet, n=n))
    assert report.ok
    assert any("no excursion" in w.lower() for w in report.warnings)
    assert report.stats["max_excursion_sigma"] < 10.0


def test_a_recording_with_passes_is_not_flagged(tmp_path: Path) -> None:
    n = 25_000
    values = 110e-6 + 1.4e-6 * np.random.default_rng(2).standard_normal(n)
    t = np.arange(n)
    values += 60e-6 * np.exp(-0.5 * ((t - 12000) / 60.0) ** 2)  # a vehicle
    report = validate_run(_write(tmp_path / "loud", values=values, n=n))
    assert report.ok
    assert not any("no excursion" in w.lower() for w in report.warnings)
    assert report.stats["max_excursion_sigma"] > 10.0


def test_a_negative_going_excursion_is_found(tmp_path: Path) -> None:
    """Regression: the real sensor deflects DOWNWARD under load.

    The first scale estimator read the low quantiles, which is exactly where a compressive
    excursion lives -- so the excursion inflated the very scale it was being measured against and
    came out looking like noise. It reported "no vehicle passes" on seven of eight recordings that
    each contain several.
    """
    n = 25_000
    values = 110e-6 + 1.4e-6 * np.random.default_rng(3).standard_normal(n)
    t = np.arange(n)
    values -= 14e-6 * np.exp(-0.5 * ((t - 12000) / 2000.0) ** 2)  # a vehicle, downward
    report = validate_run(_write(tmp_path / "down", values=values, n=n))
    assert report.ok
    assert not any("no excursion" in w.lower() for w in report.warnings)
    assert report.stats["max_excursion_sigma"] > 10.0


def test_excursions_are_found_when_the_sensor_is_loaded_much_of_the_time(tmp_path: Path) -> None:
    """A vehicle parked on the sensor makes a third of the record 'loaded'.

    Any scale or baseline estimated from the record as a whole is then contaminated by the very
    thing it is meant to measure. One of the eight recordings starts with the car already in place.
    """
    n = 60_000
    rng = np.random.default_rng(4)
    values = 110e-6 + 1.4e-6 * rng.standard_normal(n)
    values[:20_000] -= 13e-6  # the car is already there when recording starts
    report = validate_run(_write(tmp_path / "occupied", values=values, n=n))
    assert report.ok
    assert not any("no excursion" in w.lower() for w in report.warnings)
    assert report.stats["max_excursion_sigma"] > 10.0


def test_slow_drift_alone_is_not_mistaken_for_a_pass(tmp_path: Path) -> None:
    """The complement: a baseline that wanders over a minute is drift, not a vehicle."""
    n = 60_000
    rng = np.random.default_rng(5)
    values = 110e-6 + 1.4e-6 * rng.standard_normal(n) + np.linspace(0, 8e-6, n)
    report = validate_run(_write(tmp_path / "drifty", values=values, n=n))
    assert report.ok
    assert any("no excursion" in w.lower() for w in report.warnings)
