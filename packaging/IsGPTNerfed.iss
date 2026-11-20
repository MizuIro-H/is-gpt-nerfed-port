; Per-user installer for the Windows build (dist\windows). Built by packaging\build_installer.ps1, which
; passes /DAppVersion=<x.y.z> and /DSourceDir=<dist\windows> /DOutputDir=<dist>.
; Installs without admin into %LOCALAPPDATA%\Programs\is-gpt-nerfed: a fixed path, so the hook commands
; Codex stores (they point at plugin\ and nerfed-core.exe here) stay valid across upgrades.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\windows"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6E3C1B9A-5D0F-4C2E-9A47-1F8B2D6C7E10}
AppName=is-gpt-nerfed
AppVersion={#AppVersion}
AppVerName=is-gpt-nerfed {#AppVersion}
AppPublisher=MizuIro-H
AppPublisherURL=https://github.com/MizuIro-H/is-gpt-nerfed-port
AppSupportURL=https://github.com/MizuIro-H/is-gpt-nerfed-port/issues
DefaultDirName={localappdata}\Programs\is-gpt-nerfed
DisableDirPage=yes
DefaultGroupName=is-gpt-nerfed
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=IsGPTNerfed-{#AppVersion}-windows-x64-setup
SetupIconFile=IsGPTNerfed.ico
UninstallDisplayIcon={app}\IsGPTNerfed.exe
UninstallDisplayName=is-gpt-nerfed
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Upgrades replace the program wholesale: stale PyInstaller/WinUI files from an older build must not linger.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\inspector"
Type: filesandordirs; Name: "{app}\plugin"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\is-gpt-nerfed"; Filename: "{app}\IsGPTNerfed.exe"
Name: "{autodesktop}\is-gpt-nerfed"; Filename: "{app}\IsGPTNerfed.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\IsGPTNerfed.exe"; Description: "{cm:LaunchProgram,is-gpt-nerfed}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Unregister the Codex plugin/hooks that point into {app}; the ledger and settings in NERFED_HOME are kept.
Filename: "{app}\nerfed-core.exe"; Parameters: "teardown"; Flags: runhidden waituntilterminated; RunOnceId: "teardown"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure StopRunning();
var
  ResultCode: Integer;
begin
  // The tray app and its background probe workers lock files in the install folder.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM IsGPTNerfed.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM IsGPTNerfed.Inspector.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM nerfed-core.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunning();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunning();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  // The app's own "start at login" setting writes this Run value; drop it only if it is ours.
  if (CurUninstallStep = usPostUninstall) and
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'is-gpt-nerfed', Command) and
     (Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Command)) > 0) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'is-gpt-nerfed');
end;
