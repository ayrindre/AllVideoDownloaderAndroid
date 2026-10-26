; All Video Downloader — Inno Setup script (optional installer)
;
;   1. build the EXE first:   build.bat
;   2. install Inno Setup 6:  winget install JRSoftware.InnoSetup
;   3. make the installer:    iscc build\installer.iss
;      -> build\Output\AllVideoDownloader-Setup-2.0.0.exe
;
; The EXE it packages is the one build.bat produces: ..\dist\AllVideoDownloader.exe

#define AppName "All Video Downloader"
#define AppVersion "2.0.0"
#define AppExe "AllVideoDownloader.exe"
#define AppPublisher "Behnam Ehsani"
#define AppURL "https://github.com/wrappedman/AllVideoDownloader"

[Setup]
AppId={{8E2F5C31-7B4D-4A63-9C36-9A1D2B7E4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\All Video Downloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=AllVideoDownloader-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; built by build.bat
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; optional: ship FFmpeg next to the EXE so HLS capture works out of the box
Source: "..\dist\ffmpeg\*"; DestDir: "{app}\ffmpeg"; \
    Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
