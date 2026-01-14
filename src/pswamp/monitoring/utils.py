import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from pswamp.streaming.kafka_extras import Producer
import pickle
from pswamp.streaming.kafka_extras import send_to_kafka_topic
import uuid
import time
import numpy as np
import warnings   


class TimeWindowRTApp:
    """
    Generic real-time application, which does nothing, except stores a time window with PMU data of specified length.
    The run_analysis method should be overwritten in order to perform various analysis. Results can be forwarded to
    another topic automatically.
    """
    def __init__(
        self,
        io_kwargs,
        time_window_length=None,
        n_samples_window=None,
        input_topic="pmudata",
        output_topic=None,
        input_meta_topic=None,
        output_meta_topic=None,
        phasor_selection=None,
        channel_selection=None,
        channel_selection_idx=None,
        eval_freq=None,
        auto_adjust_offset=False,
        t_end=np.inf
    ):
        """

        Args:
            time_window_length: Length of the time window containing the PMU measurements
        """
        self.t_end = t_end
        self.eval_freq = eval_freq
        self.app_name = self.__class__.__name__

        self.pmu_tw = PMUTimeWindowOnline(
            n_samples=n_samples_window,
            window_length=time_window_length,
            kafka_topic=input_topic,
            io_kwargs=io_kwargs,
            # phasor_selection=phasor_selection,
            channel_selection=channel_selection,
            channel_selection_idx=channel_selection_idx,
            auto_adjust_offset=auto_adjust_offset,
        )
        self.pmu_tw.initialize()
        # self.pmu_tw_thread = threading.Thread(target=self.pmu_tw.run, daemon=True)

        self.kafka_server = io_kwargs['bootstrap_servers']

        # If output topic is specified, the results returned by "run_analysis" will be forwarded to this topic.
        self.output_topic = output_topic

        # The output_meta_topic can be used for sending static information about this application to other applications,
        # for instance information about the number of channels, parameters, etc. If output_meta_topic is specified,
        # then whatever returned by the "output_metadata" method will be forwarded to this topic.
        if self.output_topic is not None:
            self.kafka_producer = Producer(
                **io_kwargs, value_serializer=pickle.dumps
            )
        else:
            self.kafka_producer = None

        self._stopped = False

    def output_metadata(self):
        # This can be used for sending static information about this application to other applications.
        return None

    def send_output_metadata(self):
        # Sends whatever returned by the output_metadata to the Kafka topic self.output_meta_topic.
        if (self.output_topic is not None) and (self.output_meta_topic is not None):
            send_to_kafka_topic(
                self.io_kwargs, self.output_meta_topic, self.output_metadata()
            )

    def stop(self):
        """

        Returns:
            None

        """
        self._stopped = True

    def run_analysis(self, t, phasors):
        """
        This should be overwritten.
        :param t:
        :param phasors:
        :return:
        """
        return None

    def run(self):

        # Start filling the time window (with PMU data from the specified Kafka topic)
        # self.pmu_tw_thread.start()
        self.pmu_tw.initialize()
        if self.eval_freq is None:
            self.eval_freq = round(1/self.pmu_tw.dt)

        t_eval_target = round(1/self.eval_freq, 2)

        assert round(1/self.pmu_tw.dt) % self.eval_freq == 0
        
        kafka_message = next(iter(self.pmu_tw.pmu_stream))
        t_next_eval = round(kafka_message.value.get_time_stamp() + t_eval_target)
        
        def t_time_window(): return self.pmu_tw.tw.get_time()[-1]
        
        while not self._stopped:
            if t_next_eval >= self.t_end:
                self.stop()
                break
            # Get new data
            
            while np.nan_to_num(t_time_window()) < t_next_eval:
                # Get data
                try:
                    kafka_message = next(iter(self.pmu_tw.pmu_stream))
                    self.pmu_tw.update_window(kafka_message.value)
                except StopIteration as e:
                    self.stop()
                    break

            # print('Running analysis')
            
            t_eval_0 = time.time()
            # Get data from time window
            t, phasors = self.pmu_tw.tw.get()
            result = self.run_analysis(t, phasors)
            if result is not None:
                if self.kafka_producer is not None:
                    self.kafka_producer.send(self.output_topic, result)
                    self.kafka_producer.flush()

            t_eval = time.time() - t_eval_0
            if t_eval > t_eval_target:
                warnings.warn(f'Application {self.app_name}: Overflow!')
            
            t_next_eval += t_eval_target


class StatusCom:
    def __init__(self, io_kwargs, status_topic='application.status'):
        self.status_topic = status_topic
        self.producer = Producer(**io_kwargs, value_serializer=pickle.dumps)
        self.uuid = uuid.uuid4()
        self.app_name = self.__class__.__name__

        self.status_update_thread = threading.Thread(target=self.update_status, daemon=True)
        self.status_update_thread.start()
        self.status = 'Undefined'

    def update_status(self):
        while True:
            self.producer.send(self.status_topic, [self.uuid, self.app_name, self.status])