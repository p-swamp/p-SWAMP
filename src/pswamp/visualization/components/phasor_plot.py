import sys
import numpy as np
import PySide6.QtCore as QtCore
import PySide6.QtWidgets as QtWidgets
import pyqtgraph as pg
from pswamp.utils.misc import flatten_array_insert_nan


def xy_from_phasors(phasors):
    phasor_0 = np.array([0, 1, 0.9, 1, 0.9, 1]) + 1j * np.array([0, 0, -0.1, 0, 0.1, 0])
    xy_complex = phasors[:, None]*phasor_0
    return xy_complex.real, xy_complex.imag


class PhasorBasePlot(pg.GraphicsLayoutWidget):
    def __init__(self, title="", background_color=(30, 63, 64), draw_grid=True):
        super().__init__(title=title)
        self.setBackground(background_color)

        self.plotWidget = self.addPlot(title="")
        self.plotWidget.setAspectLocked(True)
        self.plotWidget.addLegend()
        self.plots = []

        if draw_grid:
            n_circles = 5
            for r in np.linspace(0, 1, n_circles)[1:]:
                circle = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
                circle.setPen(pg.mkPen("gray", width=0.5))
                self.plotWidget.addItem(circle)

            for angle in np.arange(0, 1, 0.25) * np.pi:
                x = np.array([-np.cos(angle), np.cos(angle)])
                y = np.array([-np.sin(angle), np.sin(angle)])
                line = pg.PlotCurveItem(x, y, pen=pg.mkPen("gray", width=0.5))
                self.plotWidget.addItem(line)

        self.plotWidget.hideAxis("bottom")
        self.plotWidget.hideAxis("left")
        self.plotWidget.enableAutoRange("xy", True)

    def add_plot(self, color='lightgray', width=2, **kwargs):
        pen = pg.mkPen(color=color, width=width)
        # plot = self.plotWidget.plot([0, 0], [0, 0], pen=pen, **kwargs)
        plot = pg.PlotCurveItem(pen=pen, connect='finite', **kwargs)
        self.plotWidget.addItem(plot)
        self.plots.append(plot)
        return plot

