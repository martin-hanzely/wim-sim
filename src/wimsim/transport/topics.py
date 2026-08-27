"""MQTT topic naming.

``edge/<station>/{sample,event,metric,calibration,incident}`` per buildspec section 8. The mapping
from schema topic to MQTT topic is many-to-one -- every ``calibration.*`` payload shares one topic --
because a subscriber wants the calibration stream, not three separate subscriptions it has to
reassemble in order.

An unknown schema topic raises. Publishing to a silently-invented topic would deliver to nobody and
look, from the publisher's side, exactly like success.
"""

from __future__ import annotations

__all__ = ["MQTT_SUFFIX", "topic_for", "wildcard_for"]

MQTT_SUFFIX: dict[str, str] = {
    "measurement.sample": "sample",
    "measurement.event": "event",
    "calibration.state": "calibration",
    "calibration.drift_detected": "calibration",
    "calibration.profile_activated": "calibration",
    "system.metric": "metric",
    "system.incident": "incident",
}


def topic_for(station_id: str, schema_topic: str) -> str:
    try:
        suffix = MQTT_SUFFIX[schema_topic]
    except KeyError as exc:
        raise KeyError(
            f"unknown schema topic {schema_topic!r}; known topics are {sorted(MQTT_SUFFIX)}"
        ) from exc
    return f"edge/{station_id}/{suffix}"


def wildcard_for(station_id: str = "+") -> str:
    """Subscription covering every stream from one station, or from all of them."""
    return f"edge/{station_id}/#"
