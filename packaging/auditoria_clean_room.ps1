<#
.SYNOPSIS
    Auditoria Clean-Room do pacote portatil do NexusGeo IA.

.DESCRIPTION
    Extrai o .zip final para uma pasta temporaria isolada, fora do
    repositorio e sem acesso ao .venv, sanitiza o PATH da sessao de teste
    e valida o pacote como se fosse a primeira execucao em uma maquina
    limpa:

    1. localiza dist\NexusGeoIA_v0.9.0_Portatil.zip (ou o .zip mais
       recente em dist\);
    2. extrai em %TEMP%\NexusGeoIA_CleanRoom_Test e remove qualquer
       referencia a .venv ou a uma instalacao local de Python do PATH,
       VIRTUAL_ENV, PYTHONHOME, PYTHONPATH, CONDA_PREFIX etc.;
    3. exige os arquivos que ja quebraram o pacote em producao:
       _internal\certifi\cacert.pem, .streamlit\config.toml,
       prompts\system_base.txt e iniciar.bat;
    4. executa NexusGeoIA.exe --autoteste fora do .venv, com
       SSL_CERT_FILE/REQUESTS_CA_BUNDLE apontando para um caminho
       inexistente (o launcher deve corrigir para o certifi do bundle),
       capturando codigo de saida, stdout, stderr, tracebacks e o JSON
       do autoteste;
    5. depois do processo principal, aguarda 3 segundos e falha se
       restar qualquer processo NexusGeoIA novo ou apontando para a
       pasta extraida;
    6. remove a pasta temporaria e imprime PASS/FAIL.

    O script existe para rodar ANTES de qualquer git tag ou upload no
    GitHub Releases. Ele nao substitui a validacao humana do duplo
    clique no terminal nativo do Windows, mas impede que um .zip com
    cacert.pem ausente, import quebrado, traceback silencioso ou
    processo orfao seja publicado.

.PARAMETER ZipPath
    Caminho explicito do .zip. Sem ele, usa o pacote versionado em
    dist\ e, na ausencia dele, o .zip mais recente de dist\.

.PARAMETER TimeoutSegundos
    Tempo maximo do --autoteste. Padrao: 240 segundos.

.PARAMETER ManterTemp
    Mantem a pasta temporaria para diagnostico. O padrao e remover.

.PARAMETER PularExecucao
    Valida apenas estrutura, PATH e arquivos obrigatorios. Use somente
    em diagnostico: a auditoria de release precisa executar o .exe.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\auditoria_clean_room.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\auditoria_clean_room.ps1 -ZipPath dist\NexusGeoIA_v0.9.0_Portatil.zip
#>

