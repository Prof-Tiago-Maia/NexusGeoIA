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
       dist\NexusGeoIA, a montagem dist\NexusGeoIA_v1.0.0_Portatil e o
       antigo dist\NexusGeoIA.exe do modo arquivo unico), preservando o
       .zip e o instalador ja gerados - exceto com -Limpar, que força um
       build do zero;
    4. executa
       .venv\Scripts\pyinstaller.exe --clean --noconfirm packaging\assistente.spec
       e gera dist\NexusGeoIA\NexusGeoIA.exe + dist\NexusGeoIA\_internal\
       (modo --onedir, sem console);
    5. copia para o pacote --onedir os modulos e configuracoes da
       release: .streamlit\config.toml (tema escuro), ui\ (todos os
       modulos de apresentacao, inclusive workstation_layout.py) e
       finetuning\Modelfile.nexusgeo-qwen3-4b-v2 (e o -q4, quando
       presente). Com -IncludeCustomGGUF copia tambem o GGUF
       customizado para models\ dentro do pacote gerado;
    5.1 executa o self-test OBRIGATORIO do .exe compilado
       (NexusGeoIA.exe --self-test via packaging\smoke_exe.py) e
       interrompe o build se qualquer verificacao falhar;
    6. monta dist\NexusGeoIA_v1.0.0_Portatil com todo o conteudo de
       dist\NexusGeoIA\ (NexusGeoIA.exe e _internal\) ao lado de
       iniciar.bat, setup_llm.py, prompts\, .streamlit\, ui\,
       finetuning\, README.md, PROTOCOLO_PESQUISA.md e LEIA-ME.txt
       (bilingue PT-BR/EN), sem .dsh, .venv, .git, .ruff_cache,
       .pytest_cache, __pycache__, tests, estrutura.txt, .env ou
       segredos;
    7. compacta em dist\NexusGeoIA_v1.0.0_Portatil.zip com tar.exe -a -c
       -f (fallback: Compress-Archive), confere a assinatura PK, a pasta
       raiz e a ausencia de itens proibidos dentro do .zip, e informa o
       tamanho final em MB.

    O modo --onedir elimina o erro "Could not create temporary
    directory!" do bootloader --onefile (que precisava criar _MEI... em
    %TEMP%), abre mais rapido e reduz falsos positivos de antivirus. No
    PyInstaller 6 o sys._MEIPASS aponta para dist\NexusGeoIA\_internal.

    O build termina com o self-test OBRIGATORIO do executavel
    (NexusGeoIA.exe --self-test via packaging\smoke_exe.py): importa
    todos os modulos internos, confere .streamlit/prompts/ui/finetuning,
    inicializa o SQLite WAL em pasta temporaria, resolve o modelo oficial
    nexusgeo-qwen3-4b-v2-q4 e faz o dry-run de app.py. Se qualquer
    verificacao falhar, o .zip e o instalador NAO sao gerados.

    app.py, prompts\, .streamlit\ e o configurador do modelo local viajam
    dentro de _internal\ pelo .spec. As copias em disco na raiz do
    pacote portatil servem de referencia, deixam a montagem auditavel e
    permitem conferir a configuracao sem abrir o executavel. O mesmo
    vale para ui\ e finetuning\Modelfile.*: os modulos ja vao
    compilados em _internal\, e a copia em disco documenta a release e
    acompanha os templates do modelo proprio.

    O pacote padrao e LEVE: o GGUF de ~2,5 GB
    (models\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf) fica fora do .zip. Use
    -IncludeCustomGGUF para embuti-lo, procurando primeiro em
    models\ do projeto e depois no cache D:\hf_cache.

.PARAMETER PythonExe
    python.exe usado no build. Padrao: .venv\Scripts\python.exe.

.PARAMETER SemTestes
    Pula a suite offline. Use apenas em diagnostico: o padrao e falhar
    antes de compilar quando algum teste quebra.

.PARAMETER SemZip
    Monta a pasta portatil e nao gera o .zip.

.PARAMETER IncludeCustomGGUF
    Embute o GGUF customizado no pacote portatil. Procura
    models\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf no projeto e, se nao
    existir, D:\hf_cache\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf; copia o
    arquivo para models\ dentro do pacote gerado. Sem o arquivo, o
    build e interrompido com mensagem clara. Sem esta flag o pacote
    continua leve, sem os ~2,5 GB do GGUF.

