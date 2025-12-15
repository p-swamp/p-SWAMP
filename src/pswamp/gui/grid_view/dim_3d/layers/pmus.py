
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


class PMULayer(layers_2d.PMULayer):
    # def __init__(self, *args, **kwargs):
        # super().__init__(*args, **kwargs)
        # self.uuid = uuid.uuid4()
    
    def add_scatter_plot(self, bus_coords_3d):

        bus_lines_x = np.vstack([self.x] * 2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_y = np.vstack([self.y] * 2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_z = np.vstack([self.z, self.z * 0, np.nan * np.ones(len(self.x))]).T

        edge_pos = np.vstack(
            [bus_lines_x.flatten(), bus_lines_y.flatten(), bus_lines_z.flatten()]
        ).T

        bus_lines = gl.GLLinePlotItem(
            pos=edge_pos, antialias=True, width=0.25)
        
        set_gl_options(self.config, bus_lines)

        return bus_lines