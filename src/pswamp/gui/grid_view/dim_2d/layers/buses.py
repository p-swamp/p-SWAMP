# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import ezdxf
from io import StringIO
from pswamp.database import get_from_database
import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
import pswamp.visualization.components.single_line_diagram as sld
from pswamp.gui.grid_view.exceptions import LayerFailedException


class SLDLayer:
    def __init__(self, parent, config, sld_id=None, dim3d=False) -> None:
        self.config = config
        self.plotWidget = parent.plotWidget
        self.k = 1. # 2 if geo else 1
        self.z0 = 1
        self.sld_id = sld_id
        
        self.read_sld_data(config["database"])
        self.bus_coords = np.vstack([self.x, self.y, self.z]).T
        


    def read_sld_data(self, db_kwargs):
        all_sld = get_from_database(db_kwargs, "single_line_diagrams")
        current_sld = all_sld[all_sld["name"] == self.sld_id]["data"].values
        if len(current_sld) == 0:
            raise LayerFailedException(f"Could not read SLD data for {self.sld_id}")
        dxf_data = current_sld[-1]
        dxf_file_stream = StringIO(dxf_data)
        doc = ezdxf.read(dxf_file_stream)
        self.bus_data = get_from_database(db_kwargs, "bus")

        self.bus_names, self.bus_coords = sld.get_buses(
            doc, self.bus_data["name"].to_numpy()
        )
        self.x = self.bus_coords[:, 0]
        self.y = self.bus_coords[:, 1]
        self.z = self.y*0 + self.z0


class BusesLayer(SLDLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.colors = lambda i: pg.intColor(
        #     i,
        #     hues=9,
        #     values=1,
        #     maxValue=255,
        #     minValue=150,
        #     maxHue=360,
        #     minHue=0,
        #     sat=255,
        #     alpha=255,
        # )

        # use_colors = False
        # color = np.ones((len(bus_coords_3d), 4))
        # color[:, -1] = 0.5
        # if use_colors:
        #     color = (
        #         np.array([self.colors(i).getRgb() for i in range(len(bus_coords_3d))])
        #         / 255
        #     )
        self.bus_scatter = self.add_scatter_plot(self.bus_coords)
        self.plotWidget.addItem(self.bus_scatter)

    def add_scatter_plot(self, bus_coords):
        return pg.ScatterPlotItem(
            x=bus_coords[:, 0], y=bus_coords[:, 1], brush=pg.mkBrush(('white')))  # pen=pg.mkPen('w'), )

    def remove_layer(self):
        self.plotWidget.removeItem(self.bus_scatter)


class BusNamesLayer(SLDLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bus_name_text = []
        for coord, bus_name in zip(self.bus_coords, self.bus_names):
            txtitem1= self.add_text(coord, bus_name)
            self.bus_name_text.append(txtitem1)
            self.plotWidget.addItem(txtitem1)
    
    def add_text(self, coord, text):
            text_item = pg.TextItem(anchor=(0, 0), text="{}".format(text), color=(127, 127, 127))
            text_item.setPos(coord[0], coord[1])
            return text_item

    def remove_layer(self):
        for txt in self.bus_name_text:
            self.plotWidget.removeItem(txt)


if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
    from pswamp.gui.grid_view.dim_2d.layers.countries import CountriesLayer
    from nqkafka.utils import stop_server

    config, con, pmu = create_minimal_test_case()
    # print(config)
    # config["streaming"]["consumers_seek_to_beginning"] = True

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        # geo=False,
    )
    grid_plot.window.show()

    layer_instance = BusesLayer(grid_plot, config, sld_id="sld1")
    bus_names = BusNamesLayer(grid_plot, config, sld_id="sld1")
    countries_layer = CountriesLayer(grid_plot, config, sld_id="sld1")
    # layer_instance = LineLayer(grid_plot, config, geo=False)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    # from pswamp.streaming import Producer
    # dataframe = pmu.generate_dataframe(freq_data=[49, 51, 50])
    # producer = Producer(**config["streaming"])
    # producer.send(topic="pmudata", msg=dataframe)

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])
