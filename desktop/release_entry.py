# SPDX-License-Identifier: MIT
"""Relocatable macOS preview entry; no deployment data or implicit enrollment."""
import json
import platform
import sys
from pathlib import Path

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    if '--runtime-check' in sys.argv:
        import PySide6
        from PySide6.QtCore import qVersion
        from axr import _axr_native as native
        import desktop
        root=Path(desktop.__file__).parent
        value={'version':'0.1.0-dp2','architecture':platform.machine(),'python':platform.python_version(),
               'qt':qVersion(),'pyside':PySide6.__version__,'security_release':getattr(native,'security_release',False),
               'qml':(root/'Main.qml').is_file(),'icon':(root/'icon.svg').is_file(),
               'components':(root.parent/'authority-payload.tar.gz').is_file(),'canonical':native.wire_canonical('{"check":true}')=='{"check":true}'}
        output=sys.argv[sys.argv.index('--check-output')+1] if '--check-output' in sys.argv else None
        if output:Path(output).write_text(json.dumps(value),encoding='utf-8')
        elif sys.stdout:print(json.dumps(value))
        return 0 if all(value[k] is True for k in ('security_release','qml','icon','canonical','components')) else 2
    from desktop.app import main as desktop_main
    desktop_main()

if __name__=='__main__':raise SystemExit(main())
