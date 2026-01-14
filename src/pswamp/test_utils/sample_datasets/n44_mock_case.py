import time
from nqkafka import NQKafkaServer
from nqkafka.utils import stop_server
from pswamp.test_utils import runners
from pswamp.streaming.kafka_extras import Producer
from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
import numpy as np
from topsrt.pmu_currents_freq import PMUPublisherCurrentsFreq
from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
from pswamp import load_config
import json
# from pswamp.utils.misc import lookup_strings
# from pswamp.utils.pypmu import PMUPhasorExtractor, PMUFreqExtractor
from pswamp.models.bus import read_model_data
# import pandas as pd


def generate_pmu_cfg_from_model(config):
    line_data = read_model_data(config, 'lines')
    trafo_data = read_model_data(config, 'transformers')
    bus_data = read_model_data(config, 'buses')

    obj = type('', (), {'stations': None, 'ip': '', 'port': 0, 'pdc_id': 1, 'fs': 50})()
    PMUPublisherCurrentsFreq.initialize(obj, [bus_data, line_data, trafo_data])
    return obj.pmu.pmu.cfg2


def run_mock_case(config, topic_data={}, publish_frequency=50, t_end=10):
    server = NQKafkaServer(
        config["streaming"]['bootstrap_servers'], run_in_process=False)
    server.start()
    runners.create_topics(config)
    # Load N44 model data and generate PMU config frame

    cfg = generate_pmu_cfg_from_model(config)

    data_frame = DataFrameGenerator.generate_data_frame(cfg)
    data_frame.cfg.get_ph_units()
    stations = data_frame.cfg.get_station_name()

    # coords = np.array([[16, 60, np.nan, np.nan], [
                    #   17, 62, np.nan, np.nan], [16.7, 61, np.nan, np.nan]])
    # runners.publish_geo_data(config, data=(['PMU1', 'PMU2', 'PMU3'], coords))

    # cfg = DataFrameGenerator.generate_cfg(['PMU1', 'PMU2', 'PMU3'], [['V'], ['V'], [
                                        #   'V']], publish_frequency=publish_frequency)

    producer = Producer(**config["streaming"])

    for topic, data in topic_data.items():
        [producer.send(topic, data_) for data_ in data]

    t_0 = time.time()
    dt = 1/publish_frequency
    t_sim = 0.0

    freq = 50 + np.random.randn(len(stations))*0.1

    def generate_data_frames(t_sim=t_sim, freq=freq):
        while t_sim < t_end:

            # phasors = [
                # [(1, 0.1)], [(1.01 + np.sin(t_sim*2)*0.1, 0.2)], [(1, 0.1)]]

            freq += np.random.randn(len(stations))*0.1
            data_frame = DataFrameGenerator.generate_data_frame(
                cfg, time_stamp=t_sim, freq=freq)
            try:
                producer.send('pmudata', data_frame)
            except Exception:
                pass

            # time.sleep(dt)
            t_sim += dt
            # print(t_sim)

    generate_data_frames()
    # if run_continous:
    # pmu_thread = threading.Thread(target=generate_data_frames, daemon=True)
    # pmu_thread.start()
    # else:


def stop_mock_case(config):
    from nqkafka.utils import stop_server
    stop_server(config["streaming"]['bootstrap_servers'])


if __name__ == '__main__':
    from pswamp import load_config
    import time
    config = load_config()
    run_mock_case(config)
    time.sleep(1)
    stop_mock_case(config)

    cfg = generate_pmu_cfg_from_model(config)

    data_frame = DataFrameGenerator.generate_data_frame(cfg)
    len(np.concatenate(data_frame.get_phasors()))
    len(data_frame.get_freq())*2    