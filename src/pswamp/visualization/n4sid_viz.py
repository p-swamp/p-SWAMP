# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np
import threading
import PySide6.QtCore as QtCore
import PySide6.QtWidgets as QtWidgets
import pyqtgraph as pg
import sys
from pswamp.visualization.eigenvalue_plot import EigenvaluePlot
from pswamp.visualization.components.phasor_plot import PhasorPlotFancy
from pswamp.streaming import Consumer
from pswamp.utils.load_config import load_config


# class PhasorPlotUI(QtWidgets.QWidget):
#     def __init__(self, n_phasors, n_modes):
#         super().__init__()
#
#         layout = QtWidgets.QVBoxLayout()
#
#         mode_select = QtWidgets.QComboBox()
#         mode_select.addItems(["Mode {}".format(i) for i in range(n_modes)])
#         mode_select.highlighted.connect(self.mode_selected)
#         layout.addWidget(mode_select)
#         self.mode_idx = 0
#
#         self.mode_text = pg.TextItem(
#             text="",
#             color=(200, 200, 200),
#             html=None,
#             anchor=(0, 0),
#             border=None,
#             fill=(0, 0, 0),
#             rotateAxis=None,
#         )
#         self.mode_text.setPos(0, -1.2)
#
#         self.phasor_plot = PhasorPlotFancy(n_phasors)
#         self.phasor_plot.plot_win_ph.addItem(self.mode_text)
#
#         layout.addWidget(self.phasor_plot.graphWidget)
#
#         self.setLayout(layout)
#         self.show()
#
#     def mode_selected(self, val):
#         self.mode_idx = val
#
#     def update(self, phasors):
#         mode_shape = sid.mode_shapes[:, self.mode_idx]
#
#         eig = sid.eigs[self.mode_idx]
#         if abs(eig) > 0:
#             freq = eig.imag / (2 * np.pi)
#             damping = -eig.real / abs(eig)
#             self.mode_text.setText(
#                 "Frequency: {:.2f} Hz\n Damping: {:.2f} %".format(freq, 100 * damping)
#             )
#
#         return mode_shape


