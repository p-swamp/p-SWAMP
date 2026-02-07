import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import (
    load_bus_coords_for_current_stations,
    load_bus_coords_for_stations,
)
from pswamp.utils.single_line_diagram import load_dxf
from pswamp.app_templates.snapshot_app import SnapshotApp


class PhasorPlotLayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent

        pmu_input = SnapshotApp(
            n_samples=1,
            kafka_topic=config["topics"]["pmudata"],
            io_kwargs=config["streaming"],
        )
        pmu_input.initialize()
        self.pmu_tw = pmu_input

        stations_to_plot = []

        self.col_idx_mag = []
        self.col_idx_ang = []
        for station_name in np.unique(pmu_input.header["station"]):
            idx_mag_ = pmu_input.tw.get_col_idx(
                station=station_name.strip(), measurement="v_Magnitude"
            )
            idx_ang_ = pmu_input.tw.get_col_idx(
                station=station_name.strip(), measurement="v_Angle"
            )
            if len(idx_mag_ > 0) and len(idx_mag_) == len(idx_ang_):
                # col_idx.append((idx_mag[0], idx_ang[0]))
                self.col_idx_mag.append(idx_mag_[0])
                self.col_idx_ang.append(idx_ang_[0])
                stations_to_plot.append(station_name.strip())

        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')[0] for station_name in pmu_tw.station_names]
        bus_coords = load_bus_coords_for_stations(config, stations_to_plot, geo=geo)
        bus_names_all, bus_coords_all = load_bus_coords_for_current_stations(
            config, geo=geo
        )
        bus_coords[:, 1] *= self.k

        pmu_tw_thread = threading.Thread(target=pmu_input.run, daemon=True)
        pmu_tw_thread.start()

        self.plotWidget = parent.plotWidget
        self.phasor_plot = self.add_phasor_plot(bus_coords)

        # for station_name in pmu_tw.station_names:
        #     if len(pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')) == 0:
        #         break

        # # DEBUG
        # pmu_tw.tw.header['station'][0] == pmu_tw.station_names[0].strip()
        # pmu_tw.tw.header['measurement'][0] == 'v'
        # ix = pmu_tw.tw.get_col_idx(station=station_name.strip())
        # pmu_tw.header[ix]
        # DEBUG
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')[0] for station_name in pmu_tw.station_names]
        # pmu_tw.tw.get_col_idx(
        #     station=pmu_tw.station_names[0].strip(), measurement='v')

        def phasor_fun():
            # Get the first voltage measurement at each station
            mag = pmu_input.tw.get_col(self.col_idx_mag).flatten()
            ang = pmu_input.tw.get_col(self.col_idx_ang).flatten()
            phasors = mag * np.exp(1j * ang)
            return phasors

        def update_phasors():
            phasors = phasor_fun()
            if np.all(np.isnan(phasors)):
                return
            self.phasor_plot.update(phasors)

        parent.update_funs[self.uuid] = update_phasors

    def add_phasor_plot(self, bus_coords):
        return PhasorPlot(
            self.plotWidget,
            pos0=bus_coords,
            plot_widget=self.plotWidget,
            normalize_angle="mean",
        )

    def remove_layer(self):
        self.pmu_tw.stop()
        for single_phasor_plot in self.phasor_plot.phasor_plots:
            self.plotWidget.removeItem(single_phasor_plot)

        del self.parent.update_funs[self.uuid]
        del self.phasor_plot
