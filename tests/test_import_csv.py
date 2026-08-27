"""Importing a logger CSV export.

The tests that matter here are the ones that check **which column ended up where**. Everything else
about an import is recoverable; a transposed channel is not, because the result is a plausible file
full of the wrong numbers.

That is not hypothetical. The first implementation passed an unsorted ``usecols`` to pandas with a
matching-order ``names`` list, and pandas applies names in ascending *file* order -- so Tenzo1 was
written carrying Temp2's readings and Tenzo2 was written carrying the relative-time column. Nothing
raised. It surfaced only as a negative duration in the summary.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml

from wimsim.source.import_csv import import_csv, parse_header
from wimsim.source.real_schema import validate_run

FS = 25000.0
INTERVAL = 1.0 / FS


def _write_export(
    path: Path,
    *,
    n: int = 500,
    channels: tuple[tuple[str, str], ...] = (
        ("Temp1", "°C"),
        ("Temp2", "°C"),
        ("Tenzo1", "ε"),
        ("Tenzo2", "ε"),
    ),
    timestamp: str = "9. 2. 2026 9:38:25",
    values: dict[str, np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Write a file in the logger's layout, with a distinct signature per channel."""
    t = np.arange(n) * INTERVAL
    data = values or {
        name: np.full(n, 100.0 + 10.0 * i) + np.arange(n) * (i + 1) * 1e-3
        for i, (name, _unit) in enumerate(channels)
    }

    lines = [
        ";".join(f"Timestamp;{timestamp}" for _ in channels),
        ";".join(f"Interval;{INTERVAL:g}" for _ in channels),
        ";".join(f'Channel name;"{name}"' for name, _ in channels),
        ";".join(f'Unit;"{unit}"' for _, unit in channels),
    ]
    for i in range(n):
        cells = []
        for name, _unit in channels:
            cells.append(f"{t[i]:.10g}".replace(".", ","))
            cells.append(f"{data[name][i]:.12g}".replace(".", ","))
        lines.append(";".join(cells))
    path.write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")
    return data


# -- header ------------------------------------------------------------------------------------


def test_header_is_parsed_including_roles_from_units(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src)
    header = parse_header(src)
    assert header.start_time_local == datetime(2026, 2, 9, 9, 38, 25)
    assert header.interval_s == pytest.approx(INTERVAL)
    assert header.sample_rate_hz == 25000.0, "must be exactly 25000, not 24999.999999999996"
    assert [(c.name, c.role) for c in header.channels] == [
        ("Temp1", "temperature"),
        ("Temp2", "temperature"),
        ("Tenzo1", "strain"),
        ("Tenzo2", "strain"),
    ]
    assert [c.value_column for c in header.channels] == [1, 3, 5, 7]


def test_units_are_matched_exactly_so_counts_is_not_a_temperature(tmp_path: Path) -> None:
    """Substring matching would classify anything containing 'c' as a temperature channel."""
    src = tmp_path / "export.csv"
    _write_export(src, channels=(("Raw", "counts"), ("Tenzo1", "ε")))
    roles = {c.name: c.role for c in parse_header(src).channels}
    assert roles == {"Raw": "auxiliary", "Tenzo1": "strain"}


def test_a_file_that_is_not_this_layout_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "other.csv"
    src.write_text("time,value\n0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Timestamp"):
        parse_header(src)


def test_an_unparseable_timestamp_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, timestamp="last Tuesday")
    with pytest.raises(ValueError, match="cannot parse"):
        parse_header(src)


# -- column mapping ----------------------------------------------------------------------------


def test_every_channel_lands_on_its_own_values(tmp_path: Path) -> None:
    """Regression for the transposed-column bug. This is the test the importer exists to pass."""
    src = tmp_path / "export.csv"
    data = _write_export(src, n=400)
    result = import_csv(src, tmp_path / "run", station_id="ST-1", gauge_factor=2.0)

    table = pq.read_table(result.run_dir / "samples.parquet").to_pandas()
    assert set(table.channel_id.unique()) == {"Tenzo1", "Tenzo2"}

    for strain_name, temp_name in (("Tenzo1", "Temp1"), ("Tenzo2", "Temp2")):
        rows = table[table.channel_id == strain_name].sort_values("ts")
        np.testing.assert_allclose(rows.raw_value.to_numpy(), data[strain_name], rtol=0, atol=1e-9)
        np.testing.assert_allclose(
            rows.temperature_c.to_numpy(), data[temp_name], rtol=0, atol=1e-9
        )


