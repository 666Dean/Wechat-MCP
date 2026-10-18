# SPDX-License-Identifier: MIT
import hashlib,json,tempfile,unittest
from pathlib import Path
from scripts.package_authority_macos import verify_navigation_build

class NavigationBuildManifest(unittest.TestCase):
    def test_missing_or_stale_build_is_rejected_before_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);build=root/'build';(build/'AXR').mkdir(parents=True)
            source=root/'adapters/macos/experimental_chat_navigation.swift';source.parent.mkdir(parents=True)
            source.write_bytes(b'reviewed source');(build/'AXR/libaxr.a').write_bytes(b'reviewed core')
            output=build/'wechat-chat-navigation-experimental';output.write_bytes(b'compiled helper fixture')
            with self.assertRaisesRegex(ValueError,'rebuilt'):verify_navigation_build(root,build)
            files={'source_sha256':source,'core_sha256':build/'AXR/libaxr.a','output_sha256':output}
            manifest={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in files.items()}
            output.with_suffix('.build.json').write_text(json.dumps(manifest))
            self.assertEqual(verify_navigation_build(root,build),output)
            for key,path in files.items():
                with self.subTest(key=key):
                    original=path.read_bytes();path.write_bytes(b'changed')
                    with self.assertRaisesRegex(ValueError,'rebuilt'):verify_navigation_build(root,build)
                    path.write_bytes(original)
