# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore, QtGui
from pswamp import load_config
from pswamp.coordination.alarm_handling import AlarmMonitor
from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
from pswamp.visualization.time_window_plot import TimeSeriesPlot
import threading
import datetime
from pswamp.streaming import consumer_seek_relative_offset
import time
from pswamp.visualization.voltage_phasor_plot import VoltagePhasorPlot
from pswamp.visualization.components.phasor_plot import (
    PhasorPlotFast,
    PhasorPlotFastFancy,
    PhasorBasePlot,
    xy_from_phasors,
)
from pswamp.utils.misc import convert_time_stamp_to_seconds, flatten_array_insert_nan
from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.styles import colors
from pswamp.gui.grid_view.dim_3d.layers import Islanding
from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3DLayers
from pswamp.utils.get_station_coords import (
    load_bus_coords_for_stations,
    load_bus_coords_for_current_stations,
)
from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
from pswamp.styles.colors import gl_color
from pswamp.models.line import Line
from pswamp.gui.alarms.views.interactive import InteractiveAlarmView
from pswamp.gui.alarms.views.islanding import IslandingResultKeeper as AppResultKeeper
from pswamp.utils.misc import lookup_strings
from pswamp.visualization.eigenvalue_plot import EigenvaluePlot
from pswamp.gui.alarms.views.oscillations import OscillationAlarmView


if __name__ == "__main__":
    from pswamp.gui.grid_view.grid_view_container import GridViewContainer

    # config = load_config()
    config = load_config("../config_se.toml")

    run_online = True
    if run_online:
        # config["streaming"]["consumers_seek_to_beginning"] = True
        # config["streaming"]["bootstrap_servers"] = "localhost:40000"
        # config["streaming"]['bootstrap_servers'] = 'localhost:45001'

        alarm_monitor = AlarmMonitor(
            io_kwargs=config["streaming"],
            alarm_topic=config["topics"]["alarms"],
        )
        alarm_monitor.start()
        import time

        while True:
            try:
                alarm_uuid = list(alarm_monitor.alarm_data.keys())[-1]
                alarm_data = list(alarm_monitor.alarm_data.values())[-1]
                break
            except IndexError:
                time.sleep(1)
                pass

        config["streaming"]["consumers_seek_to_beginning"] = False
        app = QtWidgets.QApplication()

        grid_view = GridViewContainer(config, True)
        grid_view.show()

        alarm_view = OscillationAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view
        )
        alarm_view.show()
        app.exec()
