# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import threading
import time

import numpy as np
from PySide6 import QtWidgets

from pswamp import load_config
from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.coordination.alarm_handling import AlarmMonitor
from pswamp.gui.alarms.views.interactive import InteractiveAlarmView
from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3DLayers
from pswamp.gui.grid_view.dim_3d.layers import Islanding
from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
from pswamp.models.line import Line
from pswamp.styles import colors
from pswamp.styles.colors import gl_color
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
from pswamp.utils.misc import flatten_array_insert_nan
from pswamp.visualization.components.phasor_plot import PhasorBasePlot, xy_from_phasors
from pswamp.gui.alarms.views.islanding import IslandingAlarmView



if __name__ == "__main__":
    from pswamp.gui.grid_view.grid_view_container import GridViewContainer

    config = load_config("../config_no.toml")
    print(config["streaming"]["bootstrap_servers"])
    config["streaming"]["bootstrap_servers"] = "localhost:40000"

    run_online = True
    if run_online:
        config["streaming"]["consumers_seek_to_beginning"] = True
        

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

        alarm_view = IslandingAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view
        )
        alarm_view.show()
        app.exec()
