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

from PySide6 import QtWidgets, QtCore, QtGui
import threading
from pswamp.streaming import Consumer, Producer
from pswamp.utils.load_config import load_config
import time
import datetime


class AppStatusMonitoring:
    def __init__(
        self,
        io_kwargs,
        input_topic='application.status',
    ):

        self.input_topic = input_topic
        self.io_kwargs = io_kwargs

        self.input_stream = Consumer(
            input_topic, **io_kwargs
        )

        self.app_status = dict()

    def run(self):

        for kafka_message in self.input_stream:
            # app_uuid, app_name, status_message = kafka_message.value
            msg = kafka_message.value
            app_uuid = msg['uuid']
            app_name = msg['app_name']
            status_message = msg['status']
            time_stamp = msg['time_stamp']
            time_stamp_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            self.app_status[app_uuid] = {'name': app_name, 'status': status_message, 'time_stamp': time_stamp_str}
            # print(self.app_status)


class AppStatusMonitoringWidget(QtWidgets.QWidget):
    def __init__(self, config):

        self.config = config

        self.status_mon = AppStatusMonitoring(
            input_topic=config['topics']['application.status'],
            io_kwargs=config["streaming"],
        )

        super().__init__()

        self.t_1 = threading.Thread(target=self.status_mon.run, daemon=True)

        self.setWindowTitle("Application Status")

        # col_headers = ['UUID', 'Name', 'Status', 'Time stamp']
        col_headers = ['Name', 'Status', 'Time stamp']
        self.tableWidget = QtWidgets.QTableWidget()
        # self.tableWidget.resizeColumnsToContents()
        self.tableWidget.setColumnCount(len(col_headers))
        self.tableWidget.resizeRowsToContents()
        # self.tableWidget.horizontalHeader(['UUID', 'Status'])
        self.tableWidget.setHorizontalHeaderLabels(col_headers)
        self.tableWidget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout = QtWidgets.QVBoxLayout()
        # layout.addWidget(self.textEdit)
        layout.addWidget(self.tableWidget)
        self.setLayout(layout)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(1)

        self.tableWidget.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.tableWidget.itemSelectionChanged.connect(self.disable_buttons)
        
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.setToolTip(
            '''Stops the application selected above.''')
        self.stop_button.clicked.connect(lambda: self.send_command('stop'))
        
        self.console_button = QtWidgets.QPushButton('Open console')
        self.console_button.setToolTip(
            '''Opens a console window to interact with the application selected above.''')
        self.console_button.clicked.connect(lambda: self.send_command('open_console'))
        self.disable_buttons()

        btn_layout = QtWidgets.QHBoxLayout()
        [btn_layout.addWidget(w) for w in [self.stop_button, self.console_button]]
        layout.addLayout(btn_layout)
         

    def disable_buttons(self):
        test = not len(self.tableWidget.selectedItems()) == 0

        self.stop_button.setEnabled(test)
        self.console_button.setEnabled(test)
    
    def send_command(self, command):
        row_idx = self.tableWidget.selectedItems()[0].row()
        uuid, app_data = list(self.status_mon.app_status.items())[row_idx]
        
        producer = Producer(**self.config["streaming"])
        producer.send(
            self.config['topics']['application.commands'],
            {'target_uuid': uuid, 'command': command})

    def update(self):
        app_data_dict = self.status_mon.app_status.copy()
        self.tableWidget.setRowCount(len(app_data_dict.keys()))
        for row, (app_uuid, app_data) in enumerate(app_data_dict.items()):
            # newitem = QtWidgets.QTableWidgetItem(str(app_uuid))
            # self.tableWidget.setItem(row, 0, newitem)
            for col, item in enumerate(app_data.values()):
                newitem = QtWidgets.QTableWidgetItem(item)
                
                # self.tableWidget.setItem(row, col + 1, newitem)
                self.tableWidget.setItem(row, col, newitem)

            time_stamp_sec = datetime.datetime.strptime(app_data['time_stamp'], '%Y-%m-%d %H:%M:%S.%f').timestamp()
            dt = time.time() - time_stamp_sec
            
            # for col in range(4):
            for col in range(3):
                if dt < 3:
                    fg = [0, 0, 0]
                    if app_data['status'] == 'OK':
                        bg = [220, 250, 230]
                    elif app_data['status'] == 'Alert':
                        bg = [250, 250, 200]
                    elif app_data['status'] == 'Emergency':
                        bg = [250, 200, 200]
                    elif app_data['status'] == 'Initializing...':
                        bg = [200, 230, 255]
                    else:
                        bg = [220, 240, 255]
                if dt >= 3:                   
                    fg = [150, 150, 150]
                    bg = [240, 240, 240]
                # if dt >= 5:
                    # color = [255, 190, 190]
                self.tableWidget.item(row, col).setBackground(QtGui.QColor(*bg))
                self.tableWidget.item(row, col).setForeground(QtGui.QBrush(QtGui.QColor(*fg)))
            #     self.tableWidget.item(row, col).setBackground(QtGui.QColor(color))

            
            # for col in range(4):
                # color = [0, 255, 0]
                # self.tableWidget.item(row, col).setBackground(QtGui.QColor(color))
        self.tableWidget.resizeRowsToContents()


        # self.tableWidget.setModel(self.model)

    def start(self):
        self.t_1.start()


def run_app_monitoring(*config_args):
    config = load_config(*config_args)
    app = QtWidgets.QApplication()

    status_mon = AppStatusMonitoringWidget(config)
    status_mon.start()
    status_mon.show()
    app.exec()


if __name__ == '__main__':
    from pswamp import load_config
    config = load_config()
    config["streaming"]['consumers_seek_to_beginning'] = True

    run_online = True
    if not run_online:

        from pswamp.test_utils.runners import run_nqkafka_server, create_topics
        run_nqkafka_server(config)
        create_topics(config)

        msgs =[ {
            'uuid': k,
            'app_name': 'SomeApp',
            'status': 'OK',
            'time_stamp': 1,
        } for k in range(5)]
        
        from pswamp.streaming import Producer
        producer = Producer(**config["streaming"])
        [producer.send('application.status', msg) for msg in msgs]

        # consumer = KafkaConsumer(**config["streaming"], topic='application.status')
        # msg = next(iter(consumer))
        # print(msg)


    run_app_monitoring(config)
