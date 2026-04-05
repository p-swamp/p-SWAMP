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

from pswamp.streaming import get_last_message_from_topic
import numpy as np
import pandas as pd
import pandas as pd
import json
from pswamp.utils.misc import recursively_default_dict


def replace_data_lists_with_dataframes(d):
    for k, v in d.items():
        if isinstance(v, dict):
            print(f'Dict {k}:{v}')
            replace_data_lists_with_dataframes(v)
        elif isinstance(v, list):
            d[k] = pd.DataFrame(columns=v[0], data=v[1:])


def get_model_data(config):
    model_data = get_last_message_from_topic(
        config["topics"]["model.data"], **config["streaming"]
    )
    replace_data_lists_with_dataframes(model_data)
    return model_data


def read_model_data(db_kwargs, key=None, format="pandas"):
    # Alternative way of reading model data (directly from a file, not from a
    # Kafka topic). Should be merged with get_model_data in the future.
    if db_kwargs["type"] == "file":
        with open(db_kwargs["file_path"]) as file:
            model_data = json.load(file)

    if key is not None:
        return pd.DataFrame(columns=model_data[key][0], data=model_data[key][1:])
    
    if format == 'pandas':
        converter = lambda value: pd.DataFrame(columns=value[0], data=value[1:])
    elif format == 'raw':
        converter = lambda value: value
    
    output = recursively_default_dict()
    list_items = {key: value for key, value in model_data.items() if isinstance(value, list)}
    dict_items = {key: value for key, value in model_data.items() if isinstance(value, dict)}
    other_items = {key: value for key, value in model_data.items() if not isinstance(value, (dict, list))}
    
    for key, value in list_items.items():
        output[key] = converter(value)

    for key, value in dict_items.items():
        for key_, value_ in value.items():
            output[key][key_] = converter(value_)

    for key, value in other_items.items():
        output[key] = value
    
    return output


if __name__ == '__main__':
    from pswamp import load_config
    config = load_config()

    all_model_data = read_model_data(config)
    model_data_subset = read_model_data(config, 'line')
    
    model_data_raw = read_model_data(config, format='raw')
    
