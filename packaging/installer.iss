; Script do Inno Setup 6. Use o criar_instalador.bat (ele chama: ISCC /DAppVersion=x.y.z packaging\installer.iss).
; Entrada: dist\Downverse\ (gerado pelo PyInstaller). Saída: dist\Downverse-Setup-x.y.z.exe

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{91FC7061-C3ED-4E0F-AED8-A55BF4ADEE99}
AppName=Downverse
AppVersion={#AppVersion}
AppVerName=Downverse {#AppVersion}
AppPublisher=The BitLab Team
AppPublisherURL=https://github.com/The-BitLab-Team/Downverse
AppSupportURL=https://github.com/The-BitLab-Team/Downverse/issues
DefaultDirName={autopf}\Downverse
DefaultGroupName=Downverse
DisableProgramGroupPage=yes
; Instala só para o usuário atual, sem pedir administrador (dá para escolher "para todos" na tela de início).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Downverse-Setup-{#AppVersion}
SetupIconFile=..\assets\downverse.ico
UninstallDisplayIcon={app}\Downverse.exe
UninstallDisplayName=Downverse
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Downverse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Downverse"; Filename: "{app}\Downverse.exe"
Name: "{autodesktop}\Downverse"; Filename: "{app}\Downverse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Downverse.exe"; Description: "{cm:LaunchProgram,Downverse}"; Flags: nowait postinstall skipifsilent
