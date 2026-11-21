<#
.SYNOPSIS
    Compila o NexusGeo IA com PyInstaller e monta o pacote portatil (.zip).

.DESCRIPTION
    Fluxo completo do pacote portatil:

    1. valida o comprimento do caminho base (MAX_PATH do Windows), a
       versao em config.py, o .spec do PyInstaller e os arquivos de
       entrada;
    2. roda a suite offline de empacotamento
       (tests/test_packaging_offline.py) antes de compilar: se um teste
       quebrar, nenhum artefato e gerado;
    3. limpa os temporarios de builds anteriores (build\pyinstaller,
       dist\NexusGeoIA, a montagem dist\NexusGeoIA_v0.9.0_Portatil e o
       antigo dist\NexusGeoIA.exe do modo arquivo unico), preservando o
       .zip e o instalador ja gerados - exceto com -Limpar, que força um
       build do zero;
    4. executa
       .venv\Scripts\pyinstaller.exe --clean --noconfirm packaging\assistente.spec
       e gera dist\NexusGeoIA\NexusGeoIA.exe + dist\NexusGeoIA\_internal\
       (modo --onedir, sem console);
    5. monta dist\NexusGeoIA_v0.9.0_Portatil com todo o conteudo de
       dist\NexusGeoIA\ (NexusGeoIA.exe e _internal\) ao lado de
       iniciar.bat, setup_llm.py, prompts\, .streamlit\, README.md,
       PROTOCOLO_PESQUISA.md e LEIA-ME.txt (bilingue PT-BR/EN), sem
       .dsh, .venv, .git, .ruff_cache, .pytest_cache, __pycache__,
       tests, estrutura.txt, .env ou segredos;
    6. compacta em dist\NexusGeoIA_v0.9.0_Portatil.zip com tar.exe -a -c
       -f (fallback: Compress-Archive), confere a assinatura PK, a pasta
       raiz e a ausencia de itens proibidos dentro do .zip, e informa o
       tamanho final em MB.

    O modo --onedir elimina o erro "Could not create temporary
    directory!" do bootloader --onefile (que precisava criar _MEI... em
    %TEMP%), abre mais rapido e reduz falsos positivos de antivirus. No
    PyInstaller 6 o sys._MEIPASS aponta para dist\NexusGeoIA\_internal.

    O executavel NAO e aberto no build padrao: ele e um aplicativo
    desktop que sobe o Streamlit e nao termina sozinho. O modo
    --autoteste do launcher (validacao de sys._MEIPASS, imports
    criticos, Word e Excel) fica disponivel em -SmokeExe.

    app.py, prompts\, .streamlit\ e o assistente de modelos viajam
    dentro de _internal\ pelo .spec. As copias em disco na raiz do
    pacote portatil servem de referencia, deixam a montagem auditavel e
    permitem conferir a configuracao sem abrir o executavel.

.PARAMETER PythonExe
    python.exe usado no build. Padrao: .venv\Scripts\python.exe.

.PARAMETER SemTestes
    Pula a suite offline. Use apenas em diagnostico: o padrao e falhar
    antes de compilar quando algum teste quebra.

.PARAMETER SemZip
    Monta a pasta portatil e nao gera o .zip.

.PARAMETER SmokeExe
    Executa dist\NexusGeoIA.exe --autoteste depois do PyInstaller. Fica
    desligado por padrao: o executavel e um aplicativo grafico (sobe o
    Streamlit e nao termina sozinho) e roda-lo no build depende da
    politica de execucao da maquina. A validacao offline equivalente
    continua em packaging\smoke_test_artefatos.py.

.PARAMETER Limpar
    Remove o executavel, o .zip e o instalador anteriores antes de
    compilar (build do zero). Sem esta opcao os artefatos finais sao
    preservados ate serem substituidos.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1 -Limpar
#>

[CmdletBinding()]
param(
    [string]$PythonExe = "",

    [switch]$SemTestes,

    [switch]$SemZip,

    [switch]$SmokeExe,

    [switch]$Limpar
)

$ErrorActionPreference = "Stop"

# Sem barra de progresso: em terminal nao interativo (CI, terminal
# integrado com saida redirecionada) o Write-Progress do
# Compress-Archive tenta ler o buffer do console e falha com
# "Acesso negado 0x5", abortando a compactacao.
$ProgressPreference = "SilentlyContinue"

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Caminhos e identidade
# ---------------------------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $ScriptDir
$Dist = Join-Path $Raiz "dist"
$Build = Join-Path $Raiz "build"

# O PyInstaller escreve o trabalho intermediario aqui; a pasta e recriada
# a cada build e pode ser removida sem perda.
$WorkPath = Join-Path $Build "pyinstaller"

# Versao oficial lida de config.py (fonte unica da verdade): interface,
# instalador e nomes dos artefatos saem daqui.
$ConteudoConfig = Get-Content -LiteralPath (Join-Path $Raiz "config.py") -Raw
$VersaoApp = [regex]::Match(
    $ConteudoConfig,
    'APP_VERSION\s*=\s*"([^"]+)"'
).Groups[1].Value

if (-not $VersaoApp) {
    throw "APP_VERSION nao encontrado em config.py"
}

$NomeApp = "NexusGeoIA"
# Saida do PyInstaller no modo --onedir:
#   dist\NexusGeoIA\NexusGeoIA.exe  +  dist\NexusGeoIA\_internal\
$PastaApp = Join-Path $Dist $NomeApp
$ExeApp = Join-Path $PastaApp "$NomeApp.exe"
$PastaInterna = Join-Path $PastaApp "_internal"
# Executavel legado do modo --onefile. E removido na limpeza para nao
# confundir a montagem nem sobrar um binario obsoleto em dist\.
$ExeLegado = Join-Path $Dist "$NomeApp.exe"
$Staging = Join-Path $Dist "${NomeApp}_v${VersaoApp}_Portatil"
$StagingInterna = Join-Path $Staging "_internal"
$ZipFinal = Join-Path $Dist "${NomeApp}_v${VersaoApp}_Portatil.zip"
$SetupFinal = Join-Path $Dist "${NomeApp}_v${VersaoApp}_Setup.exe"
$Spec = Join-Path $ScriptDir "assistente.spec"

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

