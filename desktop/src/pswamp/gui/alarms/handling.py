# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6 import QtWidgets, QtCore, QtGui
from pswamp.streaming import Producer
from pswamp.utils.load_config import load_config
import time
import datetime
from pswamp.coordination.alarm_handling import AlarmMonitor
from pswamp.gui.alarms.views.default import DefaultAlarmView
from pswamp.gui.alarms.views.islanding import IslandingAlarmView
from pswamp.gui.alarms.views.voltage_stability import VoltageStabilityAlarmView
from pswamp.gui.alarms.views.oscillations import OscillationAlarmView


# Mapping of applications to alarm views (i.e., if an application of type
# IslandingApp causes an alarm, the IslandingAlarmView will be used to show
# details on the alarm.
alarm_views = {
    'IslandingApp': IslandingAlarmView,
    'N4SIDApp': OscillationAlarmView,
    'SSIApp': OscillationAlarmView,
    'PronyApp': OscillationAlarmView,
    'VoltageStabilityApp': VoltageStabilityAlarmView,
}


class AlarmHandlingDialogue(QtWidgets.QWidget):
    """Widget for alarm handling
    
    Shows details on an alarm, e.g., identifying application, time of being
    issued, acknowledged, silenced, etc. Also shows alarm views when possible.
    
    Args:
        config: pswamp config file.
        alarm_uuid (uuid.uuid): UUID of the alarm to be shown.
        alarm_data (dict): Data for the alarm to be shown.
        measurement_data_available (bool): If this is False, alarm views will not show.
        grid_view (GridViewContainer): Allow content to be shown on the SLD.
    """
    def __init__(self, config, alarm_uuid, alarm_data, measurement_data_available=True, grid_view=None):
        self.alarm_topic = config['topics']['alarms']
        self.config = config

        super().__init__()
        self.setWindowTitle('Alarm')
        self.alarm_uuid = alarm_uuid
        self.alarm_data = alarm_data

        layout_outer = QtWidgets.QHBoxLayout()
        layout = QtWidgets.QVBoxLayout()

        # layout_outer.setRowStretchFactor(0, 0)
        # layout_outer.setRowStretchFactor(1, 13)
        # layout_outer.setRowStretchFactor(2, 8)
        
        info_label = QtWidgets.QLabel(f"Detected by:\t{alarm_data['app_name']}\nTime stamp:\t{alarm_data['time_stamp']}")
        layout.addWidget(info_label)
        
        col_headers = ['Time', 'Type', 'Message']
        self.tableWidget = QtWidgets.QTableWidget()
        self.tableWidget.setColumnCount(len(col_headers))
        self.tableWidget.resizeRowsToContents()
        # self.tableWidget.horizontalHeader(['UUID', 'Status'])
        self.tableWidget.setHorizontalHeaderLabels(col_headers)
        self.tableWidget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout.addWidget(self.tableWidget)

        ack_button = QtWidgets.QPushButton('Acknowledge')
        ack_button.clicked.connect(self.acknowledge_alarm)
        layout.addWidget(ack_button)

        annotate_button = QtWidgets.QPushButton('Annotate')
        annotate_button.clicked.connect(self.annotate_alarm)
        layout.addWidget(annotate_button)
        
        silence_button = QtWidgets.QPushButton('Silence')
        silence_button.clicked.connect(self.silence_alarm)
        layout.addWidget(silence_button)

        # delete_button = QtWidgets.QPushButton('Delete')
        # delete_button.clicked.connect(self.delete_alarm)
        # layout.addWidget(delete_button)
        layout_outer.addLayout(layout)
        layout_outer.setStretchFactor(layout, 0)
        
        if measurement_data_available:
            app_name = self.alarm_data['app_name']
            alarm_view_class = alarm_views[app_name] if app_name in alarm_views else DefaultAlarmView
            self.alarm_view = alarm_view_class(self.config, alarm_uuid, alarm_data, grid_view=grid_view)
            layout_outer.addWidget(self.alarm_view)
            layout_outer.setStretchFactor(self.alarm_view, 10)

        self.setLayout(layout_outer)

        # self.update_message_display()

        self.output_stream = Producer(
            **config["streaming"]
        )

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_message_display)
        self.timer.start(1)

    def acknowledge_alarm(self):
        alarm_message = {
            'uuid': self.alarm_uuid,
            'time_stamp': datetime.datetime.now(),
            'app': None,
            'app_name': None,
            'type': 'acknowledge',
            'message': 'Alarm acknowledged',
            # 'location': ...
            # identifyers: {freq=0.5Hz} etc.
        }
        print('Alarm acknowledged')
        print(alarm_message)
                    
        # print(self.app_status[app_uuid].keys())
        self.output_stream.send(topic=self.alarm_topic, msg=alarm_message)
        self.output_stream.flush()

    def annotate_alarm(self):

        # user_text, ok = QtWidgets.QInputDialog.getText(self, 'input dialog', 'Enter user name')
        # if not ok:
        #     return
        
        message_text, ok = QtWidgets.QInputDialog.getText(self, 'input dialog', 'Enter message')
        if not ok:
            return
        
        alarm_message = {
            'uuid': self.alarm_uuid,
            'time_stamp': datetime.datetime.now(),
            'app': None,
            'app_name': None,
            'type': 'user_message',
            # 'user': user_text,
            'message': message_text,
            # 'location': ...
            # identifyers: {freq=0.5Hz} etc.
        }
                    
        # print(self.app_status[app_uuid].keys())
        self.output_stream.send(topic=self.alarm_topic, msg=alarm_message)
        self.output_stream.flush()
    
    def silence_alarm(self):
        alarm_message = {
            'uuid': self.alarm_uuid,
            'time_stamp': datetime.datetime.now(),
            'app': None,
            'app_name': None,
            'type': 'silence',
            'message': 'Alarm silenced',
            # 'location': ...
            # identifyers: {freq=0.5Hz} etc.
        }
        print('Alarm silenced')
        print(alarm_message)
                    
        # print(self.app_status[app_uuid].keys())
        self.output_stream.send(topic=self.alarm_topic, msg=alarm_message)
        self.output_stream.flush()

    # def delete_alarm(self):
    #     alarm_message = {
    #         'uuid': self.alarm_uuid,
    #         'time_stamp': datetime.datetime.now(),
    #         'app': None,
    #         'app_name': None,
    #         'type': 'delete',
    #         'message': 'Alarm deleted',
    #         # 'location': ...
    #         # identifyers: {freq=0.5Hz} etc.
    #     }
    #     print('Alarm deleted')
    #     print(alarm_message)
                    
    #     # print(self.app_status[app_uuid].keys())
    #     self.output_stream.send(topic=self.alarm_topic, msg=alarm_message)
    #     self.output_stream.flush()
    #     self.close()




    

    def update_message_display(self):
        self.alarm_data['events']
        self.tableWidget.setRowCount(len(self.alarm_data['events']))

        for row, event in enumerate(self.alarm_data['events']):

            for col, key in enumerate(['time_stamp', 'type', 'message']):
                item_text = str(event[key])
                newitem = QtWidgets.QTableWidgetItem(item_text)
                self.tableWidget.setItem(row, col, newitem)

            if event['type'] == 'init':
                bg = [255, 100, 100]
            elif event['type'] == 'acknowledge':
                bg = [255, 200, 200]
            elif event['type'] == 'not_critical':
                bg = [255, 200, 200]
            elif event['type'] == 'user_message':
                bg = [200, 200, 255]
            elif event['type'] == 'silence':
                bg = [225, 225, 225]

            for col in range(3):
                # if dt < 3:
                    # fg = [0, 0, 0]
                # if alarm_data['status'] == 'OK':
                        # bg = [220, 250, 230]
                # if alarm_data['status'] == 'unseen':
                    # bg = [230, 0, 0]
                # elif alarm_data['status'] == 'acknowledged':
                    # bg = [250, 100, 100]
                # else:
                    # bg = [220, 240, 255]
                # if dt >= 3:                   
                    # fg = [150, 150, 150]
                    # bg = [240, 240, 240]
                # if dt >= 5:
                    # color = [255, 190, 190]
                self.tableWidget.item(row, col).setBackground(QtGui.QColor(*bg))


if __name__ == '__main__':
    config = load_config()
    config["streaming"]['consumers_seek_to_beginning'] = True
    config["streaming"]['bootstrap_servers'] = 'localhost:40000'

    alarm_monitor = AlarmMonitor(
        io_kwargs=config["streaming"],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_monitor.start()
    import time
    while True:
        try:
            # time_stamps = [time_stamp for time_stamp in alarm_monitor.alarm_data['time_stamp']]
            alarm_uuid = list(alarm_monitor.alarm_data.keys())[0]
            alarm_data = list(alarm_monitor.alarm_data.values())[0]
            break
        except IndexError:
            time.sleep(1)
            pass

    config["streaming"]['consumers_seek_to_beginning'] = False
    app = QtWidgets.QApplication()

    alarm_view = AlarmHandlingDialogue(config["streaming"], config['topics'], alarm_uuid=alarm_uuid, alarm_data=alarm_data)
    alarm_view.show()
    app.exec()
