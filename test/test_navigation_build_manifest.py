# SPDX-License-Identifier: MIT
import hashlib,json,tempfile,unittest
from pathlib import Path
from scripts.package_authority_macos import verify_navigation_build,verify_optimized_runtime

class NavigationBuildManifest(unittest.TestCase):
    def test_unoptimized_deployment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp)
            with self.assertRaisesRegex(ValueError,'optimized'):verify_optimized_runtime(build)
            for value in ('','Debug','MinSizeRel','custom'):
                (build/'CMakeCache.txt').write_text('CMAKE_BUILD_TYPE:STRING='+value+'\n')
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'optimized'):verify_optimized_runtime(build)
            for value in ('Release','RelWithDebInfo'):
                (build/'CMakeCache.txt').write_text('CMAKE_BUILD_TYPE:STRING='+value+'\n')
                verify_optimized_runtime(build)
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
