"""Importing a multichannel CSV export into the drop-in schema.

Written against the first real recording, whose layout is what a Dewetron/DEWESoft-family logger
emits: four metadata rows of repeated ``key;value`` pairs, then one ``(time, value)`` **column pair
per channel**, semicolon-delimited, with a decimal comma and a UTF-8 BOM.

    Timestamp;9. 2. 2026 9:38:25;Timestamp;9. 2. 2026 9:38:25;...
    Interval;4E-05;Interval;4E-05;...
    Channel name;"Temp1";Channel name;"Temp2";Channel name;"Tenzo1";Channel name;"Tenzo2"
    Unit;"degC";Unit;"degC";Unit;"eps";Unit;"eps"
    0;22,9248;0;23,0700;0;0,00011057;0;0,00012124

Three decisions this module makes explicit rather than silently, because each one could corrupt
every downstream number if it were wrong and invisible:

**The source timestamp has no timezone.** ``9. 2. 2026 9:38:25`` is naive local time. Guessing UTC
would shift the whole recording by an hour and nothing downstream could detect it. The assumed zone
is a parameter, defaults to ``Europe/Bratislava``, is written into ``run.yaml`` as
``timezone_assumed``, and is printed on import so a wrong assumption is visible immediately.

**Strain is stored as strain.** The logger exported a physical quantity; converting it to mV/V at
import would discard the instrument's own numbers and bake a gauge-factor assumption into the data
file. ``raw_value_kind: strain`` plus ``gauge_factor`` lets the conversion happen at the
``ReplaySource`` boundary, where it is one line and reversible.

**Temperature channels are folded into the strain rows they belong to.** They share a time grid, so
carrying each strain channel's paired temperature in ``temperature_c`` is exact and halves the file.
The pairing is by ordinal position within kind -- first temperature channel to first strain channel
-- which is a guess about the wiring. It is recorded in ``run.yaml`` and can be overridden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

__all__ = ["ChannelSpec", "CsvHeader", "import_csv", "parse_header"]

#: Units that identify a channel's role, matched **exactly** after stripping quotes, whitespace, the
#: degree sign and case. Substring matching would be a trap: "counts" contains "c" and would become
#: a temperature channel. An unrecognised unit becomes ``auxiliary`` and is reported, which is the
#: safe direction -- a channel wrongly ignored is visible, a channel wrongly used is not.
_ROLE_BY_UNIT: dict[str, str] = {
    "c": "temperature",
    "degc": "temperature",
    "celsius": "temperature",
    "k": "temperature",
    "ε": "strain",
    "eps": "strain",
    "epsilon": "strain",
    "strain": "strain",
    "ue": "strain",
    "µε": "strain",
    "mv/v": "strain",
    "v/v": "strain",
}

_TIMESTAMP_PATTERNS = (
    "%d. %m. %Y %H:%M:%S",  # 9. 2. 2026 9:38:25   (Slovak/Czech)
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    name: str
    unit: str
    role: str
    time_column: int
    value_column: int


@dataclass(frozen=True, slots=True)
class CsvHeader:
    start_time_local: datetime
    interval_s: float
    channels: tuple[ChannelSpec, ...]
    raw_rows: tuple[str, ...] = field(default=(), repr=False)

    @property
    def sample_rate_hz(self) -> float:
        """Declared rate, snapped to an integer when the interval implies one.

        ``1 / 4e-05`` is 24999.999999999996 in binary floating point. Writing that into ``run.yaml``
        would make every consumer's "does the median interval match the declared rate" check
        marginally wrong and would look like an instrument quirk rather than arithmetic.
        """
        rate = 1.0 / self.interval_s
        return float(round(rate)) if abs(rate - round(rate)) < 1e-6 * max(rate, 1.0) else rate

    def by_role(self, role: str) -> list[ChannelSpec]:
        return [c for c in self.channels if c.role == role]


def _clean(cell: str) -> str:
    return cell.strip().strip('"').strip()


def _role_for(unit: str) -> str:
    u = _clean(unit).lower().replace("°", "").replace(" ", "")
    return _ROLE_BY_UNIT.get(u, "auxiliary")


def _parse_timestamp(text: str) -> datetime:
    text = re.sub(r"\s+", " ", _clean(text))
    for pattern in _TIMESTAMP_PATTERNS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(
        f"cannot parse the export's timestamp {text!r}. Add its format to _TIMESTAMP_PATTERNS "
        "rather than guessing -- a misread date silently misplaces the whole recording"
    )


def parse_header(path: Path, *, sep: str = ";") -> CsvHeader:
    """Read the four metadata rows and work out what channels the file holds."""
    with Path(path).open("r", encoding="utf-8-sig") as fh:
        rows = [fh.readline().rstrip("\n\r") for _ in range(4)]
    if not rows[0].startswith("Timestamp"):
        raise ValueError(
            f"{path.name}: expected the first row to start with 'Timestamp', got {rows[0][:40]!r}. "
            "This importer targets the Dewetron-family layout documented in its module docstring"
        )

    cells = [row.split(sep) for row in rows]
    labels, values = [], []
    for i in range(0, len(cells[2]) - 1, 2):
        labels.append(_clean(cells[2][i + 1]))
        values.append(_clean(cells[3][i + 1]) if i + 1 < len(cells[3]) else "")

    channels = tuple(
        ChannelSpec(
            name=name,
            unit=unit,
            role=_role_for(unit),
            time_column=2 * idx,
            value_column=2 * idx + 1,
        )
        for idx, (name, unit) in enumerate(zip(labels, values, strict=True))
    )
    if not channels:
        raise ValueError(f"{path.name}: no channels found in the header")

    interval = float(_clean(cells[1][1]).replace(",", "."))
    if not np.isfinite(interval) or interval <= 0:
        raise ValueError(f"{path.name}: bad Interval {interval!r}")

    return CsvHeader(
        start_time_local=_parse_timestamp(cells[0][1]),
        interval_s=interval,
        channels=channels,
        raw_rows=tuple(rows),
    )


@dataclass(frozen=True, slots=True)
class ImportResult:
    run_dir: Path
    header: CsvHeader
    sample_rows: int
    strain_channels: tuple[str, ...]
    start_time_utc: datetime
    duration_s: float
    pairing: dict[str, str | None]


def import_csv(
    src: Path,
    run_dir: Path,
    *,
    station_id: str,
    gauge_factor: float | None = None,
    excitation_v: float | None = None,
    bridge: str | None = None,
    timezone: str = "Europe/Bratislava",
    sep: str = ";",
    notes: str = "",
    pair_temperature: bool = True,
) -> ImportResult:
    """Convert one export into ``run_dir`` in the drop-in schema.

    Only channels whose unit identifies them as strain become rows. Everything else is documented in
    ``run.yaml`` and, for temperature, folded into its paired strain channel's ``temperature_c``.
    """
    src, run_dir = Path(src), Path(run_dir)
    header = parse_header(src, sep=sep)
    strain = header.by_role("strain")
    if not strain:
        raise ValueError(
            f"{src.name}: no strain channels found. Units seen: "
            f"{sorted({c.unit for c in header.channels})}"
        )
    temps = header.by_role("temperature")

    # `names` is applied to the selected columns in ASCENDING FILE ORDER, not in the order
    # `usecols` lists them. Passing an unsorted usecols with a matching-order names list silently
    # transposes the mapping: it left Tenzo1 carrying Temp2's readings and Tenzo2 carrying the time
    # column, and only showed up as a negative duration. Sort both, together.
    usecols = sorted({strain[0].time_column, *(c.value_column for c in header.channels)})
    frame = pd.read_csv(
        src,
        sep=sep,
        decimal=",",
        skiprows=4,
        header=None,
        usecols=usecols,
        names=[f"c{i}" for i in usecols],
        dtype=np.float64,
        engine="c",
        encoding="utf-8-sig",
    )

    t_rel = frame[f"c{strain[0].time_column}"].to_numpy()
    if t_rel.size > 1:
        step = float(np.median(np.diff(t_rel)))
        if not (0.0 < step and abs(step - header.interval_s) < 0.05 * header.interval_s):
            raise ValueError(
                f"{src.name}: column {strain[0].time_column} does not look like a time axis -- "
                f"median step {step:.6g} s against a declared interval of {header.interval_s:.6g} s. "
                "Column mapping is wrong; refusing to import rather than write scrambled channels"
            )

    zone = ZoneInfo(timezone)
    start_utc = header.start_time_local.replace(tzinfo=zone)
    start_us = int(round(start_utc.timestamp() * 1e6))
    # Timestamps are built from the declared interval and the sample index, not from the file's own
    # relative-time column: that column is a float in seconds and loses microsecond exactness after
    # a few minutes, while the index cannot.
    ts_us = start_us + np.rint(np.arange(t_rel.size) * header.interval_s * 1e6).astype(np.int64)

    pairing: dict[str, str | None] = {}
    blocks = []
    for idx, ch in enumerate(strain):
        partner = temps[idx] if pair_temperature and idx < len(temps) else None
        pairing[ch.name] = partner.name if partner else None
        blocks.append(
            {
                "ts": ts_us,
                "channel_id": pa.array([ch.name] * t_rel.size, pa.string()),
                "raw_value": frame[f"c{ch.value_column}"].to_numpy(),
                "temperature_c": (
                    frame[f"c{partner.value_column}"].to_numpy()
                    if partner
                    else np.full(t_rel.size, np.nan)
                ),
            }
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    table = pa.concat_tables([pa.table(b) for b in blocks])
    pq.write_table(
        table, run_dir / "samples.parquet", compression="zstd", compression_level=3, version="2.6"
    )

    channel_map: dict[str, dict] = {}
    for ch in header.channels:
        entry: dict[str, object] = {"sensor_id": ch.name, "role": ch.role, "unit": ch.unit}
        if ch.role == "strain":
            entry["lane"] = 1
            entry["paired_temperature"] = pairing.get(ch.name)
            entry["in_samples"] = True
        else:
            entry["in_samples"] = False
        channel_map[ch.name] = entry

    duration = float(t_rel[-1] - t_rel[0]) if t_rel.size > 1 else 0.0
    run_yaml: dict[str, object] = {
        "station_id": station_id,
        "sample_rate_hz": header.sample_rate_hz,
        "raw_value_kind": "strain",
        "channel_map": channel_map,
        "start_time": start_utc.isoformat(),
        "timezone_assumed": timezone,
        "notes": (
            f"Imported from {src.name} by `wimsim import-csv`. "
            f"Source timestamp '{header.start_time_local:%Y-%m-%d %H:%M:%S}' is naive local time and "
            f"was interpreted as {timezone}; if that is wrong every timestamp here is wrong by the "
            f"offset. Temperature channels are not stored as rows: each strain channel carries its "
            f"paired probe in temperature_c, paired by ordinal position "
            f"({', '.join(f'{k}<-{v}' for k, v in pairing.items())}), which is a guess about the "
            f"wiring. No adc_range is declared because the export is a physical quantity, so "
            f"saturation cannot be checked." + (f" {notes}" if notes else "")
        ),
    }
    if gauge_factor is not None:
        run_yaml["gauge_factor"] = gauge_factor
    if excitation_v is not None:
        run_yaml["excitation_v"] = excitation_v
    if bridge is not None:
        run_yaml["bridge"] = bridge

    (run_dir / "run.yaml").write_text(
        yaml.safe_dump(run_yaml, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    return ImportResult(
        run_dir=run_dir,
        header=header,
        sample_rows=table.num_rows,
        strain_channels=tuple(c.name for c in strain),
        start_time_utc=start_utc,
        duration_s=duration,
        pairing=pairing,
    )
