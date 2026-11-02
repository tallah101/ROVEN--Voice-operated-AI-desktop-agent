"""Well-known folders, resolved the Windows way (handles OneDrive-redirected Documents)."""
from __future__ import annotations

import sys
from pathlib import Path

FOLDERID = {
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
}


def known_folder(name: str) -> Path:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            from uuid import UUID

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = UUID(FOLDERID[name])
            guid = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:
            pass
    return Path.home() / name.capitalize()


def app_root() -> Path:
    """Folder containing ROVEN.exe when installed, or the project folder in developer mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
