# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The pipeline declarations: one file per app, each exporting ``PIPELINE``.

A worker hosts an app's modules with
``PSWAMP_WORKER_PIPELINES=pswamp_modules.pipelines.<app>:PIPELINE``.

Transitional: a portion of the ``pswamp_modules`` namespace in
``legacy/pswamp-wiring/``, until pipelines become TOML files (see its README).
"""
