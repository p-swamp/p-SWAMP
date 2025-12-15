import pyqtgraph as pg

def gl_color(color):
    return pg.mkPen(color=color).color().getRgbF()
    # if isinstance(color, str) and color[0] == '#':
        # return hex2rgba(color, base=255)

def hex2rgba(color_hex, base=1):
    return tuple([int(color_hex.strip('#')[i:i+2], 16)/base for i in (0, 2, 4)] + [255/base])

background = '#1e3f40'
islanding = [
    # 'lightgray',
    '#bababa',
    '#4876ff',
    '#089200',
    '#42E3D6',
    '#ff5050',
    '#4876ff',
    '#caff70',
    '#ff83fa',
    '#65CCFF',
]
oscillations = [
    '#ff5050',
    '#4876ff',
    '#caff70',
    '#ff83fa',
    '#ffae5a',
    '#089200',
    '#0bdb7d',
    '#42E3D6',
    '#ffff50',
    '#ff5050',
    '#4876ff',
    '#caff70',
    '#ff83fa',
    '#ffae5a',
    '#089200',
    '#0bdb7d',
    '#42E3D6',
    '#ffff50',
    '#ff5050',
    '#4876ff',
    '#caff70',
    '#ff83fa',
    '#ffae5a',
    '#089200',
    '#0bdb7d',
    '#42E3D6',
    '#ffff50',
    '#ff5050',
    '#4876ff',
    '#caff70',
    '#ff83fa',
    '#ffae5a',
    '#089200',
    '#0bdb7d',
    '#42E3D6',
    '#ffff50',
]
# hex = tuple([int(color[i:i+2], 16) for i in (0, 2, 4)] + [0])

# hex2rgba([
#     '4876ff',
#     '089200',
# ])

if __name__ == '__main__':
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    import numpy as np
    
    app = pg.mkQApp()
    ax = pg.plot()
    # ax.addPlot
    ax.addLegend()

    ax_gl = gl.GLViewWidget()


    x = np.arange(10)
    bus_scatters = []
    for c in islanding:
        y = np.random.randn(10)

        pen = pg.mkPen(color=c, width=2)
        # p = pg.plot(np.arange(10), np.random.randn(10), pen=pen)
        p = pg.PlotCurveItem(x, y, pen=pen, name=f'{c}')
        ax.addItem(p)
        bus_scatter = gl.GLLinePlotItem(
            pos=np.vstack([x, y, np.zeros_like(x)]).T,
            color=gl_color(c),  # tuple(c_/255 for c_ in c),  # c,  # [202, 255, 112, 0],  # np.array(c)/255,  # [255, 0, 0, 1],
            width=1
            # size=10,
        )
        ax_gl.addItem(bus_scatter)
        bus_scatters.append(bus_scatter)
    ax.setBackground(background)
    ax_gl.setBackgroundColor(background)
    # pg.show()
    ax_gl.show()

    app.exec()