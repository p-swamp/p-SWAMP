
import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
from pswamp.visualization.components.heatmap import HeatMap as HeatMapBasePlot
import time
import uuid
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline


class FrequencyHeatMap:
    def __init__(self, parent, config, geo=True, heatmap_kwargs=dict(
            y_scale=1, lims=[-0.035, 0.035], z_offset=0)) -> None:
        self.config = config
        self.uuid = uuid.uuid4()
        self.plotWidget = parent.plotWidget
        self.k = 2 if geo else 1
        
        bus_names, bus_coords_3d = load_bus_coords_for_current_stations(config, return_3d=True, geo=geo)
        
        bus_coords_3d[:, 1] *= self.k

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]

        self.heatmap = HeatMapBasePlot(
            plot_window=self.plotWidget,
            coords=bus_coords_3d,
            **heatmap_kwargs
        )
        self.heatmap.im.setZValue(-10)

        pmu_tw = PMUTimeWindowOnline(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        pmu_tw.initialize()
        self.pmu_tw = pmu_tw
        self.freq_col_idx = self.pmu_tw.tw.get_col_idx(measurement='f')
        pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
        pmu_tw_thread.start()
        
        parent.update_funs[self.uuid] = self.update_heatmap

    def update_heatmap(self):
        freq = self.pmu_tw.tw.get_col(self.freq_col_idx).flatten()
        self.heatmap.update(freq - np.mean(freq))

    def remove_layer(self):
        self.plotWidget.removeItem(self.heatmap.im)
        self.heatmap.cb.hide()
        del self.heatmap.cb


# class VoltageHeatMap(FrequencyHeatMap):
#     def __init__(self, *args, **kwargs) -> None:
#         heatmap_kwargs = dict(y_scale=1, lims=[-0.035, 0.035], z_offset=0)
#         super().__init__(heatmap_kwargs)

        # pmu_tw = PMUTimeWindow(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='v')[0] for station_name in pmu_tw.station_names]
        # def update_fun():
        # phasors = pmu_tw.tw.get_col(col_idx).flatten()
        # z = abs(phasors)
        # heatmap.update(z)
