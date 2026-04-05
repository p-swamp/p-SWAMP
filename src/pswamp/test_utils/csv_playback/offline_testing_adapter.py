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
