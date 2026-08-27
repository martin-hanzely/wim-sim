"""Integration tests against the real broker.

The unit tests use ``InMemoryTransport`` because every property worth checking about the publisher
is about what happens when delivery *fails*, and a real broker is very bad at failing on demand.
These tests check the complementary thing the fake cannot: that a real Mosquitto accepts what we
send, in the shape we send it, and hands it back to a subscriber unchanged.

They **skip** when the stack is not up, so the suite still runs on a machine without Docker. That is
a deliberate trade -- a skipped test is a test nobody runs -- so the skip message says exactly how to
turn them on, and CI is expected to bring the stack up.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from wimsim.transport import PersistentQueue, Publisher, TransportError
from wimsim.transport.mqtt import MqttTransport
from wimsim.transport.topics import wildcard_for

HOST, PORT = "localhost", 1883


def _broker_is_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _broker_is_up(),
    reason=f"no MQTT broker on {HOST}:{PORT} -- start it with `docker compose --profile core up -d`",
)


class _Collector:
    """Subscribes and records, so a test can assert on what actually crossed the wire."""

    def __init__(self, topic: str) -> None:
        import paho.mqtt.client as mqtt

        self.messages: list[tuple[str, bytes]] = []
        self._ready = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        self._client.on_message = lambda _c, _u, msg: self.messages.append((msg.topic, msg.payload))
        self._client.on_subscribe = lambda *_a, **_k: self._ready.set()
        self._client.connect(HOST, PORT, 30)
        self._client.loop_start()
        self._client.subscribe(topic, qos=1)
        if not self._ready.wait(10.0):
            raise RuntimeError("subscription was not acknowledged")

    def wait_for(self, count: int, timeout_s: float = 15.0) -> list[tuple[str, bytes]]:
        deadline = time.monotonic() + timeout_s
        while len(self.messages) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return list(self.messages)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


@pytest.fixture
def collector():
    made: list[_Collector] = []

    def _make(topic: str) -> _Collector:
        c = _Collector(topic)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close()


def _unique(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


# -- the round trip ------------------------------------------------------------------------------


def test_a_published_event_comes_back_off_the_broker_unchanged(tmp_path: Path, collector) -> None:
    station = _unique("ST-IT")
    sink = collector(wildcard_for(station))

    transport = MqttTransport(host=HOST, port=PORT, station_id=station)
    transport.connect()
    pub = Publisher(transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station)

    payload = {"topic": "measurement.event", "event_id": "abc", "ts_start": 1_700_000_000_000_000}
    pub.publish("measurement.event", payload)
    assert pub.flush(timeout_s=15.0)

    got = sink.wait_for(1)
    assert len(got) == 1
    topic, blob = got[0]
    assert topic == f"edge/{station}/event"
    assert json.loads(blob) == payload

    pub.close()
    transport.disconnect()


def test_qos1_delivery_is_confirmed_before_the_spool_forgets(tmp_path: Path, collector) -> None:
    """The spool must not acknowledge a message the broker never saw.

    ``paho.publish()`` returning success only means the packet was queued in the client. If that
    were treated as delivery, an outage starting between the call and the PUBACK would lose exactly
    the events in flight.
    """
    station = _unique("ST-QOS")
    sink = collector(wildcard_for(station))

    transport = MqttTransport(host=HOST, port=PORT, station_id=station)
    transport.connect()
    pub = Publisher(transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station)

    for i in range(25):
        pub.publish("measurement.event", {"event_id": f"e{i}", "ts_start": 1_700_000_000 + i})
    assert pub.flush(timeout_s=20.0)
    assert pub.buffer_depth == 0, "the spool is only empty because every PUBACK arrived"

    assert len(sink.wait_for(25)) == 25

    pub.close()
    transport.disconnect()


def test_a_healthy_link_sends_immediately_rather_than_batching(tmp_path: Path, collector) -> None:
    """Ordering is a property of a *drained backlog*, not of every publish.

    On a healthy link each event goes out as it is spooled, in the order the pipeline produced it,
    which is already measurement order. The publisher is a queue that replays in timestamp order,
    not a sorter -- expecting it to reorder a live stream would mean holding every event back until
    something later might arrive, which is latency bought for nothing.
    """
    station = _unique("ST-LIVE")
    sink = collector(wildcard_for(station))

    transport = MqttTransport(host=HOST, port=PORT, station_id=station)
    transport.connect()
    pub = Publisher(transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station)

    base = 1_700_000_000_000_000
    for i in range(5):
        pub.publish("measurement.event", {"event_id": f"e{i}", "ts_start": base + i})
        assert pub.buffer_depth == 0, "a healthy link should not accumulate a backlog at all"
    assert pub.flush(timeout_s=15.0)

    ids = [json.loads(b)["event_id"] for _t, b in sink.wait_for(5)]
    assert ids == [f"e{i}" for i in range(5)]

    pub.close()
    transport.disconnect()


def test_a_backlog_drained_over_a_real_broker_arrives_in_timestamp_order(
    tmp_path: Path, collector
) -> None:
    """The buildspec's "replay in timestamp order on reconnect", against a real broker.

    Same process throughout -- the link drops and returns, the station does not restart. The
    restart case is covered separately.
    """
    station = _unique("ST-ORD")
    sink = collector(wildcard_for(station))

    transport = MqttTransport(host=HOST, port=PORT, station_id=station)
    transport.connect()
    pub = Publisher(transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station)

    transport.disconnect()  # the link drops
    base = 1_700_000_000_000_000
    for offset in (900, 100, 700, 300, 500):  # events keep arriving, out of order
        pub.publish("measurement.event", {"event_id": f"e{offset}", "ts_start": base + offset})
    assert pub.buffer_depth == 5, "nothing delivered, nothing dropped"

    transport.connect()  # and comes back
    assert pub.flush(timeout_s=20.0)

    stamps = [json.loads(b)["ts_start"] for _t, b in sink.wait_for(5)]
    assert len(stamps) == 5
    assert stamps == sorted(stamps)
    assert stamps == [base + o for o in (100, 300, 500, 700, 900)]

    pub.close()
    transport.disconnect()


# -- failure modes --------------------------------------------------------------------------------


def test_connecting_to_a_dead_port_raises_rather_than_hanging() -> None:
    transport = MqttTransport(host=HOST, port=1, station_id="ST-DEAD")
    with pytest.raises(TransportError, match="cannot reach the broker"):
        transport.connect()


def test_publishing_while_disconnected_raises_and_leaves_the_event_queued(tmp_path: Path) -> None:
    station = _unique("ST-DROP")
    transport = MqttTransport(host=HOST, port=PORT, station_id=station)
    transport.connect()
    pub = Publisher(transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station)

    transport.disconnect()
    pub.publish("measurement.event", {"event_id": "orphan", "ts_start": 1})
    assert pub.buffer_depth == 1, "an undeliverable event stays on disk"

    transport.connect()
    assert pub.flush(timeout_s=15.0)
    assert pub.buffer_depth == 0

    pub.close()
    transport.disconnect()


def test_the_spool_survives_a_broker_outage_and_a_publisher_restart(
    tmp_path: Path, collector
) -> None:
    """The scenario S5 exists for, minus the thermal ramp: link down, events keep arriving, station
    restarts, link returns, nothing lost and nothing out of order."""
    station = _unique("ST-OUT")
    sink = collector(wildcard_for(station))
    spool = tmp_path / "spool.db"
    base = 1_700_000_000_000_000

    # link down: the transport never connects, so nothing can be delivered
    down = MqttTransport(host=HOST, port=1, station_id=station)
    first = Publisher(down, queue=PersistentQueue(spool), station_id=station)
    for i in range(10):
        first.publish("measurement.event", {"event_id": f"e{i}", "ts_start": base + (10 - i)})
    assert first.buffer_depth == 10
    first.close()  # the station reboots

    up = MqttTransport(host=HOST, port=PORT, station_id=station)
    up.connect()
    second = Publisher(up, queue=PersistentQueue(spool), station_id=station)
    assert second.buffer_depth == 10, "the backlog outlived the process"
    assert second.flush(timeout_s=20.0)

    stamps = [json.loads(b)["ts_start"] for _t, b in sink.wait_for(10)]
    assert len(stamps) == 10, "nothing lost"
    assert stamps == sorted(stamps), "and replayed in measurement order"

    second.close()
    up.disconnect()
