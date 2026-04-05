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

import time
from synchrophasor.timeSeriesPlayback import PMUTimeSeriesPublisher
from pswamp.streaming import Producer
import numpy as np
from pswamp.streaming.utils import encoder
from queue import Queue


class CSVtoKafka(PMUTimeSeriesPublisher):
    def __init__(
            self,
            io_kwargs,
            *args,
            topic='pmudata',
            freq_data=None,
            dfreq_data=None,
            speed=1,
            t_end=None,
            **kwargs,
    ):
        super().__init__(ip='', port=0, *args, **kwargs)
        self.t_end = t_end if t_end is not None else np.inf
        self.speed = speed
        self.pmu.client_buffers = [Queue()]

        self.topic = topic
        self.kafka_producer = Producer(**io_kwargs, value_serializer=encoder)
        self.freq_data = np.nan_to_num(np.array(freq_data).T) if freq_data is not None else None
        self.dfreq_data = np.nan_to_num(np.array(dfreq_data).T) if dfreq_data is not None else None

    def initialize(self):
        self.config = self.pmu.cfg2
        self.header = self.pmu.header


    def main_loop(self):
        self.k_sim = 0
        # t_world = 0
        t_world = self.time[0]
        t_prev = time.time()
        self.time_stamp = self.time[0]

        while not self._stopped and self.t_end >= t_world - self.time[0]:

            with self.pause_cv:
                while self.paused:
                    self.pause_cv.wait()
                    t_prev = time.time()

            # self.time_stamp = self.time[self.k_sim]
            pmu_data = []
            for phasors in self.phasors:
                phasors_complex = phasors[self.k_sim, :]
                pmu_data.append([(abs(ph), np.nan_to_num(np.angle(ph))) for ph in phasors_complex])

            if len(self.phasors) == 1:
                pmu_data = pmu_data[0]

            # if self.pmu.clients:  # Check if there is any connected PDCs
                # print('Main loop running')
            publish_this = [self.time_stamp, pmu_data]
            if self.freq_data is not None:
                publish_this.append(list(self.freq_data[self.k_sim, :]))
            if self.dfreq_data is not None:
                publish_this.append(list(self.dfreq_data[self.k_sim, :]))
                
            self.publish(*publish_this)
            data_frame = self.pmu.client_buffers[0].get()

            self.kafka_producer.send(self.topic, data_frame)
            self.kafka_producer.flush()
                # self.publish()

            self.k_sim += 1
            if self.k_sim >= len(self.time):
                self.k_sim -= len(self.time)
            
            self.time_stamp += self.dt  # self.time[self.k_sim]

            # Code for synchronizing with wall clock time
            dt_loop = time.time() - t_prev  # Actual time spent on current loop
            t_prev = time.time()

            t_world += dt_loop * self.speed
            dt_err = self.time_stamp - t_world
            if dt_err > 0:
                # print(t_world, self.time_stamp)
                time.sleep(dt_err / self.speed)
            elif dt_err <= 0:
                pass

            dt_ideal = self.dt / self.speed

        print('PMU publisher loop finished.')
        # self.cleanup()
