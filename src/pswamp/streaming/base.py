from pswamp.streaming.kafka_extras.consumer_producer import KafkaProducer,\
    KafkaConsumer
from pswamp.streaming.kafka_io import KafkaIO
from nqkafka.producer import KafkaProducer as NQKafkaProducer
from nqkafka.consumer import KafkaConsumer as NQKafkaConsumer
from pswamp.streaming.mqtt_io import MQTTProducer, MQTTConsumer, MQTT_IO


class Producer:
    def __init__(self, *args, type="kafka", **kwargs):
        match type:
            case "kafka":
                base_class = KafkaProducer
            case "nqkafka":
                base_class = NQKafkaProducer
            case "mqtt":
                base_class = MQTTProducer
        
        self.base_object = base_class(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)


class Consumer:
    def __init__(self, *args, type="kafka", **kwargs):
        match type:
            case "kafka":
                base_class = KafkaConsumer
            case "nqkafka":
                base_class = NQKafkaConsumer
            case "mqtt":
                base_class = MQTTConsumer
        
        self.base_object = base_class(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)
    
    def __iter__(self):
        return self.base_object.__iter__()

    def __next__(self):
        return self.base_object.__next__()


class BaseIO:
    def __init__(self, *args, type="kafka", **kwargs):
        match type:
            case "kafka":
                base_class = KafkaIO
            case "nqkafka":
                # base_class = NQKafkaIO
                ...
            case "mqtt":
                base_class = MQTT_IO

        self.base_object = base_class(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)