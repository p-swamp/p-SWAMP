"""The State Estimator over the live simulation of Nordic44, with no server: a line trips.

The grid, the events, the modules and the plot are this script's; the rest (the store, the
simulation, feeding the modules) is ``pswamp_modules.state_estimator.offline``.

    uv run --package pswamp-state-estimator --extra rtsim python modules/state-estimator/examples/run_state_estimator.py [--save se.png]
"""

import argparse
from pathlib import Path

from pswamp_models.rtsim import TripBranchCommand
from pswamp_modules.state_estimator import StateEstimatorModule
from pswamp_modules.state_estimator.offline import Grid, simulate

GRID = Path("grids/nordic44")  # a folder of CGMES files; None: LazyCIM's Nordic44
SECONDS = 10.0
TRIP_AT, TRIP_LINE = 4.0, "300SIMA-BLAFALLI"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", metavar="PATH", help="write the plot to this file instead of showing it")
    args = parser.parse_args()

    grid = Grid.load(GRID if GRID and GRID.exists() else None)
    events = [(TRIP_AT, TripBranchCommand(mRID=grid.mrid(TRIP_LINE, "ACLineSegment")))]
    estimator = StateEstimatorModule(period=0.1)
    run = simulate(grid, [estimator], SECONDS, events)

    import matplotlib

    if args.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t, results = run.results(estimator)
    figure, axes = plt.subplots(figsize=(8, 4))
    stations = [b.station for b in results[0].buses]
    v_pu = [[b.v_pu if b.v_pu is not None else float("nan") for b in r.buses] for r in results]
    axes.plot(t, v_pu, linewidth=0.8)
    for at, event in run.events:
        axes.axvline(at, color="grey", linestyle="--")
        axes.annotate(f"{event.kind} ({event.cause})", (at, 1), xycoords=("data", "axes fraction"), rotation=90, va="top")
    axes.set(xlabel="simulated time (s)", ylabel="voltage (p.u.)", title=f"Estimated voltage, {len(stations)} stations")
    figure.tight_layout()
    if args.save:
        figure.savefig(args.save, dpi=120)
        print(f"saved {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
