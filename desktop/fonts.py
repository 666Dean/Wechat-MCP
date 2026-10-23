# SPDX-License-Identifier: MIT
"""Use OS fonts for native and offscreen rendering; never redistribute them."""
import sys
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase,QRawFont

def configure(app):
    if sys.platform=='win32' and app.platformName()=='offscreen':
        # The offscreen plugin does not use Windows' native font discovery;
        # scanning TTC files alone also misses their second UI family.
        import ctypes
        buffer=ctypes.create_unicode_buffer(32768)
        size=ctypes.windll.kernel32.GetSystemDirectoryW(buffer,len(buffer))
        if not 0<size<len(buffer):return False
        directory=Path(buffer.value).parent/'Fonts'
        for name in ('msyh.ttc','msyhbd.ttc','msyhl.ttc','segoeui.ttf'):
            path=directory/name
            if path.is_file():QFontDatabase.addApplicationFont(str(path))
    font=QFont('Microsoft YaHei UI' if sys.platform=='win32' else 'PingFang SC')
    app.setFont(font)
    return QRawFont.fromFont(font).supportsCharacter('微')
