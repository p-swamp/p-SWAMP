config = dict(
    kafka=dict(
        use_nqkafka=True,
        bootstrap_servers="localhost:51006"
    ),

    # Kafka topics:
    topics={
        "application.status": "application.status",
        "pmudata": "pmudata",
        "pmu.coords": "pmu.coords",
        "modeestimation": "modeestimation",
    }
)

from nqkafka.utils import stop_server as stop_nqkafka_server

import time
import pswamp.test_utils.runners as runners
# from pswamp.gui.main_window import run_main_window
from pswamp.test_utils.generate_pmu_data import generate_pmu_data
from pswamp.monitoring.utils import TimeWindowRTApp
import sys
import numpy as np
import threading


class SomeRTApp(TimeWindowRTApp):
    def run_analysis(self, t, phasors):
        sys.stdout.write("\rTime window {:.2f}% complete".format(100 * (1 - (sum(np.isnan(t))) / len(t))))


def test_case():


    runners.run_nqkafka_server(config)
    print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    time.sleep(2)
    runners.create_topics(config)

    data = generate_pmu_data()

    print('Start CSV-to-Kafka')
    p =  threading.Thread(target=runners.csv_to_kafka, args=(config, data,), daemon=True)
    p.start()
    print('CSV to Kafka playback started.')
    time.sleep(2)

    test_app = SomeRTApp(
        time_window_length=1,
        input_topic=config['topics']['pmudata'],
        kafka_kwargs=config['kafka'],
    )

    app_thread = threading.Thread(target=test_app.run)
    app_thread.start()
    
    # run_main_window(config)
    time.sleep(5)
    test_app.stop()
    print('Stopped test app')
    time.sleep(2)
    
    stop_nqkafka_server(config['kafka']['bootstrap_servers'])


if __name__ == '__main__':
    test_case()