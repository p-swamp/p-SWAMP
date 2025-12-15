from pswamp.test_utils.csv_playback.pmu_streamer import PMUDataStreamer
import numpy as np
import pickle
from nqkafka import KafkaProducer
import threading
from pathlib import Path


class PMUDataStreamerKafka(PMUDataStreamer):
    def init_publisher(self, topic, **kafka_kwargs):
        self.topic = topic
        self.kafka_producer = KafkaProducer(
            **kafka_kwargs, value_serializer=pickle.dumps)
        self.pause_cv = threading.Condition()
        self.paused = False

    def publish(self, data_frame):
        self.kafka_producer.send(self.topic, data_frame)
        self.kafka_producer.flush()