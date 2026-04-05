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
from PySide6 import QtWidgets, QtCore


'''
This widget was generated, in large, by ChatGPT
[https://openai.com/blog/chatgpt].
Some modifications were done by Hallvar Haugdal.
'''

class ChannelSelect(QtWidgets.QWidget):
    """Widget for selecting channels.

    The user can select channels in the list to the left, and move them to the
    right to include in selection.
    
    Args:
        channels (list): List of channels.
    """
    def __init__(self, channels):
        super().__init__()
        self.channel_to_idx = {key:i for i, key in enumerate(channels)}
        self.channels = sorted(channels)  # Sort the channels list
        self.selected_channels = []

        self.unselected_list = QtWidgets.QListWidget()
        self.unselected_list.setSortingEnabled(True)
        self.unselected_list.addItems(self.channels)
        self.unselected_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        self.selected_list = QtWidgets.QListWidget()
        self.selected_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        self.move_up_button = QtWidgets.QPushButton("Move Up")
        self.move_up_button.clicked.connect(self.move_up)
        self.move_down_button = QtWidgets.QPushButton("Move Down")
        self.move_down_button.clicked.connect(self.move_down)

        self.select_all_button = QtWidgets.QPushButton(">>")
        self.select_all_button.clicked.connect(self.select_all_channels)

        self.unselect_all_button = QtWidgets.QPushButton("<<")
        self.unselect_all_button.clicked.connect(self.unselect_all_channels)
        
        self.select_button = QtWidgets.QPushButton(">")
        self.select_button.clicked.connect(self.select_channels)
        self.unselect_button = QtWidgets.QPushButton("<")
        self.unselect_button.clicked.connect(self.unselect_channels)

        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter channels...")
        self.filter_edit.textChanged.connect(self.filter_channels)

        self.filter_selected_edit = QtWidgets.QLineEdit()
        self.filter_selected_edit.setPlaceholderText("Filter channels...")
        self.filter_selected_edit.textChanged.connect(self.filter_channels_selected)

        button_layout = QtWidgets.QVBoxLayout()
        button_layout.addWidget(self.select_all_button)
        button_layout.addWidget(self.unselect_all_button)
        
        button_layout.addWidget(self.select_button)
        button_layout.addWidget(self.unselect_button)

        button_layout.addWidget(self.move_up_button)
        button_layout.addWidget(self.move_down_button)
        
        unselected_layout = QtWidgets.QVBoxLayout()
        unselected_layout.addWidget(self.filter_edit)
        unselected_layout.addWidget(self.unselected_list)

        selected_layout = QtWidgets.QVBoxLayout()
        selected_layout.addWidget(self.filter_selected_edit)
        selected_layout.addWidget(self.selected_list)

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(unselected_layout)
        main_layout.addLayout(button_layout)
        main_layout.addLayout(selected_layout)
    

        self.setLayout(main_layout)

        self.item_was_selected = lambda item: None
        self.item_was_unselected = lambda item: None
    
    def select_channels(self):
        """Get channels from unselected list and transfer to selected list."""
        selected_items = self.unselected_list.selectedItems()
        for item in selected_items:
            self.selected_list.addItem(item.text())
            self.selected_channels.append(item.text())
        # for item in selected_items:
            self.unselected_list.takeItem(self.unselected_list.row(item))
        
        self.item_was_selected(selected_items)

    def select_all_channels(self):
        """Put all channels in selected list, remove from unselected."""
        items = []
        for index in range(self.unselected_list.count()):
            item = self.unselected_list.item(index)
            self.selected_list.addItem(item.text())
            self.selected_channels.append(item.text())
            items.append(item)
        self.item_was_selected(items)
        self.unselected_list.clear()

    def unselect_all_channels(self):
        """Put all channels in unselected list, remove from selected."""
        items = []
        for index in range(self.selected_list.count()):
            item = self.selected_list.item(index)
            self.unselected_list.addItem(item.text())
            items.append(item)
        self.item_was_unselected(items)
        self.selected_list.clear()
        self.selected_channels = []

    def unselect_channels(self):
        """Get channels from selected list and transfer to unselected list."""
        selected_items = self.selected_list.selectedItems()
        for item in selected_items:
            self.unselected_list.addItem(item.text())
            self.selected_channels.remove(item.text())
        for item in selected_items:
            self.selected_list.takeItem(self.selected_list.row(item))
        
        self.item_was_unselected(selected_items)

    def move_up(self):
        """Move channel up."""
        current_row = self.selected_list.currentRow()
        if current_row > 0:
            current_item = self.selected_list.takeItem(current_row)
            self.selected_list.insertItem(current_row - 1, current_item)
            self.selected_list.setCurrentItem(current_item)

    def move_down(self):
        """Move channel down."""
        current_row = self.selected_list.currentRow()
        if current_row < self.selected_list.count() - 1:
            current_item = self.selected_list.takeItem(current_row)
            self.selected_list.insertItem(current_row + 1, current_item)
            self.selected_list.setCurrentItem(current_item)

    def filter_channels(self):
        """Show unselected channels contaning text in filter_edit text box."""
        filter_text = self.filter_edit.text()
        if filter_text:
            for index in range(self.unselected_list.count()):
                item = self.unselected_list.item(index)
                if filter_text.lower() in item.text().lower():
                    item.setHidden(False)
                else:
                    item.setHidden(True)
        else:
            for index in range(self.unselected_list.count()):
                item = self.unselected_list.item(index)
                item.setHidden(False)

    def filter_channels_selected(self):
        """Show selected channels contaning text in filter_edit text box."""
        filter_text = self.filter_selected_edit.text()
        if filter_text:
            for index in range(self.selected_list.count()):
                item = self.selected_list.item(index)
                if filter_text.lower() in item.text().lower():
                    item.setHidden(False)
                else:
                    item.setHidden(True)
        else:
            for index in range(self.selected_list.count()):
                item = self.selected_list.item(index)
                item.setHidden(False)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    channels = ["Channel 1.1", "Channel 1.2", "Channel 1.3", "Channel 2.1", "Channel 2.2"]
    selector = ChannelSelect(channels)
    selector.show()

    sys.exit(app.exec())

