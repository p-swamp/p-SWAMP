import multiprocessing as mp
import time

from nqkafka.utils import stop_server as stop_nqkafka_server

from pswamp.gui.main_window import run_main_window
from pswamp.test_utils import runners
from pswamp.utils.load_config import load_config

if __name__ == '__main__':
    config = load_config('config.toml')

    if config["streaming"]["type"] == "nqkafka":
        runners.run_nqkafka_server(config)
        print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    time.sleep(2)

    runners.create_topics(config)
    # runners.publish_geo_data(config, n44_coordinates())

    p = mp.Process(
        target=runners.c37118_to_kafka,
        args=(config, config['pdc']['ip'], config['pdc']['port'], config['pdc']['id']))
    p.start()
    print('C37.118-to-Kafka started.')
    time.sleep(4)
    
    run_main_window(config)

    if config["streaming"]["type"] == "nqkafka":
        stop_nqkafka_server(config["streaming"]['bootstrap_servers'])
