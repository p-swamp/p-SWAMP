from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server

import time
from pswamp.gui.main_window import run_main_window
import multiprocessing as mp
from data.coords import n44_coordinates
import pswamp.test_utils.runners as runners


if __name__ == '__main__':
    config = load_config('config.toml')
    
    if config["streaming"]['use_nqkafka']:
        runners.run_nqkafka_server(config)
        print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    time.sleep(2)

    runners.create_topics(config)
    runners.publish_geo_data(config, n44_coordinates())

    p = mp.Process(
        target=runners.c37118_to_kafka,
        args=(config, config['pdc']['ip'], config['pdc']['port'], config['pdc']['id']))
    p.start()
    print('C37.118-to-Kafka started.')
    time.sleep(4)
    
    run_main_window(config)

    if config["streaming"]['use_nqkafka']:
        stop_nqkafka_server(config["streaming"]['bootstrap_servers'])
