; OhMyMeme Windows Installer (Inno Setup)
; 编译: iscc windows.iss

#define MyAppName "OhMyMeme"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "OhMyMeme"
#define MyAppURL "https://github.com/ohmymeme/ohmymeme"
#define MyAppExeName "OhMyMeme.exe"

[Setup]
AppId={{B8F4A3D2-1C5E-4A7B-9D6F-8E2C3A1B5D7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
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
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "启动选项"; Flags: unchecked

[Files]
Source: "..\..\dist\OhMyMeme.exe"; DestDir: "{app}"; Flags: ignoreversion
; 如果使用目录模式打包，取消注释以下行并注释掉上一行
; Source: "..\..\dist\OhMyMeme\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: ""
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; 清理配置文件（可选 - 默认保留用户数据）
; Filename: "cmd.exe"; Parameters: "/c rmdir /s /q ""{localappdata}\OhMyMeme"""; Flags: runhidden

[Code]
function InitializeSetup: Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 可选：创建日志或额外配置
  end;
end;