.PARAMETER Limpar
    Remove o executavel, o .zip e o instalador anteriores antes de
    compilar (build do zero). Sem esta opcao os artefatos finais sao
    preservados ate serem substituidos.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1 -Limpar

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_portatil.ps1 -IncludeCustomGGUF
#>

[CmdletBinding()]
param(
    [string]$PythonExe = "",

    [switch]$SemTestes,

    [switch]$SemZip,

    [switch]$IncludeCustomGGUF,

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
$ColetaInterna = Join-Path $ScriptDir "coleta_interna.py"
$SmokeExePython = Join-Path $ScriptDir "smoke_exe.py"
$ManifestoModulos = Join-Path $Build "modulos_internos.json"

# Templates do modelo proprio que acompanham a release. O -q4 e opcional:
# o loop de copia ignora quando o arquivo nao existe.
$ModelfilePrincipal = "Modelfile.nexusgeo-qwen3-4b-v2"
$ModelfilesNexusGeo = @(
    $ModelfilePrincipal,
    "Modelfile.nexusgeo-qwen3-4b-v2-q4"
)

# GGUF opcional (-IncludeCustomGGUF). O pacote padrao continua leve: sem
# a flag nada e procurado nem copiado. A ordem de busca e models\ do
# projeto e, depois, o cache do Hugging Face em D:\hf_cache.
$NomeGgufCustom = "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
$CacheGgufCustom = "D:\hf_cache"

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

# Copia os modulos e configuracoes da release para o pacote --onedir.
#
# A partir da v1.0.0 a distribuicao leva, alem de app.py e prompts\, os
# modulos de apresentacao (ui\, incluindo workstation_layout.py) e os
# templates do modelo proprio (finetuning\Modelfile.*). O pacote
# --onedir e a fonte unica dessa copia: o staging do portatil herda a
# pasta publicada e o build_installer.ps1 embute
# dist\NexusGeoIA\* recursivamente no Setup.
#
# De finetuning\ viajam apenas os Modelfile: adaptadores, datasets,
# relatorios e __pycache__ do pacote de avaliacao ficam fora da
# distribuicao.
function Copy-ModulosDeDistribuicao {
    param([string]$Destino)

    New-Item -ItemType Directory -Force -Path $Destino | Out-Null

    Copy-PastaPublicavel (Join-Path $Raiz "ui") (Join-Path $Destino "ui")

    $pastaFinetuning = Join-Path $Destino "finetuning"

    New-Item -ItemType Directory -Force -Path $pastaFinetuning | Out-Null

    foreach ($modelfile in $ModelfilesNexusGeo) {
        $origemModelfile = Join-Path $Raiz (Join-Path "finetuning" $modelfile)

        if (Test-Path -LiteralPath $origemModelfile -PathType Leaf) {
            Copy-Item -LiteralPath $origemModelfile -Destination (Join-Path $pastaFinetuning $modelfile) -Force
        }
    }
}

# Procura o GGUF customizado, nesta ordem, em models\ do projeto e no
# cache D:\hf_cache. Devolve o caminho encontrado ou $null. Recebe todos
# os caminhos por parametro para poder ser testada isoladamente por
# tests/test_packaging_offline.py com um arquivo mock leve.
function Resolve-GgufCustom {
    param(
        [string]$RaizProjeto,
        [string]$CacheAlternativo,
        [string]$NomeArquivo
    )

    $candidatos = @(
        (Join-Path (Join-Path $RaizProjeto "models") $NomeArquivo),
        (Join-Path $CacheAlternativo $NomeArquivo)
    )

    foreach ($candidato in $candidatos) {
        if (Test-Path -LiteralPath $candidato -PathType Leaf) {
            return $candidato
        }
    }

    return $null
}

# Copia o GGUF customizado para models\ dentro do pacote portatil.
# Interrompe o build com mensagem clara quando o arquivo nao existe em
# nenhuma das origens: um .zip publicado sem o GGUF prometido seria pior
# que a falha antecipada.
function Copy-GgufCustomParaPacote {
    param(
        [string]$RaizProjeto,
        [string]$CacheAlternativo,
        [string]$NomeArquivo,
        [string]$Pacote
    )

    $origem = Resolve-GgufCustom -RaizProjeto $RaizProjeto -CacheAlternativo $CacheAlternativo -NomeArquivo $NomeArquivo

    if (-not $origem) {
        throw @"
GGUF do modelo customizado nao encontrado para -IncludeCustomGGUF.

Procurei em:
  $(Join-Path (Join-Path $RaizProjeto "models") $NomeArquivo)
  $(Join-Path $CacheAlternativo $NomeArquivo)

Baixe o arquivo para models\ na raiz do projeto ou rode o build sem
-IncludeCustomGGUF (pacote leve, sem os ~2,5 GB do GGUF).
"@
    }

    $tamanho = (Get-Item -LiteralPath $origem).Length

    if ($tamanho -le 0) {
        throw "GGUF vazio ou ilegivel: $origem"
    }

    $pastaModelos = Join-Path $Pacote "models"

    New-Item -ItemType Directory -Force -Path $pastaModelos | Out-Null

    $destino = Join-Path $pastaModelos $NomeArquivo

    Copy-Item -LiteralPath $origem -Destination $destino -Force

    return $destino
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
# uma pasta ``NexusGeoIA_v1.0.0_Portatil\`` em vez de despejar tudo na
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
Assert-Arquivo (Join-Path $Raiz "encerrar.bat") "encerrar.bat"

# Modulos e configuracoes da release: sem estes arquivos a montagem
# sairia incompleta (tema escuro, layout da workstation e templates do
# modelo proprio).
Assert-Arquivo (Join-Path $Raiz ".streamlit\config.toml") ".streamlit\config.toml"
Assert-Arquivo (Join-Path $Raiz "ui\workstation_layout.py") "ui\workstation_layout.py"
Assert-Arquivo (Join-Path $Raiz "finetuning\$ModelfilePrincipal") "finetuning\$ModelfilePrincipal"

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

# O encerrar.bat chama o modo --encerrar do launcher; sem esse vinculo o
# usuario nao teria como fechar o servidor residual em um clique.
$ConteudoEncerrar = Get-Content -LiteralPath (Join-Path $Raiz "encerrar.bat") -Raw

if ($ConteudoEncerrar -notmatch "--encerrar") {
    throw "encerrar.bat nao chama o modo --encerrar do launcher."
}

if ($ConteudoEncerrar -notmatch "iniciar\.bat") {
    throw "encerrar.bat nao delega para iniciar.bat."
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
# Descoberta dos modulos internos (hidden-import explicito por .py)
# ---------------------------------------------------------------------------
#
# O .spec nao aceita --hidden-import/--collect-submodules/--collect-data
# na linha de comando: o PyInstaller proibe opcoes de makespec quando um
# .spec e fornecido. O equivalente e feito em duas camadas:
#
#  - packaging\coleta_interna.py varre core\, services\, ui\, adapters\
#    e utils\ e grava build\modulos_internos.json com um hidden-import
#    explicito para CADA .py, alem de config e setup_llm;
#  - packaging\assistente.spec le o manifesto e chama collect_submodules/
#    collect_data_files para os cinco pacotes.
#
# Aqui o build confere a coleta real antes de compilar: se um pacote
# sumir do ambiente (ou do .spec), o build falha agora em vez de gerar um
# .exe que so quebra no navegador do usuario.

Write-Etapa "Descobrindo os modulos internos para o PyInstaller"

Assert-Arquivo $ColetaInterna "coleta_interna.py"

& $PythonExe $ColetaInterna --raiz $Raiz --saida $ManifestoModulos

if ($LASTEXITCODE -ne 0) {
    throw "A descoberta de modulos internos falhou (codigo $LASTEXITCODE)."
}

Assert-Arquivo $ManifestoModulos "manifesto de modulos internos"

$manifestoModulos = Get-Content -LiteralPath $ManifestoModulos -Raw | ConvertFrom-Json

if ($manifestoModulos.modulos.Count -lt 1) {
    throw "O manifesto de modulos internos esta vazio."
}

Write-Host "    Modulos com hidden-import explicito: $($manifestoModulos.modulos.Count)"

foreach ($pacoteInterno in @("core", "services", "ui", "adapters", "utils")) {
    $quantidadeSubmodulos = & $PythonExe -c "from PyInstaller.utils.hooks import collect_submodules; print(len(collect_submodules('$pacoteInterno')))" 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "collect_submodules('$pacoteInterno') falhou: o pacote nao esta no bundle."
    }

    $quantidadeDados = & $PythonExe -c "from PyInstaller.utils.hooks import collect_data_files; print(len(collect_data_files('$pacoteInterno')))" 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "collect_data_files('$pacoteInterno') falhou."
    }

    Write-Host "    --collect-submodules $($pacoteInterno): $quantidadeSubmodulos; --collect-data $($pacoteInterno): $quantidadeDados"
}

Write-Host "    Pacotes: $($manifestoModulos.pacotes -join ', ')"

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

# O .spec le exatamente esta lista de hidden-imports explicitos.
$manifestoAnterior = $env:NEXUSGEO_MODULOS_MANIFEST
$env:NEXUSGEO_MODULOS_MANIFEST = $ManifestoModulos

Push-Location -LiteralPath $Raiz

try {
    & $executavelPyInstaller @prefixoPyInstaller @argumentosPyInstaller
    $codigoPyInstaller = $LASTEXITCODE
}
finally {
    Pop-Location

    if ($null -eq $manifestoAnterior) {
        Remove-Item Env:\NEXUSGEO_MODULOS_MANIFEST -ErrorAction SilentlyContinue
    }
    else {
        $env:NEXUSGEO_MODULOS_MANIFEST = $manifestoAnterior
    }
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

# ui\ e finetuning\ tambem precisam existir em _internal: o launcher faz
# chdir para sys._MEIPASS e o setup resolve o Modelfile por
# config.diretorio_do_projeto(). O manifesto e lido pelo --self-test.
foreach ($recursoModuloInterno in @(
    "ui\workstation_layout.py",
    "finetuning\Modelfile.nexusgeo-qwen3-4b-v2",
    "modulos_internos.json"
)) {
    $caminhoModuloInterno = Join-Path $PastaInterna $recursoModuloInterno

    if (-not (Test-Path -LiteralPath $caminhoModuloInterno -PathType Leaf)) {
        throw "Recurso de modulo ausente em _internal: $caminhoModuloInterno"
    }
}

# ---------------------------------------------------------------------------
# Modulos e configuracoes da release no pacote --onedir
# ---------------------------------------------------------------------------
#
# O pacote publica ui\ (workstation_layout.py e demais modulos) e
# finetuning\Modelfile.* ao lado do executavel. O staging do portatil
# copia esta pasta inteira e o build_installer.ps1 embute
# dist\NexusGeoIA\* recursivamente, entao a mesma copia serve aos dois
# artefatos da release. O .streamlit\config.toml ja vem do .spec em
# _internal\.streamlit\config.toml e e conferido abaixo, no staging.

Write-Etapa "Copiando modulos e configuracoes da release para o pacote"

Copy-ModulosDeDistribuicao $PastaApp

Write-Host "    ui\ (incluindo workstation_layout.py): OK"
Write-Host "    finetuning\Modelfile.*: OK"

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
# Self-test obrigatorio do executavel (--self-test)
# ---------------------------------------------------------------------------
#
# O build so conclui quando o binario compilado passa 100% no
# autodiagnostico: import de TODOS os modulos internos (config,
# setup_llm, core.*, services.*, ui.*, adapters.*, utils.*), recursos de
# runtime (.streamlit, prompts, ui e finetuning), SQLite WAL em pasta
# temporaria, resolucao do modelo oficial nexusgeo-qwen3-4b-v2-q4 e
# dry-run de app.py.
#
# Sem esta etapa um ModuleNotFoundError como core.governance so
# apareceria no navegador do usuario final, depois do .zip publicado.
#
# O executavel e console=False; packaging\smoke_exe.py executa o .exe
# com --self-test, le o relatorio JSON (ASSISTENTE_SELFTEST_REPORT) e
# devolve codigo != 0 quando qualquer verificacao falha. Nao abre
# navegador, servidor nem janela.

$RelatorioSelfTest = Join-Path $Build "self_test.json"
$PastaDadosSelfTest = Join-Path $Build "self_test_dados"
$TEMPO_LIMITE_SELFTEST = 1800

Write-Etapa "Self-test obrigatorio do executavel (--self-test)"

Assert-Arquivo $SmokeExePython "smoke_exe.py"

if (Test-Path -LiteralPath $PastaDadosSelfTest) {
    Remove-PastaSegura $PastaDadosSelfTest
}

& $PythonExe $SmokeExePython --exe $ExeApp --relatorio $RelatorioSelfTest --timeout $TEMPO_LIMITE_SELFTEST --dados $PastaDadosSelfTest

$codigoSelfTest = $LASTEXITCODE

if ($codigoSelfTest -ne 0) {
    $detalheSelfTest = ""

    if (Test-Path -LiteralPath $RelatorioSelfTest -PathType Leaf) {
        $detalheSelfTest = (Get-Content -LiteralPath $RelatorioSelfTest -Raw).Trim()
    }

    throw @"
O self-test do executavel falhou (codigo $codigoSelfTest).

O pacote portatil NAO foi montado e o .zip NAO foi gerado.

Relatorio do self-test:
$detalheSelfTest
"@
}

Assert-Arquivo $RelatorioSelfTest "Relatorio do self-test"

$relatorioSelfTestJson = Get-Content -LiteralPath $RelatorioSelfTest -Raw | ConvertFrom-Json

if (-not $relatorioSelfTestJson.ok) {
    $falhasSelfTest = ($relatorioSelfTestJson.falhas -join "; ")

    throw "O self-test do executavel reprovou: $falhasSelfTest"
}

foreach ($verificacao in $relatorioSelfTestJson.verificacoes) {
    Write-Host "    OK: $($verificacao.nome)"
}

Write-Host "    Bundle: $($relatorioSelfTestJson.base_recursos)"

if (Test-Path -LiteralPath $PastaDadosSelfTest) {
    Remove-PastaSegura $PastaDadosSelfTest
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
Copy-Item -LiteralPath (Join-Path $Raiz "encerrar.bat") -Destination (Join-Path $Staging "encerrar.bat") -Force
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
  encerrar.bat    encerra imediatamente o servidor e os processos filhos.
  setup_llm.py    copia de referencia do configurador do modelo oficial;
                  para usa-lo no dia a dia prefira: NexusGeoIA.exe --setup-modelo
  PROTOCOLO_PESQUISA.md  protocolo de validacao cientifica e mitigacao de
                  vies entre familias de LLMs (auditoria cruzada, fontes,
                  citacao e parecer tecnico).
  README.md       visao geral, instalacao e uso do aplicativo.
  prompts\        copia de referencia do system prompt padrao.
  .streamlit\     copia de referencia da configuracao do Streamlit.
  ui\             modulos de apresentacao (workstation_layout.py e demais).
  finetuning\     templates Modelfile do modelo NexusGeo Qwen3 4B v2.

O GGUF do modelo proprio (~2,5 GB) so acompanha o pacote quando o build
roda com -IncludeCustomGGUF; nesse caso ele fica em models\.

Para reconfigurar o modelo oficial depois:
    NexusGeoIA.exe --setup-modelo

Para conferir a integridade do pacote (sem abrir janela nem navegador):
    NexusGeoIA.exe --self-test
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
  encerrar.bat    shuts down the server and its child processes immediately.
  setup_llm.py    reference copy of the local model configurator; prefer:
                  NexusGeoIA.exe --setup-modelo
  PROTOCOLO_PESQUISA.md  scientific validation and LLM-family bias
                  mitigation protocol (cross-audit, sources, citation and
                  technical report).
  README.md       overview, installation and usage of the application.
  prompts\        reference copy of the default system prompt.
  .streamlit\     reference copy of the Streamlit configuration.
  ui\             presentation modules (workstation_layout.py and others).
  finetuning\     Modelfile templates for the NexusGeo Qwen3 4B v2 model.

The custom model GGUF (~2.5 GB) only ships when the build runs with
-IncludeCustomGGUF; in that case it is stored under models\.

To reconfigure the official model later:
    NexusGeoIA.exe --setup-modelo

To check package integrity (no window and no browser):
    NexusGeoIA.exe --self-test
    NexusGeoIA.exe --autoteste
"@

Set-Content -LiteralPath (Join-Path $Staging "LEIA-ME.txt") -Value $leiaMe -Encoding ASCII

# ---------------------------------------------------------------------------
# GGUF customizado (opcional, -IncludeCustomGGUF)
# ---------------------------------------------------------------------------
#
# O pacote padrao e leve: o GGUF de ~2,5 GB do modelo proprio fica fora
# do .zip para manter a distribuicao baixavel e o build rapido. Com
# -IncludeCustomGGUF o build procura models\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf
# no projeto e, se nao existir, D:\hf_cache\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf;
# o arquivo e copiado para models\ dentro do pacote gerado. Sem o
# arquivo, o build para com mensagem clara (nunca publica um pacote
# "com GGUF" vazio).

$ggufDestino = $null

if ($IncludeCustomGGUF) {
    Write-Etapa "Embutindo o GGUF customizado (-IncludeCustomGGUF)"

    # Splat de hashtable: no Windows PowerShell 5.1 o splat de array
    # entregaria os elementos como argumentos posicionais.
    $parametrosGguf = @{
        RaizProjeto = $Raiz
        CacheAlternativo = $CacheGgufCustom
        NomeArquivo = $NomeGgufCustom
        Pacote = $Staging
    }

    $ggufDestino = Copy-GgufCustomParaPacote @parametrosGguf

    $ggufMb = [math]::Round((Get-Item -LiteralPath $ggufDestino).Length / 1MB, 1)

    Write-Host "    GGUF: $ggufDestino ($ggufMb MB)"
}
else {
    Write-Etapa "GGUF do modelo customizado: nao embutido (pacote leve)"

    Write-Host "    O .zip padrao nao carrega os ~2,5 GB do GGUF."
    Write-Host "    Para embutir models\$NomeGgufCustom, use -IncludeCustomGGUF."
}

# ---------------------------------------------------------------------------
# Validacoes da montagem
# ---------------------------------------------------------------------------

Write-Etapa "Validando a montagem"

$conteudoEsperado = @(
    "$NomeApp.exe",
    "_internal",
    "iniciar.bat",
    "encerrar.bat",
    "setup_llm.py",
    "LEIA-ME.txt",
    "README.md",
    "PROTOCOLO_PESQUISA.md",
    "prompts",
    ".streamlit",
    "ui",
    "finetuning"
)

if ($IncludeCustomGGUF) {
    $conteudoEsperado += "models"
}

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

# Modulos e configuracoes da release: o tema escuro (.streamlit), os
# modulos de apresentacao (ui\) e os templates do modelo proprio
# (finetuning\Modelfile.*) precisam estar na raiz do pacote. O Modelfile
# -q4 e opcional: so e exigido quando existe no projeto.
foreach ($recursoGate3 in @(
    (Join-Path ".streamlit" "config.toml"),
    (Join-Path "ui" "__init__.py"),
    (Join-Path "ui" "workstation_layout.py")
)) {
    $caminhoGate3 = Join-Path $Staging $recursoGate3

    if (-not (Test-Path -LiteralPath $caminhoGate3 -PathType Leaf)) {
        throw "Recurso da release ausente no pacote portatil: $caminhoGate3"
    }
}

foreach ($modelfile in $ModelfilesNexusGeo) {
    $origemModelfile = Join-Path $Raiz (Join-Path "finetuning" $modelfile)

    if (-not (Test-Path -LiteralPath $origemModelfile -PathType Leaf)) {
        continue
    }

    $caminhoModelfile = Join-Path $Staging (Join-Path "finetuning" $modelfile)

    if (-not (Test-Path -LiteralPath $caminhoModelfile -PathType Leaf)) {
        throw "Template do modelo ausente no pacote portatil: $caminhoModelfile"
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

if ($ggufDestino) {
    Write-Host "  GGUF: $ggufDestino ($ggufMb MB)" -ForegroundColor Green
}
else {
    Write-Host "  GGUF: nao embutido (pacote leve; use -IncludeCustomGGUF)"
}

if ($zipMb) {
    Write-Host "  Zip: $ZipFinal ($zipMb MB) [$motorZip]" -ForegroundColor Green
}

Write-Host ""
Write-Host "Para testar: extraia o .zip (ou abra a pasta) e execute iniciar.bat" -ForegroundColor Yellow
Write-Host ""
