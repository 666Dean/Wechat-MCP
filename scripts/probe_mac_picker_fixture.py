# SPDX-License-Identifier: MIT
"""Owner-operated picker test ONLY for the separately opened synthetic fixture.

No production OwnerStore, account/keyring access, client launch or real chat.
The request must name the fixed synthetic app and synthetic resource.
"""
import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from axr.aet import Resource
from axr.guard import Guard
from axr.journal import Journal
from axr.owner_window_ocr import capture, read_private_request
from axr.storage import Vault


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--picker', required=True)
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    resource, binding = read_private_request(args.request)
    if (resource != Resource('fixture', 'fixture-account', 'fixture-chat')
            or binding['bundle'] != 'dev.axr.input-fixture'
            or binding['title'] != 'AXR synthetic input fixture'):
        parser.exit(2, 'synthetic_fixture_scope_required\n')
    with tempfile.TemporaryDirectory(prefix='axr-picker-fixture-') as folder:
        directory = Path(folder)
        guard = Guard(directory/'guard.db', b'g'*32)
        journal = Journal(directory/'journal.db', Vault(b'v'*32))
        try:
            result = capture(SimpleNamespace(directory=directory, guard=guard, journal=journal),
                             str(Path(args.picker).resolve(strict=True)), resource, binding, synthetic_control=True)
            print(json.dumps({'synthetic_only': True, **result}), flush=True)
            if result['state'] != 'Completed' or result.get('ocr_lines', 0) < 3:
                raise SystemExit(1)
        finally:
            journal.close(); guard.close()


if __name__ == '__main__':
    main()
