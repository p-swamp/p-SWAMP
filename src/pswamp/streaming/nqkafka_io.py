# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import time
from nqkafka import KafkaConsumer, KafkaProducer, utils as nqkafka_utils
import pickle


class NQKafkaIO:
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
        input_topic="pmudata",
        output_topic=None,
        status_topic="application.status",
        t_start=None,
        command_topic="application.commands",
        # auto_adjust_offset=True,
        # *args,
    ):
        self.input_topic = input_topic
        self.io_kwargs = io_kwargs
        self.kafka_server = io_kwargs["bootstrap_servers"]
        self.command_topic = command_topic

        self.input_stream = KafkaConsumer(self.input_topic, **io_kwargs
        )
        # sample_frame = self.get_sample_data_frame()

        # If output topic is specified, the results returned by "run_analysis" will be forwarded to this topic.
        self.output_topic = output_topic

        if self.output_topic is not None:
            self.kafka_producer = KafkaProducer(**io_kwargs
            )
        else:
            self.kafka_producer = None

        self.status_topic = status_topic
        self.status_producer = KafkaProducer(**io_kwargs)

        if self.command_topic is not None:
            self.command_consumer = KafkaConsumer(self.command_topic, **self.io_kwargs)
        else:
            self.command_consumer = None

    def get_sample_data_frame(self):
        """Get sample data frame from input (without affecting input stream)

        Returns:
            _type_: Data frame
        """
        while True:
            sample_data_frame = nqkafka_utils.get_last_message_from_topic(
                bootstrap_servers=self.io_kwargs["bootstrap_servers"],
                topic=self.input_topic)
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
        nqkafka_utils.consumer_seek_relative_offset(self.input_stream, n_samples)
