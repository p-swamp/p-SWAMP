# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import time
from nqkafka import NQKafkaServer
from nqkafka.utils import stop_server
from pswamp.test_utils import runners
from pswamp.streaming import Producer
from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
import numpy as np


def run_mock_case(config, topic_data={}, publish_frequency=50, t_end=10):
    server = NQKafkaServer(
        config["streaming"]['bootstrap_servers'], run_in_process=False)
    server.start()
    runners.create_topics(config)

    coords = np.array([[16, 60, np.nan, np.nan], [17, 62, np.nan, np.nan], [16.7, 61, np.nan, np.nan]])
    runners.publish_geo_data(config, data=(['PMU1', 'PMU2', 'PMU3'], coords))

    cfg = DataFrameGenerator.generate_cfg(['PMU1', 'PMU2', 'PMU3'], [['V'], ['V'], [
                                          'V']], publish_frequency=publish_frequency)

    producer = Producer(**config["streaming"])

    for topic, data in topic_data.items():
        [producer.send(topic, data_) for data_ in data]


    t_0 = time.time()
    dt = 1/publish_frequency
    t_sim = 0.0

    def generate_data_frames(t_sim=t_sim):
        while t_sim < t_end:
            
            phasors = [
                [(1, 0.1)], [(1.01 + np.sin(t_sim*2)*0.1, 0.2)], [(1, 0.1)]]
            
            freq = [
                50 + np.random.randn(1)*0.1 + np.sin(0.5*t_sim*0.7),
                50 + np.sin(0.7*time.time()*0.7 + 0.4),
                50.1 + np.random.randn(1)*0.1,
            ]
            data_frame = DataFrameGenerator.generate_data_frame(
                cfg, time_stamp=t_sim, phasors=phasors, freq=freq)
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
