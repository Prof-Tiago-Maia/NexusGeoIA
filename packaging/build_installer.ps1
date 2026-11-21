<#
.SYNOPSIS
    Gera o instalador Windows (Inno Setup) a partir do pacote portatil.

.DESCRIPTION
    1. le a versao oficial de config.py e confere se packaging\installer.iss
       e packaging\assistente.spec estao de acordo com ela;
    2. executa packaging\build_portatil.ps1, que roda a suite offline,
       compila o pacote --onedir (dist\NexusGeoIA\NexusGeoIA.exe +
       dist\NexusGeoIA\_internal\) com PyInstaller e monta o .zip
       portatil (use -SemPortatil para reaproveitar o pacote atual);
    3. localiza o compilador do Inno Setup (ISCC.exe) no PATH, nos
       diretorios padrao de instalacao e no registro do Windows;
    4. executa "ISCC.exe packaging\installer.iss" e gera
       dist\NexusGeoIA_v0.9.0_Setup.exe;
    5. roda packaging\smoke_test_artefatos.py, que valida os tres
       artefatos finais (assinaturas, conteudo do .zip sem estado local
       nem segredos e o autoteste do executavel com imports criticos,
       Word e Excel).

    Sem o Inno Setup instalado, o script explica como instalar e termina
    com codigo 1 (o executavel e o .zip portatil ja ficam prontos). Use
    -ExigirInno para tratar a ausencia como erro fatal antes de qualquer
    build e -SemInno para gerar apenas o executavel.

.PARAMETER PythonExe
    python.exe usado no build. Padrao: .venv\Scripts\python.exe.

.PARAMETER SemPortatil
    Nao executa o build portatil; exige o pacote onedir
    (dist\NexusGeoIA\NexusGeoIA.exe + dist\NexusGeoIA\_internal\) ja
    gerado.

.PARAMETER SemInno
    Gera apenas o executavel e o pacote portatil, sem compilar o
    instalador.

.PARAMETER ExigirInno
    Falha quando o ISCC.exe nao for encontrado (bom para CI).

.PARAMETER SemSmoke
    Nao roda o smoke test dos artefatos finais (packaging\
    smoke_test_artefatos.py) depois do ISCC. Use apenas em diagnostico.

.PARAMETER Limpar
    Repassa -Limpar ao build portatil (build do zero).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1 -SemPortatil -ExigirInno
#>

[CmdletBinding()]
param(
    [string]$PythonExe = "",

    [switch]$SemPortatil,

    [switch]$SemInno,

    [switch]$ExigirInno,

    [switch]$SemSmoke,

    [switch]$Limpar
)

$ErrorActionPreference = "Stop"

# Sem barra de progresso: em terminal nao interativo o Write-Progress
# dos cmdlets nativos pode falhar ao ler o buffer do console.
$ProgressPreference = "SilentlyContinue"

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Caminhos e identidade
# ---------------------------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $ScriptDir
$Dist = Join-Path $Raiz "dist"

$ConteudoConfig = Get-Content -LiteralPath (Join-Path $Raiz "config.py") -Raw
$VersaoApp = [regex]::Match(
    $ConteudoConfig,
    'APP_VERSION\s*=\s*"([^"]+)"'
).Groups[1].Value

if (-not $VersaoApp) {
    throw "APP_VERSION nao encontrado em config.py"
}

# Nome sem espacos (identidade do produto nos artefatos). O PyInstaller
# roda em --onedir: o instalador embute dist\NexusGeoIA\* (o .exe e a
# pasta _internal) na mesma pasta {app}.
$NomeApp = "NexusGeoIA"
$PastaApp = Join-Path $Dist $NomeApp
$ExeApp = Join-Path $PastaApp "$NomeApp.exe"
$SetupFinal = Join-Path $Dist "${NomeApp}_v${VersaoApp}_Setup.exe"
$ZipPortatil = Join-Path $Dist "${NomeApp}_v${VersaoApp}_Portatil.zip"
$Spec = Join-Path $ScriptDir "assistente.spec"
$Iss = Join-Path $ScriptDir "installer.iss"
$BuildPortatil = Join-Path $ScriptDir "build_portatil.ps1"
$SmokeTest = Join-Path $ScriptDir "smoke_test_artefatos.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Etapa {
    param([string]$Texto)

    Write-Host ""
    Write-Host "==> $Texto" -ForegroundColor Cyan
}

