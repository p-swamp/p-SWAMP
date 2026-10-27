# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The wire between the web backend and a browser, and the socket plumbing every page uses.

What is left of the p-SWAMP web layer now that the grid monitor runs on the live grid
(``grid_monitor/``) rather than on a recording replayed through the desktop package's
applications: the message shapes the web client's types are generated from (``wire``), serving
a downstream socket (``pump``), a client's open views (``sessions``), logging (``log``) and the
alarm list's state machine (``stores``). It imports nothing from the rest of the web backend,
which imports it (``shared.py`` re-exports what the app packages use); every import between its
own modules is relative.
"""
