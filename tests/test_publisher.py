"""The publisher and its persistent queue.

> **Outage integrity:** no events lost across a simulated disconnection; ordering preserved.
> -- buildspec section 11

That sentence is the entire reason this component exists, and it is why the queue is on disk rather
than in memory. A station is a box on a roadside behind a link that goes down; an in-process buffer
survives a broker outage and does not survive the station rebooting, and the second failure is the
one that loses a day of data.

Three properties are tested harder than the rest:

* **Nothing is acknowledged until the broker says so.** A queue that deletes on send loses exactly
  the messages that failed.
* **Replay is in timestamp order**, not insertion order and not arrival order. Downstream, an
  estimator that updates on arrival time rather than measurement time steps the wrong way when a
  backlog drains -- which is what S5 is built to expose.
* **Restarting the process resumes the backlog.** Anything less is an in-memory buffer with extra
  steps.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from wimsim.transport import InMemoryTransport, PersistentQueue, Publisher
from wimsim.transport.topics import topic_for


def _payload(i: int, *, ts: int | None = None) -> dict:
    return {"event_id": f"e{i}", "ts_start": ts if ts is not None else 1_700_000_000_000_000 + i}


def _publisher(tmp_path: Path, transport: InMemoryTransport, **kw) -> Publisher:
    return Publisher(
        transport,
        queue=PersistentQueue(tmp_path / "spool.db"),
        station_id="ST-1",
        **kw,
    )


# -- topics ----------------------------------------------------------------------------------


def test_topics_follow_the_buildspec_layout() -> None:
    assert topic_for("ST-1", "measurement.event") == "edge/ST-1/event"
    assert topic_for("ST-1", "measurement.sample") == "edge/ST-1/sample"
    assert topic_for("ST-1", "system.metric") == "edge/ST-1/metric"
    assert topic_for("ST-1", "calibration.state") == "edge/ST-1/calibration"
    assert topic_for("ST-1", "calibration.drift_detected") == "edge/ST-1/calibration"
    assert topic_for("ST-1", "system.incident") == "edge/ST-1/incident"


def test_an_unknown_topic_is_refused_rather_than_invented() -> None:
    with pytest.raises(KeyError, match="unknown"):
        topic_for("ST-1", "measurement.telepathy")


# -- the happy path --------------------------------------------------------------------------


def test_published_events_reach_the_transport_and_are_acknowledged(tmp_path: Path) -> None:
    transport = InMemoryTransport()
    pub = _publisher(tmp_path, transport)
    for i in range(5):
        pub.publish("measurement.event", _payload(i))
    pub.drain()

    assert len(transport.published) == 5
    assert pub.buffer_depth == 0
    assert pub.stats()["published"] == 5
    assert pub.stats()["failures"] == 0


def test_payloads_are_json_on_the_declared_topic(tmp_path: Path) -> None:
    import json

    transport = InMemoryTransport()
    pub = _publisher(tmp_path, transport)
    pub.publish("measurement.event", _payload(1))
    pub.drain()

    topic, blob, qos = transport.published[0]
    assert topic == "edge/ST-1/event"
    assert qos == 1, "QoS 1: at-least-once, which is what makes the idempotent upsert necessary"
    assert json.loads(blob)["event_id"] == "e1"


# -- outages ---------------------------------------------------------------------------------


def test_nothing_is_lost_while_the_link_is_down(tmp_path: Path) -> None:
    transport = InMemoryTransport()
    pub = _publisher(tmp_path, transport)

    pub.publish("measurement.event", _payload(0))
    pub.drain()
    assert len(transport.published) == 1

    transport.down = True
    for i in range(1, 6):
        pub.publish("measurement.event", _payload(i))
    pub.drain()

    assert len(transport.published) == 1, "nothing should have got through"
    assert pub.buffer_depth == 5, "and nothing should have been dropped"

    transport.down = False
    pub.drain()
    assert len(transport.published) == 6
    assert pub.buffer_depth == 0


def test_the_backlog_replays_in_timestamp_order_not_insertion_order(tmp_path: Path) -> None:
    """An estimator that updates on arrival time rather than measurement time steps the wrong way
    when a backlog drains. Ordering here is what stops that being the pipeline's fault."""
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport)

    base = 1_700_000_000_000_000
    for offset in (500, 100, 400, 200, 300):  # deliberately out of order
        pub.publish("measurement.event", _payload(offset, ts=base + offset))
    pub.drain()
    assert pub.buffer_depth == 5

    transport.down = False
    pub.drain()

    import json

    sent = [json.loads(blob)["ts_start"] for _t, blob, _q in transport.published]
    assert sent == sorted(sent)
    assert sent == [base + o for o in (100, 200, 300, 400, 500)]


def test_a_partial_outage_leaves_the_unsent_remainder_queued(tmp_path: Path) -> None:
    """A transport that accepts some messages and then refuses -- a full broker queue, say.

    The link never reports itself disconnected here, so nothing resets the backoff; the retry is
    what the polling loop would do a moment later, which is `force` or a later clock.
    """
    transport = InMemoryTransport(fail_after=3)
    pub = _publisher(tmp_path, transport)
    for i in range(10):
        pub.publish("measurement.event", _payload(i))

    assert len(transport.published) == 3
    assert pub.buffer_depth == 7

    transport.fail_after = None
    pub.drain(force=True)
    assert len(transport.published) == 10
    assert pub.buffer_depth == 0


