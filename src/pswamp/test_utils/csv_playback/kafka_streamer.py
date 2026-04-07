# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

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
