from topsrt.pmu_v2 import PMUPublisherV2 as PMUPublisher
from queue import Queue
from pswamp.streaming.kafka_extras import KafkaProducer
import pickle


class PMUToKafkaPublisher(PMUPublisher):
    def __init__(self, kafka_kwargs, *args, topic='pmudata', **kwargs):
        super().__init__(*args, ip='', port=0, **kwargs)
        self.topic = topic
        self.kafka_producer = KafkaProducer(**kafka_kwargs, value_serializer=pickle.dumps)

    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.pmu.pmu.client_buffers = [Queue()]
        self.pmu.pmu.clients = [None]
    
    def update(self, input_signal):
        super().update(input_signal)
        data_frame = self.pmu.pmu.client_buffers[0].get()
        self.kafka_producer.send(self.topic, data_frame)
        self.kafka_producer.flush()