class N4SIDViz(QtWidgets.QMainWindow):
    request_text_update = QtCore.Signal()
    def __init__(self, io_kwargs, kafka_topic, geo_plot_kwargs):
        super().__init__()
        self.mode_estimation_stream = Consumer(
            kafka_topic, **io_kwargs
        )
        self._stopped = False

        self.request_text_update.connect(self.update_mode_text)

        win = self

        d1 = QtWidgets.QDockWidget("Mode selection", win)
        d2 = QtWidgets.QDockWidget("Eigenvalues", win)
        d3 = QtWidgets.QDockWidget("Observability mode shape", win)
        # d4 = QtWidgets.QDockWidget("4", win)
        win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, d2)
        win.addDockWidget(QtCore.Qt.RightDockWidgetArea, d1)
        win.addDockWidget(QtCore.Qt.RightDockWidgetArea, d3)
        # win.addDockWidget(QtCore.Qt.RightDockWidgetArea, d4)
        # win.tabifyDockWidget(d3, d4)
        d3.raise_()

        layout = QtWidgets.QHBoxLayout()
        win.setLayout(layout)
        win.setWindowTitle("Mode Estimation Visualization")

        self.eigs_plot = EigenvaluePlot()
        d2.setWidget(self.eigs_plot.graphWidget)

        win.show()
        # self.win = win

    
        user_input_widget = QtWidgets.QWidget()
        user_input_layout = QtWidgets.QVBoxLayout()
        
        label = QtWidgets.QLabel('Mode estimator')
        user_input_layout.addWidget(label)
        self.monitoring_app_select = monitoring_app_select = QtWidgets.QComboBox()
        self.monitoring_apps = {}
        monitoring_app_select.highlighted.connect(self.monitoring_app_selected)
        user_input_layout.addWidget(monitoring_app_select)
        # self.monitoring_app_idx = None

        label = QtWidgets.QLabel('Mode')
        user_input_layout.addWidget(label)
        self.mode_select = mode_select = QtWidgets.QComboBox()
        # mode_select.addItems(["Mode {}".format(i) for i in range(sid_order)])
        mode_select.highlighted.connect(self.mode_selected)
        user_input_layout.addWidget(mode_select)
        
        user_input_widget.setLayout(user_input_layout)
        user_input_widget.setMaximumHeight(120)
        d1.setWidget(user_input_widget)
        # self.mode_idx = 0

        self.selected_app_uuid = None
        self.selected_mode_idx = None
        #
        self.mode_text = pg.TextItem(
            text="",
            color=(200, 200, 200),
            html=None,
            anchor=(0, 0),
            border=None,
            # fill=(0, 0, 0),
            rotateAxis=None,
        )
        self.mode_text.setPos(0, -1.2)
        
        #
        self.phasor_plot = PhasorPlotFancy(n_phasors=100, normalize_length=True, normalize_angle='max')
        # self.phasor_plot_widget = self.phasor_plot.graphWidget
        self.phasor_plot.plot_win_ph.addItem(self.mode_text)
        # self.phasor_plot_widget = pg.GraphicsLayoutWidget(show=True, title="Mode shapes")
        # plot_win = self.graphWidget.addPlot()
        # d3.setWidget(self.phasor_plot_widget)
        d3.setWidget(self.phasor_plot.graphWidget)


    def monitoring_app_selected(self, val):
        self.mode_select.clear()
        self.selected_app_uuid = self.monitoring_app_select.itemData(val)
        
        # self.monitoring_apps
        self.mode_select.addItems(["Mode {}".format(i + 1) for i in range(self.monitoring_apps[self.selected_app_uuid]['order'])])


    def set_mode_text(self, eig, cluster_id):
        freq = eig.imag / (2 * np.pi)
        damping = -eig.real / abs(eig)
        if cluster_id is None:
            self.mode_text_string = "Frequency: {:.2f} Hz\n Damping: {:.2f} %".format(freq, 100 * damping)
        else:
            self.mode_text_string = "Frequency: {:.2f} Hz\n Damping: {:.2f} %\n Cluster: {}".format(freq, 100 * damping, cluster_id)
        
        self.request_text_update.emit()

    def update_mode_text(self):
        self.mode_text.setText(self.mode_text_string)
    
    def mode_selected(self, val):
        self.selected_mode_idx = val
        last_result = self.monitoring_apps.get(self.selected_app_uuid, {}).get('last_result')

        if last_result is None or not isinstance(last_result, dict):
            self.set_mode_text(np.nan, np.nan)
            return

        eigenvalues = last_result.get('eigenvalues')
        cluster_id = last_result.get('cluster_id')

        if eigenvalues is None or cluster_id is None or self.selected_mode_idx >= len(eigenvalues) or self.selected_mode_idx >= len(cluster_id):
            self.set_mode_text(np.nan, np.nan)
            return

        self.set_mode_text(eigenvalues[self.selected_mode_idx], cluster_id[self.selected_mode_idx])
        self.phasor_plot.update(last_result['mode_shapes'][:, self.selected_mode_idx])
        self.eigs_plot.set_focus(self.selected_app_uuid, self.selected_mode_idx)



    def stop(self):
        self._stopped = True

    def update_plots(self, msg):
        if not msg['info']['uuid'] in self.monitoring_apps:
            self.monitoring_apps[msg['info']['uuid']] = {
                'name': msg['info']['app_name'],
                'order': msg['parameters']['order'],
                'n_measurements': msg['parameters']['n_measurements'],
                'last_result': msg['result'],
            }
            self.monitoring_app_select.addItem(
                msg['info']['app_name'], userData=msg['info']['uuid'])

        self.eigs_plot.update(
            msg['info']['uuid'], msg['info']['app_name'], msg['result']['eigenvalues'])
        if self.selected_app_uuid == msg['info']['uuid'] and self.selected_mode_idx is not None:
                # Check if 'cluster_id' exists in the result
                cluster_id = msg['result'].get('cluster_id', None)
                
                # Get the eigenvalue
                eigenvalue = msg['result']['eigenvalues'][self.selected_mode_idx]
                
                # If cluster_id does not exist, pass eigenvalue only
                if cluster_id is None:
                    self.set_mode_text(eigenvalue, None)  # Pass None if cluster_id is missing
                else:
                    self.set_mode_text(eigenvalue, cluster_id[self.selected_mode_idx])
        
                self.phasor_plot.update(
                    msg['result']['mode_shapes'][:, self.selected_mode_idx])
        # self.phasor_plot.update(self.mode_shapes[:, self.mode_idx])
        # self.grid_plot.phasor_plot.update(self.mode_shapes[:, self.mode_idx])
    
    def run(self):
        while True:
            for kafka_message in self.mode_estimation_stream:
                msg = kafka_message.value
                if msg is None:
                    self.stop()

                self.update_plots(msg)


def n4sid_viz(
    io_kwargs,
    kafka_topic="modeestimation",
    geo_plot_kwargs=None,
):

    app = QtWidgets.QApplication(sys.argv)
    viz = N4SIDViz(
        kafka_topic=kafka_topic,
        io_kwargs=io_kwargs,
        geo_plot_kwargs=geo_plot_kwargs,
    )
    viz_thread = threading.Thread(target=viz.run, daemon=True)
    viz_thread.start()

    app.exec()

    return app


def run_n4sid_viz(*config_args):
    config = load_config(*config_args)
    n4sid_viz(
        kafka_topic=config['topics']["modeestimation"],
        io_kwargs=config["streaming"],
    )


if __name__ == "__main__":
    from pswamp import load_config
    config = load_config()
    run_n4sid_viz(config)
