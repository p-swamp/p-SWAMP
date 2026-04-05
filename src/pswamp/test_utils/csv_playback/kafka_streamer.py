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

from pswamp.test_utils.csv_playback.pmu_streamer import PMUDataStreamer
from pswamp.streaming import Producer
from pswamp.streaming.utils import encoder
import threading


class PMUDataStreamerKafka(PMUDataStreamer):
    def init_publisher(self, topic, **io_kwargs):
        self.topic = topic
        self.kafka_producer = Producer(
            **io_kwargs, value_serializer=encoder)
        self.pause_cv = threading.Condition()
        self.paused = False

    def publish(self, data_frame):
        self.kafka_producer.send(self.topic, data_frame)
        self.kafka_producer.flush()
