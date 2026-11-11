"""Pinned, reparse-refusing Windows reads beneath an opened directory.

NtCreateFile's RootDirectory supplies the dir_fd semantics missing from Python
on Windows. Each component is opened relative to the preceding HANDLE, never
by reconstructing a raceable full pathname. The returned CRT fd owns the final
handle; all temporary directory handles are closed before returning.
"""
from __future__ import annotations

import os
from pathlib import Path


def open_regular_beneath(root: Path, parts: tuple[str, ...]) -> int:
    if os.name != "nt":
        raise RuntimeError("Windows relative-handle reads require Windows")
    if not parts or any(not part or part in (".", "..") or
                        any(char in part for char in ("/", "\\", ":", "\0"))
                        for part in parts):
        raise ValueError("invalid Windows bundle-relative path")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)),
                    ("Attributes", wintypes.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class IoStatus(ctypes.Structure):
        # The first field is the pointer-sized Status/Pointer union.
        _fields_ = [("Status", ctypes.c_size_t), ("Information", ctypes.c_size_t)]

    class FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll")
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatus), ctypes.c_void_p,
        wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
        ctypes.c_void_p, wintypes.ULONG]
    native.NtCreateFile.restype = wintypes.LONG
    native.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
    native.RtlNtStatusToDosError.restype = wintypes.ULONG

    def check(handle, *, directory):
        info = FileInfo()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise OSError("reparse points are not allowed in sealed bundle paths")
        if bool(info.attributes & 0x10) != directory or kernel.GetFileType(handle) != 1:
            raise OSError("bundle path component has the wrong file type")

    path = os.path.abspath(root)
    if not path.startswith("\\\\?\\"):
        path = ("\\\\?\\UNC\\" + path[2:]) if path.startswith("\\\\") else "\\\\?\\" + path
    handles = []
    try:
        # OPEN_EXISTING, BACKUP_SEMANTICS + OPEN_REPARSE_POINT. No handle is
        # inheritable; omit FILE_SHARE_DELETE while walking the directory tree.
        handle = kernel.CreateFileW(path, 0x80000000, 3, None, 3, 0x02200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append(handle)
        check(handle, directory=True)
        for index, part in enumerate(parts):
            length = len(part.encode("utf-16-le"))
            if length > 65532:
                raise ValueError("bundle path component is too long")
            buffer = ctypes.create_unicode_buffer(part)
            name = UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
            attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), handle,
                                         ctypes.pointer(name), 0x40, None, None)
            child = wintypes.HANDLE()
            status_block = IoStatus()
            directory = index < len(parts) - 1
            options = 0x00200000 | 0x20 | (0x1 if directory else 0x40)
            status = native.NtCreateFile(ctypes.byref(child), 0x80100000,
                ctypes.byref(attributes), ctypes.byref(status_block), None,
                0, 3, 1, options, None, 0)
            if status < 0:
                raise ctypes.WinError(native.RtlNtStatusToDosError(status))
            handle = child.value
            handles.append(handle)
            check(handle, directory=directory)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handles.pop()  # fd now exclusively owns the final HANDLE
        return fd
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)
