"""The Rolling frequency app's web API: a run of its pipeline per client, a
socket pushing the module's result for the instant at the cursor, and the
player's controls. server.py mounts ``router`` under /api/rolling-frequency.

The module needs five seconds of frames before it answers, so after every seek
its results stop for five seconds. The runs here share a ``ResultCache``: a
result computed for an instant of the recording, by any client, is shown again
whenever a cursor is at that instant. ``from_cache`` in the state says which
of the two the page is looking at.
"""

import contextlib
from typing import Literal

from fastapi import APIRouter, FastAPI, WebSocket
from pydantic import BaseModel, Field
from shared import (
    COMMAND_RESPONSES,
    ClientId,
    CommandAck,
    connected_pipeline,
    dispatch_command,
    get_logger,
    push_changes,
    serve_pipeline,
    transport,
)

from pswamp_core.messages import Command, PauseCommand, PlayCommand, PlayerStatus, SeekCommand, SpeedCommand
from pswamp_core.pipeline import PipelineRegistry, PipelineRun
from pswamp_core.result_cache import ResultCache
from pswamp_modules.pipelines.rolling_frequency import PIPELINE
from pswamp_modules.rolling_frequency import RollingFrequencyModule, RollingFrequencyResult

logger = get_logger("rolling-frequency")

#: The recording's results, shared by every client's run. Made in `lifespan`,
#: so each start of the server begins with none.
_cache: ResultCache | None = None

REGISTRY: PipelineRegistry[PipelineRun] = PipelineRegistry(
    lambda client_id: PipelineRun(client_id, PIPELINE, transport(), cache=_cache)
)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _cache
    _cache = ResultCache()
    try:
        async with serve_pipeline(PIPELINE, REGISTRY):
            yield
    finally:
        _cache = None


# --- the socket message --------------------------------------------------------------


class RollingFrequencyState(BaseModel):
    """Pushed on connect and after every change."""

    type: Literal["state"] = "state"
    player: PlayerStatus = Field(description="Where the player is in the recording, and which controls apply.")
    result: RollingFrequencyResult | None = Field(
        description="The module's result for the instant at the cursor; null while its window fills "
        "and nothing is kept for that instant."
    )
    from_cache: bool = Field(
        description="The result was computed on an earlier pass, by this client or another, and kept; "
        "false when the module computed it on this pass."
    )
    warm_up_s: float = Field(description="Seconds of unbroken frames the module needs before it answers.")


def state_message(run: PipelineRun) -> RollingFrequencyState:
    result = run.latest.get(RollingFrequencyResult)
    return RollingFrequencyState(
        player=run.player.status(),
        result=result,
        from_cache=run.from_cache(result),
        warm_up_s=RollingFrequencyModule.warm_up_s,
    )


# --- commands ------------------------------------------------------------------------

router = APIRouter()


def dispatch(command: Command) -> CommandAck:
    return dispatch_command(REGISTRY, command, logger)


@router.post("/playback/play", operation_id="rolling_frequency_play", responses=COMMAND_RESPONSES)
async def play(client_id: ClientId) -> CommandAck:
    """Play the recording from the cursor."""
    return dispatch(PlayCommand(client_id=client_id))


@router.post("/playback/pause", operation_id="rolling_frequency_pause", responses=COMMAND_RESPONSES)
async def pause(client_id: ClientId) -> CommandAck:
    """Pause the recording at the cursor."""
    return dispatch(PauseCommand(client_id=client_id))


class RollingSeekBody(BaseModel):
    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")


@router.post("/playback/seek", operation_id="rolling_frequency_seek", responses=COMMAND_RESPONSES)
async def seek(client_id: ClientId, body: RollingSeekBody) -> CommandAck:
    """Move to an offset into the recording. The module's window starts over there."""
    return dispatch(SeekCommand(client_id=client_id, offset_s=body.offset_s))


class RollingSpeedBody(BaseModel):
    speed: float = Field(gt=0, le=10, description="Speed multiplier; 1 is real time.")


@router.post("/playback/speed", operation_id="rolling_frequency_speed", responses=COMMAND_RESPONSES)
async def speed(client_id: ClientId, body: RollingSpeedBody) -> CommandAck:
    """Change the replay speed."""
    return dispatch(SpeedCommand(client_id=client_id, speed=body.speed))


# --- the socket ----------------------------------------------------------------------


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    async with connected_pipeline(ws, REGISTRY) as run:
        if run is not None:
            await push_changes(ws, run, lambda: state_message(run))
