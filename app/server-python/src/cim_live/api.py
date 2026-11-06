"""The live grid feed: every frame of the RT sim, read back off the transport, as compact samples.

The RT sim is a source of the PMU test streamer's pipeline: its shared run ``live.rtsim``
publishes each ``PmuFrame`` on the transport (``pmu-test-streamer.pmu.frame``), where any module
reads it. This socket reads it there too, like a module would, and sends the page what it plots:
for each frame, every station's voltage (per unit), angle and frequency, every line end's current
(A, and its loading against the end's permanent limit) and every generator's and load's power (MW,
Mvar), with the stations, line ends and injections listed once (``LiveLayout``). About 1.5 kB a frame on Nordic44, against 32 kB for the frame itself.

**Every frame reaches the page.** Each socket has a queue of its own on the transport (a 10 s
backlog); each push drains it and sends all it held, in order, in one message. A page that keeps up
gets one frame per push; one that falls behind gets fewer, larger pushes, and loses nothing until it
is more than the backlog behind. Nothing here wakes on anything but a frame.

Which substation and nominal voltage each station is, which line end a current is at (and its
limit), which machine or load a power is of, come from the CIM graph, through the PMU Analog each
column carries (``PmuHeader.analog``; ``pswamp_core.cim.measurement_table``), read once. A grid's PMUs
may measure no power (Nordic44's do not): its machines and loads are then in no frame.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from fastapi import APIRouter, WebSocket
from shared import get_logger, read_client_id, send_state, transport, wait_for_disconnect

from pswamp_core.subscription import Overflow
from pswamp_models.pmu import PmuFrame, PmuHeader

from .model import LiveFeed, LiveInjection, LiveLayout, LiveLineEnd, LiveSamples, LiveStation

logger = get_logger("cim-live")
router = APIRouter()

#: Where the frames are: the streamer's pipeline, the RT sim's shared run.
APP, KEY = "pmu-test-streamer", "live.rtsim"
#: Frames a socket may fall behind by before the oldest are dropped: 10 s at 50 Hz.
BACKLOG = 500

_cim = ThreadPoolExecutor(1, thread_name_prefix="cim-live")


@dataclass(frozen=True)
class Facts:
    """What the graph says of each PMU Analog, read once."""

    #: Analog -> its substation (mRID) and nominal kV.
    places: dict[str, tuple[str | None, float | None]]
    #: A current's Analog -> its line (mRID) and end.
    ends: dict[str, tuple[str, int]]
    #: A power's Analog -> the machine or load (mRID), its name and its kind.
    injections: dict[str, tuple[str, str, str]]
    #: (line mRID, end) -> its permanent current limit, A.
    limits: dict[tuple[str, int], float]


NO_FACTS = Facts({}, {}, {}, {})


@functools.cache
def _facts() -> Facts:
    """What the CIM graph says of each PMU Analog (see ``Facts``). Read once (in a thread)."""
    from pswamp_core.cim import connect_reader, current_limits, measurement_table

    try:
        repo = connect_reader()
        table = measurement_table(repo)
        limits = current_limits(repo)
    except Exception as error:  # no graph: the stations are still plotted, in kV units unknown
        logger.warning("the CIM graph cannot be read, stations have no substation: %s", error)
        return NO_FACTS
    kinds = {"SynchronousMachine": "generator", "EnergyConsumer": "load"}
    pmu = table[table["source"] == "PMU"]
    places, ends, injections = {}, {}, {}
    for row in pmu.itertuples():
        places[row.mRID] = (row.substation if isinstance(row.substation, str) else None, float(row.kv) if row.kv == row.kv else None)
        if row.quantity == "I" and row.equipment_class in ("ACLineSegment", "PowerTransformer"):
            ends[row.mRID] = (row.equipment, int(row.sequence))
        elif row.quantity in ("P", "Q") and row.equipment_class in kinds:
            injections[row.mRID] = (row.equipment, str(row.equipment_name), kinds[row.equipment_class])
    return Facts(places, ends, injections, limits)


@dataclass(frozen=True)
class Layout:
    """Where each station's values are in a frame, and what per unit means for it."""

    message: LiveLayout
    v: np.ndarray
    angle: np.ndarray
    f: np.ndarray
    kv: np.ndarray
    #: Each line end's current magnitude column, and its limit (NaN: none).
    i: np.ndarray
    limit: np.ndarray
    #: Each injection's P and Q columns.
    p: np.ndarray
    q: np.ndarray


