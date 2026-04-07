# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np
from scipy.fft import fft, fftfreq
from pswamp.utils.time_window import TimeWindow
from pswamp.app_templates.time_window_app import TimeWindowApp
from scipy.signal import detrend

from pswamp.streaming import get_last_message_from_topic, consumer_seek_relative_offset


def calculate_fft_spectrum(y):
    """Calculates the frequency spectrum of the signal.

    Args:
        y: Signal to be analyzed.

    Returns:
        The frequency spectrum.

    """
    y = detrend(y)
    y -= np.mean(y)
    sp = fft(y) * 2 / len(y)
    return np.abs(sp)


class FFTOnline(TimeWindowApp):
    def __init__(
        self,
        io_kwargs,
        fft_window=5,
        time_window_store=10,
        kafka_topic='pmudata',
        status_topic='application.status',
        channel_selection={'measurement': 'f'},
        *args,
        **kwargs
    ):
        sample_msg = get_last_message_from_topic(kafka_topic, **io_kwargs)
        dt = 1 / sample_msg.cfg.get_data_rate()
        n_samples_fft = 2 ** int(np.ceil(np.log(fft_window / dt) / np.log(2)))
        self.n_samples_store = int(round(time_window_store/dt))

        TimeWindowApp.__init__(
            self,
            n_samples=n_samples_fft,
            input_topic=kafka_topic,
            io_kwargs=io_kwargs,
            auto_adjust_offset=False,
            channel_selection=channel_selection,
            report_status=True,
            *args,
            **kwargs
        )
        consumer_seek_relative_offset(self.io.input_stream, -n_samples_fft - self.n_samples_store)

        self.freq_range = fftfreq(n_samples_fft, dt)
        self.em_freq_idx = (self.freq_range >= 0) & (self.freq_range <= 2)
        self.fft_tw = []

        for i in range(self.tw.n_channels):
            new_time_window = TimeWindow(n_samples=self.n_samples_store, n_cols=n_samples_fft, dtype=complex)
            new_time_window._data [:] = 0  # Better to initialize with zeros than nan, since this allows the plot to show at once.
            self.fft_tw.append(new_time_window)

        # Values need to be adjusted
        self.threshold_emergency = 10
        self.threshold_alert = 1
        self.max_amplitude = 0

        self.run_fft = calculate_fft_spectrum



    def run_analysis(self, t, measurements):
        # This is a quick-fix. Would be better to run the FFT analysis at a fixed rate.
        # time.sleep(0.01)

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
            for fft_tw_, angle in zip(self.fft_tw, measurements.T):
                spectrum = self.run_fft(angle)
                fft_tw_.append(time_stamp_fft, spectrum)
                
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
