"""The wire shapes of the live grid feed: every frame of the RT sim, as the page plots it, and its
latest SCADA scan.

Pure pydantic: the published contract (api_contract.py reads ``WS_MESSAGE``), so the page's types
are generated from these."""

from typing import Literal

from pydantic import BaseModel, Field


class LiveStation(BaseModel):
    """One PMU station of the stream: a voltage level of a substation."""

    name: str = Field(description="The station's label in the frames, '<substation>_<kV>'.")
    substation: str | None = Field(description="mRID of its substation in the CIM graph; null when unknown.")
    kv: float | None = Field(description="Its nominal voltage, kV: what v_pu is per unit of.")


class LiveLineEnd(BaseModel):
    """One end of a line, where a PMU measures its current."""

    line: str = Field(description="mRID of the line in the CIM graph.")
    end: Literal[1, 2] = Field(description="Which end: its terminal's sequence number.")
    station: str = Field(description="The station at that end, '<substation>_<kV>'.")
    limit_a: float | None = Field(description="The end's permanent current limit, A; null: the graph gives none.")


class LiveInjection(BaseModel):
    """A generator or a load, whose power a PMU measures."""

    mrid: str = Field(description="mRID of the machine or the load in the CIM graph.")
    name: str
    kind: Literal["generator", "load"]
    station: str = Field(description="The station it is at, '<substation>_<kV>'.")


class LiveScadaPoint(BaseModel):
    """One SCADA measurement of the grid (an Analog, or a switch's Discrete), and what it is on."""

    mrid: str = Field(description="mRID of the Analog or the Discrete in the CIM graph.")
    quantity: Literal["P", "Q", "V", "I", "Pos"] = Field(
        description="Active or reactive power, a voltage, a current, a switch's position (1 closed, 0 open)."
    )
    unit: str = Field(description="What its values are in: 'MW', 'Mvar', 'kV', 'A'; '' for a position.")
    kind: Literal["line", "transformer", "generator", "load", "switch", "voltage_level"] = Field(description="What it is on.")
    equipment: str = Field(description="mRID of the line, transformer, machine, load or switch; of the node, for a voltage.")
    name: str | None = Field(default=None, description="The name of what it is on, as the graph has it.")
    end: int | None = Field(default=None, description="For a line's or a transformer's end: its terminal's sequence number.")
    substation: str | None = Field(default=None, description="mRID of the substation its terminal is in.")
    kv: float | None = Field(default=None, description="The nominal voltage where it measures, kV.")
    positive_flow_in: bool | None = Field(
        default=None, description="For a power: true when a flow into the equipment is positive (CGMES), so a generator's is negative."
    )


class LiveScan(BaseModel):
    """The latest SCADA scan: one value per SCADA point of the layout, in its order."""

    t: float = Field(description="When it was scanned, seconds since the Unix epoch.")
    sim_time: float | None = Field(default=None, description="When, on the simulation's clock, s.")
    values: list[float | None] = Field(description="Each point's value; null: the scan has none for it.")


class LiveLayout(BaseModel):
    """The stations, line ends and injections, each in the order every sample lists them. Sent first,
    and again when it changes."""

    header_id: str = Field(description="The frames' layout this describes (PmuHeader.header_id).")
    stations: list[LiveStation]
    line_ends: list[LiveLineEnd] = Field(default_factory=list)
    injections: list[LiveInjection] = Field(default_factory=list)
    scada: list[LiveScadaPoint] = Field(default_factory=list, description="The grid's SCADA measurements, in the order a scan lists them.")


class LiveSamples(BaseModel):
    """Consecutive frames, oldest first: one entry per frame in ``t``, one value per station in each row."""

    t: list[float] = Field(description="Each frame's time, seconds since the Unix epoch.")
    v_pu: list[list[float | None]] = Field(description="Per frame, each station's voltage magnitude, per unit.")
    angle_deg: list[list[float | None]] = Field(description="Per frame, each station's voltage angle, degrees.")
    f_hz: list[list[float | None]] = Field(description="Per frame, each station's frequency, Hz.")
    i_a: list[list[float | None]] = Field(default_factory=list, description="Per frame, each line end's current magnitude, A.")
    loading: list[list[float | None]] = Field(
        default_factory=list,
        description="Per frame, each line end's current over its permanent limit (1 is at the limit); null without a limit.",
    )
    p_mw: list[list[float | None]] = Field(
        default_factory=list, description="Per frame, each injection's active power, MW (a load's is what it draws)."
    )
    q_mvar: list[list[float | None]] = Field(default_factory=list, description="Per frame, each injection's reactive power, Mvar.")


class LiveFeed(BaseModel):
    """One push: the layout when it is new, and every frame read since the last push.

    Nothing is merged or skipped: a push carries as many frames as came while the last one was
    being sent, so under load the pushes get fewer and larger, and no frame is lost."""

    type: Literal["state"] = "state"
    layout: LiveLayout | None = Field(default=None, description="The stations, when they are new.")
    samples: LiveSamples
    scan: LiveScan | None = Field(default=None, description="The latest SCADA scan, when it is new (or the layout is).")
