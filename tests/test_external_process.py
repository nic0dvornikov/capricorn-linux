import os
import sys
import subprocess
import unittest
from unittest.mock import patch
from external_process import external_env
from linux_actions import LinuxActions

class ExternalTests(unittest.TestCase):
    def test_frozen_restores_host_environment_without_mutating_parent(self):
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, {'LD_LIBRARY_PATH':'/bundle','LD_LIBRARY_PATH_ORIG':'/host','QT_PLUGIN_PATH':'/bundle/qt'}, clear=True):
            env=external_env()
            self.assertEqual(env['LD_LIBRARY_PATH'], '/host')
            self.assertNotIn('QT_PLUGIN_PATH', env)
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], '/bundle')
    def test_frozen_removes_unset_original(self):
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, {'LD_LIBRARY_PATH':'/bundle'}, clear=True):
            self.assertNotIn('LD_LIBRARY_PATH', external_env())
    def test_source_keeps_host_environment(self):
        with patch.object(sys, 'frozen', False, create=True), patch.dict(os.environ, {'LD_LIBRARY_PATH':'/host'}, clear=True):
            self.assertEqual(external_env()['LD_LIBRARY_PATH'], '/host')
    def test_youtube_failure_is_not_reported_as_success(self):
        with patch('linux_actions.shutil.which', return_value='/usr/bin/xdg-open'), patch('linux_actions.subprocess.run', return_value=subprocess.CompletedProcess([],4,'','test error')) as run:
            with self.assertLogs('capri', level='ERROR'):
                reply=LinuxActions().handle('открой ютуб')
            self.assertIn('Не получилось',reply)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/xdg-open','https://www.youtube.com'])
