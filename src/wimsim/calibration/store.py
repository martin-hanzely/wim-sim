"""The profile store: append-only, versioned, and readable without this program.

Buildspec section 6 asks for a store in which "every profile" carries its id, estimator type,
parameters, activation timestamp, provenance and ``superseded_by``, and in which "historical events
must be recomputable under a different profile".

**Append-only is the load-bearing word, and it decides how ``superseded_by`` works.** The obvious
implementation sets that field on the previous row when a new profile is activated -- which means
rewriting a line, which means a calibration history that can be edited. An audit trail you can edit
is not an audit trail. So the link is *derived* from the sequence on read and never written: profile
*n* is superseded by profile *n+1*, and the last one is superseded by nothing. Nothing in the file
ever changes after it is written, and ``tests/test_profile_store.py`` checks that by reading the
first line back as text after two more appends.

**One JSON object per line, and no framework.** A calibration history only readable by the program
that wrote it is not provenance. JSON Lines means ``jq`` works, a text editor works, and appending
is a single write with no read-modify-write window to lose a profile in. It also keeps this module
inside principle 6 -- stdlib only -- so a Pi with no database still has a durable calibration
history across reboots. The server's copy of the same information arrives separately, as
``calibration.profile_activated`` events.

**Timestamps must not go backwards.** A profile activated before the one it replaces makes
``active_at`` ambiguous, and every recompute over that window would then depend on the order the
file happened to be written in. Refused at append time, where there is still someone to tell.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from wimsim.calibration.base import CalibrationProfile

__all__ = ["ProfileStore"]


class ProfileStore:
    """A calibration history on disk. Reads are cheap; the file is small by construction."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._cache: list[CalibrationProfile] | None = None

    # -- writing -----------------------------------------------------------------------------

    def append(self, profile: CalibrationProfile) -> CalibrationProfile:
        """Add a profile. Never touches what is already there."""
        existing = self._load()
        if any(p.profile_id == profile.profile_id for p in existing):
            raise ValueError(
                f"profile {profile.profile_id!r} is already in the store. Profile ids are derived "
                "from the estimator state hash, so a collision means the same calibration is being "
                "activated twice -- which is a no-op worth noticing rather than recording."
            )
        if existing and profile.activated_ts_us < existing[-1].activated_ts_us:
            raise ValueError(
                f"activation timestamps must not go backwards: {profile.profile_id!r} activates at "
                f"{profile.activated_ts_us} but {existing[-1].profile_id!r} already activated at "
                f"{existing[-1].activated_ts_us}. A recompute over that window would be ambiguous."
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = profile.to_dict()
        # Derived on read, so writing it would create two sources of truth for the same link.
        record.pop("superseded_by", None)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

        self._cache = None
        return self.get(profile.profile_id)

    # -- reading -----------------------------------------------------------------------------

    def history(self) -> list[CalibrationProfile]:
        """Every profile, oldest first, with ``superseded_by`` filled in."""
        return list(self._load())

    def get(self, profile_id: str) -> CalibrationProfile:
        for profile in self._load():
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(
            f"no profile {profile_id!r} in {self.path}. Known ids: "
            f"{[p.profile_id for p in self._load()]}"
        )

    def active_at(self, ts_us: int) -> CalibrationProfile | None:
        """The profile in force at that instant, or None if none had been activated yet.

        None rather than the earliest one, deliberately. An event measured before any calibration
        existed cannot be recomputed, and handing back a law that was not in force when the vehicle
        crossed would produce a number that looks reproducible and is not.
        """
        active: CalibrationProfile | None = None
        for profile in self._load():
            if profile.activated_ts_us <= int(ts_us):
                active = profile
            else:
                break
        return active

    def latest(self) -> CalibrationProfile | None:
        profiles = self._load()
        return profiles[-1] if profiles else None

    def __len__(self) -> int:
        return len(self._load())

    def __iter__(self) -> Iterator[CalibrationProfile]:
        return iter(self._load())

    # -- internals ---------------------------------------------------------------------------

    def _load(self) -> list[CalibrationProfile]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = []
            return self._cache

        records: list[dict] = []
        with self.path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue  # a file appended to by a shell script, or repaired after a truncation
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{self.path}, line {number}: not valid JSON ({exc.msg}). Refusing to skip "
                        "it -- a station that quietly ignores part of its calibration history is a "
                        "station weighing under a profile nobody chose."
                    ) from exc

        profiles = [CalibrationProfile.from_dict(record) for record in records]
        # superseded_by, derived: each profile is replaced by the next, the last by nothing.
        self._cache = [
            _with_successor(profile, profiles[i + 1].profile_id if i + 1 < len(profiles) else None)
            for i, profile in enumerate(profiles)
        ]
        return self._cache


def _with_successor(profile: CalibrationProfile, successor: str | None) -> CalibrationProfile:
    from dataclasses import replace

    return replace(profile, superseded_by=successor)
