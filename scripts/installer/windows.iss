; OhMyMeme Windows Installer (Inno Setup)
; 编译: iscc windows.iss

#define MyAppName "OhMyMeme"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "OhMyMeme"
#define MyAppURL "https://github.com/OhMyMeme/OhMyMeme"
#define MyAppExeName "OhMyMeme.exe"
#define SourceDir "..\..\dist\src.dist"

[Setup]
AppId={{B8F4A3D2-1C5E-4A7B-9D6F-8E2C3A1B5D7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist
OutputBaseFilename=OhMyMeme-{#MyAppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
DisableProgramGroupPage=yes
DisableStartupPrompt=yes
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "启动选项"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --silent"; Tasks: autostart; Flags: uninsdeletevalue

[InstallDelete]
; 升级时清理旧版启动文件夹快捷方式（v0.2.1 及之前使用文件夹方式）
Name: "{userstartup}\{#MyAppName}.lnk"; Type: files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: ""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: postinstall nowait
