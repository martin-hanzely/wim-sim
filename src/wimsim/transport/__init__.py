"""Transport: getting events off the station without losing any.

The publisher owns a persistent, ordered spool and only acknowledges what the broker confirms. It
talks to a ``Transport``, never to paho directly, so the failure paths that matter -- outage,
partial delivery, restart mid-backlog -- are testable without a broker.

Kafka/Redpanda is explicitly deferred to phase 6 (buildspec section 13: "do not implement Kafka
before phase 6").
"""

from wimsim.transport.base import InMemoryTransport, Transport, TransportError
from wimsim.transport.publisher import Publisher
from wimsim.transport.queue import PersistentQueue, QueuedMessage
from wimsim.transport.topics import topic_for, wildcard_for

__all__ = [
    "InMemoryTransport",
    "PersistentQueue",
    "Publisher",
    "QueuedMessage",
    "Transport",
    "TransportError",
    "topic_for",
    "wildcard_for",
]
