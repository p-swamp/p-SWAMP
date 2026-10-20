# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``CimEnricher``: every PMU frame says which grid it is about, and which Analog each column measures.

A source knows its channels by label (a station, a channel, a measurement); the
grid knows its Analogs by name (``analogs.analog_name``). The enricher matches
the two once per layout and puts the result on the header: ``cimReferenceId``,
the grid's model id, and ``analog``, one Analog mRID per column, ``None`` where
nothing matches. A module then reaches the grid from a value in one call.

A column matches the Analog ``PMU_<station>_<V|F>`` (``_I_<line>`` for a current
channel ``I_<line>``), or, when the station is a substation with more than one
voltage level named, the one whose name starts ``PMU_<station>_`` and ends with
the quantity, if there is exactly one. A source whose stations are named
otherwise (the Nordic 44 recordings say 3000, 5100...) is given an alias per
station, ``PSWAMP_CIM_STATIONS=3000=FORSMARK_420,...``. A frame that already
carries its Analogs (the RT sim's) passes as it is.

Nothing is read from the store on the event loop: ``start`` reads the model id
and every Analog's name in a thread, once per process (every run's enricher
shares it), waiting up to ``wait`` seconds for it; frames that come sooner flow
as they are, and frames are enriched from the moment it is read.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Mapping

from pswamp_models.common import DataModel
from pswamp_models.pmu import PmuFrame, PmuHeader

from ..enrich import Enricher
from ..log import get_logger
from .analogs import _part
from .settings import CimSettings

__all__ = ["CimEnricher", "column_analogs"]

logger = get_logger("pswamp_core.cim")


def _quantity(channel: str, measurement: str) -> tuple[str, str | None] | None:
    """What a column measures, ``("V" | "F" | "I", line)``, from its labels; ``None`` if not one of them."""
    if measurement in ("f", "df") or channel.lower() in ("f", "frequency"):
        return "F", None
    if channel.startswith("I_"):
        return "I", channel[2:]
    if channel == "V" or measurement.startswith("V_"):
        return "V", None
    return None


def column_analogs(header: PmuHeader, index: Mapping[str, str], stations: Mapping[str, str] | None = None) -> list[str | None]:
    """The Analog mRID of each of ``header``'s columns (see the module), from ``index``, name → mRID."""
    stations = stations or {}
    found: dict[tuple[str, str, str | None], str | None] = {}
    analogs: list[str | None] = []
    for station, channel, measurement in zip(header.station, header.channel, header.measurement, strict=True):
        what = _quantity(channel, measurement)
        if what is None:
            analogs.append(None)
            continue
        key = (station, *what)
        if key not in found:
            found[key] = _lookup(_part(stations.get(station, station)), *what, index)
        analogs.append(found[key])
    return analogs


def _lookup(prefix: str, quantity: str, line: str | None, index: Mapping[str, str]) -> str | None:
    suffix = f"_{quantity}" if line is None else f"_I_{_part(line)}"
    exact = index.get(f"PMU_{prefix}{suffix}")
    if exact is not None:
        return exact
    matches = [m for name, m in index.items() if name.startswith(f"PMU_{prefix}_") and name.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def stations_from_env() -> dict[str, str]:
    """``PSWAMP_CIM_STATIONS``: ``label=alias,...``, an Analog name's ``<substation>_<kV>`` per station label."""
    pairs = (item.partition("=") for item in os.environ.get("PSWAMP_CIM_STATIONS", "").split(","))
    return {label.strip(): alias.strip() for label, _, alias in pairs if label.strip() and alias.strip()}


_read: dict[CimSettings, tuple[str | None, dict[str, str]]] = {}
_read_lock = threading.Lock()


def _grid_index(settings: CimSettings) -> tuple[str | None, dict[str, str]]:
    """The grid's model id and its Analogs by name, read once per process and settings."""
    from .analogs import analog_index
    from .store import connect_reader, model_id, open_store

    with _read_lock:
        if settings not in _read:
            reader = connect_reader(settings)
            _read[settings] = model_id(open_store(settings)), analog_index(reader)
        return _read[settings]


class CimEnricher(Enricher):
    """See the module. ``settings`` and ``stations`` default to the environment's."""

    def __init__(
        self, settings: CimSettings | None = None, stations: Mapping[str, str] | None = None, *, wait: float = 20.0
    ) -> None:
        self.settings = settings
        self.stations = dict(stations) if stations is not None else stations_from_env()
        self.wait = wait
        #: The grid's model id and its Analogs by name, once read.
        self.reference: str | None = None
        self.index: dict[str, str] | None = None
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
            logger.info("frames are tied to grid %s: %d PMU Analogs", self.reference, len(self.index))
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
