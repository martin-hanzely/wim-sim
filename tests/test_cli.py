"""The CLI, end to end.

Smoke-level on purpose: these check that the commands wire up, produce the files they promise, and
fail with a useful exit code rather than a traceback. The behaviour they invoke is tested properly
elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from wimsim.cli import app

runner = CliRunner()


def _run(*args: str):
    return runner.invoke(app, list(args))


def _text(result) -> str:
    """stdout plus stderr. Errors are written to stderr, and click keeps the two apart."""
    err = ""
    try:
        err = result.stderr or ""
    except ValueError:  # stderr not captured separately in this click version
        pass
    return (result.stdout or "") + err


def test_version() -> None:
    result = _run("version")
    assert result.exit_code == 0
    assert "wimsim" in result.stdout


def test_scenarios_lists_everything_and_flags_nothing_broken() -> None:
    result = _run("scenarios")
    assert result.exit_code == 0
    assert "S1_nominal" in result.stdout
    assert "S8_replay_real" in result.stdout
    assert "BROKEN" not in result.stdout


def test_config_hash_is_stable_and_64_hex() -> None:
    a = _run("config-hash", "S1_nominal")
    b = _run("config-hash", "S1_nominal")
    assert a.exit_code == 0
    digest = a.stdout.strip()
    assert len(digest) == 64
    assert digest == b.stdout.strip()


def test_config_hash_reflects_an_override() -> None:
    a = _run("config-hash", "S1_nominal").stdout.strip()
    b = _run("config-hash", "S1_nominal", "--set", "scenario.duration_s=60.0").stdout.strip()
    assert a != b


def test_unknown_scenario_exits_two() -> None:
    result = _run("config-hash", "not_a_scenario")
    assert result.exit_code == 2


def test_generate_inspect_and_plot(tmp_path: Path) -> None:
    out = tmp_path / "run"
    gen = _run(
        "generate",
        "S1_nominal",
        "--out",
        str(out),
        "--set",
        "scenario.duration_s=120.0",
        "--set",
        "scenario.block_seconds=30.0",
    )
    assert gen.exit_code == 0, gen.stdout
    for name in (
        "manifest.json",
        "config.yaml",
        "samples.parquet",
        "truth_passes.parquet",
        "truth_timeseries.parquet",
    ):
        assert (out / name).exists(), name

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenario"] == "S1_nominal"
    assert manifest["counts"]["passes_scheduled"] > 0

    ins = _run("inspect", str(out))
    assert ins.exit_code == 0
    assert manifest["output_hash"] in ins.stdout

    p1 = _run("plot-pass", str(out), "--index", "0")
    assert p1.exit_code == 0, p1.stdout
    assert (out / "pass_00000.png").exists()

    p2 = _run("plot-run", str(out))
    assert p2.exit_code == 0, p2.stdout
    assert (out / "run_overview.png").exists()


def test_generate_twice_then_verify_determinism(tmp_path: Path) -> None:
    args = ("--set", "scenario.duration_s=60.0", "--set", "scenario.block_seconds=30.0")
    for name in ("a", "b"):
        r = _run("generate", "S1_nominal", "--out", str(tmp_path / name), "-q", *args)
        assert r.exit_code == 0, r.stdout
    check = _run("verify-determinism", str(tmp_path / "a"), str(tmp_path / "b"))
    assert check.exit_code == 0, check.stdout
    assert "determinism check passed" in check.stdout


def test_verify_determinism_fails_on_different_seeds(tmp_path: Path) -> None:
    base = ("--set", "scenario.duration_s=60.0", "--set", "scenario.block_seconds=30.0")
    _run("generate", "S1_nominal", "--out", str(tmp_path / "a"), "-q", *base)
    _run("generate", "S1_nominal", "--out", str(tmp_path / "b"), "-q", "--seed", "999", *base)
    check = _run("verify-determinism", str(tmp_path / "a"), str(tmp_path / "b"))
    assert check.exit_code == 1


def test_generate_refuses_a_replay_scenario(tmp_path: Path) -> None:
    result = _run("generate", "S8_replay_real", "--out", str(tmp_path / "x"))
    assert result.exit_code == 2


def test_samples_none_writes_no_sample_file(tmp_path: Path) -> None:
    out = tmp_path / "run"
    r = _run(
        "generate",
        "S1_nominal",
        "--out",
        str(out),
        "-q",
        "--samples",
        "none",
        "--set",
        "scenario.duration_s=60.0",
        "--set",
        "scenario.block_seconds=30.0",
    )
    assert r.exit_code == 0, r.stdout
    assert not (out / "samples.parquet").exists()
    assert (out / "truth_passes.parquet").exists()

    plot = _run("plot-pass", str(out))
    assert plot.exit_code != 0, "plotting a waveform that was never written must fail loudly"


def test_full_samples_over_the_cap_is_refused_without_force(tmp_path: Path) -> None:
    r = _run(
        "generate",
        "S1_nominal",
        "--out",
        str(tmp_path / "big"),
        "-q",
        "--samples",
        "full",
        "--set",
        "scenario.duration_s=60.0",
        "--set",
        "scenario.block_seconds=30.0",
        "--set",
        "scenario.output.max_sample_rows=1000",
    )
    assert r.exit_code == 2
    assert "max_sample_rows" in _text(r)


def test_real_data_schema_prints_the_contract() -> None:
    result = _run("real-data-schema")
    assert result.exit_code == 0
    for token in ("samples.parquet", "run.yaml", "reference.csv", "raw_value_kind", "channel_map"):
        assert token in result.stdout


def test_validate_real_data_on_a_missing_directory_exits_one(tmp_path: Path) -> None:
    result = _run("validate-real-data", str(tmp_path / "nope"))
    assert result.exit_code == 1


def test_unapplied_pipeline_faults_are_announced(tmp_path: Path) -> None:
    """S5 carries phase-3 faults. Phase 1 must say it ignored them, not pretend it applied them."""
    out = tmp_path / "s5"
    r = _run(
        "generate",
        "S5_outage",
        "--out",
        str(out),
        "--samples",
        "none",
        "--set",
        "scenario.duration_s=300.0",
        "--set",
        'scenario.faults=[{"type": "connectivity_loss", "label": "link_down", "t_start_s": 60.0, "duration_s": 60.0}]',
    )
    assert r.exit_code == 0, r.stdout
    assert "NOT applied" in r.stdout
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["faults_unapplied"] == ["link_down"]
    assert manifest["faults_applied"] == []


# -- gap report -------------------------------------------------------------------------------


def _example_run(repo_root: Path) -> Path:
    example = repo_root / "data" / "real" / "EXAMPLE"
    if not example.is_dir():
        import pytest

        pytest.skip("data/real/EXAMPLE not present in this checkout")
    return example


def test_gap_report_compares_a_recording_against_a_scenario(repo_root: Path) -> None:
    result = _run("gap-report", str(_example_run(repo_root)), "--scenario", "S1_nominal")
    assert result.exit_code == 0, _text(result)
    out = _text(result)
    assert "Sim-to-real gap" in out
    assert "white sigma" in out
    assert "--set scenario.noise.white_sigma=" in out, (
        "the fitted parameters have to come back as lines that load"
    )


def test_gap_report_writes_a_file_when_asked(repo_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "gap.md"
    result = _run("gap-report", str(_example_run(repo_root)), "--out", str(out))
    assert result.exit_code == 0, _text(result)
    assert out.is_file()
    assert "Sim-to-real gap" in out.read_text(encoding="utf-8")


def test_gap_report_refuses_a_directory_that_is_not_a_recording(tmp_path: Path) -> None:
    result = _run("gap-report", str(tmp_path / "nope"))
    assert result.exit_code == 2
    assert "cannot read" in _text(result)


def test_gap_report_generates_its_reference_at_the_recordings_sample_rate(
    repo_root: Path, tmp_path: Path
) -> None:
    """Comparing PSDs computed on two different sample grids would show differences that are
    entirely an artefact of the grids. The synthetic side has to be generated at the recording's
    rate, and the report should say which rate that was."""
    out = tmp_path / "gap.md"
    result = _run("gap-report", str(_example_run(repo_root)), "--out", str(out))
    assert result.exit_code == 0, _text(result)
    assert "2,000 Hz" in _text(result) or "2000 Hz" in _text(result)


# -- detect -----------------------------------------------------------------------------------


def test_detect_reports_what_the_detector_found_without_scoring_it(repo_root: Path) -> None:
    """Detection needs no truth, so it is the one part of the pipeline a real recording can drive
    end to end. Everything past it -- calibration, mass, score -- bootstraps from a truth log a
    recording does not have."""
    result = _run("detect", "S1_nominal", "--set", "scenario.duration_s=300")
    assert result.exit_code == 0, _text(result)
    out = _text(result)
    assert "events" in out
    assert "kg" not in out, "a detection is not a mass, and printing one would imply a calibration"


def test_detect_runs_a_replay_scenario_from_its_config(repo_root: Path) -> None:
    """`S8_replay_real` was written in phase 1 so that switching to real data would be a config
    change and nothing else. This is the first command that makes that true."""
    example = _example_run(repo_root)
    result = _run(
        "detect",
        "S8_replay_real",
        "--set",
        f"scenario.source.replay.run_dir={example}",
    )
    assert result.exit_code == 0, _text(result)
    assert "replay" in _text(result)


def test_detect_refuses_a_replay_scenario_whose_recording_is_missing(tmp_path: Path) -> None:
    result = _run(
        "detect", "S8_replay_real", "--set", f"scenario.source.replay.run_dir={tmp_path / 'nope'}"
    )
    assert result.exit_code == 2
    assert "cannot read" in _text(result).lower() or "does not" in _text(result).lower()
