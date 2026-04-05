# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
import pswamp.gui.grid_view.dim_2d.layers as layers_2d
from pswamp.utils.gl import set_gl_options

import pyqtgraph.opengl as gl


class BusesLayer(layers_2d.BusesLayer):
    # def __init__(self, *args, **kwargs):
        # super().__init__(*args, **kwargs)
        # self.uuid = uuid.uuid4()
    
    def add_scatter_plot(self, bus_coords_3d):

        bus_lines_x = np.vstack([self.x]*2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_y = np.vstack([self.y]*2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_z = np.vstack([self.z, self.z * 0, np.nan * np.ones(len(self.x))]).T

        edge_pos = np.vstack(
            [bus_lines_x.flatten(), bus_lines_y.flatten(), bus_lines_z.flatten()]
        ).T

        bus_lines = gl.GLLinePlotItem(
            pos=edge_pos, antialias=True, width=0.25)
        
        set_gl_options(self.config, bus_lines)

        return bus_lines


class BusNamesLayer(layers_2d.BusNamesLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_text(self, coord, text):
        font = QtGui.QFont()
        font.setPixelSize(12)
        np.concatenate([coord, [self.z0]])
        text_item = gl.GLTextItem(
            pos=coord, text="{}".format(text), font=font
        )
        set_gl_options(self.config, text_item)
        return text_item


if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_3d.base_plot import GridBasePlot3D
    from pswamp.gui.grid_view.dim_3d.layers.countries import CountriesLayer
    from nqkafka.utils import stop_server

    config, con, pmu = create_minimal_test_case()
    # print(config)
    # config["streaming"]["consumers_seek_to_beginning"] = True

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot3D(
        # config,
        # sld_id="sld1"
        # geo=False,
    )
    grid_plot.window.show()

    bus_names = BusesLayer(grid_plot, config, sld_id="sld1")
    bus_names_layer = BusNamesLayer(grid_plot, config, sld_id="sld1")
    countries_layer = CountriesLayer(grid_plot, config, sld_id="sld1")
    
    # layer_instance.remove_layer()

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])
