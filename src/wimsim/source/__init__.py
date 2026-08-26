"""Source adapters: one interface, three origins.

``SyntheticSource`` drives the generator, ``ReplaySource`` reads recorded passes, ``SerialSource``
is the hardware-in-the-loop stub. Everything downstream of this package is written once.
"""

from wimsim.source.base import BaseSource, SourceAdapter
from wimsim.source.real_schema import ValidationReport, validate_run
from wimsim.source.replay import ReplaySource
from wimsim.source.serial import SerialSource
from wimsim.source.synthetic import SyntheticSource

__all__ = [
    "BaseSource",
    "ReplaySource",
    "SerialSource",
    "SourceAdapter",
    "SyntheticSource",
    "ValidationReport",
    "validate_run",
]
