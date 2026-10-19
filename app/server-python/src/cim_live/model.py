"""The wire shapes of the live grid feed: every frame of the RT sim, as the page plots it.

Pure pydantic: the published contract (api_contract.py reads ``WS_MESSAGE``), so the page's types
are generated from these."""

from typing import Literal

from pydantic import BaseModel, Field


class LiveStation(BaseModel):
    """One PMU station of the stream: a voltage level of a substation."""

    name: str = Field(description="The station's label in the frames, '<substation>_<kV>'.")
    substation: str | None = Field(description="mRID of its substation in the CIM graph; null when unknown.")
    kv: float | None = Field(description="Its nominal voltage, kV: what v_pu is per unit of.")


class LiveLayout(BaseModel):
    """The stations, in the order every sample lists them. Sent first, and again when it changes."""

    header_id: str = Field(description="The frames' layout this describes (PmuHeader.header_id).")
    stations: list[LiveStation]


class LiveSamples(BaseModel):
    """Consecutive frames, oldest first: one entry per frame in ``t``, one value per station in each row."""

    t: list[float] = Field(description="Each frame's time, seconds since the Unix epoch.")
    v_pu: list[list[float | None]] = Field(description="Per frame, each station's voltage magnitude, per unit.")
    angle_deg: list[list[float | None]] = Field(description="Per frame, each station's voltage angle, degrees.")
    f_hz: list[list[float | None]] = Field(description="Per frame, each station's frequency, Hz.")


class LiveFeed(BaseModel):
    """One push: the layout when it is new, and every frame read since the last push.

    Nothing is merged or skipped: a push carries as many frames as came while the last one was
    being sent, so under load the pushes get fewer and larger, and no frame is lost."""

    type: Literal["state"] = "state"
    layout: LiveLayout | None = Field(default=None, description="The stations, when they are new.")
    samples: LiveSamples
