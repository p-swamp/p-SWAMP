from PySide6 import QtWidgets
from pswamp.gui.components.channel_select import ChannelSelect
import multiprocessing as mp
from pswamp.streaming import get_last_message_from_topic
from pswamp.utils.pmu_time_window import PMUTimeWindow
import time


class RunApp(QtWidgets.QWidget):
    """Dialogue for running application.

    Args:
        config (dict): pswamp configuration.
        run_app_func (function): Function to run.
        params (dict): Parameters which will be arguments to the function to run.
    """
    def __init__(self, config, run_app_func, params={}):
        QtWidgets.QWidget.__init__(self)
        self.layout = QtWidgets.QGridLayout()
        self.setLayout(self.layout)

        self.config = config
        self.run_app_func = run_app_func

        while True:
            pmu_data_frame = get_last_message_from_topic(
                topic=config["topics"]["pmudata"],
                **config["streaming"],
            )
            if pmu_data_frame is not None:
                break
            else:
                time.sleep(1)

        pmu_tw = PMUTimeWindow(n_samples=1)
        pmu_tw.initialize_from_config_frame(pmu_data_frame.cfg)
        channel_names = []
        for i, row in enumerate(pmu_tw.tw.header):
            channel_names.append(':'.join([''.join(r) for r in row]))

        self.selector = ChannelSelect(channel_names)

        launch_button = QtWidgets.QPushButton('Run')

        launch_button.clicked.connect(self.launch_app)

        self.layout.addWidget(self.selector)

        
        self.inputs = {}
        params_widget = QtWidgets.QWidget()
        params_layout = QtWidgets.QGridLayout()
        for param_text, (param_name, param_default) in params.items():
            new_label = QtWidgets.QLabel(params_widget)
            new_label.setText(param_text)
            new_input_box = QtWidgets.QLineEdit(params_widget)
            new_input_box.setText(str(param_default))
            params_layout.addWidget(new_label, 0, 0, 1, 1)
            params_layout.addWidget(new_input_box, 0, 1, 1, 1)

            self.inputs[param_name] = new_input_box
        params_widget.setLayout(params_layout)
        self.layout.addWidget(params_widget)
        

        self.layout.addWidget(launch_button)
        self.selector.show()

    def launch_app(self):
        """Run the application with channel selection indices and parameters."""

        params = {}
        for param_name, input_box in self.inputs.items():
            try:
                value = float(input_box.text())
            except ValueError:
                value = input_box.text()
            params[param_name] = value
        
        # print('Running app')
        # print(selector.selected_channels)
        channel_selection_idx = [self.selector.channel_to_idx[ch]
                                 for ch in self.selector.selected_channels]
        if len(self.selector.selected_channels) == 0:
            print('No channels selected!')
        else:
            self.p = mp.Process(target=self.run_app_func, args=(self.config,), kwargs={
                                'channel_selection_idx': channel_selection_idx, **params})
            self.p.start()


if __name__ == '__main__':
    from pswamp import load_config
    config = load_config()
    app = QtWidgets.QApplication()

    launcher = RunApp(config, lambda: print('Heo'), params={'Parameter 1': 10})
    launcher.show()

    app.exec()