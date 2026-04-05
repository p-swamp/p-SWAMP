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
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations, load_bus_coords_for_stations
import pyqtgraph.opengl as gl
from pswamp.gui.grid_view.dim_3d.layers.frequency import Frequency3DLayer, Frequency3DLayerSettings
from pswamp.models.reader import get_model_data
from pswamp.utils.misc import lookup_strings


class Voltage3DLayer(Frequency3DLayer):
    def __init__(self, parent, config, *args, **kwargs) -> None:
        super().__init__(parent=parent, config=config, *args, **kwargs)
        model_data = get_model_data(config)
        stations = np.unique(self.pmu_tw.header['station'])
        station_idx = lookup_strings(stations, model_data['buses']['name'])
        self.station_V_n = model_data['buses']['V_n'][station_idx]

    def update_coords(self):
        voltage = self.pmu_tw.tw.get_col(self.col_idx).flatten()
        voltage_pu = voltage/(self.station_V_n*1e3)
        self.z = self.z_0 + self.z_scale*(voltage_pu)

    def get_col_idx(self):
        pmu_tw = self.pmu_tw

        col_idx_mag = []
        for station_name in np.unique(pmu_tw.header['station']):
            idx_mag_ = pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v_Magnitude')
            if len(idx_mag_ > 0):
                # col_idx.append((idx_mag[0], idx_ang[0]))
                col_idx_mag.append(idx_mag_[0])

        return col_idx_mag  # self.pmu_tw.tw.get_col_idx(measurement='v_Magnitude')
        

class Voltage3DLayerSettings(Frequency3DLayerSettings):
    pass