[CmdletBinding()]
param(
    [string]$ZipPath = "",

    [int]$TimeoutSegundos = 240,

    [switch]$ManterTemp,

    [switch]$PularExecucao
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Caminhos e estado da auditoria
# ---------------------------------------------------------------------------

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $ScriptDir
$Dist = Join-Path $Raiz "dist"

$NomeTemp = "NexusGeoIA_CleanRoom_Test"
$TempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$TempRoot = [System.IO.Path]::GetFullPath((Join-Path $TempBase $NomeTemp))

# O relatorio final e montado em memoria e impresso depois da limpeza.
$Checks = New-Object System.Collections.Generic.List[object]

function Write-Secao {
    param([string]$Texto)

    Write-Host ""
    Write-Host "==> $Texto" -ForegroundColor Cyan
}

function Add-Verificacao {
    param(
        [string]$Nome,
        [bool]$Ok,
        [string]$Detalhe = ""
    )

    $Checks.Add([pscustomobject]@{
        Nome = $Nome
        Ok = $Ok
        Detalhe = $Detalhe
    })

    $rotulo = if ($Ok) { "PASS" } else { "FAIL" }
    $cor = if ($Ok) { "Green" } else { "Red" }
    $sufixo = if ($Detalhe) { " - $Detalhe" } else { "" }

    Write-Host "[$rotulo] $Nome$sufixo" -ForegroundColor $cor
}

function Test-DentroDe {
    param(
        [string]$Caminho,
        [string]$Pai
    )

    if ([string]::IsNullOrWhiteSpace($Caminho) -or
        [string]::IsNullOrWhiteSpace($Pai)) {
        return $false
    }

    try {
        $caminhoAbs = [System.IO.Path]::GetFullPath($Caminho)
        $paiAbs = [System.IO.Path]::GetFullPath($Pai).TrimEnd('\', '/')
        $prefixo = $paiAbs + [System.IO.Path]::DirectorySeparatorChar

        return $caminhoAbs.Equals(
            $paiAbs,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or $caminhoAbs.StartsWith(
            $prefixo,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Remove-PastaCleanRoom {
    param([string]$Caminho)

    if (-not (Test-Path -LiteralPath $Caminho)) {
        return
    }

    # Nunca remova a raiz do TEMP nem qualquer caminho fora dela.
    if ($Caminho.TrimEnd('\', '/') -eq $TempBase.TrimEnd('\', '/') -or
        -not (Test-DentroDe $Caminho $TempBase)) {
        throw "Recusando remover caminho fora da pasta temporaria: $Caminho"
    }

    try {
        Remove-Item -LiteralPath $Caminho -Recurse -Force -ErrorAction Stop
        return
    }
    catch {
        Write-Verbose "Remove-Item falhou; tentando rd com caminho longo."
    }

    & cmd.exe /c rd /s /q "\\?\$Caminho" | Out-Null

    if (Test-Path -LiteralPath $Caminho) {
        throw "Nao foi possivel remover a pasta temporaria: $Caminho"
    }
}

function Get-TextoArquivo {
    param([string]$Caminho)

    if (-not (Test-Path -LiteralPath $Caminho -PathType Leaf)) {
        return ""
    }

    try {
        return [string](Get-Content -LiteralPath $Caminho -Raw -ErrorAction Stop)
    }
    catch {
        return ""
    }
}

function Stop-ArvoreProcesso {
    param([int]$Id)

    try {
        & taskkill.exe /PID $Id /T /F 2>$null | Out-Null
    }
    catch {
        try {
            Stop-Process -Id $Id -Force -ErrorAction Stop
        }
        catch {
            Write-Verbose "O processo $Id ja havia terminado."
        }
    }
}

function Get-ProcessosDoPacote {
    param([string]$PastaPacote)

    $encontrados = @()

    foreach ($processo in @(Get-Process -Name "NexusGeoIA" -ErrorAction SilentlyContinue)) {
        $caminho = $null

        try {
            $caminho = $processo.Path
        }
        catch {
            $caminho = $null
        }

        if ($caminho -and (Test-DentroDe $caminho $PastaPacote)) {
            $encontrados += $processo
        }
    }

    return $encontrados
}

function Show-RelatorioFinal {
    Write-Secao "Relatorio final"

    $total = $Checks.Count
    $aprovadas = @($Checks | Where-Object { $_.Ok }).Count
    $falhas = @($Checks | Where-Object { -not $_.Ok })

    foreach ($check in $Checks) {
        $rotulo = if ($check.Ok) { "PASS" } else { "FAIL" }
        $cor = if ($check.Ok) { "Green" } else { "Red" }
        $sufixo = if ($check.Detalhe) { " - $($check.Detalhe)" } else { "" }
        Write-Host "[$rotulo] $($check.Nome)$sufixo" -ForegroundColor $cor
    }

    Write-Host ""
    Write-Host "Verificacoes aprovadas: $aprovadas/$total"

    if ($falhas.Count -eq 0) {
        Write-Host "RESULTADO: PASS" -ForegroundColor Green
        return 0
    }

    Write-Host "RESULTADO: FAIL" -ForegroundColor Red
    Write-Host "Motivos:" -ForegroundColor Red

    foreach ($falha in $falhas) {
        Write-Host "  - $($falha.Nome): $($falha.Detalhe)" -ForegroundColor Red
    }

    return 1
}

# ---------------------------------------------------------------------------
# Preparacao: pasta isolada e ambiente de maquina limpa
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AUDITORIA CLEAN-ROOM - NexusGeo IA" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

Write-Secao "Preparando pasta temporaria isolada"

if (-not (Test-DentroDe $TempRoot $TempBase) -or
    $TempRoot.TrimEnd('\', '/') -eq $TempBase.TrimEnd('\', '/')) {
    throw "A pasta temporaria calculada nao esta isolada em TEMP: $TempRoot"
}

if (Test-Path -LiteralPath $TempRoot) {
    $processosAntigos = @(Get-ProcessosDoPacote $TempRoot)

    if ($processosAntigos.Count -gt 0) {
        $ids = ($processosAntigos | ForEach-Object { $_.Id }) -join ", "
        throw "Ha processo NexusGeoIA usando a pasta temporaria antiga (PID $ids). Feche-o antes da auditoria."
    }

    Remove-PastaCleanRoom $TempRoot
}

New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
Add-Verificacao "Pasta temporaria isolada criada fora do repositorio" $true $TempRoot

# ---------------------------------------------------------------------------
# Localizacao do .zip
# ---------------------------------------------------------------------------

Write-Secao "Localizando o pacote portatil"

$zipFinal = $null
$zipPreferido = Join-Path $Dist "NexusGeoIA_v0.9.0_Portatil.zip"

try {
    if ($ZipPath) {
        if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
            throw "O .zip informado nao existe: $ZipPath"
        }

        $zipFinal = (Resolve-Path -LiteralPath $ZipPath).Path
    }
    elseif (Test-Path -LiteralPath $zipPreferido -PathType Leaf) {
        $zipFinal = (Resolve-Path -LiteralPath $zipPreferido).Path
    }
    else {
        $candidatos = @(
            Get-ChildItem -LiteralPath $Dist -Filter "*.zip" -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending
        )

        if ($candidatos.Count -eq 0) {
            throw "Nenhum .zip encontrado em $Dist. Gere o pacote portatil antes da auditoria."
        }

        $zipFinal = $candidatos[0].FullName
    }

    $tamanhoMb = [math]::Round((Get-Item -LiteralPath $zipFinal).Length / 1MB, 1)
    Add-Verificacao "Pacote .zip localizado" $true "$zipFinal ($tamanhoMb MB)"
}
catch {
    Add-Verificacao "Pacote .zip localizado" $false $_.Exception.Message
}

if (-not $zipFinal) {
    $codigo = Show-RelatorioFinal
    exit $codigo
}

# ---------------------------------------------------------------------------
# Extracao e localizacao da raiz do pacote
# ---------------------------------------------------------------------------

Write-Secao "Extraindo o .zip em area isolada"

$PacoteRaiz = $null

try {
    $cronometroExtracao = [System.Diagnostics.Stopwatch]::StartNew()
    Expand-Archive -LiteralPath $zipFinal -DestinationPath $TempRoot -Force -ErrorAction Stop
    $cronometroExtracao.Stop()

    Add-Verificacao "Extracao concluida" $true (
        "$([math]::Round($cronometroExtracao.Elapsed.TotalSeconds, 1)) s"
    )

    $executaveis = @(
        Get-ChildItem -LiteralPath $TempRoot -Filter "NexusGeoIA.exe" -File -Recurse -ErrorAction Stop
    )

    if ($executaveis.Count -eq 0) {
        throw "NexusGeoIA.exe nao foi encontrado dentro do .zip."
    }

    $comInterna = @(
        $executaveis | Where-Object {
            Test-Path -LiteralPath (Join-Path $_.Directory.FullName "_internal") -PathType Container
        }
    )

    if ($comInterna.Count -gt 0) {
        $PacoteRaiz = $comInterna[0].Directory.FullName
    }
    else {
        $PacoteRaiz = $executaveis[0].Directory.FullName
    }

    Add-Verificacao "Raiz do pacote localizada" $true $PacoteRaiz
}
catch {
    Add-Verificacao "Extracao e localizacao da raiz" $false $_.Exception.Message
}

# ---------------------------------------------------------------------------
# Sanitizacao do PATH e das variaveis de Python
# ---------------------------------------------------------------------------

Write-Secao "Sanitizando PATH e variaveis de Python"

$pathOriginal = [string]$env:PATH
$entradasPath = @($pathOriginal -split ';' | Where-Object { $_.Trim() })
$mantidas = New-Object System.Collections.Generic.List[string]
$removidas = New-Object System.Collections.Generic.List[string]

foreach ($entrada in $entradasPath) {
    $normalizada = $entrada.Trim().Trim('"')
    $remover = $false

    # .venv, venv, virtualenv, conda, pyenv e instalacoes locais.
    if ($normalizada -match '(?i)[\\/]\.venv([\\/]|$)') {
        $remover = $true
    }
    elseif ($normalizada -match '(?i)[\\/](venv|virtualenv|pyenv)([\\/]|$)') {
        $remover = $true
    }
    elseif ($normalizada -match '(?i)(miniconda|anaconda|conda)') {
        $remover = $true
    }
    elseif ($normalizada -match '(?i)[\\/]Python[0-9]*([\\/]|$)') {
        $remover = $true
    }
    elseif ($normalizada -match '(?i)Programs[\\/]Python') {
        $remover = $true
    }
    elseif ($normalizada -match '(?i)AppData[\\/]Local[\\/]Microsoft[\\/]WindowsApps') {
        $remover = $true
    }
    elseif ($normalizada.StartsWith($Raiz, [System.StringComparison]::OrdinalIgnoreCase)) {
        $remover = $true
    }

    if ($remover) {
        $removidas.Add($entrada)
    }
    else {
        $mantidas.Add($entrada)
    }
}

$env:PATH = ($mantidas -join ';')

foreach ($variavel in @(
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PIP_REQUIRE_VIRTUALENV",
    "PIP_CONFIG_FILE"
)) {
    if (Test-Path -LiteralPath "Env:$variavel") {
        Remove-Item -LiteralPath "Env:$variavel" -Force -ErrorAction SilentlyContinue
    }
}

Add-Verificacao "PATH sem .venv e sem Python local" (
    $env:PATH -notmatch '(?i)[\\/]\.venv([\\/]|$)'
) "$($mantidas.Count) entrada(s) mantida(s), $($removidas.Count) removida(s)"

if ($removidas.Count -gt 0) {
    foreach ($entrada in $removidas) {
        Write-Host "    removido do PATH: $entrada" -ForegroundColor DarkYellow
    }
}

$pythonVisivel = Get-Command python -ErrorAction SilentlyContinue

if ($pythonVisivel -and $pythonVisivel.Source -match '(?i)[\\/]\.venv([\\/]|$)') {
    Add-Verificacao "Nenhum python do .venv visivel na sessao de teste" $false $pythonVisivel.Source
}
else {
    $detalhePython = if ($pythonVisivel) {
        "python resolvido em $($pythonVisivel.Source) (fora do .venv)"
    }
    else {
        "nenhum python no PATH sanitizado"
    }

    Add-Verificacao "Nenhum python do .venv visivel na sessao de teste" $true $detalhePython
}

# ---------------------------------------------------------------------------
# Arquivos obrigatorios do pacote
# ---------------------------------------------------------------------------

Write-Secao "Validando arquivos obrigatorios"

$obrigatorios = @(
    @{ Caminho = "_internal\certifi\cacert.pem"; Descricao = "certifi/cacert.pem no bundle" },
    @{ Caminho = ".streamlit\config.toml"; Descricao = "configuracao do Streamlit" },
    @{ Caminho = "prompts\system_base.txt"; Descricao = "system prompt base" },
    @{ Caminho = "iniciar.bat"; Descricao = "iniciador do pacote portatil" }
)

if (-not $PacoteRaiz) {
    Add-Verificacao "Arquivos obrigatorios" $false "Raiz do pacote indisponivel."
}
else {
    foreach ($item in $obrigatorios) {
        $caminhoCompleto = Join-Path $PacoteRaiz $item.Caminho

        if (Test-Path -LiteralPath $caminhoCompleto -PathType Leaf) {
            $tamanho = (Get-Item -LiteralPath $caminhoCompleto).Length

            if ($tamanho -gt 0) {
                Add-Verificacao "Arquivo obrigatorio: $($item.Descricao)" $true "$tamanho bytes"
            }
            else {
                Add-Verificacao "Arquivo obrigatorio: $($item.Descricao)" $false "arquivo vazio"
            }
        }
        else {
            Add-Verificacao "Arquivo obrigatorio: $($item.Descricao)" $false "ausente: $caminhoCompleto"
        }
    }
}

# ---------------------------------------------------------------------------
# Execucao real do --autoteste
# ---------------------------------------------------------------------------

$envExecucaoSalvo = @{}
$pathExecucaoSalvo = [string]$env:PATH

foreach ($nome in @(
    "ASSISTENTE_SMOKE_REPORT",
    "ASSISTENTE_DATA_DIR",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE"
)) {
    $envExecucaoSalvo[$nome] = [System.Environment]::GetEnvironmentVariable($nome, "Process")
}

$codigoAutoteste = $null
$relatorioAutoteste = $null

try {
    if ($PularExecucao) {
        Add-Verificacao "Execucao do --autoteste" $false "Ignorada por -PularExecucao (nao use em release)."
    }
    elseif (-not $PacoteRaiz) {
        Add-Verificacao "Execucao do --autoteste" $false "Raiz do pacote indisponivel."
    }
    else {
        $executavel = Join-Path $PacoteRaiz "NexusGeoIA.exe"

        if (-not (Test-Path -LiteralPath $executavel -PathType Leaf)) {
            Add-Verificacao "Execucao do --autoteste" $false "NexusGeoIA.exe ausente."
        }
        else {
            Write-Secao "Executando NexusGeoIA.exe --autoteste (fora do .venv)"

            $relatorioPath = Join-Path $TempRoot "autoteste_relatorio.json"
            $stdoutPath = Join-Path $TempRoot "autoteste_stdout.log"
            $stderrPath = Join-Path $TempRoot "autoteste_stderr.log"
            $dadosPath = Join-Path $TempRoot "dados_isolados"
            $certificadoInvalido = Join-Path $TempRoot "certificado_inexistente.pem"

            New-Item -ItemType Directory -Path $dadosPath -Force | Out-Null

            $env:ASSISTENTE_SMOKE_REPORT = $relatorioPath
            $env:ASSISTENTE_DATA_DIR = $dadosPath
            # Reproduz o cenario que quebrou o import do ollama: a variavel
            # aponta para um arquivo que nao veio no bundle. O launcher tem
            # de corrigi-la para o certifi empacotado antes do import.
            $env:SSL_CERT_FILE = $certificadoInvalido
            $env:REQUESTS_CA_BUNDLE = $certificadoInvalido

            $processosAntes = @(
                Get-Process -Name "NexusGeoIA" -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty Id
            )

            $processo = $null

            try {
                # System.Diagnostics.Process (UseShellExecute=false) e
                # usado no lugar de Start-Process porque o ExitCode de um
                # executavel grafico iniciado por Start-Process pode vir
                # vazio. Aqui o codigo de saida e o mesmo que o
                # --autoteste devolve ao sistema.
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = $executavel
                $psi.Arguments = "--autoteste"
                $psi.WorkingDirectory = $PacoteRaiz
                $psi.UseShellExecute = $false
                $psi.RedirectStandardOutput = $true
                $psi.RedirectStandardError = $true
                $psi.CreateNoWindow = $true
                $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
                $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

                $processo = New-Object System.Diagnostics.Process
                $processo.StartInfo = $psi

                if (-not $processo.Start()) {
                    throw "Nao foi possivel iniciar NexusGeoIA.exe."
                }

                $tarefaStdout = $processo.StandardOutput.ReadToEndAsync()
                $tarefaStderr = $processo.StandardError.ReadToEndAsync()

                $cronometro = [System.Diagnostics.Stopwatch]::StartNew()
                $excedeu = $false

                try {
                    $terminou = $processo.WaitForExit(
                        [int]($TimeoutSegundos * 1000)
                    )

                    if (-not $terminou) {
                        $excedeu = $true
                    }
                }
                catch {
                    if ($processo) {
                        $processo.Refresh()

                        if (-not $processo.HasExited) {
                            $excedeu = $true
                        }
                    }
                    else {
                        throw "O processo do autoteste nao foi criado."
                    }
                }

                $cronometro.Stop()

                if ($excedeu) {
                    Stop-ArvoreProcesso $processo.Id

                    try {
                        if ($tarefaStdout.Wait(2000)) {
                            $stdoutParcial = [string]$tarefaStdout.Result
                            [System.IO.File]::WriteAllText(
                                $stdoutPath,
                                $stdoutParcial,
                                [System.Text.Encoding]::UTF8
                            )
                        }

                        if ($tarefaStderr.Wait(2000)) {
                            $stderrParcial = [string]$tarefaStderr.Result
                            [System.IO.File]::WriteAllText(
                                $stderrPath,
                                $stderrParcial,
                                [System.Text.Encoding]::UTF8
                            )
                        }
                    }
                    catch {
                        Write-Verbose "Nao foi possivel recuperar a saida parcial."
                    }

                    Add-Verificacao "Autoteste terminou dentro do tempo limite" $false (
                        "$TimeoutSegundos s; processo encerrado"
                    )
                }
                else {
                    # Garante o flush dos fluxos assincronos antes de ler.
                    $processo.WaitForExit()
                    $codigoAutoteste = $processo.ExitCode

                    $stdoutFinal = [string]$tarefaStdout.Result
                    $stderrFinal = [string]$tarefaStderr.Result
                    [System.IO.File]::WriteAllText(
                        $stdoutPath,
                        $stdoutFinal,
                        [System.Text.Encoding]::UTF8
                    )
                    [System.IO.File]::WriteAllText(
                        $stderrPath,
                        $stderrFinal,
                        [System.Text.Encoding]::UTF8
                    )

                    Add-Verificacao "Autoteste terminou dentro do tempo limite" $true (
                        "$([math]::Round($cronometro.Elapsed.TotalSeconds, 1)) s"
                    )
                }
            }
            catch {
                Add-Verificacao "Execucao do --autoteste" $false (
                    "$($_.Exception.Message) | $($_.InvocationInfo.PositionMessage)"
                )

                if ($processo) {
                    Stop-ArvoreProcesso $processo.Id
                }
            }

            $stdout = [string](Get-TextoArquivo $stdoutPath)
            $stderr = [string](Get-TextoArquivo $stderrPath)
            $limiteExibicaoLog = 4000

            if ($stdout.Trim()) {
                $trechoStdout = if ($stdout.Length -gt $limiteExibicaoLog) {
                    $stdout.Substring(0, $limiteExibicaoLog) +
                        "`n... (stdout truncado; tamanho total $($stdout.Length) caracteres)"
                }
                else {
                    $stdout
                }

                Write-Host ""
                Write-Host "--- stdout do --autoteste ---" -ForegroundColor DarkGray
                Write-Host $trechoStdout.Trim()
            }

            if ($stderr.Trim()) {
                $trechoStderr = if ($stderr.Length -gt $limiteExibicaoLog) {
                    $stderr.Substring(0, $limiteExibicaoLog) +
                        "`n... (stderr truncado; tamanho total $($stderr.Length) caracteres)"
                }
                else {
                    $stderr
                }

                Write-Host ""
                Write-Host "--- stderr do --autoteste ---" -ForegroundColor DarkYellow
                Write-Host $trechoStderr.Trim()
            }

            $textoRelatorio = [string](Get-TextoArquivo $relatorioPath)
            $ocorrenciasTraceback = @()

            foreach ($padrao in @(
                "Traceback (most recent call last)",
                "FileNotFoundError",
                "ModuleNotFoundError",
                "PermissionError",
                "Could not create temporary directory"
            )) {
                if ($stderr -match [regex]::Escape($padrao) -or
                    $stdout -match [regex]::Escape($padrao) -or
                    $textoRelatorio -match [regex]::Escape($padrao)) {
                    $ocorrenciasTraceback += $padrao
                }
            }

            $detalheTraceback = if ($ocorrenciasTraceback.Count -eq 0) {
                "nenhum padrao de falha encontrado"
            }
            else {
                "encontrado: $($ocorrenciasTraceback -join ', ')"
            }

            Add-Verificacao "Sem traceback ou erro oculto em stdout/stderr" (
                $ocorrenciasTraceback.Count -eq 0
            ) $detalheTraceback

            if (-not (Test-Path -LiteralPath $relatorioPath -PathType Leaf)) {
                Add-Verificacao "Relatorio JSON do autoteste" $false "arquivo nao gerado: $relatorioPath"
            }
            else {
                try {
                    $relatorioAutoteste = Get-Content -LiteralPath $relatorioPath -Raw |
                        ConvertFrom-Json

                    Add-Verificacao "Relatorio JSON do autoteste" $true $relatorioPath

                    if ($relatorioAutoteste.ok -and $relatorioAutoteste.concluido) {
                        Add-Verificacao "Autoteste aprovou o bundle" $true (
                            "$(@($relatorioAutoteste.verificacoes).Count) verificacao(oes)"
                        )
                    }
                    else {
                        $falhasRelatorio = @($relatorioAutoteste.falhas) -join "; "
                        Add-Verificacao "Autoteste aprovou o bundle" $false $falhasRelatorio
                    }

                    foreach ($verificacao in @($relatorioAutoteste.verificacoes)) {
                        if (-not $verificacao) {
                            continue
                        }

                        $nomeVerificacao = "Autoteste: $($verificacao.nome)"
                        $detalheVerificacao = if ($verificacao.ok) {
                            "ok"
                        }
                        else {
                            [string]$verificacao.erro
                        }

                        Add-Verificacao $nomeVerificacao ([bool]$verificacao.ok) $detalheVerificacao
                    }
                }
                catch {
                    Add-Verificacao "Relatorio JSON do autoteste" $false $_.Exception.Message
                }
            }

            # Start-Process pode devolver ExitCode vazio para um executavel
            # grafico iniciado com -PassThru. Nesse caso o JSON do
            # autoteste e a fonte de verdade (ele e gravado antes de o
            # processo terminar). O codigo so reprova quando existe e nao
            # e zero; se nao existe, o relatorio precisa aprovar.
            $codigoDisponivel = (
                $null -ne $codigoAutoteste -and
                "$codigoAutoteste".Trim() -ne ""
            )

            if ($codigoDisponivel) {
                Add-Verificacao "Codigo de saida do --autoteste" (
                    $codigoAutoteste -eq 0
                ) "codigo=$codigoAutoteste"
            }
            else {
                $aprovadoPeloRelatorio = (
                    $null -ne $relatorioAutoteste -and
                    [bool]$relatorioAutoteste.ok
                )

                Add-Verificacao "Codigo de saida do --autoteste" (
                    $aprovadoPeloRelatorio
                ) (
                    "indisponivel via Start-Process; relatorio ok=" +
                    "$aprovadoPeloRelatorio"
                )
            }

            # -----------------------------------------------------------------
            # Processos orfaos: exatamente a checagem que faltava no release.
            # -----------------------------------------------------------------
            Write-Secao "Verificando processos orfaos (3 s apos o termino)"

            Start-Sleep -Seconds 3

            $processosDepois = @(Get-Process -Name "NexusGeoIA" -ErrorAction SilentlyContinue)
            $novos = @()

            foreach ($processoDepois in $processosDepois) {
                $caminhoProcesso = $null

                try {
                    $caminhoProcesso = $processoDepois.Path
                }
                catch {
                    $caminhoProcesso = $null
                }

                $ehNovo = -not ($processosAntes -contains $processoDepois.Id)
                $ehDoPacote = $caminhoProcesso -and (Test-DentroDe $caminhoProcesso $PacoteRaiz)

                if ($ehNovo -or $ehDoPacote) {
                    $novos += [pscustomobject]@{
                        Id = $processoDepois.Id
                        Caminho = $caminhoProcesso
                        Novo = $ehNovo
                        DoPacote = [bool]$ehDoPacote
                    }
                }
            }

            if ($novos.Count -eq 0) {
                $quantidadePreExistente = @($processosDepois).Count
                $detalheOrfaos = if ($quantidadePreExistente -gt 0) {
                    "0 novos; $quantidadePreExistente pre-existente(s) ignorado(s)"
                }
                else {
                    "0 processos NexusGeoIA ativos"
                }

                Add-Verificacao "Nenhum processo orfao apos o autoteste" $true $detalheOrfaos
            }
            else {
                $descricao = ($novos | ForEach-Object {
                    $marca = if ($_.DoPacote) { "do pacote" } else { "novo" }
                    "PID $($_.Id) ($marca): $($_.Caminho)"
                }) -join "; "

                Add-Verificacao "Nenhum processo orfao apos o autoteste" $false $descricao

                foreach ($orfao in $novos) {
                    try {
                        Stop-Process -Id $orfao.Id -Force -ErrorAction Stop
                    }
                    catch {
                        Write-Verbose "Nao foi possivel encerrar o PID $($orfao.Id)."
                    }
                }
            }
        }
    }
}
catch {
    Add-Verificacao "Auditoria de execucao" $false $_.Exception.Message
}
finally {
    foreach ($nome in $envExecucaoSalvo.Keys) {
        [System.Environment]::SetEnvironmentVariable(
            $nome,
            $envExecucaoSalvo[$nome],
            "Process"
        )
    }

    $env:PATH = $pathExecucaoSalvo
}

# ---------------------------------------------------------------------------
# Limpeza e relatorio
# ---------------------------------------------------------------------------

Write-Secao "Limpando a area de teste"

if ($ManterTemp) {
    Write-Host "    Pasta mantida por -ManterTemp: $TempRoot" -ForegroundColor Yellow
}
else {
    try {
        Remove-PastaCleanRoom $TempRoot

        if (Test-Path -LiteralPath $TempRoot) {
            Add-Verificacao "Pasta temporaria removida" $false $TempRoot
        }
        else {
            Add-Verificacao "Pasta temporaria removida" $true $TempRoot
        }
    }
    catch {
        Add-Verificacao "Pasta temporaria removida" $false $_.Exception.Message
    }
}

$codigoFinal = Show-RelatorioFinal
exit $codigoFinal