function Assert-Arquivo {
    param([string]$Caminho, [string]$Descricao)

    if (-not (Test-Path -LiteralPath $Caminho -PathType Leaf)) {
        throw "$Descricao nao encontrado: $Caminho"
    }
}

function Find-Iscc {
    # 1. PATH do sistema (instalacao com "Add to PATH" marcado).
    $comando = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue

    if ($comando) {
        return $comando.Source
    }

    # 2. Diretorios padrao do Inno Setup 6 e 5.
    $bases = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $env:LOCALAPPDATA
    )

    foreach ($base in $bases) {
        if (-not $base) {
            continue
        }

        foreach ($subpasta in @("Inno Setup 6", "Inno Setup 5", "Programs\Inno Setup 6")) {
            $candidato = Join-Path (Join-Path $base $subpasta) "ISCC.exe"

            if (Test-Path -LiteralPath $candidato -PathType Leaf) {
                return $candidato
            }
        }
    }

    # 3. Registro do Windows (instalacoes sem PATH).
    $chaves = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )

    foreach ($chave in $chaves) {
        if (-not (Test-Path -LiteralPath $chave)) {
            continue
        }

        $propriedades = Get-ItemProperty -LiteralPath $chave -ErrorAction SilentlyContinue

        if (-not $propriedades) {
            continue
        }

        $temLocal = $propriedades.PSObject.Properties.Name -contains "InstallLocation"

        if ($temLocal -and $propriedades.InstallLocation) {
            $candidato = Join-Path $propriedades.InstallLocation "ISCC.exe"

            if (Test-Path -LiteralPath $candidato -PathType Leaf) {
                return $candidato
            }
        }
    }

    return $null
}

# ---------------------------------------------------------------------------
# Validacoes de coerencia entre os tres arquivos de empacotamento
# ---------------------------------------------------------------------------

Write-Etapa "Validando config.py, assistente.spec e installer.iss"

Assert-Arquivo $Spec "assistente.spec"
Assert-Arquivo $Iss "installer.iss"
Assert-Arquivo $BuildPortatil "build_portatil.ps1"

$ConteudoSpec = Get-Content -LiteralPath $Spec -Raw

if ($ConteudoSpec -notmatch ('name="' + $NomeApp + '"')) {
    throw "assistente.spec nao gera $NomeApp.exe."
}

$ConteudoIss = Get-Content -LiteralPath $Iss -Raw

