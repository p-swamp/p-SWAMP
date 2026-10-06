
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
from pswamp.gui.grid_view.dim_2d.layers.pmus import PMULayer


if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    # sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'

    config = load_config("..")
    # config = load_config("examples/nordic44_rtsim/config_mqtt.toml")
    # pmu_info = get_from_database(config, "pmu")
    # print(pmu_info)
    # import matplotlib.pyplot as plt
    # fig, ax = plt.subplots(1)
    # ax.set_aspect(2)
    # ax.scatter(pmu_info["lon"], pmu_info["lat"])
    # plt.show()

    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        geo=True,
    )
    grid_plot.window.show()

    # layer_instance = LineLayer(grid_plot, config, geo=False)
    # layer_instance = PMULayer(grid_plot, config, geo=True)
    layer_instance = BusesLayer(grid_plot, config, geo=True)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    app.exec()
