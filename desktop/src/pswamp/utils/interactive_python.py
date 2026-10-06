# SPDX-License-Identifier: Apache-2.0
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