def test_buffer_depth_is_observable_throughout(tmp_path: Path) -> None:
    """Buildspec section 9 wants wim_buffer_depth on a dashboard; it has to exist to be exported."""
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport)
    depths = []
    for i in range(4):
        pub.publish("measurement.event", _payload(i))
        depths.append(pub.buffer_depth)
    assert depths == [1, 2, 3, 4]


def test_retries_back_off_rather_than_spinning(tmp_path: Path) -> None:
    """Without a gate, a publisher in a loop hammers a dead broker as fast as the CPU allows.

    The clock is injected rather than slept through: a test that measures backoff by waiting for it
    is a test that takes as long as the backoff and still races on a loaded machine.
    """
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport, backoff_initial_s=0.01, backoff_max_s=0.08)
    pub.publish("measurement.event", _payload(0))

    # Based on the real monotonic clock, because publish() already drained once using it: an
    # injected clock starting below it would sit inside the resulting retry window and every
    # attempt would be gated rather than made, which is how this test first passed vacuously.
    delays, clock = [], time.monotonic()
    for _ in range(6):
        clock += 10.0  # well past any retry_after, so every attempt is actually made
        pub.drain(now=clock)
        delays.append(pub.current_backoff_s)

    assert delays == sorted(delays), "backoff must not shrink while the link is still down"
    assert delays[-1] > delays[0], "and must actually grow"
    assert delays[-1] <= 0.08, "and must be capped"


def test_the_gate_suppresses_attempts_between_retries(tmp_path: Path) -> None:
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport, backoff_initial_s=5.0)
    pub.publish("measurement.event", _payload(0))
    attempts_after_first = pub.stats()["failures"]

    instant = time.monotonic()
    for _ in range(20):
        pub.drain(now=instant)  # same instant, still inside the 5 s backoff window
    assert pub.stats()["failures"] == attempts_after_first, "the gate should have blocked these"


def test_a_reconnect_resets_the_backoff_without_waiting_it_out(tmp_path: Path) -> None:
    """A link that has just come back is the one moment when honouring a 30 s backoff is wrong."""
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport, backoff_initial_s=5.0, backoff_max_s=30.0)
    pub.publish("measurement.event", _payload(0))
    assert pub.current_backoff_s > 5.0

    transport.down = False
    assert pub.drain() == 1, "delivery should happen immediately on reconnect"
    assert pub.current_backoff_s == pytest.approx(5.0)
    assert pub.stats()["reconnects"] == 1


# -- durability -------------------------------------------------------------------------------


def test_the_queue_survives_the_process_dying(tmp_path: Path) -> None:
    """The distinguishing property. An in-memory buffer survives a broker outage; it does not
    survive the station rebooting, and that is the failure that loses a day of data."""
    spool = tmp_path / "spool.db"
    transport = InMemoryTransport(down=True)
    first = Publisher(transport, queue=PersistentQueue(spool), station_id="ST-1")
    for i in range(4):
        first.publish("measurement.event", _payload(i))
    first.drain()
    assert first.buffer_depth == 4
    first.close()

    # a new process, a new publisher, the same spool
    revived = Publisher(InMemoryTransport(), queue=PersistentQueue(spool), station_id="ST-1")
    assert revived.buffer_depth == 4
    revived.drain()
    assert revived.buffer_depth == 0
    revived.close()


def test_acknowledged_events_are_not_resent_after_a_restart(tmp_path: Path) -> None:
    spool = tmp_path / "spool.db"
    transport = InMemoryTransport()
    first = Publisher(transport, queue=PersistentQueue(spool), station_id="ST-1")
    for i in range(3):
        first.publish("measurement.event", _payload(i))
    first.drain()
    first.close()

    second_transport = InMemoryTransport()
    second = Publisher(second_transport, queue=PersistentQueue(spool), station_id="ST-1")
    second.drain()
    assert second_transport.published == []
    second.close()


def test_the_queue_is_bounded_and_drops_oldest_with_a_loud_complaint(tmp_path: Path) -> None:
    """Unbounded buffering turns a link outage into a full disk, which takes the station down
    entirely. Dropping is bad; dropping silently is worse."""
    transport = InMemoryTransport(down=True)
    pub = _publisher(tmp_path, transport, max_queue_depth=5)
    for i in range(8):
        pub.publish("measurement.event", _payload(i))

    assert pub.buffer_depth == 5
    assert pub.stats()["dropped"] == 3

    transport.down = False
    pub.drain()
    import json

    ids = [json.loads(b)["event_id"] for _t, b, _q in transport.published]
    assert ids == ["e3", "e4", "e5", "e6", "e7"], "the oldest go first, newest data is kept"


# -- the queue itself --------------------------------------------------------------------------


def test_queue_reports_its_depth_and_survives_reopen(tmp_path: Path) -> None:
    q = PersistentQueue(tmp_path / "q.db")
    q.append("edge/ST-1/event", b'{"a":1}', ts_us=10, qos=1)
    q.append("edge/ST-1/event", b'{"a":2}', ts_us=5, qos=1)
    assert q.depth() == 2
    q.close()

    again = PersistentQueue(tmp_path / "q.db")
    assert again.depth() == 2
    batch = again.peek(10)
    assert [row.ts_us for row in batch] == [5, 10], "peek is ordered by measurement time"
    again.ack([batch[0].row_id])
    assert again.depth() == 1
    again.close()


def test_queue_ack_of_an_unknown_row_is_harmless(tmp_path: Path) -> None:
    q = PersistentQueue(tmp_path / "q.db")
    q.append("t", b"{}", ts_us=1, qos=1)
    q.ack([9999])
    assert q.depth() == 1
    q.close()
