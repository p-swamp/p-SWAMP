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
from pswamp.utils.gl import set_gl_options


class Frequency3DLayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.plotWidget = parent.plotWidget

        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent
        self.z_scale = 3

        pmu_tw = PMUTimeWindowOnline(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        pmu_tw.initialize()
        self.pmu_tw = pmu_tw
        self.col_idx = self.get_col_idx()
        bus_names, bus_coords_3d = load_bus_coords_for_current_stations(
            config, geo=geo, return_3d=True)
        bus_coords_3d[:, 1] *= self.k

        pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
        pmu_tw_thread.start()

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z_0 = bus_coords_3d[:, 2]
        self.z = self.z_0.copy()

        self.colors = lambda i: pg.intColor(
            i,
            hues=9,
            values=1,
            maxValue=255,
            minValue=150,
            maxHue=360,
            minHue=0,
            sat=255,
            alpha=255,
        )

        use_colors = False
        self.color = color = np.ones((len(bus_coords_3d), 4))
        color[:, -1] = 0.5
        if use_colors:
            color = (
                np.array([self.colors(i).getRgb()
                         for i in range(len(bus_coords_3d))])
                / 255
            )
        self.bus_scatter, self.bus_lines = self.add_scatter_plot(bus_coords_3d)
        self.plotWidget.addItem(self.bus_scatter)
        self.plotWidget.addItem(self.bus_lines)

        parent.update_funs[self.uuid] = self.update_scatter

    def show(self):
        self.bus_scatter.show()
        self.bus_lines.show()

    def hide(self):
        self.bus_scatter.hide()
        self.bus_lines.hide()
    
    def get_col_idx(self):
        return self.pmu_tw.tw.get_col_idx(measurement='f')

    def add_scatter_plot(self, bus_coords_3d):

        bus_scatter = gl.GLScatterPlotItem(
            pos=np.vstack([self.x, self.y, self.z]).T,
            color=self.color,
            size=15
        )
        set_gl_options(self.config, bus_scatter)
          
        edge_pos = self.generate_bus_lines()
        bus_lines = gl.GLLinePlotItem(pos=edge_pos, width=0.25, antialias=True)
        set_gl_options(self.config, bus_lines)
        return bus_scatter, bus_lines

    def update_coords(self):
        freq = self.pmu_tw.tw.get_col(self.col_idx).flatten()
        self.z = self.z_0 + self.z_scale*(freq - 50)
    
    def update_scatter(self):
        self.update_coords()
        self.bus_scatter.setData(pos=np.vstack([self.x, self.y, self.z]).T)
        # self.bus_scatter.update(freq)
        edge_pos = self.generate_bus_lines()
        self.bus_lines.setData(pos=edge_pos)

    def generate_bus_lines(self):
        bus_lines_x = np.vstack([self.x] * 2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_y = np.vstack([self.y] * 2 + [np.nan * np.ones(len(self.x))]).T
        bus_lines_z = np.vstack([self.z, self.z * 0, np.nan * np.ones(len(self.x))]).T

        edge_pos = np.vstack([bus_lines_x.flatten(), bus_lines_y.flatten(), bus_lines_z.flatten()]).T
        return edge_pos
    
    def remove_layer(self):
        self.pmu_tw.stop()
        self.plotWidget.removeItem(self.bus_scatter)
        self.plotWidget.removeItem(self.bus_lines)
        

class Frequency3DLayerSettings(QtWidgets.QWidget):
    def __init__(self, target_layer):
        self.target_layer = target_layer
        super().__init__()

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        freq_scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        freq_scale_slider.setRange(0, 100)
        
        freq_scale_slider.valueChanged.connect(self.slider_change)
        layout.addWidget(freq_scale_slider)
        self.show()

    def slider_change(self, val):
        self.target_layer.z_scale = val/10
