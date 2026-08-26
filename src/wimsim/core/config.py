"""Configuration models and loading.

Two YAML documents describe a run:

* a **station** (``configs/stations/*.yaml``) -- the physical installation: sensor sensitivity, ADC,
  thermal time constant. Changing the station means you are modelling a different site.
* a **scenario** (``configs/scenarios/*.yaml``) -- what happens during the run: how long, what
  traffic, how the baseline drifts, what faults are injected.

They compose into a :class:`RunConfig`, which is hashed to a ``config_hash`` that appears in every
artifact and every emitted event (principle 3).

A third, independent document describes how the *edge* processes whatever it is given:

* an **edge config** (``configs/estimators/*.yaml``) -- filter chain, zero-line tracking, detector
  thresholds, which feature drives mass, which estimator. Separate from the run on purpose: the
  same pipeline settings must be applicable to a synthetic scenario and to a replayed recording,
  and an experiment sweeps scenario against pipeline as two independent axes.

Everything is a pydantic model with ``extra="forbid"``: a typo in a YAML key is an error, never a
silently ignored setting.

Units are stated in every field description and are the *sensor units* declared by the station
(``adc.unit``, by default mV/V -- the natural output of a strain-gauge bridge). The simulator is
unit-agnostic; it only requires that ``sensor.k0``, ADC range, drift and noise all speak the same
unit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "CONFIG_ROOT",
    "DetectConfig",
    "EdgeConfig",
    "EstimateConfig",
    "PreprocessConfig",
    "RunConfig",
    "ScenarioConfig",
    "StationConfig",
    "config_hash",
    "load_edge_config",
    "load_run_config",
]

CONFIG_ROOT = Path(__file__).resolve().parents[3] / "configs"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------------------------
# Station
# --------------------------------------------------------------------------------------------


class AdcConfig(_Base):
    bits: int = Field(16, ge=8, le=32, description="ADC resolution.")
    range_min: float = Field(-0.5, description="Lower end of the input range, in `unit`.")
    range_max: float = Field(3.0, description="Upper end of the input range, in `unit`.")
    unit: str = Field("mV/V", description="Physical unit of the analog signal. Labelling only.")

    @model_validator(mode="after")
    def _ordered(self) -> AdcConfig:
        if self.range_max <= self.range_min:
            raise ValueError("adc.range_max must exceed adc.range_min")
        return self

    @property
    def levels(self) -> int:
        return 1 << self.bits

    @property
    def lsb(self) -> float:
        return (self.range_max - self.range_min) / (self.levels - 1)


class SensorConfig(_Base):
    k0: float = Field(
        2.0e-4,
        gt=0,
        description="Nominal sensitivity at T_ref, in sensor units per kg of axle load. "
        "Default: a 10 t axle produces 2.0 mV/V, i.e. bridge full scale.",
    )
    alpha0_per_c: float = Field(
        -2.0e-4,
        description="Initial relative temperature coefficient of sensitivity, 1/degC "
        "(-2e-4 = -200 ppm/degC). This is what the controller must track.",
    )
    alpha_walk_sigma_per_sqrt_s: float = Field(
        0.0,
        ge=0,
        description="Random-walk rate of alpha itself, in (1/degC) per sqrt(s). Non-zero makes the "
        "plant genuinely time-varying rather than merely temperature-dependent.",
    )
    t_ref_c: float = Field(20.0, description="Reference temperature at which k == k0, degC.")
    contact_patch_m: float = Field(
        0.22,
        gt=0,
        description="Tyre contact-patch length along the direction of travel, m. With the "
        "sensor treated as a line, this sets the pulse width: FWHM = contact_patch / speed.",
    )


class ThermalConfig(_Base):
    tau_thermal_s: float = Field(
        1800.0,
        gt=0,
        description="First-order lag between ambient air and sensor body temperature, s. The lag "
        "is the reason instantaneous ambient-temperature compensation underperforms.",
    )
    t_sensor_init_c: float | None = Field(
        None,
        description="Initial sensor temperature, degC. None = start at ambient (no transient).",
    )


class TemperatureProbeConfig(_Base):
    """The temperature the *station* reports.

    Not the true sensor temperature. A real probe sits somewhere near the sensor, not inside it, so
    it has its own lag, its own calibration offset and its own noise. Compensation algorithms only
    ever see this signal, which is precisely why perfect temperature compensation is unavailable
    even in simulation.
    """

    enabled: bool = True
    lag_s: float = Field(
        120.0,
        ge=0,
        description="Additional first-order lag of the probe behind the sensor body, s.",
    )
    offset_c: float = Field(0.0, description="Systematic calibration error of the probe, degC.")
    noise_sigma_c: float = Field(0.05, ge=0, description="Probe readout noise, degC.")
    resolution_c: float = Field(
        0.0625, ge=0, description="Probe quantisation step, degC. 0 disables quantisation."
    )


class StationConfig(_Base):
    station_id: str = "ST-DEMO-01"
    sensor_id: str = "S1"
    description: str = ""
    sample_rate_hz: float = Field(2000.0, gt=0, description="Acquisition rate, Hz.")
    lane_count: int = Field(1, ge=1, description="Reserved; phase 1 models a single lane.")
    adc: AdcConfig = AdcConfig()
    sensor: SensorConfig = SensorConfig()
    thermal: ThermalConfig = ThermalConfig()
    temperature_probe: TemperatureProbeConfig = TemperatureProbeConfig()


# --------------------------------------------------------------------------------------------
# Scenario -- traffic
# --------------------------------------------------------------------------------------------


class AxleLoadSpec(_Base):
    mean_kg: float = Field(..., gt=0, description="Mean static load on this axle, kg.")
    cv: float = Field(0.15, ge=0, description="Coefficient of variation (sigma/mean), lognormal.")


class SpeedSpec(_Base):
    mean_kmh: float = Field(85.0, gt=0)
    std_kmh: float = Field(8.0, ge=0)
    min_kmh: float = Field(20.0, gt=0)
    max_kmh: float = Field(130.0, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> SpeedSpec:
        if self.max_kmh <= self.min_kmh:
            raise ValueError("speed.max_kmh must exceed speed.min_kmh")
        return self


class DynamicLoadSpec(_Base):
    """Vehicle body bounce / pitch.

    The dominant physical error source in real WiM: the *instantaneous* force under an axle is not
    its static load, because the sprung mass oscillates. Modelled as a sinusoidal modulation of the
    static load, coherent across the axles of one vehicle (they share a body), with a random phase
    per pass. The truth log records both the static load (the quantity to be estimated) and the
    applied dynamic load, so this error floor is measurable rather than hidden.
    """

    enabled: bool = False
    amplitude: float = Field(0.06, ge=0, description="Relative amplitude, fraction of static load.")
    freq_hz_mean: float = Field(2.0, gt=0, description="Body-bounce frequency, Hz (typ. 1.5-4).")
    freq_hz_std: float = Field(0.4, ge=0)


class VehicleClass(_Base):
    name: str
    probability: float = Field(..., gt=0, description="Relative weight; normalised across classes.")
    axle_spacing_m: list[float] = Field(
        ..., description="Gaps between consecutive axles, m. Length = axle_count - 1."
    )
    axle_load_kg: list[AxleLoadSpec] = Field(..., min_length=1)
    speed: SpeedSpec = SpeedSpec()
    contact_patch_m: float | None = Field(
        None, description="Override the station's contact patch for this class, m."
    )

    @model_validator(mode="after")
    def _consistent(self) -> VehicleClass:
        if len(self.axle_spacing_m) != len(self.axle_load_kg) - 1:
            raise ValueError(
                f"vehicle class {self.name!r}: axle_spacing_m must have "
                f"{len(self.axle_load_kg) - 1} entries for {len(self.axle_load_kg)} axles"
            )
        if any(s <= 0 for s in self.axle_spacing_m):
            raise ValueError(f"vehicle class {self.name!r}: axle spacings must be positive")
        return self

    @property
    def axle_count(self) -> int:
        return len(self.axle_load_kg)


class TrafficConfig(_Base):
    mode: Literal["poisson", "fixed_interval"] = "poisson"
    rate_per_hour: float = Field(120.0, gt=0, description="Mean arrival rate of vehicles.")
    min_headway_s: float = Field(
        3.0,
        ge=0,
        description="Arrivals closer than this are pushed apart, so pulses stay separable.",
    )
    dynamic_load: DynamicLoadSpec = DynamicLoadSpec()
    classes: list[VehicleClass] = Field(..., min_length=1)


# --------------------------------------------------------------------------------------------
# Scenario -- plant: zero drift, temperature, noise, pulse shape
# --------------------------------------------------------------------------------------------


class StepEvent(_Base):
    t_s: float = Field(..., ge=0, description="Time from run start, s.")
    delta: float = Field(..., description="Additive jump in the zero line, sensor units.")


class ZeroDriftConfig(_Base):
    """q(t): everything that moves the zero line, decomposed so each part is separately loggable."""

    q0: float = Field(0.05, description="Zero-line offset at t=0, sensor units.")
    random_walk_sigma_per_sqrt_s: float = Field(
        0.0, ge=0, description="Brownian drift rate, sensor units per sqrt(s)."
    )
    linear_slope_per_hour: float = Field(0.0, description="Deterministic trend, sensor units/hour.")
    steps: list[StepEvent] = Field(
        default_factory=list, description="Explicit settling jumps at known times."
    )
    step_rate_per_hour: float = Field(
        0.0, ge=0, description="Poisson rate of *random* settling jumps, 1/hour."
    )
    step_magnitude_sigma: float = Field(
        0.01, ge=0, description="Scale of random settling jumps (zero-mean normal), sensor units."
    )
    temp_coupling_per_c: float = Field(
        0.0,
        description="Zero-line shift per degC of sensor temperature above t_ref, sensor units/degC. "
        "Distinct from the gain's temperature coefficient: this one is additive.",
    )


class TemperatureConfig(_Base):
    mean_c: float = Field(15.0, description="Daily-mean ambient temperature, degC.")
    daily_amplitude_c: float = Field(8.0, ge=0, description="Half peak-to-peak daily swing, degC.")
    peak_hour_utc: float = Field(
        15.0, ge=0, lt=24, description="Hour of day at which ambient peaks (UTC)."
    )
    trend_c_per_day: float = Field(0.0, description="Slow seasonal/weather trend, degC/day.")
    noise_sigma_c: float = Field(0.3, ge=0, description="Stationary sd of weather noise, degC.")
    noise_tau_s: float = Field(
        600.0, gt=0, description="Correlation time of weather noise (OU process), s."
    )


class MainsConfig(_Base):
    enabled: bool = False
    freq_hz: float = Field(50.0, gt=0)
    amplitude: float = Field(1e-4, ge=0, description="Fundamental amplitude, sensor units.")
    harmonics: list[float] = Field(
        default_factory=lambda: [0.3, 0.1],
        description="Amplitudes of the 2nd, 3rd, ... harmonics relative to the fundamental.",
    )


class NoiseConfig(_Base):
    white_sigma: float = Field(
        2.0e-4,
        ge=0,
        description="Gaussian noise sd *per sample*, sensor units. The implied PSD therefore "
        "depends on the station sample rate; see docs/signal-model.md.",
    )
    pink_sigma: float = Field(
        1.0e-4, ge=0, description="Total sd of the 1/f component over its band, sensor units."
    )
    pink_f_min_hz: float = Field(
        1.0e-3, gt=0, description="Lower edge of the 1/f band; below it the spectrum flattens."
    )
    pink_f_max_hz: float = Field(
        20.0, gt=0, description="Upper edge of the 1/f band; above it white noise dominates anyway."
    )
    mains: MainsConfig = MainsConfig()


class PulseConfig(_Base):
    shape: Literal["gaussian", "emg", "ringing"] = "gaussian"
    emg_tau_ratio: float = Field(
        0.6,
        gt=0,
        description="Exponential tail time constant as a multiple of the FWHM (emg only).",
    )
    ring_freq_hz: float = Field(
        60.0, gt=0, description="Structural ringing frequency, Hz (ringing only)."
    )
    ring_damping: float = Field(
        0.12, gt=0, le=1, description="Damping ratio zeta of the ringing (ringing only)."
    )
    ring_amplitude: float = Field(
        0.25, ge=0, description="Ringing amplitude relative to the main pulse (ringing only)."
    )
    support_widths: float = Field(
        8.0, gt=0, description="Pulse is evaluated over +/- this many FWHM around its centre."
    )


# --------------------------------------------------------------------------------------------
# Scenario -- faults
# --------------------------------------------------------------------------------------------


class _Fault(_Base):
    label: str = Field(..., description="Short name; appears verbatim in the truth log.")


class GainInstabilityFault(_Fault):
    """Amplifier misbehaving: k is multiplied by a factor over an interval."""

    type: Literal["gain_instability"] = "gain_instability"
    t_start_s: float = Field(..., ge=0)
    duration_s: float | None = Field(None, gt=0, description="None = lasts to end of run.")
    factor: float = Field(..., gt=0, description="Multiplicative change in k.")
    ramp_s: float = Field(0.0, ge=0, description="0 = instantaneous jump; >0 = linear ramp in.")


class SensorDisplacementFault(_Fault):
    """The sensor physically shifted: permanent step in *both* k0 and q."""

    type: Literal["sensor_displacement"] = "sensor_displacement"
    t_s: float = Field(..., ge=0)
    k_factor: float = Field(..., gt=0)
    q_delta: float = Field(..., description="Additive zero-line step, sensor units.")


class ChannelDropoutFault(_Fault):
    """Acquisition failure: the channel stops reporting real values."""

    type: Literal["channel_dropout"] = "channel_dropout"
    t_start_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)
    mode: Literal["stuck", "zero", "saturate_high", "nan"] = "stuck"
    stuck_value: float | None = Field(
        None, description="Value held during a 'stuck' dropout; None = last good sample."
    )


class ClockSkewFault(_Fault):
    """The station clock disagrees with the server: constant offset plus linear drift."""

    type: Literal["clock_skew"] = "clock_skew"
    t_start_s: float = Field(..., ge=0)
    offset_s: float = Field(0.0, description="Immediate step in the station clock, s.")
    drift_ppm: float = Field(0.0, description="Subsequent drift rate, parts per million.")


# Pipeline-level faults. Declared now so the config schema is stable, applied from phase 3.
class ConnectivityLossFault(_Fault):
    type: Literal["connectivity_loss"] = "connectivity_loss"
    t_start_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)


class PublishDelayFault(_Fault):
    type: Literal["publish_delay"] = "publish_delay"
    t_start_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)
    delay_ms: float = Field(..., ge=0)


class MalformedSchemaFault(_Fault):
    type: Literal["malformed_schema"] = "malformed_schema"
    t_start_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)
    fraction: float = Field(0.1, gt=0, le=1.0, description="Share of events emitted malformed.")


class HeartbeatLossFault(_Fault):
    type: Literal["heartbeat_loss"] = "heartbeat_loss"
    t_start_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)


Fault = Annotated[
    GainInstabilityFault
    | SensorDisplacementFault
    | ChannelDropoutFault
    | ClockSkewFault
    | ConnectivityLossFault
    | PublishDelayFault
    | MalformedSchemaFault
    | HeartbeatLossFault,
    Field(discriminator="type"),
]

#: Faults the signal generator knows how to apply. Anything else is a pipeline fault, recorded in
#: the manifest as unapplied until the phase that owns it exists.
SIGNAL_FAULT_TYPES = frozenset(
    {"gain_instability", "sensor_displacement", "channel_dropout", "clock_skew"}
)


# --------------------------------------------------------------------------------------------
# Scenario / run
# --------------------------------------------------------------------------------------------


class OutputConfig(_Base):
    truth_rate_hz: float = Field(
        1.0,
        gt=0,
        description="Rate at which the truth time series is written. The plant state moves on "
        "timescales of minutes; there is no reason to store it at the acquisition rate.",
    )
    samples: Literal["full", "windows", "none"] = Field(
        "windows",
        description="How much of the raw sample stream to persist. 'windows' keeps only the "
        "neighbourhood of each pass (see window_pad_s) and is the sane default for long runs; "
        "'full' is exact but grows at sample_rate * duration.",
    )
    window_pad_s: float = Field(
        2.0,
        gt=0,
        description="Seconds of quiet signal kept either side of a pass in 'windows' mode.",
    )
    max_sample_rows: int = Field(
        50_000_000, gt=0, description="Refuse to write more sample rows than this without --force."
    )


class ReplayConfig(_Base):
    """Where a replay scenario gets its samples. Consumed by ``ReplaySource`` in phase 6."""

    run_dir: str = Field(
        ...,
        description="Directory under data/real/ holding samples.parquet, run.yaml, reference.csv.",
    )
    rate: Literal["true", "accelerated"] = Field(
        "accelerated", description="'true' replays at the recorded wall-clock rate."
    )
    speed_multiplier: float | None = Field(
        None, gt=0, description="Override for 'true' rate: 60.0 replays a minute per second."
    )


class SourceConfig(_Base):
    kind: Literal["synthetic", "replay", "serial"] = "synthetic"
    replay: ReplayConfig | None = None

    @model_validator(mode="after")
    def _replay_configured(self) -> SourceConfig:
        if self.kind == "replay" and self.replay is None:
            raise ValueError("source.kind == 'replay' requires a source.replay block")
        return self


class ScenarioConfig(_Base):
    name: str
    description: str = ""
    source: SourceConfig = SourceConfig()
    duration_s: float = Field(..., gt=0)
    start_time: datetime = Field(
        default_factory=lambda: datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC),
        description="UTC wall-clock time of t=0. Fixed by default: a run's timestamps must not "
        "depend on when it was executed.",
    )
    seed: int = Field(20250601, ge=0)
    block_seconds: float = Field(
        30.0,
        gt=0,
        description="Length of one generation block, in seconds of simulated time. Affects memory "
        "and streaming granularity only: every generated *value* is invariant to it (asserted by "
        "tests/test_determinism.py). The parquet files are not byte-identical across block sizes, "
        "because the block size also sets the row-group layout. Expressed in seconds rather than "
        "samples so that a block boundary lands on a plant-grid point and a truth-log row at "
        "every sample rate.",
    )
    plant_rate_hz: float = Field(
        50.0,
        gt=0,
        description="Rate at which the slow plant state (zero drift, gain, temperature, 1/f noise) "
        "is integrated before linear interpolation onto the sample grid. These processes have no "
        "content near the acquisition rate, so integrating them there would only cost time. Must "
        "exceed 2.5 * noise.pink_f_max_hz.",
    )
    traffic: TrafficConfig
    zero_drift: ZeroDriftConfig = ZeroDriftConfig()
    temperature: TemperatureConfig = TemperatureConfig()
    noise: NoiseConfig = NoiseConfig()
    pulse: PulseConfig = PulseConfig()
    faults: list[Fault] = Field(default_factory=list)
    output: OutputConfig = OutputConfig()

    @field_validator("start_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def _faults_in_range(self) -> ScenarioConfig:
        for f in self.faults:
            t0 = getattr(f, "t_start_s", None)
            if t0 is None:
                t0 = getattr(f, "t_s", 0.0)
            if t0 > self.duration_s:
                raise ValueError(
                    f"fault {f.label!r} starts at t={t0}s, after the run ends at {self.duration_s}s"
                )
        labels = [f.label for f in self.faults]
        if len(labels) != len(set(labels)):
            raise ValueError("fault labels must be unique within a scenario")
        return self

    @model_validator(mode="after")
    def _plant_rate_covers_pink(self) -> ScenarioConfig:
        if self.plant_rate_hz < 2.5 * self.noise.pink_f_max_hz:
            raise ValueError(
                f"plant_rate_hz={self.plant_rate_hz} cannot represent 1/f noise up to "
                f"{self.noise.pink_f_max_hz} Hz; raise plant_rate_hz or lower pink_f_max_hz"
            )
        return self

    @property
    def signal_faults(self) -> list[Any]:
        return [f for f in self.faults if f.type in SIGNAL_FAULT_TYPES]

    @property
    def pipeline_faults(self) -> list[Any]:
        return [f for f in self.faults if f.type not in SIGNAL_FAULT_TYPES]


class RunConfig(_Base):
    """The complete, resolved description of one run. This is what gets hashed."""

    station: StationConfig
    scenario: ScenarioConfig

    @property
    def mode(self) -> str:
        """Where samples come from. Derived, never set independently of the scenario."""
        return self.scenario.source.kind

    @model_validator(mode="after")
    def _rates_consistent(self) -> RunConfig:
        fs = self.station.sample_rate_hz
        sc = self.scenario
        if sc.plant_rate_hz > fs:
            raise ValueError(
                f"plant_rate_hz ({sc.plant_rate_hz}) exceeds the station sample rate ({fs}); "
                "the plant grid must be the coarser of the two"
            )
        # Integer grid ratios are required, not merely convenient: they are what lets a block
        # boundary land on a plant point and a truth point simultaneously, which is what makes
        # the output invariant to block_size.
        for label, rate in (
            ("plant_rate_hz", sc.plant_rate_hz),
            ("output.truth_rate_hz", sc.output.truth_rate_hz),
        ):
            ratio = fs / rate
            if abs(ratio - round(ratio)) > 1e-9:
                raise ValueError(
                    f"sample_rate_hz ({fs}) must be an integer multiple of {label} ({rate}); "
                    f"got a ratio of {ratio}"
                )
        for label, rate in (
            ("sample_rate_hz", fs),
            ("plant_rate_hz", sc.plant_rate_hz),
            ("output.truth_rate_hz", sc.output.truth_rate_hz),
        ):
            ticks = sc.block_seconds * rate
            if abs(ticks - round(ticks)) > 1e-9:
                raise ValueError(
                    f"block_seconds ({sc.block_seconds}) must contain a whole number of {label} "
                    f"ticks; got {ticks}"
                )
        return self

    @property
    def plant_ratio(self) -> int:
        """Sample-grid points per plant-grid point."""
        return round(self.station.sample_rate_hz / self.scenario.plant_rate_hz)

    @property
    def truth_ratio(self) -> int:
        """Sample-grid points per truth-log row."""
        return round(self.station.sample_rate_hz / self.scenario.output.truth_rate_hz)

    @property
    def block_size(self) -> int:
        """Samples per generation block."""
        return round(self.scenario.block_seconds * self.station.sample_rate_hz)

    @property
    def sample_count(self) -> int:
        return int(round(self.scenario.duration_s * self.station.sample_rate_hz))

    def canonical(self) -> str:
        """Stable JSON serialisation. Key order fixed, no whitespace, UTC-normalised datetimes."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def config_hash(cfg: RunConfig) -> str:
    return cfg.config_hash()