# Remove uma pasta mesmo quando o caminho passa de MAX_PATH. O
# Remove-Item do Windows PowerShell 5.1 falha nesses casos; o fallback
# usa "rd" com o prefixo \\?\ que o cmd.exe repassa ao Win32.
function Remove-PastaSegura {
    param([string]$Caminho)

    if (-not (Test-Path -LiteralPath $Caminho)) {
        return
    }

    try {
        Remove-Item -LiteralPath $Caminho -Recurse -Force -ErrorAction Stop
        return
    }
    catch {
        Write-Verbose "Remove-Item falhou; tentando rd com caminho longo: $Caminho"
    }

    & cmd.exe /c rd /s /q "\\?\$Caminho" | Out-Null
}

# Recusa remover qualquer caminho que escape da raiz do projeto.
function Assert-DentroDoProjeto {
    param([string]$Caminho)

    $resolvido = (Resolve-Path -LiteralPath $Caminho).Path
    $raizResolvida = (Resolve-Path -LiteralPath $Raiz).Path

    if (-not $resolvido.StartsWith($raizResolvida, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusando remover caminho fora do projeto: $resolvido"
    }
}

# Copia uma pasta publicavel sem caches, testes, estado local nem
# segredos. robocopy e usado porque lida bem com arvores grandes e
# devolve codigos distintos para "copiou" e "falhou".
#
# -ManterCertificados existe para a copia do pacote --onedir: o
# _internal\certifi\cacert.pem e uma CA publica necessaria ao HTTPS e
# era removido pelo filtro "*.pem" (foi assim que o pacote portatil
# ficou sem o certificado mesmo com o dist\NexusGeoIA correto). Para as
# pastas do projeto (prompts\, .streamlit\) o filtro continua valendo e
# a varredura de segredos abaixo confere o resultado.
function Copy-PastaPublicavel {
    param(
        [string]$Origem,
        [string]$DestinoPasta,
        [switch]$ManterCertificados
    )

    New-Item -ItemType Directory -Force -Path $DestinoPasta | Out-Null

    $exclusoesArquivo = @(
        "*.pyc",
        "*.pyo",
        "secrets.toml",
        ".env",
        ".env.*",
        "*.env",
        "*.key",
        "*.p12",
        "*.pfx"
    )

    if (-not $ManterCertificados) {
        $exclusoesArquivo += "*.pem"
    }

    $argumentos = @(
        $Origem,
        $DestinoPasta,
        "/E",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/XD",
        "__pycache__",
        ".git",
        ".dsh",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
        "/XF"
    ) + $exclusoesArquivo

    & robocopy @argumentos | Out-Null

    if ($LASTEXITCODE -ge 8) {
        throw "robocopy falhou (codigo $LASTEXITCODE) ao copiar $Origem"
    }
}

# Compacta uma pasta em .zip preservando a pasta raiz dentro do arquivo.
#
# Preferencia pelo tar.exe (bsdtar) que acompanha o Windows 10 1803+ e o
# Windows 11: ele e ordens de grandeza mais rapido que o Compress-Archive
# do PowerShell 5.1 em arvores grandes (o bundle chega a dezenas de
# milhares de arquivos) e nao passa pelo pipeline de objetos .NET, que
# estoura memoria e tempo no Windows PowerShell. O Compress-Archive
# continua como fallback quando o tar.exe nao existe (Windows Server
# antigo) ou quando ele termina com erro.
#
# ``tar -a`` infere o formato pela extensao do arquivo (``.zip``) e
# ``-C`` muda a raiz para os caminhos sairem relativos: o .zip extrai
# uma pasta ``NexusGeoIA_v0.9.0_Portatil\`` em vez de despejar tudo na
# pasta atual. Devolve o nome do motor usado.
function Invoke-CompactacaoZip {
    param([string]$Origem, [string]$Destino)

    if (Test-Path -LiteralPath $Destino) {
        Remove-Item -LiteralPath $Destino -Force
    }

    $tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue

    if ($tar) {
        $pai = Split-Path -Parent $Origem
        $folha = Split-Path -Leaf $Origem

        Write-Host "    Motor: tar.exe ($($tar.Source))"

        & $tar.Source -a -c -f $Destino -C $pai $folha
        $codigoTar = $LASTEXITCODE

        $gerou = (Test-Path -LiteralPath $Destino -PathType Leaf) -and
            ((Get-Item -LiteralPath $Destino).Length -gt 0)

        if ($codigoTar -eq 0 -and $gerou) {
            return "tar.exe"
        }

        Write-Warning "tar.exe falhou (codigo $codigoTar); usando Compress-Archive."

        if (Test-Path -LiteralPath $Destino) {
            Remove-Item -LiteralPath $Destino -Force
        }
    }
    else {
        Write-Host "    tar.exe indisponivel; usando Compress-Archive."
    }

    # Compress-Archive precisa da pasta como -LiteralPath para incluir a
    # propria pasta raiz, e nao apenas o conteudo, dentro do .zip.
    Compress-Archive -LiteralPath $Origem -DestinationPath $Destino -CompressionLevel Optimal -Force

    return "Compress-Archive"
}

# ---------------------------------------------------------------------------
# Validacao do caminho (MAX_PATH)
# ---------------------------------------------------------------------------
#
# O MAX_PATH classico do Windows limita a 260 caracteres. A extracao do
# .zip pelo Explorer e o proprio PyInstaller (build\pyinstaller\...)
# acrescentam dezenas de caracteres ao caminho base; acima de 100 ja
# sobra pouca margem para a arvore de build e para as pastas internas do
# bundle. O build continua, mas avisa antes de gastar minutos.

$LIMITE_CAMINHO_BASE = 100
$LIMITE_CAMINHO_ARTEFATO = 180

Write-Etapa "Validando o caminho do projeto"

Write-Host "    Raiz: $Raiz ($($Raiz.Length) caracteres)"

$avisosCaminho = @()

if ($Raiz.Length -gt $LIMITE_CAMINHO_BASE) {
    $avisosCaminho += @(
        "O caminho base tem $($Raiz.Length) caracteres (limite recomendado: $LIMITE_CAMINHO_BASE).",
        "O MAX_PATH do Windows (260) pode ser atingido ao extrair o .zip ou",
        "ao compilar com o PyInstaller. Prefira um caminho curto, por exemplo",
        "C:\NexusGeoIA, se o build falhar com erro de caminho longo."
    )
}

if ($Staging.Length -gt $LIMITE_CAMINHO_ARTEFATO) {
    $avisosCaminho += "A pasta de montagem tem $($Staging.Length) caracteres; extracao do .zip pode falhar no Explorer."
}

if ($WorkPath.Length -gt $LIMITE_CAMINHO_ARTEFATO) {
    $avisosCaminho += "A pasta de trabalho do PyInstaller tem $($WorkPath.Length) caracteres; o build pode falhar no MAX_PATH."
}

foreach ($aviso in $avisosCaminho) {
    Write-Warning $aviso
}

# ---------------------------------------------------------------------------
# Validacoes iniciais
# ---------------------------------------------------------------------------

Write-Etapa "Validando o projeto e a especificacao do PyInstaller"

Assert-Arquivo (Join-Path $Raiz "app.py") "app.py"
Assert-Arquivo (Join-Path $Raiz "config.py") "config.py"
Assert-Arquivo (Join-Path $Raiz "launcher_desktop.py") "launcher_desktop.py"
Assert-Arquivo (Join-Path $Raiz "setup_llm.py") "setup_llm.py"
Assert-Arquivo (Join-Path $Raiz "iniciar.bat") "iniciar.bat"
Assert-Arquivo $Spec "assistente.spec"

$ConteudoSpec = Get-Content -LiteralPath $Spec -Raw

# O nome do executavel do .spec precisa bater com o que o instalador
# (packaging\installer.iss) embute e com o que este script publica.
if ($ConteudoSpec -notmatch ('name="' + $NomeApp + '"')) {
    throw "assistente.spec nao gera $NomeApp.exe: name=`"$NomeApp`" ausente."
}

if ($ConteudoSpec -notmatch 'launcher_desktop\.py') {
    throw "assistente.spec nao usa launcher_desktop.py como ponto de entrada."
}

# O empacotamento e --onedir: EXE com exclude_binaries=True seguido de
# COLLECT. Sem isso o .spec volta ao arquivo unico e o bootloader tenta
# criar _MEI... em %TEMP% (origem do erro "Could not create temporary
# directory!" em maquinas com %TEMP% restrito).
if ($ConteudoSpec -notmatch 'exclude_binaries\s*=\s*True') {
    throw "assistente.spec nao esta no modo --onedir: exclude_binaries=True ausente."
}

if ($ConteudoSpec -notmatch 'COLLECT\(') {
    throw "assistente.spec nao chama COLLECT(...): o pacote --onedir nao seria gravado."
}

if ($ConteudoSpec -notmatch 'contents_directory\s*=\s*"_internal"') {
    throw 'assistente.spec nao grava os dados em _internal (contents_directory="_internal").'
}

# O .spec precisa embutir os dados lidos por caminho em tempo de execucao.
foreach ($dadoEmbutido in @('RAIZ / "app.py"', 'RAIZ / "prompts"', 'RAIZ / ".streamlit"')) {
    if (-not $ConteudoSpec.Contains($dadoEmbutido)) {
        throw "assistente.spec nao embute o dado obrigatorio: $dadoEmbutido"
    }
}

# Bug corrigido: sem o cacert.pem do certifi em _internal\certifi o
# import de services.llm_service (ollama -> httpx -> ssl) falha com
# FileNotFoundError no executavel congelado. O build aborta se a coleta
# sair da especificacao.
if ($ConteudoSpec -notmatch 'collect_data_files\("certifi"\)') {
    throw "assistente.spec nao coleta o certifi (collect_data_files(""certifi""))."
}

if ($ConteudoSpec -notmatch 'certifi/cacert\.pem') {
    throw "assistente.spec nao valida certifi/cacert.pem no bundle."
}

# O iniciar.bat do pacote portatil precisa saber abrir o executavel e
# manter os dados gravaveis ao lado da pasta extraida.
$ConteudoIniciar = Get-Content -LiteralPath (Join-Path $Raiz "iniciar.bat") -Raw

if ($ConteudoIniciar -notmatch "NexusGeoIA\.exe") {
    throw "iniciar.bat nao abre $NomeApp.exe na pasta portatil."
}

if ($ConteudoIniciar -notmatch "ASSISTENTE_DATA_DIR") {
    throw "iniciar.bat nao define ASSISTENTE_DATA_DIR para a pasta portatil."
}

# O caminho de desenvolvimento (sem executavel) continua precisando da
# abertura automatica do navegador e da porta dinamica.
if ($ConteudoIniciar -notmatch "--server\.headless=false") {
    throw "iniciar.bat perdeu --server.headless=false (o navegador nao abriria)."
}

if ($ConteudoIniciar -notmatch "--server\.port=%PORTA%") {
    throw "iniciar.bat usa porta fixa: --server.port=%PORTA% ausente."
}

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
New-Item -ItemType Directory -Force -Path $Build | Out-Null

# ---------------------------------------------------------------------------
# Python do build
# ---------------------------------------------------------------------------

Write-Etapa "Localizando o Python do build"

if (-not $PythonExe) {
    $candidato = Join-Path $Raiz ".venv\Scripts\python.exe"

    if (Test-Path -LiteralPath $candidato -PathType Leaf) {
        $PythonExe = $candidato
    }
    else {
        $comando = Get-Command "python.exe" -ErrorAction SilentlyContinue

        if ($comando) {
            $PythonExe = $comando.Source
        }
    }
}

if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw @"
Python nao encontrado. Crie o ambiente virtual ou informe -PythonExe:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
"@
}

$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$PythonDir = Split-Path -Parent $PythonExe
$PyInstallerExe = Join-Path $PythonDir "pyinstaller.exe"

Write-Host "    Python: $PythonExe"

& $PythonExe -c "import sys; print('    Versao: %d.%d.%d' % sys.version_info[:3])"

# ---------------------------------------------------------------------------
# PyInstaller
# ---------------------------------------------------------------------------

Write-Etapa "Verificando o PyInstaller"

& $PythonExe -c "import PyInstaller; print('    PyInstaller: ' + PyInstaller.__version__)" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "    PyInstaller ausente; instalando..."
    & $PythonExe -m pip install --upgrade pyinstaller

    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar o PyInstaller (codigo $LASTEXITCODE)"
    }
}

# Preferencia: o launcher pyinstaller.exe do .venv (o mesmo que o
# usuario chamaria na mao). Sem ele, cai para "python -m PyInstaller".
$executavelPyInstaller = $PythonExe
$prefixoPyInstaller = @("-m", "PyInstaller")

if (Test-Path -LiteralPath $PyInstallerExe -PathType Leaf) {
    $executavelPyInstaller = $PyInstallerExe
    $prefixoPyInstaller = @()
    Write-Host "    Launcher: $PyInstallerExe"
}
else {
    Write-Warning "pyinstaller.exe ausente em $PythonDir; usando 'python -m PyInstaller'."
}

# ---------------------------------------------------------------------------
# Suite offline de empacotamento
# ---------------------------------------------------------------------------
#
# O recorte pedido e tests/test_packaging_offline.py, executado com o
# Python do .venv (o mesmo interpretador do build). Qualquer falha
# interrompe o build antes de gastar minutos no PyInstaller.

if (-not $SemTestes) {
    Write-Etapa "Rodando a suite offline de empacotamento"

    $argumentosTeste = @(
        "-m",
        "unittest",
        "tests/test_packaging_offline.py"
    )

    Push-Location -LiteralPath $Raiz

    try {
        & $PythonExe @argumentosTeste
        $codigoTestes = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($codigoTestes -ne 0) {
        throw @"
A suite tests/test_packaging_offline.py falhou (codigo $codigoTestes).

O build foi interrompido e nenhum artefato novo foi gerado. Corrija os
testes ou, em diagnostico, rode com -SemTestes.
"@
    }

    Write-Host "    Testes de empacotamento: OK"
}
else {
    Write-Warning "-SemTestes: a suite de empacotamento foi ignorada neste build."
}

# ---------------------------------------------------------------------------
# Limpeza dos temporarios de builds anteriores
# ---------------------------------------------------------------------------
#
# Sempre remove o trabalho intermediario e a montagem anterior (sao
# recriaveis). Com -Limpar remove tambem os artefatos finais, forçando um
# build do zero. Sem -Limpar, executavel/.zip/instalador antigos ficam no
# lugar ate serem substituidos no fim.

Write-Etapa "Limpando temporarios de builds anteriores"

foreach ($alvo in @($WorkPath, $Staging, $PastaApp, $ExeLegado)) {
    if (Test-Path -LiteralPath $alvo) {
        Assert-DentroDoProjeto $alvo
        Remove-PastaSegura $alvo
        Write-Host "    Removido: $alvo"
    }
}

if ($Limpar) {
    foreach ($alvo in @($ExeApp, $ZipFinal, $SetupFinal)) {
        if (Test-Path -LiteralPath $alvo) {
            Remove-Item -LiteralPath $alvo -Force
            Write-Host "    Removido (artefato final): $alvo"
        }
    }
}

# ---------------------------------------------------------------------------
# Dados do RapidOCR (config.yaml e modelos ONNX)
# ---------------------------------------------------------------------------
#
# O RapidOCR resolve os proprios .yaml e modelos ONNX por caminho dentro
# do pacote. No pacote --onedir eles precisam ir para _internal; sem isso
# o Omegaconf levanta FileNotFoundError e o OCR derruba o app. A coleta
# efetiva fica em packaging\assistente.spec
# (collect_data_files), unico caminho aceito pelo PyInstaller quando um
# .spec e fornecido. O equivalente na linha de comando seria
# --collect-data rapidocr (pacote atual) ou --collect-data
# rapidocr_onnxruntime (pacote legado, Python < 3.13); passar a flag
# junto do .spec faz o PyInstaller abortar com "makespec options not
# valid when a .spec file is given". Por isso o script apenas confere os
# dados aqui.

Write-Etapa "Conferindo os dados do RapidOCR"

$pacotesOcrInstalados = @()

foreach ($pacoteOcr in @("rapidocr", "rapidocr_onnxruntime")) {
    & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$pacoteOcr') else 1)" 2>$null

    if ($LASTEXITCODE -ne 0) {
        continue
    }

    $pacotesOcrInstalados += $pacoteOcr

    $quantidadeDados = & $PythonExe -c "from PyInstaller.utils.hooks import collect_data_files; print(len(collect_data_files('$pacoteOcr')))" 2>$null

    if ($LASTEXITCODE -ne 0 -or [int]$quantidadeDados -le 0) {
        Write-Warning "Nenhum arquivo de dados em $pacoteOcr; o OCR pode ficar indisponivel no executavel."
    }
    else {
        Write-Host "    $pacoteOcr`: $quantidadeDados arquivo(s) de dados"
    }
}

