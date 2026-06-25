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
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=BlindRSS-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

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
