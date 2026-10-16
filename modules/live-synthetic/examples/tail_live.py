"""Print two seconds of the synthetic live feed, with no server.

The synchronous ``read`` runs the feed on a private event loop; without an
``end`` it would never stop, so the script bounds it.

    uv run python modules/live-synthetic/examples/tail_live.py
"""

from __future__ import annotations

from datetime import timedelta

from pswamp_core.util.time import utcnow
from pswamp_modules.live_synthetic import LiveSynthetic


def main() -> None:
    feed = LiveSynthetic()
    stations = feed.recording.header.stations
    print(f"{feed.source}: {len(stations)} stations, {feed.recording.header.data_rate:g} Hz")
    for frame in feed.read(end=utcnow() + timedelta(seconds=2)):
        frequencies = [v for v, m in zip(frame.values, frame.header.measurement) if m == "f"]
        print(f"  {frame.timestamp:%H:%M:%S.%f}  mean frequency {sum(frequencies) / len(frequencies):.4f} Hz")


if __name__ == "__main__":
    main()
