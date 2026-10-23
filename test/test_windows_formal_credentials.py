# SPDX-License-Identifier: MIT
"""Real Windows binaries: formal denial and reference/mixed-build rejection."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from scripts.validate_windows_credentials import single_product, validate


@unittest.skipUnless(sys.platform == 'win32', 'Windows formal credential boundary')
class WindowsFormalCredentials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        formal = os.environ.get('WECHAT_TEST_FORMAL_BUILD')
        reference = os.environ.get('WECHAT_TEST_REFERENCE_BUILD')
        library = os.environ.get('AXR_SQLCIPHER_LIBRARY')
        if not formal or not reference or not library:
            raise unittest.SkipTest('explicit formal/reference Windows native builds required')
        cls.formal, cls.reference, cls.library = Path(formal), Path(reference), library

    def test_formal_binaries_refuse_ordinary_process_without_secret_lookup(self):
        report = validate(self.formal, self.library)
        self.assertTrue(report['formal_native'])
        self.assertTrue(report['fixture_key_constructor_absent'])
        self.assertTrue(report['ordinary_store_denied'])
        self.assertTrue(report['ordinary_consumer_denied'])
        self.assertTrue(report['ordinary_source_denied'])
        self.assertFalse(report['credentials_read'])
        self.assertFalse(report['authority_started'])

    def test_reference_sdk_cannot_pass_formal_qualification(self):
        with self.assertRaisesRegex(ValueError, '^formal_native_required$'):
            validate(self.reference, self.library)

    def test_formal_sdk_with_reference_consumer_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='axr-mixed-credentials-') as directory:
            build = Path(directory)
            sdk, application = build/'AXR/Release', build/'Release'
            sdk.mkdir(parents=True)
            application.mkdir()
            source = self.formal/'AXR/Release'
            native = single_product(source, '_axr_native*.pyd')
            shutil.copyfile(native, sdk/native.name)
            for library in source.glob('*.dll'):
                shutil.copyfile(library, sdk/library.name)
            consumer = single_product(self.reference/'Release', '_wechat_credentials*.pyd')
            shutil.copyfile(consumer, application/consumer.name)
            with self.assertRaisesRegex(ValueError, '^fixture_key_constructor_present$'):
                validate(build, self.library)
