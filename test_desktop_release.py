# SPDX-License-Identifier: MIT
"""Frozen desktop cannot recursively launch itself as a Python interpreter."""
import os
import sys
import unittest
from unittest.mock import patch
try:
    from desktop.app import Controller,call
    from PySide6.QtWidgets import QApplication
    from axr.aet import AXRError
except ModuleNotFoundError:raise unittest.SkipTest('optional desktop runtime')

class PreviewBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])
    def test_unconfigured_frozen_client_does_not_use_legacy_transport(self):
        with patch.object(sys,'frozen',True,create=True),patch('desktop.app.authority_installed',return_value=False),patch('desktop.app.legacy_call') as legacy:
            with self.assertRaisesRegex(AXRError,'setup_service_required'):call('/unused','status')
        legacy.assert_not_called()
    def test_frozen_start_cannot_spawn_a_second_desktop_as_broker(self):
        c=Controller('/unused-fixture',fixture=True);c.timer.stop();c.fixture=False
        try:
            with patch.object(sys,'frozen',True,create=True),patch('desktop.app.authority_installed',return_value=False),patch.object(c,'run',side_effect=lambda _,fn:fn()),patch('desktop.app.subprocess.Popen') as process:
                with self.assertRaisesRegex(AXRError,'setup_service_required'):c.start()
            process.assert_not_called()
        finally:c.fixture=True;c.close()
