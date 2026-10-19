"""Run the live grid simulation from a plain script: no server, no transport, no asyncio.

It simulates a grid in real time (the sample grid the core ships; ``--nordic44`` for Nordic44, which
LazyCIM downloads on first use), opens a breaker a few seconds in **by editing the graph**, and plots
the frequency of the substations. A source is read like any iterable; the graph is how it is steered.
With no web backend there is no writer, so the script edits its own in-process graph
(``pswamp_core.cim.testing.edit``), which a deployment never does.

    uv run --package pswamp-rtsim-from-cim --extra examples python modules/rtsim-from-cim/examples/run_rtsim.py [--save f.png]

``--save`` writes a PNG instead of opening a window. ``--breaker`` names the breaker to open (by mRID).
"""

import argparse
from datetime import timedelta

import matplotlib

from pswamp_core.cim import SAMPLE_GRID, CimSettings
from pswamp_core.cim.testing import edit
from pswamp_core.util.time import utcnow
from pswamp_modules.rtsim_from_cim import RtsimFromCimSource

BAY_BREAKER = "3f5e0000-0000-4000-8000-0000000000a1"  # the sample grid's Alpha-Gamma bay breaker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=10.0, help="how long to read, after the model has loaded")
    parser.add_argument("--at", type=float, default=2.0, help="seconds before the breaker opens")
    parser.add_argument("--nordic44", action="store_true", help="simulate Nordic44 instead of the sample grid")
    parser.add_argument("--breaker", default=BAY_BREAKER, help="the mRID of the breaker to open")
    parser.add_argument("--save", help="write the plot to this PNG instead of showing it")
    args = parser.parse_args()
    if args.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    settings = CimSettings() if args.nordic44 else CimSettings(cim_path=SAMPLE_GRID)
    source = RtsimFromCimSource(graph=settings)
    print("loading the model ...")
    frequency, out = [], False
    for i, frame in enumerate(source.read(end=utcnow() + timedelta(seconds=args.seconds + 60))):
        t = i / frame.header.data_rate
        if t >= args.seconds:
            break
        if t >= args.at and not out:
            edit(settings, args.breaker, open=True)  # the graph, not the source
            print(f"{args.breaker} opened")
            out = True
        f = [v for v, m in zip(frame.values, frame.header.measurement, strict=True) if m == "f" and v is not None]
        frequency.append((t, min(f), sum(f) / len(f), max(f)))
    figure, axes = plt.subplots(figsize=(8, 4))
    ts = [f[0] for f in frequency]
    axes.plot(ts, [f[2] for f in frequency], label="mean")
    axes.fill_between(ts, [f[1] for f in frequency], [f[3] for f in frequency], alpha=0.25, label="min to max")
    axes.axvline(args.at, color="grey", linestyle="--", label="the breaker opens")
    axes.set(xlabel="simulated time (s)", ylabel="frequency (Hz)", title="Substation frequency after a breaker opens")
    axes.legend()
    figure.tight_layout()
    if args.save:
        figure.savefig(args.save, dpi=120)
        print(f"wrote {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
