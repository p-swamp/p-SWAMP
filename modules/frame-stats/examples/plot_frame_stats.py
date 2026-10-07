"""Plot the frame statistics of a synthetic frequency dip, with no server.

Three stations at 50 frames per second for ten seconds; at t = 3 s the
frequency dips by 0.2 Hz and recovers. Each frame goes through
``FrameStatsModule`` with a plain synchronous call, ``run_one``, which returns
the ``FrameStatsResult`` the module would publish when hosted. No server, no
transport, no event loop.

    uv run --package pswamp-frame-stats --extra examples python modules/frame-stats/examples/plot_frame_stats.py
    uv run --package pswamp-frame-stats --extra examples python modules/frame-stats/examples/plot_frame_stats.py --save fs.png

``--extra examples`` brings matplotlib, which the module itself does not need.
Without it (plain ``uv run python modules/frame-stats/examples/plot_frame_stats.py``)
the script prints the statistics instead of plotting them.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta, timezone

from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.frame_stats import FrameStatsModule

RATE_HZ = 50.0
STATIONS = ["A", "B", "C"]
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Per station: voltage magnitude (kV), voltage angle (deg) and frequency (Hz).
HEADER = PmuHeader(
    station=[s for s in STATIONS for _ in range(3)],
    channel=["V", "V", "f"] * len(STATIONS),
    measurement=["V_Magnitude", "V_Angle", "f"] * len(STATIONS),
    units=["kV", "deg", "Hz"] * len(STATIONS),
    data_rate=RATE_HZ,
)


def frequency_at(t: float, station: int) -> float:
    """50 Hz, then a 0.2 Hz dip from t = 3 s that recovers over a couple of seconds."""
    dip = 0.0 if t < 3.0 else -0.2 * math.exp(-(t - 3.0) / 1.5) * math.cos(2.0 * (t - 3.0))
    return 50.0 + dip + 0.002 * station


def synthetic_frames(seconds: float = 10.0) -> list[PmuFrame]:
    frames = []
    for n in range(int(seconds * RATE_HZ)):
        t = n / RATE_HZ
        values: list[float | None] = []
        for i, _ in enumerate(STATIONS):
            values += [400.0 + 2.0 * i, 10.0 * i + 5.0 * (frequency_at(t, i) - 50.0), frequency_at(t, i)]
        frames.append(PmuFrame(timestamp=T0 + timedelta(seconds=t), mRID="synthetic", header=HEADER, values=values))
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", metavar="PATH", help="write the plot to this file instead of showing it")
    args = parser.parse_args()

    stats = FrameStatsModule()
    frames = synthetic_frames()
    results = [stats.run_one(frame).result for frame in frames]
    seconds = [(frame.timestamp - T0).total_seconds() for frame in frames]

    lowest = min(results, key=lambda r: r.mean_frequency_hz)
    print(f"{len(results)} frames; lowest mean frequency {lowest.mean_frequency_hz:.4f} Hz")

    try:
        import matplotlib
    except ImportError:
        for r, s in list(zip(results, seconds))[:: int(RATE_HZ)]:
            print(f"  t={s:4.1f} s  mean {r.mean_frequency_hz:.4f} Hz  angle spread {r.angle_spread_deg:.3f} deg")
        hint = "matplotlib is not installed: add `--package pswamp-frame-stats --extra examples` to `uv run`"
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
    ax.set_title("frame-stats over a synthetic frequency dip")
    ax.legend()
    fig.tight_layout()
    if args.save:
        fig.savefig(args.save)
        print(f"saved {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
