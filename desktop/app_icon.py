# SPDX-License-Identifier: MIT
"""Render the vector product mark into native macOS icon sizes."""
from pathlib import Path
import struct
from PySide6.QtCore import QRectF,QBuffer,QByteArray,QIODevice
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

def mac_icon(svg,destination):
    renderer=QSvgRenderer(str(svg))
    if not renderer.isValid():raise ValueError('invalid product icon')
    chunks=[]
    for tag,pixels in ((b'icp4',16),(b'icp5',32),(b'icp6',64),(b'ic07',128),(b'ic08',256),(b'ic09',512),(b'ic10',1024)):
        image=QImage(pixels,pixels,QImage.Format_ARGB32_Premultiplied);image.fill(0)
        painter=QPainter(image);renderer.render(painter,QRectF(0,0,pixels,pixels));painter.end()
        data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer,'PNG'):raise ValueError('icon render failed')
        raw=bytes(data);chunks.append(tag+struct.pack('>I',len(raw)+8)+raw)
    payload=b''.join(chunks);Path(destination).write_bytes(b'icns'+struct.pack('>I',len(payload)+8)+payload)
    return Path(destination)
