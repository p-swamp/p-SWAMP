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

import sqlite3
import pandas as pd
import json


def get_from_database(db_kwargs, field):
    if db_kwargs["type"] == "sqlite":
        con = sqlite3.connect(db_kwargs["file_path"],
            **{k: v for k, v in db_kwargs.items() if k not in ["type", "file_path"]})
        try:
            data = pd.read_sql(f"SELECT * FROM {field}", con)
        except pd.errors.DatabaseError:
            return
        if "index" in data.columns:
            data = data.set_index("index")
        con.close()
        return data
    
    elif db_kwargs["type"] == "file":
        with open(db_kwargs["file_path"]) as file:
            model_data = json.load(file)
        return pd.DataFrame(columns=model_data[field][0], data=model_data[field][1:])
