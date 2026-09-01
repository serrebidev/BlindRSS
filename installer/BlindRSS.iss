; Copyright (c) serrebidev and contributors
; This file is part of BlindRSS
; SPDX-License-Identifier: MIT

#define MyAppName "BlindRSS"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Serrebi"
#define MyAppExeName "BlindRSS.exe"

[Setup]
AppId={{3D129EA4-7BCE-4E64-A45A-1AB29CB13C9A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-machine install into Program Files. The program lives under Program Files
; (x64 -> "Program Files", x86 -> "Program Files (x86)"); nothing is written back
; into the install dir at runtime. Mutable data lives outside it, keyed off the
; .windows-installed marker (see core/config.py): config.json/rss.db/logs/caches
; in %APPDATA%\BlindRSS, episode downloads in the user's Downloads folder, and
; the self-updating yt-dlp.exe in %LOCALAPPDATA%\BlindRSS\bin.
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=BlindRSS-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
; Install in 64-bit mode on x64 Windows so {autopf} resolves to "Program Files"
; (not "Program Files (x86)") and the 64-bit registry/uninstall view is used.
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ShowLanguageDialog=auto

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\BlindRSS\*"; DestDir: "{app}"; Excludes: "config.json,rss.db,rss.db-wal,rss.db-shm,rss.db-journal,blindrss.log,youtube_cookies.txt,podcasts\*,ytplay_cache\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "windows-installed.marker"; DestDir: "{app}"; DestName: ".windows-installed"; Flags: ignoreversion

[Icons]
Name: "{group}\BlindRSS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\BlindRSS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch BlindRSS"; Flags: nowait postinstall skipifsilent

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "sv"; MessagesFile: "compiler:Languages\Swedish.isl"
