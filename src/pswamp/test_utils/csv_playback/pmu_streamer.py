from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator

import numpy as np
from synchrophasor.pmu_mod import PmuMod
import threading
import time
from pathlib import Path

"""
tinyPMU will listen on ip:port for incoming connections.
When tinyPMU receives command to start sending
measurements - fixed (sample) measurement will
be sent.
"""


class PMUDataStreamer(DataFrameGenerator):
    def __init__(self, pmu_data_folder, publisher_kwargs, case_name_hint='', pdc_id=1, publish_frequency=50, speed=1, n_samples=None, t_end=None, skip_seconds_in_beginning=0, *args, **kwargs) -> None:
        super().__init__(pmu_data_folder, case_name_hint,
                         pdc_id, publish_frequency=publish_frequency, *args, **kwargs)
        self.skip_seconds_in_beginning = skip_seconds_in_beginning

        self.speed = speed
        self.publish_frequency = publish_frequency
        self.n_samples = n_samples if n_samples is not None else np.inf
        self.t_end = t_end if t_end is not None else np.inf

        self._stopped = False
        # pmu.run()
        self.dt = round(1/publish_frequency, 2)

        self.init_publisher(**publisher_kwargs)

        self.pause_cv = threading.Condition()
        self.paused = False

    def init_publisher(self, ip, port):
        self.pmu = PmuMod(ip=ip, port=port, set_timestamp=False,
                          data_rate=self.publish_frequency)
        self.pmu.set_configuration(self.cfg2)

    def toggle_pause(self):
        self.paused = not self.paused
        with self.pause_cv:
            self.pause_cv.notify()

    def stop(self):
        self._stopped = True

    def publish(self, data_frame):
        if self.pmu.clients:  # Check if there is any connected PDCs
            # print('Main loop running')
            self.pmu.send(data_frame)
            # self.publish()

    def main_loop(self):

        k = 0
        t_world = 0  # self.time[0]
        t_prev = time.time()
        t_simulation = 0  # self.time[0]

        # Fastforward if skip seconds > 0
        for _ in range(round(self.skip_seconds_in_beginning/self.dt)):
            t_simulation += self.dt  # self.time[self.k_sim]
            data_frame = self.get_next_data_frame()

        while not self._stopped and k < self.n_samples and t_simulation < self.t_end:

            with self.pause_cv:
                while self.paused:
                    self.pause_cv.wait()
                    t_prev = time.time()

            t_simulation += self.dt  # self.time[self.k_sim]

            data_frame = self.get_next_data_frame()
            if data_frame is None:
                print('Reached end of data.')
                break
            self.publish(data_frame)

            # Code for synchronizing with wall clock time
            dt_loop = time.time() - t_prev  # Actual time spent on current loop
            t_prev = time.time()

            t_world += dt_loop * self.speed
            dt_err = t_simulation - t_world
            if dt_err > 0:
                # print(t_world, self.time_stamp)
                time.sleep(dt_err / self.speed)
            elif dt_err <= 0:
                pass

            dt_ideal = self.dt / self.speed

            k += 1

        print('PMU publisher loop finished.')