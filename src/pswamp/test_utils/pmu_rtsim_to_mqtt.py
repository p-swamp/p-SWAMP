from topsrt.pmu_v2 import PMUPublisherV2 as PMUPublisher
from queue import Queue
# from pswamp.streaming.kafka_extras import KafkaProducer
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