# SPDX-License-Identifier: MIT
import unittest
from desktop.onboarding import assessment
from axr_applications.send_schedule import readiness

class SetupChecks(unittest.TestCase):
    def test_no_completion_from_ui_flags_or_partial_setup(self):
        status={'operational':True,'owner_authorized':True,'inference':{'ready':True},'permissions':{'database':True,'accessibility':True}}
        assistant={'thread_id':'00000000-0000-4000-8000-000000000001'}
        self.assertFalse(assessment({'status':status},assistant,False)['ready'])
        self.assertFalse(assessment({'status':status},{},True)['ready'])
        self.assertFalse(assessment({'status':{**status,'owner_authorized':False}},assistant,True)['ready'])
        self.assertTrue(assessment({'status':status},assistant,True)['ready'])
    def test_scheduling_never_interprets_unknown_activity_as_idle(self):
        self.assertEqual(readiness('when_idle',15,idle=None),'activity_unavailable')
        self.assertEqual(readiness('when_idle',15,idle=14),'user_active')
        self.assertIsNone(readiness('when_idle',15,idle=16))
        self.assertEqual(readiness('foreground_only',15,idle=16),'wechat_background')
        self.assertIsNone(readiness('foreground_only',15,idle=16,foreground=True))