def test_a_time_column_that_is_not_a_time_column_is_refused(tmp_path: Path) -> None:
    """Belt and braces on the same bug: if the mapping is wrong, the 'time' axis will not step by
    the declared interval, and refusing beats writing a scrambled file."""
    src = tmp_path / "export.csv"
    _write_export(src, n=200)
    time_column = parse_header(src).by_role("strain")[0].time_column

    text = src.read_text(encoding="utf-8").splitlines()
    body = []
    for line in text[4:]:
        cells = line.split(";")
        cells[time_column] = "0"  # flatten the axis the importer will read as time
        body.append(";".join(cells))
    src.write_text("\n".join(text[:4] + body) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not look like a time axis"):
        import_csv(src, tmp_path / "run", station_id="ST-1")


def test_duration_and_row_count_are_sane(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, n=1000)
    result = import_csv(src, tmp_path / "run", station_id="ST-1")
    assert result.duration_s == pytest.approx(999 * INTERVAL)
    assert result.sample_rows == 2000  # two strain channels
    assert result.pairing == {"Tenzo1": "Temp1", "Tenzo2": "Temp2"}


# -- timestamps ---------------------------------------------------------------------------------


def test_the_naive_timestamp_is_interpreted_in_the_named_zone_and_recorded(tmp_path: Path) -> None:
    """A wrong guess here shifts the whole recording by the offset and nothing downstream notices,
    so the assumption is a parameter and it is written into run.yaml."""
    src = tmp_path / "export.csv"
    _write_export(src, n=200)
    result = import_csv(src, tmp_path / "run", station_id="ST-1", timezone="Europe/Bratislava")
    expected = datetime(2026, 2, 9, 9, 38, 25, tzinfo=ZoneInfo("Europe/Bratislava"))
    assert result.start_time_utc == expected

    run = yaml.safe_load((result.run_dir / "run.yaml").read_text(encoding="utf-8"))
    assert run["timezone_assumed"] == "Europe/Bratislava"
    assert "naive local time" in run["notes"]


def test_a_different_zone_moves_every_timestamp(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, n=200)
    a = import_csv(src, tmp_path / "a", station_id="ST-1", timezone="Europe/Bratislava")
    b = import_csv(src, tmp_path / "b", station_id="ST-1", timezone="UTC")
    ta = pq.read_table(a.run_dir / "samples.parquet").column("ts").to_numpy()
    tb = pq.read_table(b.run_dir / "samples.parquet").column("ts").to_numpy()
    assert int(tb[0]) - int(ta[0]) == 3600 * 1_000_000  # CET is UTC+1 in February


def test_timestamps_are_built_from_the_index_not_the_float_time_column(tmp_path: Path) -> None:
    """The file's own time column is a float in seconds and loses microsecond exactness; the sample
    index cannot."""
    src = tmp_path / "export.csv"
    _write_export(src, n=1000)
    result = import_csv(src, tmp_path / "run", station_id="ST-1")
    ts = pq.read_table(result.run_dir / "samples.parquet").to_pandas()
    first = ts[ts.channel_id == "Tenzo1"].sort_values("ts").ts.to_numpy()
    assert np.all(np.diff(first) == 40)  # exactly 40 us, no jitter


# -- the resulting run directory -------------------------------------------------------------------


def test_the_imported_run_satisfies_the_schema(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, n=2000)
    result = import_csv(src, tmp_path / "run", station_id="ST-1", gauge_factor=2.0)
    report = validate_run(result.run_dir)
    assert report.ok, report.errors


def test_run_yaml_documents_the_channels_that_are_not_rows(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, n=200)
    result = import_csv(src, tmp_path / "run", station_id="ST-1")
    run = yaml.safe_load((result.run_dir / "run.yaml").read_text(encoding="utf-8"))
    assert run["channel_map"]["Temp1"]["in_samples"] is False
    assert run["channel_map"]["Tenzo1"]["in_samples"] is True
    assert run["channel_map"]["Tenzo1"]["paired_temperature"] == "Temp1"
    assert run["raw_value_kind"] == "strain"
    assert "adc_range" not in run, "a physical-quantity export has no converter to describe"


def test_an_export_with_no_strain_channels_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "export.csv"
    _write_export(src, channels=(("Temp1", "°C"), ("Temp2", "°C")))
    with pytest.raises(ValueError, match="no strain channels"):
        import_csv(src, tmp_path / "run", station_id="ST-1")
