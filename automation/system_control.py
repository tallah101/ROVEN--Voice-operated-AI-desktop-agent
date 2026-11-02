"""Volume, brightness, Settings pages, lock, power and resource status."""
from __future__ import annotations

import ctypes
import os
import subprocess

SETTINGS_PAGES = {
    "wifi": "ms-settings:network-wifi", "bluetooth": "ms-settings:bluetooth",
    "display": "ms-settings:display", "sound": "ms-settings:sound",
    "network": "ms-settings:network", "apps": "ms-settings:appsfeatures",
    "windows_update": "ms-settings:windowsupdate", "notifications": "ms-settings:notifications",
    "battery": "ms-settings:batterysaver", "privacy": "ms-settings:privacy",
    "personalization": "ms-settings:personalization", "default_apps": "ms-settings:defaultapps",
}


def _endpoint():
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    from pycaw.pycaw import AudioUtilities
    speakers = AudioUtilities.GetSpeakers()
    ev = getattr(speakers, "EndpointVolume", None)       # pycaw >= 20240316
    if ev is not None:
        return ev
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def get_volume() -> dict:
    ev = _endpoint()
    return {"volume_percent": round(ev.GetMasterVolumeLevelScalar() * 100), "muted": bool(ev.GetMute())}


def set_volume(percent: int) -> dict:
    ev = _endpoint()
    ev.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100.0, None)
    return {"verified_state": get_volume()}


def change_volume(delta: int) -> dict:
    return set_volume(get_volume()["volume_percent"] + delta)


def set_mute(muted: bool) -> dict:
    _endpoint().SetMute(1 if muted else 0, None)
    return {"verified_state": get_volume()}


def set_brightness(percent: int) -> dict:
    import screen_brightness_control as sbc
    sbc.set_brightness(max(0, min(100, percent)))
    try:
        return {"brightness": sbc.get_brightness(), "verified": True}
    except Exception:
        return {"verified": False, "note": "Brightness may not be adjustable on external monitors."}


def open_settings_page(page: str) -> dict:
    os.startfile(SETTINGS_PAGES[page])  # type: ignore[attr-defined]
    return {"opened": page}


def lock_computer() -> dict:
    ok = bool(ctypes.windll.user32.LockWorkStation())  # type: ignore[attr-defined]
    return {"locked": ok}


def power_action(action: str) -> dict:
    commands = {
        "shutdown": ["shutdown", "/s", "/t", "10"],
        "restart": ["shutdown", "/r", "/t", "10"],
        "sign_out": ["shutdown", "/l"],
    }
    if action == "sleep":
        ctypes.windll.powrprof.SetSuspendState(0, 1, 0)  # type: ignore[attr-defined]
    else:
        subprocess.run(commands[action], check=True)
    return {"action": action, "note": "Shutdown/restart begins in 10 seconds; run 'shutdown /a' to abort."}


def system_status(top: int = 8) -> dict:
    import psutil
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            continue
    totals: dict[str, int] = {}
    for rss, name in procs:
        totals[name] = totals.get(name, 0) + rss
    heaviest = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top]
    battery = psutil.sensors_battery()
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": vm.percent,
        "memory_used_gb": round(vm.used / 1e9, 1),
        "top_memory_apps": [{"process": n, "memory_mb": round(b / 1e6)} for n, b in heaviest],
        "battery": None if battery is None else {"percent": battery.percent, "plugged_in": battery.power_plugged},
    }
