from PySide6 import QtWidgets, QtCore
# from pyqtgraph.console import ConsoleWidget
# import numpy as np


class SimulationControl(QtWidgets.QWidget):
    def __init__(self, rts, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # self.setBackgroundRole(QtGui.QPalette.Base)
        # self.setAutoFillBackground(True)

        self.rts = rts

        # Controls
        self.ctrlWidget = QtWidgets.QWidget()
        self.ctrlWidget.setWindowTitle('Simulation Controls')
        layout = QtWidgets.QGridLayout()

        # Add speed slider
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self.ctrlWidget)
        self.speed_slider = slider
        slider.setMinimum(20)
        slider.setMaximum(1000)
        slider.valueChanged.connect(lambda state: self.updateSpeed())
        slider.setAccessibleName('Simulation speed')
        slider.setValue(100)
        layout.addWidget(slider, 0, 0)

        # Pause button
        button = QtWidgets.QPushButton('Pause')
        button.setCheckable(True)
        button.setChecked(False)
        layout.addWidget(button, 1, 0)
        button.clicked.connect(lambda state: self.pauseSimulation())

        # Reset button
        # button = QtWidgets.QPushButton('Reset')
        # button.setCheckable(False)
        # layout.addWidget(button, 2, 0)
        # button.clicked.connect(lambda state: self.resetSimulation())

        self.ctrlWidget.setLayout(layout)
        self.ctrlWidget.show()

    def updateSpeed(self):
        self.rts.speed = self.speed_slider.value()/100

    # def resetSimulation(self):
        # self.rts.toggle_pause()
        # self.ps.init_dyn_sim()
        # self.rts.sol.x[:] = self.ps.x_0
        # self.rts.sol.v[:] = self.ps.v_0
        # self.rts.toggle_pause()

    def pauseSimulation(self):
        self.rts.toggle_pause()


def run_simulation_control(rts):
    app = QtWidgets.QApplication()
    sim_ctrl = SimulationControl(rts)
    app.exec()