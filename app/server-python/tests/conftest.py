"""Settings every server test shares."""

import os

from pswamp_core.cim.grid import SAMPLE_GRID

# The CIM graph the streamer's frames are tied to: the sample grid, in the process, never
# Nordic44 (downloaded, and minutes to stage). A test that wants another sets its own.
os.environ.setdefault("PSWAMP_CIM_PATH", str(SAMPLE_GRID))
