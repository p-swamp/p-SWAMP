import numpy as np

# from pswamp_monitoring.utils.pmu_receiver import PMUReceiver
from pswamp.utils.load_config import load_config
from pswamp.visualization.components.phasor_plot import PhasorPlotFancy
import threading
import PySide6.QtWidgets as QtWidgets
import pyqtgraph as pg
import sys
from pswamp.app_templates.snapshot_app import SnapshotApp

# importlib.reload(pmu_recv)



class VoltagePhasorPlot:
    def __init__(
        self,
        io_kwargs,
        input_topic="pmudata",
        **kwargs
    ):

        self.pmu_input = SnapshotApp(
            # n_samples=1,
            input_topic=input_topic,
            io_kwargs=io_kwargs,
            command_topic=None,
        )
        # pmu_input.initialize()
        pmu_tw_thread = threading.Thread(target=self.pmu_input.run, daemon=True)
        pmu_tw_thread.start()
        
        pmu_tw = self.pmu_input

        max_phasors = 1000
        # pmu_tw.is_initialized = True
        # pmu_tw.tw = TimeWindow(pmu_tw.n_samples, 7, dtype=complex)
        

        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='v')[0] for station_name in pmu_tw.station_names]
        # Get first voltage phasor at each bus
        col_idx_mag = []
        col_idx_ang = []
        stations_to_plot = []
        for station_name in np.unique(pmu_tw.tw.header['station']):
            idx_mag_ = pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v_Magnitude')
            idx_ang_ = pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v_Angle')
            if len(idx_mag_ > 0) and len(idx_mag_) == len(idx_ang_):
                # col_idx.append((idx_mag[0], idx_ang[0]))
                col_idx_mag.append(idx_mag_[0])
                col_idx_ang.append(idx_ang_[0])
                stations_to_plot.append(station_name.strip())

        self.phasor_plot = PhasorPlotFancy(len(col_idx_mag), update_freq=None, normalize_length=False, normalize_angle='mean')
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='v')[0] for station_name in pmu_tw.station_names]    

        def update_fun():
            for kafka_message in pmu_tw.pmu_stream:
                pmu_tw.update_window(kafka_message.value)            

                mag = pmu_tw.tw.get_col(col_idx_mag).flatten()
                ang = pmu_tw.tw.get_col(col_idx_ang).flatten()
                phasors = mag*np.exp(1j*ang)
                self.phasor_plot.update(phasors)

                if pmu_tw._is_stopped:
                    break
        
        p_2 = threading.Thread(target=update_fun, daemon=True)
        p_2.start()


def run_voltage_phasor_plot(*config_args, update_freq=25, **kwargs):
    app = QtWidgets.QApplication(sys.argv)

    config = load_config(*config_args)
    voltage_phasor_plot = VoltagePhasorPlot(
        io_kwargs=config["streaming"],
        input_topic=config['topics']['pmudata'],
        **kwargs
    )

    app.exec()

    return app


if __name__ == '__main__':
    config = load_config()
    run_online = False
    if run_online:
        run_voltage_phasor_plot(config)
    else:
        config["streaming"]['bootstrap_servers'] = 'localhost:50000'

        from nqkafka import NQKafkaServer
        from nqkafka.utils import stop_server
        from pswamp.test_utils import runners
        from pswamp.streaming import Producer
        from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator

        server = NQKafkaServer(config["streaming"]['bootstrap_servers'], run_in_process=False)
        server.start()
        runners.create_topics(config)

        cfg = DataFrameGenerator.generate_cfg(['PMU1', 'PMU2'], [['V'], ['V']])
        
        producer = Producer(**config["streaming"])
        import time
        def generate_data_frames():
            while True:
                phasors = [[(1, 0.1)], [(1.01 + np.sin(time.time()*2)*0.1, 0.2)]]
                data_frame = DataFrameGenerator.generate_data_frame(cfg, phasors=phasors)
                producer.send('pmudata', data_frame)
                time.sleep(0.02)

        pmu_thread = threading.Thread(target=generate_data_frames, daemon=True)
        pmu_thread.start()

        run_voltage_phasor_plot(config)

        stop_server(config["streaming"]['bootstrap_servers'])
    