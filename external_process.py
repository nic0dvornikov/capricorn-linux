"""Restore the host library environment for programs outside the frozen bundle."""
import os
import sys


def external_env():
    env = os.environ.copy()
    if sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
        original = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if original:
            env['LD_LIBRARY_PATH'] = original
        else:
            env.pop('LD_LIBRARY_PATH', None)
        for name in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
            env.pop(name, None)
    return env
