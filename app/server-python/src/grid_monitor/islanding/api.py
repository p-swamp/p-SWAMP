"""Islanding detection and its alarms, over the live grid.

The web counterpart of the desktop's islanding alarm view and alarm overview. The detector is the
``islanding-detection`` module; its assessments and alarms reach every view at once (``LIVE``), about
once a second, and are sent when they arrive.

**An alarm is everyone's.** The grid is one, so its alarm list is too: an operator who acknowledges,
silences or annotates an alarm does so for every viewer, and every open view is sent the change at
once (``LIVE.nudge``). The commands still say whose browser they come from (``client_id``), as every
command does: it is in the access log, and it is not authentication.
"""

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field
from shared import ClientId, CommandAck, get_logger

from pswamp_web.pump import serve_updates
from pswamp_web.wire import AlarmList, IslandingState

from ..live import ALARMS, ISLANDING, LIVE, accept

logger = get_logger("grid-monitor.islanding")
router = APIRouter()


def current_message() -> IslandingState:
    return IslandingState(islanding=LIVE.islanding, alarms=AlarmList(alarms=LIVE.alarms.list()))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not await accept(ws):
        return
    with LIVE.updates(ISLANDING, ALARMS) as updates:
        await serve_updates(ws, updates, lambda _event: current_message())


# An operator note longer than this is a report, not an annotation; truncated
# rather than rejected so a slip cannot lose what was typed.
MAX_NOTE = 500


class AlarmNote(BaseModel):
    """Body of POST /alarms/{alarm_uuid}/annotate."""

    message: str = Field(
        min_length=1,
        description=(
            "The operator's note. Longer than 500 characters is truncated rather "
            "than rejected, so a slip cannot lose what was typed."
        ),
    )


# --- REST commands ----------------------------------------------------------
#
# The alarm is a resource with an id, so these read as actions on it:
#
#     POST /api/islanding/alarms/<uuid>/acknowledge


def _annotate(client_id: str, alarm_uuid: str, event_type: str, message: str) -> None:
    """Apply one operator event to the alarm, for everyone, or 404."""
    if not LIVE.alarms.annotate(alarm_uuid, event_type, message):
        raise HTTPException(status_code=404, detail=f"no alarm {alarm_uuid}")
    logger.info("alarm %s: %s, from client %s", alarm_uuid, event_type, client_id)
    LIVE.nudge()


@router.post("/alarms/{alarm_uuid}/acknowledge", operation_id="islanding_acknowledge")
async def acknowledge(alarm_uuid: str, client_id: ClientId) -> CommandAck:
    """Mark an alarm as seen by an operator."""
    _annotate(client_id, alarm_uuid, "acknowledge", "Acknowledged by operator")
    return CommandAck(applied="acknowledge")


@router.post("/alarms/{alarm_uuid}/silence", operation_id="islanding_silence")
async def silence(alarm_uuid: str, client_id: ClientId) -> CommandAck:
    """Stop an alarm from asserting itself, without resolving it."""
    _annotate(client_id, alarm_uuid, "silence", "Silenced by operator")
    return CommandAck(applied="silence")


@router.post("/alarms/{alarm_uuid}/annotate", operation_id="islanding_annotate")
async def annotate(alarm_uuid: str, client_id: ClientId, body: AlarmNote) -> CommandAck:
    """Attach a free-text operator note to an alarm.

    The Qt dialogue's "Annotate" button. The desktop records this as a ``user_message`` event on the
    alarm rather than as a state change, so the same event type is used here.
    """
    note = body.message.strip()[:MAX_NOTE]
    if not note:
        raise HTTPException(status_code=422, detail="note is empty")
    _annotate(client_id, alarm_uuid, "user_message", note)
    return CommandAck(applied="annotate")
