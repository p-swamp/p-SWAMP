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

import numpy as np
from scipy.fft import fft, fftfreq
from .utils import TimeWindowRTApp, StatusCom
from pswamp.streaming import get_last_message_from_topic

class FFTOnline(TimeWindowRTApp, StatusCom):
    # TODO: Change TimeWindowRTApp with TimeWindowApp.
    def __init__(
        self,
        io_kwargs,
        fft_window=5,
        kafka_topic='pmudata',
        status_topic='application.status',
        *args,
        **kwargs
    ):
        sample_msg = get_last_message_from_topic(kafka_topic, **io_kwargs)
        dt = 1 / sample_msg.cfg.get_data_rate()
        n_samples_fft = 2 ** int(np.ceil(np.log(fft_window / dt) / np.log(2)))

        TimeWindowRTApp.__init__(self, n_samples_window=n_samples_fft, input_topic=kafka_topic, io_kwargs=io_kwargs, auto_adjust_offset=True, *args, **kwargs)
        StatusCom.__init__(self, io_kwargs=io_kwargs, status_topic=status_topic)

        self.n_samples_store = 500

        self.freq_range = fftfreq(n_samples_fft, dt)
        self.em_freq_idx = (self.freq_range >= 0) & (self.freq_range <= 2)
        
        # Values need to be adjusted
        self.threshold_emergency = 10
        self.threshold_alert = 1
        self.max_amplitude = 0


    def run_analysis(self, t, measurement):
        measurement = measurement.flatten()

        # Do not run FFT before the time window is filled up (the time window is initialized with np.nan).
        if not np.any(np.isnan(t)):

            # Get angles, and remove 2pi-steps
            # angles = np.angle(phasors)
            # angles = np.unwrap(angles, axis=1)
            # angles = np.unwrap(angles, axis=0)
            # angles -= np.mean(angles, axis=1)[:, None]
            # angles -= np.mean(angles, axis=0)[None, :]

            time_stamp_fft = np.mean(t)
            self.max_amplitude = 0
            # for fft_tw_, angle in zip(self.fft_tw, measurement.T):
            spectrum = self.run_fft(measurement)
            # self.fft_tw.append(time_stamp_fft, spectrum)
            self.max_amplitude = np.max([self.max_amplitude, np.max(abs(spectrum))])

            # print(max_amplitude)
            if self.max_amplitude > self.threshold_emergency:
                self.status = 'Emergency'
            elif self.max_amplitude > self.threshold_alert:
                self.status = 'Alert'
            else:
                self.status = 'OK'

            # print(self.max_amplitude, self.threshold_alert, self.threshold_emergency)

        else:
            self.status = 'Initializing...'
