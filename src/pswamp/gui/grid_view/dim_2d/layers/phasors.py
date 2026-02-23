from io import StringIO
import ezdxf
from pswamp.visualization.components import single_line_diagram as sld
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
import pswamp.models as model_lib
from pswamp.database import get_from_database


class PhasorPlotLayer:
    def __init__(self, parent, config, sld_id=None, geo=True) -> None:
        self.config = config
        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent
        self.sld_id = sld_id

        self.read_sld_data(config["database"])

        pmu_input = SnapshotApp(
            # n_samples=1,
            input_topic=config["topics"]["pmudata"],
            io_kwargs=config["streaming"],
            command_topic=None,
        )
        # pmu_input.initialize()
        self.pmu_input = pmu_input

        self.bus_mdl = model_lib.bus.Bus(
            config["database"],
            pmu_input.get_sample_data_frame())

        
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')[0] for station_name in pmu_tw.station_names]
        # bus_coords = load_bus_coords_for_stations(config, stations_to_plot, geo=geo)
        # bus_names_all, bus_coords_all = load_bus_coords_for_current_stations(
        #     config, geo=geo
        # )
        # bus_coords[:, 1] *= self.k

        pmu_tw_thread = threading.Thread(target=pmu_input.run, daemon=True)
        pmu_tw_thread.start()

        self.plotWidget = parent.plotWidget
        self.phasor_plot = self.add_phasor_plot(self.bus_coords)

        def phasor_fun():
            # Get the first voltage measurement at each station
            # mag = pmu_input.tw.get_col(self.col_idx_mag).flatten()
            # ang = pmu_input.tw.get_col(self.col_idx_ang).flatten()
            # phasors = mag * np.exp(1j * ang)
            df = self.pmu_input.most_recent_data_frame
            if df is None:
                return
            return self.bus_mdl.v(df)

        def update_phasors():
            phasors = phasor_fun()
            if phasors is None or np.all(np.isnan(phasors)):
                return
            self.phasor_plot.update(phasors)

        parent.update_funs[self.uuid] = update_phasors

    def read_sld_data(self, db_kwargs):
        sld_data = get_from_database(db_kwargs, "single_line_diagrams")
        dxf_data = sld_data[sld_data["name"] == self.sld_id]["data"].values[-1]
        dxf_file_stream = StringIO(dxf_data)
        
        doc = ezdxf.read(dxf_file_stream)
        self.bus_data = get_from_database(db_kwargs, "bus")
        self.bus_names, self.bus_coords = sld.get_buses(
            doc, self.bus_data["name"].to_numpy()
        )
        
    def add_phasor_plot(self, bus_coords):
        return PhasorPlot(
            self.plotWidget,
            pos0=bus_coords,
            plot_widget=self.plotWidget,
            normalize_angle="mean",
        )

    def remove_layer(self):
        self.pmu_input.stop()
        for single_phasor_plot in self.phasor_plot.phasor_plots:
            self.plotWidget.removeItem(single_phasor_plot)

        del self.parent.update_funs[self.uuid]
        del self.phasor_plot

if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
    from nqkafka.utils import stop_server
    from pswamp.gui.grid_view.dim_2d import layers as lrs

    config, con, pmu = create_minimal_test_case()

    app = pg.mkQApp()
    grid_plot = GridBasePlot2D()
    grid_plot.window.show()
    # buses_layer = BusesLayer(grid_plot, config, geo=False)
    line_layer = lrs.LineLayer(grid_plot, config, sld_id="sld1")
    bus_layer = lrs.BusesLayer(grid_plot, config, sld_id="sld1")
    bus_names_layer = lrs.BusNamesLayer(grid_plot, config, sld_id="sld1")
    phasors_layer = lrs.PhasorPlotLayer(grid_plot, config, sld_id="sld1")
    layer_instance = lrs.FrequencyHeatMap(grid_plot, config, sld_id="sld1")
    # countries_layer = bl.BusesLayer(grid_plot, config, sld_id="sld1")

    app.exec()

    stop_server(config["streaming"]["bootstrap_servers"])