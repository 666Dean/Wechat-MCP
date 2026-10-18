# SPDX-License-Identifier: MIT
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from axr.initialization import empty_initialization

class EmptyInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for file,counts in [('guard.sqlite3',{'policy':1,'grants':0,'security_meta':1}),
            ('journal.sqlite3',{k:0 for k in ('jobs','contexts','events','telemetry','audit_records','results','disclosed_scopes','execution_claims')})]:
            db=sqlite3.connect(self.root/file)
            for name,count in counts.items():
                db.execute('CREATE TABLE '+name+'(value TEXT)')
                if count:db.execute('INSERT INTO '+name+' VALUES(?)',('fixture',))
            db.commit();db.close()
    def test_only_empty_interrupted_first_setup_is_eligible(self):self.assertTrue(empty_initialization(self.root))
    def test_policy_receipt_is_only_a_preliminary_resume_candidate(self):
        (self.root/'policy.sealed.json').write_text('MAC must still be verified by the native authority')
        self.assertTrue(empty_initialization(self.root))
    def test_any_previous_job_grant_or_audit_record_blocks_resume(self):
        for filename,table in [('guard.sqlite3','grants'),('journal.sqlite3','audit_records'),('journal.sqlite3','jobs')]:
            db=sqlite3.connect(self.root/filename);db.execute('INSERT INTO '+table+' VALUES(?)',('fixture',));db.commit()
            self.assertFalse(empty_initialization(self.root));db.execute('DELETE FROM '+table);db.commit();db.close()
    def test_policy_unknown_file_link_or_missing_table_blocks_resume(self):
        for name in ('peer-registry.sealed','security-state.sealed','unexpected'):
            p=self.root/name;p.write_bytes(b'fixture');self.assertFalse(empty_initialization(self.root));p.unlink()
        p=self.root/'guard.sqlite3-wal';p.symlink_to(self.root/'guard.sqlite3');self.assertFalse(empty_initialization(self.root));p.unlink()
        db=sqlite3.connect(self.root/'journal.sqlite3');db.execute('DROP TABLE results');db.close()
        self.assertFalse(empty_initialization(self.root))

class PolicyBudgetTests(unittest.TestCase):
    def test_large_valid_configuration_and_failed_write_preserves_receipt(self):
        from axr.policy import OwnerStore
        from axr.aet import AXRError
        with tempfile.TemporaryDirectory() as temporary:
            store=OwnerStore.__new__(OwnerStore);store.directory=Path(temporary);store.key=b'k'*32
            value={'catalog':'联系人'*70000}
            store.seal_config(value);self.assertEqual(store.config(),value)
            with self.assertRaisesRegex(AXRError,'policy_budget'):store.seal_config({'catalog':'联系人'*200000})
            self.assertEqual(store.config(),value)

class SetupResumeTests(unittest.TestCase):
    def test_authenticated_receipt_finishes_without_another_owner_prompt(self):
        from axr import authority_setup
        from axr.aet import AXRError
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            config={'version':2,'application_module':'axr_applications.fixture','deployment':{'state':'fixture'}}
            (root/'deployment.json').write_text(json.dumps(config))
            backend=Mock();backend.get.side_effect=AXRError('owner_secret_not_provisioned')
            registration=Mock();registration.owner_setup_review.return_value={}
            registration.resume_owner_setup.return_value={'state':'approved-fixture'}
            with patch.object(authority_setup.native,'security_release',True,create=True), \
                patch.object(authority_setup,'AuthoritySecretStore',return_value=backend), \
                patch.object(authority_setup.importlib,'import_module',return_value=registration), \
                patch.object(authority_setup.native,'HardwareSigningKey',return_value=Mock()) as key, \
                patch.object(authority_setup,'authenticate') as password, \
                patch.object(authority_setup,'complete') as complete:
                authority_setup.initialize(root)
                password.assert_not_called();registration.authenticate_owner_setup.assert_not_called()
                registration.initialize_owner.assert_not_called()
                key.assert_called_once_with('Stellaria.AXR.Root.v2')
                self.assertEqual(complete.call_args.args[2],{'state':'approved-fixture'})

    def test_operational_bootstrap_cannot_enter_resume(self):
        from axr import authority_setup
        from axr.aet import AXRError
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'deployment.json').write_text(json.dumps({'version':2,'application_module':'axr_applications.fixture','deployment':{}}))
            with patch.object(authority_setup.native,'security_release',True,create=True), \
                patch.object(authority_setup,'AuthoritySecretStore',return_value=Mock()), \
                patch.object(authority_setup.importlib,'import_module') as registration:
                with self.assertRaisesRegex(AXRError,'already_initialized'):authority_setup.initialize(root)
                registration.assert_not_called()
