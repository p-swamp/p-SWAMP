from kafka import KafkaConsumer as KafkaPythonConsumer, KafkaProducer as KafkaPythonProducer
from nqkafka import KafkaConsumer as NQKafkaConsumer, KafkaProducer as NQKafkaProducer
import pswamp.streaming.kafka_extras.utils as utils
import nqkafka.utils as nqkafka_utils
import numpy as np


def consumer_seek_relative_offset(consumer, relative_offset):
    imported_module = utils if hasattr(consumer, "instance") and isinstance(
        consumer.instance, KafkaPythonConsumer) else nqkafka_utils
    imported_module.consumer_seek_relative_offset(consumer, relative_offset)
    

class KafkaConsumer:
    """Wrapper for Kafka consumer.    

    Args:
        use_nqkafka (bool, optional): Determines whether self.instance is a NQKafkaConsumer (from the nqkafka package, can be thought of as a "mock") or actual KafkaConsumer (from the kafka-python package), which connects to a Kafka server. Defaults to False.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Attributes:
        instance (:obj:`nqkafka.NQKafkaConsumer` or :obj:`kafka.KafkaConsumer`): Determined from input parameters.
    """
    def __init__(self, *args, use_nqkafka=False, **kwargs):
        consumers_seek_to_beginning = 'consumers_seek_to_beginning' in kwargs and kwargs['consumers_seek_to_beginning']  #  == True
        if 'consumers_seek_to_beginning' in kwargs: kwargs.pop('consumers_seek_to_beginning')

        self.instance = NQKafkaConsumer(*args, **kwargs) if use_nqkafka else KafkaPythonConsumer(*args, **kwargs)

        if consumers_seek_to_beginning:
            consumer_seek_relative_offset(self.instance, -np.inf)

    def __getattr__(self, name):
        """Inherits the same attributes as the instance.

        Args:
            name (_type_): Name of the attribute.

        Returns:
            The attribute of the instance.
        """
        return self.instance.__getattribute__(name)
    
    def __iter__(self):
        """The iterator is the same as the iterator of the instance.

        Returns:
            The instance.
        """
        return self.instance.__iter__()
    

class KafkaProducer:
    """Wrapper for Kafka producer.

    Args:
        use_nqkafka (bool, optional): Determines whether self.instance is a NQKafkaProducer (from the nqkafka package, can be thought of as a "mock") or actual KafkaProducer (from the kafka-python package), which connects to a Kafka server. Defaults to False.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Attributes:
        instance (:obj:`nqkafka.NQKafkaProducer` or :obj:`kafka.KafkaProducer`): Determined from input parameters.
    """
    def __init__(self, *args, use_nqkafka=False, **kwargs):
        if "auto_offset_reset" in kwargs.keys(): kwargs.pop("auto_offset_reset")
        self.instance = NQKafkaProducer(*args, **kwargs) if use_nqkafka else KafkaPythonProducer(*args, **kwargs)

    def __getattr__(self, name):
        """Inherits the same attributes as the instance.

        Args:
            name (_type_): Name of the attribute.

        Returns:
            The attribute of the instance.
        """
        return self.instance.__getattribute__(name)
    
    def __iter__(self):
        """The iterator is the same as the iterator of the instance.

        Returns:
            The instance.
        """
        return self.instance.__iter__()
    

if __name__ == '__main__':
    bootstrap_servers = 'localhost:9092'
    consumer = KafkaConsumer('test_topic', bootstrap_servers=bootstrap_servers, use_nqkafka=True)

    for msg in consumer:
        print(msg.value)

