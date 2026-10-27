"""Run the Islanding module over a synthetic islanding-detection case, with no server.

``run`` is a plain synchronous call returning what the module would publish
when hosted (a list: empty when it publishes nothing for a frame). No server,
no transport, no event loop.

    uv run python modules/islanding-detection/examples/run_islanding_detection.py
"""

from datetime import datetime, timedelta, timezone

from pswamp_models.common import AlarmEvent
from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.islanding_detection import IslandingDetectionModule
from pswamp_modules.islanding_detection.synthetic_cases import islanding_test_case_1

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
time_stamps, frequency = islanding_test_case_1()
n_channels = frequency.shape[1]
HEADER = PmuHeader(
    station=[f"S{i}" for i in range(n_channels)],
    channel=["f"]*n_channels,
    measurement=["f"]*n_channels,
    units=["Hz"]*n_channels,
    data_rate=50.0
)
READINGS = frequency

def main() -> None:
    module = IslandingDetectionModule()
    for n, values in enumerate(READINGS):
        frame = PmuFrame(timestamp=T0 + timedelta(seconds=n / 50), mRID="synthetic", header=HEADER, values=values)
        for message in module.run(frame):
            if isinstance(message, AlarmEvent):
                print(f"{n / 50:6.1f} s: ALARM {message.type}: {message.message}")
            else:
                print(f"{n / 50:6.1f} s: {message.result.status}, islands {message.result.islands}")


if __name__ == "__main__":
    main()
