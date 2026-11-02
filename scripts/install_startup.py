"""Start ROVEN automatically at Windows sign-in (per-user Run key, no admin rights needed).

    python scripts/install_startup.py           # enable
    python scripts/install_startup.py --remove  # disable
"""
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "ROVEN"


def command() -> str:
    if getattr(sys, "frozen", False):                 # packaged ROVEN.exe
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw}" "{main}"'


def enable() -> str:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
    return command()


def disable() -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, NAME)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    if "--remove" in sys.argv:
        disable()
        print("ROVEN will no longer start at sign-in.")
    else:
        print("ROVEN will start at sign-in:", enable())
