# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore




# def dSdZ(Eth, Zth, Zl, theta):
#     nom = Eth**2*((Zth**2 -Zl**2))
#     den = (Zl**2 + Zth**2 +2*Zl*Zth*np.cos(theta))**2
#     return nom/den

def lpf(v_prev, v_in, beta):
    if v_prev is None:
        v_prev = v_in
    return beta*v_prev + (1 - beta)*v_in


def generate_dSdZ_curve(E_th, Z_th, Z_l, ang_Z_l, ang_thev):
    num = (E_th**2)*(Z_th**2 - Z_l**2)
    den = (Z_th**2 + Z_l**2 + 2*Z_l*Z_th*np.cos(ang_thev - ang_Z_l))**2
    return num/den


class dSdZPlot(pg.GraphicsLayoutWidget):
    request_plot_update = QtCore.Signal()
    def __init__(self, curve_data=None):
        super().__init__()

        self.plot_ax = self.addPlot()
        self.plot_ax.addLegend()
        self.setBackground((30, 63, 64))
        # [plot_ax.addItem(pg.InfiniteLine((0, 0), angle=a)) for a in [0, 90]]
        self.colors = ['b', 'lightblue', 'm', 'g']

        self.ang_thev = 90*np.pi/180

        self.indicator_plot = pg.ScatterPlotItem(brush=pg.mkBrush(color='r'), size=10)
        self.plot_ax.addItem(self.indicator_plot)

        self.isocurves = []

        self.Z_l = None

        if curve_data is not None: self.add_isocurves(curve_data) 

        self.request_plot_update.connect(self.update)

        # self.dynamic_isocurve = pg.PlotCurveItem(pen=pg.mkPen(color='w', width=2))  # name=f'{Z_th} Zth')
        # self.plot_ax.addItem(self.dynamic_isocurve)
        

    def add_isocurves(self, curve_data):
        if 'dSdZ_lims' in curve_data:
            self.plot_ax.setYRange(*curve_data['dSdZ_lims'])
            
        self.Z_l = Z_l = np.arange(*curve_data['Zl_range'])
        for i, (ang_Z_l, Z_th, E_th) in enumerate(zip(*[curve_data[key] for key in ['ang_Zl', 'Zth', 'Eth']])):
            curve_dSdZ = generate_dSdZ_curve(E_th, Z_th, Z_l, ang_Z_l, self.ang_thev)
            pl = pg.PlotCurveItem(x=Z_l, y=curve_dSdZ, pen=pg.mkPen(color=self.colors[i], width=2, style=QtCore.Qt.DashLine))  # name=f'{Z_th} Zth')
            self.plot_ax.addItem(pl)
            self.isocurves.append(pl)       

    def update_external(self, data):
        self._newest_data = data
        self.request_plot_update.emit()

    
    def update(self, data=None):
        if data is None:
            data = self._newest_data
        # Should not be called by other threads than main.
        dSdZ = data['result']['dSdZ']
        Zl = data['result']['Zl']
        Eth = data['result']['Eth']
        Zth = data['result']['Zth']
        ang_Z_l = data['result']['Zl_angle']

        if self.Z_l is not None:
            dSdZ_curve = generate_dSdZ_curve(Eth, Zth, self.Z_l, ang_Z_l, self.ang_thev)
            # self.dynamic_isocurve.setData(self.Z_l, dSdZ_curve)

        self.indicator_plot.setData(x=[Zl], y=[dSdZ])


