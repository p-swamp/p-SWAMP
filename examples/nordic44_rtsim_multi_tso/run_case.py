from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server

import multiprocessing as mp
import time
# from data.coords import load as load_coordinates
import pswamp.test_utils.runners as runners
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher

from run_sim import run_rtsim
from pswamp.gui.main_window import run_main_window
# import pyqtgraph


if __name__ == '__main__':
    config_no = load_config("config_no.toml")
    config_se = load_config("config_se.toml")

    if config_no["streaming"]['type'] == "nqkafka":
        runners.run_nqkafka_server(config_no)
        print('Started NQKafka Server')
                
        # Wait for a while, to make sure the server has started before continuing
        # time.sleep(2)

    for config in [config_no, config_se]:
        runners.create_database(config) 

        if config["streaming"]['type'] in ["kafka", "nqkafka"]:
            runners.create_topics(config)

    run_rtsim(pmu_publisher_type=PMUToKafkaPublisher, pmu_kwargs=[
        {
            'topic': 'no.pmudata',
            'io_kwargs': config_no["streaming"],
            'stations': config_no["pmus"]["stations"]
        },
        {
            'topic': 'se.pmudata',
            'io_kwargs': config_se["streaming"],
            'stations': config_se["pmus"]["stations"]
        }]
        )


    p_3_no = mp.Process(target=run_main_window, args=(config_no,))
    p_3_se = mp.Process(target=run_main_window, args=(config_se,))

    p_3_no.start()
    p_3_se.start()
    p_3_no.join()
    p_3_se.join()
