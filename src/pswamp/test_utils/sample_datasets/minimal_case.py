# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from synchrophasor.simplePMU import SimplePMU
from pswamp.test_utils import runners
from pswamp.streaming.base import Producer
import pandas as pd
import pswamp.visualization.components.single_line_diagram as sld
from io import StringIO
import ezdxf
import sqlite3


def create_minimal_test_case():
    # Returns:
    # config: The configuration for the case, which is used across the p-SWAMP
    # platform
    # con: A reference to the SQLite in-memory database connection, which holds
    # data on the three buses, lines, and a single-line diagram-
    # pmu: A PyPMU object which can be used to generate PMU data frames for
    # the minimal test case.
    
    # Create a new DXF document, which will hold the Single-Line Diagram (SLD).
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    
    # Add lines
    msp.add_line((0, 0), (20, 0))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((20, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((0, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})

    # Add buses
    msp.add_mtext("B1").set_location((0, 0))
    msp.add_mtext("B2").set_location((20, 0))
    msp.add_mtext("B3").set_location((10, 20))

    # Write to the DXF document
    f = StringIO()
    doc.write(f)
    fout = StringIO(f.getvalue())
    doc = ezdxf.read(fout)

    # From the SLD, the coordinates of buses can be obtained by matching names
    # with MTEXT-objects:
    sld.SCALING_FACTOR = 1
    sld.get_buses(doc, ["B1", "B2", "B3"])

    # The configuration for the case:
    config = {
        "database": {
            "type": "sqlite",
            "file_path": "file::memory:?cache=shared",
            "uri": True,
        },
        "single_line_diagrams": {
            "sld1": {
                "countries": ["Norway", "Sweden", "Denmark", "Finland"],
                "aspect_ratio": 2,
                "geo": True,
            }
        },
    }

    # Make a SQLite in-memory database
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)

    # Remove previous tables (if present)
    for field in ["line", "bus", "single_line_diagrams"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue

    # Add new bus and line data
    pd.DataFrame(
        columns=["name", "from_bus", "to_bus"],
        data=[["L1-2", "B1", "B2"], ["L2-3", "B2", "B3"], ["L1-3", "B1", "B3"]],
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
    cursor.execute(
        """CREATE TABLE "single_line_diagrams" ("name" TEXT, "data"	BLOB);"""
    )
    cursor.execute(
        f"""INSERT INTO "single_line_diagrams" (name, data) VALUES ('sld1', '{f.getvalue()}')"""
    )
    con.commit()

    # Add some fields to the configuration
    config["streaming"] = {
        "type": "nqkafka",
        "bootstrap_servers": "localhost: 50000",
        "consumers_seek_to_beginning": True,
    }

    # Start a NQKafka server, acting as a NQKafka server which consumers or
    # producers can connect to.
    runners.run_nqkafka_server(config, run_in_process=False)
    runners.create_topic("pmudata", config["streaming"])
    config["topics"] = {"pmudata": "pmudata"}

    # consumer = Consumer(**config["streaming"], topic="pmudata")

    # Create a PyPMU object that can generate PMU data frames (according to 
    # C37.118), with voltage measurements at the three buses and current
    # measurements at the lines
    pmu = SimplePMU(
        "",
        0,
        station_names=["B1", "B2", "B3"],
        channel_names=[
            ["V", "I[L1-2]", "I[L1-3]"],
            ["V", "I[L1-2]", "I[L2-3]"],
            ["V", "I[L1-3]", "I[L2-3]"],
        ],
    )

    # Create a single PMU data frame and send it to the "pmudata" topic of the
    # NQKafka server
    dataframe = pmu.generate_dataframe()
    producer = Producer(**config["streaming"])
    producer.send(topic="pmudata", msg=dataframe)

    return config, con, pmu
