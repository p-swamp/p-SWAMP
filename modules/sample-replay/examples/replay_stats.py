"""Replay the sample recording through the frame statistics module, with no server.

``SampleReplay().read()`` is a plain iterator of the recording's ``PmuFrame``s
and ``FrameStatsModule().run_one`` a plain call: no server, no transport, no
event loop. The recording is three seconds of the Nordic 44 simulation, five
stations at 20 Hz, spanning a line trip.

    uv run python modules/sample-replay/examples/replay_stats.py
    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py
    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py --save fs.png

The module and the source are both installed in the workspace environment, so
the first form works as it is; ``--extra examples`` brings matplotlib, which
the source does not need. Without it the script prints the statistics instead
of plotting them.
"""

from __future__ import annotations

import argparse
import sys

from pswamp_modules.frame_stats import FrameStatsModule
from pswamp_modules.sample_replay import SampleReplay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", metavar="PATH", help="write the plot to this file instead of showing it")
    args = parser.parse_args()

    stats = FrameStatsModule()
    frames = list(SampleReplay().read())
    results = [stats.run_one(frame).result for frame in frames]
    start = frames[0].timestamp
    seconds = [(frame.timestamp - start).total_seconds() for frame in frames]

    lowest = min(results, key=lambda r: r.mean_frequency_hz)
    widest = max(results, key=lambda r: r.angle_spread_deg)
    print(
        f"{len(results)} frames over {seconds[-1]:.2f} s; "
        f"lowest mean frequency {lowest.mean_frequency_hz:.4f} Hz, "
        f"widest angle spread {widest.angle_spread_deg:.2f} deg"
    )

    try:
        import matplotlib
    except ImportError:
        for r, s in list(zip(results, seconds))[::10]:
            print(f"  t={s:5.2f} s  mean {r.mean_frequency_hz:.4f} Hz  angle spread {r.angle_spread_deg:.2f} deg")
        hint = "matplotlib is not installed: add `--package pswamp-sample-replay --extra examples` to `uv run`"
        if args.save:
            sys.exit(f"cannot save a plot: {hint}")
        print(f"(to plot: {hint})")
        return

    if args.save:
        matplotlib.use("Agg")  # no display needed to write a file
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(seconds, [r.mean_frequency_hz for r in results], label="mean")
    ax.fill_between(
        seconds, [r.min_frequency_hz for r in results], [r.max_frequency_hz for r in results], alpha=0.3, label="min to max"
    )
    ax.set_xlabel("time (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.set_title("frame-stats over the sample recording")
    ax.legend()
    fig.tight_layout()
    if args.save:
        fig.savefig(args.save)
        print(f"saved {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
