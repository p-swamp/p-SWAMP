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

import sys
from PySide6 import QtWidgets


class SingleChannelSelect(QtWidgets.QWidget):
    """Widget for selecting a single channel.
    
    (Currently used only in FFT viz)
    Args:
        channels (list): List of channels to select from.
    """
    def __init__(self, channels):
        super().__init__()
        self.channel_to_idx = {key: i for i, key in enumerate(channels)}
        self.channels = sorted(channels)  # Sort the channels list
        # self.selected_channels = []

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setSortingEnabled(True)
        self.channel_list.addItems(self.channels)
        self.channel_list.selectionChanged = self.on_select
        self.channel_list.setCurrentItem(self.channel_list.item(0))

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.addWidget(self.channel_list)
        self.setLayout(main_layout)

        self.item_was_selected = self.on_select
        
        self.last_selected = self.channel_list.item(0)

    def selected_channel(self):
        return self.last_selected.text()
        
    def selected_channel_idx(self):
        return self.channel_to_idx[self.selected_channel()]
    
    def on_select(self, item, item2):
        if len(self.channel_list.selectedItems()) == 0:
            self.channel_list.setCurrentItem(self.last_selected)
        else:
            self.last_selected = self.channel_list.selectedItems()[0]

        # print(item.data(), item2.data())

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    channels = ["Channel 1.1", "Channel 1.2", "Channel 1.3", "Channel 2.1", "Channel 2.2"]
    selector = SingleChannelSelect(channels)
    selector.show()

    # def myfun():
    #     selected_channels = []
    #     for i in range(selector.selected_list.count()):
    #         selected_channels.append(selector.channel_to_idx[selector.selected_list.item(i).data(0)])
    #     print(selected_channels)
    # selector.selected_list.model().rowsInserted.connect(myfun)
    # selector.selected_list.model().rowsRemoved.connect(myfun)
    def my_fun(item):
        print(item.data(0))
    selector.item_was_selected = my_fun
    selector.item_was_unselected = my_fun
    sys.exit(app.exec())

