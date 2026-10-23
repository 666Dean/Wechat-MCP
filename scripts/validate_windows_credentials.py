# SPDX-License-Identifier: MIT
"""Qualify formal Windows native binaries without secrets, enrollment or a service.

Imports copied source and the selected binaries in a fresh isolated interpreter.
The synthetic request must fail at the native service identity boundary before
any credential lookup or database open. This is not deployment qualification.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CHECK = r'''
import json, os, sys
from pathlib import Path
root, binary_directory, library = map(Path, sys.argv[1:])
handles = [os.add_dll_directory(str(binary_directory))]
sys.path.insert(0, str(root))
from axr import _axr_native as native
if native.security_release is not True:
    raise RuntimeError('formal_native_required')
from axr_applications import _wechat_credentials as consumer
if hasattr(consumer, 'fixture_consumer'):
    raise RuntimeError('fixture_key_constructor_present')
if Path(native.__file__).parent != root / 'axr':
    raise RuntimeError('selected_native_not_loaded')
if Path(consumer.__file__).parent != root / 'axr_applications':
    raise RuntimeError('selected_consumer_not_loaded')
def refused(operation, expected='protected_service_identity_required'):
    try:
        operation()
    except RuntimeError as error:
        if str(error) == expected:
            return True
        raise
    raise RuntimeError('ordinary_process_accepted_as_authority')
store_denied = refused(lambda: native.ProtectedStore('AXRQualificationNeverUsed'))
resource = {'platform':'wechat', 'account_id':'fixture-self', 'conversation_id':'fixture-peer'}
configuration = {'account_id':'fixture-self', 'resources':[resource],
    'credential_namespace':'AXRQualificationNeverUsed', 'sqlcipher_library':str(library),
    'shards':[{'id':'fixture', 'role':'message', 'path':str(root/'never-created.db'),
               'cipher_profile':'sqlcipher4', 'key_reference':'fixture-key'}]}
instance = consumer.WeChatConsumer('fixture-handler', json.dumps(configuration))
consumer_denied = refused(lambda: native.CredentialConsumer.use(instance,
    json.dumps(resource), 'database.query', json.dumps({'kind':'messages'}), lambda:None))
source_denied = refused(lambda: native.windows_source_readiness('{}'), 'windows_source_protected_authority_required')
source_denied = refused(lambda: native.run_windows_source('{}', '{}', lambda:None), 'windows_source_protected_authority_required') and source_denied
frontend_acl_denied = refused(lambda: native.expose_windows_authority_identity('S-1-5-21-1-2-3-4'), 'windows_frontend_authority_required')
import_denied = refused(lambda: consumer.import_owner_credentials(json.dumps(configuration), '{}'))
import_denied = refused(lambda: consumer.import_legacy_owner_credentials(json.dumps(configuration), 'Stellaria.AXR.FixtureNeverUsed', 'S-1-5-21-1-2-3-4')) and import_denied
print(json.dumps({'formal_native':True, 'fixture_key_constructor_absent':True,
    'ordinary_store_denied':store_denied, 'ordinary_consumer_denied':consumer_denied,
    'ordinary_source_denied':source_denied,
    'ordinary_frontend_acl_change_denied':frontend_acl_denied,
    'ordinary_credential_import_denied':import_denied,
    'credentials_read':False, 'authority_started':False}))
'''


def single_product(directory, pattern):
    found = list(directory.glob(pattern))
    if len(found) != 1 or found[0].is_symlink() or not found[0].is_file():
        raise ValueError('single_regular_native_product_required')
    return found[0]


def validate(build, library):
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12):
        raise ValueError('windows_python312_required')
    project = Path(__file__).resolve().parents[1]
    build, library = Path(build).resolve(strict=True), Path(library).resolve(strict=True)
    native = single_product(build/'AXR/Release', '_axr_native*.pyd')
    consumer = single_product(build/'Release', '_wechat_credentials*.pyd')
    with tempfile.TemporaryDirectory(prefix='axr-formal-credentials-') as directory:
        root = Path(directory)
        shutil.copytree(project/'AXR/axr', root/'axr',
            ignore=lambda directory, names: [name for name in names
                if name == '__pycache__' or not (Path(directory)/name).is_dir() and not name.endswith('.py')])
        (root/'axr_applications').mkdir()
        shutil.copyfile(project/'axr_applications/__init__.py', root/'axr_applications/__init__.py')
        shutil.copyfile(native, root/'axr'/native.name)
        shutil.copyfile(consumer, root/'axr_applications'/consumer.name)
        # -S also excludes editable-install import hooks from the reference SDK.
        result = subprocess.run([sys.executable, '-I', '-S', '-c', CHECK,
            str(root), str(native.parent), str(library)], capture_output=True,
            text=True, encoding='utf8', errors='replace', timeout=30,
            env={key:value for key,value in os.environ.items() if not key.startswith('PYTHON')})
        if result.returncode:
            if 'formal_native_required' in result.stderr:
                raise ValueError('formal_native_required')
            if 'fixture_key_constructor_present' in result.stderr:
                raise ValueError('fixture_key_constructor_present')
            raise ValueError('formal_windows_credential_validation_failed')
        report = json.loads(result.stdout)
        expected = {'formal_native':True, 'fixture_key_constructor_absent':True,
            'ordinary_store_denied':True, 'ordinary_consumer_denied':True,
            'ordinary_source_denied':True,
            'ordinary_frontend_acl_change_denied':True,
            'ordinary_credential_import_denied':True,
            'credentials_read':False, 'authority_started':False}
        if report != expected:
            raise ValueError('formal_windows_credential_validation_failed')
        return report


def build_formal(build, toolchain):
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12):
        raise ValueError('windows_python312_required')
    import pybind11
    project = Path(__file__).resolve().parents[1]
    build, toolchain = Path(build).absolute(), Path(toolchain).resolve(strict=True)
    # Construct Unicode arguments in Python; piping paths through legacy shell
    # encodings can corrupt a Chinese Python or pybind11 installation path.
    subprocess.run(['cmake', '-S', str(project), '-B', str(build),
        '-DAXR_SECURITY_RELEASE=ON', '-DAXR_PYTHON=ON', '-DAXR_AUTHORITY_HOST=ON',
        '-DWECHAT_NATIVE_CREDENTIALS=ON', '-DBUILD_TESTING=OFF',
        '-DPython_EXECUTABLE='+sys.executable, '-Dpybind11_DIR='+pybind11.get_cmake_dir(),
        '-DCMAKE_TOOLCHAIN_FILE='+str(toolchain)], check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release',
        '--target', '_axr_native', '_wechat_credentials', 'axr-authority', 'axr-owner', 'axr-frontend', 'axr-runtime-check', 'wechat-uia', '--parallel', '4'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True)
    parser.add_argument('--library', required=True)
    parser.add_argument('--compile', action='store_true', help='Build formal binaries before validation')
    parser.add_argument('--toolchain', help='vcpkg toolchain required by --compile')
    args = parser.parse_args()
    if args.compile and not args.toolchain:
        parser.error('--compile requires --toolchain')
    try:
        if args.compile:
            build_formal(args.build, args.toolchain)
        print(json.dumps(validate(args.build, args.library)))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(json.dumps({'validation_passed':False, 'error':code}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
