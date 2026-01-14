import numpy as np
from .time_window_labeled import TimeWindowLabeled
from pswamp.streaming import get_last_message_from_topic
import time
from pswamp.streaming import consumer_seek_relative_offset
from pswamp.streaming import Consumer
from pswamp.utils.time_window_labeled import GrowingTimeWindowLabeled
from pswamp.utils.time_window_labeled import Indexer


class PMUDecoder:
    def __init__(
            self,
            channel_selection=None,
            channel_selection_idx=None,
            substitute_zero_freq_with_nan=True):
        
        self.channel_selection = channel_selection
        if channel_selection_idx is not None:
            self.channel_selection = None
        self.channel_selection_idx = np.array(
            channel_selection_idx) if channel_selection_idx is not None else slice(None)
        
        self.substitute_zero_freq_with_nan = substitute_zero_freq_with_nan
        self.data_dtype = float

    def get_time_stamp(self, data_frame):
        return data_frame.get_time_stamp()
    
    def get_data_rate(self, sample_data_frame):
        return sample_data_frame.cfg.get_data_rate()
    
    def generate_header(self, sample_data_frame=None, config_frame=None):
        if config_frame is None:
            config_frame = sample_data_frame.cfg
        station_names = config_frame.get_station_name()
        phasor_channel_names = config_frame.get_channel_names()
        phasor_ph_units = config_frame.get_ph_units()

        n_stations = len(station_names)

        header_station_names = [st.strip() for st in station_names]*2
        header_channel_names = ['Frequency'] * \
            n_stations + ['Dfrequency']*n_stations
        header_types = ['f']*n_stations + ['Df']*n_stations
        for st, ch, ph_type in zip(header_station_names, phasor_channel_names, phasor_ph_units):
            for c, t in zip(ch, ph_type):
                [header_station_names.append(st.strip()) for _ in range(2)]
                header_channel_names.append(c.strip()+'_Magnitude')
                header_channel_names.append(c.strip()+'_Angle')
                header_types.append(f'{t[1]}_Magnitude')
                header_types.append(f'{t[1]}_Angle')

        if self.channel_selection is not None:
            channel_indexer = Indexer(
                header=dict(
                    station=header_station_names,
                    channel=header_channel_names,
                    measurement=header_types,
                )
            )
            self.channel_selection_idx = channel_indexer.get_col_idx(
                **self.channel_selection)

        if self.channel_selection_idx is None:
            self.channel_selection_idx = slice(None)

        return dict(
            station=np.array(header_station_names)[self.channel_selection_idx],
            channel=np.array(header_channel_names)[self.channel_selection_idx],
            measurement=np.array(header_types)[self.channel_selection_idx],
        )
    
    def data_frame_to_row(self, pmu_data_frame):
        t = pmu_data_frame.get_time_stamp()
        freq = np.array(pmu_data_frame.get_freq())
        dfreq = np.array(pmu_data_frame.get_dfreq())
        if self.substitute_zero_freq_with_nan:
            freq[freq==0] = np.nan
            dfreq[dfreq==0] = np.nan
        
        phasors = np.concatenate(
            pmu_data_frame.get_phasors(convert2polar=False)).flatten()

        return t, np.concatenate([freq, dfreq, phasors])[self.channel_selection_idx]

class PMUTimeWindow:
    def __init__(
            self,
            n_samples=None,
            window_length=None,
            time_window_type=TimeWindowLabeled,
            substitute_zero_freq_with_nan=True,
            channel_selection=None,
            channel_selection_idx=None):
        self.time_window_type = time_window_type
        self.tw = None
        self.header = None
        self.n_samples = n_samples
        self.window_length = window_length

        if self.n_samples is None and self.window_length is None:
            self.window_length = None
            self.time_window_type = GrowingTimeWindowLabeled

        self.is_initialized = False
        self.n_channels = None  # n_channels
        self.dt = np.nan
        self.fs = np.nan

        self.pmu_decoder = PMUDecoder(
            channel_selection,
            channel_selection_idx,
            substitute_zero_freq_with_nan)

    def initialize_from_config_frame(self, config_frame):
        self.fs = config_frame.get_data_rate()
        self.dt = 1 / self.fs

        if self.n_samples is not None:
            self.window_length = self.n_samples * self.dt
        elif self.window_length is not None:
            self.n_samples = int(round(self.window_length / self.dt))

        self.tw = self.time_window_type(
            self.n_samples, dtype=self.pmu_decoder.data_dtype,
            header=self.pmu_decoder.generate_header(config_frame=config_frame)
        )
        self.header = self.tw.header
        self.n_channels = self.tw.n_cols
        self.is_initialized = True

    def update_window(self, pmu_data_frame):
        time_stamp, data = self.pmu_decoder.data_frame_to_row(pmu_data_frame)
        self.tw.append(time_stamp, data)


class PMUTimeWindowOnline(PMUTimeWindow):
    # TODO: To be removed
    """This class is intended for consuming PMU data from a specified Kafka topic and storing the last samples (n_samples) in a
    TimeWindow object."""

    def __init__(
        self,
        io_kwargs={},
        kafka_topic="pmudata",
        auto_adjust_offset=False,
        **kwargs,
    ):
        # self.data_dtype = float

        # self.kafka_server = io_kwargs['bootstrap_servers']
        self.kafka_topic = kafka_topic
        self.io_kwargs = io_kwargs
        self.auto_adjust_offset = auto_adjust_offset
        self.pmu_stream = Consumer(
            self.kafka_topic, **io_kwargs
        )
        super().__init__(**kwargs)

        self._is_stopped = False

    def initialize(self):
        msg = None
        while True:
            msg = get_last_message_from_topic(
                self.kafka_topic, **self.io_kwargs)
            if not msg is None:
                break
            else:
                time.sleep(1)

        config_frame = msg.cfg
        self.initialize_from_config_frame(config_frame)
        if self.auto_adjust_offset:
            consumer_seek_relative_offset(self.pmu_stream, -self.n_samples)

    def run(self):
        if not self.is_initialized:
            self.initialize()

        for kafka_message in self.pmu_stream:
            self.update_window(kafka_message.value)
            if self._is_stopped:
                break

    def stop(self):
        self._is_stopped = True


# if __name__ == "__main__":

#     import pathlib
#     import sys
#     import os
#     from pswamp.test_utils.offline.csv_to_pmu import CSVToPMUData

#     pmu_data_path = pathlib.Path(os.getcwd()) / \
#         'examples'/'recorded_pmu_data'/'data'
#     sys.path.append(str(pmu_data_path))

#     import load_pmu_data
#     data = load_pmu_data.load()
#     csv_to_pmutw = CSVToPMUData(
#         time=data['time'],
#         phasors=data['phasors'],
#         station_names=data['stations'],
#         channel_names=data['channels'],
#     )

#     # Generate data frames according to C37.118 standard
#     data_frames = csv_to_pmutw.generate_pmu_data_frames()
#     data_frame = data_frames[0]

#     pmu_tw = PMUTimeWindowOfflineV1(n_samples=1)
#     pmu_tw.initialize_from_config_frame(data_frame.cfg)
#     pmu_tw.update_window(data_frame)
#     pmu_tw.tw.get_col()

#     pmu_tw.tw.header

#     pmu_tw = PMUTimeWindowOfflineV2(n_samples=1, channel_selection={
#                                     'measurement': 'v_Angle'})
#     pmu_tw.initialize_from_config_frame(data_frame.cfg)
#     pmu_tw.update_window(data_frame)
#     pmu_tw.tw.header
