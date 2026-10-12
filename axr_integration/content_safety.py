# SPDX-License-Identifier: MIT
"""Conservative local masking of explicitly labelled credential values.

This is a bounded disclosure transform, not a complete secret classifier.
Application/account/sender identity checks never use transformed text.
"""
import re

_LABEL=re.compile(r'(?i)(["\']?(?:密码|口令|验证码|助记词|私钥|password|passwd|access_token|refresh_token|api[_ -]?key|secret[_ -]?key)["\']?\s*[:：=]\s*["\']?)([^\r\n,，;；"\']+)')
_BEARER=re.compile(r'(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._~+/-]+)')
_KEY=re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b')
MASK='[敏感值已本地遮盖]'


def mask_credentials(text):
    safe=_LABEL.sub(lambda m:m[1]+MASK,text)
    safe=_BEARER.sub(lambda m:m[1]+MASK,safe)
    safe=_KEY.sub(MASK,safe)
    return safe,safe!=text