# --------------------------------------------------------------------------------------------
# Edge pipeline
# --------------------------------------------------------------------------------------------


class PreprocessConfig(_Base):
    """Filter chain, zero-line tracking and temperature compensation.

    The filter is **causal**. A station cannot look into the future, so zero-phase filtering is not
    on the menu, and the group delay that costs is measured and reported rather than pretended away.
    """

    despike: bool = Field(
        False,
        description="Replace isolated outliers with the local median. Only samples exceeding "
        "despike_threshold robust deviations are touched -- a blanket median filter wide enough to "
        "despike would flatten a 5 ms axle pulse.",
    )
    despike_window: int = Field(
        11,
        ge=3,
        description="Centred median width, samples. Odd. Kept short so it tracks a pulse rather "
        "than flattening it; this sets what a sample is compared *against*, not the noise scale.",
    )
    despike_scale_window_s: float = Field(
        1.0,
        gt=0,
        description="Trailing window over which the channel's noise scale is estimated. Long on "
        "purpose: an 11-sample MAD has enormous variance, and thresholding against it flags "
        "roughly one quiet sample in three hundred as a spike.",
    )
    despike_threshold: float = Field(
        6.0, gt=0, description="Noise scales beyond which a sample is an outlier."
    )

    filter: Literal["none", "moving_average", "butterworth"] = "none"
    window: int = Field(1, ge=1, description="Moving-average width in samples.")
    cutoff_hz: float | None = Field(None, gt=0, description="Butterworth -3 dB corner, Hz.")
    order: int = Field(4, ge=1, le=10, description="Butterworth order.")
    compensate_group_delay: bool = Field(
        True,
        description="Shift the filtered signal back by the chain's DC group delay, so a reported "
        "ts_peak means the time the axle crossed rather than the time the filter noticed. Exact "
        "for a moving average; a DC approximation for Butterworth, whose delay is "
        "frequency-dependent.",
    )

    zero_window_s: float = Field(
        2.0,
        gt=0,
        description="Trailing window over which the zero line is estimated as a median. The median "
        "is unbiased for symmetric noise and immune to vehicles while they occupy less than half "
        "the window -- which is why it is a median and not a mean.",
    )
    zero_update_s: float = Field(
        0.25,
        gt=0,
        description="How often the zero estimate is recomputed. Held constant between updates, so "
        "the estimate at any instant depends only on the past.",
    )
    zero_occupancy_warn: float = Field(
        0.35,
        gt=0,
        lt=0.5,
        description="Flag the zero estimate as suspect once this fraction of the window sits well "
        "above the baseline. Past 0.5 the median stops being the baseline at all.",
    )

    @model_validator(mode="after")
    def _coherent(self) -> PreprocessConfig:
        if self.filter == "butterworth" and self.cutoff_hz is None:
            raise ValueError("filter: butterworth requires cutoff_hz")
        if self.filter == "moving_average" and self.window < 2:
            raise ValueError("filter: moving_average requires window >= 2")
        if self.despike and self.despike_window % 2 == 0:
            raise ValueError("despike_window must be odd so the median has a defined centre")
        if self.zero_update_s > self.zero_window_s:
            raise ValueError("zero_update_s cannot exceed zero_window_s")
        return self


