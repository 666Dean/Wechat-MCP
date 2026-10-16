# SPDX-License-Identifier: MIT
"""Proposals cannot issue grants or resolve ambiguous contacts on an agent's behalf."""
import unittest
from unittest.mock import patch
import test_axr
from axr.aet import AXRError
from axr_integration.authorization_requests import request,status,list_requests

class AuthorizationProposals(unittest.TestCase):
    def setUp(self):
        self.fixture=test_axr.ServiceTests();self.fixture.setUp();self.s=self.fixture.service
        self.addCleanup(self.fixture.tearDown)
    def test_agent_request_is_encrypted_pending_and_grants_nothing(self):
        before=self.s.guard.version
        with patch.object(self.s.guard,'_issue_owner') as issue:
            result=request(self.s,'Synthetic target','继续处理主人指定的工作请求')
            self.assertFalse(result['authority_granted']);issue.assert_not_called()
        self.assertEqual(self.s.guard.version,before)
        self.assertEqual(status(self.s,result['request_id'])['state'],'AwaitingOwner')
        self.assertEqual(list_requests(self.s)[0]['target'],'Synthetic target')
        payload=self.s.journal.db.execute('SELECT payload FROM authorization_requests').fetchone()[0]
        self.assertNotIn(b'Synthetic target',payload)
    def test_invalid_expired_or_missing_requests_never_become_grants(self):
        for target,reason in [('', 'reason'),('a'*513,'reason'),('person','x'*2001)]:
            with self.assertRaises(AXRError):request(self.s,target,reason)
        with self.assertRaises(AXRError):status(self.s,'missing')
        value=request(self.s,'Synthetic','Synthetic')
        self.s.journal.db.execute('UPDATE authorization_requests SET expires=0')
        with self.assertRaises(AXRError):status(self.s,value['request_id'])
