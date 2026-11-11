# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""SCADA scans: the latest value of every SCADA measurement of the grid, at once (ADR-017).

A scan's values point at the grid's own measurements, the ``Analog``s and
``Discrete``s of its Operation profile whose values come from the SCADA
``MeasurementValueSource``. Today the live simulation (``rtsim-from-cim``) is
the one producer; a real SCADA feed would publish the same message.
"""

from .scan import AnalogReading, DiscreteReading, ScadaScan

__all__ = ["AnalogReading", "DiscreteReading", "ScadaScan"]
