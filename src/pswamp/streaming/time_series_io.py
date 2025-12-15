from collections import defaultdict
import numpy as np


class TimeSeriesIO:
    def __init__(self, time_stamps, measurements):
        self.time_stamps = time_stamps
        self.dt = np.round(np.median(time_stamps[1:] - time_stamps[:-1]), 3)
        self.measurements = measurements
        self.iterator = iter(zip(self.time_stamps, self.measurements))
        self.output = defaultdict(list)
        self.metadata = {
            "dt": self.dt,
            "header": [f"{m}" for m in range(len(measurements[0, :]))]
        }

    def get_config_frame(self):
        return self.metadata
    
    def get_sample_data_frame(self):
        # Get sample data frame without affecting the "main" iterator
        return self.metadata, self.time_stamps[0], self.measurements[0, :]
    
    def get_next_data_frame(self):
        time, measurement =  next(self.iterator)
        return self.metadata, time, measurement
    
    def handle_result(self, result):
        if result is None:
            return
        self.output["result"].append(result)

    def handle_output(self, topic, output):
        self.output[topic].append(output)

    def handle_status(self, status):
        self.output["status"].append(status)

    def seek_relative_input_offset(self, offset):
        pass

    def get_next_command(self):
        pass


class Decoder:
    def __init__(self, **app_kwargs):
        self.data_dtype = float
    
    def get_data_rate(self, data_frame):
        metadata, _, _ = data_frame
        return 1/metadata["dt"]
    
    def generate_header(self, sample_data_frame):
        metadata, _, _ = sample_data_frame
        header = metadata["header"]
        return header
    
    def get_time_stamp(self, data_frame):
        return data_frame[1]

    def data_frame_to_row(self, data_frame):
        metadata, time, measurements = data_frame
        return time, measurements