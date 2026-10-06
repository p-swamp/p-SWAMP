# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6.QtWidgets import QComboBox, QMainWindow, QApplication, QWidget, QVBoxLayout
from PySide6 import QtCore
from PySide6.QtGui import QIcon
import sys
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np


class ChannelSelect(QWidget):
    """
    For selecting a single channel.
    """

    def __init__(self, station_names, channel_names):
        super().__init__()

        self.channel_names = channel_names
        self.station_names = station_names

        self.station_select = QComboBox()
        self.station_select.addItems(self.station_names)
        self.station_select.highlighted.connect(self.station_selected)

        self.channel_select = QComboBox()
        self.channel_select.addItems(self.channel_names[0])
        self.channel_select.highlighted.connect(self.channel_selected)

        layout = QVBoxLayout()
        layout.addWidget(self.station_select)
        layout.addWidget(self.channel_select)

        # self.z_scale = 150
        # depthSpin = pg.SpinBox(
        #     value=self.z_scale, step=1, bounds=[0, 1000], delay=0, int=False
        # )
        # depthSpin.valueChanged.connect(self.scale_change)
        # layout.addWidget(depthSpin)

        # container = QWidget()
        self.setLayout(layout)

        self.station_idx = 0
        self.channel_idx = 0
        self.station_channel_idx = np.insert(
            np.cumsum([len(ch_nam) for ch_nam in self.channel_names]), 0, 0
        )
        self.col_idx = 0

        # self.setCentralWidget(container)
        self.show()

    # def scale_change(self, val):
    #     self.z_scale = val

    def station_selected(self, station_idx):
        self.channel_idx = 0
        self.station_idx = station_idx
        self.channel_select.clear()
        self.channel_select.addItems(self.channel_names[station_idx])

        self.current_station = self.station_names[self.station_idx]
        self.current_channel = self.channel_names[self.station_idx][self.channel_idx]

        self.col_idx = self.station_channel_idx[self.station_idx] + self.channel_idx
        print(self.current_station, self.current_channel, self.col_idx)

    def channel_selected(self, channel_idx):
        self.channel_idx = channel_idx

        self.current_station = self.station_names[self.station_idx]
        self.current_channel = self.channel_names[self.station_idx][self.channel_idx]

        self.col_idx = self.station_channel_idx[self.station_idx] + self.channel_idx

        print(self.current_station, self.current_channel, self.col_idx)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    station_names = ["PMU 0           ", "PMU 1           "]

    channel_names = [
        [
            "Ph0             ",
            "Ph1             ",
            "Ph2             ",
            "Ph3             ",
        ],
        [
            "Ph0             ",
            "Ph1             ",
            "Ph2             ",
        ],
    ]

    w = ChannelSelect(station_names, channel_names)
    w.show()
    app.exec()
