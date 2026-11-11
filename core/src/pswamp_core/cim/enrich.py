# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``CimEnricher``: every PMU frame says which grid it is about, and which Analog each column measures.

A source knows its channels by label (a station, a channel, a measurement); the grid knows its
PMU measurements by where they are (``measurements.measurement_table``). The enricher matches the
two once per layout and puts the result on the header: ``cimReferenceId``, the grid's model id, and
``analog``, one Analog mRID per column, ``None`` where nothing matches. A module then reaches the
grid from a value in one call.

Each column has an Analog of its own: a voltage's magnitude (``V`` / ``V_Magnitude``) and angle
(``V_Angle``), a frequency (``f``) and its rate of change (``df``), a current's magnitude and angle on
channel ``I_<line>``, at the end of that line at the station. A station is ``<substation>_<kV>``, or
the substation's name alone when it has one voltage level; a substation with more than one named
alone matches the one level whose PMU measures that, if there is exactly one. A source whose
stations are named otherwise (the Nordic 44 recordings say 3000, 5100...) is given an alias per
station, ``PSWAMP_CIM_STATIONS=3000=FORSMARK_420,...``. A frame that already carries its Analogs
(the RT sim's) passes as it is.

Nothing is read from the store on the event loop: ``start`` reads the model id and every PMU
measurement in a thread, once per process (every run's enricher shares it), waiting up to ``wait``
seconds for it; frames that come sooner flow as they are, and frames are enriched from the moment
it is read.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from collections.abc import Mapping

from pswamp_models.common import DataModel
from pswamp_models.pmu import PmuFrame, PmuHeader

from ..enrich import Enricher
from ..log import get_logger
from .settings import CimSettings

__all__ = ["CimEnricher", "PmuKey", "column_analogs", "pmu_index"]

logger = get_logger("pswamp_core.cim")

#: Where a PMU column is in the grid: ``(station, quantity, line)``; ``quantity`` is one of
#: ``measurement_table``'s (``V``, ``V_angle``, ``F``, ``ROCOF``, ``I``, ``I_angle``), ``line`` a
#: current's line name (whitespace as ``_``), ``None`` otherwise.
PmuKey = tuple[str, str, str | None]

_AT_NODE = ("V", "V_angle", "F", "ROCOF")


def _part(text: object) -> str:
    return re.sub(r"\s+", "_", str(text).strip())


def pmu_index(table) -> dict[PmuKey, str]:
    """Every PMU Analog of ``table`` (a ``measurement_table``) by where it measures (``PmuKey``)."""
    pmu = table[(table["source"] == "PMU") & table["station"].notna()]
    single = {
        substation for substation, count in pmu.groupby("substation")["kv"].nunique().items() if count == 1
    }
    index: dict[PmuKey, str] = {}
    for row in pmu.itertuples():
        if row.quantity in _AT_NODE:
            index.setdefault((row.station, row.quantity, None), row.mRID)
            if row.substation in single:
                index.setdefault((_part(row.substation_name), row.quantity, None), row.mRID)
        elif row.quantity in ("I", "I_angle") and isinstance(row.equipment_name, str):
            index.setdefault((row.station, row.quantity, _part(row.equipment_name)), row.mRID)
            if row.substation in single:
                index.setdefault((_part(row.substation_name), row.quantity, _part(row.equipment_name)), row.mRID)
    return index


def _quantity(channel: str, measurement: str) -> tuple[str, str | None] | None:
    """What a column measures, ``(quantity, line)``, from its labels; ``None`` if not one of them."""
    angle = measurement.lower().endswith("angle")
    if measurement == "df":
        return "ROCOF", None
    if measurement == "f" or channel.lower() in ("f", "frequency"):
        return "F", None
    if channel.startswith("I_"):
        return ("I_angle" if angle else "I"), _part(channel[2:])
    if channel == "V" or measurement.startswith("V_"):
        return ("V_angle" if angle else "V"), None
    return None


def column_analogs(header: PmuHeader, index: Mapping[PmuKey, str], stations: Mapping[str, str] | None = None) -> list[str | None]:
    """The Analog mRID of each of ``header``'s columns (see the module), from ``index`` (``pmu_index``)."""
    stations = stations or {}
    found: dict[PmuKey, str | None] = {}
    analogs: list[str | None] = []
    for station, channel, measurement in zip(header.station, header.channel, header.measurement, strict=True):
        what = _quantity(channel, measurement)
        if what is None:
            analogs.append(None)
            continue
        key = (_part(stations.get(station, station)), *what)
        if key not in found:
            found[key] = _lookup(key, index)
        analogs.append(found[key])
    return analogs


def _lookup(key: PmuKey, index: Mapping[PmuKey, str]) -> str | None:
    exact = index.get(key)
    if exact is not None:
        return exact
    station, quantity, line = key
    matches = {m for (s, q, n), m in index.items() if q == quantity and n == line and s.startswith(f"{station}_")}
    return matches.pop() if len(matches) == 1 else None


def stations_from_env() -> dict[str, str]:
    """``PSWAMP_CIM_STATIONS``: ``label=alias,...``, the station (``<substation>_<kV>``, or a substation with one level) per label."""
    pairs = (item.partition("=") for item in os.environ.get("PSWAMP_CIM_STATIONS", "").split(","))
    return {label.strip(): alias.strip() for label, _, alias in pairs if label.strip() and alias.strip()}


_read: dict[CimSettings, tuple[str | None, dict[PmuKey, str]]] = {}
_read_lock = threading.Lock()


def _grid_index(settings: CimSettings) -> tuple[str | None, dict[PmuKey, str]]:
    """The grid's model id and its PMU Analogs by where they measure, read once per process and settings."""
    from .measurements import measurement_table
    from .store import connect_reader, model_id, open_store

    with _read_lock:
        if settings not in _read:
            reader = connect_reader(settings)
            _read[settings] = model_id(open_store(settings)), pmu_index(measurement_table(reader))
        return _read[settings]


class CimEnricher(Enricher):
    """See the module. ``settings`` and ``stations`` default to the environment's."""

    def __init__(
        self, settings: CimSettings | None = None, stations: Mapping[str, str] | None = None, *, wait: float = 20.0
    ) -> None:
        self.settings = settings
        self.stations = dict(stations) if stations is not None else stations_from_env()
        self.wait = wait
        #: The grid's model id and its PMU Analogs by where they measure, once read.
        self.reference: str | None = None
        self.index: dict[PmuKey, str] | None = None
        self._loading: asyncio.Task | None = None
        self._headers: dict[str, PmuHeader] = {}

    async def start(self) -> None:
        if self.index is not None:
            return
        if self._loading is None:
            self._loading = asyncio.ensure_future(asyncio.to_thread(self._load))
        try:
            await asyncio.wait_for(asyncio.shield(self._loading), self.wait)
        except TimeoutError:
            logger.info("still reading the CIM graph: frames are tied to it once it is read")

    async def ready(self) -> None:
        """Wait for the grid to be read (for a script or a test)."""
        await self.start()
        await asyncio.shield(self._loading)

    def _load(self) -> None:
        try:
            self.reference, self.index = _grid_index(self.settings or CimSettings.from_env())
            logger.info("frames are tied to grid %s: %d PMU measurements", self.reference, len(self.index))
        except Exception as error:  # a grid that cannot be read leaves the frames as they are
            logger.warning("the CIM graph cannot be read, frames carry no CIM reference: %s", error)
            self.index = {}

    def enrich(self, record: DataModel) -> DataModel:
        if not isinstance(record, PmuFrame) or self.index is None:
            return record
        header = record.header
        enriched = self._headers.get(header.header_id)
        if enriched is None:
            enriched = self._headers[header.header_id] = self._enrich(header)
        return record if enriched is header else record.model_copy(update={"header": enriched})

    def _enrich(self, header: PmuHeader) -> PmuHeader:
        update: dict = {}
        if header.cimReferenceId is None and self.reference is not None:
            update["cimReferenceId"] = self.reference
        if header.analog is None and self.index:
            analogs = column_analogs(header, self.index, self.stations)
            if any(analogs):
                update["analog"] = analogs
        return header.model_copy(update=update) if update else header
