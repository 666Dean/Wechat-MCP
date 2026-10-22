# SPDX-License-Identifier: MIT
"""CI accepts enumerated native refusals, never arbitrary errors or startup."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


class SecurityHostValidation(unittest.TestCase):
    def validate(self,error,*,started=False,code=1):
        script=Path(__file__).resolve().parents[1]/'scripts/validate_security_host.py'
        response=subprocess.CompletedProcess([],code,'',json.dumps({'authority_started':started,'error':error}))
        with patch('sys.argv',[str(script),'unused-ci-build']),patch('subprocess.run',return_value=response),contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(script),run_name='__main__')
    def test_fixed_installation_refusal_is_an_expected_unprovisioned_host(self):
        self.validate('protected_host_installation_required')
    def test_unknown_failure_does_not_count_as_a_security_refusal(self):
        with self.assertRaises(AssertionError):self.validate('unexpected_runtime_failure')
    def test_startup_or_success_exit_cannot_pass_even_with_an_allowed_error(self):
        for fields in ({'started':True},{'started':0},{'code':0},{'code':2}):
            with self.subTest(fields=fields),self.assertRaises(AssertionError):
                self.validate('protected_host_installation_required',**fields)
