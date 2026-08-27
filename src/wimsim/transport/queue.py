"""The publisher's spool: an on-disk, ordered, acknowledge-on-delivery queue.

**On disk, not in memory.** A station is a box on a roadside behind a link that goes down. An
in-process buffer survives a broker outage and does not survive the station rebooting, and the
second failure is the one that loses a day of data.

**Ordered by measurement time, not insertion time.** ``peek`` returns the oldest *measurements*
first, so a drained backlog arrives in the order the vehicles actually crossed. That matters
downstream rather than here: an estimator that updates on arrival time rather than measurement time
steps the wrong way when a backlog drains, which is precisely what ``S5_outage`` exists to expose.
Delivering in the wrong order would make that the pipeline's fault instead of the estimator's.

**Nothing is deleted until the broker acknowledges it.** A queue that deletes on send loses exactly
the messages that failed to send.

SQLite rather than a file per message: one fsync per batch instead of one per event, atomic
acknowledgement, and a depth query that does not mean listing a directory of half a million files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PersistentQueue", "QueuedMessage"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spool (
    row_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_us   INTEGER NOT NULL,
    topic   TEXT    NOT NULL,
    qos     INTEGER NOT NULL DEFAULT 1,
    payload BLOB    NOT NULL
);
-- Replay order. row_id breaks ties so that two events sharing a timestamp still come out in a
-- deterministic order rather than whatever the page layout happens to give.
CREATE INDEX IF NOT EXISTS spool_order ON spool (ts_us, row_id);
"""


@dataclass(frozen=True, slots=True)
class QueuedMessage:
    row_id: int
    ts_us: int
    topic: str
    qos: int
    payload: bytes


class PersistentQueue:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        # WAL survives a process kill without a torn database, and lets a reader (the metrics
        # exporter asking for depth) run while the publisher writes.
        self._db.execute("PRAGMA journal_mode=WAL")
        # NORMAL, not FULL: FULL fsyncs on every commit, which at a few hundred events an hour is
        # pointless, and at sample rates would dominate the station's power budget. With WAL,
        # NORMAL loses at most the last transaction on an OS crash -- not on a process crash.
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    # -- writing ------------------------------------------------------------------------------

    def append(self, topic: str, payload: bytes, *, ts_us: int, qos: int = 1) -> int:
        cur = self._db.execute(
            "INSERT INTO spool (ts_us, topic, qos, payload) VALUES (?, ?, ?, ?)",
            (int(ts_us), topic, int(qos), payload),
        )
        return int(cur.lastrowid)

    def ack(self, row_ids: list[int]) -> int:
        """Delete acknowledged rows. Unknown ids are ignored rather than raising: an ack arriving
        twice is a normal consequence of at-least-once delivery."""
        if not row_ids:
            return 0
        marks = ",".join("?" * len(row_ids))
        cur = self._db.execute(f"DELETE FROM spool WHERE row_id IN ({marks})", row_ids)
        return int(cur.rowcount)

    def trim_to(self, max_depth: int) -> int:
        """Drop the oldest rows beyond ``max_depth``. Returns how many were dropped.

        Unbounded buffering turns a link outage into a full disk, which takes the station down
        entirely -- a worse outcome than losing the oldest events. The caller is expected to count
        and report what this drops; dropping is bad, dropping silently is worse.
        """
        excess = self.depth() - max_depth
        if excess <= 0:
            return 0
        cur = self._db.execute(
            "DELETE FROM spool WHERE row_id IN ("
            "  SELECT row_id FROM spool ORDER BY ts_us, row_id LIMIT ?"
            ")",
            (excess,),
        )
        return int(cur.rowcount)

    # -- reading ------------------------------------------------------------------------------

    def peek(self, limit: int) -> list[QueuedMessage]:
        rows = self._db.execute(
            "SELECT row_id, ts_us, topic, qos, payload FROM spool ORDER BY ts_us, row_id LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [QueuedMessage(*row) for row in rows]

    def depth(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM spool").fetchone()[0])

    def oldest_ts_us(self) -> int | None:
        row = self._db.execute("SELECT MIN(ts_us) FROM spool").fetchone()
        return None if row is None or row[0] is None else int(row[0])

    # -- lifecycle -----------------------------------------------------------------------------

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> PersistentQueue:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
