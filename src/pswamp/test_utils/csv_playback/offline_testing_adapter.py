# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from pswamp.test_utils.csv_playback.data_frame_generator import\
    DataFrameGenerator


class OfflineTestingAdapter(DataFrameGenerator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_frame_already_obtained = False
        self.latest_frame = None
        self.results = []
        self.statuses = []

        
    def get_next_data_frame(self):
        if self.new_frame_already_obtained:
            self.new_frame_already_obtained = False
            return self.latest_frame
        
        self.latest_frame = super().get_next_data_frame()
        return self.latest_frame
    
    def get_sample_data_frame(self):
        if self.latest_frame is None:
            self.latest_frame = self.get_next_data_frame()
        self.new_frame_already_obtained = True
        return self.latest_frame
    
    def handle_result(self, result):
        self.results.append(result)

    def handle_status(self, status):
        self.statuses.append(status)

    def seek_relative_input_offset(self):
        pass
