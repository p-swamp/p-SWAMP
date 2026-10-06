# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from queue import Queue
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUPublisher


from pswamp.test_utils.csv_playback.offline_testing_adapter import\
    OfflineTestingAdapter



class PMUPublisherMod(PMUPublisher, OfflineTestingAdapter):
    def __init__(self, sim=None, *args, **kwargs):
        PMUPublisher.__init__(self, sim, *args, ip='', port=0, **kwargs)
        self.sim = sim
        self.new_frame_already_obtained = False
        self.latest_frame = None
        self.results = []
        self.statuses = []
    
    def initialize(self, *args, **kwargs):
        super().initialize(*args, **kwargs)
        self.pmu.pmu.client_buffers = [Queue()]
        self.pmu.pmu.clients = [None]
    
    def update(self, *args, **kwargs):
        return PMUPublisher.update(self, *args, **kwargs)
    
    def get_data_frame(self, sim):
        self.update(self.read_input_signal(sim))
        return self.pmu.pmu.client_buffers[0].get()

    def get_next_data_frame(self):
        if self.new_frame_already_obtained:
            self.new_frame_already_obtained = False
            return self.latest_frame
        
        self.sim.make_simulation_step()
        self.latest_frame = self.get_data_frame(self.sim)
        return self.latest_frame
        
    def seek_relative_input_offset(self):
        pass
