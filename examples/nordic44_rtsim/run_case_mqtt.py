from pswamp.utils.load_config import load_config
# from nqkafka.utils import stop_server as stop_nqkafka_server

# import multiprocessing as mp
# import time
# from pswamp.gui.main_window import run_main_window
import multiprocessing as mp
# from data.coords import load as load_coordinates
import pswamp.test_utils.runners as runners
from pswamp.test_utils.pmu_rtsim_to_mqtt import PMUToMQTTPublisher
from run_sim import run_rtsim
# import pyqtgraph
import json
import sqlite3
from pswamp.models.reader import replace_data_lists_with_dataframes
import pandas as pd
from pswamp.test_utils.runners import create_database


if __name__ == '__main__':
    config = load_config("config_mqtt.toml")

    # runners.create_topics(config)
    # runners.publish_geo_data(config, load_coordinates())
    # runners.publish_model_data(config)

    create_database(config)

    mqtt_kwargs = config['streaming']

    run_rtsim(pmu_publisher_type=PMUToMQTTPublisher, pmu_kwargs={'topic': 'pmudata', 'mqtt_kwargs': mqtt_kwargs})

    # # p_3 = mp.Process(target=run_main_window, args=(config,))
    # # p_3.start()

    # # p_1.join()
    # # p_2.join()
    # # p_3.join()
    # # p_server.join()
    # # time.sleep(2)
    input("Press a key to quit")

    # if config["streaming"]['use_nqkafka']:
    #     stop_nqkafka_server(config["streaming"]['bootstrap_servers'])
