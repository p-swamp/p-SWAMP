from kafka import KafkaProducer, KafkaConsumer
import json
import pickle
# from pswamp.streaming import get_last_message_from_topic
from kafka.structs import TopicPartition
from pswamp.test_utils.offline.sample_dataframe import create_sample_data_frame


def get_last_message_from_topic(kafka_kwargs, topic):
    consumer = KafkaConsumer(**kafka_kwargs)
    partition_idxs = consumer.partitions_for_topic(topic)
    partition_idx = next(iter(partition_idxs))
    partition = TopicPartition(topic, partition_idx)

    end_offset = consumer.end_offsets([partition])[partition]

    consumer = KafkaConsumer(**kafka_kwargs)  # , offset=end_offset)
    consumer.assign([partition])

    end_offset = end_offset - 1 if end_offset > 0 else 0
    consumer.seek(partition, end_offset)
    return next(iter(consumer)).value

def encoder(msg):
    if isinstance(msg, dict):
        return json.dumps(msg).encode("utf8")
    return json.dumps({"__bytes__": pickle.dumps(msg).decode("latin")}).encode("utf8")
    
def decoder(msg):
    msg_decoded = json.loads(msg)
    if "__bytes__" in msg_decoded:
        return pickle.loads(msg_decoded["__bytes__"].encode("latin"))
    return msg_decoded

prod = KafkaProducer(
    bootstrap_servers="localhost:9094",
    value_serializer=encoder)  # lambda msg: json.dumps(msg).encode("utf8"))
# prod = KafkaProducer(bootstrap_servers="localhost:9094", value_serializer=pickle.dumps)
msg_dict = {"x": 2, "y": [3.0, 1.0, 2.0]}
_ = prod.send(topic="test_topic", value=msg_dict)
prod.flush()

msg_dict_recv = get_last_message_from_topic(
    kafka_kwargs={"bootstrap_servers": "localhost:9094", "value_deserializer": decoder},
    topic="test_topic",
)

msg_pmu = create_sample_data_frame()
_ = prod.send(topic="test_topic", value=msg_pmu)
prod.flush()

msg_pmu_recv = get_last_message_from_topic(
    kafka_kwargs={"bootstrap_servers": "localhost:9094", "value_deserializer": decoder},
    topic="test_topic",
)

assert msg_pmu_recv.get_phasors() == msg_pmu.get_phasors()
assert msg_pmu_recv.get_freq() == msg_pmu.get_freq()
assert msg_pmu_recv.get_time_stamp() == msg_pmu.get_time_stamp()
assert msg_dict_recv == msg_dict

# data_dict = data.__dict__
# data_dict["cfg"] = data.__dict__["cfg"].__dict__
# dir(data)

# prod.send(topic="test_topic", value=data)

# def decoder(msg):
#     if isinstance(msg, bytes):
#         return pickle.loads(msg)
#     json.loads(msg)

# isinstance(encoder(msg), bytes)

# pickle.loads(pickle.dumps(msg))
# pickle.dumps(msg)


# isinstance(encoder(msg), bytes)
# isinstance(encoder(data), bytes)

# json.dumps({"__bytes__": pickle.dumps(data)})



msg = get_last_message_from_topic(
    **{
        "bootstrap_servers": "localhost:9094", 
        "value_deserializer": decoder},
    topic="test_topic")

data_frame = pickle.loads(msg["__bytes__"].encode("latin"))
data_frame.get_phasors()


cons = KafkaConsumer(
    "test_topic",
    bootstrap_servers="localhost:9094",
    # value_deserializer=lambda msg: json.dumps(msg).encode("utf8"),
    # auto_offset_reset=True,
)
from pswamp.streaming import consumer_seek_relative_offset
consumer_seek_relative_offset(cons, 0)

for msg in cons:
    print(msg)
    break
# next(iter(cons))
DataFrame

import pydantic

from synchrophasor.frame import DataFrame
class DataFramePyd(DataFrame, pydantic.BaseModel):
    pass

DataFramePyddata
pydantic.dumps