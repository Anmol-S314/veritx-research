"""Exclusive file locking for local Windows and POSIX stores.

Callers own the descriptor and must not nest locks on the same file. Product
storage handles reentrancy before reaching this boundary.
"""
from __future__ import annotations

import os

if os.name != "nt":
    import fcntl


def _windows_lock(fd: int, *, release: bool) -> None:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = msvcrt.get_osfhandle(fd)
    region = Overlapped()  # lock byte zero, independent of file position
    if release:
        function = kernel.UnlockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(Overlapped)]
        arguments = (handle, 0, 1, 0, ctypes.byref(region))
    else:
        function = kernel.LockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        # Synchronous file handle, exclusive lock, no FAIL_IMMEDIATELY:
        # wait for contention like flock, with no CRT finite retry budget.
        arguments = (handle, 0x2, 0, 1, 0, ctypes.byref(region))
    function.restype = wintypes.BOOL
    if not function(*arguments):
        raise ctypes.WinError(ctypes.get_last_error())


def lock_exclusive(fd: int) -> None:
    if os.name == "nt":
        _windows_lock(fd, release=False)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def unlock(fd: int) -> None:
    if os.name == "nt":
        _windows_lock(fd, release=True)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
