"""The State Estimator module: one ``PmuFrame`` in, one ``StateEstimatorResult`` out.

The analysis is a placeholder: the station with the highest frequency in each
frame. It is a plain function, ``highest_frequency``; ``process`` only adapts a
frame to it and its answer to a result. Replace the function and the
``StateEstimatorBody`` it fills (in ``pswamp_models.state_estimator``) with yours, keeping
that split.

``process`` is plain synchronous code returning the body; the base class wraps
it in ``StateEstimatorResult``. The same module runs hosted, or from a script::

    StateEstimatorModule().run_one(frame).result

This one keeps no state between frames. One that does (a window, a count)
clears it in ``reset``, which its host calls when the stream starts over (a
seek, a loop), and releases what ``setup`` took in ``teardown``.

To read the grid, set ``cim = True`` (and depend on ``pswamp-core[cim]``):
``self.cim_repo`` is then a LazyCIM repository of this instance's own over the
CIM graph, and ``frame.header.analog[i]`` the Analog column ``i`` measures::

    analog = self.cim_repo.from_mRID(frame.header.analog[i])
    analog.Terminal.ConnectivityNode.name

The core keeps that repository up to date before each call; anything derived from
the graph is rebuilt in ``cim_changed``, which it calls when the graph changed.
"""

from pswamp_core.modules import Module
from pswamp_models.state_estimator import StateEstimatorBody, StateEstimatorResult
from pswamp_models.pmu import PmuFrame

__all__ = ["StateEstimatorModule", "highest_frequency"]


def highest_frequency(stations: list[str], frequencies: list[float | None]) -> tuple[str, float] | None:
    """The station with the highest frequency, and that frequency; ``None``
    when no station has a value."""
    readings = [(hz, station) for station, hz in zip(stations, frequencies) if hz is not None]
    if not readings:
        return None
    hz, station = max(readings)
    return station, hz


class StateEstimatorModule(Module):
    name = "state-estimator"
    inputs = (PmuFrame,)
    outputs = (StateEstimatorResult,)
    # cim = True  # read the CIM graph through self.cim_repo

    def process(self, frame: PmuFrame) -> StateEstimatorBody | None:
        columns = frame.header.columns(measurement="f")
        peak = highest_frequency([frame.header.station[i] for i in columns], [frame.values[i] for i in columns])
        if peak is None:
            return None  # publish nothing for this frame
        station, hz = peak
        return StateEstimatorBody(station=station, frequency_hz=hz)
