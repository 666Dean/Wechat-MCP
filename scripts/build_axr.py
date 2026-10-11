# SPDX-License-Identifier: MIT
"""Build native helpers and thin bindings; no source checkout or secrets are downloaded."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--build',default='.local-private/build')
    parser.add_argument('--openssl');parser.add_argument('--toolchain')
    parser.add_argument('--config',choices=['Debug','Release'],default='Debug')
    parser.add_argument('--mac-selection-probe',action='store_true',help='Compile metadata-only owner picker probe; never run it')
    args=parser.parse_args()
    import pybind11
    root=Path(__file__).resolve().parents[1];build=root/args.build
    command=['cmake','-S',str(root),'-B',str(build),'-DAXR_PYTHON=ON','-DCMAKE_BUILD_TYPE='+args.config,
        '-DPython_EXECUTABLE='+sys.executable,'-Dpybind11_DIR='+pybind11.get_cmake_dir()]
    if args.openssl:command+=['-DOPENSSL_ROOT_DIR='+args.openssl]
    if args.toolchain:command+=['-DCMAKE_TOOLCHAIN_FILE='+args.toolchain]
    if args.mac_selection_probe:
        if sys.platform!='darwin':parser.error('--mac-selection-probe requires macOS')
        command+=['-DAXR_MAC_SELECTION_PROBE=ON']
    subprocess.run(command,check=True);subprocess.run(['cmake','--build',str(build),'--config',args.config,'--parallel','4'],check=True)
    products=list((build/'AXR').rglob('_axr_native*'))
    for p in products:
        if p.suffix in {'.so','.pyd'}:shutil.copy2(p,root/'AXR'/'axr'/p.name)
    subprocess.run(['ctest','--test-dir',str(build/'AXR'),'-C',args.config,'--output-on-failure'],check=True)
if __name__=='__main__':main()