class PhasorPlot(QtWidgets.QWidget):
    request_plot_update = QtCore.Signal()
    def __init__(self, n_phasors=None, pos0=None, normalize_length=True, normalize_angle=False, update_freq=None, plot_widget=None, background_color=(30, 63, 64), *args, **kwargs):

        if pos0 is not None:
            self.n_phasors = pos0.shape[0]
        elif n_phasors is not None:
            self.n_phasors = n_phasors
        else:
            print('Either pos0 or n_phasors have to be specified in PhasorPlot.')

        if pos0 is None:
            pos0 = np.zeros((self.n_phasors, 2))
        self.pos0 = pos0

        self.approx_zero_value = 1e-6

        self.normalize_length = normalize_length
        self.normalize_angle = normalize_angle
        self.update_freq = update_freq

        self.angles_prev = np.zeros(self.n_phasors)
        self.phasors = np.ones(self.n_phasors, dtype=complex)
        self.phasor_0 = np.array([0, 1, 0.9, 1, 0.9, 1]) + 1j * np.array(
            [0, 0, -0.1, 0, 0.1, 0]
        )

        self.colors = lambda i: pg.intColor(
            i,
            hues=9,
            values=1,
            maxValue=255,
            minValue=150,
            maxHue=360,
            minHue=0,
            sat=255,
            alpha=255,
        )

        if self.update_freq:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.update_plot)
            # self.timer.timeout.connect(self.request_plot_update)
            self.timer.start(1000 // update_freq)
        
        super().__init__(*args, **kwargs)
        self.request_plot_update.connect(self.update_plot)

        # Phasor diagram
        if plot_widget is not None:
            self.plot_win_ph = plot_widget
        else:
            self.graphWidget = pg.GraphicsLayoutWidget(show=True, title="")
            self.graphWidget.setBackground(background_color)
            self.plot_win_ph = self.graphWidget.addPlot(title="")
            self.plot_win_ph.setAspectLocked(True)
            self.graphWidget.show()
            self.plot_win_ph.enableAutoRange("xy", False)

        self.create_plot_items()
        
        # self.update(np.ones(self.n_phasors, dtype=complex)*1e-6)

    def create_plot_items(self):    
        self.phasor_plots = self.pl_ph = []
        for i, phasor in enumerate(self.phasors[:, None] * self.phasor_0):
            pen = pg.mkPen(color=self.colors(i), width=2)
            pl_ph = pg.PlotCurveItem(phasor.real + self.pos0[i, 0], phasor.imag + self.pos0[i, 1], pen=pen)
            self.plot_win_ph.addItem(pl_ph)
            self.pl_ph.append(pl_ph)

    def update(self, phasors):  # , normalize=False):
        self.phasors = np.concatenate([phasors, np.ones(self.n_phasors - len(phasors))*self.approx_zero_value])
        #  = phasors
        # self.normalize = normalize
        if not self.update_freq:
            self.request_plot_update.emit()

    def update_plot(self):
        draw_phasors = self.phasors.copy()
        if np.all(np.isnan(draw_phasors)): return
        
        if self.normalize_length:
            max_idx = np.nanargmax(abs(draw_phasors))
            if abs(draw_phasors[max_idx]) > 0:
                draw_phasors = draw_phasors / abs(draw_phasors[max_idx])  # if normalize == 'length' else phasors[max_idx])
            else:
                draw_phasors = 0 * draw_phasors

        if self.normalize_angle == 'mean':
            angle = np.angle(draw_phasors)
            angle = np.unwrap(np.vstack([self.angles_prev, angle]), axis=0)[1, :]
            not_nan_idx = ~np.isnan(angle)
            self.angles_prev[not_nan_idx] = angle[not_nan_idx]

            angle -= np.nanmean(angle[abs(draw_phasors) > max(abs(draw_phasors))*0.9])
            draw_phasors = abs(draw_phasors)*np.exp(1j*angle)
        elif self.normalize_angle == 'max':
            max_idx = np.nanargmax(abs(draw_phasors))
            if abs(draw_phasors[max_idx]) > 0:
                draw_phasors = draw_phasors*np.exp(-1j*np.angle(draw_phasors[max_idx]))  # if normalize == 'length' else phasors[max_idx])

        approx_zero = np.max([self.approx_zero_value, 1e-3*np.nanmin(abs(draw_phasors))])
        draw_phasors[np.isnan(draw_phasors)|(draw_phasors==0)] = approx_zero

        self.update_plot_items(draw_phasors)

    def update_plot_items(self, draw_phasors):
        for i, (pl_ph, pos0_, phasor) in enumerate(
            zip(self.pl_ph, self.pos0, draw_phasors[:, None] * self.phasor_0)
        ):
            pl_ph.setData(phasor.real + pos0_[0], phasor.imag + pos0_[1])

class PhasorPlotFast(PhasorPlot):    
    def __init__(self, *args, color='w', **kwargs):
        self.color = color
        super().__init__(*args, **kwargs)

    def create_plot_items(self):
        pen = pg.mkPen(color=self.color, width=2)
        self.phasor_plot = pg.PlotCurveItem([self.approx_zero_value, self.approx_zero_value], [self.approx_zero_value, self.approx_zero_value], pen=pen, connect='finite')
        self.plot_win_ph.addItem(self.phasor_plot)

    def update_plot_items(self, phasors):
        complex_arrow_data = phasors[:, None] * self.phasor_0
        x_data = (complex_arrow_data.real.T + self.pos0[:, 0]).T
        y_data = (complex_arrow_data.imag.T + self.pos0[:, 1]).T
        # z_data = (np.zeros_like(x_data).T + self.pos0[:, 2]).T

        # pos = np.vstack([
        x_data = np.vstack([x_data.T, np.nan*np.ones(x_data.shape[0])]).T.flatten()
        y_data = np.vstack([y_data.T, np.nan*np.ones(y_data.shape[0])]).T.flatten()
        #     # np.vstack([z_data.T, np.nan*np.ones(z_data.shape[0])]).T.flatten(),
        # ]).T

        self.phasor_plot.setData(x_data, y_data)


class PhasorPlotFancy(PhasorPlot):
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        n_circles = 5
        for r in np.linspace(0, 1, n_circles)[1:]:
            circle = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            circle.setPen(pg.mkPen("gray", width=0.5))
            self.plot_win_ph.addItem(circle)

        for angle in np.arange(0, 1, 0.25) * np.pi:
            x = np.array([-np.cos(angle), np.cos(angle)])
            y = np.array([-np.sin(angle), np.sin(angle)])
            line = pg.PlotCurveItem(x, y, pen=pg.mkPen("gray", width=0.5))
            self.plot_win_ph.addItem(line)

        self.plot_win_ph.hideAxis("bottom")
        self.plot_win_ph.hideAxis("left")
        self.plot_win_ph.enableAutoRange("xy", True)


class PhasorPlotFastFancy(PhasorPlotFast, PhasorPlotFancy):
    def __init__(self, *args, color='w', **kwargs):
        self.color = color
        PhasorPlotFancy.__init__(self, *args, **kwargs)
        



def main_2():
    app = QtWidgets.QApplication(sys.argv)

    n_phasors = 100
    # phasor_plot = PhasorPlot(n_phasors, update_freq=10)
    base_plot = PhasorBasePlot()
    plot_handle = base_plot.add_plot(color='r')
    base_plot.show()
    # phasor_plot_fancy = PhasorPlotFancy(n_phasors, update_freq=None, normalize_length=True)
    # phasor_plot_fast = PhasorPlotFastFancy(
    #     n_phasors, update_freq=None, normalize_length=True)
    # phasor_plot_fast_2 = PhasorPlotFast(n_phasors, update_freq=None, normalize_length=True, plot_widget=base_plot.plotWidget, color='r')
    # phasor_plot_fast_3 = PhasorPlotFast(n_phasors, update_freq=None, normalize_length=True, plot_widget=base_plot.plotWidget, color='r')
    # phasor_plot_fast_2 = PhasorPlotFast(n_phasors, update_freq=None, normalize_length=True, plot_widget=base_plot.plotWidget, color='r')
    # # phasor_plot_fancy_2 = PhasorPlotFancy(pos0=np.random.randn(10, 2), update_freq=None, normalize_length=True)

    mode_text = pg.TextItem(
        text="Some text",
        color=(200, 200, 200),
        html=None,
        anchor=(0, 0),
        border=None,
        # fill=(0, 0, 0),
        rotateAxis=None,
    )
    mode_text.setPos(0, -1.2)
    base_plot.plotWidget.addItem(mode_text)

    import time
    import threading

    def update_fun():
        while True:
            phasors = np.random.randn(7) + 1j * np.random.randn(7)
            x, y = xy_from_phasors(phasors/max(abs(phasors)))
            x, y = flatten_array_insert_nan(x.T, y.T)
            base_plot.plots[0].setData(x, y)
            
            # phasor_plot.update(np.random.randn(10) + 1j * np.random.randn(10))
            # phasor_plot_fancy.update(np.random.randn(7) + 1j * np.random.randn(7))
            # phasor_plot_fast.update(np.random.randn(7) + 1j * np.random.randn(7))
            # phasor_plot_fast_2.update(np.random.randn(7) + 1j * np.random.randn(7))
            # phasor_plot_fast_3.update(np.random.randn(7) + 1j * np.random.randn(7))
            # phasor_plot_fancy_2.update(np.random.randn(10) + 1j * np.random.randn(10))
            time.sleep(0.01)

    update_thread = threading.Thread(target=update_fun, daemon=True)
    update_thread.start()

    app.exec()

    return app


def main():
    app = QtWidgets.QApplication(sys.argv)

    n_phasors = 100
    # phasor_plot = PhasorPlot(n_phasors, update_freq=10)
    phasor_plot_fancy = PhasorPlotFancy(n_phasors, update_freq=None, normalize_length=True)
    phasor_plot_fast = PhasorPlotFastFancy(
        n_phasors, update_freq=None, normalize_length=True)
    phasor_plot_fast_2 = PhasorPlotFast(n_phasors, update_freq=None, normalize_length=True, plot_widget=phasor_plot_fast.plot_win_ph, color='r')
    # phasor_plot_fancy_2 = PhasorPlotFancy(pos0=np.random.randn(10, 2), update_freq=None, normalize_length=True)

    mode_text = pg.TextItem(
        text="Some text",
        color=(200, 200, 200),
        html=None,
        anchor=(0, 0),
        border=None,
        # fill=(0, 0, 0),
        rotateAxis=None,
    )
    mode_text.setPos(0, -1.2)
    phasor_plot_fancy.plot_win_ph.addItem(mode_text)

    import time
    import threading

    def update_fun():
        while True:
            # phasor_plot.update(np.random.randn(10) + 1j * np.random.randn(10))
            phasor_plot_fancy.update(np.random.randn(7) + 1j * np.random.randn(7))
            phasor_plot_fast.update(np.random.randn(7) + 1j * np.random.randn(7))
            phasor_plot_fast_2.update(np.random.randn(7) + 1j * np.random.randn(7))
            # phasor_plot_fancy_2.update(np.random.randn(10) + 1j * np.random.randn(10))
            time.sleep(0.01)

    update_thread = threading.Thread(target=update_fun, daemon=True)
    update_thread.start()

    app.exec()

    return app


if __name__ == "__main__":
    main_2()