class DetectConfig(_Base):
    """Dual-threshold hysteresis with minimum-duration and refractory constraints.

    Thresholds are in **sensor units above the zero line**, i.e. they apply to the compensated
    signal, so they do not have to be retuned every time the baseline drifts.
    """

    start_threshold: float = Field(
        0.05, gt=0, description="Rise above the zero line that opens a candidate window."
    )
    end_threshold: float = Field(
        0.02,
        gt=0,
        description="Fall below which closes it. Strictly less than start_threshold: that gap is "
        "the hysteresis, and without it noise around one threshold chatters.",
    )
    end_hold_s: float = Field(
        0.002,
        ge=0,
        description="The signal must stay below end_threshold for this long before a window is "
        "considered closed. Without it a single noise sample dipping past the lower threshold "
        "splits one axle into two, which hysteresis alone does not prevent -- it only makes rare.",
    )
    min_duration_s: float = Field(
        0.001, gt=0, description="Windows shorter than this are noise, not axles."
    )
    max_duration_s: float = Field(
        2.0,
        gt=0,
        description="Windows longer than this are a stuck channel or a stopped vehicle, not a pass.",
    )
    refractory_s: float = Field(
        0.0,
        ge=0,
        description="Dead time after a window closes. 0 by default: axles within a bogie are only "
        "milliseconds apart and suppressing them would destroy the axle count.",
    )
    merge_gap_s: float = Field(
        0.6,
        ge=0,
        description="Windows separated by less than this are merged into one vehicle. The default "
        "comes from the traffic, not from taste: the longest axle spacing in the shipped fleet is "
        "6.1 m and the slowest heavy vehicle does 50 km/h, giving 0.44 s, while the minimum "
        "headway between vehicles is 3 s. 0.6 s sits comfortably between the two. Set it to 0 to "
        "emit axle-level events instead of vehicle-level ones.",
    )
    subsample_peak: bool = Field(
        True,
        description="Refine the peak by fitting a parabola through the sample maximum and its "
        "neighbours. Phase 1 measured that discrete peak-picking cannot reach 0.1 % at 2 kHz; this "
        "recovers it and costs three multiplications.",
    )
    area_pad_widths: float = Field(
        1.0,
        ge=0,
        description="Extend the integration window by this multiple of the detected duration on "
        "each side. Integrating only between the threshold crossings truncates the pulse tails, "
        "and by an amount that depends on how far the peak sits above the threshold -- so the bias "
        "would vary with load rather than being a constant the fitted gain could absorb.",
    )


