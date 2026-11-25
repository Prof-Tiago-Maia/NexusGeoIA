"""Assistente de configuração do modelo LLM local do NexusGeo IA v1.0.0.

Este script roda **antes da primeira abertura** do aplicativo e mantém o
fluxo único da release v1.0.0: o único modelo oficial é
``nexusgeo-qwen3-4b-v2-q4`` (``nexusgeo-qwen3-4b-v2-Q4_K_M.gguf``).

1. Garante o Ollama instalado e respondendo em ``/api/tags``; quando o
   executável não existe, baixa o ``OllamaSetup.exe`` oficial, exige
   assinatura Authenticode válida e instala em silêncio
   (``/VERYSILENT /NORESTART``). Em seguida inclui
   ``%LOCALAPPDATA%\\Programs\\Ollama`` no ``PATH`` da sessão e sobe
   ``ollama serve`` em segundo plano quando necessário.
2. Aplica o fluxo automático do modelo oficial:
   a. se ``nexusgeo-qwen3-4b-v2-q4`` (ou ``:latest``) já está
      registrado no Ollama, grava o ``config_local.json`` e encerra com
      código ``0`` sem abrir janela (salvo ``--forcar``);
   b. se o GGUF local existe em ``models\\`` ou no cache
      ``D:\\hf_cache``, registra via
      ``ollama create nexusgeo-qwen3-4b-v2-q4 -f <Modelfile>``,
      grava o ``config_local.json`` e conclui;
   c. se o GGUF não existe (pacote portátil leve), abre uma janela
      minimalista de progresso (PT-BR/EN) que baixa o GGUF oficial dos
      GitHub Releases para ``models\\`` e o registra no Ollama;
   d. em falha de rede/download, aplica o fallback técnico único
      ``ollama pull qwen3:4b``.
3. Grava ``modelo_ollama``, ``modelo_padrao`` e
   ``modelos_instalados`` no ``config_local.json`` do diretório de
   dados do aplicativo.

Não existe catálogo de múltiplos modelos, detecção de RAM nem
checkboxes de seleção. A dependência de interface é apenas o
``tkinter`` que acompanha o Python; sem ele o mesmo fluxo roda no
terminal. O download usa ``requests`` e cai para ``urllib`` quando o
pacote não está instalado.

Uso:

    python setup_llm.py
    python setup_llm.py --forcar

``--forcar`` reexecuta a verificação e o registro mesmo quando o
modelo já está configurado (é o que o atalho *Gerenciar Modelo Local*
do instalador executa).
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import config

try:  # ``requests`` é a via principal; ``urllib`` é o plano B.
    import requests
except ImportError:  # pragma: no cover - exercitado só sem o pacote
    requests = None


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

HOST_OLLAMA_PADRAO = (
    os.getenv("OLLAMA_HOST", "").strip().rstrip("/")
    or "http://127.0.0.1:11434"
)

# Endereço loopback usado pelo healthcheck e pelo ``ollama serve``. O
# serviço do Ollama escuta em 127.0.0.1:11434 por padrão.
HOST_OLLAMA_LOCAL = "http://127.0.0.1:11434"

URL_DOWNLOAD_OLLAMA = "https://ollama.com/download/windows"

# Instalador oficial do Windows, baixado silenciosamente quando o
# executável do Ollama não é encontrado.
URL_INSTALADOR_OLLAMA = "https://ollama.com/download/OllamaSetup.exe"

NOME_INSTALADOR_OLLAMA = "OllamaSetup.exe"

# Flags do instalador Inno Setup usado pelo Ollama: instalação sem
# janelas e sem reiniciar o Windows.
FLAGS_INSTALADOR_OLLAMA = ("/VERYSILENT", "/NORESTART")

# Tamanho dos blocos lidos durante o download do instalador.
TAMANHO_BLOCO_DOWNLOAD = 1024 * 1024

# Tempo limite (conexão e leitura) do download do instalador.
TIMEOUT_DOWNLOAD_OLLAMA = 60.0

# Tempo máximo para o instalador silencioso terminar. O arquivo tem
# poucas centenas de MB e a instalação costuma levar menos de um minuto.
TIMEOUT_INSTALADOR_OLLAMA = 900.0

# Tempo máximo que o assistente espera o serviço recém-iniciado responder.
ESPERA_OLLAMA_SEGUNDOS = 15.0

# Intervalo entre as tentativas de ``/api/tags``.
INTERVALO_OLLAMA = 0.5

# Janela de tolerância usada pela interface **antes** de exibir qualquer
# aviso modal de "Ollama indisponível". O ``ollama serve`` iniciado pelo
# aplicativo leva alguns instantes para abrir a porta 11434; sem essa
# espera o usuário via o alerta antes de o serviço terminar de subir e
# precisava fechar o diálogo e clicar em "Verificar novamente".
# São 10 intervalos de 0,5 s, ou seja, até 5,0 s de espera.
ESPERA_UI_OLLAMA_SEGUNDOS = 5.0
INTERVALO_ESPERA_UI_OLLAMA = 0.5

# Trechos (comparados sem diferenciar maiúsculas) que identificam uma
# falha de permissão NTFS na pasta de modelos do Ollama, tanto na CLI
# quanto no JSON de erro do ``/api/pull``.
PADROES_ACESSO_NEGADO = (
    "access is denied",
    "access denied",
    "acesso negado",
    "permission denied",
    "permissão negada",
    "permissao negada",
    "winerror 5",
    "errno 13",
)

# Tempo limite de cada consulta HTTP (conexão, leitura). A leitura é
# generosa porque o Ollama pode ficar baixando camadas sem enviar uma
# linha nova por vários segundos.
TIMEOUT_HTTP = (10.0, 300.0)

# Limite de espera da verificação inicial, para a interface abrir rápido.
TIMEOUT_VERIFICACAO = 2.5

IDIOMA_PADRAO = "pt"

IDIOMAS = ("pt", "en")


# ---------------------------------------------------------------------------
# Modelo fine-tuned local (GGUF Q4_K_M)
# ---------------------------------------------------------------------------

# Nome com que o modelo fine-tuned validado é registrado no Ollama.
# O GGUF fica fora do pacote (centenas de MB) e é referenciado pelo
# Modelfile temporário gerado a partir do template versionado.
NOME_MODELO_LOCAL = "nexusgeo-qwen3-4b-v2-q4"
ARQUIVO_GGUF_LOCAL = "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
PASTA_GGUF_LOCAL = "models"
MODELFILE_LOCAL = Path("finetuning") / f"Modelfile.{NOME_MODELO_LOCAL}"
GGUF_CACHE_PADRAO = Path(r"D:\hf_cache") / ARQUIVO_GGUF_LOCAL

# Tempo máximo do ``ollama create`` (importação do GGUF e escrita das
# camadas no armazenamento local do Ollama).
TEMPO_LIMITE_CRIACAO_MODELO = 900.0



# ---------------------------------------------------------------------------
# Modelo oficial único da v1.0.0
# ---------------------------------------------------------------------------

# GGUF oficial publicado nos GitHub Releases da release v1.0.0. É a única
# origem de download do modelo fine-tuned; o pacote portátil leve não o
# embute.
URL_GGUF_OFICIAL = (
    "https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases/download/"
    "v1.0.0/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
)

# Fallback técnico único quando o download do GGUF oficial falha por rede
# ou quando o ``ollama create`` não consegue registrar o modelo local.
MODELO_TECNICO_FALLBACK = "qwen3:4b"


def formatar_mb(valor_bytes, idioma=IDIOMA_PADRAO):
    """Formata uma quantidade de bytes em MB (vírgula em PT-BR)."""

    try:
        megabytes = float(valor_bytes) / (1024 * 1024)
    except (TypeError, ValueError):
        return "—"

    texto = f"{megabytes:.1f}"

    if idioma == "pt":
        texto = texto.replace(".", ",")

    return f"{texto} MB"


def nome_base_modelo(nome):
    """Nome do modelo sem a tag (``modelo:latest`` -> ``modelo``)."""

    return str(nome or "").strip().split(":")[0]


def caminho_gguf_destino():
    """Destino oficial do GGUF dentro do pacote (``models\\...``)."""

    return (
        Path(config.diretorio_do_projeto())
        / PASTA_GGUF_LOCAL
        / ARQUIVO_GGUF_LOCAL
    )


def modelo_local_registrado(host=HOST_OLLAMA_PADRAO):
    """Diz se o modelo oficial já está registrado no Ollama.

    Aceita a tag exata (``nexusgeo-qwen3-4b-v2-q4``) e a variante
    ``:latest``, comparando o nome sem a tag. Falha de rede devolve
    ``False`` para o fluxo continuar pelo GGUF local.
    """

    try:
        instalados = modelos_instalados(host)
    except (OSError, RuntimeError, ValueError):
        return False

    base_oficial = nome_base_modelo(NOME_MODELO_LOCAL)

    return any(
        nome_base_modelo(nome) == base_oficial for nome in instalados
    )



# ---------------------------------------------------------------------------
# Integração com o serviço Ollama
# ---------------------------------------------------------------------------

class ErroDownload(Exception):
    """Falha ao baixar um modelo pelo ``/api/pull``."""


class ErroInstalacaoOllama(Exception):
    """Falha ao baixar ou instalar o Ollama automaticamente."""


class _RespostaUrllib:
    """Adapta a resposta do ``urllib`` à interface usada do ``requests``."""

    def __init__(self, resposta, codigo=200):
        self._resposta = resposta
        self.status_code = codigo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ErroDownload(
                f"HTTP {self.status_code} ao consultar o Ollama"
            )

    def iter_lines(self, decode_unicode=True):
        for linha in self._resposta:
            if isinstance(linha, bytes):
                yield linha.decode("utf-8", "replace").rstrip("\r\n")
            else:
                yield str(linha).rstrip("\r\n")

    def close(self):
        try:
            self._resposta.close()
        except OSError:
            pass


class _SessaoUrllib:
    """Sessão mínima com ``post`` usado quando ``requests`` falta."""

    def post(self, url, json=None, stream=False, timeout=None):
        dados = json_dumps_bytes(json or {})
        requisicao = urllib.request.Request(
            url,
            data=dados,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        limite = timeout

        if isinstance(limite, (tuple, list)):
            limite = limite[0]

        try:
            resposta = urllib.request.urlopen(requisicao, timeout=limite)
        except urllib.error.HTTPError as erro:
            raise ErroDownload(
                f"HTTP {erro.code} ao consultar o Ollama"
            ) from erro
        except urllib.error.URLError as erro:
            raise ErroDownload(
                f"Ollama inacessível: {erro.reason}"
            ) from erro

        return _RespostaUrllib(resposta, getattr(resposta, "status", 200))


def json_dumps_bytes(dados):
    """Serializa ``dados`` em JSON UTF-8 (resposta ao ``/api/pull``)."""

    return json.dumps(dados, ensure_ascii=False).encode("utf-8")


def _criar_sessao():
    """Cria a sessão HTTP de download (``requests`` ou ``urllib``)."""

    if requests is not None:
        return requests.Session()

    return _SessaoUrllib()


def _url(host, rota):
    """Monta a URL de uma rota do Ollama."""

    base = str(host or HOST_OLLAMA_PADRAO).strip().rstrip("/")

    return f"{base}{rota}"


def _http_json(url, timeout=TIMEOUT_VERIFICACAO):
    """GET que devolve JSON, ou ``None`` em qualquer falha."""

    if requests is not None:
        try:
            resposta = requests.get(url, timeout=timeout)

            if resposta.status_code != 200:
                return None

            return resposta.json()
        except (requests.RequestException, ValueError):
            return None

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def modelos_instalados(host=HOST_OLLAMA_PADRAO):
    """Nomes dos modelos já baixados no Ollama (lista vazia se offline)."""

    dados = _http_json(_url(host, "/api/tags"))

    if not isinstance(dados, dict):
        return []

    modelos = dados.get("models")

    if not isinstance(modelos, list):
        return []

    nomes = []

    for item in modelos:
        if isinstance(item, dict):
            nome = str(item.get("name") or item.get("model") or "").strip()

            if nome:
                nomes.append(nome)

    return nomes


def servico_ollama_ativo(host=HOST_OLLAMA_PADRAO, timeout=TIMEOUT_VERIFICACAO):
    """Indica se ``/api/tags`` respondeu (serviço no ar)."""

    dados = _http_json(_url(host, "/api/tags"), timeout=timeout)

    return isinstance(dados, dict)


def aguardar_ollama(
    host=HOST_OLLAMA_PADRAO,
    espera=ESPERA_UI_OLLAMA_SEGUNDOS,
    intervalo=INTERVALO_ESPERA_UI_OLLAMA,
    verificador=None,
    dormir=None,
):
    """Consulta ``/api/tags`` em intervalos até o serviço responder.

    É a barreira usada **antes de qualquer aviso modal** de "Ollama
    indisponível": com os padrões, tenta a cada 0,5 s por até 5,0 s
    (11 consultas), tempo suficiente para o ``ollama serve`` iniciado
    pelo próprio aplicativo abrir a porta 11434.

    ``verificador`` e ``dormir`` existem para os testes exercitarem a
    janela de espera sem rede e sem pausa real; em produção valem
    :func:`servico_ollama_ativo` e ``time.sleep``. Devolve ``True``
    assim que o serviço responde e ``False`` ao esgotar a janela.
    """

    intervalo = max(float(intervalo), 0.01)
    espera = max(float(espera), 0.0)
    tentativas = max(1, round(espera / intervalo) + 1)
    verificar = verificador or (lambda: servico_ollama_ativo(host))
    dormir = dormir or time.sleep
    limite = time.monotonic() + espera

    for tentativa in range(tentativas):
        if verificar():
            return True

        # O prazo é cronometrado: uma consulta lenta não estica a
        # janela além dos 5,0 s prometidos ao usuário.
        if tentativa == tentativas - 1 or time.monotonic() >= limite:
            break

        dormir(intervalo)

    return False


def pastas_ollama_padrao():
    """Pastas onde o instalador oficial do Ollama coloca o ``ollama.exe``.

    A instalação por usuário usa ``%LOCALAPPDATA%\\Programs\\Ollama``; a
    instalação para todos os usuários usa ``%ProgramFiles%\\Ollama``.
    """

    if os.name != "nt":
        return []

    pastas = []
    bases = (
        (os.getenv("LOCALAPPDATA"), Path("Programs") / "Ollama"),
        (os.getenv("PROGRAMFILES"), Path("Ollama")),
        (os.getenv("PROGRAMFILES(X86)"), Path("Ollama")),
        (os.getenv("PROGRAMW6432"), Path("Ollama")),
    )

    for base, subpasta in bases:
        if not base:
            continue

        candidata = Path(base) / subpasta

        if candidata not in pastas:
            pastas.append(candidata)

    return pastas


def caminhos_ollama_padrao():
    """Caminhos completos do ``ollama.exe`` nas pastas padrão."""

    return [pasta / "ollama.exe" for pasta in pastas_ollama_padrao()]


def adicionar_ollama_ao_path(executavel=None):
    """Adiciona a pasta do Ollama ao ``PATH`` da sessão atual.

    Devolve a pasta adicionada (ou ``None`` fora do Windows). É
    idempotente: a pasta não é repetida quando já está no ``PATH``.
    """

    if os.name != "nt":
        return None

    pasta = Path(executavel).parent if executavel else None

    if pasta is None:
        pastas = pastas_ollama_padrao()

        for candidata in pastas:
            if candidata.is_dir():
                pasta = candidata
                break

        if pasta is None and pastas:
            # Mesmo antes de o instalador criar a pasta, ela é o destino
            # padrão e precisa entrar no PATH para o processo atual.
            pasta = pastas[0]

    if pasta is None:
        return None

    atual = os.environ.get("PATH", "")
    normalizada = str(pasta).rstrip("\\/").casefold()
    partes = [
        str(Path(parte)).rstrip("\\/").casefold()
        for parte in atual.split(os.pathsep)
        if parte.strip()
    ]

    if normalizada not in partes:
        os.environ["PATH"] = (
            str(pasta) + (os.pathsep + atual if atual else "")
        )

    return str(pasta)


def localizar_ollama():
    """Caminho do executável ``ollama`` no PATH ou na instalação padrão."""

    caminho = shutil.which("ollama")

    if caminho:
        return caminho

    if os.name == "nt":
        for candidato in caminhos_ollama_padrao():
            if candidato.is_file():
                return str(candidato)

    return None


def _emitir_progresso(callback_progresso, evento):
    """Envia um evento de progresso sem deixar a interface quebrar o fluxo."""

    if callback_progresso is None:
        return

    try:
        callback_progresso(evento)
    except Exception:  # a UI nunca deve interromper a instalação
        pass


def _abrir_url(url, timeout=TIMEOUT_DOWNLOAD_OLLAMA):
    """Abre uma URL para leitura binária com ``User-Agent`` do aplicativo."""

    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}",
        },
    )

    return urllib.request.urlopen(requisicao, timeout=timeout)


def _tamanho_download(resposta):
    """Extrai o ``Content-Length`` da resposta, quando informado."""

    cabecalhos = getattr(resposta, "headers", None)

    if cabecalhos is not None:
        try:
            tamanho = cabecalhos.get("Content-Length")
        except (AttributeError, TypeError):
            tamanho = None

        if tamanho is not None:
            return _inteiro(tamanho)

    return _inteiro(getattr(resposta, "length", None))


def baixar_instalador_ollama(
    destino=None,
    callback_progresso=None,
    timeout=TIMEOUT_DOWNLOAD_OLLAMA,
):
    """Baixa o ``OllamaSetup.exe`` oficial para uma pasta temporária única.

    Reporta progresso em MB e percentual pelo ``callback_progresso`` e
    devolve o caminho local do instalador. Levanta
    :class:`ErroInstalacaoOllama` em qualquer falha de rede ou disco.

    O destino padrão é uma pasta criada por ``tempfile.mkdtemp`` com nome
    imprevisível, em vez de ``%TEMP%\\OllamaSetup.exe``. Isso reduz a
    janela de corrida em que outro processo poderia substituir o arquivo
    antes da execução.
    """

    pasta_temporaria = None

    if destino is None:
        try:
            pasta_temporaria = Path(
                tempfile.mkdtemp(prefix="nexusgeo_ollama_")
            )
        except OSError as erro:
            raise ErroInstalacaoOllama(
                "Não foi possível criar a pasta temporária do "
                f"instalador: {erro}"
            ) from erro

        destino = pasta_temporaria / NOME_INSTALADOR_OLLAMA
    else:
        destino = Path(destino)

    def _limpar_download():
        """Remove o arquivo parcial e a pasta única criada por mkdtemp."""

        try:
            destino.unlink(missing_ok=True)
        except OSError:
            pass

        if pasta_temporaria is not None:
            try:
                pasta_temporaria.rmdir()
            except OSError:
                pass

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        _limpar_download()
        raise ErroInstalacaoOllama(
            f"Não foi possível preparar a pasta do instalador: {erro}"
        ) from erro

    _emitir_progresso(
        callback_progresso,
        {
            "tipo": "ollama",
            "etapa": "baixando",
            "baixado_bytes": 0,
            "total_bytes": None,
            "percentual": None,
            "destino": str(destino),
        },
    )

    baixado = 0
    total = None

    try:
        with _abrir_url(URL_INSTALADOR_OLLAMA, timeout) as resposta:
            total = _tamanho_download(resposta)

            with destino.open("wb") as arquivo:
                while True:
                    bloco = resposta.read(TAMANHO_BLOCO_DOWNLOAD)

                    if not bloco:
                        break

                    arquivo.write(bloco)
                    baixado += len(bloco)

                    _emitir_progresso(
                        callback_progresso,
                        {
                            "tipo": "ollama",
                            "etapa": "baixando",
                            "baixado_bytes": baixado,
                            "total_bytes": total,
                            "percentual": calcular_percentual(
                                baixado,
                                total,
                            ),
                            "destino": str(destino),
                        },
                    )
    except (urllib.error.URLError, OSError, ValueError) as erro:
        _limpar_download()

        raise ErroInstalacaoOllama(
            f"Falha ao baixar o instalador do Ollama: {erro}"
        ) from erro

    if baixado <= 0:
        _limpar_download()

        raise ErroInstalacaoOllama(
            "O download do instalador do Ollama veio vazio."
        )

    _emitir_progresso(
        callback_progresso,
        {
            "tipo": "ollama",
            "etapa": "baixando",
            "baixado_bytes": baixado,
            "total_bytes": total or baixado,
            "percentual": 100.0,
            "destino": str(destino),
        },
    )

    return str(destino)


def _resumir_stderr_assinatura(stderr, limite=160):
    """Reduz o stderr do PowerShell a uma linha curta e objetiva.

    O ``Get-AuthenticodeSignature`` escreve blocos longos de categoria e
    rastreamento no stderr quando reprova. Despejar isso na mensagem da
    interface confunde o usuário, então fica apenas a última linha com
    conteúdo, normalizada e truncada.
    """

    for linha in reversed(str(stderr or "").splitlines()):
        texto = " ".join(linha.split())

        if not texto:
            continue

        if len(texto) > limite:
            return texto[:limite].rstrip() + "…"

        return texto

    return ""


def _verificar_assinatura_instalador(caminho):
    """Exige assinatura Authenticode válida do fornecedor Ollama.

    O instalador é baixado da internet e executado com privilégios do
    usuário. Sem essa checagem, um compromise do CDN, um proxy TLS
    malicioso ou um arquivo preparado em ``%TEMP%`` poderia executar
    código arbitrário. A verificação usa ``Get-AuthenticodeSignature``
    e falha fechado: qualquer status diferente de ``Valid`` ou qualquer
    signatário que não contenha "Ollama" interrompe a instalação.
    """

    if os.name != "nt":
        raise ErroInstalacaoOllama(
            "A verificação de assinatura do instalador exige Windows."
        )

    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:NEXUSGEO_INSTALADOR; "
        "if ($s.Status -ne 'Valid' -or "
        "$s.SignerCertificate.Subject -notmatch 'Ollama') { "
        "Write-Error ('Assinatura invalida: ' + $s.Status); exit 1 }"
    )

    ambiente = os.environ.copy()
    ambiente["NEXUSGEO_INSTALADOR"] = str(caminho)

    try:
        resultado = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=ambiente,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as erro:
        raise ErroInstalacaoOllama(
            f"Não foi possível verificar a assinatura do Ollama: {erro}"
        ) from erro

    if resultado.returncode != 0:
        detalhe = _resumir_stderr_assinatura(
            getattr(resultado, "stderr", "")
        )
        raise ErroInstalacaoOllama(
            "O instalador do Ollama não tem assinatura Authenticode válida. "
            "Instale manualmente em https://ollama.com/download/windows. "
            + (f"Detalhe: {detalhe}" if detalhe else "")
        )

    return True


def _remover_instalador_temporario(caminho):
    """Remove o instalador e a pasta única criada por ``mkdtemp``."""

    try:
        alvo = Path(caminho)
        alvo.unlink(missing_ok=True)

        if alvo.parent.name.startswith("nexusgeo_ollama_"):
            alvo.parent.rmdir()
    except OSError:
        pass


def executar_instalador_ollama(caminho_instalador):
    """Executa o instalador do Ollama em modo silencioso e verificado.

    Usa ``/VERYSILENT /NORESTART`` (Inno Setup), como o instalador
    oficial. Antes de executar, exige Authenticode válido do fornecedor
    Ollama. Devolve ``True``; levanta :class:`ErroInstalacaoOllama`
    quando a assinatura é inválida, o instalador falha ou não pode ser
    executado.
    """

    if os.name != "nt":
        raise ErroInstalacaoOllama(
            "A instalação automática do Ollama só é suportada no Windows."
        )

    _verificar_assinatura_instalador(caminho_instalador)

    comando = [
        str(caminho_instalador),
        *FLAGS_INSTALADOR_OLLAMA,
    ]

    try:
        subprocess.run(comando, check=True)
    except (OSError, subprocess.CalledProcessError) as erro:
        raise ErroInstalacaoOllama(
            f"O instalador silencioso do Ollama falhou: {erro}"
        ) from erro

    return True


def garantir_ollama_instalado(callback_progresso=None, host=HOST_OLLAMA_LOCAL):
    """Garante o Ollama instalado e o daemon respondendo.

    Fluxo:

    1. procura ``ollama`` no ``PATH`` e nos caminhos padrão do Windows;
    2. quando ausente, baixa ``OllamaSetup.exe`` para ``%TEMP%`` com
       progresso em MB/percentual e executa ``/VERYSILENT /NORESTART``;
    3. inclui ``%LOCALAPPDATA%\\Programs\\Ollama`` no ``PATH`` da sessão;
    4. sobe ``ollama serve`` com ``CREATE_NO_WINDOW`` e aguarda
       ``http://127.0.0.1:11434/api/tags`` responder.

    Devolve o caminho do ``ollama.exe``. Levanta
    :class:`ErroInstalacaoOllama` quando não é possível instalar ou
    localizar o executável.
    """

    caminho = localizar_ollama()
    instalado_agora = False

    if caminho:
        adicionar_ollama_ao_path(caminho)
        _emitir_progresso(
            callback_progresso,
            {
                "tipo": "ollama",
                "etapa": "detectado",
                "caminho": caminho,
            },
        )
    else:
        if os.name != "nt":
            erro = ErroInstalacaoOllama(
                "O Ollama não está instalado e a instalação automática "
                "só é suportada no Windows."
            )
            _emitir_progresso(
                callback_progresso,
                {
                    "tipo": "ollama",
                    "etapa": "erro",
                    "mensagem": str(erro),
                },
            )
            raise erro

        _emitir_progresso(
            callback_progresso,
            {
                "tipo": "ollama",
                "etapa": "ausente",
                "mensagem": "Ollama não encontrado; iniciando instalação.",
            },
        )

        instalador = None

        try:
            instalador = baixar_instalador_ollama(
                callback_progresso=callback_progresso,
            )

            _emitir_progresso(
                callback_progresso,
                {
                    "tipo": "ollama",
                    "etapa": "instalando",
                    "instalador": instalador,
                },
            )

            executar_instalador_ollama(instalador)
        except ErroInstalacaoOllama as erro:
            _emitir_progresso(
                callback_progresso,
                {
                    "tipo": "ollama",
                    "etapa": "erro",
                    "mensagem": str(erro),
                },
            )
            raise
        finally:
            if instalador:
                _remover_instalador_temporario(instalador)

        instalado_agora = True

        # O executável fica imediatamente acessível sem reiniciar o
        # Windows; depois tentamos novamente antes de desistir.
        adicionar_ollama_ao_path()
        caminho = localizar_ollama()

        if not caminho:
            for candidato in caminhos_ollama_padrao():
                if candidato.is_file():
                    caminho = str(candidato)
                    break

        if not caminho:
            erro = ErroInstalacaoOllama(
                "O Ollama foi instalado, mas o ollama.exe não foi "
                "encontrado nos caminhos padrão."
            )
            _emitir_progresso(
                callback_progresso,
                {
                    "tipo": "ollama",
                    "etapa": "erro",
                    "mensagem": str(erro),
                },
            )
            raise erro

        adicionar_ollama_ao_path(caminho)
        _emitir_progresso(
            callback_progresso,
            {
                "tipo": "ollama",
                "etapa": "instalado",
                "caminho": caminho,
            },
        )

    _emitir_progresso(
        callback_progresso,
        {
            "tipo": "ollama",
            "etapa": "iniciando_servico",
            "caminho": caminho,
            "host": host,
        },
    )

    try:
        ativo = iniciar_servidor_ollama(host)
    except Exception:  # o serviço pode já ter sido iniciado por outro app
        ativo = servico_ollama_ativo(host)

    _emitir_progresso(
        callback_progresso,
        {
            "tipo": "ollama",
            "etapa": "pronto" if ativo else "servico_indisponivel",
            "caminho": caminho,
            "host": host,
            "ativo": ativo,
            "instalado_agora": instalado_agora,
        },
    )

    return caminho


def _comando_ollama_serve(executavel):
    """Parâmetros de ``Popen`` para subir ``ollama serve`` sem janela."""

    ambiente = os.environ.copy()
    ambiente.setdefault("OLLAMA_HOST", "127.0.0.1:11434")

    parametros = {
        "args": [executavel, "serve"],
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": ambiente,
        "close_fds": True,
    }

    if os.name == "nt":
        parametros["creationflags"] = (
            subprocess.CREATE_NO_WINDOW
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        )

    return parametros


def iniciar_servidor_ollama(
    host=HOST_OLLAMA_PADRAO,
    espera=ESPERA_OLLAMA_SEGUNDOS,
):
    """Sobe ``ollama serve`` em segundo plano e espera o serviço responder.

    Devolve ``True`` quando ``/api/tags`` passa a responder. Nunca
    levanta exceção: a interface usa o retorno para orientar o usuário.
    """

    if servico_ollama_ativo(host, timeout=TIMEOUT_VERIFICACAO):
        return True

    executavel = localizar_ollama()

    if not executavel:
        return False

    try:
        processo = subprocess.Popen(**_comando_ollama_serve(executavel))
    except (OSError, ValueError):
        return False

    limite = time.monotonic() + max(float(espera), 0.0)

    while time.monotonic() < limite:
        if servico_ollama_ativo(host, timeout=TIMEOUT_VERIFICACAO):
            return True

        if processo.poll() is not None:
            # O ``ollama serve`` recém-criado pode sair de imediato quando
            # outra instância já está subindo e toma a porta antes dele.
            # Em vez de declarar o serviço indisponível na hora (o que
            # produzia o falso alerta na primeira abertura), concedemos a
            # mesma janela de tolerância usada pela interface.
            return aguardar_ollama(host)

        time.sleep(INTERVALO_OLLAMA)

    return servico_ollama_ativo(host, timeout=TIMEOUT_VERIFICACAO)


def garantir_servico_ollama(
    host=HOST_OLLAMA_PADRAO,
    callback_progresso=None,
):
    """Verifica o serviço, instala o Ollama se preciso e o inicia.

    Quando o executável não existe, chama
    :func:`garantir_ollama_instalado`, que baixa e instala o Ollama
    silenciosamente. Devolve um dicionário com ``ativo``, ``iniciado``,
    ``instalado``, ``caminho`` e ``mensagem``.
    """

    if servico_ollama_ativo(host):
        caminho = localizar_ollama()

        if caminho:
            adicionar_ollama_ao_path(caminho)
        else:
            adicionar_ollama_ao_path()

        return {
            "ativo": True,
            "iniciado": False,
            "instalado": False,
            "caminho": caminho,
            "mensagem": "Ollama ativo",
        }

    ja_instalado = localizar_ollama()

    try:
        caminho = garantir_ollama_instalado(
            callback_progresso=callback_progresso,
            host=host,
        )
    except ErroInstalacaoOllama as erro:
        return {
            "ativo": False,
            "iniciado": False,
            "instalado": False,
            "caminho": ja_instalado,
            "mensagem": str(erro),
        }

    instalado_agora = ja_instalado is None

    if servico_ollama_ativo(host):
        return {
            "ativo": True,
            "iniciado": True,
            "instalado": instalado_agora,
            "caminho": caminho,
            "mensagem": "Ollama iniciado",
        }

    if iniciar_servidor_ollama(host):
        return {
            "ativo": True,
            "iniciado": True,
            "instalado": instalado_agora,
            "caminho": caminho,
            "mensagem": "Ollama iniciado",
        }

    return {
        "ativo": False,
        "iniciado": False,
        "instalado": instalado_agora,
        "caminho": caminho,
        "mensagem": "Ollama não encontrado ou não respondeu",
    }



# ---------------------------------------------------------------------------
# Diagnóstico de permissão na pasta de modelos
# ---------------------------------------------------------------------------

def pasta_modelos_ollama():
    """Pasta onde o Ollama grava os modelos (respeita ``OLLAMA_MODELS``).

    O padrão do Ollama no Windows é ``%USERPROFILE%\\.ollama\\models``;
    quando a variável existe, ela manda e é a alternativa recomendada
    para máquinas com a pasta padrão bloqueada por permissão.
    """

    configurada = os.getenv("OLLAMA_MODELS", "").strip()

    if configurada:
        return Path(configurada)

    return Path.home() / ".ollama" / "models"


def erro_de_permissao(mensagem):
    """Reconhece falha de acesso à pasta de modelos do Ollama.

    Cobre as mensagens do Windows em inglês (``Access is denied``) e em
    português (``Acesso negado``), além de variantes de ``errno`` usadas
    pela CLI e pelo JSON de erro do ``/api/pull``. A comparação ignora
    maiúsculas/minúsculas e acentos não são normalizados de propósito:
    os dois textos aparecem literalmente nas mensagens do Windows.
    """

    texto_mensagem = str(mensagem or "").casefold()

    return any(
        padrao in texto_mensagem for padrao in PADROES_ACESSO_NEGADO
    )


def orientacao_permissao(
    mensagem="",
    idioma=IDIOMA_PADRAO,
    pasta=None,
):
    """Orientação bilíngue para desbloquear a pasta de modelos.

    Explica a causa (Ollama executado como Administrador/serviço), o
    comando ``icacls`` para liberar a pasta e a alternativa
    ``OLLAMA_MODELS`` apontando para uma pasta gravável. O texto segue
    o idioma da interface, com PT-BR como fallback.
    """

    pasta = str(pasta or pasta_modelos_ollama())

    return texto(
        "permissao_modelos_mensagem",
        idioma,
        pasta=pasta,
        mensagem=str(mensagem or "").strip(),
    )


def mensagem_de_download(mensagem, idioma=IDIOMA_PADRAO):
    """Acrescenta a orientação de permissão quando o erro é de acesso.

    Mensagens de rede/modelo inexistente passam inalteradas; apenas as
    de permissão ganham o diagnóstico e os comandos de correção.
    """

    if erro_de_permissao(mensagem):
        return orientacao_permissao(mensagem, idioma)

    return str(mensagem)


def _detalhe_resposta(resposta):
    """Melhor esforço para ler o corpo de uma resposta HTTP de falha.

    O Ollama devolve o motivo real (``Access is denied``, modelo
    inexistente etc.) no corpo; sem ele, o diagnóstico de permissão não
    teria o que analisar. Qualquer falha de leitura vira string vazia.
    """

    try:
        corpo = getattr(resposta, "text", None)
    except (AttributeError, OSError, ValueError):
        corpo = None

    if isinstance(corpo, str) and corpo.strip():
        return " ".join(corpo.split())[:500]

    try:
        dados = resposta.json()
    except (AttributeError, OSError, TypeError, ValueError):
        return ""

    if isinstance(dados, dict):
        return " ".join(
            str(dados.get("error") or dados.get("erro") or "").split()
        )[:500]

    return ""



# ---------------------------------------------------------------------------
# Download em streaming
# ---------------------------------------------------------------------------

def calcular_percentual(completed, total):
    """Percentual (0–100) de ``completed``/``total`` ou ``None``."""

    try:
        concluido = float(completed)
        tamanho = float(total)
    except (TypeError, ValueError):
        return None

    if tamanho <= 0 or concluido < 0:
        return None

    return max(0.0, min(100.0, (concluido / tamanho) * 100.0))


def texto_de_progresso(indice, total, modelo, idioma=IDIOMA_PADRAO):
    """Texto da barra: ``Baixando 1/2: qwen3:4b...``."""

    if idioma == "pt":
        return f"Baixando {indice}/{total}: {modelo}..."

    return f"Downloading {indice}/{total}: {modelo}..."


def baixar_modelo(
    modelo,
    host=HOST_OLLAMA_PADRAO,
    ao_progresso=None,
    sessao=None,
    timeout=TIMEOUT_HTTP,
):
    """Baixa um modelo consumindo ``/api/pull`` em streaming.

    ``ao_progresso`` recebe dicionários com ``status``, ``completed``,
    ``total``, ``percentual`` e o nome do modelo. Levanta
    :class:`ErroDownload` quando o servidor devolve ``error`` ou uma
    resposta HTTP de falha.
    """

    identificador = str(modelo or "").strip()

    if not identificador:
        raise ErroDownload("Modelo vazio")

    sessao = sessao or _criar_sessao()

    try:
        resposta = sessao.post(
            _url(host, "/api/pull"),
            json={"model": identificador, "stream": True},
            stream=True,
            timeout=timeout,
        )
    except Exception as erro:  # requests.RequestException e URLError
        raise ErroDownload(
            f"Não foi possível contatar o Ollama: {erro}"
        ) from erro

    try:
        try:
            resposta.raise_for_status()
        except ErroDownload:
            raise
        except Exception as erro:
            detalhe = _detalhe_resposta(resposta)
            mensagem = (
                f"HTTP {getattr(resposta, 'status_code', '?')} "
                f"ao baixar {identificador}: {erro}"
            )

            if detalhe:
                mensagem = f"{mensagem} — {detalhe}"

            raise ErroDownload(mensagem) from erro

        for linha in resposta.iter_lines(decode_unicode=True):
            if not linha:
                continue

            try:
                evento = json.loads(linha)
            except (TypeError, ValueError):
                continue

            if not isinstance(evento, dict):
                continue

            erro = evento.get("error") or evento.get("erro")

            if erro:
                raise ErroDownload(str(erro))

            status = str(evento.get("status") or "").strip()
            total = _inteiro(evento.get("total"))
            completed = _inteiro(evento.get("completed"))
            percentual = calcular_percentual(completed, total)

            if ao_progresso is not None:
                ao_progresso(
                    {
                        "tipo": "progresso",
                        "modelo": identificador,
                        "status": status,
                        "completed": completed,
                        "total": total,
                        "percentual": percentual,
                    }
                )
    finally:
        try:
            resposta.close()
        except (OSError, AttributeError):
            pass

    return True



def _inteiro(valor):
    """Converte ``completed``/``total`` em ``int`` ou ``None``."""

    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def baixar_modelos(
    modelos,
    host=HOST_OLLAMA_PADRAO,
    ao_progresso=None,
    sessao=None,
    idioma=IDIOMA_PADRAO,
):
    """Baixa os modelos pedidos em sequência pelo ``/api/pull``.

    Usado pelo fallback técnico (``qwen3:4b``) e por diagnósticos. Não
    existe catálogo: qualquer identificador válido do Ollama é aceito.
    Uma falha não interrompe os seguintes; falhas de permissão recebem a
    orientação bilíngue de :func:`orientacao_permissao`.
    """

    modelos = config.normalizar_lista_modelos(modelos)

    if not modelos:
        raise ValueError("Informe pelo menos um modelo para baixar")

    sessao = sessao or _criar_sessao()
    total = len(modelos)
    instalados = []
    falhas = {}

    def emitir(evento):
        if ao_progresso is not None:
            ao_progresso(evento)

    for indice, identificador in enumerate(modelos, start=1):
        emitir(
            {
                "tipo": "inicio",
                "indice": indice,
                "total": total,
                "modelo": identificador,
                "texto": texto_de_progresso(
                    indice,
                    total,
                    identificador,
                ),
            }
        )

        try:
            baixar_modelo(
                identificador,
                host=host,
                ao_progresso=ao_progresso,
                sessao=sessao,
            )
        except Exception as erro:
            falhas[identificador] = mensagem_de_download(
                str(erro) or f"{type(erro).__name__}",
                idioma,
            )
            emitir(
                {
                    "tipo": "erro",
                    "indice": indice,
                    "total": total,
                    "modelo": identificador,
                    "mensagem": falhas[identificador],
                }
            )
            continue

        instalados.append(identificador)
        emitir(
            {
                "tipo": "concluido",
                "indice": indice,
                "total": total,
                "modelo": identificador,
            }
        )

    resultado = {
        "tipo": "fim",
        "instalados": instalados,
        "falhas": falhas,
        "modelo": instalados[0] if instalados else "",
    }

    emitir(resultado)

    return resultado


# ---------------------------------------------------------------------------
# Registro do modelo fine-tuned local (GGUF)
# ---------------------------------------------------------------------------

def caminho_gguf_local():
    r"""Caminho do GGUF fine-tuned disponível, ou None.

    A busca segue a ordem models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf
    (relativa à raiz do projeto) e o cache do ambiente de treino em
    D:\hf_cache. Nenhum caminho é criado: apenas verificado.
    """

    raiz = Path(config.diretorio_do_projeto())
    candidatos = (
        raiz / PASTA_GGUF_LOCAL / ARQUIVO_GGUF_LOCAL,
        GGUF_CACHE_PADRAO,
    )

    for candidato in candidatos:
        try:
            if candidato.is_file():
                return candidato
        except OSError:
            continue

    return None


def caminho_modelfile_local():
    """Caminho do template Modelfile do modelo fine-tuned."""

    return Path(config.diretorio_do_projeto()) / MODELFILE_LOCAL


def _modelfile_com_gguf(caminho_modelfile, caminho_gguf):
    """Devolve o template com apenas a linha FROM apontando o GGUF."""

    # utf-8-sig remove o BOM que o template versionado carrega; sem
    # isso a primeira linha não casaria com FROM.
    texto = Path(caminho_modelfile).read_text(encoding="utf-8-sig")
    linhas = texto.splitlines(keepends=True)

    for indice, linha in enumerate(linhas):
        if linha.lstrip().upper().startswith("FROM "):
            final = "\r\n" if linha.endswith("\r\n") else "\n"
            linhas[indice] = f"FROM {Path(caminho_gguf).resolve()}{final}"
            return "".join(linhas)

    raise ValueError("O Modelfile não possui uma linha FROM")


def registrar_modelo_local(
    host=HOST_OLLAMA_PADRAO,
    ao_progresso=None,
    gguf=None,
    modelfile=None,
    executavel=None,
):
    """Registra o GGUF fine-tuned no Ollama via ollama create.

    Só age quando o GGUF e o template existem; sem eles devolve None
    e o fluxo normal de ollama pull continua. O Modelfile enviado é
    temporário (apenas a linha FROM trocada pelo caminho absoluto do
    GGUF) e é removido ao final, com sucesso ou falha. Devolve o nome
    registrado ou None quando não foi possível concluir.
    """

    caminho_gguf = Path(gguf) if gguf else caminho_gguf_local()
    caminho_template = (
        Path(modelfile) if modelfile else caminho_modelfile_local()
    )

    if caminho_gguf is None or not caminho_gguf.is_file():
        return None

    if not caminho_template.is_file():
        return None

    executavel = executavel or localizar_ollama()

    if not executavel:
        return None

    try:
        conteudo = _modelfile_com_gguf(caminho_template, caminho_gguf)
    except (OSError, ValueError) as erro:
        _emitir_progresso(
            ao_progresso,
            {
                "tipo": "modelo_local",
                "etapa": "erro",
                "modelo": NOME_MODELO_LOCAL,
                "mensagem": f"{type(erro).__name__}: {erro}",
            },
        )
        return None

    _emitir_progresso(
        ao_progresso,
        {
            "tipo": "modelo_local",
            "etapa": "registrando",
            "modelo": NOME_MODELO_LOCAL,
        },
    )

    pasta = Path(tempfile.mkdtemp(prefix="nexusgeo_modelfile_"))
    modelfile_temporario = pasta / "Modelfile"

    try:
        modelfile_temporario.write_text(conteudo, encoding="utf-8")

        ambiente = os.environ.copy()
        servidor = str(host or HOST_OLLAMA_PADRAO).strip()
        servidor = servidor.split("://")[-1].rstrip("/")
        ambiente.setdefault("OLLAMA_HOST", servidor)

        resultado = subprocess.run(
            [
                str(executavel),
                "create",
                NOME_MODELO_LOCAL,
                "-f",
                str(modelfile_temporario),
            ],
            capture_output=True,
            text=True,
            timeout=TEMPO_LIMITE_CRIACAO_MODELO,
            env=ambiente,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        _emitir_progresso(
            ao_progresso,
            {
                "tipo": "modelo_local",
                "etapa": "erro",
                "modelo": NOME_MODELO_LOCAL,
                "mensagem": f"{type(erro).__name__}: {erro}",
            },
        )
        return None
    finally:
        shutil.rmtree(pasta, ignore_errors=True)

    if resultado.returncode != 0:
        detalhe = (resultado.stderr or resultado.stdout or "").strip()
        _emitir_progresso(
            ao_progresso,
            {
                "tipo": "modelo_local",
                "etapa": "erro",
                "modelo": NOME_MODELO_LOCAL,
                "mensagem": detalhe[:500] or "ollama create falhou",
            },
        )
        return None

    _emitir_progresso(
        ao_progresso,
        {
            "tipo": "modelo_local",
            "etapa": "registrado",
            "modelo": NOME_MODELO_LOCAL,
        },
    )

    return NOME_MODELO_LOCAL



# ---------------------------------------------------------------------------
# Download do GGUF oficial (GitHub Releases)
# ---------------------------------------------------------------------------

def baixar_gguf_oficial(
    url=URL_GGUF_OFICIAL,
    destino=None,
    ao_progresso=None,
    abrir=None,
    timeout=TIMEOUT_DOWNLOAD_OLLAMA,
):
    """Baixa o GGUF oficial para ``models\\`` com progresso em MB.

    A gravação é atômica: os bytes vão para ``.part`` e só substituem o
    destino final depois do download completo. Qualquer falha de rede ou
    disco remove o parcial e levanta :class:`ErroDownload`.
    """

    destino = Path(destino) if destino is not None else caminho_gguf_destino()
    parcial = destino.with_name(destino.name + ".part")
    abrir = abrir or (lambda endereco: _abrir_url(endereco, timeout=timeout))

    baixado = 0

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        with abrir(url) as resposta:
            total = _tamanho_download(resposta)

            with open(parcial, "wb") as arquivo:
                while True:
                    bloco = resposta.read(TAMANHO_BLOCO_DOWNLOAD)

                    if not bloco:
                        break

                    arquivo.write(bloco)
                    baixado += len(bloco)

                    _emitir_progresso(
                        ao_progresso,
                        {
                            "tipo": "progresso",
                            "baixado_bytes": baixado,
                            "total_bytes": total,
                            "percentual": calcular_percentual(
                                baixado,
                                total,
                            ),
                        },
                    )

        if baixado <= 0:
            raise ErroDownload("O download do GGUF retornou vazio")

        os.replace(parcial, destino)
    except ErroDownload:
        try:
            parcial.unlink()
        except OSError:
            pass
        raise
    except Exception as erro:
        try:
            parcial.unlink()
        except OSError:
            pass
        raise ErroDownload(
            f"Falha ao baixar o GGUF oficial: {type(erro).__name__}: {erro}"
        ) from erro

    return destino


# ---------------------------------------------------------------------------
# Persistência no config_local.json
# ---------------------------------------------------------------------------

def precisa_configurar(caminho=None):
    """Indica se o assistente ainda precisa ser executado."""

    dados = config.carregar_config_local(caminho)

    return not config.modelo_padrao_do_config(dados)


def modelos_ja_instalados(caminho=None):
    """Lista ``modelos_instalados`` do ``config_local.json``."""

    dados = config.carregar_config_local(caminho)

    return config.normalizar_lista_modelos(dados.get("modelos_instalados"))


def persistir_modelo(modelo=NOME_MODELO_LOCAL, caminho=None):
    """Grava o modelo único da v1.0.0 no ``config_local.json``.

    Escreve ``modelo_ollama``, ``modelo_padrao`` e
    ``modelos_instalados``. A lista acumula o que já estava gravado,
    sempre com o modelo configurado nesta execução na primeira posição.
    """

    modelo = str(modelo or "").strip()

    if not modelo:
        raise ValueError("Nenhum modelo válido para gravar")

    destino = (
        Path(caminho) if caminho is not None else config.caminho_config_local()
    )

    dados = config.carregar_config_local(destino)

    anteriores = config.normalizar_lista_modelos(
        dados.get("modelos_instalados")
    )

    acumulados = config.normalizar_lista_modelos([modelo] + anteriores)

    dados.update(
        {
            "versao_config": config.VERSAO_CONFIG_LOCAL,
            "modelo_ollama": modelo,
            "modelos_instalados": acumulados,
            "modelo_padrao": modelo,
            "atualizado_em": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
    )

    config.salvar_config_local(dados, destino)

    return dados


# ---------------------------------------------------------------------------
# Fluxo único do modelo oficial
# ---------------------------------------------------------------------------

def _resultado_fluxo(modelo, origem, dados):
    """Monta o dicionário de resultado do fluxo único."""

    return {
        "modelo": modelo,
        "origem": origem,
        "config": dados,
        "caminho_config": str(config.caminho_config_local()),
    }


def _aplicar_fallback_tecnico(
    motivo,
    host=HOST_OLLAMA_PADRAO,
    idioma=IDIOMA_PADRAO,
    emitir=None,
):
    """Fallback técnico único: ``ollama pull qwen3:4b``."""

    emitir = emitir or (lambda _evento: None)

    emitir(
        {
            "tipo": "status",
            "etapa": "fallback",
            "modelo": MODELO_TECNICO_FALLBACK,
            "mensagem": str(motivo or ""),
        }
    )

    def _progresso(evento):
        tipo = evento.get("tipo")

        if tipo == "inicio":
            emitir(
                {
                    "tipo": "status",
                    "etapa": "fallback_andamento",
                    "modelo": MODELO_TECNICO_FALLBACK,
                }
            )
        elif tipo == "progresso":
            emitir(evento)

    try:
        baixar_modelo(
            MODELO_TECNICO_FALLBACK,
            host=host,
            ao_progresso=_progresso,
        )
    except Exception as erro:
        raise ErroDownload(
            "Falha no fallback técnico "
            f"({MODELO_TECNICO_FALLBACK}): {type(erro).__name__}: {erro}"
        ) from erro

    dados = persistir_modelo(MODELO_TECNICO_FALLBACK)
    resultado = _resultado_fluxo(
        MODELO_TECNICO_FALLBACK,
        "fallback",
        dados,
    )

    emitir({"tipo": "finalizado", "resultado": resultado})

    return resultado


def garantir_modelo_oficial(
    forcar=False,
    host=HOST_OLLAMA_PADRAO,
    idioma=IDIOMA_PADRAO,
    ao_progresso=None,
):
    """Executa o fluxo único do modelo oficial e devolve o resultado.

    Ordem: modelo já registrado -> GGUF local -> download do GGUF oficial
    -> fallback técnico ``qwen3:4b``. ``forcar=True`` ignora o atalho
    do modelo já registrado e refaz o registro/download.
    """

    def emitir(evento):
        _emitir_progresso(ao_progresso, evento)

    if not forcar and modelo_local_registrado(host):
        dados = persistir_modelo(NOME_MODELO_LOCAL)
        resultado = _resultado_fluxo(
            NOME_MODELO_LOCAL,
            "registrado",
            dados,
        )
        emitir({"tipo": "finalizado", "resultado": resultado})
        return resultado

    emitir({"tipo": "status", "etapa": "verificando"})

    # Garante o Ollama instalado e respondendo antes de registrar ou
    # baixar qualquer coisa. Sem isso o fluxo falharia no primeiro uso
    # de uma máquina que ainda não tem o serviço.
    servico = garantir_servico_ollama(
        host,
        callback_progresso=ao_progresso,
    )

    if not servico.get("ativo"):
        raise ErroDownload(
            "Ollama indisponível: "
            f"{servico.get('mensagem') or 'serviço não respondeu'}"
        )

    gguf = caminho_gguf_local()

    if gguf is None:
        emitir({"tipo": "status", "etapa": "baixando_gguf"})

        try:
            gguf = baixar_gguf_oficial(ao_progresso=ao_progresso)
        except ErroDownload as erro:
            return _aplicar_fallback_tecnico(
                erro,
                host=host,
                idioma=idioma,
                emitir=emitir,
            )

    emitir({"tipo": "status", "etapa": "registrando"})

    registrado = registrar_modelo_local(
        host=host,
        ao_progresso=ao_progresso,
        gguf=gguf,
    )

    if registrado:
        dados = persistir_modelo(NOME_MODELO_LOCAL)
        resultado = _resultado_fluxo(
            NOME_MODELO_LOCAL,
            "gguf",
            dados,
        )
        emitir({"tipo": "finalizado", "resultado": resultado})
        return resultado

    return _aplicar_fallback_tecnico(
        "ollama create não registrou o GGUF local",
        host=host,
        idioma=idioma,
        emitir=emitir,
    )



# ---------------------------------------------------------------------------
# Textos da interface (PT-BR / EN)
# ---------------------------------------------------------------------------

TEXTOS = {
    "pt": {
        "titulo": (
            f"{config.APP_NAME} v{config.APP_VERSION} — Modelo Local"
        ),
        "subtitulo": (
            "Configuração do modelo oficial nexusgeo-qwen3-4b-v2-q4 "
            "(GGUF Q4_K_M). O download pode levar alguns minutos."
        ),
        "idioma": "Idioma / Language:",
        "status_iniciando": "Preparando a configuração do modelo oficial...",
        "status_verificando": "Verificando o modelo oficial no Ollama...",
        "status_baixando_gguf": (
            "Baixando o modelo oficial ({baixado} de {total})..."
        ),
        "status_baixando_gguf_sem_total": (
            "Baixando o modelo oficial: {baixado}..."
        ),
        "status_registrando": "Registrando o modelo oficial no Ollama...",
        "status_fallback": (
            "Download indisponível; aplicando o fallback técnico "
            "{modelo}..."
        ),
        "status_fallback_andamento": (
            "Baixando o fallback técnico {modelo} pelo Ollama..."
        ),
        "status_concluido": "Modelo configurado: {modelo}",
        "sucesso_titulo": "Modelo pronto",
        "sucesso_mensagem": (
            "Modelo configurado: {modelo}\n\n"
            "Configuração gravada em:\n{config}"
        ),
        "falha_titulo": "Falha na configuração",
        "falha_mensagem": (
            "Não foi possível configurar o modelo local:\n{mensagem}"
        ),
        "cancelar": "Cancelar",
        "fechar_titulo": "Fechar assistente",
        "fechar_baixando": (
            "O download está em andamento. Deseja realmente fechar?"
        ),
        "ja_configurado": (
            "Modelo oficial já configurado. Use --forcar para refazer "
            "a verificação e o registro."
        ),
        "sem_interface": (
            "Não foi possível abrir a interface gráfica (Tkinter). "
            "Executando o mesmo fluxo no terminal."
        ),
        "ollama_ausente": (
            "O Ollama não foi encontrado. Iniciando a instalação "
            "automática e silenciosa..."
        ),
        "ollama_baixando": (
            "Baixando o instalador do Ollama: {percentual}% "
            "({baixado} de {total})"
        ),
        "ollama_baixando_sem_total": (
            "Baixando o instalador do Ollama: {baixado}"
        ),
        "ollama_instalando": (
            "Instalando o Ollama silenciosamente (/VERYSILENT)..."
        ),
        "ollama_iniciando": (
            "Iniciando o serviço local do Ollama em {host}..."
        ),
        "ollama_instalado": "Ollama instalado em {caminho}",
        "ollama_instalacao_falhou": (
            "Não foi possível instalar o Ollama automaticamente: "
            "{mensagem}"
        ),
        "permissao_modelos_titulo": (
            "Permissão negada na pasta de modelos do Ollama"
        ),
        "permissao_modelos_mensagem": (
            "A pasta de modelos do Ollama está bloqueada por permissão "
            "do Windows:\n\n"
            "{pasta}\n\n"
            "Isso acontece quando o Ollama já foi executado como "
            "Administrador ou instalado como serviço. Feche o Ollama e "
            "escolha uma das correções:\n\n"
            "1) Libere a pasta para o seu usuário em um Prompt de "
            "Comando como Administrador:\n"
            "   icacls \"{pasta}\" /grant \"%USERNAME%\":(OI)(CI)F /T\n\n"
            "2) Use uma pasta gravável definindo a variável "
            "OLLAMA_MODELS antes de abrir o NexusGeo IA, por exemplo:\n"
            "   setx OLLAMA_MODELS \"D:\\ollama_models\"\n\n"
            "Depois feche e reabra o NexusGeo IA e o Ollama.\n\n"
            "Erro original: {mensagem}"
        ),
        "cli_titulo": (
            "=== Configuração do modelo local "
            f"({config.APP_NAME} v{config.APP_VERSION}) ==="
        ),
        "cli_sucesso": (
            "Configuração gravada em:\n{config}\nModelo: {modelo}"
        ),
        "cli_falha": (
            "Não foi possível configurar o modelo local: {mensagem}"
        ),
        "cli_cancelado": (
            "Operação cancelada; nenhum modelo foi configurado."
        ),
    },
    "en": {
        "titulo": (
            f"{config.APP_NAME} v{config.APP_VERSION} — Local Model"
        ),
        "subtitulo": (
            "Configuration of the official nexusgeo-qwen3-4b-v2-q4 model "
            "(Q4_K_M GGUF). The download may take a few minutes."
        ),
        "idioma": "Language / Idioma:",
        "status_iniciando": "Preparing the official model configuration...",
        "status_verificando": "Checking the official model in Ollama...",
        "status_baixando_gguf": (
            "Downloading the official model ({baixado} of {total})..."
        ),
        "status_baixando_gguf_sem_total": (
            "Downloading the official model: {baixado}..."
        ),
        "status_registrando": "Registering the official model in Ollama...",
        "status_fallback": (
            "Download unavailable; applying the technical fallback "
            "{modelo}..."
        ),
        "status_fallback_andamento": (
            "Downloading the technical fallback {modelo} through Ollama..."
        ),
        "status_concluido": "Model configured: {modelo}",
        "sucesso_titulo": "Model ready",
        "sucesso_mensagem": (
            "Model configured: {modelo}\n\n"
            "Configuration written to:\n{config}"
        ),
        "falha_titulo": "Configuration failed",
        "falha_mensagem": (
            "The local model could not be configured:\n{mensagem}"
        ),
        "cancelar": "Cancel",
        "fechar_titulo": "Close assistant",
        "fechar_baixando": (
            "A download is in progress. Do you really want to close?"
        ),
        "ja_configurado": (
            "The official model is already configured. Use --forcar to "
            "rerun the check and registration."
        ),
        "sem_interface": (
            "The graphical interface (Tkinter) could not be opened. "
            "Running the same flow in the terminal."
        ),
        "ollama_ausente": (
            "Ollama was not found. Starting the automatic silent "
            "installation..."
        ),
        "ollama_baixando": (
            "Downloading the Ollama installer: {percentual}% "
            "({baixado} of {total})"
        ),
        "ollama_baixando_sem_total": (
            "Downloading the Ollama installer: {baixado}"
        ),
        "ollama_instalando": (
            "Installing Ollama silently (/VERYSILENT)..."
        ),
        "ollama_iniciando": (
            "Starting the local Ollama service at {host}..."
        ),
        "ollama_instalado": "Ollama installed at {caminho}",
        "ollama_instalacao_falhou": (
            "Ollama could not be installed automatically: {mensagem}"
        ),
        "permissao_modelos_titulo": (
            "Access denied in the Ollama models folder"
        ),
        "permissao_modelos_mensagem": (
            "The Ollama models folder is blocked by a Windows "
            "permission:\n\n"
            "{pasta}\n\n"
            "This happens when Ollama was already run as Administrator "
            "or installed as a service. Close Ollama and pick one of "
            "the fixes:\n\n"
            "1) Grant your user access from an Administrator Command "
            "Prompt:\n"
            "   icacls \"{pasta}\" /grant \"%USERNAME%\":(OI)(CI)F /T\n\n"
            "2) Use a writable folder by setting the OLLAMA_MODELS "
            "environment variable before opening NexusGeo IA, for "
            "example:\n"
            "   setx OLLAMA_MODELS \"D:\\ollama_models\"\n\n"
            "Then close and reopen NexusGeo IA and Ollama.\n\n"
            "Original error: {mensagem}"
        ),
        "cli_titulo": (
            "=== Local model configuration "
            f"({config.APP_NAME} v{config.APP_VERSION}) ==="
        ),
        "cli_sucesso": (
            "Configuration written to:\n{config}\nModel: {modelo}"
        ),
        "cli_falha": (
            "The local model could not be configured: {mensagem}"
        ),
        "cli_cancelado": (
            "Operation cancelled; no model was configured."
        ),
    },
}


def texto(chave, idioma=IDIOMA_PADRAO, **valores):
    """Texto traduzido com fallback para PT-BR e para a própria chave."""

    tabela = TEXTOS.get(idioma) or TEXTOS[IDIOMA_PADRAO]
    mensagem = tabela.get(chave) or TEXTOS[IDIOMA_PADRAO].get(chave, chave)

    if valores:
        try:
            return mensagem.format(**valores)
        except (KeyError, IndexError, ValueError):
            return mensagem

    return mensagem



# ---------------------------------------------------------------------------
# Interface gráfica minimalista (progresso do fluxo único)
# ---------------------------------------------------------------------------

LARGURA_JANELA = 640
ALTURA_JANELA = 300


def abrir_interface(forcar=False, oculta=False):
    """Abre a janela de progresso do fluxo único e só retorna ao fechar.

    Sem tabela, sem checkboxes e sem sugestão por RAM: a janela apenas
    acompanha o download/registro do modelo oficial, com troca de
    idioma PT-BR/EN. O ``tkinter`` é importado aqui dentro para o
    módulo continuar testável em ambientes sem interface.
    """

    import tkinter as tk
    from tkinter import messagebox, ttk

    estado = {
        "idioma": IDIOMA_PADRAO,
        "em_andamento": False,
        "baixado_bytes": 0,
        "total_bytes": None,
        "fila": queue.Queue(),
    }

    raiz = tk.Tk()
    raiz.title(texto("titulo"))
    raiz.geometry(f"{LARGURA_JANELA}x{ALTURA_JANELA}")
    raiz.minsize(560, 280)

    if oculta:
        raiz.withdraw()

    try:
        raiz.columnconfigure(0, weight=1)
    except tk.TclError:  # pragma: no cover - janela exótica
        pass

    estilo = ttk.Style(master=raiz)

    try:
        estilo.theme_use("clam")
    except tk.TclError:  # pragma: no cover - tema indisponível
        pass

    estilo.configure("Titulo.TLabel", font=("Segoe UI", 15, "bold"))
    estilo.configure("Subtitulo.TLabel", foreground="#4a4a4a")
    estilo.configure("Destaque.TLabel", font=("Segoe UI", 10, "bold"))

    quadro = ttk.Frame(raiz, padding=(18, 16, 18, 14))
    quadro.grid(row=0, column=0, sticky="nsew")
    quadro.columnconfigure(0, weight=1)

    rotulo_titulo = ttk.Label(
        quadro,
        text=texto("titulo"),
        style="Titulo.TLabel",
    )
    rotulo_titulo.grid(row=0, column=0, sticky="w")

    rotulo_subtitulo = ttk.Label(
        quadro,
        text=texto("subtitulo"),
        style="Subtitulo.TLabel",
        wraplength=560,
        justify="left",
    )
    rotulo_subtitulo.grid(row=1, column=0, sticky="w", pady=(4, 12))

    idioma_var = tk.StringVar(master=raiz, value=estado["idioma"])

    seletor_idioma = ttk.Frame(quadro)
    seletor_idioma.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))

    rotulo_idioma = ttk.Label(seletor_idioma, text=texto("idioma"))
    rotulo_idioma.grid(row=0, column=0, columnspan=2, sticky="e")

    def _mudar_idioma():
        estado["idioma"] = idioma_var.get()
        _aplicar_idioma()

    radio_pt = ttk.Radiobutton(
        seletor_idioma,
        text="PT-BR",
        value="pt",
        variable=idioma_var,
        command=_mudar_idioma,
    )
    radio_pt.grid(row=1, column=0, sticky="e")

    radio_en = ttk.Radiobutton(
        seletor_idioma,
        text="EN",
        value="en",
        variable=idioma_var,
        command=_mudar_idioma,
    )
    radio_en.grid(row=1, column=1, sticky="e", padx=(8, 0))

    status_var = tk.StringVar(master=raiz, value=texto("status_iniciando"))
    rotulo_status = ttk.Label(
        quadro,
        textvariable=status_var,
        style="Destaque.TLabel",
        wraplength=560,
        justify="left",
    )
    rotulo_status.grid(row=2, column=0, columnspan=2, sticky="w")

    barra_progresso = ttk.Progressbar(
        quadro,
        orient="horizontal",
        mode="determinate",
        maximum=100.0,
    )
    barra_progresso.grid(
        row=3,
        column=0,
        columnspan=2,
        sticky="ew",
        pady=(10, 12),
    )

    acoes = ttk.Frame(quadro)
    acoes.grid(row=4, column=0, columnspan=2, sticky="e")

    botao_cancelar = ttk.Button(
        acoes,
        text=texto("cancelar"),
        command=lambda: _fechar(confirmar=True),
    )
    botao_cancelar.grid(row=0, column=0)

    def _aplicar_idioma():
        idioma = estado["idioma"]

        raiz.title(texto("titulo", idioma))
        rotulo_titulo.configure(text=texto("titulo", idioma))
        rotulo_subtitulo.configure(text=texto("subtitulo", idioma))
        rotulo_idioma.configure(text=texto("idioma", idioma))
        botao_cancelar.configure(text=texto("cancelar", idioma))

        if not estado["em_andamento"]:
            status_var.set(texto("status_iniciando", idioma))
        elif estado["total_bytes"]:
            status_var.set(
                texto(
                    "status_baixando_gguf",
                    idioma,
                    baixado=formatar_mb(estado["baixado_bytes"], idioma),
                    total=formatar_mb(estado["total_bytes"], idioma),
                )
            )

    def _iniciar():
        estado["em_andamento"] = True
        status_var.set(texto("status_verificando", estado["idioma"]))
        threading.Thread(target=_trabalhar, daemon=True).start()

    def _trabalhar():
        try:
            resultado = garantir_modelo_oficial(
                forcar=forcar,
                ao_progresso=estado["fila"].put,
            )
        except Exception as erro:
            estado["fila"].put(
                {
                    "tipo": "erro",
                    "mensagem": f"{type(erro).__name__}: {erro}",
                }
            )
            return

        estado["fila"].put({"tipo": "finalizado", "resultado": resultado})

    def _tratar_evento(evento):
        tipo = evento.get("tipo")
        idioma = estado["idioma"]

        if tipo == "ollama":
            etapa = evento.get("etapa")
            idioma = estado["idioma"]

            if etapa == "ausente":
                status_var.set(texto("ollama_ausente", idioma))
            elif etapa == "baixando":
                baixado = formatar_mb(
                    evento.get("baixado_bytes") or 0,
                    idioma,
                )
                percentual = evento.get("percentual")

                if percentual is not None and evento.get("total_bytes"):
                    status_var.set(
                        texto(
                            "ollama_baixando",
                            idioma,
                            percentual=f"{float(percentual):.0f}",
                            baixado=baixado,
                            total=formatar_mb(
                                evento.get("total_bytes"),
                                idioma,
                            ),
                        )
                    )
                    barra_progresso["value"] = float(percentual)
                else:
                    status_var.set(
                        texto(
                            "ollama_baixando_sem_total",
                            idioma,
                            baixado=baixado,
                        )
                    )
            elif etapa == "instalando":
                status_var.set(texto("ollama_instalando", idioma))
            elif etapa == "instalado":
                status_var.set(
                    texto(
                        "ollama_instalado",
                        idioma,
                        caminho=evento.get("caminho") or "",
                    )
                )
            elif etapa == "iniciando_servico":
                status_var.set(
                    texto(
                        "ollama_iniciando",
                        idioma,
                        host=evento.get("host") or HOST_OLLAMA_PADRAO,
                    )
                )
            elif etapa == "erro":
                status_var.set(
                    texto(
                        "ollama_instalacao_falhou",
                        idioma,
                        mensagem=evento.get("mensagem") or "",
                    )
                )
            return

        if tipo == "status":
            etapa = evento.get("etapa")

            if etapa == "verificando":
                status_var.set(texto("status_verificando", idioma))
            elif etapa == "baixando_gguf":
                barra_progresso["value"] = 0.0
                status_var.set(
                    texto(
                        "status_baixando_gguf_sem_total",
                        idioma,
                        baixado=formatar_mb(0, idioma),
                    )
                )
            elif etapa == "registrando":
                barra_progresso["value"] = 100.0
                status_var.set(texto("status_registrando", idioma))
            elif etapa == "fallback":
                barra_progresso["value"] = 0.0
                status_var.set(
                    texto(
                        "status_fallback",
                        idioma,
                        modelo=evento.get("modelo")
                        or MODELO_TECNICO_FALLBACK,
                    )
                )
            elif etapa == "fallback_andamento":
                status_var.set(
                    texto(
                        "status_fallback_andamento",
                        idioma,
                        modelo=evento.get("modelo")
                        or MODELO_TECNICO_FALLBACK,
                    )
                )
            return

        if tipo == "progresso":
            percentual = evento.get("percentual")

            if percentual is not None:
                barra_progresso["value"] = float(percentual)

            estado["baixado_bytes"] = evento.get("baixado_bytes") or 0
            estado["total_bytes"] = evento.get("total_bytes")

            if estado["total_bytes"]:
                status_var.set(
                    texto(
                        "status_baixando_gguf",
                        idioma,
                        baixado=formatar_mb(
                            estado["baixado_bytes"],
                            idioma,
                        ),
                        total=formatar_mb(
                            estado["total_bytes"],
                            idioma,
                        ),
                    )
                )
            else:
                status_var.set(
                    texto(
                        "status_baixando_gguf_sem_total",
                        idioma,
                        baixado=formatar_mb(
                            estado["baixado_bytes"],
                            idioma,
                        ),
                    )
                )
            return

        if tipo == "erro":
            estado["em_andamento"] = False
            botao_cancelar.state(["!disabled"])
            messagebox.showerror(
                texto("falha_titulo", idioma),
                texto(
                    "falha_mensagem",
                    idioma,
                    mensagem=evento.get("mensagem") or "",
                ),
                parent=raiz,
            )
            return

        if tipo == "finalizado":
            estado["em_andamento"] = False
            resultado = evento.get("resultado") or {}
            modelo = resultado.get("modelo") or NOME_MODELO_LOCAL

            status_var.set(
                texto("status_concluido", idioma, modelo=modelo)
            )
            barra_progresso["value"] = 100.0

            messagebox.showinfo(
                texto("sucesso_titulo", idioma),
                texto(
                    "sucesso_mensagem",
                    idioma,
                    modelo=modelo,
                    config=resultado.get("caminho_config")
                    or str(config.caminho_config_local()),
                ),
                parent=raiz,
            )

            _fechar(confirmar=False)
            return

    def _processar_fila():
        while True:
            try:
                evento = estado["fila"].get_nowait()
            except queue.Empty:
                break

            try:
                _tratar_evento(evento)
            except tk.TclError:  # janela já fechada
                return

        try:
            raiz.after(120, _processar_fila)
        except tk.TclError:  # pragma: no cover
            pass

    def _fechar(confirmar=True):
        if (
            confirmar
            and estado["em_andamento"]
            and not messagebox.askyesno(
                texto("fechar_titulo", estado["idioma"]),
                texto("fechar_baixando", estado["idioma"]),
                parent=raiz,
            )
        ):
            return

        try:
            raiz.destroy()
        except tk.TclError:  # pragma: no cover
            pass

    raiz.protocol("WM_DELETE_WINDOW", _fechar)

    raiz.after(150, _iniciar)
    raiz.after(200, _processar_fila)

    try:
        raiz.mainloop()
    except tk.TclError:  # pragma: no cover - fechamento abrupto
        return


# ---------------------------------------------------------------------------
# Fallback de terminal (sem Tkinter)
# ---------------------------------------------------------------------------

def tkinter_disponivel():
    """Indica se o ``tkinter`` pode ser importado neste interpretador."""

    try:
        import tkinter  # noqa: F401
    except (ImportError, OSError):
        return False

    return True


def interface_indisponivel(erro):
    """Diz se a falha da janela justifica cair para o terminal."""

    if isinstance(erro, ImportError):
        return True

    try:
        import tkinter
    except (ImportError, OSError):
        return True

    return isinstance(erro, tkinter.TclError)


def _imprimir(mensagem):
    """``print`` seguro em executável sem console (``sys.stdout`` nulo)."""

    fluxo = sys.stdout

    if fluxo is None:
        return

    try:
        print(mensagem, file=fluxo)
    except (OSError, ValueError):  # pragma: no cover
        pass


def _texto_status_cli(evento, idioma):
    """Traduz um evento de status/progresso do fluxo para o terminal."""

    tipo = evento.get("tipo")

    if tipo == "ollama":
        etapa = evento.get("etapa")

        if etapa == "ausente":
            return texto("ollama_ausente", idioma)
        if etapa == "baixando":
            baixado = formatar_mb(evento.get("baixado_bytes") or 0, idioma)
            percentual = evento.get("percentual")

            if percentual is not None and evento.get("total_bytes"):
                return texto(
                    "ollama_baixando",
                    idioma,
                    percentual=f"{float(percentual):.0f}",
                    baixado=baixado,
                    total=formatar_mb(evento.get("total_bytes"), idioma),
                )

            return texto(
                "ollama_baixando_sem_total",
                idioma,
                baixado=baixado,
            )
        if etapa == "instalando":
            return texto("ollama_instalando", idioma)
        if etapa == "instalado":
            return texto(
                "ollama_instalado",
                idioma,
                caminho=evento.get("caminho") or "",
            )
        if etapa == "iniciando_servico":
            return texto(
                "ollama_iniciando",
                idioma,
                host=evento.get("host") or HOST_OLLAMA_PADRAO,
            )
        if etapa == "erro":
            return texto(
                "ollama_instalacao_falhou",
                idioma,
                mensagem=evento.get("mensagem") or "",
            )

        return ""

    if tipo == "status":
        etapa = evento.get("etapa")

        if etapa == "verificando":
            return texto("status_verificando", idioma)
        if etapa == "baixando_gguf":
            return texto(
                "status_baixando_gguf_sem_total",
                idioma,
                baixado=formatar_mb(0, idioma),
            )
        if etapa == "registrando":
            return texto("status_registrando", idioma)
        if etapa == "fallback":
            return texto(
                "status_fallback",
                idioma,
                modelo=evento.get("modelo") or MODELO_TECNICO_FALLBACK,
            )
        if etapa == "fallback_andamento":
            return texto(
                "status_fallback_andamento",
                idioma,
                modelo=evento.get("modelo") or MODELO_TECNICO_FALLBACK,
            )

        return ""

    if tipo == "progresso":
        total = evento.get("total_bytes")

        if total:
            return texto(
                "status_baixando_gguf",
                idioma,
                baixado=formatar_mb(evento.get("baixado_bytes") or 0, idioma),
                total=formatar_mb(total, idioma),
            )

        return texto(
            "status_baixando_gguf_sem_total",
            idioma,
            baixado=formatar_mb(evento.get("baixado_bytes") or 0, idioma),
        )

    return ""


def executar_fluxo_cli(idioma=IDIOMA_PADRAO, forcar=False):
    """Executa o fluxo único no terminal, sem depender do Tkinter.

    Devolve ``0`` quando o ``config_local.json`` foi gravado e
    ``1`` em qualquer falha.
    """

    _imprimir("")
    _imprimir(texto("cli_titulo", idioma))
    _imprimir("")

    ultimo = {"texto": "", "percentual": -10.0}

    def _ao_progresso(evento):
        # O terminal não precisa de uma linha por MB: imprime no máximo a
        # cada 10% de avanço, além das mudanças de etapa.
        if evento.get("tipo") == "progresso":
            percentual = evento.get("percentual")

            if percentual is not None:
                if float(percentual) < ultimo["percentual"] + 10.0:
                    return

                ultimo["percentual"] = float(percentual)

        mensagem = _texto_status_cli(evento, idioma)

        if mensagem and mensagem != ultimo["texto"]:
            ultimo["texto"] = mensagem
            _imprimir(mensagem)

    try:
        resultado = garantir_modelo_oficial(
            forcar=forcar,
            idioma=idioma,
            ao_progresso=_ao_progresso,
        )
    except Exception as erro:
        _imprimir(
            texto(
                "cli_falha",
                idioma,
                mensagem=f"{type(erro).__name__}: {erro}",
            )
        )
        return 1

    _imprimir(
        texto(
            "cli_sucesso",
            idioma,
            config=resultado.get("caminho_config")
            or str(config.caminho_config_local()),
            modelo=resultado.get("modelo") or NOME_MODELO_LOCAL,
        )
    )

    return 0


# ---------------------------------------------------------------------------
# Entrada do script
# ---------------------------------------------------------------------------

def principal(argv=None):
    """Ponto de entrada do fluxo único da v1.0.0.

    Sem ``--forcar``, o modelo oficial já registrado no Ollama grava o
    ``config_local.json`` e encerra sem abrir janela. GGUF local é
    registrado automaticamente; só a ausência do arquivo abre a janela
    de download.
    """

    analisador = argparse.ArgumentParser(
        prog="setup_llm.py",
        description=(
            "Configurador do modelo local único do "
            f"{config.APP_NAME} v{config.APP_VERSION} (Ollama)."
        ),
    )
    analisador.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "refaz a verificação e o registro mesmo quando o modelo "
            "oficial já está configurado"
        ),
    )

    argumentos = analisador.parse_args(argv)
    host = HOST_OLLAMA_PADRAO

    if not argumentos.forcar and modelo_local_registrado(host):
        persistir_modelo(NOME_MODELO_LOCAL)
        _imprimir(texto("ja_configurado"))
        return 0

    gguf = caminho_gguf_local()

    if gguf is not None:
        registrado = registrar_modelo_local(host=host, gguf=gguf)

        if registrado:
            persistir_modelo(NOME_MODELO_LOCAL)
            _imprimir(
                texto(
                    "cli_sucesso",
                    IDIOMA_PADRAO,
                    config=str(config.caminho_config_local()),
                    modelo=NOME_MODELO_LOCAL,
                )
            )
            return 0

    if not tkinter_disponivel():
        _imprimir(texto("sem_interface"))
        return executar_fluxo_cli(forcar=argumentos.forcar)

    try:
        abrir_interface(forcar=argumentos.forcar)
    except Exception as erro:  # TclError, sem display, etc.
        _imprimir(texto("sem_interface"))
        _imprimir(f"Detalhe: {type(erro).__name__}: {erro}")

        if interface_indisponivel(erro):
            return executar_fluxo_cli(forcar=argumentos.forcar)

        return 1

    return 0


def main(argv=None):
    """Alias público usado pelo ``launcher_desktop.py``."""

    return principal(argv)


if __name__ == "__main__":
    raise SystemExit(main())
