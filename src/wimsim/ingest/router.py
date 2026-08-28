"""Validation and dispatch: deciding what a received payload is, or why it is not acceptable.

Separated from the MQTT subscription on purpose. This half is pure -- bytes in, a validated model or
a rejection out -- so every malformed-input case can be tested without a broker, and the subscriber
below it has nothing to decide.

**Nothing reaches the database unvalidated.** A payload that fails is not dropped and not
best-effort repaired: it goes to the dead-letter queue with a reason code and its bytes intact. A
pipeline that silently discards what it cannot parse looks identical, from the outside, to one that
is working.

**The topic is a hint, not the answer.** MQTT topics are a routing convenience and a producer can
publish anything anywhere; the payload's own ``topic`` field is what decides which model validates
it, and a disagreement between the two is itself a rejection rather than something to resolve by
preferring one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from wimsim.core.schemas import TOPIC_MODELS
from wimsim.transport.topics import MQTT_SUFFIX

__all__ = ["REASONS", "Rejection", "RoutedPayload", "Router"]

#: Reason codes. Fixed strings rather than free text so a dashboard can group by them, which is the
#: difference between "the DLQ is filling up" and "the DLQ is filling up with malformed_json from
#: one station since 14:20".
REASONS = (
    "invalid_utf8",
    "invalid_json",
    "not_an_object",
    "missing_topic",
    "unknown_topic",
    "topic_mismatch",
    "schema_validation_failed",
)


@dataclass(frozen=True, slots=True)
class RoutedPayload:
    schema_topic: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: str
    detail: str


class Router:
    def __init__(self, *, strict_topic: bool = True) -> None:
        #: When true, an MQTT topic that disagrees with the payload's own topic is a rejection.
        #: Turning it off is for consuming someone else's bridge, not for making warnings go away.
        self.strict_topic = strict_topic

    def route(self, mqtt_topic: str, raw: bytes) -> RoutedPayload | Rejection:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return Rejection("invalid_utf8", str(exc))

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return Rejection("invalid_json", f"{exc.msg} at position {exc.pos}")

        if not isinstance(payload, dict):
            return Rejection("not_an_object", f"top level is {type(payload).__name__}")

        schema_topic = payload.get("topic")
        if not schema_topic:
            return Rejection("missing_topic", "payload has no 'topic' field")

        model = TOPIC_MODELS.get(schema_topic)
        if model is None:
            return Rejection("unknown_topic", f"{schema_topic!r} is not a known event type")

        if self.strict_topic:
            expected = MQTT_SUFFIX.get(schema_topic)
            actual = mqtt_topic.rsplit("/", 1)[-1] if "/" in mqtt_topic else mqtt_topic
            if expected and actual != expected:
                return Rejection(
                    "topic_mismatch",
                    f"payload says {schema_topic!r} (-> .../{expected}) but it arrived on "
                    f"{mqtt_topic!r}",
                )

        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            where = ".".join(str(p) for p in first.get("loc", ()))
            return Rejection(
                "schema_validation_failed",
                f"{where or '<root>'}: {first.get('msg', 'invalid')} ({exc.error_count()} errors)",
            )

        return RoutedPayload(schema_topic, validated.model_dump(mode="json"))