if ($pacotesOcrInstalados.Count -eq 0) {
    Write-Warning "RapidOCR nao instalado neste ambiente; o executavel sera gerado sem OCR."
}

# ---------------------------------------------------------------------------
# Dados do python-docx (modelo do Parecer Tecnico)
# ---------------------------------------------------------------------------
#
# ``docx.Document()`` sem argumento abre ``docx/templates/default.docx``
# do disco. No pacote --onedir esse arquivo precisa ir para _internal;
# sem ele o botao "Exportar Parecer Tecnico" levanta
# FileNotFoundError mesmo com o pacote instalado. A coleta fica no .spec
# e aqui ela e conferida: se o nome do modulo estiver errado (o pacote
# importa como ``docx``, mas a distribuicao se chama ``python-docx``), o
# PyInstaller so avisa "not a package" e o build passaria sem o modelo.

Write-Etapa "Conferindo os dados do python-docx"

& $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('docx') else 1)" 2>$null

if ($LASTEXITCODE -eq 0) {
    $modeloDocx = & $PythonExe -c @"
from PyInstaller.utils.hooks import collect_data_files
dados = collect_data_files('docx')
print(sum(1 for origem, _ in dados if origem.replace(chr(92), '/').endswith('docx/templates/default.docx')))
"@ 2>$null

    if ([int]$modeloDocx -lt 1) {
        throw @"
O modelo docx/templates/default.docx nao foi coletado.

Sem ele o executavel gera erro ao exportar o Parecer Tecnico em Word.
Confira a tupla PACOTES_DOCUMENTO em packaging\assistente.spec: o
primeiro item precisa ser o nome IMPORTADO ("docx"), nao o da
distribuicao ("python-docx").
"@
    }

    Write-Host "    docx/templates/default.docx: OK"
}
else {
    Write-Warning "python-docx nao instalado; o executavel sera gerado sem o Parecer em Word."
}