class EstimateConfig(_Base):
    """How a detected window becomes a mass."""

    feature: Literal["peak", "area"] = Field(
        "peak",
        description="Which detector feature drives the estimate. Peak is speed-invariant; area "
        "averages noise but scales with 1/speed. Which wins is an experimental question -- see "
        "docs/signal-model.md -- so it is a config switch, not a hard-coded choice.",
    )
    axle_summation: Literal["per_axle_sum", "whole_signal"] = Field(
        "whole_signal",
        description="per_axle_sum estimates each axle and adds; whole_signal treats the merged "
        "vehicle window as one measurement.",
    )
    estimator: Literal["static_affine"] = Field(
        "static_affine", description="RLS, Kalman and the residual learner arrive in phase 5."
    )
    coverage_target: float = Field(0.95, gt=0, lt=1)
    bootstrap_passes: int = Field(
        50,
        ge=2,
        description="Reference passes used to fit the initial profile. Phase 2 bootstraps from "
        "truth in an offline calibration split; phase 5 replaces this with the reference-observation "
        "modes.",
    )


class EdgeConfig(_Base):
    """One complete pipeline configuration. Hashed into every event's provenance."""

    name: str
    description: str = ""
    preprocess: PreprocessConfig = PreprocessConfig()
    detect: DetectConfig = DetectConfig()
    estimate: EstimateConfig = EstimateConfig()

    @model_validator(mode="after")
    def _hysteresis_is_a_gap(self) -> EdgeConfig:
        if self.detect.end_threshold >= self.detect.start_threshold:
            raise ValueError(
                f"end_threshold ({self.detect.end_threshold}) must be strictly below "
                f"start_threshold ({self.detect.start_threshold}); equal thresholds are not "
                "hysteresis and will chatter on noise"
            )
        if self.detect.max_duration_s <= self.detect.min_duration_s:
            raise ValueError("max_duration_s must exceed min_duration_s")
        return self

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return data


