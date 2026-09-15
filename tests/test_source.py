"""Principle 2: one interface for synthetic and real data.

The claim is that everything downstream of ``SourceAdapter`` is identical for both. A claim like
that is only worth anything if something checks it, so :func:`test_a_consumer_cannot_tell_them_apart`
runs the *same* consumer function over a synthetic stream and over a replayed one and requires it to
work unchanged.

The replay fixture writes a synthetic run out in the real-data format and reads it back. That is
deliberate: it exercises the whole real-data path -- schema, validator, unit conversion, block
framing -- before any real recording exists, so when the drives arrive the only new variable is the
data itself.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from wimsim.core.config import RunConfig
from wimsim.core.types import Sample, SampleBlock
from wimsim.source import ReplaySource, SerialSource, SourceAdapter, SyntheticSource
from wimsim.source.real_schema import validate_run


def _fake_real_run(dir_: Path, cfg: RunConfig, *, rows: int = 20_000, corrupt: str = "") -> Path:
    """Write a synthetic stream in the real-data format, optionally with a planted defect."""
    from wimsim.signal.generator import SignalGenerator

    gen = SignalGenerator(cfg)
    ts, counts, temp = [], [], []
    for block in gen.blocks():
        s = block.samples
        ts.append(s.ts_us)
        counts.append(s.raw_counts)
        temp.append(s.temperature_c)
        if sum(a.size for a in ts) >= rows:
            break
    ts_a = np.concatenate(ts)[:rows]
    counts_a = np.concatenate(counts)[:rows]
    temp_a = np.concatenate(temp)[:rows]

    if corrupt == "clock_backwards":
        ts_a[rows // 2] = ts_a[rows // 2] - 5_000_000
    elif corrupt == "gap":
        ts_a[rows // 2 :] += 1_000_000

    dir_.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "ts": ts_a,
                "channel_id": pa.array([cfg.station.sensor_id] * rows, pa.string()),
                "raw_value": counts_a,
                "temperature_c": temp_a,
            }
        ),
        dir_ / "samples.parquet",
    )
    (dir_ / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "station_id": cfg.station.station_id,
                "sample_rate_hz": cfg.station.sample_rate_hz,
                "raw_value_kind": "counts",
                "adc_bits": cfg.station.adc.bits,
                "adc_range": [cfg.station.adc.range_min, cfg.station.adc.range_max],
                "channel_map": {
                    cfg.station.sensor_id: {"sensor_id": cfg.station.sensor_id, "lane": 1}
                },
                "excitation_v": 5.0,
                "gauge_factor": 2.05,
                "notes": "synthetic stream written in the real-data format, for testing the path",
            }
        ),
        encoding="utf-8",
    )
    with (dir_ / "reference.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pass_id", "reference_mass_kg", "t_approx", "vehicle_description"])
        for p in gen.passes[:3]:
            w.writerow(
                [p.pass_id, f"{p.true_mass_kg:.0f}", int(p.t_entry_s * 1e6), p.vehicle_class]
            )
    return dir_


# -- protocol conformance ------------------------------------------------------------------


def test_synthetic_source_satisfies_the_protocol(short_cfg: RunConfig) -> None:
    src = SyntheticSource(short_cfg)
    assert isinstance(src, SourceAdapter)
    md = src.metadata
    assert md.mode == "synthetic"
    assert md.sample_rate_hz == short_cfg.station.sample_rate_hz
    assert md.channels == (short_cfg.station.sensor_id,)


def test_metadata_reveals_nothing_about_truth(short_cfg: RunConfig) -> None:
    """A downstream stage must not be able to learn the answer from its own source metadata."""
    md = SyntheticSource(short_cfg).metadata
    blob = repr(md).lower()
    for forbidden in ("true_mass", "k_true", "q_true", "truth", "peak_load"):
        assert forbidden not in blob, f"metadata leaks {forbidden!r}"


def test_stream_and_stream_blocks_agree(short_cfg: RunConfig) -> None:
    """``stream()`` is defined in terms of ``stream_blocks()``; they must not diverge."""
    blocks = SyntheticSource(short_cfg)
    flat = SyntheticSource(short_cfg)

    from_blocks = np.concatenate([b.raw_counts for b in blocks.stream_blocks()])
    from_samples = np.fromiter((s.raw_counts for s in flat.stream()), dtype=np.int64)
    np.testing.assert_array_equal(from_blocks, from_samples)


def test_iterating_a_block_yields_samples(short_cfg: RunConfig) -> None:
    block = next(iter(SyntheticSource(short_cfg).stream_blocks()))
    assert isinstance(block, SampleBlock)
    first = next(iter(block))
    assert isinstance(first, Sample)
    assert first.ts_us == int(block.ts_us[0])
    assert first.channel_id == short_cfg.station.sensor_id


def test_serial_source_has_the_interface_but_not_the_implementation() -> None:
    src = SerialSource("COM3", station_id="ST", sensor_id="S1")
    assert isinstance(src, SourceAdapter)
    assert src.metadata.mode == "serial"
    with pytest.raises(NotImplementedError, match="hardware-in-the-loop"):
        next(iter(src.stream_blocks()))


# -- the real-data path --------------------------------------------------------------------


def test_written_fake_run_satisfies_the_schema(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "drive_00", short_cfg)
    report = validate_run(run)
    assert report.ok, report.errors
    assert report.stats["rows"] == 20_000
    assert report.stats["channels"] == [short_cfg.station.sensor_id]


def test_validator_rejects_a_backwards_clock(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "bad_clock", short_cfg, corrupt="clock_backwards")
    report = validate_run(run)
    assert not report.ok
    assert any("not strictly increasing" in e for e in report.errors)


def test_validator_warns_about_a_gap(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "gappy", short_cfg, corrupt="gap")
    report = validate_run(run)
    assert report.ok, "a gap is a warning, not a rejection -- real recordings have gaps"
    assert any("timestamp gaps" in w for w in report.warnings)


def test_validator_reports_missing_files(tmp_path: Path) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    report = validate_run(empty)
    assert not report.ok
    assert any("run.yaml" in e for e in report.errors)
    assert any("samples.parquet" in e for e in report.errors)


def test_validator_requires_declared_channels(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "unmapped", short_cfg)
    doc = yaml.safe_load((run / "run.yaml").read_text(encoding="utf-8"))
    doc["channel_map"] = {"SOMETHING_ELSE": {"sensor_id": "x"}}
    (run / "run.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    report = validate_run(run)
    assert any("channel_map" in e for e in report.errors)


def test_saturation_is_judged_in_the_domain_raw_value_actually_uses(
    tmp_path: Path, short_cfg: RunConfig
) -> None:
    """Counts must be compared against the count rails, not against a mV/V range.

    Getting this wrong flags an entire recording as 100 % saturated -- exactly the class of unit
    error ``raw_value_kind`` exists to prevent.
    """
    run = _fake_real_run(tmp_path / "counts", short_cfg)
    clean = validate_run(run)
    assert not any("ADC rail" in w for w in clean.warnings), clean.warnings

    table = pq.read_table(run / "samples.parquet").to_pydict()
    raw = np.asarray(table["raw_value"])
    raw[:500] = (1 << short_cfg.station.adc.bits) - 1
    pq.write_table(
        pa.table(
            {
                "ts": table["ts"],
                "channel_id": pa.array(table["channel_id"], pa.string()),
                "raw_value": raw,
                "temperature_c": table["temperature_c"],
            }
        ),
        run / "samples.parquet",
    )
    pinned = validate_run(run)
    assert any("ADC rail" in w for w in pinned.warnings)
    assert pinned.stats[f"saturated[{short_cfg.station.sensor_id}]"] == 500


def test_example_real_run_ships_and_validates(repo_root: Path) -> None:
    """data/real/EXAMPLE makes the schema concrete before any drive arrives."""
    example = repo_root / "data" / "real" / "EXAMPLE"
    if not example.is_dir():
        pytest.skip("data/real/EXAMPLE not present in this checkout")
    report = validate_run(example)
    assert report.ok, report.errors
    run = yaml.safe_load((example / "run.yaml").read_text(encoding="utf-8"))
    assert "SYNTHETIC" in run["notes"], "the example must not be mistakable for a real recording"


def test_replay_reproduces_the_values_it_was_given(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "drive_01", short_cfg)
    stored = pq.read_table(run / "samples.parquet")
    src = ReplaySource(run, block_seconds=1.0)

    counts = np.concatenate([b.raw_counts for b in src.stream_blocks()])
    np.testing.assert_array_equal(counts, stored.column("raw_value").to_numpy())
    assert src.metadata.mode == "replay"
    assert src.metadata.station_id == short_cfg.station.station_id
    # counts -> sensor units must use the recording's own ADC declaration
    assert src._value[0] == pytest.approx(
        short_cfg.station.adc.range_min + counts[0] * short_cfg.station.adc.lsb
    )


def test_replay_refuses_a_run_that_fails_the_schema(tmp_path: Path, short_cfg: RunConfig) -> None:
    run = _fake_real_run(tmp_path / "bad", short_cfg, corrupt="clock_backwards")
    with pytest.raises(ValueError, match="real-data schema"):
        ReplaySource(run)
    ReplaySource(run, strict=False)  # explicitly opting in is allowed


def test_a_consumer_cannot_tell_them_apart(tmp_path: Path, short_cfg: RunConfig) -> None:
    """The same consumer, unchanged, over both sources. This *is* principle 2."""

    def consume(source: SourceAdapter) -> dict[str, float]:
        """A stand-in for the phase-2 edge pipeline: touches only the public interface."""
        md = source.metadata
        n = 0
        peak = -np.inf
        for block in source.stream_blocks():
            n += block.n
            peak = max(peak, float(np.nanmax(block.raw_value)))
        return {"n": n, "peak": peak, "fs": md.sample_rate_hz, "channels": len(md.channels)}

    run = _fake_real_run(tmp_path / "drive_02", short_cfg, rows=20_000)
    synth = consume(SyntheticSource(short_cfg))
    replay = consume(ReplaySource(run, block_seconds=1.0))

    assert synth["fs"] == replay["fs"]
    assert synth["channels"] == replay["channels"] == 1
    assert replay["n"] == 20_000
    assert synth["n"] == short_cfg.sample_count
    # the replay covers the first 10 s of the same signal, so its peak cannot exceed the whole run's
    assert replay["peak"] <= synth["peak"] + 1e-12


def test_replay_opens_a_recording_that_declares_no_adc_range(
    tmp_path: Path, short_cfg: RunConfig
) -> None:
    """Regression: `ReplaySource` read `adc_range` and `adc_bits` unconditionally and died with a
    `KeyError` on every recording the project actually has.

    `real_schema` makes both optional unless `raw_value_kind: counts` -- a strain or mV/V export is
    already a physical quantity, so there is no quantisation to declare -- and `import-csv` writes
    exactly that. The schema said one thing and the only consumer of it said another, so principle
    2's single interface did not reach the real data at all.
    """
    run = _fake_real_run(tmp_path / "physical", short_cfg)
    doc = yaml.safe_load((run / "run.yaml").read_text(encoding="utf-8"))
    doc["raw_value_kind"] = "strain"
    doc.pop("adc_range")
    doc.pop("adc_bits")
    doc["gauge_factor"] = 2.0
    (run / "run.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")

    src = ReplaySource(run)
    blocks = list(src.stream_blocks())
    assert blocks
    assert src.metadata.unit == "strain"
    assert src.metadata.adc_range is None, "a range that was never declared must not be invented"

    # Saturation cannot be checked without a range, which the validator already warns about; the
    # source has to agree with it rather than claim every sample is in range on its own authority.
    assert not any(b.saturated.any() for b in blocks)
    assert "raw_counts" in src.metadata.extra


def test_replay_still_inverts_the_adc_when_a_range_is_declared(
    tmp_path: Path, short_cfg: RunConfig
) -> None:
    """The counts path is the one that has a range, and it must keep working: dropping it in order
    to support physical quantities would trade one unreadable half of the corpus for the other."""
    run = _fake_real_run(tmp_path / "counts", short_cfg)
    src = ReplaySource(run)
    block = next(iter(src.stream_blocks()))
    assert src.metadata.adc_range is not None
    assert block.raw_counts.dtype.kind == "i"
    assert block.raw_counts.max() > 0
