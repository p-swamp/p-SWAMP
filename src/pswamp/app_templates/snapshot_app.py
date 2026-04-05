# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from pswamp.streaming import BaseIO
import threading
import time
import numpy as np
import warnings
import uuid
from pswamp.app_templates.status_reporting import ReportingApp
from pswamp.utils.misc import convert_time_stamp_to_seconds
import datetime


class SnapshotApp:
    """General application template.

    New applications could be defined by inheriting from this template, and
    defining the "run_analysis" method.

    Args:
        io: Input/output object (normally connects to Kafka)
        eval_freq: How often the evaluation of the application should be run
            (e.g., the part in "run_analysis")
        t_end: The application will stop running when this time is reached
            (but can be restarted)
        t_start: The application will ask the io object (first argument) to
            search for t_start when initializing.
        app_name: Name for the application.
        input_decoder: This determines how the input is read/decoded (if no
            decoder is specified, a decoder for PMU data frames will be used.)
        decoder_kwargs: Kwargs for initalizing the "input_decoder".
        report_status: If enabled, status messages will be emitted.
        io_kwargs: Any other kwargs will be forwarded to the io object.
    """
    def __init__(
        self,
        io=None,
        eval_freq=None,
        t_end=None,
        t_start=None,
        app_name=None,
        input_decoder=None,
        decoder_kwargs={},
        report_status=False,
        **kwargs,
    ):
        self.app_name = app_name if app_name is not None else self.__class__.__name__
        self.uuid = str(uuid.uuid4())
        self.status = 'Undefined'


        self.eval_freq = eval_freq
        if isinstance(t_end, datetime.datetime):
            self.t_end = convert_time_stamp_to_seconds(t_end)
        elif t_end is not None:
            self.t_end = t_end
        else:
            self.t_end = np.inf
        self._stopped = False
        # self.pmu_data_frame_generator = pmu_data_frame_generator
        self.most_recent_data_frame = None
        self.most_recent_time_stamp = None
        self.last_result = None
        self.t_next_eval = None
        self.update_callbacks = []

        if io is None:
            self.io = BaseIO(**kwargs)
        else:
            self.io = io
        if input_decoder is None:
            from pswamp.utils.pypmu import PMUDecoder
            input_decoder = PMUDecoder

        self.decoder = input_decoder(
            **decoder_kwargs)

        sample_frame = self.io.get_sample_data_frame()
        self.time_stamp_at_init = self.get_time_stamp_from_frame(sample_frame)

        if t_start is not None:
            if isinstance(t_start, float) or isinstance(t_start, int):
                # t_start = convert_time_stamp_to_seconds(t_start)
                t_start = datetime.datetime.fromtimestamp(t_start, datetime.UTC)
            data_rate = self.get_input_data_rate()
            input_stream_current_time = datetime.datetime.fromtimestamp(self.time_stamp_at_init, datetime.UTC)
            relative_offset = int(((input_stream_current_time - t_start).total_seconds() + 5)*data_rate)
            self.io.seek_relative_input_offset(-relative_offset)
        
        self.input_dt = 1/self.get_input_data_rate()
        self.pmu_dt = self.input_dt

        self.results = []
        if self.eval_freq is None:
            self.eval_freq = round(1/self.input_dt)

        self.t_eval_target = round(1/self.eval_freq, 2)

        if self.eval_freq > 1/self.input_dt:
            print("Evaluation frequency can not be higher than input frequency")
            self.eval_freq = 1/self.input_dt
        
        if self.eval_freq > 1:
            assert round(1/self.input_dt) % self.eval_freq == 0
        else:  # Allow slower evaluation frequency. Should be a check here also?
            assert round(1/self.eval_freq, 2) - round(1/self.eval_freq) == 0

        if report_status:
            self.reporter = ReportingApp(self)
            self.update_callbacks.append(self.reporter.communicate_status)


    def get_sample_data_frame(self):
        return self.io.get_sample_data_frame()
    
    def get_input_data_rate(self):
        df = self.io.get_sample_data_frame()
        return self.decoder.get_data_rate(df)
    
    def get_time_stamp_from_frame(self, data_frame):
        return self.decoder.get_time_stamp(data_frame)

    def stop(self):
        self._stopped = True

    def get_config_frame(self):
        return self.io.get_config_frame()

    def get_next_data_frame(self):
        return self.io.get_next_data_frame()
        # return next(iter(self.pmu_tw.pmu_stream)).value

    def handle_result(self, result):
        self.io.handle_result(result)

    def run_analysis(self, time_stamp, measurements):
        pass
        # print(time_stamp)  # , measurements.shape)

    def run_in_thread(self):
        self.runner_thread = threading.Thread(target=self.run, daemon=True)
        self.runner_thread.start()

    
    def run(self):

        while not self._stopped:
            result = self.update()
            self.last_result = result
            self.handle_result(result)
            [callback() for callback in self.update_callbacks]


    def update(self):
        # Get next data frame
        try:
            self.most_recent_data_frame = self.get_next_data_frame()
            self.most_recent_time_stamp = self.get_time_stamp_from_frame(
                self.most_recent_data_frame
            )
            if self.most_recent_data_frame is None:
                self.stop()
                return
        except StopIteration:
            self.stop()
            return

        # Only on first iteration:
        if self.t_next_eval is None:
            self.t_next_eval = self.get_time_stamp_from_frame(self.most_recent_data_frame)

        # If end time was reached
        if self.t_next_eval >= self.t_end or self.get_time_stamp_from_frame(self.most_recent_data_frame) >= self.t_end:
            self.stop()
            return

        t_eval_0 = time.time()

        self.update_storage(self.most_recent_data_frame)
        if np.nan_to_num(self.get_time_stamp_from_frame(self.most_recent_data_frame)) > self.t_next_eval:
            self.t_next_eval += self.t_eval_target
            result = self.get_result(self.most_recent_data_frame)
        else:
            result = None           

        t_eval = time.time() - t_eval_0
        if t_eval > self.t_eval_target:
            warnings.warn(f'Application {self.app_name}: Overflow!')

        return result

    def update_storage(self, next_data_frame):
        pass

    def get_result(self, next_data_frame):
        return self.run_analysis(next_data_frame.get_time_stamp(), next_data_frame)
    
    def start(self):
        self.main_thread = threading.Thread(target=self.run)
        self.main_thread.start()

        while not self._stopped:
            msg = self.io.get_next_command()
            if not msg.value['target_uuid'] == self.uuid:
                continue
            
            if msg.value['command'] == 'open_console':
                self.console_popup()

            if msg.value['command'] == 'stop':
                self.stop()
                break

    def console_popup(self):
        from pyqtgraph.console import ConsoleWidget
        import pyqtgraph as pg
        app = pg.mkQApp()
        
        console = ConsoleWidget(namespace=dict(self=self))
        console.show()

        # self.console.eval_in_thread()

        app.exec()



if __name__ == '__main__':
    app = SnapshotApp()
