"""Voltage phasors, one per station of the live grid, each in the colour of its island.

The web counterpart of the desktop's ``visualization.voltage_phasor_plot``. Reads the newest frame
of the measurement window the time window plots, so it adds no store of its own, and sends it as a
snapshot: a dial reads the same at 5 Hz as at 10, and every message is every station.

The simulation measures a voltage in kV and an angle in degrees; the wire carries volts and radians,
as the dial has always been sent them.
"""

from fastapi import APIRouter, WebSocket

import numpy as np

from pswamp_web.pump import serve_ticks
from pswamp_web.wire import Phasor, PhasorSnapshot, sample

from ..live import LIVE, accept

PUSH_HZ = 5
#: A unit to volts, and to radians.
VOLTS = {"V": 1.0, "kV": 1e3}
RADIANS = {"rad": 1.0, "deg": np.pi / 180}

router = APIRouter()

_pairs: tuple[int, list[tuple[str, str, int, int, float, float]]] = (0, [])


def _voltage_columns() -> list[tuple[str, str, int, int, float, float]]:
    """(station, channel, magnitude column, angle column, to volts, to radians), per station: read
    from the window's header once per layout."""
    global _pairs
    window = LIVE.window
    if _pairs[0] != window.generation:
        header = window.header
        angles = {(header.station[i], header.channel[i]): i for i in header.columns(measurement="V_Angle")}
        _pairs = (
            window.generation,
            [
                (header.station[i], header.channel[i], i, angles[key],
                 VOLTS.get(header.units[i], 1.0), RADIANS.get(header.units[angles[key]], 1.0))
                for i in header.columns(measurement="V_Magnitude")
                if (key := (header.station[i], header.channel[i])) in angles
            ],
        )  # fmt: skip
    return _pairs[1]


def snapshot_message() -> PhasorSnapshot | None:
    if LIVE.window.header is None:
        return None
    columns = _voltage_columns()
    t, latest = LIVE.window.latest([c for entry in columns for c in (entry[2], entry[3])])
    magnitudes = latest[0::2] * np.array([entry[4] for entry in columns])
    angles = latest[1::2] * np.array([entry[5] for entry in columns])

    finite = magnitudes[np.isfinite(magnitudes)]
    mag_ref = float(np.max(finite)) if finite.size else None
    # A circular mean: angles wrap at +/-pi, and a plain average lands in the wrong place there.
    finite_angles = angles[np.isfinite(angles)]
    ang_ref = (
        float(np.arctan2(np.mean(np.sin(finite_angles)), np.mean(np.cos(finite_angles)))) if finite_angles.size else None
    )
    return PhasorSnapshot(
        t=t if np.isfinite(t) else 0.0,
        phasors=[
            Phasor(
                station=station,
                channel=channel,
                mag=sample(magnitude, 1),  # volts to a tenth, radians to six decimals: finer than a dial shows
                ang=sample(angle, 6),
                island=LIVE.island_of.get(station),
            )
            for (station, channel, *_), magnitude, angle in zip(columns, magnitudes, angles, strict=True)
        ],
        mag_ref=sample(mag_ref),
        ang_ref=sample(ang_ref),
    )


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if await accept(ws):
        await serve_ticks(ws, PUSH_HZ, snapshot_message)
