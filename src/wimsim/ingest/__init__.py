"""Ingest: broker to database, with a dead-letter queue in between.

Validation and dispatch (``router``) are separated from the subscription (``consumer``) so that
every malformed-input case is testable without a broker. Nothing reaches the database unvalidated,
and nothing is silently discarded.
"""

from wimsim.ingest.consumer import IngestConsumer, IngestStats
from wimsim.ingest.router import REASONS, Rejection, RoutedPayload, Router

__all__ = ["REASONS", "IngestConsumer", "IngestStats", "Rejection", "RoutedPayload", "Router"]