def _resolve(name_or_path: str, kind: str, root: Path) -> Path:
    """Accept either a bare config name ('S1_nominal') or an explicit path."""
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        return p
    for candidate in (root / kind / f"{name_or_path}.yaml", root / kind / f"{name_or_path}.yml"):
        if candidate.exists():
            return candidate
    available = sorted(x.stem for x in (root / kind).glob("*.y*ml"))
    raise FileNotFoundError(
        f"no {kind[:-1]} config named {name_or_path!r} in {root / kind}. Available: {available}"
    )


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _apply_override(tree: dict[str, Any], dotted: str) -> None:
    """Apply one ``a.b.c=value`` override in place. Value is parsed as YAML."""
    if "=" not in dotted:
        raise ValueError(f"override {dotted!r} must look like path.to.key=value")
    path, raw = dotted.split("=", 1)
    value = yaml.safe_load(raw)
    keys = path.split(".")
    node: Any = tree
    for key in keys[:-1]:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"override path {path!r}: no such key {key!r}")
        node = node[key]
    if not isinstance(node, dict) or keys[-1] not in node:
        raise KeyError(f"override path {path!r}: no such key {keys[-1]!r}")
    node[keys[-1]] = value


def load_run_config(
    scenario: str,
    station: str | None = None,
    *,
    overrides: list[str] | None = None,
    seed: int | None = None,
    root: Path | None = None,
) -> RunConfig:
    """Load and compose a station + scenario into a validated :class:`RunConfig`.

    A scenario may name its station with a top-level ``station:`` key; the ``station`` argument
    overrides it. Scenarios may also inherit with ``extends: <other scenario>``.
    """
    root = root or CONFIG_ROOT
    scenario_path = _resolve(scenario, "scenarios", root)
    raw = _read_yaml(scenario_path)

    # scenario inheritance, one level of extends at a time, cycle-guarded
    seen = {scenario_path.resolve()}
    while "extends" in raw:
        parent_name = raw.pop("extends")
        parent_path = _resolve(parent_name, "scenarios", root)
        if parent_path.resolve() in seen:
            raise ValueError(f"circular 'extends' involving {parent_path}")
        seen.add(parent_path.resolve())
        raw = _deep_merge(_read_yaml(parent_path), raw)

    station_name = station or raw.pop("station", "default")
    raw.pop("station", None)
    station_raw = _read_yaml(_resolve(station_name, "stations", root))

    # A scenario may tweak the installation it runs on without forking the whole station file --
    # e.g. "same site, but its temperature coefficient is ageing". The override is applied here and
    # leaves no trace in the resolved config, so the config hash covers the effective values only.
    station_patch = raw.pop("station_overrides", None)
    if station_patch:
        if not isinstance(station_patch, dict):
            raise ValueError("scenario.station_overrides must be a mapping")
        station_raw = _deep_merge(station_raw, station_patch)

    tree = {"station": station_raw, "scenario": raw}
    for ov in overrides or []:
        _apply_override(tree, ov)
    if seed is not None:
        tree["scenario"]["seed"] = int(seed)

    return RunConfig.model_validate(tree)


def load_edge_config(
    name: str,
    *,
    overrides: list[str] | None = None,
    root: Path | None = None,
) -> EdgeConfig:
    """Load a pipeline configuration from ``configs/estimators/``.

    Independent of :func:`load_run_config` on purpose: the same pipeline settings must apply to a
    synthetic scenario and to a replayed recording, and an experiment sweeps the two axes
    separately.
    """
    root = root or CONFIG_ROOT
    raw = _read_yaml(_resolve(name, "estimators", root))

    seen = {_resolve(name, "estimators", root).resolve()}
    while "extends" in raw:
        parent_name = raw.pop("extends")
        parent_path = _resolve(parent_name, "estimators", root)
        if parent_path.resolve() in seen:
            raise ValueError(f"circular 'extends' involving {parent_path}")
        seen.add(parent_path.resolve())
        raw = _deep_merge(_read_yaml(parent_path), raw)

    tree = {"edge": raw}
    for ov in overrides or []:
        _apply_override(tree, ov)
    return EdgeConfig.model_validate(tree["edge"])
