from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server

import multiprocessing as mp
import time
from data.coords import load as load_coordinates
import pswamp.test_utils.runners as runners
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher

from run_sim import run_rtsim
from pswamp.gui.main_window import run_main_window
# import pyqtgraph


if __name__ == '__main__':
    config = load_config()

    if config["streaming"]['type'] == "nqkafka":
        runners.run_nqkafka_server(config)
        print('Started NQKafka Server')
        # Wait for a while, to make sure the server has started before continuing
        time.sleep(2)

    runners.create_topics(config)
    runners.publish_geo_data(config, load_coordinates())
    runners.publish_model_data(config)

    run_rtsim(pmu_publisher_type=PMUToKafkaPublisher, pmu_kwargs={'topic': 'pmudata', 'io_kwargs': config["streaming"]})

    # p_3 = mp.Process(target=run_main_window, args=(config,))
    # p_3.start()

    # p_1.join()
    # p_2.join()
    # p_3.join()
    # p_server.join()
    # time.sleep(2)
    input("Press a key to quit")

    if config["streaming"]['use_nqkafka']:
        stop_nqkafka_server(config["streaming"]['bootstrap_servers'])
