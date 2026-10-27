# /// script
# requires-python = ">=3.12"
# dependencies = ["lazycim[tops]>=0.2.2", "pswamp-islanding-detection"]
#
# [tool.uv.sources]
# pswamp-islanding-detection = { path = "..", editable = true }
# ///
"""Islanding detection on a Nordic 44 simulation built from CIM, with no server.

The grid comes from LazyCIM: its Nordic 44 demo model, given machine dynamics
(``create_dynamic=True``) and a governor, exciter and stabilizer per machine,
then exported to a TOPS model with a PLL on every bus. TOPS simulates it: four
lines trip at 15 s, cutting buses 6500, 6700 and 6701 off from the rest of the
grid, and reconnect at 35 s. Every 20 ms of simulation time becomes a
``PmuFrame`` (voltage magnitude, angle and frequency per bus), and each frame
goes through ``IslandingDetectionModule`` with a plain synchronous call.

    uv run modules/islanding-detection/examples/n44_line_trip_tops.py

The script carries its own environment (the block at the top): LazyCIM needs
Python 3.12, and the workspace is locked for 3.11, so it cannot be an extra of
the module. The first run downloads the Nordic 44 files into LazyCIM's cache.
Nordic 44 is licensed CC BY-NC-SA 4.0 by Statnett SF.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import numpy as np
import tops.dynamic as dps
from lazycim import F, L
from lazycim.demo import load_nordic44
from lazycim.sim import get_exporter
from tops import solvers

from pswamp_models.common import AlarmEvent
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.islanding_detection import IslandingDetectionModule

RATE_HZ = 50.0
DT = 5e-3  # simulation step, s
T_END = 70.0
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Nordic 44's data and the CGMES ontology spell this namespace two ways.
# LazyCIM would work that out and warn; saying so up front is quiet.
NAMESPACE_ALIASES = {"http://iec.ch/TC57/CIM100-EuropeanExtension/1/0#": "http://iec.ch/TC57/CIM100-European#"}

# The lines, by the PSS/E bus numbers at their ends. Disconnecting these four
# severs the buses 6500, 6700 and 6701 from the rest of the grid.
LINES = ["L3244-6500", "L5100-6500", "L3115-6701", "L3701-6700"]
EVENTS = [(15.0, "disconnect"), (35.0, "connect")]


def add_controllers(repo) -> None:
    """A governor, an exciter and a stabilizer for every machine, as CIM objects.

    The machine dynamics alone have no governor, so after the split neither
    side settles, and the two reconnect far out of step. The parameters are
    those of the desktop package's Nordic 44 simulation (TGOV1, SEXS, STAB1),
    in the attributes of the CIM classes the TOPS exporter maps to them.
    """
    new = repo.L
    for dynamics in repo.query(L.SynchronousMachineTimeConstantReactances).all():
        new.GovSteam0(
            SynchronousMachineDynamics=dynamics,
            r=0.05, dt=0.0, vmin=0.0, vmax=1.0, t1=0.2, t2=1.0, t3=2.0,
            mwbase=float(dynamics.SynchronousMachine.ratedS),
        )  # fmt: skip
        exciter = new.ExcSEXS(
            SynchronousMachineDynamics=dynamics,
            k=100.0, tatb=0.2, tb=10.0, te=0.5, emin=-3.0, emax=3.0,
        )  # fmt: skip
        new.PssIEEE1A(
            ExcitationSystemDynamics=exciter,
            ks=50.0, t5=10.0, t1=0.5, t2=0.05, t3=0.5, t4=0.05,
            t6=0.0, a1=0.0, a2=0.0, vrmax=0.03, vrmin=-0.03,
        )  # fmt: skip
    repo.commit()


def bus_numbers(repo, sim) -> tuple[dict[str, str], dict[str, str]]:
    """The TOPS line of each ``L<from>-<to>``, and the PSS/E number of each bus.

    LazyCIM names lines and buses after their CIM objects (``300AJAURE-MO``,
    ``AJAURE``). The Nordic 44 model keeps the PSS/E bus numbers at the start of
    each line's description (``"3701 6700 '1 '"``), in from-to order.
    """
    description = dict(repo.query(L.ACLineSegments).to_dataframe(mRID=F.mRID, d=F.description).values)
    columns, *rows = sim.model["lines"]
    from_bus, to_bus = columns.index("from_bus"), columns.index("to_bus")
    lines, numbers = {}, {}
    for row in rows:
        a, b, *_ = description[sim.ids["lines"][row[0]]].split()
        lines[f"L{a}-{b}"] = row[0]
        for bus, number in ((row[from_bus], a), (row[to_bus], b)):
            assert numbers.setdefault(bus, number) == number, f"{bus} is both {numbers[bus]} and {number}"
    return lines, numbers


def simulate() -> Iterator[PmuFrame]:
    """Build the model from CIM, run it in TOPS, and yield a frame every 20 ms."""
    repo = load_nordic44(create_dynamic=True, namespace_aliases=NAMESPACE_ALIASES)
    add_controllers(repo)
    sim = get_exporter("tops", repo, plls=True).build()
    lines, numbers = bus_numbers(repo, sim)

    ps = dps.PowerSystemModel(model=sim.model)
    ps.init_dyn_sim()
    buses = list(ps.buses["name"])
    assert list(ps.pll["PLL1"].par["bus"]) == buses  # one PLL per bus, in bus order
    v_n = np.asarray(ps.buses["V_n"], dtype=float)  # kV

    # A bus no line reaches (an HVDC terminal) keeps its name.
    stations = [numbers.get(bus, bus) for bus in buses]
    header = PmuHeader(
        station=[s for s in stations for _ in range(3)],
        channel=["V", "V", "f"] * len(stations),
        measurement=["V_Magnitude", "V_Angle", "f"] * len(stations),
        units=["kV", "deg", "Hz"] * len(stations),
        data_rate=RATE_HZ,
    )

    solver = solvers.ModifiedEulerDAE(
        ps.state_derivatives, ps.solve_algebraic, 0, ps.x_0.copy(), T_END, max_step=DT
    )
    events = list(EVENTS)
    n = 0
    while solver.t < T_END:
        while events and solver.t >= events[0][0]:
            _, action = events.pop(0)
            for line in LINES:
                ps.lines["Line"].event(ps, lines[line], action)
        solver.step()
        if solver.t < n / RATE_HZ - DT / 2:
            continue

        v = solver.v[: len(buses)]
        f = sim.model["f"] * (1 + ps.pll["PLL1"].freq_est(solver.y, solver.v))
        values = np.column_stack([np.abs(v) * v_n, np.degrees(np.angle(v)), f]).ravel()
        yield PmuFrame(
            timestamp=T0 + timedelta(seconds=n / RATE_HZ), mRID="n44-tops", header=header, values=values.tolist()
        )
        n += 1


def main() -> None:
    module = IslandingDetectionModule()
    # last = None
    for frame in simulate():
        for message in module.run(frame):
            if isinstance(message, AlarmEvent):
                print(f"{(message.timestamp - T0).total_seconds():5.1f} s: ALARM {message.type}: {message.message}")
                continue
            islands = message.result.islands
            # if islands != last:
            t = (frame.timestamp - T0).total_seconds()
            print(f"{t:5.1f} s: islands {islands}")
            # last = islands


if __name__ == "__main__":
    main()
