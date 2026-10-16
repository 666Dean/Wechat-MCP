# SPDX-License-Identifier: MIT
"""Package CI-tested Windows reference products only; no owner state or configuration."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

HELPERS = ('axr-owner-auth.exe', 'axr-sandbox.exe', 'axr-worker-probe.exe', 'axr-core-tests.exe')
DEPENDENCIES = ('openssl', 'sqlite3', 'sqlcipher', 'nlohmann-json')


def package(wheels, build, dependencies, output, revision, repository):
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        raise ValueError('source_identity_required')
    wheels, build, dependencies, output = map(Path, (wheels, build, dependencies, output))
    wheel = list(wheels.glob('stellaria_axr-*-cp312-cp312-win_amd64.whl'))
    if len(wheel) != 1:
        raise ValueError('single_python312_windows_sdk_wheel_required')
    sources = [(wheel[0], Path('wheels') / wheel[0].name)]
    sources += [(build / 'AXR' / 'Release' / name, Path('bin') / name) for name in HELPERS]
    sources.append((build / 'Release' / 'wechat-uia.exe', Path('bin/wechat-uia.exe')))
    crypto = list((dependencies / 'bin').glob('libcrypto*.dll'))
    if len(crypto) != 1:
        raise ValueError('single_openssl_crypto_runtime_required')
    sources += [(path, Path('bin') / path.name) for path in crypto]
    sources += [(dependencies / 'bin' / name, Path('bin') / name) for name in ('sqlite3.dll', 'sqlcipher.dll')]
    sources += [(dependencies / 'share' / name / 'copyright', Path('licenses') / (name + '.txt'))
                for name in DEPENDENCIES]
    root = Path(__file__).resolve().parents[1]
    sources += [(root / name, Path('licenses') / name) for name in ('LICENSE', 'LICENSES.md', 'THIRD_PARTY_NOTICES.md')]
    sources.append((root / 'AXR' / 'LICENSE', Path('licenses/AXR-AGPL-3.0.txt')))
    if output.exists() and any(output.iterdir()):
        raise ValueError('output_must_be_empty')
    # Validate every source before writing any deployable file.
    for source, _ in sources:
        if source.is_symlink() or not source.is_file():
            raise ValueError('required_regular_runtime_product_missing')
    files = {}
    for source, relative in sources:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {'version':1, 'platform':'windows-x64', 'python':'3.12', 'revision':revision,
                'source':'https://github.com/' + repository + '/tree/' + revision,
                'files':files, 'security_profile':'reference', 'security2_release_qualified':False,
                'owner_state_included':False, 'configuration_included':False}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('wheels', 'build', 'dependencies', 'output', 'revision', 'repository'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    manifest = package(**vars(args))
    print(json.dumps({'packaged_files':len(manifest['files']), 'revision':manifest['revision']}))


if __name__ == '__main__':
    main()