# ---------------------------------------------------------------------------
# Compilacao do executavel
# ---------------------------------------------------------------------------

Write-Etapa "Compilando o executavel com PyInstaller"

$argumentosPyInstaller = @(
    "--clean",
    "--noconfirm",
    "--distpath",
    $Dist,
    "--workpath",
    $WorkPath,
    "packaging\assistente.spec"
)

Push-Location -LiteralPath $Raiz

try {
    & $executavelPyInstaller @prefixoPyInstaller @argumentosPyInstaller
    $codigoPyInstaller = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($codigoPyInstaller -ne 0) {
    throw "PyInstaller falhou (codigo $codigoPyInstaller)"
}

Assert-Arquivo $ExeApp "Executavel gerado (dist\$NomeApp\$NomeApp.exe)"

if (-not (Test-Path -LiteralPath $PastaInterna -PathType Container)) {
    throw "PyInstaller nao gerou a pasta $PastaInterna (modo --onedir incompleto)."
}

# O _internal precisa trazer os recursos lidos por caminho: o
# sys._MEIPASS do modo --onedir aponta para ele. O certifi/cacert.pem e
# obrigatorio: sem ele o import de services.llm_service quebra no boot.
foreach ($recursoInterno in @("app.py", "prompts\system_base.txt", ".streamlit\config.toml", "certifi\cacert.pem")) {
    $caminhoRecurso = Join-Path $PastaInterna $recursoInterno

    if (-not (Test-Path -LiteralPath $caminhoRecurso -PathType Leaf)) {
        throw "Recurso ausente em _internal: $caminhoRecurso"
    }
}

# Assinatura MZ: confirma que o PyInstaller gerou um PE valido e nao um
# arquivo truncado (o que passaria apenas pelo teste de existencia).
$assinatura = Get-Content -LiteralPath $ExeApp -Encoding Byte -TotalCount 2

if ($assinatura.Count -lt 2 -or $assinatura[0] -ne 77 -or $assinatura[1] -ne 90) {
    throw "O executavel gerado nao comeca com a assinatura MZ de um PE valido."
}

$exeMb = [math]::Round((Get-Item -LiteralPath $ExeApp).Length / 1MB, 1)
$tamanhoPastaAppMb = [math]::Round(
    (Get-ChildItem -LiteralPath $PastaApp -Recurse -File |
        Measure-Object -Property Length -Sum).Sum / 1MB,
    1
)

Write-Host "    Executavel: $ExeApp ($exeMb MB)"
Write-Host "    Pacote onedir: $PastaApp ($tamanhoPastaAppMb MB com _internal)"

# ---------------------------------------------------------------------------
# Smoke test do executavel (opcional, -SmokeExe)
# ---------------------------------------------------------------------------
#
# O executavel e um aplicativo desktop (subsistema grafico, console=False)
# que, no uso normal, sobe o Streamlit e nao termina sozinho. O modo
# ``--autoteste`` existe para validar o bundle e sair, mas executar um
# binario durante o build depende da politica de execucao da maquina
# (antivirus, permissao, GPO). Por isso essa etapa e OPT-IN: o build
# padrao nunca abre o .exe.
#
# A validacao offline equivalente (assinaturas, conteudo do .zip e imports
# criticos a partir do codigo-fonte) roda em
# packaging\smoke_test_artefatos.py e em tests/test_packaging_offline.py.
#
# Quando usado, o autoteste valida os recursos em sys._MEIPASS (que no
# --onedir aponta para _internal), os imports criticos e gera um .docx e
# um .xlsx de verdade - exatamente os caminhos que quebram sem aviso no
# build.
#
# No modo --onedir nao ha extracao de _MEI... a cada execucao; o limite
# abaixo cobre com folga a inicializacao do pacote em disco lento.

$relatorioSmoke = Join-Path $Build "smoke_autoteste.json"

if (-not $SmokeExe) {
    Write-Etapa "Smoke test do executavel: ignorado (use -SmokeExe)"

    Write-Host "    O .exe nao e executado no build padrao (aplicativo grafico)."
    Write-Host "    Validacao offline: packaging\smoke_test_artefatos.py."
}
else {
    Write-Etapa "Smoke test do executavel (--autoteste)"

    # Tempo maximo do autoteste. No --onedir o bootloader nao extrai o
    # bundle; o limite existe para nao deixar o build travado se um
    # import de DLL ou o antivirus segurar o processo.
    $TIMEOUT_SMOKE = 1800

    if (Test-Path -LiteralPath $relatorioSmoke) {
        Remove-Item -LiteralPath $relatorioSmoke -Force
    }

    $smokeReportAnterior = $env:ASSISTENTE_SMOKE_REPORT
    $smokeDadosAnterior = $env:ASSISTENTE_DATA_DIR

    $env:ASSISTENTE_SMOKE_REPORT = $relatorioSmoke
    # Pasta de dados isolada: o autoteste nao toca no perfil do usuario.
    $env:ASSISTENTE_DATA_DIR = Join-Path $Build "smoke_dados"

    try {
        # Sem -Wait: o autoteste valida _internal, imports e geracao de
        # Word/Excel. Wait-Process com timeout garante que um travamento
        # nao deixe o build parado para sempre.
        $processoSmoke = Start-Process `
            -FilePath $ExeApp `
            -ArgumentList "--autoteste" `
            -PassThru `
            -WindowStyle Hidden

        $cronometroSmoke = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            $processoSmoke | Wait-Process -Timeout $TIMEOUT_SMOKE -ErrorAction Stop
            $codigoSmoke = $processoSmoke.ExitCode
        }
        catch {
            Write-Warning "O autoteste excedeu $TIMEOUT_SMOKE s; encerrando o processo."

            try {
                Stop-Process -Id $processoSmoke.Id -Force -ErrorAction Stop
            }
            catch {
                Write-Verbose "O processo do autoteste ja havia terminado."
            }

            $codigoSmoke = -2
        }

        $cronometroSmoke.Stop()

        Write-Host "    Tempo do autoteste: $([math]::Round($cronometroSmoke.Elapsed.TotalSeconds, 1)) s"
    }
    finally {
        $env:ASSISTENTE_SMOKE_REPORT = $smokeReportAnterior
        $env:ASSISTENTE_DATA_DIR = $smokeDadosAnterior
    }

    if ($codigoSmoke -eq -2) {
        $parcialSmoke = ""

        if (Test-Path -LiteralPath $relatorioSmoke -PathType Leaf) {
            $parcialSmoke = (Get-Content -LiteralPath $relatorioSmoke -Raw).Trim()
        }

        throw @"
O autoteste do executavel excedeu $TIMEOUT_SMOKE s e foi encerrado.

O pacote portatil NAO foi montado e o .zip NAO foi gerado.

Ultimo relatorio parcial gravado (mostra onde o teste parou):
$parcialSmoke
"@
    }

    if ($codigoSmoke -ne 0) {
        $detalheSmoke = ""

        if (Test-Path -LiteralPath $relatorioSmoke -PathType Leaf) {
            $detalheSmoke = (Get-Content -LiteralPath $relatorioSmoke -Raw).Trim()
        }

        throw @"
O autoteste do executavel falhou (codigo $codigoSmoke).

O .exe foi compilado, mas nao passou na validacao de recursos/imports.
O pacote portatil NAO foi montado e o .zip NAO foi gerado.

Relatorio do autoteste:
$detalheSmoke
"@
    }

    Assert-Arquivo $relatorioSmoke "Relatorio do autoteste"

    $relatorioSmokeJson = Get-Content -LiteralPath $relatorioSmoke -Raw | ConvertFrom-Json

    if (-not $relatorioSmokeJson.ok) {
        $falhasSmoke = ($relatorioSmokeJson.falhas -join "; ")

        throw "O autoteste do executavel reprovou: $falhasSmoke"
    }

    foreach ($verificacao in $relatorioSmokeJson.verificacoes) {
        Write-Host "    OK: $($verificacao.nome)"
    }

    Write-Host "    Bundle: $($relatorioSmokeJson.base_recursos)"
}

