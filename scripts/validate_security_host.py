# SPDX-License-Identifier: MIT
"""CI verifies the unsigned/unprovisioned host cannot start an authority."""
import json,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);binary=root/('Release/axr-authority.exe' if sys.platform=='win32' else 'axr-authority')
r=subprocess.run([str(binary),'--serve'],capture_output=True,text=True,timeout=10)
assert r.returncode==1,(r.returncode,'host must refuse an unprovisioned CI deployment')
v=json.loads(r.stderr)
assert v.get('authority_started') is False
assert v.get('error') in {'protected_keychain_group_not_configured','protected_service_identity_required','authority_installed_identity_required','authority_installation_not_protected'},v
print('native authority refuses an unprovisioned development process')
