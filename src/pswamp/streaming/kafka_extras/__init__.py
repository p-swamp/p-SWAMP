from pswamp.streaming.kafka_extras.consumer_producer import KafkaConsumer, KafkaProducer, consumer_seek_relative_offset
import kafka as proper_kafka
import pswamp.streaming.kafka_extras.utils as utils
import nqkafka.utils as nqkafka_utils
import pickle
    

def create_topic(name, kafka_kwargs, **kwargs):
    use_nqkafka = 'use_nqkafka' in kafka_kwargs and kafka_kwargs['use_nqkafka']

    if use_nqkafka:
        n_samples = kwargs['n_samples'] if 'n_samples' in kwargs else 600
        nqkafka_utils.create_topic(name, bootstrap_servers=kafka_kwargs['bootstrap_servers'], n_samples=max(6000, n_samples) if name == 'pmudata' else n_samples)
    else:
        kafka_kwargs_tmp = kafka_kwargs.copy()
        kwargs_tmp = kwargs.copy()
        delete_keys = ["use_nqkafka", "auto_offset_reset",
            "consumers_start_from_beginning"]
        [kafka_kwargs_tmp.pop(k) for k in delete_keys if k in kafka_kwargs_tmp.keys()]
        if 'n_samples' in kwargs_tmp:
            kwargs_tmp.pop('n_samples')
        utils.create_topic(name=name, kafka_kwargs=kafka_kwargs_tmp, **kwargs_tmp)
        
        
def get_last_message_from_topic(kafka_kwargs, topic):  # *args, **kwargs):
    use_nqkafka = 'use_nqkafka' in kafka_kwargs and kafka_kwargs['use_nqkafka']
    serv = kafka_kwargs['bootstrap_servers']
    if use_nqkafka:
        return nqkafka_utils.get_last_message_from_topic(bootstrap_servers=kafka_kwargs['bootstrap_servers'], topic=topic)  # , *args)
    else:
        kafka_kwargs_tmp = kafka_kwargs.copy()
        if 'use_nqkafka' in kafka_kwargs:
            kafka_kwargs_tmp = kafka_kwargs.copy()
            kafka_kwargs_tmp.pop('use_nqkafka')
        return utils.get_last_message_from_topic(kafka_kwargs=kafka_kwargs_tmp, topic=topic)  #*args, **kwargs)
    
def send_to_kafka_topic(kafka_kwargs, topic, msg):
    producer = KafkaProducer(
        **kafka_kwargs, value_serializer=pickle.dumps
    )
    producer.send(topic, msg)
    producer.flush()
