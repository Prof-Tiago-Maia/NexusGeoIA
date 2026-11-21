<#
.SYNOPSIS
    Baixa, verifica e instala o Ollama silenciosamente.

.DESCRIPTION
    Script fixo chamado pelo instalador Inno Setup. O caminho do
    instalador chega por parâmetro, sem interpolação em -Command, e o
    binário só é executado depois de uma verificação Authenticode válida
    do fornecedor Ollama. Em qualquer falha, o script termina com erro e
    o instalador orienta a instalação manual.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Instalador
)

$ErrorActionPreference = "Stop"
$Url = "https://ollama.com/download/OllamaSetup.exe"

Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Instalador

$assinatura = Get-AuthenticodeSignature -LiteralPath $Instalador

if ($assinatura.Status -ne "Valid" -or
    $assinatura.SignerCertificate.Subject -notmatch "Ollama") {
    throw "Instalador do Ollama sem assinatura Authenticode valida."
}

$processo = Start-Process -FilePath $Instalador `
    -ArgumentList "/VERYSILENT", "/NORESTART" -Wait -PassThru

if ($processo.ExitCode -ne 0) {
    throw "Instalador do Ollama retornou codigo $($processo.ExitCode)."
}