def _layout(header: PmuHeader, facts: Facts) -> Layout:
    columns: dict[str, dict[str, int]] = {}
    ends: dict[tuple[str, int], tuple[str, int]] = {}  # (line, end) -> its station and I_Magnitude column
    powers: dict[str, dict[str, int]] = {}  # injection -> its P and Q columns
    station_of: dict[str, str] = {}
    analogs = header.analog or [None] * header.n_columns
    for i, (station, measurement, analog) in enumerate(zip(header.station, header.measurement, analogs, strict=True)):
        if measurement in ("V_Magnitude", "V_Angle", "f"):
            columns.setdefault(station, {}).setdefault(measurement, i)
        elif measurement == "I_Magnitude" and analog in facts.ends:
            ends.setdefault(facts.ends[analog], (station, i))
        elif measurement in ("P", "Q") and analog in facts.injections:
            mrid = facts.injections[analog][0]
            powers.setdefault(mrid, {})[measurement] = i
            station_of.setdefault(mrid, station)
    stations, v, angle, f, kv = [], [], [], [], []
    for station, found in columns.items():
        analog = header.analog[found["V_Magnitude"]] if header.analog and "V_Magnitude" in found else None
        substation, nominal = facts.places.get(analog, (None, None)) if analog else (None, None)
        stations.append(LiveStation(name=station, substation=substation, kv=nominal))
        v.append(found.get("V_Magnitude", -1))
        angle.append(found.get("V_Angle", -1))
        f.append(found.get("f", -1))
        kv.append(nominal or np.nan)
    line_ends = [
        LiveLineEnd(line=line, end=end, station=station, limit_a=facts.limits.get((line, end)))
        for (line, end), (station, _) in ends.items()
    ]
    names = {mrid: (name, kind) for mrid, name, kind in facts.injections.values()}
    injections = [
        LiveInjection(mrid=mrid, name=names[mrid][0], kind=names[mrid][1], station=station_of[mrid]) for mrid in powers
    ]
    ints = lambda values: np.array(values, dtype=int)  # noqa: E731
    return Layout(
        LiveLayout(header_id=header.header_id, stations=stations, line_ends=line_ends, injections=injections),
        np.array(v), np.array(angle), np.array(f), np.array(kv, dtype=float),
        ints([column for _, column in ends.values()]),
        np.array([np.nan if e.limit_a is None else e.limit_a for e in line_ends], dtype=float),
        ints([found.get("P", -1) for found in powers.values()]),
        ints([found.get("Q", -1) for found in powers.values()]),
    )  # fmt: skip


def _rows(values: np.ndarray, index: np.ndarray, scale: np.ndarray | None, digits: int) -> list[list[float | None]]:
    """Per frame, the values at the columns ``index`` (-1: none), over ``scale``, rounded; NaN is null."""
    if len(index) == 0:
        return [[] for _ in range(len(values))]
    picked = np.where(index >= 0, values[:, np.maximum(index, 0)], np.nan)
    if scale is not None:
        picked = picked / scale
    picked = np.round(picked, digits)
    return [[None if x != x else x for x in row] for row in picked.tolist()]  # NaN -> null


def samples(layout: Layout, frames: list[PmuFrame]) -> LiveSamples:
    values = np.array([[np.nan if v is None else v for v in frame.values] for frame in frames], dtype=float)
    return LiveSamples(
        t=[frame.timestamp.timestamp() for frame in frames],
        v_pu=_rows(values, layout.v, layout.kv, 5),
        angle_deg=_rows(values, layout.angle, None, 3),
        f_hz=_rows(values, layout.f, None, 5),
        i_a=_rows(values, layout.i, None, 1),
        loading=_rows(values, layout.i, layout.limit, 4),
        p_mw=_rows(values, layout.p, None, 2),
        q_mvar=_rows(values, layout.q, None, 2),
    )


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if read_client_id(ws) is None:
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    facts = await loop.run_in_executor(_cim, _facts)
    with transport().subscribe(PmuFrame, app=APP, key=KEY, overflow=Overflow.DROP_OLDEST, maxsize=BACKLOG) as frames:

        async def push() -> None:
            layout: Layout | None = None
            while True:
                _, first = await frames.get()
                batch = [first]
                while (more := frames.get_nowait()) is not None:
                    batch.append(more[1])
                for header_id, run in itertools.groupby(batch, key=lambda frame: frame.header.header_id):
                    group, new = list(run), None
                    if layout is None or header_id != layout.message.header_id:
                        layout = _layout(group[0].header, facts)
                        new = layout.message
                    await send_state(ws, LiveFeed(layout=new, samples=samples(layout, group)))

        pusher = asyncio.create_task(push())
        try:
            await wait_for_disconnect(ws)
        finally:
            pusher.cancel()
            await asyncio.gather(pusher, return_exceptions=True)
