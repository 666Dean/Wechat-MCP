# SPDX-License-Identifier: MIT
import hashlib
import tempfile
import unittest
from pathlib import Path
from scripts.package_windows_runtime import package, HELPERS, DEPENDENCIES


class RuntimePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wheels, self.build, self.deps, self.output = [self.root / n for n in ('wheels','build','deps','output')]
        paths = [self.wheels / 'stellaria_axr-1.0.0.dev1-cp312-cp312-win_amd64.whl',
                 self.build / 'Release' / 'wechat-uia.exe']
        paths += [self.build / 'AXR' / 'Release' / name for name in HELPERS]
        paths += [self.deps / 'bin' / name for name in ('libcrypto-3-x64.dll','sqlite3.dll','sqlcipher.dll')]
        paths += [self.deps / 'share' / name / 'copyright' for name in DEPENDENCIES]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic build fixture')

    def pack(self):
        return package(self.wheels, self.build, self.deps, self.output, 'a'*40, 'fixture/repository')

    def test_allowlist_excludes_owner_data_and_manifest_matches_every_product(self):
        (self.build / 'owner.db').write_bytes(b'synthetic private state')
        (self.wheels / 'policy.sealed.json').write_bytes(b'synthetic private configuration')
        manifest = self.pack()
        self.assertEqual(manifest['security_profile'],'reference')
        self.assertFalse(manifest['security2_release_qualified'])
        self.assertFalse(manifest['owner_state_included'])
        self.assertFalse(manifest['configuration_included'])
        self.assertNotIn('owner.db', manifest['files'])
        self.assertNotIn('policy.sealed.json', manifest['files'])
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), expected)
        self.assertIn('licenses/AXR-AGPL-3.0.txt', manifest['files'])

    def test_missing_required_product_fails_before_output_and_stale_output_is_rejected(self):
        helper = self.build / 'AXR' / 'Release' / HELPERS[0]
        helper.unlink()
        with self.assertRaisesRegex(ValueError, 'required_regular'):
            self.pack()
        self.assertFalse(self.output.exists())
        helper.write_bytes(b'synthetic build fixture')
        self.pack()
        with self.assertRaisesRegex(ValueError, 'output_must_be_empty'):
            self.pack()

    def test_wrong_platform_wheel_or_unbound_revision_is_rejected(self):
        wheel = next(self.wheels.glob('*.whl'))
        wheel.rename(self.wheels / 'stellaria_axr-1.0.0-cp314-cp314-win_amd64.whl')
        with self.assertRaisesRegex(ValueError, 'python312_windows'):
            self.pack()
        with self.assertRaisesRegex(ValueError, 'source_identity'):
            package(self.wheels, self.build, self.deps, self.output, 'main', 'fixture/repository')


if __name__ == '__main__':
    unittest.main()
