# SPDX-License-Identifier: MIT
"""Relocatable desktop preview entry; no deployment data or implicit enrollment."""
import json
import platform
import sys
from pathlib import Path

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    if sys.platform=='win32' and '--windows-setup-request' in sys.argv:
        from desktop.windows_setup import main as admin_main
        return admin_main()
    if '--runtime-check' in sys.argv:
        import PySide6
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QGuiApplication
        from desktop.fonts import configure
        app=QGuiApplication.instance() or QGuiApplication([])
        from axr import _axr_native as native
        import desktop
        root=Path(desktop.__file__).parent
        value={'version':'0.1.0-dp2','architecture':platform.machine(),'python':platform.python_version(),
               'qt':qVersion(),'pyside':PySide6.__version__,'security_release':getattr(native,'security_release',False),'chinese_glyphs':configure(app),
               'qml':(root/'Main.qml').is_file(),'icon':(root/'icon.svg').is_file(),
               'components':((root.parent/'authority-components/package-review.json').is_file() if sys.platform=='win32' else
                             (root.parent/'authority-payload.tar.gz').is_file()),'canonical':native.wire_canonical('{"check":true}')=='{"check":true}'}
        if sys.platform=='win32':
            # Import frozen routes without UAC, SCM, installed configuration
            # reads, owner authentication or a UIA helper operation.
            from desktop.windows_lifecycle import configure_navigation,admission_request,import_admission
            from scripts.configure_windows_navigation import configure
            from scripts.import_windows_admission import import_material
            from axr_applications.windows_navigation import prepare
            from axr_applications.windows_admission import verify
            value['windows_metadata_entries']=all(callable(f) for f in (
                configure_navigation,admission_request,import_admission,configure,import_material,prepare,verify))
        output=sys.argv[sys.argv.index('--check-output')+1] if '--check-output' in sys.argv else None
        if output:Path(output).write_text(json.dumps(value),encoding='utf-8')
        elif sys.stdout:print(json.dumps(value))
        required=('security_release','qml','icon','canonical','components','chinese_glyphs')+(
            ('windows_metadata_entries',) if sys.platform=='win32' else ())
        return 0 if all(value[k] is True for k in required) else 2
    from desktop.app import main as desktop_main
    desktop_main()

if __name__=='__main__':raise SystemExit(main())
