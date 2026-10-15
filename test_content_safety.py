# SPDX-License-Identifier: MIT
import unittest
from axr_integration.content_safety import mask_credentials,MASK


class CredentialMasking(unittest.TestCase):
    def test_explicit_credentials_json_and_auth_header_are_masked(self):
        text='账号：fixture-account\n密码：fixture-password\n验证码=123456\n"access_token":"fixture-token"\nAuthorization: Bearer fixture.bearer.value\nAPI key: fixture-key'
        safe,masked=mask_credentials(text)
        self.assertTrue(masked);self.assertIn('账号：fixture-account',safe)
        for secret in ('fixture-password','123456','fixture-token','fixture.bearer.value','fixture-key'):
            self.assertNotIn(secret,safe)
        self.assertIn(MASK,safe)
        self.assertEqual(mask_credentials(safe),(safe,False))

    def test_ordinary_password_discussion_and_identity_are_preserved(self):
        text='请检查密码安全；讨论password策略。微信ID fixture-id，周五18:30开会。'
        self.assertEqual(mask_credentials(text),(text,False))

    def test_mnemonic_and_long_key_not_copied_to_model_context(self):
        safe,masked=mask_credentials('助记词：one two three four five six\nsk-proj-'+'x'*32)
        self.assertTrue(masked);self.assertNotIn('one two',safe);self.assertNotIn('x'*32,safe)
