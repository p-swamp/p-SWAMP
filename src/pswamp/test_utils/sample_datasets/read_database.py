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
