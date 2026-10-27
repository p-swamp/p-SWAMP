"""A live view of the live grid's measurement window.

The web counterpart of the desktop's ``visualization.time_window_plot_v2``. The window is the
process's one (``LIVE.window``: the last 30 s of every column of the simulation's frames); what
differs between views is only which channels each plots.

So the window is sent once (``mode: "full"``), and after that only the samples that are new
(``"append"``), on a ticker: a 30 s window of 44 channels at 50 Hz is 66,000 numbers, and re-sending
it ten times a second would be megabytes a second per view. When the simulation's layout changes
(it rebuilt its model), a view starts over on its default selection.
"""

from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field
from shared import ClientId, CommandAck, SessionRegistry, read_client_id

from pswamp_web.pump import serve_ticks
from pswamp_web.wire import ChannelCatalogue, Channel, TimeWindowSlice, series

from ..live import LIVE, accept

# How often a view is updated. Fast enough to read as live, and slow enough
# that each message carries a handful of samples rather than one.
PUSH_HZ = 10
#: What a view plots before it chooses: this many stations' frequencies.
DEFAULT_CHANNEL_COUNT = 8
#: How long GET /channels waits for the first frame (the simulation takes seconds to start).
CHANNELS_WAIT = 60.0

router = APIRouter()


@dataclass
class ClientState:
    """One open view: what it plots, and how far it has been sent. Published in SESSIONS for the
    life of the socket, so the commands, which arrive on no connection, can find it."""

    selection: list[int] = field(default_factory=list)
    #: The window's generation the selection is for: another means other columns.
    generation: int = 0
    #: The window's append count at the last message, which is how the next knows what is new.
    last_appended: int = 0
    seq: int = 0
    needs_full: bool = True


SESSIONS: SessionRegistry[ClientState] = SessionRegistry()


def default_selection(channels: list[Channel]) -> list[int]:
    """The first stations' frequencies; the first channels, for a stream with none."""
    frequency = [c.idx for c in channels if c.measurement == "f"]
    return (frequency or [c.idx for c in channels])[:DEFAULT_CHANNEL_COUNT]


def sanitise(requested, n_columns: int) -> list[int]:
    """A client's selection clamped to real columns, in order, each once: it comes from the browser,
    and an index out of range would fail in every later tick."""
    return list(dict.fromkeys(value for value in requested or () if 0 <= value < n_columns))


def build_message(state: ClientState) -> TimeWindowSlice | None:
    """This view's next message; ``None`` when there is nothing new."""
    window = LIVE.window
    if window.header is None:
        return None
    if state.generation != window.generation:
        state.generation = window.generation
        state.selection = default_selection(window.channels)
        state.needs_full = True
        state.last_appended = 0

    new_rows = window.appended - state.last_appended
    state.last_appended = window.appended
    # A view behind by more than the window shares no samples with it: start it over.
    full = state.needs_full or new_rows >= window.n_samples
    if not full and new_rows <= 0:
        return None
    state.needs_full = False

    times, data = window.snapshot(state.selection)
    rows = slice(None) if full else slice(-new_rows, None)
    state.seq += 1
    return TimeWindowSlice(
        mode="full" if full else "append",
        seq=state.seq,
        # Epoch seconds to the millisecond: finer than 50 Hz, and short on the wire.
        t=series(times[rows], ndigits=3),
        series=[series(data[rows, position]) for position in range(len(state.selection))],  # one list per channel
        channels=[window.channels[idx] for idx in state.selection] if full else None,
        n_samples=window.n_samples if full else None,
        sampling_rate=window.header.data_rate if full else None,
    )


# --- REST commands ----------------------------------------------------------
#
# Neither pushes anything itself: both set state the push task reads on its next tick.


class ChannelSelection(BaseModel):
    """Body of POST /selection."""

    channels: list[int] = Field(description="Channel indices, as listed by GET /channels.", examples=[[3, 17, 204]])


def _sessions_or_404(client_id: str) -> list[ClientState]:
    """This browser's open views: none is a 404, since there is no selection to change."""
    sessions = SESSIONS.of(client_id)
    if not sessions:
        raise HTTPException(status_code=404, detail=f"client {client_id} has no open time-window view")
    return sessions


@router.post("/selection", operation_id="time_window_select_channels")
async def select_channels(client_id: ClientId, body: ChannelSelection) -> CommandAck:
    """Choose which channels this browser's measurement view plots."""
    sessions = _sessions_or_404(client_id)
    window = LIVE.window
    selection = sanitise(body.channels, window.header.n_columns if window.header else 0)
    if not selection:
        raise HTTPException(status_code=422, detail="no usable channel indices in the request")
    for state in sessions:
        state.selection = selection
        state.generation = window.generation
        state.needs_full = True  # the view's traces are for other channels
    return CommandAck(applied=f"select_channels ({len(selection)})")


@router.post("/resync", operation_id="time_window_resync")
async def resync(client_id: ClientId) -> CommandAck:
    """Ask for the whole window again rather than the next delta: for a view whose buffer no longer
    matches what the server thinks it has."""
    for state in _sessions_or_404(client_id):
        state.needs_full = True
    return CommandAck(applied="resync")


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not await accept(ws):
        return
    state = ClientState()
    with SESSIONS.registered(read_client_id(ws), state):
        await serve_ticks(ws, PUSH_HZ, lambda: build_message(state))


@router.get("/channels", operation_id="time_window_channels")
async def list_channels() -> ChannelCatalogue:
    """Every selectable channel: every column of the live stream. Waits for the first frame; 503 when
    none comes."""
    if not await LIVE.wait_header(CHANNELS_WAIT):
        raise HTTPException(503, "the live grid is not streaming yet")
    return ChannelCatalogue(channels=LIVE.window.channels)
