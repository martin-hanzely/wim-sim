"""Provenance stamping.

Principle 3: a result you cannot reproduce is not a result. Every artifact this repository writes
carries a :class:`Provenance` block, and so will every emitted event from phase 2 onward.

The git state is captured honestly: if the working tree is dirty, ``git_dirty`` is true and the
commit alone does *not* identify the code that ran. Downstream analysis should treat dirty runs as
non-citable.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wimsim import SCHEMA_VERSION

__all__ = ["Provenance", "collect", "git_state", "hash_files", "sha256_file"]

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def git_state() -> tuple[str | None, bool]:
    """(commit sha, dirty). ``(None, True)`` when this is not a git checkout."""
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return None, True
    status = _git("status", "--porcelain")
    return commit, bool(status)


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def hash_files(paths: list[Path]) -> str:
    """One hash standing for a set of files: sha256 over ``name:filehash`` lines, name-sorted.

    Order- and path-independent, so the same run written to two directories hashes the same.
    """
    lines = sorted(f"{p.name}:{sha256_file(p)}" for p in paths if p.is_file())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    schema_version: str
    config_hash: str
    seed: int
    mode: str
    git_commit: str | None
    git_dirty: bool
    wimsim_version: str
    python_version: str
    platform: str
    created_at: str
    """Wall-clock time of the run. Deliberately excluded from every hash -- it is the one field
    that legitimately differs between two reproductions of the same run."""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect(*, config_hash: str, seed: int, mode: str = "synthetic") -> Provenance:
    commit, dirty = git_state()
    from wimsim import __version__

    return Provenance(
        schema_version=SCHEMA_VERSION,
        config_hash=config_hash,
        seed=int(seed),
        mode=mode,
        git_commit=commit,
        git_dirty=dirty,
        wimsim_version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
