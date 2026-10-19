"""The wire shapes of the CIM graph app: the layout the page draws, the state the socket pushes, the
commands' bodies. Pure pydantic: they are the published contract (api_contract.py reads them from
the routes and from ``WS_MESSAGE``), so the page's types are generated from these, not copied."""

from typing import Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    lon: float = Field(description="Longitude, degrees east (WGS 84).")
    lat: float = Field(description="Latitude, degrees north (WGS 84).")


class LayoutSubstation(BaseModel):
    mrid: str
    name: str
    position: Point


class LayoutBranch(BaseModel):
    """A line, or a transformer between two substations."""

    mrid: str
    name: str
    kind: Literal["line", "transformer"]
    from_substation: str = Field(description="mRID of the substation at its first end.")
    to_substation: str = Field(description="mRID of the substation at its second end.")
    path: list[Point] = Field(description="Its route; empty: a straight segment between the substations.")
    breaker: str | None = Field(
        description="mRID of the one breaker that takes it out of service on its own (its bay's, at one end); "
        "null: it has none, and is operated as a line (POST /lines/{mrid})."
    )


class LayoutBreaker(BaseModel):
    mrid: str
    name: str
    substation: str = Field(description="mRID of the substation it stands in.")


class CimLayout(BaseModel):
    """Where the grid is, read once from the graph's GL profile. Static: state is on the socket."""

    substations: list[LayoutSubstation]
    branches: list[LayoutBranch]
    breakers: list[LayoutBreaker]


class SwitchBody(BaseModel):
    open: bool = Field(description="True to open the switch (or take the line out of service), false to close it (or bring it back).")


class CimGraphState(BaseModel):
    """What the graph says is switched off, pushed on connect and whenever it changes.

    The whole state each time, not a delta: it is a few hundred booleans, and a client that missed
    a message cannot end up wrong."""

    type: Literal["state"] = "state"
    switches: dict[str, bool] = Field(description="Every switch (mRID) and whether it is open.")
    out_of_service: list[str] = Field(description="The lines and transformers (mRIDs) out of service, which is what the simulation follows.")
    writable: bool = Field(description="Whether the graph can be edited (the CGMES profiles are in it).")
