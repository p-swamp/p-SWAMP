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

import os
import __main__
from pathlib import Path


def python_is_interactive():
    if not hasattr(__main__, "__file__"):
        return True
    if r"ipython\code.py" in __file__:
        return True
    return False


global project_dir
project_dir = None

def fix_paths_if_interactive(this_file):
    global project_dir
    if project_dir is None:
        project_dir = Path(os.getcwd())
    os.chdir(project_dir/this_file)
