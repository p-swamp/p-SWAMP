from pswamp.utils.pmu_time_window import PMUTimeWindowOffline
from synchrophasor.timeSeriesPlayback import PMUTimeSeriesPublisher
import numpy as np
from queue import Queue


class CSVToPMUData(PMUTimeSeriesPublisher):
    def __init__(self, time, phasors, station_names, channel_names, freq_data=None, dfreq_data=None):
        self.freq_data = np.array(
            freq_data).T if freq_data is not None else None
        self.dfreq_data = np.array(
            dfreq_data).T if dfreq_data is not None else None
        super().__init__('', 0, time=time, phasors=phasors, station_names=station_names, channel_names=channel_names)
        self.pmu.client_buffers = [Queue()]

    def generate_pmu_data_frames(self):
        self.k_sim = 0
        self.time_stamp = self.time[0]
        n_samples = len(self.time)
        self.pmu_data_frames = []
        for self.k_sim in range(n_samples):
            print(f'Generating frame {self.k_sim} of {n_samples}.')

            # self.time_stamp = self.time[self.self.k_sim]
            self.time_stamp = self.time[self.k_sim]
            pmu_data = []
            for phasors in self.phasors:
                phasors_complex = phasors[self.k_sim, :]
                # pmu_data.append([(abs(ph), np.angle(ph)) for ph in phasors_complex])
                pmu_data.append([(abs(ph), np.nan_to_num(np.angle(ph))) for ph in phasors_complex])

            if len(self.phasors) == 1:
                pmu_data = pmu_data[0]

            publish_this = [self.time_stamp, pmu_data]
            if self.freq_data is not None:
                publish_this.append(list(self.freq_data[self.k_sim, :]))
            if self.dfreq_data is not None:
                publish_this.append(list(self.dfreq_data[self.k_sim, :]))

            self.publish(*publish_this)
            data_frame = self.pmu.client_buffers[0].get()
            self.pmu_data_frames.append(data_frame)

        return self.pmu_data_frames
    
    def make_time_window(self, n_samples=None, window_length=None, t_start=0, phasor_selection=None, time_window_type=PMUTimeWindowOffline):
        start_idx = np.argmax(t_start <= self.time)

        if n_samples is None and window_length is None:
            n_samples = len(self.time)

        pmu_tw = time_window_type(n_samples=n_samples, window_length=window_length, phasor_selection=phasor_selection)
        pmu_tw.initialize_from_config_frame(self.pmu_data_frames[0].cfg)

        for sample_idx in range(start_idx + pmu_tw.n_samples):
            pmu_tw.update_window(self.pmu_data_frames[sample_idx])
        return pmu_tw