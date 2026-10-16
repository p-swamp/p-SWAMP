# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Record a Nordic 44 PMU stream to a replayable dataset.

Run once, by hand, to produce the artifact the server replays. It needs the
simulator, which lives in p-SWAMP's ``[full]`` extra and is therefore *not* in
this project's environment -- so run it with the desktop package's own
interpreter (``uv sync --extra full`` in desktop/, which also needs fastapi on
the path, see AGENTS.md), pointed at this source tree:

    PYTHONPATH=app/server-python/src \
      desktop/.venv/bin/python app/server-python/tools/record_n44_dataset.py

Nothing that *consumes* a recording needs any of that: the server reads the
resulting .npz with numpy alone.

What is recorded are decoded rows -- the ``(time, measurements)`` an application
sees after ``PMUDecoder`` -- rather than raw C37.118 frames. The frames are
produced by the real ``SimplePMU`` and decoded by the real ``PMUDecoder``, so
the rows are identical to what the live path yields, but replaying them needs
neither the C37.118 implementation nor the per-frame decoding cost.

The scenario is the one from ``desktop/tests/monitoring/test_islanding.py``: four lines
trip at t=20 s and reconnect at t=40 s, splitting the northern part of the grid
into its own frequency island. That disturbance is the point of the recording,
so :func:`verify` re-runs the real islanding detector over the finished data and
refuses to write a file that does not reproduce it.
"""

import argparse
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DEFAULT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "pswamp_web"
    / "data"
    / "n44_line_trip_50hz.npz"
)

# Verbatim from desktop/tests/monitoring/test_islanding.py. Disconnecting these four
# lines is what severs the northern buses from the rest of the system.
EVENTS = [
    (20.0, ("line", "L3244-6500", "disconnect")),
    (20.0, ("line", "L5100-6500", "disconnect")),
    (20.0, ("line", "L3115-6701", "disconnect")),
    (20.0, ("line", "L3701-6700", "disconnect")),
    (40.0, ("line", "L3244-6500", "connect")),
    (40.0, ("line", "L5100-6500", "connect")),
    (40.0, ("line", "L3115-6701", "connect")),
    (40.0, ("line", "L3701-6700", "connect")),
]

# Voltage and frequency only. The current channels (one per line, trafo, load and
# generator incident on each bus) quadruple the width, and nothing that reads
# this recording today looks at them. Use --channels all to keep them.
VOLTAGE_MEASUREMENTS = ("f", "Df", "v_Magnitude", "v_Angle")


class Events:
    """Applies scheduled grid events to a running simulation.

    Same shape as the class in ``n44_rtsim_offline.py``; kept here so the
    generator is self-contained and the event list above is the only definition
    of the scenario.
    """

    def __init__(self, events):
        self.pending = sorted(events, key=lambda e: e[0])
        self.applied = []

    def update(self, sim):
        while self.pending and self.pending[0][0] <= sim.sol.t:
            t, (kind, name, action) = self.pending.pop(0)
            if kind == "line":
                sim.ps.lines["Line"].event(sim.ps, name, action)
            self.applied.append({"t": t, "kind": kind, "name": name, "action": action})


def _make_publisher(rts, fs):
    """Build a PMU publisher that decodes into memory instead of sending.

    Two deviations from ``PMUToKafkaPublisher``, both deliberate:

    * The PMU is given a fake connected client, so ``update`` believes a PDC is
      listening and actually encodes a frame. Same trick as the Kafka publisher.
    * The threaded interfacer is bypassed. ``InterfacerQueues.interface_fun``
      discards any queued sample before enqueuing a new one -- it is built to
      keep a live consumer on the newest data, not to deliver every sample. With
      the simulation running as fast as it can, that drops most of the stream and
      leaves gaps in the recording. Driving ``update`` straight from the
      simulation loop keeps every sample and removes the thread entirely.
    """
    from queue import Queue

    from topsrt.pmu_v2 import PMUPublisherV2

    from pswamp.utils.pypmu import PMUDecoder

    class PMUToRecording(PMUPublisherV2):
        def initialize(self, *args, **kwargs):
            super().initialize(*args, **kwargs)
            self.pmu.pmu.client_buffers = [Queue()]
            self.pmu.pmu.clients = [None]
            # Record raw frequencies: the zero-to-NaN substitution is a decoding
            # choice, and baking it in here would take that choice away from
            # whoever replays the file.
            self.decoder = PMUDecoder(substitute_zero_freq_with_nan=False)
            self.header = self.decoder.generate_header(config_frame=self.pmu.pmu.cfg2)
            self.times = []
            self.rows = []

        def update(self, input_signal):
            super().update(input_signal)
            frame = self.pmu.pmu.client_buffers[0].get()
            t, row = self.decoder.data_frame_to_row(frame)
            self.times.append(t)
            self.rows.append(row)

    publisher = PMUToRecording(rts=rts, publish_frequency=fs)

    name = publisher.interface_name_unique
    interval = 1.0 / fs

    def record_synchronously(sim, _p=publisher, _name=name, _dt=interval):
        if sim.sol.t < sim.interface_timers[_name]:
            return
        sim.interface_timers[_name] += _dt
        _p.update(_p.read_input_signal(sim))

    rts.interface_functions[name] = record_synchronously
    return publisher


def _git_revision():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def record(fs=50, t_end=70.0, dt=10e-3, channels="voltage"):
    """Run the simulation and return the resulting :class:`Recording`."""
    from topsrt.sim import RealTimeSimulatorThread

    from pswamp_web.recorded_io import HEADER_ROWS, Recording

    from pswamp.test_utils.sample_datasets.n44.sim import create_sim

    print(f"building Nordic 44 simulation (dt={dt}s, t_end={t_end}s, fs={fs}Hz)")
    ps = create_sim()

    # speed=inf: run as fast as the solver allows. The recording carries
    # simulation time, so wall-clock pacing is the player's job, not ours.
    rts = RealTimeSimulatorThread(ps, dt=dt, t_end=t_end, speed=np.inf)
    events = Events(EVENTS)
    rts.interface_functions["Events"] = events.update

    publisher = _make_publisher(rts, fs)

    t_0 = time.time()
    rts.run()
    print(f"simulated {t_end}s in {time.time() - t_0:.1f}s wall clock")

    time_vec = np.asarray(publisher.times, dtype=np.float64)
    data = np.asarray(publisher.rows, dtype=np.float32)
    header = {row: np.asarray(publisher.header[row]) for row in HEADER_ROWS}

    recording = Recording(
        header=header,
        time=time_vec,
        data=data,
        data_rate=float(fs),
        events=tuple(events.applied),
        source=(
            f"Nordic 44 TOPS simulation, p-SWAMP {_git_revision()}, "
            f"recorded {datetime.now(timezone.utc):%Y-%m-%d}"
        ),
    )

    if channels == "voltage":
        keep = np.where(np.isin(header["measurement"], VOLTAGE_MEASUREMENTS))[0]
        recording = recording.select(keep)

    return recording


def verify(recording):
    """Check the recording actually contains the disturbance it exists for.

    Runs the real islanding detector over it. A recording where the trip does
    not produce a detectable island is useless as a fixture, and committing one
    would turn every consumer's assertion into a mystery.
    """
    from pswamp.monitoring.islanding import IslandingApp
    from pswamp_web.recorded_io import LabeledRowDecoder, RecordingPlayer

    freq = recording.data[:, recording.col_idx(measurement="f")]
    median = float(np.nanmedian(freq[freq != 0]))
    print(f"  median frequency: {median:.4f} Hz")
    assert 49.0 < median < 51.0, (
        f"frequency channels look wrong: median {median} Hz. Expected absolute "
        "Hz around the 50 Hz nominal, not a per-unit or deviation value."
    )

    mag = recording.data[:, recording.col_idx(measurement="v_Magnitude")]
    median_v = float(np.nanmedian(mag))
    print(f"  median voltage magnitude: {median_v / 1e3:.1f} kV")
    assert 1e4 < median_v < 1e6, f"voltage magnitudes look wrong: {median_v}"

    results = []
    player = RecordingPlayer(
        recording, speed=200.0, loop=False, rebase_to_wallclock=False
    )
    io = player.subscribe(
        publish=lambda topic, payload: results.append((topic, payload))
    )
    app = IslandingApp(
        io=io, input_decoder=LabeledRowDecoder, window_length=10, eval_freq=1
    )
    player.start()
    app.run_in_thread()
    while player._thread is not None and player._thread.is_alive():
        time.sleep(0.05)
    time.sleep(0.5)
    app.stop()
    player.stop()

    stations = np.asarray(app.tw.header["station"])
    detections = [
        (
            payload["result"]["time_stamp"],
            sorted(
                {
                    str(stations[i])
                    for island in payload["result"]["islands"]
                    for i in island
                }
            ),
        )
        for topic, payload in results
        if topic == "result" and payload.get("result")
    ]
    t_trip = min(t for t, _ in EVENTS)
    t_reconnect = max(t for t, _ in EVENTS)

    quiet = [(t, s) for t, s in detections if t < t_trip]
    active = [(t, s) for t, s in detections if t_trip + 2 < t < t_reconnect]
    print(
        f"  {len(detections)} evaluations; islands before trip: "
        f"{sum(1 for _, s in quiet if s)}, during: {sum(1 for _, s in active if s)}"
    )

    assert detections, "islanding application produced no evaluations at all"
    assert not any(s for _, s in quiet), "islands detected before the trip"
    assert any(s for _, s in active), "no island detected while lines were open"

    islanded = next(s for _, s in active if s)
    print(f"  islanded stations: {islanded}")
    return islanded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--fs", type=int, default=50, help="publish rate in Hz")
    parser.add_argument("--t-end", type=float, default=70.0)
    parser.add_argument(
        "--channels",
        choices=("voltage", "all"),
        default="voltage",
        help="'voltage' keeps frequency and voltage phasors; 'all' also keeps "
        "the per-branch current channels (roughly four times the size)",
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="write without checking the scenario"
    )
    args = parser.parse_args()

    recording = record(fs=args.fs, t_end=args.t_end, channels=args.channels)
    print(
        f"recorded {recording.n_samples} samples x {recording.n_channels} channels "
        f"({recording.data.nbytes / 1e6:.1f} MB raw)"
    )
    print(f"  events applied: {len(recording.events)}")

    if not args.no_verify:
        print("verifying scenario:")
        verify(recording)

    recording.save(args.out)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB compressed)")


if __name__ == "__main__":
    main()
