# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The wire format between the p-SWAMP analysis core and a browser.

p-SWAMP's Qt front end never needed one of these: its widgets hold a reference to
the very ``TimeWindow`` object the application thread is writing into, and read it
on a repaint timer. Nothing is ever serialised, so nothing ever had to have a
schema. The one place a message does cross a process boundary -- the streaming
layer -- pickles Python objects inside a JSON envelope, which no browser can read.

So this module is where the shapes get named. Every message a page receives is
declared here, and every page sends through :func:`send_state`.

It also holds the names every REST command endpoint declares itself with --
:data:`ClientId`, :class:`CommandAck`, :func:`read_client_id` -- for the whole
backend, not just this package. They live here rather than in ``src/shared.py``
because the import may only run one way: this package is kept self-contained so
that the repo's two Python projects can be consolidated in whichever direction the
Qt front end's lifetime ends up dictating (§7 of
``doc/WIP-context-port-from-qt-to-web-frontend.md``), so nothing in it may import
from the rest of the web backend, while ``shared.py`` importing *inward* costs
nothing and stays legal whichever way that goes. It re-exports them for the app
packages beside it.

Two conventions worth knowing before adding a message:

**snake_case on the wire, and on the screen.** The web client reads these field
names as they are, through the types generated from this module -- there is no
renaming layer, because one that has to be extended by hand for every new field
is one that silently drops the fields nobody remembered.

**NaN is null.** Not a formality: ``json.dumps`` emits a bare ``NaN`` token,
which ``JSON.parse`` rejects outright, and NaN is the *normal* case here -- a
``TimeWindow`` is all-NaN until it fills, and the PMU decoder substitutes NaN for
missing frequencies. Without this the very first message to every page would be a
parse error in the browser. ``null`` is also what a charting library wants to see
for a gap, so nothing is lost on the way in.
"""

import math
import re
from typing import Annotated, Literal

from fastapi import Query, WebSocket
from pydantic import BaseModel

# A measurement that may be missing. NaN and infinities become null on the wire.
Sample = float | None

# Statuses an application can report. Mirrors the strings p-SWAMP's applications
# actually set on themselves; "Undefined" is the value before the first analysis.
AppStatusValue = Literal["OK", "Alert", "Emergency", "Initializing...", "Undefined"]


def sample(value, ndigits: int | None = None) -> Sample:
    """Coerce one float to something JSON can represent.

    ``ndigits`` is worth passing wherever a message carries many of these: a
    float64 repr is up to 17 characters of which only the first few mean
    anything, and on a payload that is mostly numbers the difference is roughly
    half the bytes.
    """
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return value if ndigits is None else round(value, ndigits)


def series(values, ndigits: int = 6) -> list[Sample]:
    """Coerce a 1-D float array to a JSON-safe list.

    Rounding is not cosmetic: PMU measurements carry far fewer significant
    figures than a float64 repr prints, and six decimals cuts roughly a third off
    a payload that is almost entirely digits.
    """
    out: list[Sample] = []
    for value in values:
        value = float(value)
        # value != value is the NaN test, and the cheapest one.
        out.append(
            None
            if (value != value or value in (math.inf, -math.inf))
            else round(value, ndigits)
        )
    return out


# The one spelling of a client id, shared by the query parameter below, the
# socket parser beside it, and the ``client_id`` the web client persists per
# browser profile (app/client-web/src/lib/clientId.ts). Numeric and bounded: the
# value ends up in log lines and in thread names.
CLIENT_ID_PATTERN = r"^\d{1,20}$"


def read_client_id(ws: WebSocket) -> str | None:
    """The client id from a socket's ``?client_id=``, or None if unusable.

    Applies :data:`CLIENT_ID_PATTERN` -- the very rule :data:`ClientId` applies
    to a command's query parameter -- so a page's socket and its commands can
    never address different state. One regex, not two hand-kept-equal checks.

    This is not authentication and does not pretend to be: supply someone else's
    id and you share their stream.
    """
    raw = ws.query_params.get("client_id")
    if raw is None:
        return None
    return raw.strip() if re.match(CLIENT_ID_PATTERN, raw.strip()) else None


ClientId = Annotated[
    str,
    Query(
        alias="client_id",
        pattern=CLIENT_ID_PATTERN,
        description=(
            "The browser's client id -- the same value its WebSockets send, which "
            "is what makes a command apply to the pipeline the page is watching."
        ),
    ),
]
"""The caller's identity on a command request.

Deliberately the same ``?client_id=`` the sockets already carry rather than a
header or a body field: it mirrors the WebSocket convention exactly, and it lands
in the access log, which is half the reason these commands became HTTP requests.

A *string*, because pipeline keys are strings and because "0" and "007" are then
one identity rather than three. :func:`read_client_id` applies the same pattern
to the socket's query parameter, so the two cannot disagree.

