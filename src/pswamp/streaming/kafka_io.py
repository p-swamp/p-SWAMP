import time
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import TopicPartition
from pswamp.streaming.utils import encoder, decoder
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, UnknownTopicOrPartitionError



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


def get_last_message_from_topic(topic, **io_kwargs):
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
        **topic_kwargs,
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


class KafkaIO:
    """Online input/output object to be used by applications.
    
    TODO: Remove t_start from arguments.
    
    Args:
        io_kwargs: Kwargs that will be used in kafka consumers and producers.
        input_topic: Kafka topic for input data stream.
        output_topic: Kafka topic for output data stream.
        status_topic: Kafka topic for status messages.
        t_start: Not used anymore.
        command_topic: Kafka topic for application commands.
    
    """
    def __init__(
        self,
        io_kwargs,
        input_topic='pmudata',
        output_topic=None,
        status_topic='application.status',
        t_start=None,
        command_topic="application.commands",
        # **io_kwargs,
        # auto_adjust_offset=True,
        # *args,
    ):

        self.input_topic = input_topic
        self.io_kwargs = io_kwargs
        self.kafka_server = io_kwargs['bootstrap_servers']
        self.command_topic = command_topic

        self.input_stream = KafkaConsumer(
            self.input_topic, value_deserializer=decoder, **io_kwargs
        )
        # sample_frame = self.get_sample_data_frame()
  
        # If output topic is specified, the results returned by "run_analysis" will be forwarded to this topic.
        self.output_topic = output_topic

        if self.output_topic is not None:
            self.kafka_producer = KafkaProducer(
                **io_kwargs, value_serializer=encoder
            )
        else:
            self.kafka_producer = None

        self.status_topic = status_topic
        self.status_producer = KafkaProducer(
            **io_kwargs, value_serializer=encoder)
        
        self.command_consumer = KafkaConsumer(
            self.command_topic, **self.io_kwargs)

    def get_sample_data_frame(self):
        """Get sample data frame from input (without affecting input stream)

        Returns:
            _type_: Data frame
        """
        while True:
            sample_data_frame = get_last_message_from_topic(
                self.input_topic, **self.io_kwargs
            )
            if sample_data_frame is not None:
                break
            time.sleep(1)
        return sample_data_frame
    
    def get_sample_pmu_data_frame(self):
        """Included for backwards compatibility

        Returns:
            _type_: Data frame
        """
        return self.get_sample_data_frame()
    
    def get_config_frame(self):
        """Get config frame

        Returns:
            _type_: Config frame
        """
        return self.get_sample_data_frame().cfg

    def get_next_data_frame(self):
        """Get next dataframe

        Returns:
            _type_: Data frame
        """
        return next(iter(self.input_stream)).value
    
    def get_next_command(self):
        """Get command frame

        Returns:
            _type_: Command frame
        """
        return next(iter(self.command_consumer))

    def handle_result(self, result):
        """Handle result once analysis completes. If result is not None, the
        result will be sent to the output topic.

        Args:
            result (_type_): Result
        """
        if result is not None and self.kafka_producer is not None:
            self.kafka_producer.send(self.output_topic, result)
            self.kafka_producer.flush()

        # return self.pmu_data_frame_generator.get_next_data_frame()
        # return next(iter(self.pmu_tw.pmu_stream)).value

    def handle_output(self, topic, output):
        if self.kafka_producer is None:
            return
        self.kafka_producer.send(topic, output)
        self.kafka_producer.flush()

    def handle_status(self, message):
        """Sends the satus message to the status topic.

        Args:
            message (_type_): Status message
        """
        self.status_producer.send(self.status_topic, message)

    def seek_relative_input_offset(self, n_samples):
        """Changes the offset of the input data consumer according to the
        specified number of samples.

        Args:
            n_samples (int): Number of samples to shift
        """
        consumer_seek_relative_offset(self.input_stream, n_samples)

