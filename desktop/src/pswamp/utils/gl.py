# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

def set_gl_options(config, pl):
    """Set graphics options from config.

    Args:
        config (dict): pswamp Configuration file (from config.toml)
        pl (GLGraphicsItem): Plot item for which to set options.
    """
    if 'graphics' in config and 'gl_mode' in config['graphics']:
        pl.setGLOptions(config['graphics']['gl_mode'])
