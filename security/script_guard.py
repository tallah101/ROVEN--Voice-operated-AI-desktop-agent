"""Checks scripts ROVEN writes before they run.

* Forbidden (never runs): reading saved passwords/cookies, elevating to admin, weakening Windows security,
  wiping disks/boot config, deleting system folders, writing machine-wide registry, download-and-execute.
* Read-only (looks only): medium risk — asks unless you trusted 'run_script'.
* Anything that changes something: high risk — always asks.
This is a safety net against mistakes, not a sandbox; every script is also logged."""
from __future__ import annotations

import re

from security.permission_manager import Risk

FORBIDDEN = [
    (r"Login Data|\bCookies\b|Web Data|Local State|key4\.db|logins\.json|CryptUnprotectData|ProtectedData|"
     r"\bvaultcmd\b|\bcmdkey\b|mimikatz|\blsass\b|\\SAM\b|reg(\.exe)?\s+save", "it would read saved passwords, cookies or credential stores"),
    (r"-Verb\s+RunAs|\brunas(\.exe)?\s|\bsudo\b|ShellExecute\w*\([^)]*runas", "it would request administrator rights (UAC)"),
    (r"Set-MpPreference|Add-MpPreference|DisableRealtimeMonitoring|advfirewall\s+set\s+\w+\s+state\s+off|"
     r"Set-NetFirewallProfile[^\n]*-Enabled\s+(False|0)|Set-ExecutionPolicy[^\n]*(LocalMachine|Unrestricted)",
     "it would weaken Windows security"),
    (r"\bbcdedit\b|\bdiskpart\b|Format-Volume|Clear-Disk|Initialize-Disk|Remove-Partition|\bformat(\.com)?\s+[a-z]:|"
     r"vssadmin\s+delete|wbadmin\s+delete|cipher(\.exe)?\s+/w", "it could wipe disks or break booting"),
    (r"(Remove-Item|\brm\b|\bdel\b|\brd\b|\brmdir\b|\berase\b|shutil\.rmtree|os\.remove)[^\n]*"
     r"(C:\\\\?\s*['\"]?\s*($|\)|-)|C:\\\\?Windows|C:\\\\?Program Files|\$env:SystemRoot|\$env:windir|System32)",
     "it would delete system files"),
    (r"reg(\.exe)?\s+(add|delete|import)\s+HKLM|(Set|New|Remove)-Item(Property)?[^\n]*HKLM:|winreg\.HKEY_LOCAL_MACHINE[^\n]*(Set|Delete)",
     "it would change machine-wide registry settings"),
    (r"DownloadString\(|\b(iex|Invoke-Expression)\b[^\n]*(iwr|irm|Invoke-WebRequest|Invoke-RestMethod|http)|"
     r"(iwr|irm|Invoke-WebRequest|curl|wget)[^\n]*\|\s*(iex|Invoke-Expression)", "it would download and run code from the internet"),
    (r"\bshutdown(\.exe)?\s+/[srpgh]|Stop-Computer|Restart-Computer", "use the power tool for shutdown/restart (it asks first)"),
]

PS_MUTATING = re.compile(
    r"\b(Remove|Set|New|Move|Rename|Copy|Stop|Start|Restart|Clear|Disable|Enable|Install|Uninstall|Add|Update|Invoke|"
    r"Send|Export|Import|Register|Unregister|Suspend|Resume|Mount|Dismount|Reset|Push|Publish|Expand|Compress|Lock|"
    r"Unlock|Out)-(?!String\b)\w+|\bWrite-(?!Output\b|Host\b|Verbose\b|Information\b)\w+|"
    r"\.(Delete|MoveTo|CopyTo|Kill|SetValue|Create\w*)\(|::(Delete|Move|Copy|WriteAll\w*|AppendAll\w*|Create\w*|Start)\(",
    re.I)
CMD_MUTATING = re.compile(r"(^|[\s;&|(])(del|erase|rd|rmdir|move|ren|rename|copy|xcopy|robocopy|mkdir|md|attrib|icacls|"
                          r"takeown|taskkill|sc|net|reg|schtasks|setx|wmic|powercfg|start)(\.exe)?\s", re.I)
PS_REDIRECT = re.compile(r"(?<![-<=])>{1,2}(?!\s*\$null|&)\s*[\w$\"'\\.:~/]")
PY_MUTATING = re.compile(
    r"open\([^)]*['\"][^'\"]*[wax+][^'\"]*['\"]|\.write\(|\.write_text\(|\.write_bytes\(|\.unlink\(|\.rmdir\(|"
    r"\.rename\(|\.replace\(\s*['\"]?[A-Za-z]:|\.mkdir\(|\.touch\(|os\.(remove|unlink|rmdir|rename|replace|makedirs|"
    r"mkdir|system|startfile|kill|chmod)|shutil\.|subprocess|send2trash|requests\.(post|put|delete|patch)|"
    r"urlopen\([^)]*data=|socket\.|smtplib|winreg\.(Set|Delete|Create)|pyautogui|keyboard\.|ctypes|win32api|"
    r"win32gui|win32con|exec\(|eval\(|__import__", re.I)


class ForbiddenScript(PermissionError):
    pass


def classify(language: str, code: str) -> Risk:
    """Raises ForbiddenScript, or returns MEDIUM (read-only) / HIGH (changes something)."""
    for pattern, reason in FORBIDDEN:
        if re.search(pattern, code, re.I):
            raise ForbiddenScript(f"I won't run that script because {reason}.")
    if language == "python":
        return Risk.HIGH if PY_MUTATING.search(code) else Risk.MEDIUM
    stripped = re.sub(r"#.*", "", code)
    if PS_MUTATING.search(stripped) or CMD_MUTATING.search(stripped) or PS_REDIRECT.search(stripped):
        return Risk.HIGH
    return Risk.MEDIUM
