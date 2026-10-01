# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The PMU test streamer's web API: one POST per command, one socket for state.

Each client gets its own run of ``PIPELINE``: a gateway over the sample
recording and the live feed, a player, and the modules wherever the deployment
hosts them. Each POST builds one typed command and dispatches it: a player
command is checked here (404 without a run, 409 when refused), a module command
where the module runs (a refusal comes back as an ``ErrorEvent``). The socket
pushes one ``PmuStreamState`` on connect and after every change.
"""

from __future__ import annotations

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

from pswamp_core.messages import (
    Command,
    PauseCommand,
    PlayCommand,
    PlayerStatus,
    PmuFrame,
    SeekCommand,
    SpeedCommand,
    StepCommand,
    SwitchSourceCommand,
)
from pswamp_core.pipeline import PipelineRegistry, PipelineRun

from .excursion_module import AutoPauseCommand, ExcursionResult
from .pipeline import PIPELINE
from .range_summary_module import RangeSummaryResult, SummarizeRangeCommand
from .stats_module import FrameStatsResult

logger = get_logger("pmu")

REGISTRY: PipelineRegistry[PipelineRun] = PipelineRegistry(
    lambda client_id: PipelineRun(client_id, PIPELINE, transport(), loop=True)
)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with serve_pipeline(PIPELINE, REGISTRY):
        yield


# --- the socket message --------------------------------------------------------------


class PmuStreamState(BaseModel):
    """What the page renders, pushed on connect and after every change. Its parts
    are the core's messages as they are, so the browser's types are generated
    from the same classes."""

    type: Literal["state"] = "state"
    frame: PmuFrame | None = Field(description="The frame at the cursor, with its layout.")
    player: PlayerStatus = Field(description="Where the player is and which controls apply.")
    stats: FrameStatsResult | None = Field(description="The frame statistics for (about) that frame.")
    frame_index: int | None = Field(description="0-based position of the frame in the recording; null when live.")
    frame_count: int | None = Field(description="Frames in the recording; null when live.")
    excursion: ExcursionResult | None = Field(description="The excursion module's latest result.")
    summary: RangeSummaryResult | None = Field(description="The answer to this client's last range summary.")


def state_message(run: PipelineRun) -> PmuStreamState:
    status = run.player.status()
    frame = run.frame if isinstance(run.frame, PmuFrame) else None
    index = count = None
    if frame is not None and status.mode == "replay" and status.coverage_start and status.coverage_end:
        interval = 1.0 / frame.header.data_rate
        index = round((frame.timestamp - status.coverage_start).total_seconds() / interval)
        count = round((status.coverage_end - status.coverage_start).total_seconds() / interval)
    return PmuStreamState(
        frame=frame,
        player=status,
        stats=_about(run.latest.get(FrameStatsResult), frame),
        frame_index=index,
        frame_count=count,
        excursion=run.latest.get(ExcursionResult),
        summary=run.latest.get(RangeSummaryResult),
    )


def _about(result, frame: PmuFrame | None):
    """``result`` if it is about ``frame``, else ``None``. A result comes back
    over the transport a little after its frame, so one up to two frames older
    still counts; one from another stream (before a seek or a switch) does not."""
    if result is None or frame is None:
        return None
    behind = (frame.timestamp - result.timestamp).total_seconds()
    return result if 0 <= behind <= 2 / frame.header.data_rate else None


# --- commands ------------------------------------------------------------------------

router = APIRouter()


def dispatch(command: Command) -> CommandAck:
    return dispatch_command(REGISTRY, command, logger)


@router.post("/playback/play", operation_id="pmu_test_streamer_play", responses=COMMAND_RESPONSES)
async def play(client_id: ClientId) -> CommandAck:
    """Play the recording from the cursor."""
    return dispatch(PlayCommand(client_id=client_id))


@router.post("/playback/pause", operation_id="pmu_test_streamer_pause", responses=COMMAND_RESPONSES)
async def pause(client_id: ClientId) -> CommandAck:
    """Pause the recording at the cursor."""
    return dispatch(PauseCommand(client_id=client_id))


class StepBody(BaseModel):
    n: int = Field(description="Frames to step; negative steps back.")


@router.post("/playback/step", operation_id="pmu_test_streamer_step", responses=COMMAND_RESPONSES)
async def step(client_id: ClientId, body: StepBody) -> CommandAck:
    """Step ``n`` frames, forward or back."""
    return dispatch(StepCommand(client_id=client_id, n=body.n))


class SeekBody(BaseModel):
    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")
    end_offset_s: float | None = Field(default=None, gt=0, description="Stop here: play a chunk.")
    play: bool = Field(default=False, description="Also start playing.")


@router.post("/playback/seek", operation_id="pmu_test_streamer_seek", responses=COMMAND_RESPONSES)
async def seek(client_id: ClientId, body: SeekBody) -> CommandAck:
    """Move to an offset into the recording; with an end, play only that chunk."""
    return dispatch(SeekCommand(client_id=client_id, **body.model_dump()))


class SpeedBody(BaseModel):
    speed: float = Field(gt=0, le=10, description="Speed multiplier; 1 is real time.")


@router.post("/playback/speed", operation_id="pmu_test_streamer_speed", responses=COMMAND_RESPONSES)
async def speed(client_id: ClientId, body: SpeedBody) -> CommandAck:
    """Change the replay speed."""
    return dispatch(SpeedCommand(client_id=client_id, speed=body.speed))


class SourceBody(BaseModel):
    name: str = Field(description="One of PlayerStatus.sources.")


@router.post("/playback/source", operation_id="pmu_test_streamer_source", responses=COMMAND_RESPONSES)
async def source(client_id: ClientId, body: SourceBody) -> CommandAck:
    """Read another source: a recording lands paused at its start, a live feed
    is followed from now."""
    return dispatch(SwitchSourceCommand(client_id=client_id, source=body.name))


# Module commands: published as they are, and checked where the module runs.


class AutoPauseBody(BaseModel):
    enabled: bool = Field(description="Pause the player when the frequency leaves the band.")


@router.post("/excursion/auto-pause", operation_id="pmu_test_streamer_auto_pause", responses=COMMAND_RESPONSES)
async def auto_pause(client_id: ClientId, body: AutoPauseBody) -> CommandAck:
    """Tell the excursion module whether to pause the player on an excursion."""
    return dispatch(AutoPauseCommand(client_id=client_id, enabled=body.enabled))


class SummaryBody(BaseModel):
    source: str = Field(description="The recording to read: one of PlayerStatus.sources.")
    offset_s: float = Field(ge=0, description="Seconds from the start of the recording.")
    end_offset_s: float = Field(gt=0, description="Exclusive end, in seconds from the start.")


@router.post("/summary", operation_id="pmu_test_streamer_summary", responses=COMMAND_RESPONSES)
async def summary(client_id: ClientId, body: SummaryBody) -> CommandAck:
    """Ask the range summary module to summarize a range of a recording. The
    answer arrives on the socket as ``summary``."""
    return dispatch(SummarizeRangeCommand(client_id=client_id, **body.model_dump()))


# --- the socket ----------------------------------------------------------------------


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    async with connected_pipeline(ws, REGISTRY) as run:
        if run is not None:
            await push_changes(ws, run, lambda: state_message(run))
