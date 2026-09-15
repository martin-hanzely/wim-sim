"""Building the source a config asks for.

Principle 2: *everything downstream of ``SourceAdapter`` is identical whether samples come from the
generator or from a recording, so switching to real data is a config change and nothing else.*

Until this existed, that was an assertion rather than a fact. ``SourceConfig.kind`` was read by
nothing: every caller in the project constructed ``SyntheticSource(cfg)`` directly, and
``configs/scenarios/S8_replay_real.yaml`` -- written in phase 1 specifically so the switch would be
one config file -- was a document no code consulted.

What this does *not* do is make a real recording scorable. Every pipeline entry point bootstraps
its calibration from the truth log, and a recording has no truth log; see ``docs/sim-to-real.md``,
which has said since phase 3 that turning the real sensor's response into kilograms needs one
weighed vehicle. The factory closes the gap it can close -- the config now decides where samples
come from -- and leaves the one it cannot visible.
"""

from __future__ import annotations

from pathlib import Path

from wimsim.core.config import RunConfig
from wimsim.source.base import SourceAdapter
from wimsim.source.replay import ReplaySource
from wimsim.source.synthetic import SyntheticSource

__all__ = ["REAL_ROOT", "build_source"]

#: Where a bare ``run_dir`` is looked up. ``S8_replay_real`` says ``run_dir: drive_01``, and
#: ``docs/real-data-schema.md`` defines that as a directory under ``data/real/`` -- not a path
#: relative to wherever the command happened to be run from.
REAL_ROOT = Path("data/real")


def build_source(cfg: RunConfig, *, real_root: Path | str | None = None) -> SourceAdapter:
    """The source ``cfg.scenario.source.kind`` asks for."""
    source = cfg.scenario.source
    if source.kind == "synthetic":
        return SyntheticSource(cfg)

    if source.kind == "replay":
        replay = source.replay
        if replay is None:  # pragma: no cover - SourceConfig's validator refuses this
            raise ValueError("source.kind == 'replay' requires a source.replay block")
        run_dir = Path(replay.run_dir)
        if not run_dir.is_absolute() and len(run_dir.parts) == 1:
            run_dir = Path(real_root if real_root is not None else REAL_ROOT) / run_dir
        return ReplaySource(
            run_dir,
            channel=replay.channel,
            pacing=replay.rate,
            speed_multiplier=replay.speed_multiplier,
            block_seconds=cfg.scenario.block_seconds,
        )

    # `SerialSource` is a stub with no hardware behind it. Returning it here would mean a config
    # typo produced a run that read zeros and reported them as measurements, which is the failure
    # mode this project is least able to detect.
    raise ValueError(
        f"source.kind == {source.kind!r} is not runnable: SerialSource is a stub and has no "
        "hardware behind it. Use 'synthetic' or 'replay'."
    )
