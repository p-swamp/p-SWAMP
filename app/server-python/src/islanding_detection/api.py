"""The Islanding detection app's web API: a run of its pipeline per client, and a socket
pushing the module's latest result. server.py mounts ``router`` under /api/islanding-detection."""

import contextlib
from typing import Literal

from fastapi import APIRouter, FastAPI, WebSocket
from pydantic import BaseModel, Field
from shared import app_pipeline, connected_pipeline, push_changes, run_registry, serve_pipeline

from pswamp_core.pipeline import PipelineRun
from pswamp_models.common import AlarmEvent
from pswamp_models.islanding_detection import IslandingDetectionResult
from pswamp_models.player import PlayerStatus

PIPELINE = app_pipeline("islanding-detection")

REGISTRY = run_registry(PIPELINE)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with serve_pipeline(PIPELINE, REGISTRY):
        yield


class IslandingDetectionState(BaseModel):
    """Pushed on connect and after every change."""

    type: Literal["state"] = "state"
    player: PlayerStatus = Field(description="Which source is open, and where it is.")
    result: IslandingDetectionResult | None = Field(description="The module's latest result; null until the first.")
    alarm: AlarmEvent | None = Field(description="The module's latest alarm event; null until the first.")


def state_message(run: PipelineRun) -> IslandingDetectionState:
    return IslandingDetectionState(
        player=run.status(),
        result=run.latest.get(IslandingDetectionResult),
        alarm=run.latest.get(AlarmEvent),
    )


router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    async with connected_pipeline(ws, REGISTRY) as run:
        if run is not None:
            await push_changes(ws, run, lambda: state_message(run))
