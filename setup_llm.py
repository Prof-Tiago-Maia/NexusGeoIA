"""Assistente gráfico de seleção e download dos modelos LLM do Ollama.

Este script roda **antes da primeira abertura** do NexusGeo IA. Ele:

1. verifica se o Ollama está instalado e acessível em ``/api/tags``.
   Quando o executável não existe, baixa o ``OllamaSetup.exe`` oficial
   para uma pasta temporária única (com progresso em MB/percentual na
   janela ou no terminal), exige assinatura Authenticode válida do
   fornecedor Ollama e só então o instala em silêncio com
   ``/VERYSILENT /NORESTART``;
   em seguida inclui ``%LOCALAPPDATA%\\Programs\\Ollama`` no ``PATH`` da
   sessão e sobe ``ollama serve`` em segundo plano, sem janela, quando o
   serviço ainda não está respondendo;
2. detecta a RAM total da máquina (``psutil`` quando disponível, senão
   ``ctypes`` no Windows) e pré-marca o modelo mais adequado;
3. apresenta **exatamente três modelos**, com checkboxes
   (``tk.Checkbutton``) para selecionar um, dois ou todos, com perfil de
   hardware, RAM ocupada e comportamento esperado em PT-BR ou EN;
4. baixa os modelos marcados em sequência, consumindo
   ``POST /api/pull`` em streaming e mostrando ``completed``/``total``
   na barra de progresso;
5. grava ``modelos_instalados`` e ``modelo_padrao`` no
   ``config_local.json`` do diretório de dados do aplicativo.

Não há campo de texto livre nem catálogo além dos três modelos
suportados pelo instalador. A dependência de interface é apenas o
``tkinter`` que acompanha o Python; quando ele não está disponível
(Embeddable sem Tcl/Tk), o assistente cai para um seletor numérico no
próprio terminal. O download usa ``requests`` e cai para ``urllib``
quando o pacote não está instalado.

Uso:

    python setup_llm.py
    python setup_llm.py --forcar

``--forcar`` reabre o seletor mesmo quando o ``config_local.json`` já
existe, permitindo baixar modelos adicionais a qualquer momento (é o que
o atalho *Gerenciar Modelos LLM* do instalador executa).
"""

from __future__ import annotations

import argparse
import ctypes
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
from dataclasses import dataclass
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
# Catálogo dos três modelos suportados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeloLLM:
    """Um modelo do catálogo, com os textos nos dois idiomas."""

    identificador: str
    ram_gb: float
    perfil_pt: str
    perfil_en: str
    comportamento_pt: str
    comportamento_en: str

    def perfil(self, idioma=IDIOMA_PADRAO):
        """Perfil de hardware no idioma pedido (PT-BR como fallback)."""

        return self.perfil_pt if idioma == "pt" else self.perfil_en

    def comportamento(self, idioma=IDIOMA_PADRAO):
        """Comportamento esperado no idioma pedido."""

        return (
            self.comportamento_pt
            if idioma == "pt"
            else self.comportamento_en
        )

    def ram_formatada(self, idioma=IDIOMA_PADRAO):
        """RAM ocupada aproximada, com vírgula decimal em PT-BR."""

        return formatar_ram(self.ram_gb, idioma)


CATALOGO_MODELOS = (
    ModeloLLM(
        identificador="qwen3:4b",
        ram_gb=2.6,
        perfil_pt=(
            "Sem GPU dedicada + 16 GB RAM "
            "(Padrão do Instalador Offline)"
        ),
        perfil_en=(
            "No dedicated GPU + 16 GB RAM "
            "(Offline Installer Default)"
        ),
        comportamento_pt=(
            "Roteamento JSON rápido, síntese RAG fluida "
            "(18–28 tok/s) sem travar o sistema."
        ),
        comportamento_en=(
            "Fast JSON routing, fluid RAG synthesis "
            "(18–28 tok/s) without freezing the system."
        ),
    ),
    ModeloLLM(
        identificador="qwen3:14b",
        ram_gb=9.0,
        perfil_pt=(
            "Workstation / GPU dedicada "
            "(≥ 8 GB VRAM ou 32+ GB RAM)"
        ),
        perfil_en=(
            "Workstation / dedicated GPU "
            "(≥ 8 GB VRAM or 32+ GB RAM)"
        ),
        comportamento_pt=(
            "Máxima profundidade analítica para cruzamento de "
            "múltiplos relatórios."
        ),
        comportamento_en=(
            "Maximum analytical depth for cross-referencing "
            "multiple reports."
        ),
    ),
    ModeloLLM(
        identificador="qwen2.5:3b",
        ram_gb=1.9,
        perfil_pt="Notebooks antigos (8 GB RAM)",
        perfil_en="Older laptops (8 GB RAM)",
        comportamento_pt=(
            "Operação ultraleve para resumos objetivos e "
            "consultas rápidas."
        ),
        comportamento_en=(
            "Ultra-light operation for objective summaries and "
            "quick queries."
        ),
    ),
)


def identificadores_modelos():
    """IDs dos três modelos, na ordem exibida na interface."""

    return [modelo.identificador for modelo in CATALOGO_MODELOS]


def obter_modelo(identificador):
    """Devolve o ``ModeloLLM`` do catálogo ou ``None``."""

    for modelo in CATALOGO_MODELOS:
        if modelo.identificador == identificador:
            return modelo

    return None


def normalizar_modelos(selecionados):
    """Filtra uma seleção, mantendo só IDs do catálogo e sem repetição."""

    selecionados = config.normalizar_lista_modelos(selecionados)

    return [
        identificador
        for identificador in selecionados
        if obter_modelo(identificador) is not None
    ]


def formatar_ram(valor_gb, idioma=IDIOMA_PADRAO):
    """Formata a RAM em GB com uma casa decimal (vírgula em PT-BR)."""

    try:
        texto = f"{float(valor_gb):.1f}"
    except (TypeError, ValueError):
        return "—"

    if idioma == "pt":
        texto = texto.replace(".", ",")

    return f"~{texto} GB"


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


def estimar_ram_gb(selecionados):
    """RAM total aproximada dos modelos marcados, em GB."""

    total = 0.0

    for identificador in normalizar_modelos(selecionados):
        modelo = obter_modelo(identificador)

        if modelo is not None:
            total += modelo.ram_gb

    return round(total, 1)


def modelo_padrao(selecionados):
    """Modelo padrão do ``config_local.json`` segundo a prioridade do app.

    ``qwen3:14b`` > ``qwen3:4b`` > ``qwen2.5:3b``; sem nenhum modelo
    conhecido devolve string vazia.
    """

    selecionados = normalizar_modelos(selecionados)

    for preferido in config.PRIORIDADE_MODELOS_PADRAO:
        if preferido in selecionados:
            return preferido

    return selecionados[0] if selecionados else ""


# ---------------------------------------------------------------------------
# Memória RAM da máquina
# ---------------------------------------------------------------------------

