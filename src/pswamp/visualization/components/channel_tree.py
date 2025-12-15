from PySide6.QtCore import *
from PySide6.QtGui import *
import sys

from PySide6.QtWidgets import *


class ChannelTree(QTreeWidget):
    """For showing a tree representing Stations and PMUs"""
    def __init__(self, station_names, channel_names, *args):
        """
        Constructor. Channel names is specified as list of list of channel names, where each sublist corresponds to a
        station.
        Args:
            station_names: List of Station names
            channel_names: List of list of channel names
            *args:
        """
        super().__init__()
        # app = QApplication(sys.argv)
        self.station_names = station_names
        self.channel_names = channel_names

        self.setHeaderLabel('')
        headerItem = QTreeWidgetItem()
        headerItem.setText(0, '')
        item = QTreeWidgetItem()

        self.itemClicked.connect(self.onItemClicked)
        
        self.station_idx = dict()
        k_station = 0
        for station_name, channel_names_ in zip(station_names, channel_names):
            self.station_idx[station_name] = k_station
            parent = QTreeWidgetItem(self)
            parent.setText(0, station_name)
            # parent.setFlags(parent.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
            for channel_name in channel_names_:
                child = QTreeWidgetItem(parent)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setText(0, channel_name)
                child.setCheckState(0, Qt.Unchecked)

            k_station += 1
        self.show()

    @Slot(QTreeWidgetItem, int)
    def onItemClicked(self, it, col):
        # print(it, col, it.text(col))
        parent = it.parent()
        if parent is not None:
            channel = it.text(col)
            station = parent.text(col)
        else:
            station = it.text(col)
            channel = None
        print(self.station_idx[station], station, channel)


def main():

    station_names = ['PMU 0           ', 'PMU 1           ']

    channel_names = [
        ['Ph0             ', 'Ph1             ', 'Ph2             ', 'Ph3             '],
        ['Ph0             ', 'Ph1             ', 'Ph2             ', ]
    ]

    app = QApplication(sys.argv)
    tree = ChannelTree(station_names, channel_names)
    app.exec()



if __name__ == '__main__':
    main()