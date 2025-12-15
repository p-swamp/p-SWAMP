import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from PySide6 import QtWidgets, QtCore


class PhasorPlot3D:
    """This class inserts phasors in a 3D plot window at specific coordinates."""
    # request_plot_update = QtCore.Signal()

    def __init__(self, plot_window, pos0=None, n_phasors=None, normalize_length=True, normalize_angle=False, update_freq=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if pos0 is not None:
            self.n_phasors = len(pos0.T)
        elif n_phasors is not None:
            self.n_phasors = n_phasors
        else:
            print('Either pos0 or n_phasors have to be specified in PhasorPlot3D.')

        if pos0 is None:
            pos0 = np.zeros((self.n_phasors, 3))

        self.normalize_length = normalize_length
        self.normalize_angle = normalize_angle
        self.update_freq = update_freq
        
        self.angles_prev = np.zeros(self.n_phasors)
        
        # print(self.n_phasors)
        

        self.pos0 = pos0
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

        # if self.update_freq:
        #     self.timer = QtCore.QTimer()
        #     self.timer.timeout.connect(self.update_plot)
        #     # self.timer.timeout.connect(self.request_plot_update)
        #     self.timer.start(1000 // update_freq)

        self.phasor_plots = []
        phasors = np.ones(self.n_phasors, dtype=complex)
        for i, (pos0_, phasor) in enumerate(
            zip(pos0.T, phasors[:, None] * self.phasor_0)
        ):
            pos = np.vstack(
                [
                    phasor.real + pos0_[0],
                    phasor.imag + pos0_[1],
                    np.zeros(len(phasor)) + pos0_[2],
                ]
            ).T
            phasor_plot = gl.GLLinePlotItem(
                pos=pos, antialias=True, width=2, color=self.colors(i)
            )
            plot_window.addItem(phasor_plot)

            # plot_win_ph.addItem(pl_ph)
            self.phasor_plots.append(phasor_plot)

    def update(self, phasors, normalize=False):
        self.phasors = phasors
        self.normalize=normalize
        self.update_plot()

    def update_plot(self):
        phasors = self.phasors
        normalize=self.normalize
        """
        Updates the plot with new phasors.
        Args:
            phasors: The new phasors to draw. Complex numpy array of same length as the xyz-positions specified in init.

        Returns:
            None

        """

        draw_phasors = self.phasors.copy()
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

        approx_zero = np.max([1e-6, 1e-3*np.nanmin(abs(draw_phasors))])
        draw_phasors[np.isnan(draw_phasors)|(draw_phasors==0)] = approx_zero

        for i, (phasor_plot, pos0_, phasor) in enumerate(
            zip(self.phasor_plots, self.pos0.T, draw_phasors[:, None] * self.phasor_0)
        ):
            pos = np.vstack(
                [
                    phasor.real + pos0_[0],
                    phasor.imag + pos0_[1],
                    np.zeros(len(phasor)) + pos0_[2],
                ]
            ).T
            phasor_plot.setData(pos=pos)


def main():
    import time
    import threading

    n_phasors = 100

    app = QtWidgets.QApplication()
    window = gl.GLViewWidget()
    phasor_plot = PhasorPlot3D(window, pos0=np.random.randn(3, n_phasors))
    window.show()

    # This is only for showing how the phasors can be updated
    running = True

    vectors = np.random.randn(n_phasors) + 1j * np.random.randn(n_phasors)
    phase_offsets = np.random.randn(n_phasors)
    def updater():
        while running:
            time.sleep(0.05)
            phasor_plot.update(
                vectors + np.sin(time.time() + phase_offsets) + 1j*np.cos(time.time() + phase_offsets)
            )

    thr = threading.Thread(target=updater, daemon=True)
    thr.start()

    app.exec()
    running = False  # Stops the while loop running in the thread
    time.sleep(0.1)  # Allows the thread to exit.
    return app


if __name__ == "__main__":
    main()