class _EstadoMemoriaWindows(ctypes.Structure):
    """Estrutura ``MEMORYSTATUSEX`` usada pela API do Windows."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _ram_psutil():
    """RAM total via ``psutil`` quando o pacote está instalado."""

    try:
        import psutil
    except ImportError:
        return None

    try:
        return float(psutil.virtual_memory().total) / (1024 ** 3)
    except (AttributeError, OSError, ValueError):
        return None


def _ram_windows():
    """RAM total via ``GlobalMemoryStatusEx`` (sem dependências)."""

    if os.name != "nt":
        return None

    try:
        estado = _EstadoMemoriaWindows()
        estado.dwLength = ctypes.sizeof(_EstadoMemoriaWindows)

        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
            ctypes.byref(estado)
        ):
            return None

        return float(estado.ullTotalPhys) / (1024 ** 3)
    except (AttributeError, OSError, ValueError):
        return None


def _ram_posix():
    """RAM total via ``sysconf`` em Linux/macOS."""

    if not hasattr(os, "sysconf"):
        return None

    try:
        paginas = os.sysconf("SC_PHYS_PAGES")
        tamanho = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None

    if paginas <= 0 or tamanho <= 0:
        return None

    return float(paginas * tamanho) / (1024 ** 3)


def memoria_total_gb():
    """RAM total detectada em GB (arredondada) ou ``None``."""

    for detector in (_ram_psutil, _ram_windows, _ram_posix):
        valor = detector()

        if valor and valor > 0:
            return round(valor, 1)

    return None


def modelos_iniciais(ram_gb=None):
    """Seleção pré-marcada conforme a RAM disponível.

    - 8 GB ou menos: ``qwen2.5:3b``;
    - 32 GB ou mais: ``qwen3:14b``;
    - faixa intermediária (o padrão do instalador): ``qwen3:4b``.

    Sem leitura de RAM, mantém o padrão ``qwen3:4b``.
    """

    if ram_gb is None:
        ram_gb = memoria_total_gb()

    if ram_gb is not None:
        if ram_gb >= 31.0:
            return ["qwen3:14b"]

        if ram_gb < 12.0:
            return ["qwen2.5:3b"]

    return ["qwen3:4b"]


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
    selecionados,
    host=HOST_OLLAMA_PADRAO,
    ao_progresso=None,
    sessao=None,
    idioma=IDIOMA_PADRAO,
):
    """Baixa os modelos marcados em sequência.

    Emite eventos para a interface:

    - ``inicio`` (com ``indice``/``total``/``modelo`` e o texto pronto);
    - ``progresso`` (``completed``/``total``/``percentual``);
    - ``concluido`` e ``erro`` por modelo;
    - ``fim`` com ``instalados`` e ``falhas``.

    Uma falha em um modelo não interrompe os seguintes. Falhas de
    permissão na pasta de modelos recebem a orientação bilíngue de
    :func:`orientacao_permissao` no texto do evento e em ``falhas``.
    Devolve o dicionário do evento ``fim``.
    """

    selecionados = normalizar_modelos(selecionados)

    if not selecionados:
        raise ValueError("Selecione pelo menos um modelo para baixar")

    sessao = sessao or _criar_sessao()
    total = len(selecionados)
    instalados = []
    falhas = {}

    def emitir(evento):
        if ao_progresso is not None:
            ao_progresso(evento)

    for indice, identificador in enumerate(selecionados, start=1):
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
        except ErroDownload as erro:
            falhas[identificador] = mensagem_de_download(str(erro), idioma)
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
        except Exception as erro:  # rede inesperada: segue para o próximo
            falhas[identificador] = mensagem_de_download(
                f"{type(erro).__name__}: {erro}",
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
        "modelo_padrao": modelo_padrao(instalados),
    }

    emitir(resultado)

    return resultado


# ---------------------------------------------------------------------------
# Persistência no config_local.json
# ---------------------------------------------------------------------------

def precisa_configurar(caminho=None):
    """Indica se o assistente ainda precisa ser executado.

    Verdadeiro quando o ``config_local.json`` não existe ou não define
    um ``modelo_padrao`` utilizável.
    """

    dados = config.carregar_config_local(caminho)

    return not config.modelo_padrao_do_config(dados)


def modelos_ja_instalados(caminho=None):
    """Lista ``modelos_instalados`` do ``config_local.json``."""

    dados = config.carregar_config_local(caminho)

    return config.normalizar_lista_modelos(dados.get("modelos_instalados"))


def persistir_selecao(modelos_baixados, caminho=None):
    """Grava ``modelos_instalados`` e ``modelo_padrao`` no config local.

    A lista acumula o que já estava gravado (o ``--forcar`` pode baixar
    modelos adicionais) e o padrão segue a prioridade
    ``qwen3:14b`` > ``qwen3:4b`` > ``qwen2.5:3b``.
    """

    novos = normalizar_modelos(modelos_baixados)

    if not novos:
        raise ValueError("Nenhum modelo válido para gravar")

    destino = (
        Path(caminho) if caminho is not None else config.caminho_config_local()
    )

    dados = config.carregar_config_local(destino)

    acumulados = config.normalizar_lista_modelos(
        config.normalizar_lista_modelos(dados.get("modelos_instalados"))
        + novos
    )

    dados.update(
        {
            "versao_config": config.VERSAO_CONFIG_LOCAL,
            "modelos_instalados": acumulados,
            # O padrão segue os modelos marcados nesta execução; a lista
            # acumulada guarda tudo o que já foi baixado pelo assistente.
            "modelo_padrao": modelo_padrao(novos),
            "atualizado_em": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
    )

    config.salvar_config_local(dados, destino)

    return dados


# ---------------------------------------------------------------------------
# Textos da interface (PT-BR / EN)
# ---------------------------------------------------------------------------

TEXTOS = {
    "pt": {
        "titulo": (
            f"{config.APP_NAME} v{config.APP_VERSION} — Configuração de Modelos Locais (Ollama)"
        ),
        "subtitulo": (
            "Escolha um, dois ou os três modelos abaixo. Eles serão "
            "baixados pelo Ollama; a primeira execução pode levar alguns "
            "minutos, dependendo da conexão."
        ),
        "idioma": "Idioma / Language:",
        "verificando": "Verificando o serviço Ollama...",
        "aguardando_ollama": (
            "Aguardando o Ollama responder em {host} "
            "(até 5 segundos)..."
        ),
        "servico_ativo": "Ollama ativo em {host}",
        "servico_iniciado": "Ollama iniciado em {host}",
        "servico_inativo": (
            "Ollama não encontrado. Instale o Ollama para baixar os "
            "modelos e abra este assistente novamente."
        ),
        "servico_inativo_detalhe": (
            "Ollama indisponível em {host}: {mensagem}"
        ),
        "verificar": "Verificar novamente",
        "baixar_ollama": "Baixar o Ollama",
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
        "ram_total": "Memória RAM detectada: {ram}",
        "ram_indisponivel": "Memória RAM não detectada",
        "recomendado": "Sugestão para esta máquina: {modelos}",
        "tag_recomendado": "[Recomendado]",
        "coluna_modelo": "Modelo",
        "coluna_perfil": "Perfil de Hardware",
        "coluna_ram": "RAM Ocupada",
        "coluna_comportamento": "Comportamento Esperado",
        "memoria_selecionada": "Espaço/RAM estimado dos modelos marcados: {ram}",
        "memoria_nenhuma": (
            "Marque pelo menos um modelo para continuar."
        ),
        "selecione_ao_menos": (
            "Selecione pelo menos um dos três modelos para continuar."
        ),
        "baixar_continuar": "Baixar selecionados e continuar",
        "cancelar": "Cancelar",
        "preparando": "Preparando o download...",
        "baixando": "Baixando {indice}/{total}: {modelo}...",
        "concluido_modelo": "Concluído: {modelo}",
        "falha_modelo": "Falha em {modelo}: {mensagem}",
        "sucesso_titulo": "Modelos prontos",
        "sucesso_mensagem": (
            "Modelos instalados: {modelos}\n\n"
            "Modelo padrão: {padrao}\n\n"
            "Configuração gravada em:\n{config}"
        ),
        "falhas_titulo": "Alguns modelos não foram baixados",
        "falhas_mensagem": (
            "Instalados: {instalados}\n\n"
            "Falhas:\n{falhas}\n\n"
            "A configuração dos modelos instalados foi gravada e você "
            "pode tentar novamente com --forcar."
        ),
        "falha_geral_titulo": "Falha no download",
        "falha_geral_mensagem": (
            "Não foi possível concluir o download:\n{mensagem}"
        ),
        "falha_config_titulo": "Configuração não gravada",
        "falha_config_mensagem": (
            "Os modelos foram baixados, mas o config_local.json não pôde "
            "ser gravado:\n{mensagem}\n\n"
            "Os modelos continuam disponíveis no Ollama; selecione-os "
            "pela barra lateral do assistente."
        ),
        "sem_ollama_titulo": "Ollama indisponível",
        "sem_ollama_mensagem": (
            "O Ollama não está acessível em {host}.\n\n"
            "Instale pelo site oficial, abra o Ollama e clique em "
            "“Verificar novamente”."
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
        "ollama_inicio_falhou": (
            "Não foi possível iniciar o Ollama automaticamente. "
            "Abra o aplicativo do Ollama e tente de novo."
        ),
        "fechar_baixando": (
            "O download está em andamento. Deseja realmente fechar?"
        ),
        "fechar_titulo": "Fechar assistente",
        "instalados": "Já instalados: {modelos}",
        "nenhum_instalado": "Nenhum modelo do catálogo está instalado ainda.",
        "ja_configurado": (
            "A configuração dos modelos já existe. Use --forcar para "
            "reabrir o seletor."
        ),
        "sem_interface": (
            "Não foi possível abrir a interface gráfica (Tkinter). "
            "Abrindo o seletor de modelos no terminal."
        ),
        "cli_titulo": (
            "=== Seletor de modelos no terminal ==="
        ),
        "cli_prompt": (
            "Escolha com 1, 2 ou 3 (vários com vírgula, ex.: 1,3); "
            "ENTER vazio usa a sugestão para esta máquina: "
        ),
        "cli_invalido": (
            "Opção inválida. Digite 1, 2 ou 3 (ex.: 1,3) ou ENTER "
            "para a sugestão."
        ),
        "cli_cancelado": (
            "Operação cancelada; nenhum modelo foi configurado."
        ),
        "cli_ollama_inativo": (
            "O Ollama não está acessível em {host}. Instale/abra o "
            "Ollama e execute novamente:\n"
            "    python\\python.exe setup_llm.py --forcar"
        ),
        "cli_sucesso": (
            "Configuração gravada em:\n{config}\n"
            "Modelo padrão: {padrao}"
        ),
        "cli_falha_config": (
            "Os modelos foram baixados, mas o config_local.json não "
            "pôde ser gravado: {mensagem}"
        ),
        "cli_sem_instalados": (
            "Nenhum modelo foi baixado. Verifique o Ollama e tente "
            "novamente."
        ),
    },
    "en": {
        "titulo": (
            f"{config.APP_NAME} v{config.APP_VERSION} — Local Model Configuration (Ollama)"
        ),
        "subtitulo": (
            "Pick one, two, or all three models below. They will be "
            "downloaded by Ollama; the first run may take a few minutes "
            "depending on your connection."
        ),
        "idioma": "Language / Idioma:",
        "verificando": "Checking the Ollama service...",
        "aguardando_ollama": (
            "Waiting for Ollama to answer at {host} "
            "(up to 5 seconds)..."
        ),
        "servico_ativo": "Ollama is up at {host}",
        "servico_iniciado": "Ollama started at {host}",
        "servico_inativo": (
            "Ollama was not found. Install Ollama to download the "
            "models, then open this assistant again."
        ),
        "servico_inativo_detalhe": (
            "Ollama is unavailable at {host}: {mensagem}"
        ),
        "verificar": "Check again",
        "baixar_ollama": "Download Ollama",
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
        "ram_total": "Detected RAM: {ram}",
        "ram_indisponivel": "RAM could not be detected",
        "recomendado": "Suggested for this machine: {modelos}",
        "tag_recomendado": "[Recommended]",
        "coluna_modelo": "Model",
        "coluna_perfil": "Hardware Profile",
        "coluna_ram": "RAM Usage",
        "coluna_comportamento": "Expected Behavior",
        "memoria_selecionada": "Estimated RAM for the selected models: {ram}",
        "memoria_nenhuma": "Select at least one model to continue.",
        "selecione_ao_menos": (
            "Select at least one of the three models to continue."
        ),
        "baixar_continuar": "Download selected and continue",
        "cancelar": "Cancel",
        "preparando": "Preparing the download...",
        "baixando": "Downloading {indice}/{total}: {modelo}...",
        "concluido_modelo": "Completed: {modelo}",
        "falha_modelo": "Failed on {modelo}: {mensagem}",
        "sucesso_titulo": "Models ready",
        "sucesso_mensagem": (
            "Installed models: {modelos}\n\n"
            "Default model: {padrao}\n\n"
            "Configuration written to:\n{config}"
        ),
        "falhas_titulo": "Some models were not downloaded",
        "falhas_mensagem": (
            "Installed: {instalados}\n\n"
            "Failures:\n{falhas}\n\n"
            "The installed models were saved and you can try again "
            "with --forcar."
        ),
        "falha_geral_titulo": "Download failed",
        "falha_geral_mensagem": (
            "The download could not be completed:\n{mensagem}"
        ),
        "falha_config_titulo": "Configuration not saved",
        "falha_config_mensagem": (
            "The models were downloaded, but config_local.json could not "
            "be written:\n{mensagem}\n\n"
            "The models remain available in Ollama; choose them in the "
            "assistant sidebar."
        ),
        "sem_ollama_titulo": "Ollama unavailable",
        "sem_ollama_mensagem": (
            "Ollama is not reachable at {host}.\n\n"
            "Install it from the official site, start Ollama and click "
            "“Check again”."
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
        "ollama_inicio_falhou": (
            "Ollama could not be started automatically. Open the Ollama "
            "app and try again."
        ),
        "fechar_baixando": (
            "A download is in progress. Do you really want to close?"
        ),
        "fechar_titulo": "Close assistant",
        "instalados": "Already installed: {modelos}",
        "nenhum_instalado": "No catalog model is installed yet.",
        "ja_configurado": (
            "The model configuration already exists. Use --forcar to "
            "reopen the selector."
        ),
        "sem_interface": (
            "The graphical interface (Tkinter) could not be opened. "
            "Falling back to the terminal model selector."
        ),
        "cli_titulo": (
            "=== Terminal model selector ==="
        ),
        "cli_prompt": (
            "Choose 1, 2 or 3 (several with commas, e.g. 1,3); "
            "an empty ENTER uses this machine's suggestion: "
        ),
        "cli_invalido": (
            "Invalid option. Type 1, 2 or 3 (e.g. 1,3) or press ENTER "
            "for the suggestion."
        ),
        "cli_cancelado": (
            "Operation cancelled; no model was configured."
        ),
        "cli_ollama_inativo": (
            "Ollama is not reachable at {host}. Install/start Ollama "
            "and run again:\n"
            "    python\\python.exe setup_llm.py --forcar"
        ),
        "cli_sucesso": (
            "Configuration written to:\n{config}\n"
            "Default model: {padrao}"
        ),
        "cli_falha_config": (
            "The models were downloaded, but config_local.json could "
            "not be written: {mensagem}"
        ),
        "cli_sem_instalados": (
            "No model was downloaded. Check Ollama and try again."
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
# Interface gráfica
# ---------------------------------------------------------------------------

# Geometria da tabela de modelos. Cada coluna tem uma largura mínima
# (``minsize``) e um peso de expansão; a última coluna absorve o espaço
# restante da janela. O mesmo ``padx`` é usado no cabeçalho e em todas as
# células para que o título "RAM Ocupada" fique exatamente sobre os
# valores ``~2,6 GB``, ``~9,0 GB`` e ``~1,9 GB``.
COLUNAS_TABELA_MODELOS = (
    ("coluna_modelo", 135, 0),
    ("coluna_perfil", 250, 0),
    ("coluna_ram", 105, 0),
    ("coluna_comportamento", 390, 1),
)

PADX_COLUNA_TABELA = 8
WRAPLENGTH_PERFIL = 235
WRAPLENGTH_COMPORTAMENTO = 375

# Altura inicial da janela e do Canvas da lista: os três cartões cabem
# sem a faixa branca que sobrava com a janela de 760 px. A altura final
# é calculada a partir do conteúdo já montado (ver
# ``_ajustar_altura_inicial``), o que também acomoda fontes maiores.
LARGURA_INICIAL_JANELA = 1040
ALTURA_INICIAL_JANELA = 560
ALTURA_MINIMA_JANELA = 500
ALTURA_CANVAS_MODELOS = 260


def configurar_grade_tabela(contêiner):
    """Aplica ``minsize`` e ``weight`` às quatro colunas da tabela."""

    for indice, (_chave, largura, peso) in enumerate(
        COLUNAS_TABELA_MODELOS
    ):
        contêiner.columnconfigure(
            indice,
            minsize=largura,
            weight=peso,
        )


def texto_tag_recomendado(idioma=IDIOMA_PADRAO):
    """Rótulo discreto do modelo sugerido para o hardware detectado."""

    return texto("tag_recomendado", idioma)


def montar_tabela_modelos(
    contêiner,
    idioma=IDIOMA_PADRAO,
    variaveis=None,
    ao_marcar=None,
    recomendados=(),
):
    """Monta cabeçalho e linhas na mesma grade ``grid`` de 4 colunas.

    Cabeçalho e linhas compartilham as larguras mínimas, o ``padx`` e o
    alinhamento à esquerda, garantindo que cada valor fique abaixo do
    seu título. Devolve a lista de tuplas ``(check, perfil, ram,
    comportamento)`` na ordem de ``CATALOGO_MODELOS``.
    """

    from tkinter import ttk

    variaveis = variaveis or {}
    recomendados = set(recomendados or ())

    for filho in contêiner.winfo_children():
        filho.destroy()

    configurar_grade_tabela(contêiner)

    for coluna, (chave, *_resto) in enumerate(COLUNAS_TABELA_MODELOS):
        ttk.Label(
            contêiner,
            text=texto(chave, idioma),
            style="Cabecalho.TLabel",
        ).grid(
            row=0,
            column=coluna,
            sticky="w",
            padx=PADX_COLUNA_TABELA,
            pady=(4, 8),
        )

    linhas = []

    for indice, modelo in enumerate(CATALOGO_MODELOS):
        # Uma linha de conteúdo e outra de separador; o separador dá o
        # aspecto de cartão sem quebrar o alinhamento das colunas.
        linha = 1 + indice * 2

        caixa = ttk.Frame(contêiner)
        caixa.grid(
            row=linha,
            column=0,
            sticky="nw",
            padx=PADX_COLUNA_TABELA,
            pady=(10, 6),
        )

        check = ttk.Checkbutton(
            caixa,
            variable=variaveis.get(modelo.identificador),
            command=ao_marcar,
        )
        check.grid(row=0, column=0, sticky="nw")

        ttk.Label(
            caixa,
            text=modelo.identificador,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))

        if modelo.identificador in recomendados:
            ttk.Label(
                caixa,
                text=texto_tag_recomendado(idioma),
                foreground="#1b5e20",
                font=("Segoe UI", 8),
                anchor="w",
            ).grid(row=1, column=1, sticky="w", padx=(6, 0))

        perfil = ttk.Label(
            contêiner,
            text=modelo.perfil(idioma),
            wraplength=WRAPLENGTH_PERFIL,
            justify="left",
            anchor="w",
        )
        perfil.grid(
            row=linha,
            column=1,
            sticky="nw",
            padx=PADX_COLUNA_TABELA,
            pady=(10, 6),
        )

        ram = ttk.Label(
            contêiner,
            text=modelo.ram_formatada(idioma),
            anchor="w",
        )
        ram.grid(
            row=linha,
            column=2,
            sticky="nw",
            padx=PADX_COLUNA_TABELA,
            pady=(10, 6),
        )

        comportamento = ttk.Label(
            contêiner,
            text=modelo.comportamento(idioma),
            wraplength=WRAPLENGTH_COMPORTAMENTO,
            justify="left",
            anchor="w",
        )
        comportamento.grid(
            row=linha,
            column=3,
            sticky="nw",
            padx=PADX_COLUNA_TABELA,
            pady=(10, 6),
        )

        ttk.Separator(contêiner, orient="horizontal").grid(
            row=linha + 1,
            column=0,
            columnspan=len(COLUNAS_TABELA_MODELOS),
            sticky="ew",
            pady=(0, 2),
        )

        linhas.append((check, perfil, ram, comportamento))

    return linhas


def abrir_interface(forcar=False, oculta=False):
    """Abre a janela do assistente e só retorna quando ela fecha.

    O ``tkinter`` é importado aqui dentro para que este módulo possa ser
    importado (e testado) em ambientes sem interface gráfica.
    ``oculta`` mantém a janela fora da tela, útil no teste de fumaça
    offline que valida a montagem da tabela.
    """

    import tkinter as tk
    from tkinter import messagebox, ttk

    host = HOST_OLLAMA_PADRAO

    ram_total = memoria_total_gb()

    estado = {
        "idioma": IDIOMA_PADRAO,
        "baixando": False,
        "verificando": False,
        "servico_ativo": None,
        "fila": queue.Queue(),
        "vars": {},
        "instalados": [
            identificador
            for identificador in modelos_ja_instalados()
            if obter_modelo(identificador) is not None
        ],
    }

    iniciais = estado["instalados"] or modelos_iniciais(ram_total)

    raiz = tk.Tk()
    raiz.title(texto("titulo"))
    raiz.geometry(f"{LARGURA_INICIAL_JANELA}x{ALTURA_INICIAL_JANELA}")
    raiz.minsize(1000, ALTURA_MINIMA_JANELA)

    if oculta:
        raiz.withdraw()

    try:
        raiz.columnconfigure(0, weight=1)
        # A lista mantém a altura fixa de ``ALTURA_CANVAS_MODELOS``; o
        # peso fica em 0 para a janela não esticar o Canvas e recriar a
        # faixa branca abaixo das três linhas.
        raiz.rowconfigure(2, weight=0)
    except tk.TclError:  # pragma: no cover - janela exótica
        pass

    estilo = ttk.Style(master=raiz)

    try:
        estilo.theme_use("clam")
    except tk.TclError:  # pragma: no cover - tema indisponível
        pass

    estilo.configure("Titulo.TLabel", font=("Segoe UI", 16, "bold"))
    estilo.configure("Subtitulo.TLabel", foreground="#4a4a4a")
    estilo.configure("Cabecalho.TLabel", font=("Segoe UI", 10, "bold"))
    estilo.configure("Destaque.TLabel", font=("Segoe UI", 10, "bold"))
    estilo.configure("Cartao.TFrame", relief="solid", borderwidth=1)
    estilo.configure("Barra.TFrame")
    estilo.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    # -- Cabeçalho ------------------------------------------------------
    cabecalho = ttk.Frame(raiz, padding=(18, 14, 18, 6))
    cabecalho.grid(row=0, column=0, sticky="ew")
    cabecalho.columnconfigure(0, weight=1)

    rotulo_titulo = ttk.Label(
        cabecalho,
        text=texto("titulo"),
        style="Titulo.TLabel",
    )
    rotulo_titulo.grid(row=0, column=0, sticky="w")

    rotulo_subtitulo = ttk.Label(
        cabecalho,
        text=texto("subtitulo"),
        style="Subtitulo.TLabel",
        wraplength=720,
        justify="left",
    )
    rotulo_subtitulo.grid(row=1, column=0, sticky="w", pady=(4, 0))

    idioma_var = tk.StringVar(master=raiz, value=estado["idioma"])

    seletor_idioma = ttk.Frame(cabecalho)
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

    # -- Status do Ollama e da RAM -------------------------------------
    faixa_status = ttk.Frame(raiz, padding=(18, 0, 18, 8))
    faixa_status.grid(row=1, column=0, sticky="ew")
    faixa_status.columnconfigure(0, weight=1)

    status_var = tk.StringVar(master=raiz, value=texto("verificando"))
    rotulo_status = ttk.Label(
        faixa_status,
        textvariable=status_var,
        style="Destaque.TLabel",
    )
    rotulo_status.grid(row=0, column=0, sticky="w")

    ram_texto = (
        texto("ram_total", ram=formatar_ram(ram_total, estado["idioma"]))
        if ram_total is not None
        else texto("ram_indisponivel")
    )

    ram_var = tk.StringVar(master=raiz, value=ram_texto)
    rotulo_ram = ttk.Label(faixa_status, textvariable=ram_var)
    rotulo_ram.grid(row=1, column=0, sticky="w", pady=(2, 0))

    sugestao = ", ".join(modelos_iniciais(ram_total))
    rotulo_sugestao = ttk.Label(
        faixa_status,
        text=texto("recomendado", modelos=sugestao),
        style="Subtitulo.TLabel",
    )
    rotulo_sugestao.grid(row=2, column=0, sticky="w", pady=(2, 0))

    botoes_status = ttk.Frame(faixa_status)
    botoes_status.grid(row=0, column=1, rowspan=3, sticky="e")

    botao_baixar_ollama = ttk.Button(
        botoes_status,
        text=texto("baixar_ollama"),
        command=lambda: _abrir_site_ollama(),
    )
    botao_verificar = ttk.Button(
        botoes_status,
        text=texto("verificar"),
        command=lambda: _iniciar_verificacao(),
    )
    botao_verificar.grid(row=0, column=0, padx=(0, 6))

    # -- Tabela rolável de modelos --------------------------------------
    area_modelos = ttk.Frame(raiz, padding=(18, 0, 18, 0))
    area_modelos.grid(row=2, column=0, sticky="nsew")
    area_modelos.columnconfigure(0, weight=1)
    area_modelos.rowconfigure(0, weight=1)

    canvas = tk.Canvas(
        area_modelos,
        highlightthickness=0,
        borderwidth=0,
        height=ALTURA_CANVAS_MODELOS,
    )
    canvas.grid(row=0, column=0, sticky="nsew")

    barra_rolagem = ttk.Scrollbar(
        area_modelos,
        orient="vertical",
        command=canvas.yview,
    )
    barra_rolagem.grid(row=0, column=1, sticky="ns")

    canvas.configure(yscrollcommand=barra_rolagem.set)

    interior = ttk.Frame(canvas)
    janela = canvas.create_window((0, 0), window=interior, anchor="nw")

    def _ajustar_rolagem(_evento=None):
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except tk.TclError:  # pragma: no cover
            pass

    def _ajustar_largura(evento):
        try:
            canvas.itemconfigure(janela, width=evento.width)
        except tk.TclError:  # pragma: no cover
            pass

    interior.bind("<Configure>", _ajustar_rolagem)
    canvas.bind("<Configure>", _ajustar_largura)

    def _rolar(evento):
        try:
            canvas.yview_scroll(int(-1 * (evento.delta / 120)), "units")
        except tk.TclError:  # pragma: no cover
            pass

    canvas.bind_all("<MouseWheel>", _rolar)

    for modelo in CATALOGO_MODELOS:
        estado["vars"][modelo.identificador] = tk.BooleanVar(
            master=raiz,
            value=modelo.identificador in iniciais,
        )

    linhas_modelos = []

    def _selecionados():
        return [
            modelo.identificador
            for modelo in CATALOGO_MODELOS
            if estado["vars"][modelo.identificador].get()
        ]

    def _atualizar_resumo(*_):
        selecionados = _selecionados()

        if selecionados:
            resumo_var.set(
                texto(
                    "memoria_selecionada",
                    ram=formatar_ram(
                        estimar_ram_gb(selecionados),
                        estado["idioma"],
                    ),
                )
            )

            # Enquanto a verificação/início do Ollama está em andamento
            # (ou um download já roda), confirmar abriria o falso alerta
            # de "Ollama indisponível": o botão fica bloqueado até o
            # serviço responder de fato.
            if estado["verificando"] or estado["baixando"]:
                botao_confirmar.state(["disabled"])
            else:
                botao_confirmar.state(["!disabled"])
        else:
            resumo_var.set(texto("memoria_nenhuma"))
            botao_confirmar.state(["disabled"])

    def _montar_modelos():
        """Recria a tabela na grade única, preservando as variáveis."""

        recomendados = modelos_iniciais(ram_total)

        linhas_modelos.clear()
        linhas_modelos.extend(
            montar_tabela_modelos(
                interior,
                idioma=estado["idioma"],
                variaveis=estado["vars"],
                ao_marcar=_atualizar_resumo,
                recomendados=recomendados,
            )
        )

        _ajustar_rolagem()

    # -- Rodapé: resumo, progresso e ações ------------------------------
    rodape = ttk.Frame(raiz, padding=(18, 10, 18, 14))
    rodape.grid(row=3, column=0, sticky="ew")
    rodape.columnconfigure(0, weight=1)

    resumo_var = tk.StringVar(master=raiz, value="")

    ttk.Label(
        rodape,
        textvariable=resumo_var,
        style="Destaque.TLabel",
    ).grid(row=0, column=0, sticky="w")

    progresso_var = tk.StringVar(master=raiz, value="")

    rotulo_progresso = ttk.Label(
        rodape,
        textvariable=progresso_var,
        wraplength=720,
        justify="left",
    )
    rotulo_progresso.grid(row=1, column=0, sticky="w", pady=(6, 4))

    barra_progresso = ttk.Progressbar(
        rodape,
        orient="horizontal",
        mode="determinate",
        maximum=100.0,
        length=680,
    )
    barra_progresso.grid(row=2, column=0, sticky="ew")

    acoes = ttk.Frame(rodape)
    acoes.grid(row=0, column=1, rowspan=3, sticky="e", padx=(12, 0))

    botao_confirmar = ttk.Button(
        acoes,
        text=texto("baixar_continuar"),
        style="Accent.TButton",
    )
    botao_confirmar.grid(row=0, column=0, padx=(0, 8))

    botao_cancelar = ttk.Button(
        acoes,
        text=texto("cancelar"),
        command=lambda: _fechar(confirmar=False),
    )
    botao_cancelar.grid(row=0, column=1)

    # -- Operações ------------------------------------------------------

    def _abrir_site_ollama():
        import webbrowser

        try:
            webbrowser.open(URL_DOWNLOAD_OLLAMA)
        except Exception:  # pragma: no cover - sem navegador
            pass

    def _aplicar_idioma():
        idioma = estado["idioma"]

        raiz.title(texto("titulo", idioma))

        rotulo_titulo.configure(text=texto("titulo", idioma))
        rotulo_subtitulo.configure(text=texto("subtitulo", idioma))
        rotulo_idioma.configure(text=texto("idioma", idioma))

        if ram_total is not None:
            ram_var.set(
                texto(
                    "ram_total",
                    idioma,
                    ram=formatar_ram(ram_total, idioma),
                )
            )
        else:
            ram_var.set(texto("ram_indisponivel", idioma))

        rotulo_sugestao.configure(
            text=texto(
                "recomendado",
                idioma,
                modelos=", ".join(modelos_iniciais(ram_total)),
            )
        )

        botao_baixar_ollama.configure(text=texto("baixar_ollama", idioma))
        botao_verificar.configure(text=texto("verificar", idioma))
        botao_confirmar.configure(text=texto("baixar_continuar", idioma))
        botao_cancelar.configure(text=texto("cancelar", idioma))
        rotulo_progresso.configure(wraplength=720)

        if estado["servico_ativo"] is False:
            status_var.set(texto("servico_inativo", idioma))

        if not estado["baixando"]:
            if estado["instalados"]:
                progresso_var.set(
                    texto(
                        "instalados",
                        idioma,
                        modelos=", ".join(estado["instalados"]),
                    )
                )
            else:
                progresso_var.set(texto("nenhum_instalado", idioma))

        _montar_modelos()
        _atualizar_resumo()

    def _iniciar_verificacao():
        estado["verificando"] = True
        status_var.set(texto("verificando", estado["idioma"]))
        botao_verificar.state(["disabled"])
        # A verificação pode baixar e instalar o Ollama; não deixe o
        # usuário iniciar o download dos modelos no meio da instalação.
        botao_confirmar.state(["disabled"])
        threading.Thread(target=_verificar_servico, daemon=True).start()

    def _verificar_servico():
        try:
            resultado = garantir_servico_ollama(
                host,
                callback_progresso=estado["fila"].put,
            )
        except Exception as erro:  # pragma: no cover - falha inesperada
            resultado = {
                "ativo": False,
                "iniciado": False,
                "instalado": False,
                "mensagem": str(erro),
            }

        estado["fila"].put({"tipo": "servico", **resultado})

    def _iniciar_download():
        selecionados = _selecionados()

        if not selecionados:
            messagebox.showwarning(
                texto("titulo", estado["idioma"]),
                texto("selecione_ao_menos", estado["idioma"]),
                parent=raiz,
            )
            return

        if estado["servico_ativo"] is not True:
            # Nada de aviso modal imediato: o ``ollama serve`` iniciado
            # pelo aplicativo pode ainda estar abrindo a porta 11434.
            # Aguardamos a janela de tolerância em segundo plano e só
            # alertamos se o serviço continuar fora do ar.
            _aguardar_servico_para_download(selecionados)
            return

        estado["baixando"] = True

        botao_confirmar.state(["disabled"])
        botao_verificar.state(["disabled"])
        botao_cancelar.state(["disabled"])
        barra_progresso["value"] = 0.0
        progresso_var.set(texto("preparando", estado["idioma"]))

        threading.Thread(
            target=_trabalhar_download,
            args=(selecionados,),
            daemon=True,
        ).start()

    def _aguardar_servico_para_download(selecionados):
        """Espera o Ollama responder antes de qualquer aviso modal.

        A consulta a ``/api/tags`` roda em thread para a janela não
        congelar; o resultado volta pela fila como ``servico_aguardando``
        e só então a interface decide entre seguir com o download ou
        mostrar o alerta de indisponibilidade.
        """

        status_var.set(
            texto("aguardando_ollama", estado["idioma"], host=host)
        )
        botao_confirmar.state(["disabled"])
        botao_verificar.state(["disabled"])

        def _trabalhar():
            try:
                ativo = aguardar_ollama(host)
            except (OSError, RuntimeError, ValueError):
                ativo = False

            estado["fila"].put(
                {
                    "tipo": "servico_aguardando",
                    "ativo": ativo,
                    "selecionados": list(selecionados),
                }
            )

        threading.Thread(target=_trabalhar, daemon=True).start()

    def _trabalhar_download(selecionados):
        try:
            resultado = baixar_modelos(
                selecionados,
                host=host,
                ao_progresso=estado["fila"].put,
                idioma=estado["idioma"],
            )
        except Exception as erro:
            estado["fila"].put(
                {
                    "tipo": "falha_geral",
                    "mensagem": f"{type(erro).__name__}: {erro}",
                }
            )
            return

        dados = None
        erro_config = None

        if resultado["instalados"]:
            try:
                dados = persistir_selecao(resultado["instalados"])
            except Exception as erro:  # gravação local pode falhar
                erro_config = f"{type(erro).__name__}: {erro}"

        estado["fila"].put(
            {
                "tipo": "finalizado",
                "resultado": resultado,
                "config": dados,
                "erro_config": erro_config,
            }
        )

    def _tratar_evento(evento):
        tipo = evento.get("tipo")

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
                total_bytes = evento.get("total_bytes")
                percentual = evento.get("percentual")

                if percentual is not None and total_bytes:
                    status_var.set(
                        texto(
                            "ollama_baixando",
                            idioma,
                            percentual=f"{float(percentual):.0f}",
                            baixado=baixado,
                            total=formatar_mb(total_bytes, idioma),
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
                        host=evento.get("host") or host,
                    )
                )
            elif etapa == "servico_indisponivel":
                status_var.set(texto("ollama_inicio_falhou", idioma))
            elif etapa == "erro":
                status_var.set(
                    texto(
                        "ollama_instalacao_falhou",
                        idioma,
                        mensagem=evento.get("mensagem") or "",
                    )
                )
            return

        if tipo == "servico":
            ativo = bool(evento.get("ativo"))
            estado["servico_ativo"] = ativo
            estado["verificando"] = False
            botao_verificar.state(["!disabled"])

            if ativo:
                botao_baixar_ollama.grid_remove()
                mensagem = (
                    "servico_iniciado"
                    if evento.get("iniciado")
                    else "servico_ativo"
                )
                status_var.set(
                    texto(mensagem, estado["idioma"], host=host)
                )
            else:
                botao_baixar_ollama.grid(
                    row=0,
                    column=1,
                    padx=(6, 0),
                )
                detalhe = str(evento.get("mensagem") or "").strip()

                if detalhe:
                    status_var.set(
                        texto(
                            "servico_inativo_detalhe",
                            estado["idioma"],
                            host=host,
                            mensagem=detalhe,
                        )
                    )
                else:
                    status_var.set(
                        texto("servico_inativo", estado["idioma"])
                    )

            # Restaura o botão de download conforme a seleção atual.
            if not estado["baixando"]:
                _atualizar_resumo()
            return

        if tipo == "servico_aguardando":
            # Resultado da janela de tolerância: só depois dela o aviso
            # modal de "Ollama indisponível" pode aparecer.
            ativo = bool(evento.get("ativo"))
            estado["servico_ativo"] = ativo
            botao_verificar.state(["!disabled"])

            if ativo:
                botao_baixar_ollama.grid_remove()
                status_var.set(
                    texto("servico_ativo", estado["idioma"], host=host)
                )

                if not estado["baixando"]:
                    _atualizar_resumo()

                _iniciar_download()
                return

            messagebox.showwarning(
                texto("sem_ollama_titulo", estado["idioma"]),
                texto(
                    "sem_ollama_mensagem",
                    estado["idioma"],
                    host=host,
                ),
                parent=raiz,
            )

            if not estado["baixando"]:
                _atualizar_resumo()

            _iniciar_verificacao()
            return

        if tipo == "inicio":
            estado["atual"] = {
                "indice": evento.get("indice", 1),
                "total": evento.get("total", 1),
                "modelo": evento.get("modelo", ""),
            }
            barra_progresso["value"] = 0.0
            progresso_var.set(
                texto(
                    "baixando",
                    estado["idioma"],
                    indice=estado["atual"]["indice"],
                    total=estado["atual"]["total"],
                    modelo=estado["atual"]["modelo"],
                )
            )
            return

        if tipo == "progresso":
            percentual = evento.get("percentual")

            if percentual is not None:
                barra_progresso["value"] = float(percentual)

            atual = estado.get("atual") or {
                "indice": 1,
                "total": 1,
                "modelo": evento.get("modelo", ""),
            }

            # Mantém "Baixando 1/2: qwen3:4b..." visível e acrescenta o
            # andamento (percentual quando há total; senão o status).
            mensagem = texto(
                "baixando",
                estado["idioma"],
                indice=atual.get("indice", 1),
                total=atual.get("total", 1),
                modelo=atual.get("modelo", ""),
            )

            if percentual is not None:
                mensagem += f" {float(percentual):.0f}%"
            else:
                status_modelo = str(evento.get("status") or "").strip()

                if status_modelo:
                    mensagem += f" ({status_modelo})"

            progresso_var.set(mensagem)
            return

        if tipo == "concluido":
            barra_progresso["value"] = 100.0
            progresso_var.set(
                texto(
                    "concluido_modelo",
                    estado["idioma"],
                    modelo=evento.get("modelo", ""),
                )
            )
            return

        if tipo == "erro":
            mensagem = str(evento.get("mensagem", ""))

            if erro_de_permissao(mensagem):
                # O detalhe completo (icacls/OLLAMA_MODELS) fica para o
                # diálogo final; o rodapé mostra só o diagnóstico curto
                # para não esticar a janela com um texto de várias linhas.
                progresso_var.set(
                    texto("permissao_modelos_titulo", estado["idioma"])
                )
            else:
                progresso_var.set(
                    texto(
                        "falha_modelo",
                        estado["idioma"],
                        modelo=evento.get("modelo", ""),
                        mensagem=mensagem,
                    )
                )
            return

        if tipo == "falha_geral":
            estado["baixando"] = False
            botao_confirmar.state(["!disabled"])
            botao_cancelar.state(["!disabled"])
            messagebox.showerror(
                texto("falha_geral_titulo", estado["idioma"]),
                texto(
                    "falha_geral_mensagem",
                    estado["idioma"],
                    mensagem=evento.get("mensagem", ""),
                ),
                parent=raiz,
            )
            return

        if tipo == "finalizado":
            estado["baixando"] = False
            botao_cancelar.state(["!disabled"])

            resultado = evento.get("resultado") or {}
            instalados = resultado.get("instalados") or []
            falhas = resultado.get("falhas") or {}
            dados = evento.get("config") or {}
            caminho_config = config.caminho_config_local()

            if not instalados:
                botao_confirmar.state(["!disabled"])
                detalhes = "\n".join(
                    f"- {modelo}: {motivo}"
                    for modelo, motivo in falhas.items()
                )
                messagebox.showerror(
                    texto("falha_geral_titulo", estado["idioma"]),
                    texto(
                        "falha_geral_mensagem",
                        estado["idioma"],
                        mensagem=detalhes or "sem detalhes",
                    ),
                    parent=raiz,
                )
                return

            if falhas:
                detalhes = "\n".join(
                    f"- {modelo}: {motivo}"
                    for modelo, motivo in falhas.items()
                )
                messagebox.showwarning(
                    texto("falhas_titulo", estado["idioma"]),
                    texto(
                        "falhas_mensagem",
                        estado["idioma"],
                        instalados=", ".join(instalados),
                        falhas=detalhes,
                    ),
                    parent=raiz,
                )

            if evento.get("erro_config"):
                messagebox.showwarning(
                    texto("falha_config_titulo", estado["idioma"]),
                    texto(
                        "falha_config_mensagem",
                        estado["idioma"],
                        mensagem=evento["erro_config"],
                    ),
                    parent=raiz,
                )
            elif not falhas:
                messagebox.showinfo(
                    texto("sucesso_titulo", estado["idioma"]),
                    texto(
                        "sucesso_mensagem",
                        estado["idioma"],
                        modelos=", ".join(instalados),
                        padrao=dados.get(
                            "modelo_padrao",
                            modelo_padrao(instalados),
                        ),
                        config=str(caminho_config),
                    ),
                    parent=raiz,
                )

            raiz.destroy()
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
            and estado["baixando"]
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

    botao_confirmar.configure(command=_iniciar_download)

    _montar_modelos()
    _aplicar_idioma()
    _atualizar_resumo()

    if estado["instalados"]:
        progresso_var.set(
            texto(
                "instalados",
                estado["idioma"],
                modelos=", ".join(estado["instalados"]),
            )
        )
    else:
        progresso_var.set(texto("nenhum_instalado", estado["idioma"]))

    # Oculta o botão do site até a verificação confirmar que falta o Ollama.
    botao_baixar_ollama.grid_remove()

    def _ajustar_altura_inicial():
        """Encolhe a janela até o conteúdo, sem faixa branca no rodapé."""

        try:
            raiz.update_idletasks()
            altura = max(ALTURA_MINIMA_JANELA, raiz.winfo_reqheight())
            limite = raiz.winfo_screenheight() - 120

            if limite > ALTURA_MINIMA_JANELA:
                altura = min(altura, limite)

            raiz.geometry(f"{LARGURA_INICIAL_JANELA}x{altura}")
        except tk.TclError:  # pragma: no cover - janela exótica
            pass

    raiz.after(150, _processar_fila)
    raiz.after(200, _iniciar_verificacao)

    _ajustar_altura_inicial()

    try:
        raiz.mainloop()
    finally:
        try:
            canvas.unbind_all("<MouseWheel>")
        except tk.TclError:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Seletor no terminal (fallback quando o Tkinter não está disponível)
#
# O Python Embeddable do Windows não traz ``tkinter``/Tcl-Tk por padrão.
# O ``build_portatil.ps1`` copia esse suporte, mas em ambientes mínimos
# (ou numa montagem antiga) a janela não abre. Nesse caso o assistente
# continua configurando o modelo por ``input()`` no próprio terminal.
# ---------------------------------------------------------------------------

# Quantas tentativas o usuário tem para digitar uma opção válida.
TENTATIVAS_ESCOLHA_CLI = 3


def tkinter_disponivel():
    """Indica se o ``tkinter`` pode ser importado neste interpretador."""

    try:
        import tkinter  # noqa: F401
    except (ImportError, OSError):
        return False

    return True


def interface_indisponivel(erro):
    """Diz se a falha da janela justifica cair para o seletor CLI.

    Cobre o ``ImportError`` (Embeddable sem tkinter/_tkinter/Tcl DLLs) e
    o ``tkinter.TclError`` (pacote importável, mas Tcl/Tk sem dados).
    Outros erros continuam sendo falha real e não abrem o CLI.
    """

    if isinstance(erro, ImportError):
        return True

    try:
        import tkinter
    except (ImportError, OSError):
        return True

    return isinstance(erro, tkinter.TclError)


def interpretar_escolha_cli(linha, recomendados=None):
    """Converte a linha digitada em IDs do catálogo.

    Aceita ``"1"``, ``"1,3"``, ``"1 3"`` e ``"1;3"``. Linha vazia devolve
    a sugestão por RAM. Devolve ``None`` quando a entrada é inválida,
    fora do intervalo ou não sobra nenhum modelo.
    """

    if recomendados is None:
        recomendados = modelos_iniciais()

    limpa = str(linha or "").strip().lower()

    if not limpa:
        return list(recomendados)

    escolhidos = []

    for parte in limpa.replace(",", " ").replace(";", " ").split():
        if not parte.isdigit():
            return None

        indice = int(parte)

        if not 1 <= indice <= len(CATALOGO_MODELOS):
            return None

        identificador = CATALOGO_MODELOS[indice - 1].identificador

        if identificador not in escolhidos:
            escolhidos.append(identificador)

    return escolhidos or None


def _tabela_modelos_cli(idioma=IDIOMA_PADRAO):
    """Tabela numerada dos três modelos para o seletor de terminal."""

    linhas = []

    for indice, modelo in enumerate(CATALOGO_MODELOS, start=1):
        linhas.append(
            f"  {indice}) {modelo.identificador:<12} "
            f"{modelo.ram_formatada(idioma):>10}  "
            f"{modelo.perfil(idioma)}"
        )

    return "\n".join(linhas)


def executar_seletor_cli(entrada=input, idioma=IDIOMA_PADRAO):
    """Configura o modelo pelo terminal, sem depender do Tkinter.

    Apresenta os três modelos numerados e pede a escolha por ``input()``
    (ENTER usa a sugestão por RAM), verifica/inicia o Ollama, baixa os
    modelos em sequência e grava o ``config_local.json``.

    Devolve ``0`` quando a configuração foi gravada e ``1`` em qualquer
    falha (Ollama inativo, download vazio, entrada cancelada etc.).
    """

    ram_total = memoria_total_gb()
    recomendados = modelos_iniciais(ram_total)

    _imprimir("")
    _imprimir(texto("cli_titulo", idioma))

    if ram_total is not None:
        _imprimir(
            texto("ram_total", idioma, ram=formatar_ram(ram_total, idioma))
        )
    else:
        _imprimir(texto("ram_indisponivel", idioma))

    _imprimir(texto("recomendado", idioma, modelos=", ".join(recomendados)))
    _imprimir("")
    _imprimir(_tabela_modelos_cli(idioma))
    _imprimir("")

    escolhidos = None

    for _ in range(TENTATIVAS_ESCOLHA_CLI):
        try:
            linha = entrada(texto("cli_prompt", idioma))
        except (EOFError, KeyboardInterrupt):
            _imprimir("")
            _imprimir(texto("cli_cancelado", idioma))
            return 1

        escolhidos = interpretar_escolha_cli(linha, recomendados)

        if escolhidos:
            break

        _imprimir(texto("cli_invalido", idioma))

    if not escolhidos:
        _imprimir(texto("cli_cancelado", idioma))
        return 1

    host = HOST_OLLAMA_PADRAO

    def _ao_progresso_ollama(evento):
        etapa = evento.get("etapa")

        if etapa == "ausente":
            _imprimir(texto("ollama_ausente", idioma))
        elif etapa == "baixando":
            baixado = formatar_mb(evento.get("baixado_bytes") or 0, idioma)
            total_bytes = evento.get("total_bytes")
            percentual = evento.get("percentual")

            if percentual is not None and total_bytes:
                _imprimir(
                    texto(
                        "ollama_baixando",
                        idioma,
                        percentual=f"{float(percentual):.0f}",
                        baixado=baixado,
                        total=formatar_mb(total_bytes, idioma),
                    )
                )
            else:
                _imprimir(
                    texto(
                        "ollama_baixando_sem_total",
                        idioma,
                        baixado=baixado,
                    )
                )
        elif etapa == "instalando":
            _imprimir(texto("ollama_instalando", idioma))
        elif etapa == "instalado":
            _imprimir(
                texto(
                    "ollama_instalado",
                    idioma,
                    caminho=evento.get("caminho") or "",
                )
            )
        elif etapa == "iniciando_servico":
            _imprimir(
                texto(
                    "ollama_iniciando",
                    idioma,
                    host=evento.get("host") or host,
                )
            )
        elif etapa == "erro":
            _imprimir(
                texto(
                    "ollama_instalacao_falhou",
                    idioma,
                    mensagem=evento.get("mensagem") or "",
                )
            )

    servico = garantir_servico_ollama(
        host,
        callback_progresso=_ao_progresso_ollama,
    )

    if not servico.get("ativo"):
        _imprimir(texto("cli_ollama_inativo", idioma, host=host))
        return 1

    def _ao_progresso(evento):
        tipo = evento.get("tipo")

        if tipo == "inicio":
            _imprimir(
                texto(
                    "baixando",
                    idioma,
                    indice=evento.get("indice", 1),
                    total=evento.get("total", 1),
                    modelo=evento.get("modelo", ""),
                )
            )
        elif tipo == "concluido":
            _imprimir(
                texto(
                    "concluido_modelo",
                    idioma,
                    modelo=evento.get("modelo", ""),
                )
            )
        elif tipo == "erro":
            _imprimir(
                texto(
                    "falha_modelo",
                    idioma,
                    modelo=evento.get("modelo", ""),
                    mensagem=evento.get("mensagem", ""),
                )
            )

    try:
        resultado = baixar_modelos(
            escolhidos,
            ao_progresso=_ao_progresso,
            idioma=idioma,
        )
    except Exception as erro:  # ErroDownload, rede, catálogo inválido
        _imprimir(
            texto(
                "falha_geral_mensagem",
                idioma,
                mensagem=f"{type(erro).__name__}: {erro}",
            )
        )
        return 1

    instalados = resultado.get("instalados") or []

    if not instalados:
        _imprimir(texto("cli_sem_instalados", idioma))
        return 1

    try:
        dados = persistir_selecao(instalados)
    except Exception as erro:  # gravação local pode falhar
        _imprimir(
            texto(
                "cli_falha_config",
                idioma,
                mensagem=f"{type(erro).__name__}: {erro}",
            )
        )
        return 1

    _imprimir(
        texto(
            "cli_sucesso",
            idioma,
            config=str(config.caminho_config_local()),
            padrao=dados.get("modelo_padrao", modelo_padrao(instalados)),
        )
    )

    return 0


# ---------------------------------------------------------------------------
# Entrada do script
# ---------------------------------------------------------------------------

def _imprimir(mensagem):
    """``print`` seguro em executável sem console (``sys.stdout`` nulo)."""

    fluxo = sys.stdout

    if fluxo is None:
        return

    try:
        print(mensagem, file=fluxo)
    except (OSError, ValueError):  # pragma: no cover
        pass


def principal(argv=None):
    """Ponto de entrada com suporte a ``--forcar``.

    Sem ``--forcar``, um ``config_local.json`` já configurado encerra o
    script sem abrir janela: é o que o ``iniciar.bat`` executa em toda
    abertura.
    """

    analisador = argparse.ArgumentParser(
        prog="setup_llm.py",
        description=(
            "Assistente de seleção e download dos modelos LLM locais "
            f"(Ollama) do {config.APP_NAME} v{config.APP_VERSION}."
        ),
    )
    analisador.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "reabre o seletor mesmo quando a configuração já existe, "
            "para baixar modelos adicionais"
        ),
    )

    argumentos = analisador.parse_args(argv)

    if not argumentos.forcar and not precisa_configurar():
        _imprimir(texto("ja_configurado"))
        return 0

    # Ambiente mínimo (Embeddable sem Tkinter/Tcl copiados): nem tenta
    # abrir a janela, segue direto para o seletor do terminal.
    if not tkinter_disponivel():
        _imprimir(texto("sem_interface"))
        return executar_seletor_cli()

    try:
        abrir_interface(forcar=argumentos.forcar)
    except Exception as erro:  # TclError, sem display, etc.
        _imprimir(texto("sem_interface"))
        _imprimir(f"Detalhe: {type(erro).__name__}: {erro}")

        if interface_indisponivel(erro):
            return executar_seletor_cli()

        return 1

    return 0


def main(argv=None):
    """Alias público usado pelo ``launcher_desktop.py``."""

    return principal(argv)


if __name__ == "__main__":
    raise SystemExit(main())
