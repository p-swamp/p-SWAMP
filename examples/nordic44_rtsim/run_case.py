import multiprocessing as mp
import time

from nqkafka.utils import stop_server as stop_nqkafka_server
from run_sim import run_rtsim

from pswamp.gui.main_window import run_main_window
from pswamp.test_utils import runners
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher
from pswamp.utils.load_config import load_config

if __name__ == '__main__':
    config = load_config()
    runners.create_database(config)

    if config["streaming"]['type'] == "nqkafka":
        runners.run_nqkafka_server(config)
        print('Started NQKafka Server')
        
        # Wait for a while, to make sure the server has started before continuing
        time.sleep(2)

    if config["streaming"]['type'] in ["kafka", "nqkafka"]:
        runners.create_topics(config)

    run_rtsim(pmu_publisher_type=PMUToKafkaPublisher, pmu_kwargs={'topic': 'pmudata', 'io_kwargs': config["streaming"]})

    p_3 = mp.Process(target=run_main_window, args=(config,))
    p_3.start()
    p_3.join()

    if config["streaming"]["type"] == "nqkafka":
        stop_nqkafka_server(config["streaming"]['bootstrap_servers'])
