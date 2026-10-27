"""The grid topology, over plain HTTP: the grid in the CIM graph, as the grid view draws it.

Static for the process (the CIM graph app edits switches and terminals, not where the grid is), so a
page fetches it once on mount. It is read from the graph once, when the server starts; until the grid
is loaded the request waits for it.
"""

from fastapi import APIRouter, HTTPException

from pswamp_web.wire import GridModel

from ..live import LIVE

router = APIRouter()


@router.get("/model", operation_id="grid_model")
async def grid_model() -> GridModel:
    """The grid in the CIM graph: a bus per voltage level of each substation (the live stream's
    stations), the lines and transformers between them, and where to draw them. 503 when the grid
    cannot be read."""
    try:
        return (await LIVE.grid()).model
    except Exception as error:
        raise HTTPException(503, f"the grid cannot be read: {error}") from error
