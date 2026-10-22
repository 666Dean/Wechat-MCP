# SPDX-License-Identifier: MIT
"""First-run packaging/metadata and protected configuration rejection tests."""
import io
import hashlib
import json
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from axr.aet import AXRError
from desktop.provisioning import account_inventory,unpack_payload,regular,fingerprint,native_provider
from axr.deployment_configuration import path as configuration_path,MARKER

class FirstRunDeployment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
    def data(self):
        root=self.root/'wxid_fixture_owner_install/db_storage'
        for name in ('contact/contact.db','session/session.db','general/general.db','message/message_0.db'):
            file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'1'*4096)
        return root
    def test_exact_account_metadata_and_generation_pins(self):
        root=self.data();rows=account_inventory(root,'wxid_fixture_owner')
        self.assertEqual({r['role'] for r in rows},{'contact','session','general','message'})
        self.assertTrue(all(len(r['salt'])==32 and r['key_reference'].startswith('wcdb:') for r in rows))
        with self.assertRaisesRegex(AXRError,'folder_mismatch'):account_inventory(root,'wxid_other')
        (root/'contact/contact.db').write_bytes(b'SQLite format 3\0'+b'0'*4080)
        with self.assertRaisesRegex(AXRError,'format_unqualified'):account_inventory(root,'wxid_fixture_owner')
    def test_links_and_missing_shards_never_become_usable_data(self):
        root=self.data();(root/'session/session.db').unlink();(root/'session/session.db').symlink_to(root/'contact/contact.db')
        with self.assertRaisesRegex(AXRError,'redirected'):account_inventory(root,'wxid_fixture_owner')
        with self.assertRaisesRegex(AXRError,'file_invalid'):regular(self.root,100)
    def test_credential_fingerprint_does_not_parse_or_return_key(self):
        source=self.root/'selected.txt';source.write_bytes(b'a'*64)
        result=fingerprint(source,65536)
        self.assertEqual(result,'ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb')
    @unittest.skipUnless(sys.platform=='win32','Windows native hash utility')
    def test_windows_fingerprint_handles_literal_paths_and_rejects_ambiguous_hashes(self):
        source=self.root/'selected $literal ; 中文.txt';source.write_bytes(b'synthetic credential bytes')
        self.assertEqual(fingerprint(source,65536),hashlib.sha256(source.read_bytes()).hexdigest())
        from subprocess import CompletedProcess
        with patch('desktop.provisioning.subprocess.run',return_value=CompletedProcess([],0,b'a'*64+b'\n'+b'b'*64+b'\n')):
            with self.assertRaisesRegex(AXRError,'hash_result_invalid'):fingerprint(source,65536)
    def test_codex_symlink_resolves_to_a_verified_self_contained_image(self):
        import subprocess
        image=self.root/'native-codex';image.write_bytes(b'signed image fixture')
        launcher=self.root/'codex';launcher.symlink_to(image)
        def run(args,**kwargs):
            return subprocess.CompletedProcess(args,0,str(image)+':\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n' if args[0].endswith('otool') else '','')
        with patch('desktop.provisioning.subprocess.run',side_effect=run):
            self.assertEqual(native_provider(launcher),image)
    def test_codex_wrappers_and_external_library_dependencies_are_not_deployed(self):
        import subprocess
        image=self.root/'codex';image.write_bytes(b'#!/usr/bin/env node\n')
        def run(args,**kwargs):
            if args[0].endswith('codesign'):raise subprocess.CalledProcessError(1,args)
            raise AssertionError('unsigned wrapper must not reach dependency inspection')
        with patch('desktop.provisioning.subprocess.run',side_effect=run):
            with self.assertRaisesRegex(AXRError,'runtime_not_self_contained'):native_provider(image)
        def external(args,**kwargs):
            return subprocess.CompletedProcess(args,0,'codex:\n\t/opt/homebrew/lib/libexample.dylib (compatibility version 1.0.0)\n' if args[0].endswith('otool') else '','')
        with patch('desktop.provisioning.subprocess.run',side_effect=external):
            with self.assertRaisesRegex(AXRError,'runtime_not_self_contained'):native_provider(image)
    def test_archive_cannot_escape_or_introduce_links(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('AXR Authority.app/link',tarfile.SYMTYPE),('CodexCLI.app/vendor',tarfile.REGTYPE)]:
            with self.subTest(name=name):
                archive=self.root/('payload-'+str(len(name))+'.tar.gz')
                with tarfile.open(archive,'w:gz') as t:
                    item=tarfile.TarInfo(name);item.type=kind;item.size=0;t.addfile(item,io.BytesIO(b''))
                with self.assertRaisesRegex(AXRError,'components_path_invalid'):unpack_payload(archive,self.root/('out-'+str(len(name))))
        self.assertFalse((self.root/'escape').exists())
    def test_signed_inline_configuration_remains_compatible(self):
        root=self.root/'runtime';root.mkdir();file=root/'deployment.json';file.write_text('{"version":2}')
        self.assertEqual(configuration_path(root),file)
        file.unlink();file.symlink_to(self.root/'elsewhere')
        with self.assertRaisesRegex(AXRError,'configuration_invalid'):configuration_path(root)
    @unittest.skipUnless(sys.platform=='darwin','macOS root-owned sidecar configuration')
    def test_external_configuration_requires_protected_ownership(self):
        root=self.root/'install/Authority.app/Contents/Resources';root.mkdir(parents=True)
        (root/'deployment.json').write_text(json.dumps(MARKER))
        target=self.root/'install/deployment.json';target.write_text('{}')
        with self.assertRaisesRegex(AXRError,'not_protected'):configuration_path(root)
        (root/'deployment.json').write_text(json.dumps({**MARKER,'deployment_source':'/tmp/untrusted'}))
        with self.assertRaisesRegex(AXRError,'configuration_invalid'):configuration_path(root)
    def test_codex_setup_requires_the_actual_enabled_native_section(self):
        from desktop.codex_config import native_registered,native_snippet
        file=self.root/'config.toml'
        self.assertFalse(native_registered(file))
        file.write_text(native_snippet());self.assertTrue(native_registered(file))
        file.write_text(native_snippet().replace('enabled = true','enabled = false'));self.assertFalse(native_registered(file))
        file.write_text(native_snippet().replace('--mcp','--something-else'));self.assertFalse(native_registered(file))
        file.write_text('[invalid');self.assertFalse(native_registered(file))
    @unittest.skipUnless(sys.platform=='darwin','macOS bundle installer and permission script')
    def test_public_install_keeps_configuration_private_and_public_runtime_readable(self):
        from scripts import install_authority_macos as installer
        package=self.root/'components';manifest={}
        for name in installer.BUNDLES:
            file=package/name/'Contents/Resources/deployment.json';file.parent.mkdir(parents=True)
            file.write_text(json.dumps(MARKER));manifest[str(file.relative_to(package))]=hashlib.sha256(file.read_bytes()).hexdigest()
        (package/'package-review.json').write_text(json.dumps({'files':manifest}))
        binary=self.root/'local-codex';binary.write_bytes(b'synthetic signed runtime')
        ca=self.root/'public-ca.pem';ca.write_bytes(b'synthetic public trust');ca.chmod(0o600)
        provider={'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'tls_sha256':hashlib.sha256(ca.read_bytes()).hexdigest()}
        config={'version':2,'application_module':'axr_applications.wechat','deployment':{'application':{'codex_provider':provider}}}
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return __import__('subprocess').CompletedProcess(args,0,'','')
        with patch.object(installer,'BASE',self.root/'protected-install'),patch.object(installer.subprocess,'run',side_effect=run),patch('axr.platform.macos_application.register_bundle'):
            result=installer.install(package,configuration=config,local_assets={'codex':binary,'ca':ca})
        self.assertTrue(result['installed']);self.assertFalse(result['owner_enrolled']);self.assertFalse(result['wechat_authorized'])
        request=next(args[2] for args in calls if args[0]=='/usr/bin/osascript')
        self.assertIn('umask 077',request);self.assertIn(' allow read',request)
        self.assertIn('/bin/chmod 644',request);self.assertIn('/bin/chmod 755',request)
        self.assertNotIn('codesign --force',request)
