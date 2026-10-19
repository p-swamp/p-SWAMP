"""Frame statistics of the live grid simulation, over a LazyCIM store of the script's own.

The grid is Nordic44, one of LazyCIM's demo models, in an **embedded Oxigraph** store (pyoxigraph):
no server, no Docker, no p-SWAMP store. Any LazyCIM repository would do; this is how a script
brings its own. ``prepare`` gives it what p-SWAMP needs (machine dynamics, PMU Analogs). The live
simulation is named by its entry point, never imported: a module, and its examples, import no
other module. A few seconds in, the script **edits the graph** (the largest load steps up, or
``--breaker`` opens a breaker); the simulation, which looks at a store with no version stamp every
couple of seconds, follows. Each frame goes through ``FrameStatsModule.run_one``.

    uv run --package pswamp-frame-stats --extra rtsim python modules/frame-stats/examples/rtsim_frame_stats.py [--save fs.png]

Nordic44 is downloaded by LazyCIM once, into its cache (``python -m lazycim.demo`` fills it ahead).
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from lazycim import CIMRepository, F, L, OxigraphBackend
from lazycim.demo import CIM100, cgmes_profile_files, nordic44_files

from pswamp_core.cim import prepare
from pswamp_core.scripts import source
from pswamp_core.util.time import utcnow
from pswamp_modules.frame_stats import FrameStatsModule


def nordic44() -> OxigraphBackend:
    """Nordic44 and the CGMES vocabularies (Dynamics included), one named graph per profile."""
    store = OxigraphBackend("nordic44")
    store.load_cgmes(nordic44_files(), cgmes_profile_files(dynamics=True))
    return store


def repository(store: OxigraphBackend) -> CIMRepository:
    return CIMRepository(store, default_namespace=CIM100, graphs="discover")


def disturb(store: OxigraphBackend, breaker: str | None, step: float) -> str:
    """Edit the graph through a repository of the script's own (the simulation owns the other)."""
    edit = repository(store)
    if breaker:
        edit.from_mRID(breaker).open = True
        what = f"breaker {breaker} opened"
    else:
        loads = edit.query(L.EnergyConsumers).to_dataframe(mRID=F.mRID, name=F.name, p=F.p)
        largest = loads.loc[loads.p.idxmax()]
        target = edit.from_mRID(largest.mRID)
        target.p = float(largest.p) * (1 + step)
        what = f"load {largest['name']} stepped from {largest.p:.0f} to {target.p:.0f} MW"
    edit.commit()
    return what


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=20.0, help="how long to read, once the model is running")
    parser.add_argument("--at", type=float, default=4.0, help="seconds before the graph is edited")
    parser.add_argument("--step", type=float, default=0.5, help="the largest load's step, as a fraction of its P")
    parser.add_argument("--breaker", help="open this breaker (an mRID) instead of stepping a load")
    parser.add_argument("--save", metavar="PATH", help="write the plot to this file instead of showing it")
    args = parser.parse_args()

    print("loading Nordic44 into an embedded Oxigraph store ...")
    store = nordic44()
    print(f"{prepare(repository(store))} PMU Analogs added")
    # Read through a repository made after prepare, so it sees the graphs prepare created.
    sim = source("rtsim-from-cim", repo=repository(store))
    stats = FrameStatsModule()

    print("starting the simulation ...")
    seconds, results, edited = [], [], None
    for frame in sim.read(end=utcnow() + timedelta(seconds=args.seconds + 120)):
        t = len(results) / frame.header.data_rate
        if t >= args.seconds:
            break
        if edited is None and t >= args.at:
            print(f"t={t:.1f} s: {disturb(store, args.breaker, args.step)}")
            edited = t
        seconds.append(t)
        results.append(stats.run_one(frame).result)

    lowest = min(results, key=lambda r: r.mean_frequency_hz)
    print(f"{len(results)} frames; lowest mean frequency {lowest.mean_frequency_hz:.4f} Hz")
    try:
        import matplotlib
    except ImportError:
        for t, r in list(zip(seconds, results))[:: int(frame.header.data_rate)]:
            print(f"  t={t:4.1f} s  mean {r.mean_frequency_hz:.4f} Hz  mean voltage {r.mean_voltage_kv:.1f} kV")
        return
    if args.save:
        matplotlib.use("Agg")  # no display needed to write a file
    import matplotlib.pyplot as plt

    figure, (frequency, voltage) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    frequency.plot(seconds, [r.mean_frequency_hz for r in results], label="mean")
    frequency.fill_between(
        seconds, [r.min_frequency_hz for r in results], [r.max_frequency_hz for r in results], alpha=0.3, label="min to max"
    )
    voltage.plot(seconds, [r.mean_voltage_kv for r in results])
    for axes in (frequency, voltage):
        if edited is not None:
            axes.axvline(edited, color="grey", linestyle="--", label="the graph is edited" if axes is frequency else None)
    frequency.set(ylabel="frequency (Hz)", title="frame-stats over the live simulation of Nordic44")
    voltage.set(xlabel="simulated time (s)", ylabel="mean voltage (kV)")
    frequency.legend()
    figure.tight_layout()
    if args.save:
        figure.savefig(args.save, dpi=120)
        print(f"saved {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
