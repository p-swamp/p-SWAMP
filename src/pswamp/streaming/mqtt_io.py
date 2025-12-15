import paho.mqtt.client as mqtt #import the client1
import paho.mqtt.subscribe as subscribe

import queue
import time
import pickle


class MQTTConsumer:
    def __init__(self, topic, hostname, port):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self.on_message
        self.client.connect(hostname, port=port)
        self.client.loop_start()
        self.client.subscribe(topic)
        self.last_msg = ""
        self.output_queue = queue.Queue(maxsize=3)
    
    def get_next(self):
        new_msg = self.output_queue.get()
        return pickle.loads(new_msg.payload)

    def on_message(self, client, userdata, message):
        self.output_queue.put(message)

    def __iter__(self):
        return self
    
    def __next__(self):
        return self.get_next()



class MQTTProducer:
    def __init__(self, hostname, port):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(hostname, port=port) #connect to broker
        # self.client.loop_start()


    def publish(self, topic, msg):
        msg_bytes = pickle.dumps(msg)
        return self.client.publish(topic, msg_bytes)
    
    def send(self, *args, **kwargs):
        return self.publish(*args, **kwargs)
    
    def flush(self, *args, **kwargs):
        pass
    

class MQTT_IO:
    """Online input/output object to be used by applications.
    
    TODO: Remove t_start from arguments.
    
    Args:
        kafka_kwargs: Kwargs that will be used in kafka consumers and producers.
        input_topic: Kafka topic for input data stream.
        output_topic: Kafka topic for output data stream.
        status_topic: Kafka topic for status messages.
        t_start: Not used anymore.
        command_topic: Kafka topic for application commands.
    
    """
    def __init__(
        self,
        mqtt_kwargs,
        input_topic='pmudata',
        output_topic=None,
        status_topic='application.status',
        command_topic="application.commands",
        # auto_adjust_offset=True,
        # *args,
    ):

        self.input_topic = input_topic
        self.mqtt_kwargs = mqtt_kwargs
        # self.mqtt_server = mqtt_kwargs['ip'], mqtt_kwargs['port']
        self.command_topic = command_topic

        self.input_stream = MQTTConsumer(self.input_topic, **mqtt_kwargs)

        # If output topic is specified, the results returned by "run_analysis" will be forwarded to this topic.
        self.output_topic = output_topic

        if self.output_topic is not None:
            self.producer = MQTTProducer(**mqtt_kwargs)
        else:
            self.producer = None

        self.status_topic = status_topic
        self.status_producer = MQTTProducer(**mqtt_kwargs)
        
        self.command_consumer = MQTTConsumer(self.command_topic, **self.mqtt_kwargs)

    def get_sample_data_frame(self):
        """Get sample data frame from input (without affecting input stream)

        Returns:
            _type_: Data frame
        """
        msg = subscribe.simple(self.input_topic, **self.mqtt_kwargs)
        return pickle.loads(msg.payload)

    
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
        return self.input_stream.get_next()
    
    def get_next_command(self):
        """Get command frame

        Returns:
            _type_: Command frame
        """
        return self.command_consumer.get_next()

    def handle_result(self, result):
        """Handle result once analysis completes. If result is not None, the
        result will be sent to the output topic.

        Args:
            result (_type_): Result
        """
        if result is not None and self.producer is not None:
            self.producer.send(self.output_topic, result)
            self.producer.flush()

        # return self.pmu_data_frame_generator.get_next_data_frame()
        # return next(iter(self.pmu_tw.pmu_stream)).value

    def handle_output(self, topic, output):
        if self.producer is None:
            return
        self.producer.send(topic, output)
        self.producer.flush()

    def handle_status(self, message):
        """Sends the satus message to the status topic.

        Args:
            message (_type_): Status message
        """
        self.status_producer.send(self.status_topic, message)

    def seek_relative_input_offset(self, n_samples):
        pass
