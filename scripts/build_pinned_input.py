# SPDX-License-Identifier: MIT
"""Explicit developer build. Does not install, approve or run the input adapter."""
import argparse
import hashlib,json
import subprocess
import sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',default='.local-private/build')
    parser.add_argument('--navigation',action='store_true',help='Build the experimental main-window menu search helper instead')
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('experimental input adapter is macOS-only')
    root=Path(__file__).resolve().parents[1]
    build=Path(args.build).resolve(strict=True)
    cache=(build/'CMakeCache.txt').read_text()
    libraries=[line.split('=',1)[1] for line in cache.splitlines()
               if line.startswith('OPENSSL_CRYPTO_LIBRARY:')]
    if len(libraries)!=1:parser.error('build AXR with its explicit OpenSSL dependency first')
    crypto=Path(libraries[0]).resolve(strict=True)
    core=(build/'AXR/libaxr.a').resolve(strict=True)
    source='experimental_chat_navigation.swift' if args.navigation else 'experimental_pinned_input.swift'
    output=build/('wechat-chat-navigation-experimental' if args.navigation else 'wechat-pinned-input-experimental')
    optimized=any(line in ('CMAKE_BUILD_TYPE:STRING=Release','CMAKE_BUILD_TYPE:STRING=RelWithDebInfo') for line in cache.splitlines())
    subprocess.run(['swiftc',*(['-O'] if optimized else []),'-I',str(root/'AXR/native/bridge'),
        str(root/'adapters/macos'/source),
        '-Xlinker',str(core),'-Xlinker',str(crypto),'-lsqlite3','-lc++',
        '-o',str(output)],check=True)
    output.with_suffix('.build.json').write_text(json.dumps({
        'source_sha256':hashlib.sha256((root/'adapters/macos'/source).read_bytes()).hexdigest(),
        'core_sha256':hashlib.sha256(core.read_bytes()).hexdigest(),
        'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()},sort_keys=True))
    print('Experimental adapter compiled; not installed or enabled.')


if __name__=='__main__':main()
