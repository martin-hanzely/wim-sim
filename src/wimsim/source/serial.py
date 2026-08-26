"""``SerialSource`` -- hardware in the loop. Deliberately unimplemented.

Present, with the full interface, because the interface is the deliverable. When the estimator is
cross-deployed to a Jetson or a Pi reading a real ADC over serial, this is the only file that gets
written, and nothing downstream changes. Leaving a typed stub here is what makes that claim
checkable rather than aspirational.

Implementing it will need: a framing protocol, a hardware timestamp policy (device counter vs.
host arrival time -- they are not the same and the difference is a clock-skew fault by another
name), and a back-pressure policy for when the host cannot keep up.
"""

from __future__ import annotations

from collections.abc import Iterator

from wimsim.core.types import SampleBlock, SourceMetadata
from wimsim.source.base import BaseSource

__all__ = ["SerialSource"]


class SerialSource(BaseSource):
    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 921600,
        sample_rate_hz: float = 2000.0,
        station_id: str = "",
        sensor_id: str = "",
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.sample_rate_hz = sample_rate_hz
        self.station_id = station_id
        self.sensor_id = sensor_id

    @property
    def metadata(self) -> SourceMetadata:
        return SourceMetadata(
            mode="serial",
            sample_rate_hz=self.sample_rate_hz,
            channels=(self.sensor_id or "ch0",),
            station_id=self.station_id,
            sensor_id=self.sensor_id,
            extra={"port": self.port, "baudrate": self.baudrate},
        )

    def stream_blocks(self) -> Iterator[SampleBlock]:
        raise NotImplementedError(
            "SerialSource is a phase-6+ hardware-in-the-loop stub. The interface is fixed; the "
            "framing protocol, timestamp policy and back-pressure policy are not."
        )
