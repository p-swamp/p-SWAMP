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

from topsrt.pmu_v2 import PMUPublisherV2 as PMUPublisher
from queue import Queue
# from pswamp.streaming.mqtt_io import MQTTProducer
from pswamp.streaming import Producer
import pickle


class PMUToMQTTPublisher(PMUPublisher):
    def __init__(self, mqtt_kwargs, *args, topic='pmudata', **kwargs):
        super().__init__(*args, ip='', port=0, **kwargs)
        self.topic = topic
        self.producer = Producer(**mqtt_kwargs)

    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.pmu.pmu.client_buffers = [Queue()]
        self.pmu.pmu.clients = [None]
    
    def update(self, input_signal):
        super().update(input_signal)
        data_frame = self.pmu.pmu.client_buffers[0].get()
        self.producer.send(self.topic, data_frame)
        self.producer.flush()
