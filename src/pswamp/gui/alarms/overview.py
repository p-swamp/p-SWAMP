from PySide6 import QtWidgets, QtCore, QtGui
from pswamp.utils.load_config import load_config
from pswamp.coordination.alarm_handling import AlarmSender, AlarmMonitor
from pswamp.gui.alarms.handling import AlarmHandlingDialogue



class AlarmOverview(QtWidgets.QWidget):
    """Widget for showing overview of alarms
    
    Args:
        config (dict): pswamp Configuration file.
        alarm_keeper (AlarmMonitor): Object which stores alarm data.
        measurement_data_available (bool): Determines if alarm views are shown.
        alarm_details_dock (QDockWidget): Dock where to show alarm details.
        grid_view (GridViewContainer): Allow content to be shown on the SLD.
    """
    def __init__(
        self,
        config,
        alarm_keeper,
        measurement_data_available=True,
        alarm_details_dock=None,
        grid_view=None,
    ):
        
        self.config = config
        self.io_kwargs = config["streaming"]
        self.kafka_topics = config['topics']
        self.alarm_topic = self.kafka_topics['alarms']
        self.alarm_keeper = alarm_keeper
        self.measurement_data_available = measurement_data_available
        self.alarm_details_dock = alarm_details_dock
        self.grid_view = grid_view

        super().__init__()

        self.setWindowTitle("Alarms")

        col_headers = ['Time', 'App', 'Alarm status']
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
        
        self.row_to_uuid = {}
        self.alarm_handling_dialogues = {}

        
        self.tableWidget.cellClicked.connect(self.cell_was_clicked)
        

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.start(1)

    def cell_was_clicked(self, row, column):
        """Show alarm details when cell is clicked.

        Use row and col to determine which alarm was clicked, and run an alarm
        handling dialogue targeting the selected alarm.

        Args:
            row (int): Row of the clicked cell.
            column (int): Column of the clicked cell.
        """
        alarm_uuid = self.row_to_uuid[row]
        # print("Row %d and Column %d was clicked, %s" % (row, column, alarm_uuid))
        
        print(alarm_uuid)
        alarm_handling_dialogue = AlarmHandlingDialogue(
            self.config,
            alarm_uuid,
            self.alarm_keeper.alarm_data[alarm_uuid],
            measurement_data_available=self.measurement_data_available,
            grid_view=self.grid_view
        )
        if self.alarm_details_dock is not None:
            self.alarm_details_dock.setWidget(alarm_handling_dialogue)
            self.alarm_details_dock.show()

            # This is to (try to) ensure that the alarm view widget is 
            # closed/stopped when the dock closes (alarm views are a bit
            # heavy to run).
            def visiblity_changed():
                if not self.alarm_details_dock.isVisible():
                    alarm_handling_dialogue.alarm_view.close_view()
                    self.alarm_details_dock.setWidget(None)
            self.alarm_details_dock.visibilityChanged.connect(visiblity_changed)

        alarm_handling_dialogue.show()
        self.alarm_handling_dialogues[alarm_uuid] = alarm_handling_dialogue

    def update_display(self):
        """Update the alarm overview table

        Update the table based on content stored in the AlarmMonitor
        (self.alarm_keeper). The color of alarms is determined by the status,
        e.g., unseen: red, acknowledged or not_critical: light red,
        silenced: gray.
        """
        alarm_data_dict = self.alarm_keeper.alarm_data  # .copy()
        n_alarms = len(alarm_data_dict.keys())
        self.tableWidget.setRowCount(n_alarms)
            
        for i_alarm, (alarm_uuid, alarm_data) in enumerate(alarm_data_dict.items()):
            row = n_alarms - i_alarm - 1
            
            self.row_to_uuid[row] = alarm_uuid
            for col, key in enumerate(['time_stamp', 'app_name', 'status']):
                item_text = str(alarm_data[key])
                newitem = QtWidgets.QTableWidgetItem(item_text)
                newitem.setFlags(QtCore.Qt.ItemIsEnabled)
                self.tableWidget.setItem(row, col, newitem)            
            
            if alarm_data['status'] == 'silenced':
                bg = [225, 225, 225]
            elif alarm_data['status'] == 'not_critical':
                bg = [255, 200, 200]
            elif alarm_data['status'] == 'acknowledged':
                bg = [255, 200, 200]
            else:
                bg = [250, 100, 100]
            
            for col in range(3):
                self.tableWidget.item(row, col).setBackground(QtGui.QColor(*bg))

        self.tableWidget.resizeRowsToContents()



def run_alarm_handling(config):

    alarm_sender = AlarmSender(
        io_kwargs=config["streaming"],
        input_topic=config['topics']['application.status'],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_sender.start()

    alarm_monitor = AlarmMonitor(
        io_kwargs=config["streaming"],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_monitor.start()

    if 'other_tso' in config.keys():
        alarm_monitors_other_tsos = []
        for config_ in config['other_tso']:
            alarm_monitor_other_tso = AlarmMonitor(
                io_kwargs=config_['kafka'],
                alarm_topic=config_['topics']['alarms'],
            )
            alarm_monitor_other_tso.start()
            alarm_monitors_other_tsos.append(alarm_monitor_other_tso)

    app = QtWidgets.QApplication()

    alarm_display = AlarmOverview(config, alarm_monitor)
    alarm_display.show()

    app.exec()


def run_alarm_monitor(config):

    alarm_monitor = AlarmMonitor(
        io_kwargs=config["streaming"],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_monitor.start()

    if 'other_tso' in config.keys():
        alarm_monitors_other_tsos = []
        for config_ in config['other_tso']:
            alarm_monitor_other_tso = AlarmMonitor(
                io_kwargs=config_['kafka'],
                alarm_topic=config_['topics']['alarms'],
            )
            alarm_monitor_other_tso.start()
            alarm_monitors_other_tsos.append(alarm_monitor_other_tso)

    app = QtWidgets.QApplication()

    alarm_display = AlarmOverview(config, alarm_monitor)
    alarm_display.show()

    app.exec()
    

if __name__ == '__main__':
    config = load_config()
    config["streaming"]['consumers_seek_to_beginning'] = True
    run_alarm_handling(config)