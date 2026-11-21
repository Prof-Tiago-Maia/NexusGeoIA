; ---------------------------------------------------------------------------
; Instalador do NexusGeo IA (Inno Setup 6)
;
; Compile com packaging\build_installer.ps1 ou diretamente:
;     ISCC.exe packaging\installer.iss
;
; Saida: dist\NexusGeoIA_v0.9.0_Setup.exe
;
; O pacote --onedir gerado por packaging\assistente.spec
; (dist\NexusGeoIA\NexusGeoIA.exe + dist\NexusGeoIA\_internal\) e
; embutido recursivamente no instalador, preservando a pasta _internal
; ao lado do executavel. Os dados do usuario ficam em
; %LOCALAPPDATA%\NexusGeoIA, definidos por launcher_desktop.py.
;
; Instalacao por usuario, sem UAC: PrivilegesRequired=lowest evita o
; prompt de Administrador em PCs academicos/laboratorios. Com essa
; diretiva, {autopf} resolve para %LOCALAPPDATA%\Programs, ou seja, o
; padrao vira {localappdata}\Programs\NexusGeoIA. O usuario ainda pode
; optar pelo modo administrativo no dialogo de modo de instalacao
; (PrivilegesRequiredOverridesAllowed=dialog); nesse caso {autopf}
; passa a ser {commonpf} (Program Files).
; ---------------------------------------------------------------------------

#define MyAppName "NexusGeo IA"
#define MyAppVersion "0.9.0"
#define MyAppPublisher "NexusGeo IA"
#define MyAppExeName "NexusGeoIA.exe"
#define MyAppDirName "NexusGeoIA"

[Setup]
; AppId fixo: atualiza a mesma instalacao em versoes futuras.
AppId={{8F2C1A54-3B7D-4E6A-9C21-5D4B7A1E9F03}
AppName=NexusGeo IA
AppVersion=0.9.0
AppVerName=NexusGeo IA v0.9.0
AppPublisher=NexusGeo IA
DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=NexusGeoIA_v0.9.0_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Instalacao por usuario (sem UAC). {autopf} acompanha o modo escolhido:
; lowest => %LOCALAPPDATA%\Programs; admin (override) => Program Files.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
; Icone opcional: crie packaging\icone.ico para usa-lo.
#if FileExists("icone.ico")
SetupIconFile=icone.ico
#endif

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalhos na Area de Trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: checkedonce

[Files]
; Todo o pacote --onedir: NexusGeoIA.exe + _internal\ (bibliotecas,
; app.py, prompts\ e .streamlit\) na mesma pasta de instalacao. O
; recursesubdirs/createallsubdirs preserva a arvore de _internal, que o
; executavel precisa ao lado dele. O .spec ja filtra .dsh, .git,
; .ruff_cache, __pycache__, tests, .env e demais estado local; nenhuma
; pasta do projeto e embarcada diretamente pelo instalador.
Source: "..\dist\NexusGeoIA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Menu Iniciar
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Abrir o NexusGeo IA"
Name: "{group}\Gerenciar Modelos LLM"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup-modelo"; Comment: "Escolher e baixar modelos do Ollama"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
; Area de Trabalho
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Abrir o NexusGeo IA"
Name: "{autodesktop}\Gerenciar Modelos LLM"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup-modelo"; Tasks: desktopicon; Comment: "Escolher e baixar modelos do Ollama"

[Run]
; Executa o assistente de escolha/download ao final da instalacao.
; skipifsilent evita abrir janela em instalacoes silenciosas.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup-modelo"; Description: "Abrir o assistente de escolha dos modelos LLM"; Flags: postinstall nowait skipifsilent runascurrentuser

[Code]
{ ---------------------------------------------------------------------------
  Ollama: deteccao, download e instalacao silenciosa.

  O instalador oficial do Ollama e baixado para a pasta temporaria do
  setup e executado com /VERYSILENT /NORESTART. Assim o usuario final
  nao precisa instalar o Ollama manualmente antes de abrir o NexusGeo.
  --------------------------------------------------------------------------- }

const
  UrlInstaladorOllama = 'https://ollama.com/download/OllamaSetup.exe';

function OllamaInstalado(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{pf}\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{pf32}\Ollama\ollama.exe'));
end;

function InstalarOllamaSilencioso(): Boolean;
var
  Codigo: Integer;
  Instalador: String;
  Comando: String;
begin
  Result := False;
  Instalador := ExpandConstant('{tmp}\OllamaSetup.exe');

  { O PowerShell faz o download e executa o instalador do Ollama com as
    flags silenciosas. A janela do console fica oculta (SW_HIDE). }
  Comando :=
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    '$ProgressPreference = ''SilentlyContinue''; ' +
    '$ErrorActionPreference = ''Stop''; ' +
    'Invoke-WebRequest -UseBasicParsing -Uri ''' + UrlInstaladorOllama + '''' +
    ' -OutFile ''' + Instalador + '''; ' +
    'Start-Process -FilePath ''' + Instalador + '''' +
    ' -ArgumentList ''/VERYSILENT'',''/NORESTART'' -Wait"';

  { Roda como o usuario original sempre que possivel: o Ollama e
    instalado em %LOCALAPPDATA%\Programs\Ollama do usuario, nao no
    perfil do administrador que elevou o instalador. }
  if not ExecAsOriginalUser(
    'powershell.exe',
    Comando,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    Codigo
  ) then
  begin
    if not Exec(
      'powershell.exe',
      Comando,
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      Codigo
    ) then
      Exit;
  end;

  Result := (Codigo = 0) and OllamaInstalado();
end;

function InitializeSetup(): Boolean;
begin
  { A instalacao do Ollama acontece em CurStepChanged(ssPostInstall),
    sem bloquear o assistente com perguntas. }
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;

  if OllamaInstalado() then
    Exit;

  WizardForm.StatusLabel.Caption :=
    'Instalando o Ollama automaticamente (sem janelas)...';

  if not InstalarOllamaSilencioso() then
  begin
    { Em instalacoes silenciosas nao bloqueie com uma janela. }
    if not WizardSilent then
      MsgBox(
        'O Ollama nao pode ser instalado automaticamente.' + #13#10 + #13#10 +
        'O NexusGeo IA abrira mesmo assim. Depois, instale o Ollama pelo ' +
        'site oficial e use o atalho "Gerenciar Modelos LLM" para baixar ' +
        'os modelos.',
        mbInformation,
        MB_OK
      );
  end;
end;
