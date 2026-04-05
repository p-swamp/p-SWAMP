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

from pswamp.utils.time_window_labeled import TimeWindowLabeled
from pswamp.utils.time_window_labeled import GrowingTimeWindowLabeled
from pswamp.app_templates.snapshot_app import SnapshotApp


class TimeWindowApp(SnapshotApp):
    """General time window application template.

    New applications could be defined by inheriting from this template, and
    defining the "run_analysis" method. Similar to SnapshotApp, but has an
    internal time window storage. The length of the time window is determined by
    either of the arguments n_samples or window_length. If neither are
    specified, the size of the time window will grow indefinitely.

    
    TODO: Remove channel_selection and channel_selection_idx from arguments.

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
        channel_selection: Argument for specifying channel subset.
        channel_selection_idx: Argument for specifying channel subset.
        n_samples: Determines the window length in samples.
        window_length: Determines the window length in seconds.
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
            channel_selection=None,
            channel_selection_idx=None,
            n_samples=None,
            window_length=None,
            report_status=False,
            auto_adjust_offset=None,
            **kwargs):
        
        decoder_extra_kwargs = {
            'channel_selection': channel_selection,
            'channel_selection_idx': channel_selection_idx}
                
        SnapshotApp.__init__(
            self, io, eval_freq, t_end, t_start, app_name, input_decoder,
            decoder_kwargs={**decoder_extra_kwargs, **decoder_kwargs},
            report_status=report_status, **kwargs)
        
        header = self.decoder.generate_header(sample_data_frame=self.get_sample_data_frame())

        if n_samples is None and window_length is None:
            window_length = None
            self.time_window_type = GrowingTimeWindowLabeled
        else:
            self.time_window_type = TimeWindowLabeled

        # Determine number of samples in TimeWindow (if not specified)
        # based on sampling and window length
        self.sampling_frequency = self.decoder.get_data_rate(self.get_sample_data_frame())
        self.sampling_time = 1 / self.sampling_frequency

        if n_samples is not None:
            window_length = n_samples * self.sampling_time
        elif window_length is not None:
            n_samples = int(round(window_length / self.sampling_time))
        
        self.tw = self.time_window_type(
            header=header,
            n_samples=n_samples,
            dtype=self.decoder.data_dtype)
        
        # self.tw.initialize_from_config_frame(self.get_config_frame())
        if t_start is None and (
            auto_adjust_offset or (auto_adjust_offset is None and
                self.time_window_type == TimeWindowLabeled)):
            self.io.seek_relative_input_offset(-self.tw.n_samples)
    
    def update_storage(self, next_data_frame):
        """Adds the data frame to the time window storage"""
        t, data = self.decoder.data_frame_to_row(next_data_frame)
        self.tw.append(t, data)

    def get_result(self, next_data_frame):
        """Perform assessment on the currently stored data and return result"""
        # Get data from time window
        time_stamp, measurements = self.tw.get()
        return self.run_analysis(time_stamp, measurements)
