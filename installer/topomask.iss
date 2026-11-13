; SPDX-License-Identifier: Apache-2.0
; Per-user installer for the Windows desktop app. Built by scripts/build_installer.ps1:
;   ISCC /DAppVersion=0.1.0 /F<output name> installer\topomask.iss
; Files written by an installer carry no Mark of the Web, so the .NET components used
; by WebView2 load without unblocking the extracted files by hand.

#ifndef AppVersion
  #error AppVersion is not defined: pass /DAppVersion=x.y.z to ISCC
#endif

#define AppName "topomask"
#define AppExe "topomask.exe"
#define AppUrl "https://github.com/felicerosella/topomask"

[Setup]
; AppId identifies the installation for upgrades and uninstall: never change it.
AppId={{F077569A-6609-4872-AB2E-C3E392B6D75E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName} contributors
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\build\topomask.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\out
CloseApplications=yes
RestartApplications=no
AppMutex=Local\topomask

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[CustomMessages]
english.AutoStart=Start {#AppName} in the notification area when I sign in
italian.AutoStart=Avvia {#AppName} nell'area di notifica all'accesso

[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove the previous bundle so stale libraries from an older version never load.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\topomask\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
