from PySide6 import QtWidgets, QtCore
import sys
import numpy as np
from pswamp.visualization.components.heatmap import HeatMapGeo
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from pswamp.utils.load_config import load_config
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations


def run_freq_heatmap(*config_args):
    config = load_config(*config_args)
    app = QtWidgets.QApplication(sys.argv)
    k = 1 / np.cos(60 / 180 * np.pi)

    bus_names, bus_coords = load_bus_coords_for_current_stations(config)

    pmu_tw = PMUTimeWindowOnline(
        n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
    pmu_tw.initialize()

    pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
    pmu_tw_thread.start()

    heatmap = HeatMapGeo(
        countries=config['geo_data']['countries'],
        coords=bus_coords,
        y_scale=k,
        lims=[-0.035, 0.035],  # [-np.pi*0.1, np.pi*0.1],
        z_offset=0,
        # countries=config['countries'],
        # power_line_geo_data=config['geo_data']['line_data_path'],
    )

    subtract_mean = True
    station_list = np.unique(pmu_tw.tw.header['station'])
    col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='f')[
        0] for station_name in station_list]
    # phasors_0 = pmu_tw.tw.get_col(col_idx).flatten()
    # freq_0 = pmu_tw.tw.get_col(col_idx).flatten()
    # phasors_0 = pmu_tw.tw.get_col_str(measurement='v').flatten()
    # angles_prev = np.zeros(len(phasors_0))  # np.angle(phasors_0)
    # angles_prev = np.unwrap(angles_prev)
    # d_angle = np.zeros_like(angles_prev)

    def update_fun():
        # phasors = pmu_tw.tw.get_col_str(measurement='v').flatten()
        freq = pmu_tw.tw.get_col(col_idx).flatten()
        heatmap.update(freq - np.mean(freq))

    update_freq = 25
    timer = QtCore.QTimer()
    timer.timeout.connect(update_fun)
    timer.start(update_freq)

    app.exec()
    return app
