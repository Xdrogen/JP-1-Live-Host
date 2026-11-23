; JAMJUM JP-1 安装脚本 —— 先保存，先别编译
#define MyAppName "JP-1 Live Host"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "JAMJUM"
#define MyAppExeName "jamjum_jp1.exe"

[Setup]
AppId={{8F3A2C1E-5B47-4D09-9A61-2E7C4B8D1F30}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\JAMJUM JP-1
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=E:\JAMJUM JP-1
OutputBaseFilename=JP-1 Live Host Setup
SetupIconFile=E:\JAMJUM JP-1\jamjum.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "E:\JAMJUM JP-1\dist\jamjum_jp1\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent