# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

# from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
import sys


class SurfacePlot(QtWidgets.QWidget):
    """Creates a 3D surface plot for visualizing a 2D array."""

    def __init__(
        self, cols, rows, height_fun, *args, col_ticks=[], row_ticks=[], background_color=(30, 63, 64), **kwargs
    ):
        """
        Constructor for the surface plot. The size of the array is specified (cols, rows), and a function returning the
        updated array. Values along the x- and y-axis can be displayed using col_ticks and row_ticks. (The ticks will
        be placed such that the first and last values are positioned at the ends of the surface.)
        Args:
            cols: The number of columns of the array to be visualized.
            rows: The number of rows of the array to be visualized.
            height_fun: A function returning the updated array to be drawn.
            *args:
            col_ticks: Ticks on column axis.
            row_ticks: Ticks on row axis.
            **kwargs:
        """
        super().__init__(*args, **kwargs)

        # Main window
        w = gl.GLViewWidget()
        w.setBackgroundColor(background_color)
        # w.show()
        w.setWindowTitle("Surface plot")
        w.setCameraPosition(distance=25)
        # layout = 
        self.w = w
        self.window = w

        # layout = QtWidgets.QHBoxLayout()
        # layout.addWidget(w)
        # self.setLayout(layout)

        # Draw grid
        g = gl.GLGridItem()
        g.scale(2, 2, 1)
        g.setDepthValue(10)
        w.addItem(g)

        # Spec of the array
        self.cols = cols
        self.rows = rows
        self.height_fun = height_fun

        x = np.linspace(-8, 8, cols).reshape(cols, 1)
        y = np.linspace(-8, 8, rows).reshape(1, rows)

        # This is from a pyqtgraph example:
        ## create a surface plot, tell it to use the 'heightColor' shader
        ## since this does not require normal vectors to render (thus we
        ## can set computeNormals=False to save time when the mesh updates)
        self.pl = gl.GLSurfacePlotItem(
            x=x[:, 0],
            y=y[0, :],
            shader="heightColor",
            computeNormals=False,
            smooth=True,
        )
        # self.pl.shader()['colorMap'] = np.array([0.2, 2, 0.5, 0.2, 1, 1, 0.2, 0, 2])
        self.pl.shader()["colorMap"] = np.array(
            [0.2, 2, 0.5, 0.2, 1, 1, 0.2, 0, 2]  # r  # g
        )  # b
        w.addItem(self.pl)

        font = QtGui.QFont()
        font.setPixelSize(12)

        # Add some values along the x-axis
        for x_tick in col_ticks:
            x_tick_pos = x[0, 0] + (x[-1, 0] - x[0, 0]) / (
                col_ticks[-1] - col_ticks[0]
            ) * (x_tick - col_ticks[0])
            txtitem1 = gl.GLTextItem(
                pos=(x_tick_pos, np.max(y), 0.0),
                text="{:.2f}".format(x_tick),
                font=font,
            )
            w.addItem(txtitem1)

        # Add some values along the y-axis
        for y_tick in row_ticks:
            y_tick_pos = y[0, 0] + (y[0, -1] - y[0, 0]) / (
                row_ticks[-1] - row_ticks[0]
            ) * (y_tick - row_ticks[0])
            txtitem1 = gl.GLTextItem(
                pos=(np.max(x), y_tick_pos, 0.0), text="{:.2f}".format(y_tick)
            )
            w.addItem(txtitem1)

        # The plots are updated [update_freq] times pr. second.
        update_freq = 25
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(update_freq)

    def update(self):
        """
        Function for updating the surface plot with new array.
        Returns:
            None

        """
        z = self.height_fun()
        if not np.any(np.isnan(z)):
            self.pl.setData(z=z)


if __name__ == "__main__":

    cols = 50
    rows = 60

    def height_fun():
        return np.random.random((cols, rows))

    # This line is required to allow multiple surface plots in the same thread.
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    fft_plt = SurfacePlot(
        cols, rows, height_fun, col_ticks=[-1, 0, 1]
    )  # , row_ticks=[0, 10, 20, 30])
    fft_plt.w.show()

    fft_plt_2 = SurfacePlot(
        cols, rows, height_fun, col_ticks=[-1, 0, 1]
    )  # , row_ticks=[0, 10, 20, 30])
    fft_plt_2.w.show()

    # w_1 = gl.GLViewWidget()
    # g = gl.GLGridItem()
    # g.scale(2, 2, 1)
    # g.setDepthValue(10)
    # w_1.addItem(g)
    # w_1.show()

    # w_2 = gl.GLViewWidget()
    # g = gl.GLGridItem()
    # g.scale(2, 2, 1)
    # g.setDepthValue(10)
    # w_2.addItem(g)
    # w_2.show()

    app.exec()
