from pswamp.streaming.kafka_extras import KafkaConsumer
import numpy as np
import threading
from pswamp.streaming.kafka_extras import consumer_seek_relative_offset
import time
from pswamp.streaming.kafka_extras import KafkaConsumer
import numpy as np
import threading
import pickle


class TopicGetter:
    def __init__(self, topic, kafka_kwargs, relative_start_offset=-np.inf, empty_topic_timeout=0.2):
        self.data = []
        self.consumer = KafkaConsumer(topic, value_deserializer=pickle.loads, **kafka_kwargs)
        # consumer_seek_relative_offset(self.consumer, relative_start_offset)
        self.consumer_thread = threading.Thread(target=self.run, daemon=True)
        self.consumer_thread.start()
        self.newest_msg = None

        timeout_t0 = time.time()
        while self.newest_msg is None and (time.time() - timeout_t0) < empty_topic_timeout:
            time.sleep(0.1)
        last_data = self.newest_msg
        time.sleep(0.1)
        while not (last_data == self.newest_msg):
            # print('Waiting')
            last_data = self.newest_msg
            time.sleep(0.1)

    def run(self):
        for msg in self.consumer:
            # print(msg)
            self.newest_msg = msg
            self.store_data(msg)

    def store_data(self, msg):
        self.data.append(msg)


class TopicToFile(TopicGetter):
    def __init__(self, *args, file_path, **kwargs):
        self.file_path = file_path
        self.file = open(file_path, 'wb')
        super().__init__(*args, **kwargs)
        self.file.close()

    def store_data(self, msg):
        pickle.dump(msg, self.file)


class TopicFromFile:
    def __init__(self, file_path):
        self.file_path = file_path
        file = open(file_path, 'rb')
        self.data = []
        while True:
            try:
                msg = pickle.load(file)
                self.data.append(msg)
            except EOFError:
                break

        file.close()