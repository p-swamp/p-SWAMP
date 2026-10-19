"""The live grid feed: every frame of the RT sim, read back off the transport, as compact samples.

The RT sim is a source of the PMU test streamer's pipeline: its shared run ``live.rtsim``
publishes each ``PmuFrame`` on the transport (``pmu-test-streamer.pmu.frame``), where any module
reads it. This socket reads it there too, like a module would, and sends the page what it plots:
for each frame, every station's voltage (per unit), angle and frequency, with the stations listed
once (``LiveLayout``). About 1.5 kB a frame on Nordic44, against 32 kB for the frame itself.

**Every frame reaches the page.** Each socket has a queue of its own on the transport (a 10 s
backlog); each push drains it and sends all it held, in order, in one message. A page that keeps up
gets one frame per push; one that falls behind gets fewer, larger pushes, and loses nothing until it
is more than the backlog behind. Nothing here wakes on anything but a frame.

Which substation and nominal voltage each station is comes from the CIM graph, through the PMU
Analog its voltage column carries (``PmuHeader.analog``), read once.
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

from .model import LiveFeed, LiveLayout, LiveSamples, LiveStation

logger = get_logger("cim-live")
router = APIRouter()

#: Where the frames are: the streamer's pipeline, the RT sim's shared run.
APP, KEY = "pmu-test-streamer", "live.rtsim"
#: Frames a socket may fall behind by before the oldest are dropped: 10 s at 50 Hz.
BACKLOG = 500

_cim = ThreadPoolExecutor(1, thread_name_prefix="cim-live")


@functools.cache
def _places() -> dict[str, tuple[str | None, float | None]]:
    """Each PMU Analog's substation (mRID) and nominal kV, from the CIM graph. Read once (in a thread)."""
    from lazycim import F, L
    from pswamp_core.cim import analog_table, connect_reader

    try:
        repo = connect_reader()
        analogs = analog_table(repo)
        nodes = repo.query(L.ConnectivityNodes).to_dataframe(
            node=F.mRID,
            substation=F.ConnectivityNodeContainer.Substation.mRID,
            kv=F.ConnectivityNodeContainer.BaseVoltage.nominalVoltage,
        )
    except Exception as error:  # no graph: the stations are still plotted, in kV units unknown
        logger.warning("the CIM graph cannot be read, stations have no substation: %s", error)
        return {}
    at = {
        row.node: (row.substation if isinstance(row.substation, str) else None, float(row.kv) if row.kv == row.kv else None)
        for row in nodes.itertuples()
    }
    return {row.mRID: at.get(row.node, (None, None)) for row in analogs.itertuples()}


@dataclass(frozen=True)
class Layout:
    """Where each station's values are in a frame, and what per unit means for it."""

    message: LiveLayout
    v: np.ndarray
    angle: np.ndarray
    f: np.ndarray
    kv: np.ndarray


def _layout(header: PmuHeader, places: dict[str, tuple[str | None, float | None]]) -> Layout:
    columns: dict[str, dict[str, int]] = {}
    for i, (station, measurement) in enumerate(zip(header.station, header.measurement, strict=True)):
        if measurement in ("V_Magnitude", "V_Angle", "f"):
            columns.setdefault(station, {}).setdefault(measurement, i)
    stations, v, angle, f, kv = [], [], [], [], []
    for station, found in columns.items():
        analog = header.analog[found["V_Magnitude"]] if header.analog and "V_Magnitude" in found else None
        substation, nominal = places.get(analog, (None, None)) if analog else (None, None)
        stations.append(LiveStation(name=station, substation=substation, kv=nominal))
        v.append(found.get("V_Magnitude", -1))
        angle.append(found.get("V_Angle", -1))
        f.append(found.get("f", -1))
        kv.append(nominal or np.nan)
    return Layout(
        LiveLayout(header_id=header.header_id, stations=stations),
        np.array(v), np.array(angle), np.array(f), np.array(kv, dtype=float),
    )  # fmt: skip


def _rows(values: np.ndarray, index: np.ndarray, scale: np.ndarray | None, digits: int) -> list[list[float | None]]:
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
    )


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if read_client_id(ws) is None:
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    places = await loop.run_in_executor(_cim, _places)
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
                        layout = _layout(group[0].header, places)
                        new = layout.message
                    await send_state(ws, LiveFeed(layout=new, samples=samples(layout, group)))

        pusher = asyncio.create_task(push())
        try:
            await wait_for_disconnect(ws)
        finally:
            pusher.cancel()
            await asyncio.gather(pusher, return_exceptions=True)
