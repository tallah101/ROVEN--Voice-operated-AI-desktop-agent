; Inno Setup script: turns dist\ROVEN into ONE file, dist\ROVEN-Setup-<version>.exe.
; Per-user install (no admin rights needed), Start-menu + optional desktop shortcut, starts at sign-in.
#define AppName "ROVEN"
#define AppVersion "1.3.0"

[Setup]
AppId={{9C3B6F1E-52A4-4D2B-9C7E-6A1D2F8B4E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ROVEN
DefaultDirName={localappdata}\Programs\ROVEN
DefaultGroupName=ROVEN
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ROVEN-Setup-{#AppVersion}
SetupIconFile=roven.ico
UninstallDisplayIcon={app}\ROVEN.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start ROVEN automatically when I sign in to Windows"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\ROVEN\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\ROVEN"; Filename: "{app}\ROVEN.exe"
Name: "{group}\Uninstall ROVEN"; Filename: "{uninstallexe}"
Name: "{userdesktop}\ROVEN"; Filename: "{app}\ROVEN.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ROVEN"; \
  ValueData: """{app}\ROVEN.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\ROVEN.exe"; Description: "Start ROVEN now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM ROVEN.exe /F"; Flags: runhidden; RunOnceId: "StopRoven"
