# SPDX-License-Identifier: MIT
"""Early CI smoke for NT handle boundaries; requires only the Python stdlib."""
import importlib,json,subprocess,sys,tempfile,types
from pathlib import Path
if sys.platform!='win32':raise SystemExit('Windows validation only')
# Load just the stdlib-only file boundary, before the C++ wheel is built. No
# production package, authority, secret store or application state is loaded.
package=types.ModuleType('axr_path_probe');package.__path__=[str(Path(__file__).resolve().parents[1]/'AXR/axr')]
sys.modules[package.__name__]=package
rooted=importlib.import_module('axr_path_probe.rooted');error=importlib.import_module('axr_path_probe.aet').AXRError
with tempfile.TemporaryDirectory(prefix='axr-path-probe-') as temporary:
    base=Path(temporary);area=base/'area';outside=base/'outside';area.mkdir();outside.mkdir()
    (area/'文件.txt').write_bytes(b'fixture');(outside/'private.txt').write_bytes(b'private fixture')
    directory=rooted.RootedDirectory(area)
    try:
        assert directory.read('文件.txt',100)==b'fixture'
        with directory.parent('文件.txt') as (parent,name):directory.replace_at(parent,name,b'changed',lambda:None)
        assert directory.read('文件.txt',100)==b'changed'
        result=subprocess.run(['cmd','/c','mklink','/J',str(area/'link'),str(outside)],capture_output=True)
        assert result.returncode==0,'junction fixture creation failed'
        try:directory.read('link/private.txt',100)
        except error:pass
        else:raise AssertionError('reparse traversal was allowed')
    finally:directory.close()
    assert (outside/'private.txt').read_bytes()==b'private fixture'
print(json.dumps({'relative_read':True,'atomic_replace':True,'reparse_denied':True}))
