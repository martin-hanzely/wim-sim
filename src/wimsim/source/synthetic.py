"""``SyntheticSource`` -- drives the generator.

Supports two pacing modes:

``accelerated`` (default)
    As fast as the CPU allows. What experiments use.
``realtime``
    Throttled to wall-clock time, optionally with a speed multiplier, so a demo dashboard fills at
    a watchable rate.

The truth half of every generated block is dropped on the floor here, and that is the whole point:
this class is the membrane between the simulator and the system under test. It holds a reference to
the generator, so ``source.generator.passes`` *is* reachable -- but only by the run writer and the
truth exporter, which are the two components entitled to it. Nothing in ``edge/`` or
``calibration/`` may import this module's package sibling ``wimsim.signal``, and the isolation test
enforces that.
"""

from __future__ import annotations

from collections.abc import Iterator

from wimsim.core.clock import Pacer
from wimsim.core.config import RunConfig
from wimsim.core.types import SampleBlock, SourceMetadata, to_epoch_us
from wimsim.signal.generator import SignalGenerator
from wimsim.source.base import BaseSource

__all__ = ["SyntheticSource"]


class SyntheticSource(BaseSource):
    def __init__(
        self,
        cfg: RunConfig,
        *,
        pacing: str = "accelerated",
        speed_multiplier: float | None = None,
        run_id: str = "",
        generator: SignalGenerator | None = None,
    ) -> None:
        if pacing not in {"accelerated", "realtime"}:
            raise ValueError("pacing must be 'accelerated' or 'realtime'")
        self.cfg = cfg
        self.pacing = pacing
        self.run_id = run_id
        self.generator = generator or SignalGenerator(cfg)
        rate = None if pacing == "accelerated" else (speed_multiplier or 1.0)
        self._pacer = Pacer(rate)

    @property
    def metadata(self) -> SourceMetadata:
        st = self.cfg.station
        return SourceMetadata(
            mode="synthetic",
            sample_rate_hz=st.sample_rate_hz,
            channels=(st.sensor_id,),
            station_id=st.station_id,
            sensor_id=st.sensor_id,
            unit=st.adc.unit,
            adc_bits=st.adc.bits,
            adc_range=(st.adc.range_min, st.adc.range_max),
            start_time_us=to_epoch_us(self.cfg.scenario.start_time),
            run_id=self.run_id,
            extra={
                "scenario": self.cfg.scenario.name,
                "config_hash": self.cfg.config_hash(),
                "seed": self.cfg.scenario.seed,
            },
        )

    def stream_blocks(self) -> Iterator[SampleBlock]:
        for block in self.generator.blocks():
            self._pacer.wait_until(float(block.samples.t_s[-1]))
            yield block.samples
