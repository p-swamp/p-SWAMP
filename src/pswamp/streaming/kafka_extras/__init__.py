from pswamp.streaming.kafka_extras.consumer_producer import Consumer, Producer, consumer_seek_relative_offset
# import kafka as proper_kafka
import pswamp.streaming.kafka_extras.utils as utils
try:
    import nqkafka.utils as nqkafka_utils
except ImportError:
    _has_nqkafka = False
else:
    _has_nqkafka = True
    
import pickle
    

def create_topic(name, io_kwargs, **kwargs):
    use_nqkafka = io_kwargs['type'] == "nqkafka"

    if use_nqkafka:
        n_samples = kwargs['n_samples'] if 'n_samples' in kwargs else 600
        nqkafka_utils.create_topic(name, bootstrap_servers=io_kwargs['bootstrap_servers'], n_samples=max(6000, n_samples) if name == 'pmudata' else n_samples)
    else:
        io_kwargs_tmp = io_kwargs.copy()
        kwargs_tmp = kwargs.copy()
        delete_keys = [
            "use_nqkafka",
            "auto_offset_reset",
            "consumers_start_from_beginning",
            "consumers_seek_to_beginning",
        ]
        [io_kwargs_tmp.pop(k) for k in delete_keys if k in io_kwargs_tmp.keys()]
        if 'n_samples' in kwargs_tmp:
            kwargs_tmp.pop('n_samples')
        utils.create_topic(name=name, io_kwargs=io_kwargs_tmp, **kwargs_tmp)
        
        
def get_last_message_from_topic(io_kwargs, topic):  # *args, **kwargs):
    use_nqkafka = 'use_nqkafka' in io_kwargs and io_kwargs['use_nqkafka']
    # serv = io_kwargs['bootstrap_servers']
    if use_nqkafka:
        return nqkafka_utils.get_last_message_from_topic(bootstrap_servers=io_kwargs['bootstrap_servers'], topic=topic)  # , *args)
    else:
        io_kwargs_tmp = io_kwargs.copy()
        if 'use_nqkafka' in io_kwargs:
            io_kwargs_tmp = io_kwargs.copy()
            io_kwargs_tmp.pop('use_nqkafka')
        return utils.get_last_message_from_topic(topic=topic, **io_kwargs_tmp)  #*args, **kwargs)
    
def send_to_kafka_topic(io_kwargs, topic, msg):
    producer = Producer(
        **io_kwargs
    )
    producer.send(topic, msg)
    producer.flush()
