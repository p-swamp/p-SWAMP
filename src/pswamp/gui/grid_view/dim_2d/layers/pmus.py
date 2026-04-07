# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.


import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
from pswamp.database import get_from_database


class PMULayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.plotWidget = parent.plotWidget
        self.k = 2 if geo else 1
        # bus_names, bus_coords_3d = load_bus_coords_for_current_stations(
        #     config, return_3d=True, geo=geo)
        pmu_info = get_from_database(config, "pmu")
        bus_names = pmu_info["name"]
        bus_coords_3d = np.vstack([
            pmu_info["lon"],
            pmu_info["lat"],
            np.zeros(len(pmu_info))
        ]).T
        
        bus_coords_3d[:, 1] *= self.k

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]

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
        color = np.ones((len(bus_coords_3d), 4))
        color[:, -1] = 0.5
        if use_colors:
            color = (
                np.array([self.colors(i).getRgb() for i in range(len(bus_coords_3d))])
                / 255
            )
        self.bus_scatter = self.add_scatter_plot(bus_coords_3d)
        self.plotWidget.addItem(self.bus_scatter)

    def add_scatter_plot(self, bus_coords_3d):
        return pg.ScatterPlotItem(
            x=bus_coords_3d[:, 0], y=bus_coords_3d[:, 1], brush=pg.mkBrush(('white')))  # pen=pg.mkPen('w'), )

    def remove_layer(self):
        self.plotWidget.removeItem(self.bus_scatter)




if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'

    config = load_config()
    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        geo=True,
    )
    grid_plot.window.show()

    # layer_instance = LineLayer(grid_plot, config, geo=False)
    layer_instance = PMULayer(grid_plot, config, geo=True)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    app.exec()
