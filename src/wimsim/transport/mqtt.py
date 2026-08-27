"""MQTT transport, on paho.

Thin on purpose. Everything interesting about delivery -- the spool, ordering, backoff, what counts
as acknowledged -- lives in :mod:`wimsim.transport.publisher`, which is testable without a broker.
This module's only job is to turn "publish these bytes" into a network operation and to raise
:class:`TransportError` when that does not happen.

Two things it does not do, deliberately:

**It does not retry.** The publisher owns that policy, and a client that retried underneath would
break the guarantee that nothing is acknowledged until it is actually delivered.

**It does not consider a message delivered when ``publish()`` returns.** At QoS 1 that call only
queues the packet in the client; delivery is confirmed by PUBACK, which arrives later. ``wait_for
_publish`` is what turns the two into one synchronous fact, and without it the spool would ack
messages the broker never saw.

The last will is a retained ``system.incident`` on the station's own topic, so a station that dies
without saying goodbye announces it itself -- rather than being noticed some minutes later by a
heartbeat rule that has to be written, deployed and remembered.
"""

from __future__ import annotations

import json
import threading
import time

import paho.mqtt.client as mqtt

from wimsim.transport.base import TransportError
from wimsim.transport.topics import topic_for

__all__ = ["MqttTransport"]


class MqttTransport:
    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 1883,
        station_id: str = "",
        client_id: str | None = None,
        keepalive_s: int = 30,
        publish_timeout_s: float = 10.0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.station_id = station_id
        self.publish_timeout_s = publish_timeout_s

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or f"wimsim-{station_id or 'edge'}",
            # A clean session would have the broker forget QoS-1 state on every reconnect, which
            # is the state the at-least-once guarantee is made of.
            clean_session=None,
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._connected = threading.Event()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        if station_id:
            self._client.will_set(
                topic_for(station_id, "system.incident"),
                json.dumps(
                    {
                        "topic": "system.incident",
                        "schema_version": "1.0.0",
                        "station_id": station_id,
                        "ts": 0,
                        "severity": "error",
                        "kind": "heartbeat_loss",
                        "message": (
                            "station disconnected without a clean shutdown; this message was left "
                            "with the broker in advance"
                        ),
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
                qos=1,
                retain=True,
            )

    # -- callbacks -----------------------------------------------------------------------------

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            self._connected.clear()
        else:
            self._connected.set()

    def _on_disconnect(self, _client, _userdata, _flags, _reason_code, _properties=None) -> None:
        self._connected.clear()

    # -- lifecycle -----------------------------------------------------------------------------

    def connect(self, *, timeout_s: float = 10.0) -> None:
        try:
            self._client.connect(self.host, self.port, keepalive=30)
        except OSError as exc:
            raise TransportError(
                f"cannot reach the broker at {self.host}:{self.port}: {exc}"
            ) from exc
        self._client.loop_start()
        if not self._connected.wait(timeout_s):
            self._client.loop_stop()
            raise TransportError(
                f"connected to {self.host}:{self.port} but the broker did not acknowledge within "
                f"{timeout_s} s"
            )

    def disconnect(self) -> None:
        # A clean disconnect tells the broker not to send the will. That is the point of the
        # distinction: an orderly shutdown is not an incident.
        self._client.disconnect()
        self._client.loop_stop()
        self._connected.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set() and self._client.is_connected()

    # -- publishing ----------------------------------------------------------------------------

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        if not self.is_connected:
            raise TransportError("not connected to the broker")

        info = self._client.publish(topic, payload, qos=qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise TransportError(f"publish to {topic} refused: {mqtt.error_string(info.rc)}")

        if qos == 0:
            return
        # At QoS 1 the call above only queued the packet. Treating that as delivery would let the
        # spool acknowledge messages the broker never received -- the exact failure the spool exists
        # to prevent.
        deadline = time.monotonic() + self.publish_timeout_s
        while not info.is_published():
            if time.monotonic() > deadline:
                raise TransportError(
                    f"no PUBACK for {topic} within {self.publish_timeout_s} s; leaving it queued"
                )
            if not self.is_connected:
                raise TransportError(f"link dropped while awaiting PUBACK for {topic}")
            time.sleep(0.002)

    def __enter__(self) -> MqttTransport:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()
