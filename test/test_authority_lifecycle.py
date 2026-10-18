# SPDX-License-Identifier: MIT
"""POSIX shutdown releases server and journal even during an idle accept."""
import os,signal,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr import authority_main

@unittest.skipIf(os.name=='nt','POSIX signal lifecycle; Windows uses SCM')
class AuthorityLifecycle(unittest.TestCase):
    def test_term_closes_application_transport_and_kernel_and_restores_handlers(self):
        from axr.authority_server import AuthorityServer
        previous={s:signal.getsignal(s) for s in (signal.SIGTERM,signal.SIGINT)}
        server=Mock(spec=AuthorityServer);server.kernel=Mock(development_fixture=False)
        server.serve.side_effect=lambda:signal.raise_signal(signal.SIGTERM)
        config={'version':2,'application_module':'axr_applications.fixture','deployment':{}}
        registration=Mock();registration.create_authority.return_value=server
        with patch.object(authority_main.native,'security_release',True,create=True), \
             patch.object(authority_main,'AuthoritySecretStore'), \
             patch.object(authority_main,'Vault',return_value=SimpleNamespace(open=lambda *a:config)), \
             patch.object(authority_main.importlib,'import_module',return_value=registration):
            authority_main.main()
        server.close.assert_called_once();server.kernel.close.assert_called_once()
        self.assertIsNone(authority_main._server)
        self.assertEqual({s:signal.getsignal(s) for s in previous},previous)