Not authentication -- see :func:`read_client_id`. FastAPI rejects a missing or
malformed one with a 422 before any handler runs, which is the whole validation
story.

The scaffold app packages under ``src/`` import this (and :class:`CommandAck`)
through ``shared.py``, which re-exports both. The import direction is one-way:
nothing in here may import from the rest of the web backend, so that the Python
consolidation (§7 of ``doc/WIP-context-port-from-qt-to-web-frontend.md``) stays
cheap in either direction.
"""


class CommandAck(BaseModel):
    """The reply to every command POST.

    Deliberately NOT the resulting state. That arrives on whichever socket the
    page has open, on the server's own schedule, so state has exactly one path
    and there is no ordering for a client to reconcile between two of them. What
    this carries is only "the command was understood and applied, and here is
    what it was" -- enough to log and to assert on, and nothing a page renders.
    """

    status: Literal["ok"] = "ok"
    applied: str


async def send_state(ws: WebSocket, message: BaseModel) -> None:
    """Send a message to one client.

    Deliberately the only way a page sends. ``WebSocket.send_json`` routes through
    ``json.dumps``, which happily emits bare ``NaN`` and ``Infinity`` tokens that
    are not valid JSON and that ``JSON.parse`` refuses; pydantic's serialiser does
    not, given the field types declared below. Routing every page through here
    means a new message type cannot quietly reintroduce that bug.
    """
    await ws.send_text(message.model_dump_json())


# --- time window ------------------------------------------------------------


class Channel(BaseModel):
    """One column of a labelled time window.

    Flattened from p-SWAMP's three-row header, plus a precomputed display label so
    the client never has to join the parts itself.
    """

    idx: int  # column index within the application's window; the selection token
    station: str  # "3000"
    channel: str  # "Frequency" | "V_Magnitude" | "I[L3000-3020]_Angle"
    measurement: str  # "f" | "Df" | "v_Magnitude" | "v_Angle" | "i_..."
    label: str  # "3000 Frequency"


class ChannelCatalogue(BaseModel):
    """Body of ``GET /api/time-window/channels``: every selectable channel.

    Static for the life of the process, which is why it is a plain GET rather than
    something pushed down the socket. Declared as a model so the catalogue is in
    the contract -- it used to be built as a hand-dumped dict, which published as
    a bare `object` and left the client casting an implicitly-`any` response.
    """

    channels: list[Channel]


class TimeWindowSlice(BaseModel):
    """A slice of the client's measurement window.

    ``series`` is column-major -- one list per channel, parallel to ``channels``.
    That is the layout a streaming chart wants; row-major would force the client
    to transpose a matrix of a few hundred thousand numbers on every update.

    ``mode`` is what keeps this affordable. A full window is tens of thousands of
    numbers and re-sending it several times a second is megabytes per second per
    client; an "append" carries only the samples added since the last message.
    The server sends "full" on connect and whenever the selection changes, and
    "append" the rest of the time. ``seq`` counts messages so a client can tell
    it missed one and ask for a fresh "full".
    """

    type: Literal["state"] = "state"
    mode: Literal["full", "append"]
    seq: int
    t: list[Sample]
    series: list[list[Sample]]
    channels: list[Channel] | None = None
    n_samples: int | None = None
    sampling_rate: float | None = None


# --- phasors ----------------------------------------------------------------


class Phasor(BaseModel):
    station: str
    channel: str
    mag: Sample  # volts
    ang: Sample  # radians
    island: int | None = None  # 0 is the main system


class PhasorSnapshot(BaseModel):
    """The most recent phasor per station.

    ``mag_ref`` and ``ang_ref`` are sent rather than applied, so the client can
    offer per-unit and mean-angle-relative views as toggles -- which is what the
    Qt phasor plot does -- without the server having to guess which is wanted.
    """

    type: Literal["state"] = "state"
    t: float
    phasors: list[Phasor]
    mag_ref: Sample = None
    ang_ref: Sample = None


# --- islanding --------------------------------------------------------------


class Island(BaseModel):
    index: int  # 0 is the main system
    stations: list[str]
    mean_freq: Sample


class IslandingParameters(BaseModel):
    window_length: float
    mean_threshold: float
    eval_freq: float


class IslandingResult(BaseModel):
    type: Literal["state"] = "state"
    t: float
    app_uuid: str
    app_name: str
    status: AppStatusValue
    islands: list[Island]
    parameters: IslandingParameters


# --- line outage detection --------------------------------------------------


class LineOutageEvent(BaseModel):
    """One branch changing connection state, as the detector reports it.

    ``stations`` and ``measurements`` come straight from the time window's
    header for the channels that flipped, so a single physical line trip
    normally appears with the station at each end -- the current on that branch
    goes to zero as seen from both.
    """

    t: float
    kind: Literal["disconnect", "connect"]
    stations: list[str]
    measurements: list[str]


class LineOutageLog(BaseModel):
    """Newest first. The detector is silent unless something changes, so
    ``events`` is a log of transitions; ``disconnected`` is the present state
    they add up to."""

    type: Literal["state"] = "state"
    app_uuid: str | None = None
    app_name: str | None = None
    window_length: float | None = None
    events: list[LineOutageEvent]
    # What is open *now*: every element whose current is zero, named as its
    # channel names it ("L3244-6500"). Lines, transformers, loads and generators
    # alike -- a reader after branches matches these against ``GridBranch.name``.
    disconnected: list[str] = []


# --- alarms -----------------------------------------------------------------


# What an alarm event can be. Was a bare `str` with these spelled out only in a
# trailing comment, which published as an unconstrained string -- so a client had
# no way to know the vocabulary and no check if it guessed wrong.
AlarmEventType = Literal[
    "init",
    "not_critical",
    "acknowledge",
    "silence",
    "user_message",
]


class AlarmEvent(BaseModel):
    t: float
    type: AlarmEventType
    message: str


class Alarm(BaseModel):
    uuid: str
    app_uuid: str
    app_name: str
    t_start: float
    t_end: float | None = None
    status: Literal["unseen", "acknowledged", "silenced", "not_critical"]
    events: list[AlarmEvent]


class AlarmList(BaseModel):
    type: Literal["state"] = "state"
    alarms: list[Alarm]  # newest first


class IslandingState(BaseModel):
    """Both halves of the islanding page in one message.

    Detection and alarms are separate concerns upstream -- different topics, one
    derived from the other -- but they change together and are read together, so
    splitting them across two sockets would only mean the page could render them
    inconsistently.

    Declared here rather than in islanding/api.py, where it used to live: this
    module's whole job is to be the one place a message shape is named, and a
    shape defined next to its endpoint was the one exception.
    """

    type: Literal["state"] = "state"
    islanding: IslandingResult | None = None
    alarms: AlarmList


# --- application status -----------------------------------------------------


class AppStatus(BaseModel):
    uuid: str
    app_name: str
    status: AppStatusValue
    t: float  # data time stamp the application reported
    received_at: float  # server wall clock when it arrived
    stale: bool  # nothing heard recently; the Qt table greys these out


class AppStatusTable(BaseModel):
    type: Literal["state"] = "state"
    apps: list[AppStatus]
    server_time: float
    replay: "ReplayStatus"


class ReplayStatus(BaseModel):
    """State of the PMU source feeding every application."""

    source: str
    playing: bool
    data_rate: float
    n_samples: int
    n_channels: int
    cursor: int  # absolute row index, so it keeps counting across loops
    position: float  # seconds into the current pass
    duration: float


# --- grid model -------------------------------------------------------------


class GridBus(BaseModel):
    name: str
    v_nom: Sample = None
    area: str | None = None
    lon: Sample = None
    lat: Sample = None


class GridBranch(BaseModel):
    name: str
    from_bus: str
    to_bus: str
    kind: Literal["line", "trafo"]


class PmuSite(BaseModel):
    name: str
    lon: float
    lat: float


LonLat = tuple[float, float]


class GridDiagram(BaseModel):
    """How the grid is drawn: the Qt grid view's base layers, as data.

    Separate from the topology beside it because the two disagree on purpose. A
    single-line diagram places a bus where it is legible, not where the station
    stands -- up to a few degrees away from its ``PmuSite`` -- and routes a
    branch along a polyline rather than straight between its ends. So a view
    that draws this must take every position from here and none from ``pmus``.

    Built ahead of time by ``tools/build_n44_grid_geometry.py``, because the DXF
    and shapefile readers it needs are not in the server's environment.
    """

    sld: str  # which single-line diagram this is, e.g. "geo"
    countries: list[str]
    # How much taller a degree of latitude is drawn than a degree of longitude.
    aspect_ratio: float
    buses: dict[str, LonLat]  # bus name -> where the diagram draws it
    # Branch name -> its route, from ``from_bus`` to ``to_bus``. A branch the
    # diagram does not draw is simply absent.
    branches: dict[str, list[LonLat]]
    outlines: list[list[LonLat]]  # one closed ring per coastline or border


class GridModel(BaseModel):
    """Static topology. Served over HTTP rather than a socket: it never changes,
    it is worth caching, and putting it on the socket would make every page's
    hook handle a second message shape for no benefit."""

    buses: list[GridBus]
    branches: list[GridBranch]
    pmus: list[PmuSite]
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max
    diagram: GridDiagram | None = None
