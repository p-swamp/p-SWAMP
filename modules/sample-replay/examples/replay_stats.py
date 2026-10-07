"""Replay the sample recording through the frame statistics module, in a plain script.

A source is read with a ``for`` loop and a module is called like a function: no
server, no transport, no event loop. The recording is three seconds of the
Nordic 44 simulation, five stations at 20 Hz, spanning a line trip.

    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py
    uv run --package pswamp-sample-replay --extra examples python modules/sample-replay/examples/replay_stats.py --save fs.png

``--extra examples`` brings matplotlib and the frame-stats module, neither of
which the source itself needs. ``--save`` writes the plot to a file instead of
opening a window.
"""

import sys

import matplotlib

if "--save" in sys.argv:
    matplotlib.use("Agg")  # no display needed to write a file
import matplotlib.pyplot as plt

from pswamp_modules.frame_stats import FrameStatsModule
from pswamp_modules.sample_replay import SampleReplay

frames = list(SampleReplay().read())

stats = FrameStatsModule()
results = [stats.run_one(frame).result for frame in frames]

seconds = [(frame.timestamp - frames[0].timestamp).total_seconds() for frame in frames]
plt.plot(seconds, [r.mean_frequency_hz for r in results], label="mean")
plt.fill_between(
    seconds, [r.min_frequency_hz for r in results], [r.max_frequency_hz for r in results], alpha=0.3, label="min to max"
)
plt.xlabel("time (s)")
plt.ylabel("frequency (Hz)")
plt.title("frame-stats over the sample recording")
plt.legend()

if "--save" in sys.argv:
    plt.savefig(sys.argv[sys.argv.index("--save") + 1])
else:
    plt.show()
