# SPDX-License-Identifier: MIT
"""Content-free public macOS activity checks; never capture input events."""
import ctypes
import math
import sys

def idle_seconds():
    if sys.platform!='darwin':return None
    try:
        framework=ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        fn=framework.CGEventSourceSecondsSinceLastEventType
        fn.argtypes=[ctypes.c_int32,ctypes.c_uint32];fn.restype=ctypes.c_double
        value=fn(1,0xffffffff)  # HID system state, any input; no event contents.
        return value if math.isfinite(value) and 0<=value<365*86400 else None
    except (OSError,AttributeError):return None

def readiness(policy,threshold,*,idle,foreground=False):
    if policy=='immediate':return None
    if idle is None:return 'activity_unavailable'
    if idle<threshold:return 'user_active'
    if policy=='foreground_only' and not foreground:return 'wechat_background'
    return None
