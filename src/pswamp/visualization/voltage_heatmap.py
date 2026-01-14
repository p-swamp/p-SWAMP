from PySide6 import QtWidgets, QtCore
import sys
import numpy as np
from pswamp.visualization.components.heatmap import HeatMapGeo
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from pswamp.utils.load_config import load_config
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations


def run_voltage_heatmap(*config_args):
    config = load_config(*config_args)
    app = QtWidgets.QApplication(sys.argv)
    k = 1 / np.cos(60 / 180 * np.pi)

    bus_names, bus_coords = load_bus_coords_for_current_stations(config)

    pmu_tw = PMUTimeWindow(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
    pmu_tw.initialize()

    pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
    pmu_tw_thread.start()

    countries_to_be_drawn = config['geo_data']['countries'] if 'geo_data' in config and 'countries' in config['geo_data'] else []

    heatmap = HeatMapGeo(
        countries=countries_to_be_drawn,
        coords=bus_coords,
        y_scale=k,
        # countries=config['countries'],
        # power_line_geo_data=config['geo_data']['line_data_path'],
    )

    col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='v')[0] for station_name in pmu_tw.station_names]
    def update_fun():
        # phasors = pmu_tw.tw.get_col_str(measurement='v').flatten()
        phasors = pmu_tw.tw.get_col(col_idx).flatten()

        # z = abs(pmu_tw.tw.get_col_str(measurement='v').flatten())
        z = abs(phasors)

        heatmap.update(z)

    update_freq = 25
    timer = QtCore.QTimer()
    timer.timeout.connect(update_fun)
    timer.start(update_freq)

    app.exec()
    return app