class dSdZPlotAuto(dSdZPlot):
    def __init__(self, *args, **kwargs):
        self.Z_th_range = np.array([0.8, 0.9, 1, 1.1, 1.2])
        self.Z_l_range = np.arange(100, 3000, 1)/300
        self.colors = ['r', 'g', 'b', 'y', 'm']
        self.lpf_beta = 0.95

        self.Z_l = None
        self.Z_th = None
        self.E_th = None
        self.ang_Z_l = None
        super().__init__(*args, **kwargs)

    def add_isocurves(self):
        for i, Z_th in enumerate(self.Z_th_range):
            pl = pg.PlotCurveItem(name=f'{Z_th} Zth', pen=pg.mkPen(color=self.colors[i], width=2))
            self.plot_ax.addItem(pl)
            self.isocurves.append(pl)

    def update_isocurves(self, new_data):
        self.Z_l = lpf(self.Z_l, new_data['result']['Zl']*self.Z_l_range, self.lpf_beta)
        self.Z_th = lpf(self.Z_th, new_data['result']['Zth']*self.Z_th_range, self.lpf_beta)
        self.E_th = lpf(self.E_th, new_data['result']['Eth'], self.lpf_beta)
        self.ang_Z_l = lpf(self.ang_Z_l, new_data['result']['Zl_angle'], self.lpf_beta)

        for i, Z_th_ in enumerate(self.Z_th):
            num = (self.E_th**2)*(Z_th_**2 - self.Z_l**2)
            den = (Z_th_**2 + self.Z_l**2 + 2*self.Z_l*Z_th_*np.cos(self.ang_thev - self.ang_Z_l))**2
            curve_dSdZ = num/den
            self.isocurves[i].setData(x=self.Z_l, y=curve_dSdZ)

    def update_ang_thev(self, new_data):
        Z_l = new_data['result']['Zl']
        Z_th = new_data['result']['Zth']
        E_th = new_data['result']['Eth']
        ang_Z_l = new_data['result']['Zl_angle']
        dSdZ = new_data['result']['dSdZ']

        num = (E_th**2)*(Z_th**2 - Z_l**2)
        den = (Z_th**2 + Z_l**2 + 2*Z_l*Z_th *
               np.cos(self.ang_thev - ang_Z_l))**2

        ang_thev_new = ang_Z_l + \
            np.arccos(1/(2*Z_l*Z_th) * (np.sqrt(num/dSdZ) - Z_th**2 - Z_l**2))

        self.ang_thev = lpf(self.ang_thev, ang_thev_new, self.lpf_beta)


class dSdZPlotAutoUI(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.dSdZ_plot = dSdZPlotAuto(*args, **kwargs)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        # slider.setMaximum(100)
        self.slider.valueChanged.connect(self.update_slider)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.dSdZ_plot)
        layout.addWidget(self.slider)
        self.setLayout(layout)

    def update_slider(self, val):
        # print(val)
        self.dSdZ_plot.ang_thev = val/100*np.pi

    def add_isocurves(self, *args, **kwargs):
        return self.dSdZ_plot.add_isocurves(*args, **kwargs)

    def update_isocurves(self, *args, **kwargs):
        return self.dSdZ_plot.update_isocurves(*args, **kwargs)

    def update_ang_thev(self, *args, **kwargs):
        return self.dSdZ_plot.update_ang_thev(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self.dSdZ_plot.update(*args, **kwargs)


        


if __name__ == '__main__':

    data = {
        'time_stamp': 0,
        'info': {
            'app_name': 'VoltageStabilityMonitor',
            'uuid': '123',
            'locations': 'Station',
        },
        'parameters': {},
        'result': {
            'Zl': 0.02,
            'Zl_angle': 0.5404195002,
            'Zth': 0.014941860,
            'ratio': 300/400,
            # 'vsi': VSI,
            'Pmax': 100,
            'Pmargin': 10,
            'dSdZ': -300,
            'Eth': 1.34,
        }
    }

    curve_data = {
        'Zl_range': (0.01, 0.15, 0.001),
        'ang_Zl': [0.540419500270582, 0.5404195002705714, 0.5404195002705607, 0.5404195002705505],
        'Zth': [0.019452813298988274, 0.014941860469164915, 0.015992839672011358, 0.0171006111356433],
        'Eth': [1.4625731424296669, 1.3427068419651353, 1.3846150854589492, 1.4185168203257166],
    }
    
    app = pg.mkQApp()  

    dsdz_plot = dSdZPlot(curve_data)
    dsdz_plot.update_external(data)
    dsdz_plot.show()

    if False:
        dsdz_plot = dSdZPlotAutoUI()
        # dsdz_plot = dSdZPlotAuto(curve_data)
        dsdz_plot.show()
        dsdz_plot.update(data)
        # dsdz_plot.update_ang_thev(data)
        dsdz_plot.update_isocurves(data)
        # dsdz_plot.disableAutoRange()

        def update():
            # dsdz_plot.update_ang_thev(data)
            # print(dsdz_plot.ang_thev)
            dsdz_plot.update_isocurves(data)

        from PySide6 import QtCore
        timer = QtCore.QTimer()
        timer.timeout.connect(update)
        timer.start(100)


    app.exec()
