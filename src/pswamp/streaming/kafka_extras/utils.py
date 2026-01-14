try:
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError, UnknownTopicOrPartitionError
    # from pswamp.streaming import KafkaConsumer, KafkaProducer
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.structs import TopicPartition
except ImportError:
    _has_kafka = False
else:
    _has_kafka = True
    
from pswamp.streaming.utils import decoder


def create_topic(
    io_kwargs, name, num_partitions=1, replication_factor=1, **topic_kwargs
):
    admin_client = KafkaAdminClient(
        **{k: io_kwargs[k] for k in io_kwargs if k != "type"}
    )
    new_topic = NewTopic(
        name=name,
        num_partitions=num_partitions,
        replication_factor=replication_factor,
        **topic_kwargs
    )

    try:
        admin_client.create_topics(new_topics=[new_topic], validate_only=False)
        print("Topic Created Successfully")
    except TopicAlreadyExistsError as e:
        print("Topic Already Exist")
    except Exception as e:
        print(e)


def delete_topics(io_kwargs, topic_names):
    # This has not been tested.
    # Deleting topics might cause error when running Kafka on Windows (something with log files)
    io_kwargs = io_kwargs.copy()
    delete_keys = ["use_nqkafka", "auto_offset_reset", "consumers_start_from_beginning"]
    [io_kwargs.pop(k) for k in delete_keys if k in io_kwargs.keys()]

    admin_client = KafkaAdminClient(**io_kwargs)

    try:
        for topic_name in topic_names:
            admin_client.delete_topics(topics=[topic_name])
            print("Topic Deleted Successfully")
    except UnknownTopicOrPartitionError as e:
        print("Topic Doesn't Exist")
    except Exception as e:
        print(e)


def get_last_message_from_topic(io_kwargs, topic):

    consumer = KafkaConsumer(**io_kwargs)
    partition_idxs = consumer.partitions_for_topic(topic)
    partition_idx = next(iter(partition_idxs))
    partition = TopicPartition(topic, partition_idx)

    end_offset = consumer.end_offsets([partition])[partition]

    consumer = KafkaConsumer(
        **io_kwargs, value_deserializer=decoder
    )  # , offset=end_offset)
    consumer.assign([partition])
    
    end_offset = end_offset - 1 if end_offset > 0 else 0
        
    consumer.seek(partition, end_offset)

    return next(iter(consumer)).value


def consumer_seek_relative_offset(consumer, relative_offset):
    consumer.topics()
    partition_assignment = consumer.assignment()
    assert len(partition_assignment) == 1
    partition = next(iter(partition_assignment))
    current_offset = consumer.position(partition)
    new_offset = current_offset + relative_offset
    try:
        consumer.seek(partition, new_offset)
    except AssertionError:
        consumer.seek(partition, 0)
