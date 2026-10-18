# SPDX-License-Identifier: AGPL-3.0-only
"""Fixed entry of the native, mandatory OS-sandboxed MCP transport."""
from .authority_owner import registration

def main(runtime_root):
    return registration(runtime_root).frontend_main(runtime_root)
