import threading

from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

# pg.setConfigOption('background', 'w')
# pg.setConfigOption('foreground', 'k')


class EigenvaluePlot(QtWidgets.QWidget):
    """This class is for live plotting of eigenvalues."""
    request_plot_update = QtCore.Signal()
    def __init__(self, background_color=(30, 63, 64), *args, **kwargs):
        """
        Constructor for eigenvalue plot.
        Args:
            xy_fun: This function returns the real and imaginary part of the updated eigenvalues.
            *args:
            **kwargs:
        """
        super().__init__(*args, **kwargs)
        # update_freq = 50

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
        self.markers = lambda i: ['o', 't', 't1', 't2', 't3', 's', 'p', 'h', 'star', '+', 'd', 'x'][i%12]

        # self.xy_fun = xy_fun

        # Add a plot window
        self.graphWidget = pg.GraphicsLayoutWidget(show=True, title="Eigenvalue")
        self.graphWidget.setBackground(background_color)
        self.plot_win = plot_win = self.graphWidget.addPlot()

        # Either Hz or rad/s along y-axis
        y_ax_unit = "Hz"
        if y_ax_unit == "rad/s":
            y_scale = 1

        elif y_ax_unit == "Hz":
            y_scale = 1 / (2 * np.pi)
        self.y_scale = y_scale

        # Labels
        plot_win.setLabel("left", "Frequency [{}]".format(y_ax_unit))
        plot_win.setLabel("bottom", "Real part")
        plot_win.addLegend()

        # Axes limits
        y_range = 2 * np.pi * 3 * y_scale
        plot_win.setXRange(-2.5, 0.05, padding=0)
        plot_win.setYRange(-y_range, y_range, padding=0)

        # Draw lines indicating damping
        damping_lines = [3, 5, 7]
        pen = pg.mkPen(color=pg.mkColor(255, 255, 255, 124))
        for damping_line in damping_lines:
            # color = np.array([1, 1, 1]) * damping_line / 10
            slope = np.sqrt(1 - (damping_line / 100) ** 2) / (damping_line / 100)

            y_lim = (
                1000  # The damping line is drawn for y-values between 0 and this value
            )
            for sign in [-1, 1]:
                plot_win.addItem(
                    pg.PlotCurveItem(
                        [0, -y_lim / slope], [0, y_scale * sign * y_lim], pen=pen
                    )
                )

            # Add text
            txt = pg.TextItem(
                text="{}%".format(damping_line),
                color=(200, 200, 200),
                html=None,
                anchor=(0, 0),
                border=None,
                # fill=(0, 0, 0),
                # angle=np.arctan(slope)*180/np.pi,
                rotateAxis=None,
            )

            txt.setPos(-y_range * 0.8 / slope / y_scale, y_range * 0.8)
            plot_win.addItem(txt)

        # x, y = self.xy_fun()
        # self.eigs_pl = plot_win.plot(
        #     [], [], pen=None, symbol="o", symbolBrush="r", symbolSize=15
        # )
        self.eig_plots = {}
        self.eigs = {}

        plot_win.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pen))
        plot_win.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pen))

        self.focus_plot = self.plot_win.plot(
            [], [], pen=None, symbol='o', symbolBrush='r', symbolSize=25,  # label='Selection'
        )
        # self.plot_win.legend.addItem(self.focus_plot, 'Selection')  # str(self.plot_counter))
        
        self.request_plot_update.connect(self.update_plot)
        # self.timer = QtCore.QTimer()
        # self.timer.timeout.connect(self.update)
        # self.timer.start(1000//update_freq)
        self.plot_counter = 0

    def add_plot(self, plot_id, plot_name):
        new_plot = self.plot_win.plot(
            [], [], pen=None, symbol=self.markers(self.plot_counter), symbolBrush=self.colors(self.plot_counter), symbolSize=15, label=self.plot_counter
        )
        self.plot_win.legend.addItem(new_plot, plot_name)  # str(self.plot_counter))
        self.plot_counter += 1
        return self.plot_counter - 1, new_plot

    def update(self, plot_id, plot_name, new_eigs):
        self.eigs[plot_id] = [plot_name, new_eigs]
        self.request_plot_update.emit()
        
    def update_plot(self):
        """Update the eigenvalue plot with new values."""
        # x, y = self.xy_fun()
        for plot_id, (name, eigs) in self.eigs.items():
            if not plot_id in self.eig_plots:
                self.eig_plots[plot_id] = self.add_plot(plot_id, name)
            
            self.eig_plots[plot_id][1].setData(eigs.real, self.y_scale * eigs.imag)

    def set_focus(self, plot_id, idx):
        self.focus_plot.setData(
            self.eigs[plot_id][1].real[[idx]],
            self.y_scale * self.eigs[plot_id][1].imag[[idx]],
            # symbol='o',
            # color='g',
        )
        self.focus_plot.setSymbol(self.markers(self.eig_plots[plot_id][0]))
        self.focus_plot.setSymbolBrush(self.colors(self.eig_plots[plot_id][0]))


def main():
    app = QtWidgets.QApplication()

    ev_plot = EigenvaluePlot()

    import time

    eigs_pl_1 = np.random.randn(10) + 1j*np.random.randn(10)
    eigs_pl_2 = np.random.randn(10) + 1j*np.random.randn(10)
    
    t_0 = time.time()
    def update_fun():
        while True:
            ev_plot.update('plot_1', 'Plot 1', eigs_pl_1 + 0.01*(np.random.randn(10) + 1j*np.random.randn(10)))
            ev_plot.update('plot_2', 'Plot 2', eigs_pl_2 + 0.01*(np.random.randn(10) + 1j*np.random.randn(10)))

            if 0.1 < time.time() - t_0 < 4:
                ev_plot.set_focus('plot_2', 4)
            elif 4 < time.time() - t_0:
                ev_plot.set_focus('plot_1', 6)
            
            # ev_plot.update('plot_3', 'Plot 3', 0.5*np.random.randn(10) + 8j * np.random.randn(10))
            # ev_plot.update('plot_4', 'Plot 4', 0.2*np.random.randn(10) + 3j * np.random.randn(10))
            # ev_plot.update('plot_5', 'Plot 5', 0.8*np.random.randn(10) + 1j * np.random.randn(10))
            time.sleep(0.1)

    update_thread = threading.Thread(target=update_fun, daemon=True)
    update_thread.start()

    app.exec()


if __name__ == "__main__":
    main()
