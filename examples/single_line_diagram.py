import matplotlib.pyplot as plt
import pandas as pd
import pswamp.database as db
import pswamp.visualization.components.single_line_diagram as sld
from io import StringIO
import ezdxf
# from ezdxf import colors
# from ezdxf.enums import TextEntityAlignment
import sqlite3


if __name__ == "__main__":
    
    # %%
    # Create a new DXF document.
    doc = ezdxf.new(dxfversion="R2010")

    msp = doc.modelspace()

    # Add entities to a layout by factory methods: layout.add_...() 
    msp.add_line((0, 0), (20, 0))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((20, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((0, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_mtext("B1").set_location((0, 0))
    msp.add_mtext("B2").set_location((20, 0))
    msp.add_mtext("B3").set_location((10, 20))

    f = StringIO()
    doc.write(f)
    
    fout = StringIO(f.getvalue())
    doc = ezdxf.read(fout)
    
    sld.SCALING_FACTOR = 1
    sld.get_buses(doc, ["B1", "B2", "B3"])

    config = {
        "database": {"type": "sqlite", "file_path": "file::memory:?cache=shared", "uri": True},
        "single_line_diagrams": {
            "sld1": {
                "countries": ["Norway", "Sweden", "Denmark", "Finland"],
                "aspect_ratio": 2,
            }
        }
    }
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)
    # %%
    # Remove previous tables (if present)
    for field in ["line", "bus", "single_line_diagrams"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue

    # Add new bus and line data
    pd.DataFrame(
        columns=["name", "from_bus", "to_bus"],
        data=[
            ["L1-2", "B1", "B2"],
            ["L2-3", "B2", "B3"],
            ["L1-3", "B1", "B3"]
        ],
    ).to_sql("line", con)

    pd.DataFrame(
        columns=["name", "V_n"],
        data=[
            ["B1", 420],
            ["B2", 420],
            ["B3", 420],
        ],
    ).to_sql("bus", con)

    cursor = con.cursor()
    cursor.execute("""CREATE TABLE "single_line_diagrams" ("name" TEXT, "data"	BLOB);""")
    cursor.execute(f"""INSERT INTO "single_line_diagrams" (name, data) VALUES ('sld1', '{f.getvalue()}')""")
    con.commit()
    # %%

    data = db.get_from_database(config["database"], "single_line_diagrams")
    data.iloc[-1]
    
    fout = StringIO(data["data"][0])
    doc = ezdxf.read(fout)
    
    bus_data = db.get_from_database(config["database"], "bus")
    line_data = db.get_from_database(config["database"], "line")
    sld.SCALING_FACTOR = 1
    # TODO: How to deal with it when some buses are missing in the SLD?
    buses, bus_coords = sld.get_buses(doc, bus_data["name"])
    line_coords, midpoints = sld.get_branches_xy_by_matching_buses(doc, line_data)

    [plt.plot(lc[:, 0], lc[:, 1]) for lc in line_coords]
    plt.scatter(bus_coords[:, 0], bus_coords[:, 1])
    plt.show()
    # %%
    import numpy as np
    class BusesLayer:
        def __init__(self, parent, config, geo=True) -> None:
            self.config = config
            self.plotWidget = parent.plotWidget
            self.k = 2 if geo else 1

            bus_data = db.get_from_database(config["database"], "bus")
            bus_names, bus_coords = sld.get_buses(doc, bus_data["name"])
            
            bus_coords[:, 1] *= self.k

            self.x = bus_coords[:, 0]
            self.y = bus_coords[:, 1]
            # self.z = bus_coords[:, 2]

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

            use_colors = False
            color = np.ones((len(bus_coords), 4))
            color[:, -1] = 0.5
            if use_colors:
                color = (
                    np.array([self.colors(i).getRgb() for i in range(len(bus_coords))])
                    / 255
                )
            self.bus_scatter = self.add_scatter_plot(bus_coords)
            self.plotWidget.addItem(self.bus_scatter)

        def add_scatter_plot(self, bus_coords):
            return pg.ScatterPlotItem(
                x=bus_coords[:, 0], y=bus_coords[:, 1], brush=pg.mkBrush(('white')))  # pen=pg.mkPen('w'), )

        def remove_layer(self):
            self.plotWidget.removeItem(self.bus_scatter)
    

    # %%
    from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
    # import pswamp.gui.grid_view.dim_2d.layers.lines_2 as ll
    # import pswamp.gui.grid_view.dim_2d.layers.buses as bl
    import pswamp.gui.grid_view.dim_2d.layers as layers
    import importlib
    # importlib.reload(ll)
    # importlib.reload(bl)
    importlib.reload(db)
    importlib.reload(layers)

    dir(layers)
    
    import pyqtgraph as pg
    app = pg.mkQApp()
    grid_plot = GridBasePlot2D()
    grid_plot.window.show()
    # buses_layer = BusesLayer(grid_plot, config, geo=False)
    line_layer = layers.LineLayer(grid_plot, config, sld_id="sld1")
    bus_layer = layers.BusesLayer(grid_plot, config, sld_id="sld1")
    bus_layer = layers.BusNamesLayer(grid_plot, config, sld_id="sld1")
    # countries_layer = bl.BusesLayer(grid_plot, config, sld_id="sld1")

    tables = ["bus", "line", "trafo"]
    model_data = {table: db.get_from_database(config["database"], table) for table in tables}
    app.exec()

    # %%

    config["streaming"]