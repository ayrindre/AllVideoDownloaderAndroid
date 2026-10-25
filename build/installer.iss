; WebFinder — Inno Setup installer script
; Build:  iscc build\installer.iss   (Inno Setup 6: https://jrsoftware.org/isinfo.php)

[Setup]
AppName=WebFinder
AppVersion=1.0.0
AppPublisher=WebFinder Project
AppSupportURL=https://github.com/wrappedman/WenFinder
DefaultDirName={autopf}\WebFinder
DefaultGroupName=WebFinder
OutputBaseFilename=WebFinder-Setup-1.0.0
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\WebFinder.exe
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\WebFinder.exe"; DestDir: "{app}"; Flags: ignoreversion
; Optional — ship FFmpeg next to the EXE so HLS capture works out of the box:
Source: "..\dist\ffmpeg\*"; DestDir: "{app}\ffmpeg"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\WebFinder"; Filename: "{app}\WebFinder.exe"
Name: "{group}\Uninstall WebFinder"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WebFinder"; Filename: "{app}\WebFinder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WebFinder.exe"; Description: "Launch WebFinder"; Flags: nowait postinstall skipifsilent
