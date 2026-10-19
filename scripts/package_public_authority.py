# SPDX-License-Identifier: MIT
"""Create signed account-free components for the desktop first-run installer."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from .package_authority_macos import stage

def build(root,build_dir,output,identity,cipher):
    output=Path(output).absolute()
    stage(root,build_dir,output,{'application':{'sqlcipher_library':str(cipher),'navigation_helper':'@resources/bin/wechat-navigation'}},identity=identity,public=True)
    # No runtime-check app, account config, third-party Codex App or deployment
    # data belongs in the public install payload.
    from desktop.provisioning import BUNDLES
    from axr.deployment_configuration import MARKER
    for name in BUNDLES:
        resources=output/name/'Contents/Resources'
        if json.loads((resources/'deployment.json').read_bytes())!=MARKER:raise RuntimeError('public_deployment_marker_required')
        if (resources/'CodexCLI.app').exists():raise RuntimeError('vendor_runtime_redistribution_denied')
        for source in (root/'AXR/licenses').iterdir():
            if source.is_file():(resources/'licenses'/source.name).write_bytes(source.read_bytes())
        # Adding notices changes the resource seal; sign the outer bundle once
        # more while preserving the same hardened executable signatures.
        from .package_authority_macos import command
        command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none',output/name])
        command(['/usr/bin/codesign','--verify','--deep','--strict',output/name])
    inventory={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
               for name in BUNDLES for p in (output/name).rglob('*') if p.is_file()}
    manifest={'version':2,'files':inventory,'public_components':True,'account_data_included':False,'vendor_codex_binary_included':False}
    (output/'package-review.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=output.parent/(output.name+'.tar.gz')
    def public_metadata(entry):
        entry.uid=entry.gid=0;entry.uname=entry.gname='';entry.mtime=0
        return entry
    with tarfile.open(archive,'w:gz') as tar:
        for name in (*BUNDLES,'package-review.json'):tar.add(output/name,arcname=name,recursive=True,filter=public_metadata)
    (archive.with_suffix('.json')).write_text(json.dumps({'version':1,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n')
    return archive

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--identity',required=True);p.add_argument('--cipher',type=Path,required=True)
    a=p.parse_args();print(build(Path(__file__).resolve().parents[1],a.build.resolve(),a.output,a.identity,a.cipher.resolve()))

if __name__=='__main__':main()