# ---------------------------------------------------------------------------
# Montagem do pacote portatil
# ---------------------------------------------------------------------------

Write-Etapa "Montando $Staging"

New-Item -ItemType Directory -Force -Path $Staging | Out-Null

# Todo o conteudo do pacote --onedir vai para a raiz do staging:
# NexusGeoIA.exe + _internal\. O Copy-PastaPublicavel aplica a mesma
# higiene (caches, testes, estado local e segredos) e usa robocopy para
# lidar com a arvore grande de _internal. -ManterCertificados preserva
# o cacert.pem do certifi, que e dado publico do bundle e nao segredo.
Copy-PastaPublicavel $PastaApp $Staging -ManterCertificados
Copy-Item -LiteralPath (Join-Path $Raiz "iniciar.bat") -Destination (Join-Path $Staging "iniciar.bat") -Force
Copy-Item -LiteralPath (Join-Path $Raiz "setup_llm.py") -Destination (Join-Path $Staging "setup_llm.py") -Force

# Documentacao de metodo e visao geral que acompanham o binario. A lista
# $arquivos e a fonte unica das copias avulsas: o README.md apresenta a
# aplicacao e o PROTOCOLO_PESQUISA.md registra o fluxo de validacao
# cruzada entre familias de LLMs (auditoria adversarial, contraprova e
# linhagem). O build falha se qualquer um dos dois sumir.
$protocolo = Join-Path $Raiz "PROTOCOLO_PESQUISA.md"

