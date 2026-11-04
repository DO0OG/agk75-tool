; AGK75 Tool Windows 설치 프로그램 (Inno Setup 6)
;
; 빌드 (agk75-tool 폴더에서, build_exe.py 를 먼저 실행. PySide6 의 Qt DLL 은 BuildDir 안에 그대로 들어 있어 교체할 수 있다):
;   ISCC installer\AGK75Tool.iss
; 백업 파일은 %AppData%\AGK75Tool\backups 에 저장되므로 제거해도 남는다.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\dist\AGK75Tool.dist"
#endif

[Setup]
AppId={{B7E4C1A2-5D3F-4A86-9C0E-2F1D8A6B4E73}
AppName=AGK75 Tool
AppVersion={#AppVersion}
AppVerName=AGK75 Tool {#AppVersion}
VersionInfoProductName=AGK75 Tool
VersionInfoVersion={#AppVersion}.0
AppPublisher=DO0OG
DefaultDirName={autopf}\AGK75 Tool
DisableProgramGroupPage=yes
; 기본은 모든 사용자용(Program Files) 설치. 명령줄 /CURRENTUSER는 자동 검사용이다.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=AGK75Tool-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\AGK75Tool.exe
UninstallDisplayName=AGK75 Tool
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ShowLanguageDialog=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"; InfoBeforeFile: "notice-ko.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "notice-en.txt"
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"; InfoBeforeFile: "notice-zh.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AGK75 Tool"; Filename: "{app}\AGK75Tool.exe"
Name: "{autodesktop}\AGK75 Tool"; Filename: "{app}\AGK75Tool.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AGK75Tool.exe"; Description: "{cm:LaunchProgram,AGK75 Tool}"; Flags: nowait postinstall skipifsilent
