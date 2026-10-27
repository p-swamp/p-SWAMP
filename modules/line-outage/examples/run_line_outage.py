"""Run the Line outage module over a synthetic line trip, with no server.

    uv run python modules/line-outage/examples/run_line_outage.py
"""

from datetime import datetime, timedelta, timezone

from pswamp_models.pmu import PmuFrame, PmuHeader
from pswamp_modules.line_outage import LineOutageModule

RATE = 50.0
header = PmuHeader(
    station=["A", "B"], channel=["I_AB", "I_AB"], measurement=["I_Magnitude"] * 2, units=["A"] * 2, data_rate=RATE
)
t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
module = LineOutageModule()

# 4 s of current, the line out from 1 s to 3 s.
for k in range(int(4 * RATE)):
    current = 0.0 if 1 <= k / RATE < 3 else 400.0
    frame = PmuFrame(mRID="example", timestamp=t0 + timedelta(seconds=k / RATE), header=header, values=[current] * 2)
    for result in module.run(frame):
        for change in result.result.changes:
            stations = ", ".join(current.station for current in change.currents)
            print(f"{k / RATE:5.2f} s  {change.kind:10}  {stations}")