Assert-Arquivo $protocolo "PROTOCOLO_PESQUISA.md"

$arquivos = @(
    "README.md",
    "PROTOCOLO_PESQUISA.md"
)

foreach ($arquivo in $arquivos) {
    $origem = Join-Path $Raiz $arquivo

    Assert-Arquivo $origem $arquivo
    Copy-Item -LiteralPath $origem -Destination (Join-Path $Staging $arquivo) -Force
}

Copy-PastaPublicavel (Join-Path $Raiz "prompts") (Join-Path $Staging "prompts")
Copy-PastaPublicavel (Join-Path $Raiz ".streamlit") (Join-Path $Staging ".streamlit")

# Documento de apoio: o executavel ja traz tudo embutido, mas o .zip
# precisa explicar a montagem e o destino dos dados. O texto e bilingue:
# o bloco em portugues vem primeiro e a versao em ingles (EN) logo
# abaixo, para o mesmo .zip servir aos dois idiomas da interface.
$leiaMe = @"
NexusGeo IA v$VersaoApp - pacote portatil

1. Instale o Ollama (https://ollama.com/download/windows) e mantenha-o aberto.
2. Extraia este .zip em uma pasta curta (ex.: C:\NexusGeoIA) para evitar o
   limite de caminho do Windows.
3. Execute iniciar.bat.

O iniciar.bat define ASSISTENTE_DATA_DIR para a propria pasta do pacote e
abre NexusGeoIA.exe, que escolhe a primeira porta livre a partir de 8501 e
abre o navegador. Historico, documentos, banco SQLite e config_local.json
ficam em data\ e database\ ao lado do executavel; a pasta pode ser copiada
para outro computador com Windows x64 (o Ollama precisa estar instalado).
Se a pasta do pacote nao for gravavel (por exemplo, C:\Program Files), o
launcher usa %LOCALAPPDATA%\NexusGeoIA como fallback automaticamente.

Conteudo do pacote:

  NexusGeoIA.exe  carregador do aplicativo (modo --onedir do PyInstaller).
  _internal\      bibliotecas, app.py, prompts\ e .streamlit\ de runtime;
                  mantenha esta pasta sempre ao lado de NexusGeoIA.exe.
  iniciar.bat     abre o executavel e fixa a pasta de dados.
  setup_llm.py    copia de referencia do assistente de modelos; para usa-lo
                  no dia a dia prefira: NexusGeoIA.exe --setup-modelo
  PROTOCOLO_PESQUISA.md  protocolo de validacao cientifica e mitigacao de
                  vies entre familias de LLMs (auditoria cruzada, fontes,
                  citacao e parecer tecnico).
  README.md       visao geral, instalacao e uso do aplicativo.
  prompts\        copia de referencia do system prompt padrao.
  .streamlit\     copia de referencia da configuracao do Streamlit.

Para trocar ou adicionar modelos depois:
    NexusGeoIA.exe --setup-modelo

Para conferir a integridade do pacote (sem abrir janela nem navegador):
    NexusGeoIA.exe --autoteste

---------------------------------------------------------------------------
NexusGeo IA v$VersaoApp - portable package (English)

1. Install Ollama (https://ollama.com/download/windows) and keep it running.
2. Extract this .zip into a short folder path (e.g. C:\NexusGeoIA) to stay
   clear of the Windows path length limit.
3. Run iniciar.bat.

iniciar.bat sets ASSISTENTE_DATA_DIR to this package folder and starts
NexusGeoIA.exe, which picks the first free port from 8501 upwards and opens
the browser. History, documents, the SQLite database and config_local.json
live in data\ and database\ next to the executable, so the whole folder can
be copied to another Windows x64 computer (Ollama must be installed there).

Conteudo do pacote (English):

  NexusGeoIA.exe  application loader (PyInstaller --onedir build).
  _internal\      runtime libraries, app.py, prompts\ and .streamlit\;
                  always keep this folder next to NexusGeoIA.exe.
  iniciar.bat     starts the executable and pins the data folder.
  setup_llm.py    reference copy of the model assistant; day to day prefer:
                  NexusGeoIA.exe --setup-modelo
  PROTOCOLO_PESQUISA.md  scientific validation and LLM-family bias
                  mitigation protocol (cross-audit, sources, citation and
                  technical report).
  README.md       overview, installation and usage of the application.
  prompts\        reference copy of the default system prompt.
  .streamlit\     reference copy of the Streamlit configuration.

To change or add models later:
    NexusGeoIA.exe --setup-modelo

To check package integrity (no window and no browser):
    NexusGeoIA.exe --autoteste
"@

Set-Content -LiteralPath (Join-Path $Staging "LEIA-ME.txt") -Value $leiaMe -Encoding ASCII

# ---------------------------------------------------------------------------
# Validacoes da montagem
# ---------------------------------------------------------------------------

Write-Etapa "Validando a montagem"

$conteudoEsperado = @(
    "$NomeApp.exe",
    "_internal",
    "iniciar.bat",
    "setup_llm.py",
    "LEIA-ME.txt",
    "README.md",
    "PROTOCOLO_PESQUISA.md",
    "prompts",
    ".streamlit"
)

foreach ($item in $conteudoEsperado) {
    $caminhoItem = Join-Path $Staging $item

    if (-not (Test-Path -LiteralPath $caminhoItem)) {
        throw "Montagem incompleta: $item ausente em $Staging"
    }
}

# O _internal e a saida do PyInstaller: precisa continuar ao lado do .exe
# e conter os recursos lidos por caminho (sys._MEIPASS no --onedir),
# incluindo o certificado TLS usado pelo httpx/ollama.
foreach ($recursoPortatil in @("app.py", "prompts\system_base.txt", ".streamlit\config.toml", "certifi\cacert.pem")) {
    $caminhoRecursoPortatil = Join-Path $StagingInterna $recursoPortatil

    if (-not (Test-Path -LiteralPath $caminhoRecursoPortatil -PathType Leaf)) {
        throw "Recurso ausente no pacote portatil: $caminhoRecursoPortatil"
    }
}

$proibidos = @(
    "tests",
    ".dsh",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    ".env",
    "estrutura.txt",
    "config_local.json",
    "secrets.toml"
)

foreach ($proibido in $proibidos) {
    if (Test-Path -LiteralPath (Join-Path $Staging $proibido)) {
        throw "Item que deveria ser ignorado apareceu na montagem: $proibido"
    }
}

# _internal carrega os certificados CA das dependencias (por exemplo
# certifi\cacert.pem), que sao dados publicos do bundle e nao segredos do
# projeto. A varredura de segredos vale para o que publicamos fora dele:
# raiz do pacote, prompts\ e .streamlit\.
$prefixoInterno = $StagingInterna +
    [System.IO.Path]::DirectorySeparatorChar

$arquivosSuspeitos = Get-ChildItem -LiteralPath $Staging -Recurse -File -Force |
    Where-Object {
        -not $_.FullName.StartsWith(
            $prefixoInterno,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and (
            $_.Extension -in @(".pem", ".key", ".p12", ".pfx") -or
            $_.Name -eq ".env" -or
            $_.Name -like ".env.*"
        )
    }

if ($arquivosSuspeitos) {
    $lista = ($arquivosSuspeitos | ForEach-Object { $_.FullName }) -join "; "

    throw "Arquivo sensivel apareceu na montagem: $lista"
}

$pastasTemporarias = Get-ChildItem -LiteralPath $Staging -Directory -Filter "tmp*" -ErrorAction SilentlyContinue

if ($pastasTemporarias) {
    throw "Pastas temporarias tmp* apareceram na montagem"
}

# ---------------------------------------------------------------------------
# Zip final
# ---------------------------------------------------------------------------

$tamanhoStagingMb = [math]::Round(
    (Get-ChildItem -LiteralPath $Staging -Recurse -File |
        Measure-Object -Property Length -Sum).Sum / 1MB,
    1
)

$zipMb = $null
$motorZip = $null

if (-not $SemZip) {
    Write-Etapa "Gerando $ZipFinal"

    $motorZip = Invoke-CompactacaoZip -Origem $Staging -Destino $ZipFinal

    Assert-Arquivo $ZipFinal "Zip final"

    # Assinatura PK\x03\x04: confirma que o .zip foi realmente gravado e
    # nao ficou um arquivo vazio ou truncado por falha de compactacao.
    $assinaturaZip = Get-Content -LiteralPath $ZipFinal -Encoding Byte -TotalCount 4

    if ($assinaturaZip.Count -lt 4 -or
        $assinaturaZip[0] -ne 80 -or
        $assinaturaZip[1] -ne 75 -or
        $assinaturaZip[2] -ne 3 -or
        $assinaturaZip[3] -ne 4) {
        throw "O .zip gerado nao comeca com a assinatura PK de um arquivo ZIP valido."
    }

    # O .zip precisa conter a pasta raiz e nenhum item proibido: a
    # extracao pelo Explorer nao deve despejar arquivos soltos nem
    # carregar estado local para a maquina de destino.
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $arquivoZip = [System.IO.Compression.ZipFile]::OpenRead($ZipFinal)

    try {
        $entradasZip = @($arquivoZip.Entries | ForEach-Object { $_.FullName })
    }
    finally {
        $arquivoZip.Dispose()
    }

    $raizZip = (Split-Path -Leaf $Staging) + "/"

    if (-not ($entradasZip | Where-Object { $_.StartsWith($raizZip) })) {
        throw "O .zip nao preserva a pasta raiz $raizZip; a extracao ficaria solta."
    }

    $padroesProibidosZip = @(
        "(^|/)(\.dsh|\.git|\.ruff_cache|\.pytest_cache|__pycache__|tests|\.venv)(/|$)",
        "(^|/)\.env(\.|$|/)",
        "(^|/)(estrutura\.txt|config_local\.json|secrets\.toml)$",
        "(^|/)tmp[^/]*/"
    )

    foreach ($padraoZip in $padroesProibidosZip) {
        $encontrados = @($entradasZip | Where-Object { $_ -match $padraoZip })

        if ($encontrados.Count -gt 0) {
            $exemplo = $encontrados[0]

            throw "O .zip contem item proibido ($($encontrados.Count) ocorrencia(s)): $exemplo"
        }
    }

    Write-Host "    Entradas no .zip: $($entradasZip.Count)"

    $zipMb = [math]::Round((Get-Item -LiteralPath $ZipFinal).Length / 1MB, 1)
}
else {
    Write-Warning "-SemZip: a pasta portatil foi montada e o .zip nao foi gerado."
}

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Pacote portatil concluido." -ForegroundColor Green
Write-Host "  Versao: $VersaoApp"
Write-Host "  Executavel: $ExeApp ($exeMb MB)"
Write-Host "  Pacote onedir: $PastaApp ($tamanhoPastaAppMb MB)"
Write-Host "  Pasta: $Staging ($tamanhoStagingMb MB)"

if ($zipMb) {
    Write-Host "  Zip: $ZipFinal ($zipMb MB) [$motorZip]" -ForegroundColor Green
}

Write-Host ""
Write-Host "Para testar: extraia o .zip (ou abra a pasta) e execute iniciar.bat" -ForegroundColor Yellow
Write-Host ""
