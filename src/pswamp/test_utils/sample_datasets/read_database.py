from pswamp import load_config
from pswamp.database import get_from_database
import ezdxf
from io import StringIO


if __name__ == "__main__": 

    config = load_config()
    # pmu_info = get_from_database(config, "pmu")
    pmu_info = get_from_database(config, "pmu")

    print(pmu_info)

    sld_data = get_from_database(config, "single_line_diagrams")
    dxf_data = sld_data[sld_data["name"] == "other"]["data"].values[-1]

    dxf_file_stream = StringIO(dxf_data)
    doc = ezdxf.read(dxf_file_stream)