"""Record five seconds of synthetic frames, then read them back: no server, no event loop.

    uv run python modules/recorder/examples/record_and_replay.py [folder]
"""

import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.recorder import Recorder

RATE = 50
HEADER = PmuHeader(
    station=["3000", "3000"], channel=["V", "f"], measurement=["V_Magnitude", "f"], units=["kV", "Hz"], data_rate=RATE
)


def synthetic_frames(seconds: float, start: datetime):
    for i in range(int(seconds * RATE)):
        yield PmuFrame(
            timestamp=start + timedelta(seconds=i / RATE),
            mRID="example",
            header=HEADER,
            values=[420.0 + 0.1 * (i % 10), 50.0 + 0.001 * (i % 7)],
        )


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="recorder-"))
    start = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)

    recorder = Recorder(dir=folder)
    for frame in synthetic_frames(5, start):
        recorder.run(frame)  # records; publishes nothing
    recorder.flush()

    held = Recorder(dir=folder)
    coverage = held.coverage()
    print(f"{folder}: holds {coverage.start:%H:%M:%S.%f} to {coverage.end:%H:%M:%S.%f}")
    second = list(held.read(start + timedelta(seconds=2), start + timedelta(seconds=3)))
    print(f"the third second: {len(second)} frames, first at {second[0].timestamp:%H:%M:%S.%f}")


if __name__ == "__main__":
    main()
