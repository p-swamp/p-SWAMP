from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
from pswamp import load_config
import time


def test_mock_case():
    config = load_config()
    config["streaming"]['bootstrap_servers'] = 'localhost:51007'
    run_mock_case(config)
    time.sleep(1)
    stop_mock_case(config)