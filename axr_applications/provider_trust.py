# SPDX-License-Identifier: MIT
"""Owner-setup TLS trust material for the fixed source provider.

Only public certificates are materialized. This is never an MCP credential or
network endpoint API. The authority seals the returned digest in its policy.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
from axr.aet import AXRError
from axr import _axr_native as native

def prepare_public_ca_bundle(destination):
    path=Path(destination)
    if path.exists() or path.is_symlink():raise AXRError('source_tls_new_destination_required')
    if sys.platform=='win32':
        try:parts=[native.windows_public_ca_bundle().encode('ascii')]
        except (RuntimeError,UnicodeError):raise AXRError('source_tls_public_certificates_unavailable') from None
    elif sys.platform=='darwin':
        parts=[Path('/etc/ssl/cert.pem').read_bytes()]
        for store in ('/Library/Keychains/System.keychain','/System/Library/Keychains/SystemRootCertificates.keychain'):
            result=subprocess.run(['/usr/bin/security','find-certificate','-a','-p',store],
                capture_output=True,timeout=15,check=False)
            if result.returncode or len(result.stdout)>1024*1024:raise AXRError('source_tls_public_certificates_unavailable')
            parts.append(result.stdout)
    else:raise AXRError('source_tls_platform_unqualified')
    data=b'\n'.join(parts)
    if len(data)>2*1024*1024 or b'PRIVATE KEY' in data or b'BEGIN CERTIFICATE' not in data:
        raise AXRError('source_tls_certificate_bundle_invalid')
    if not native.durable_write(str(path),data):raise AXRError('source_tls_bundle_write_failed')
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'private_keys_exported':False}
