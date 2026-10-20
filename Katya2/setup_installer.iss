#define MyAppName "Katya 2.10"
#define MyAppVersion "2.10"
#define MyAppPublisher "kirill181024-cyber"
#define MyAppURL "https://github.com/kirill181024-cyber/katya"
#define MyAppLauncher "setup_env.bat"

[Setup]
AppId={{8F3A2C71-9B4E-4D2A-9C11-77E2A0B5D910}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=E:\Katya2\dist_setup
OutputBaseFilename=Katya2.10_Setup
SetupIconFile=E:\Katya2\Katya2\katya.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\katya.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "E:\Katya2\Katya2\main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\katya.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\banner.svg"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\README_RU.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "E:\Katya2\Katya2\core\*"; DestDir: "{app}\core"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "E:\Katya2\Katya2\skills\*"; DestDir: "{app}\skills"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "E:\Katya2\setup\setup_env.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\setup_env.bat"; WorkingDir: "{app}"; IconFilename: "{app}\katya.ico"; Comment: "Katya 2.10 - Hyper-Drive"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\setup_env.bat"; WorkingDir: "{app}"; IconFilename: "{app}\katya.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\setup_env.bat"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\skills"
Type: filesandordirs; Name: "{app}\__pycache__"