# O instalador embute exatamente dist\NexusGeoIA\* (o .exe e a pasta
# _internal) que o build portatil publica. Se um dos dois mudar de
# caminho, falha aqui antes do ISCC.
if (-not $ConteudoIss.Contains('Source: "..\dist\' + $NomeApp + '\*"')) {
    throw "installer.iss nao embute ..\dist\$NomeApp\* (pacote --onedir)."
}

# Sem recursesubdirs/createallsubdirs o Inno Setup copiaria apenas os
# arquivos da raiz e deixaria _internal de fora: o .exe nao abriria.
foreach ($flagPasta in @("recursesubdirs", "createallsubdirs")) {
    if (-not $ConteudoIss.Contains($flagPasta)) {
        throw "installer.iss nao usa $flagPasta; a pasta _internal nao seria instalada."
    }
}

if (-not $ConteudoIss.Contains('#define MyAppVersion "' + $VersaoApp + '"')) {
    throw "installer.iss nao usa a versao $VersaoApp de config.py (#define MyAppVersion)."
}

if (-not $ConteudoIss.Contains('OutputBaseFilename=' + $NomeApp + '_v' + $VersaoApp + '_Setup')) {
    throw "installer.iss nao gera o instalador versionado ${NomeApp}_v${VersaoApp}_Setup.exe."
}

# Instalacao por usuario, sem UAC: evita o prompt de Administrador em PCs
# academicos/laboratorios. O diretorio padrao usa {autopf}, que em modo
# nao administrativo aponta para %LOCALAPPDATA%\Programs; o dialogo de
# override continua permitindo o modo administrativo.
if ($ConteudoIss -match '(?m)^\s*PrivilegesRequired\s*=\s*admin\s*$') {
    throw "installer.iss usa PrivilegesRequired=admin; use lowest para instalar sem UAC."
}

if ($ConteudoIss -notmatch '(?m)^\s*PrivilegesRequired\s*=\s*lowest\s*$') {
    throw "installer.iss precisa de PrivilegesRequired=lowest (instalacao por usuario, sem UAC)."
}

if ($ConteudoIss -notmatch '(?m)^\s*PrivilegesRequiredOverridesAllowed\s*=\s*dialog\s*$') {
    throw "installer.iss precisa de PrivilegesRequiredOverridesAllowed=dialog."
}

if ($ConteudoIss -notmatch '(?m)^\s*DefaultDirName\s*=\s*\{(?:autopf|localappdata)\}') {
    throw "installer.iss precisa de DefaultDirName em {autopf} ou {localappdata} (instalacao sem UAC)."
}

Write-Host "    Versao: $VersaoApp"

# ---------------------------------------------------------------------------
# Executavel (pacote portatil)
# ---------------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $Dist | Out-Null

if ($SemPortatil) {
    Write-Etapa "Reaproveitando o pacote onedir existente (-SemPortatil)"

    if (-not (Test-Path -LiteralPath $ExeApp -PathType Leaf)) {
        throw @"
-SemPortatil foi informado, mas $ExeApp nao existe.

Rode o build portatil antes:
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1
"@
    }

    if (-not (Test-Path -LiteralPath (Join-Path $PastaApp "_internal") -PathType Container)) {
        throw "-SemPortatil foi informado, mas $PastaApp\_internal nao existe (pacote onedir incompleto)."
    }

    $exeMb = [math]::Round((Get-Item -LiteralPath $ExeApp).Length / 1MB, 1)
    Write-Host "    Executavel: $ExeApp ($exeMb MB) + _internal"
}
else {
    Write-Etapa "Executando o build portatil (testes + PyInstaller + .zip)"

    # Splat de HASHTABLE: no PowerShell 5.1 o splat de array envia os
    # elementos como argumentos POSICIONAIS, entao "-Limpar" virava o
    # valor de -PythonExe e o build portatil abortava com "Python nao
    # encontrado". O hashtable preserva o nome de cada parametro.
    $parametrosPortatil = @{}

    if ($PythonExe) {
        $parametrosPortatil["PythonExe"] = $PythonExe
    }

    if ($Limpar) {
        $parametrosPortatil["Limpar"] = $true
    }

    & $BuildPortatil @parametrosPortatil

    if (-not $?) {
        throw "O build portatil falhou; o instalador nao sera compilado."
    }

    Assert-Arquivo $ExeApp "Executavel do pacote portatil"

    if (-not (Test-Path -LiteralPath (Join-Path $PastaApp "_internal") -PathType Container)) {
        throw "O build portatil nao gerou $PastaApp\_internal; o instalador ficaria incompleto."
    }
}

# ---------------------------------------------------------------------------
# Instalador
# ---------------------------------------------------------------------------

if ($SemInno) {
    Write-Host ""
    Write-Host "Executavel e pacote portatil prontos (Inno Setup ignorado por -SemInno)." -ForegroundColor Green
    Write-Host "  Executavel: $ExeApp"

    if (Test-Path -LiteralPath $ZipPortatil -PathType Leaf) {
        Write-Host "  Portatil:   $ZipPortatil"
    }

    exit 0
}

Write-Etapa "Localizando o Inno Setup (ISCC.exe)"

$Iscc = Find-Iscc

if (-not $Iscc) {
    $mensagem = @(
        "ISCC.exe (Inno Setup 6) nao foi encontrado.",
        "",
        "Instale o Inno Setup 6 em https://jrsoftware.org/isdl.php",
        "e rode este script de novo para gerar o instalador.",
        "",
        "O executavel e o pacote portatil ja estao prontos:",
        "  $ExeApp",
        "  $ZipPortatil"
    ) -join [Environment]::NewLine

    if ($ExigirInno) {
        throw $mensagem
    }

    Write-Warning $mensagem
    exit 1
}

Write-Host "    ISCC: $Iscc"

Write-Etapa "Compilando o instalador com Inno Setup"

& $Iscc $Iss

if ($LASTEXITCODE -ne 0) {
    throw "ISCC falhou (codigo $LASTEXITCODE)"
}

Assert-Arquivo $SetupFinal "Instalador gerado"

# Assinatura MZ: confirma que o ISCC gravou um PE valido e nao um arquivo
# truncado (que passaria apenas pelo teste de existencia).
$assinaturaSetup = Get-Content -LiteralPath $SetupFinal -Encoding Byte -TotalCount 2

if ($assinaturaSetup.Count -lt 2 -or $assinaturaSetup[0] -ne 77 -or $assinaturaSetup[1] -ne 90) {
    throw "O instalador gerado nao comeca com a assinatura MZ de um PE valido."
}

$setupMb = [math]::Round((Get-Item -LiteralPath $SetupFinal).Length / 1MB, 1)

# ---------------------------------------------------------------------------
# Smoke test dos artefatos finais
# ---------------------------------------------------------------------------
#
# Ultima barreira do build completo: confere que os tres artefatos existem
# com assinatura valida, que o .zip nao carrega estado local nem segredos
# e que o executavel passa no autoteste interno (imports criticos, Word e
# Excel). Roda depois do ISCC, entao valida o que o usuario vai receber.

if ($SemSmoke) {
    Write-Warning "-SemSmoke: o smoke test dos artefatos finais foi ignorado."
}
else {
    Write-Etapa "Smoke test dos artefatos finais"

    Assert-Arquivo $SmokeTest "smoke_test_artefatos.py"

    $pythonSmoke = $PythonExe

    if (-not $pythonSmoke) {
        $candidatoSmoke = Join-Path $Raiz ".venv\Scripts\python.exe"

        if (Test-Path -LiteralPath $candidatoSmoke -PathType Leaf) {
            $pythonSmoke = $candidatoSmoke
        }
        else {
            $comandoSmoke = Get-Command "python.exe" -ErrorAction SilentlyContinue

            if ($comandoSmoke) {
                $pythonSmoke = $comandoSmoke.Source
            }
        }
    }

    if (-not $pythonSmoke -or -not (Test-Path -LiteralPath $pythonSmoke -PathType Leaf)) {
        throw "Python nao encontrado para rodar o smoke test dos artefatos: $pythonSmoke"
    }

    Push-Location -LiteralPath $Raiz

    try {
        # Sem --com-executavel: valida os tres artefatos (assinaturas,
        # .zip sem estado local nem segredos) sem abrir o .exe. O
        # aplicativo e desktop (sobe o Streamlit e nao termina sozinho),
        # e roda-lo no build depende da politica de execucao da maquina.
        & $pythonSmoke $SmokeTest --dist $Dist
        $codigoSmoke = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($codigoSmoke -ne 0) {
        throw @"
O smoke test dos artefatos finais reprovou (codigo $codigoSmoke).

Os tres artefatos foram gerados, mas nao passaram na validacao de
conteudo/imports. Veja o relatorio em build\smoke_artefatos\resumo.json.
"@
    }
}

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Build completo concluido." -ForegroundColor Green
Write-Host "  Versao:     $VersaoApp"
Write-Host "  Executavel: $ExeApp"

if (Test-Path -LiteralPath $ZipPortatil -PathType Leaf) {
    $zipMb = [math]::Round((Get-Item -LiteralPath $ZipPortatil).Length / 1MB, 1)
    Write-Host "  Portatil:   $ZipPortatil ($zipMb MB)"
}

Write-Host "  Instalador: $SetupFinal ($setupMb MB)" -ForegroundColor Green
Write-Host ""
