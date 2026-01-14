config = dict(
    kafka=dict(
        bootstrap_servers='localhost:29092',
        #bootstrap_servers='pkc-l7q2j.europe-north1.gcp.confluent.cloud:9092',
        #sasl_mechanism='PLAIN',
        #security_protocol='SASL_SSL',
        #sasl_plain_username='QFKJKEV7NTHRJLKZ',
        #sasl_plain_password='RD9TVWCxXqR1vppyCGt2yQ9ovajGsQ/Ss+XpPXNhhTKlLKOjrv2+FzyYpbcfZSqV',
    ),

    # Kafka topics:
    topics={
        "application.status": "application.status",
        "pmudata": "pmudata",
        "pmu.coords": "pmu.coords",
        "modeestimation": "modeestimation",
    }
)

import time
import multiprocessing as mp
import pswamp.test_utils.runners as runners
# from pswamp.gui.main_window import run_main_window
from pswamp.test_utils.generate_pmu_data import generate_pmu_data
from pswamp.monitoring.utils import TimeWindowRTApp
import sys
import numpy as np
import threading


class SomeRTApp(TimeWindowRTApp):
    # TODO: Change TimeWindowRTApp with TimeWindowApp
    def run_analysis(self, t, phasors):
        sys.stdout.write("\rTime window {:.2f}% complete".format(100 * (1 - (sum(np.isnan(t))) / len(t))))


def test():

    # runners.run_nqkafka_server(config)
    # print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    time.sleep(2)
    runners.create_topics(config)

    data = generate_pmu_data()

    print('Start CSV-to-Kafka')
    p =  threading.Thread(target=runners.csv_to_kafka, args=(config, data,), kwargs=dict(speed=20, t_end=180), daemon=True)
    p.start()
    # runners.csv_to_kafka(config, data, speed=20, t_end=180)
    # print('CSV to Kafka playback started.')
    time.sleep(2)

    test_app = SomeRTApp(
        time_window_length=2,
        input_topic=config['topics']['pmudata'],
        io_kwargs=config["streaming"],
    )

    app_thread = threading.Thread(target=test_app.run)
    app_thread.start()
    
    # run_main_window(config)
    time.sleep(5)
    test_app.stop()
    print('Stopped test app')


if __name__ == '__main__':
    test()