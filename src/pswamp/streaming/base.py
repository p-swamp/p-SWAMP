import pickle
import numpy as np
from pswamp.streaming.utils import encoder, decoder

try:
    import pswamp.streaming.nqkafka_io as nqkafka_io
except ImportError:
    _has_nqkafka = False
else:
    _has_nqkafka = True

try:
    import pswamp.streaming.kafka_io as kafka_io
except ImportError:
    _has_kafka = False
else:
    _has_kafka = True    

try:
    import pswamp.streaming.mqtt_io as mqtt_io
except ImportError:
    _has_mqtt = False
else:
    _has_mqtt = True

class Producer:
    def __init__(self, *args, type="kafka", consumers_seek_to_beginning=False, **kwargs):
        match type:
            case "kafka":
                self.base_object = kafka_io.KafkaProducer(*args, value_serializer=encoder, **kwargs)
            case "nqkafka":
                self.base_object = nqkafka_io.KafkaProducer(*args, **kwargs)
            case "mqtt":
                self.base_object = mqtt_io.MQTTProducer(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)


class Consumer:
    def __init__(self, *args, type="kafka", consumers_seek_to_beginning=False, **kwargs):
        match type:
            case "kafka":
                self.base_object = kafka_io.KafkaConsumer(
                    *args, value_deserializer=decoder, **kwargs)
                if consumers_seek_to_beginning:
                    kafka_io.consumer_seek_relative_offset(
                        self.base_object, -np.inf)
            case "nqkafka":
                self.base_object = nqkafka_io.KafkaConsumer(*args, **kwargs)
                if consumers_seek_to_beginning:
                    nqkafka_io.nqkafka_utils.consumer_seek_relative_offset(
                        self.base_object, -np.inf)
            case "mqtt":
                self.base_object = mqtt_io.MQTTConsumer(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)
    
    def __iter__(self):
        return self.base_object.__iter__()

    def __next__(self):
        return self.base_object.__next__()


class BaseIO:
    def __init__(self, io_kwargs, **kwargs):
        type = io_kwargs["type"]
        match type:
            case "kafka":
                base_class = kafka_io.KafkaIO
            case "nqkafka":
                base_class = nqkafka_io.NQKafkaIO
            case "mqtt":
                base_class = mqtt_io.MQTT_IO

        self.base_object = base_class(
            {k: io_kwargs[k] for k in io_kwargs if k != "type"}, **kwargs)

    def __getattr__(self, name):
        return getattr(self.base_object, name)
    


def get_last_message_from_topic(*args, type="kafka", **kwargs):
    match type:
        case "kafka":
            return kafka_io.get_last_message_from_topic(*args, **kwargs)
        case "nqkafka":
            return nqkafka_io.nqkafka_utils.get_last_message_from_topic(
                *args, **kwargs
            )
        case "mqtt":
            pass
            # base_class = MQTT_IO


def consumer_seek_relative_offset(*args, type="kafka", **kwargs):
    match type:
        case "kafka":
            return kafka_io.consumer_seek_relative_offset(*args, **kwargs)
        case "nqkafka":
            return nqkafka_io.nqkafka_utils.consumer_seek_relative_offset(
                *args, **kwargs
            )
        case "mqtt":
            pass
            # base_class = MQTT_IO