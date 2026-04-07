# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 
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
# Copyright Contributors to the p-SWAMP Project.

import json
import pickle


def encoder(msg):
    if isinstance(msg, dict):
        try:
            return json.dumps(msg).encode("utf8")
        except TypeError:
            pass
    return json.dumps({"__bytes__": pickle.dumps(msg).decode("latin")}).encode("utf8")


def decoder(msg):
    msg_decoded = json.loads(msg)
    if "__bytes__" in msg_decoded:
        return pickle.loads(msg_decoded["__bytes__"].encode("latin"))
    return msg_decoded
