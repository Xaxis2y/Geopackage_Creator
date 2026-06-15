; ============================================================================
;  GeoPackage Creator - Inno Setup installer script
;  Produces:  Output\GeoPackageCreator-Setup-0.28.0.exe
;
;  Prerequisites:
;    1. Run the one-dir PyInstaller build first so that
;       <root>\dist\GeoPackageCreator\GeoPackageCreator.exe exists:
;           packaging\build_windows.ps1 -OneDirOnly
;    2. Install Inno Setup 6 (https://jrsoftware.org/isinfo.php).
;    3. Open this .iss in the Inno Setup Compiler and press "Compile"
;       (or run:  ISCC.exe packaging\installer\GeoPackageCreator.iss).
;
;  Paths below are relative to THIS script's folder (packaging\installer),
;  so the project root is two levels up.
; ============================================================================

#define MyAppName "GeoPackage Creator"
#define MyAppVersion "0.28.0"
#define MyAppPublisher "GeoPackage Creator"
#define MyAppExeName "GeoPackageCreator.exe"
; Project root, relative to this script (packaging\installer\ -> ..\..)
#define SourceDist "..\..\dist\GeoPackageCreator"

[Setup]
AppId={{8E2C9B41-4F2A-4D7B-9C3E-7A1D2B6F0A28}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GeoPackage Creator
DefaultGroupName=GeoPackage Creator
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=GeoPackageCreator-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Per-machine install needs admin; use "lowest" for per-user installs.
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
; SetupIconFile=..\app.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Recursively include the entire one-dir PyInstaller output.
Source: "{#SourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundle user-facing docs next to the app (optional; remove if not wanted).
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\..\USER_MANUAL.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\..\GETTING_STARTED.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
