"""Ponto de entrada do executável do NexusGeo IA.

Este é o alvo do PyInstaller (``packaging/assistente.spec``). Ele resolve
as diferenças entre a pasta portátil e a instalação em ``Program Files``:

1. aponta ``SSL_CERT_FILE``/``REQUESTS_CA_BUNDLE`` para o
   ``certifi/cacert.pem`` empacotado **antes** de importar o projeto
   (sem isso o ``import ollama`` -> ``httpx`` -> ``ssl`` quebra com
   ``FileNotFoundError`` no bundle congelado);
2. define ``ASSISTENTE_DATA_DIR=%LOCALAPPDATA%\\NexusGeoIA``
   **antes** de importar ``config`` (a pasta de instalação é somente
   leitura; histórico, banco, documentos e ``config_local.json`` precisam
   ir para o perfil do usuário);
3. executa o assistente de modelos (``setup_llm.py``) quando o
   ``config_local.json`` ainda não existe ou quando recebe
   ``--setup-modelo`` (atalho *Gerenciar Modelos LLM* do instalador);
4. antes de subir um servidor novo, verifica se já existe uma instância
   saudável do aplicativo respondendo na faixa de portas do launcher
   (8501..8510). Se existir, apenas abre a aba e encerra o launcher
   secundário — é isso que evita as instâncias duplicadas e os processos
   órfãos;
5. sobe o Streamlit em um **subprocesso** associado a um Windows Job
   Object com ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. Quando o launcher
   termina — inclusive ao fechar o terminal/``iniciar.bat`` ou por
   ``taskkill`` — o Job Object mata a árvore de processos filha. Além
   disso, ``SetConsoleCtrlHandler`` e ``atexit`` executam
   ``taskkill /F /T /PID`` imediatamente no encerramento normal;
6. aguarda o healthcheck HTTP local responder e só então executa
   ``webbrowser.open(f"http://localhost:{porta}")``.

Os recursos lidos por caminho (``app.py``, ``prompts/system_base.txt`` e
``.streamlit/config.toml``) são sempre resolvidos em
``sys._MEIPASS`` quando ``sys.frozen`` está ativo: no pacote ``--onedir``
do PyInstaller 6 isso é ``dist\\NexusGeoIA\\_internal``, e em
``Program Files`` a pasta de instalação é somente leitura (os arquivos
não ficam soltos nela).

Uso pelo executável:

    NexusGeoIA.exe
    NexusGeoIA.exe --setup-modelo
    NexusGeoIA.exe --autoteste
    NexusGeoIA.exe --verificar-imports
    NexusGeoIA.exe --nova-instancia
"""

from __future__ import annotations

import atexit
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.client import HTTPException
from pathlib import Path

NOME_APLICATIVO = "NexusGeoIA"

# Porta preferida; se estiver ocupada, a próxima livre é usada.
PORTA_PREFERIDA = 8501

# Interface de rede usada nos testes de porta livre. O Streamlit é
# iniciado em ``localhost``; verificar o mesmo loopback evita escolher
# uma porta que o ``bind`` do servidor recusaria em seguida.
ENDERECO_LOOPBACK = "127.0.0.1"

# Endereço que o navegador deve abrir quando a porta preferida responde.
URL_APLICATIVO = "http://localhost:8501"

# Endpoint de saúde exposto pelo servidor do Streamlit.
CAMINHO_SAUDE = "/_stcore/health"

# Espera máxima pela subida do servidor antes de desistir de abrir a aba
# (120 tentativas x 0,5 s = 60 s).
TENTATIVAS_SAUDE = 120
INTERVALO_SAUDE = 0.5

# Quantas portas subsequentes são testadas (8501..8510) antes de pedir
# uma porta efêmera ao sistema operacional.
TENTATIVAS_PORTA = 10

# Argumentos de linha de comando reconhecidos pelo launcher.
ARG_SETUP = "--setup-modelo"
ARG_FORCAR = "--forcar"

# Modo interno: o subprocesso que roda o CLI do Streamlit. Não é
# documentado para o usuário; o launcher se reexecuta com ele.
ARG_SERVIDOR = "--servidor-streamlit"
ARG_PORTA = "--porta"

# Força uma instância nova mesmo quando já existe uma respondendo.
ARG_NOVA_INSTANCIA = "--nova-instancia"

# Valida os imports do bundle sem abrir GUI, servidor ou navegador.
ARG_VERIFICAR_IMPORTS = "--verificar-imports"
ENV_RELATORIO_IMPORTS = "ASSISTENTE_IMPORTS_REPORT"

# Nomes das variáveis de ambiente que o OpenSSL, o ``requests`` e o
# ``httpx`` consultam para localizar as autoridades certificadoras.
VARIAVEIS_CERTIFICADO = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")

# Arquivo de registro da instância em execução (porta + PID). Fica na
# pasta de dados gravável, que é a mesma para o pacote portátil e para a
# instalação em ``%LOCALAPPDATA%``.
NOME_ARQUIVO_INSTANCIA = "instancia_ativa.json"


def configurar_certificados():
    """Aponta as variáveis TLS para o ``cacert.pem`` do ``certifi``.

    BUG CORRIGIDO: no executável congelado o ``ssl.create_default_context``
    do Windows procura o arquivo de CAs em ``SSL_CERT_FILE``. Se a
    variável não existir (ou apontar para um caminho que não veio no
    bundle), o ``httpx`` levanta ``FileNotFoundError`` durante o
    ``import ollama`` e o aplicativo nem chega a abrir.

    A função só define as variáveis quando estão vazias **ou** apontando
    para um arquivo inexistente: um caminho válido definido pelo usuário
    é preservado. Devolve o caminho usado ou ``None`` quando o
    ``certifi`` não está disponível.
    """

    try:
        import certifi

        caminho = str(certifi.where())
    except Exception:  # noqa: BLE001 - ambiente sem certifi
        return None

    if not caminho or not os.path.isfile(caminho):
        return None

    for variavel in VARIAVEIS_CERTIFICADO:
        atual = os.environ.get(variavel, "").strip()

        if not atual or not os.path.isfile(atual):
            os.environ[variavel] = caminho

    return caminho


# Executado antes de qualquer import do projeto (``services.llm_service``
# instancia ``ollama.Client`` no topo do módulo e cria o contexto SSL já
# no import).
CAMINHO_CERTIFICADOS = configurar_certificados()


def diretorio_localappdata():
    """Pasta gravável do usuário, com o nome do aplicativo."""

    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")

    if base:
        return Path(base) / NOME_APLICATIVO

    return Path.home() / "AppData" / "Local" / NOME_APLICATIVO


def adicionar_ollama_ao_path():
    """Inclui a pasta do Ollama no ``PATH`` da sessão atual.

    O ``setup_llm.py`` instala o Ollama silenciosamente em
    ``%LOCALAPPDATA%\\Programs\\Ollama``; repetir a inclusão aqui evita
    que o assistente e o Streamlit (em processos subsequentes) não
    encontrem o ``ollama.exe`` até o próximo logon.
    """

    if os.name != "nt":
        return None

    candidatas = []

    base = os.getenv("LOCALAPPDATA")

    if base:
        candidatas.append(Path(base) / "Programs" / "Ollama")

    for variavel in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        base = os.getenv(variavel)

        if base:
            candidatas.append(Path(base) / "Ollama")

    pasta = next(
        (caminho for caminho in candidatas if caminho.is_dir()),
        candidatas[0] if candidatas else None,
    )

    if pasta is None:
        return None

    atual = os.environ.get("PATH", "")
    alvo = str(pasta).rstrip("\\/").casefold()
    partes = [
        str(Path(parte)).rstrip("\\/").casefold()
        for parte in atual.split(os.pathsep)
        if parte.strip()
    ]

    if alvo not in partes:
        os.environ["PATH"] = str(pasta) + (
            os.pathsep + atual if atual else ""
        )

    return str(pasta)


def _diretorio_gravavel(caminho):
    """Testa escrita real em ``caminho`` sem depender de permissões nominais.

    A checagem cria a pasta e grava um arquivo temporário curto. Isso cobre
    o cenário do pacote portátil extraído em ``C:\\Program Files`` ou em
    uma pasta corporativa somente leitura: nesses casos o diretório pode
    existir, mas o usuário comum não consegue gravar nele.
    """

    try:
        caminho = Path(caminho).expanduser()
        caminho.mkdir(parents=True, exist_ok=True)
        teste = caminho / ".escrita_nexusgeo.tmp"
        teste.write_text("", encoding="utf-8")
        teste.unlink()
        return True
    except OSError:
        return False


def configurar_diretorio_dados():
    """Define ``ASSISTENTE_DATA_DIR`` e devolve o diretório escolhido.

    A pasta portátil é preservada quando realmente gravável. Se o usuário
    extraiu o .zip em uma pasta protegida (por exemplo ``C:\\Program Files``),
    o launcher cai para ``%LOCALAPPDATA%\\NexusGeoIA`` antes de importar
    ``config``, evitando ``PermissionError`` no boot. Um valor já definido
    pelo usuário continua sendo a primeira opção; só é substituído quando
    não permite escrita.
    """

    desejado = os.getenv("ASSISTENTE_DATA_DIR", "").strip()
    candidatos = []

    if desejado:
        candidatos.append(Path(desejado).expanduser())

    candidatos.append(diretorio_localappdata())

    for candidato in candidatos:
        if _diretorio_gravavel(candidato):
            os.environ["ASSISTENTE_DATA_DIR"] = str(candidato)
            return candidato

    # Nenhum candidato gravável: mantém o último caminho para que o
    # ``config.py`` produza a mensagem de erro original, agora com um alvo
    # previsível e documentado.
    os.environ["ASSISTENTE_DATA_DIR"] = str(diretorio_localappdata())
    return Path(os.environ["ASSISTENTE_DATA_DIR"])


# Executado antes de qualquer import do projeto: ``config.py`` lê a
# variável no momento em que é importado.
DIRETORIO_DADOS = configurar_diretorio_dados()

# O Ollama pode ter acabado de ser instalado pelo assistente; o PATH da
# sessão precisa incluir a pasta antes de chamar o setup e o Streamlit.
PATH_OLLAMA = adicionar_ollama_ao_path()

# Importado depois de ``ASSISTENTE_DATA_DIR`` estar definido para que o
# ``config.py`` resolva o mesmo diretório gravável usado pelo launcher.
import config  # noqa: E402


def diretorio_recursos():
    """Pasta dos arquivos empacotados (``_MEIPASS``) ou do projeto."""

    base = getattr(sys, "_MEIPASS", None)

    if base:
        return Path(base).resolve()

    return Path(__file__).resolve().parent


def caminho_app():
    """Caminho absoluto do ``app.py`` que o Streamlit vai executar."""

    return diretorio_recursos() / "app.py"


# Arquivos empacotados que o executável lê por caminho em tempo de
# execução. A verificação é feita no bundle extraído (``_MEIPASS``), e
# não na pasta do ``.exe``: em ``Program Files`` a pasta de instalação é
# somente leitura e não contém esses arquivos.
RECURSOS_OBRIGATORIOS = (
    ("app.py", "aplicativo Streamlit"),
    ("prompts/system_base.txt", "system prompt padrão"),
    (".streamlit/config.toml", "configuração do Streamlit"),
)

# Argumentos que disparam o autoteste (smoke test do executável).
ARG_AUTOTESTE = "--autoteste"
ARG_AUTOTESTE_ALTERNATIVO = "--smoke-test"

# Variável de ambiente que recebe o caminho do relatório do autoteste.
ENV_RELATORIO_AUTOTESTE = "ASSISTENTE_SMOKE_REPORT"


def recursos_ausentes():
    """Lista os recursos obrigatórios que não estão no bundle.

    Devolve pares ``(caminho, descrição)``; lista vazia significa bundle
    completo. Usada pelo autoteste e por ``preparar_ambiente``.
    """

    base = diretorio_recursos()
    ausentes = []

    for relativo, descricao in RECURSOS_OBRIGATORIOS:
        if not (base / relativo).is_file():
            ausentes.append((str(base / relativo), descricao))

    return ausentes


def verificar_recursos():
    """Garante que o bundle traz os recursos lidos por caminho.

    Levanta :class:`FileNotFoundError` com a lista completa quando falta
    algum arquivo, em vez de deixar o Streamlit ou o system prompt
    falharem depois de o servidor já ter subido.
    """

    ausentes = recursos_ausentes()

    if ausentes:
        detalhes = "\n".join(
            f"  - {caminho} ({descricao})" for caminho, descricao in ausentes
        )

        raise FileNotFoundError(
            "Recursos do aplicativo ausentes no bundle:\n" + detalhes
        )

    return diretorio_recursos()



def _porta_disponivel(porta, endereco=ENDERECO_LOOPBACK):
    """Indica se ``porta`` pode ser reservada em ``endereco``.

    A checagem usa ``bind`` e fecha o socket em seguida. Existe uma
    janela entre o teste e a abertura real do Streamlit; se outra
    aplicação tomar a porta nesse intervalo, o Streamlit falha de forma
    visível em vez de abrir na porta errada.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        try:
            soquete.bind((str(endereco), int(porta)))
        except OSError:
            return False

    return True


def _encontrar_porta_livre(
    porta_inicial: int = PORTA_PREFERIDA,
    tentativas: int = TENTATIVAS_PORTA,
) -> int:
    """Primeira porta TCP livre a partir de ``porta_inicial``.

    Testa ``tentativas`` portas consecutivas em 127.0.0.1 — com os
    padrões, 8501..8510. Quando nenhuma delas está livre, pede uma porta
    efêmera ao sistema operacional, que sempre nasce desocupada.
    """

    inicial = int(porta_inicial)
    limite = max(1, int(tentativas))

    for porta in range(inicial, inicial + limite):
        if _porta_disponivel(porta):
            return porta

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        soquete.bind((ENDERECO_LOOPBACK, 0))

        return int(soquete.getsockname()[1])


def porta_livre(preferida=PORTA_PREFERIDA, tentativas=TENTATIVAS_PORTA):
    """Compatibilidade: nome histórico de ``_encontrar_porta_livre``."""

    return _encontrar_porta_livre(preferida, tentativas)


def url_aplicativo(porta=PORTA_PREFERIDA):
    """URL local que o navegador deve abrir para a porta informada."""

    porta = int(porta)

    if porta == PORTA_PREFERIDA:
        return URL_APLICATIVO

    return f"http://localhost:{porta}"


def aplicacao_respondendo(porta=PORTA_PREFERIDA, timeout=1.0):
    """Consulta o healthcheck HTTP do Streamlit.

    Devolve ``True`` apenas quando ``/_stcore/health`` responde 2xx.
    Qualquer erro de rede, timeout ou status inesperado conta como
    "ainda não está pronta", sem interromper a espera.
    """

    url = f"{url_aplicativo(porta)}{CAMINHO_SAUDE}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            codigo = getattr(resposta, "status", None)

            if codigo is None:
                codigo = resposta.getcode()

            return 200 <= int(codigo) < 300
    except (urllib.error.URLError, OSError, HTTPException, ValueError):
        return False


def abrir_navegador_quando_pronto(
    porta=PORTA_PREFERIDA,
    tentativas=TENTATIVAS_SAUDE,
    intervalo=INTERVALO_SAUDE,
    abrir=None,
):
    """Aguarda o healthcheck e abre o navegador uma única vez.

    A função é síncrona para poder ser testada sem threads; em produção
    ``agendar_abertura_navegador`` a executa em segundo plano.
    """

    abrir = abrir or webbrowser.open

    for _ in range(max(1, int(tentativas))):
        if aplicacao_respondendo(porta):
            try:
                abrir(url_aplicativo(porta))
            except Exception:  # pragma: no cover - navegador indisponível
                return False

            return True

        time.sleep(float(intervalo))

    return False


def agendar_abertura_navegador(porta=PORTA_PREFERIDA):
    """Dispara a abertura do navegador em uma thread daemon."""

    thread = threading.Thread(
        target=abrir_navegador_quando_pronto,
        kwargs={"porta": porta},
        name="nexusgeo-navegador",
        daemon=True,
    )
    thread.start()

    return thread


# ---------------------------------------------------------------------------
# Instância já em execução (evita servidores e processos duplicados)
# ---------------------------------------------------------------------------


def caminho_registro_instancia():
    """Arquivo JSON que registra a porta da instância em execução."""

    return Path(DIRETORIO_DADOS) / NOME_ARQUIVO_INSTANCIA


def _ler_registro_instancia():
    """Porta registrada pela instância atual, ou ``None``."""

    try:
        dados = json.loads(
            caminho_registro_instancia().read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None

    try:
        porta = int(dados.get("porta"))
    except (AttributeError, TypeError, ValueError):
        return None

    return porta if 0 < porta < 65536 else None


def _gravar_registro_instancia(porta):
    """Registra a porta da instância; tolerante a pasta somente leitura."""

    try:
        Path(DIRETORIO_DADOS).mkdir(parents=True, exist_ok=True)
        caminho_registro_instancia().write_text(
            json.dumps(
                {"porta": int(porta), "pid": os.getpid()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return True
    except OSError:
        return False


def _remover_registro_instancia():
    """Remove o registro da instância, ignorando ausência de arquivo."""

    try:
        caminho_registro_instancia().unlink()
    except OSError:
        pass


def pagina_do_aplicativo(porta=PORTA_PREFERIDA, timeout=1.0):
    """Confere que a porta serve uma página do Streamlit.

    O healthcheck sozinho não identifica a aplicação: qualquer servidor
    Streamlit responde em ``/_stcore/health``. A página raiz traz os
    assets estáticos do Streamlit, o que reduz o risco de o launcher
    adotar outro programa que esteja ocupando a faixa de portas.
    """

    try:
        with urllib.request.urlopen(
            url_aplicativo(porta) + "/",
            timeout=timeout,
        ) as resposta:
            conteudo = resposta.read(65536)

        return b"streamlit" in conteudo.lower()
    except (urllib.error.URLError, OSError, HTTPException, ValueError):
        return False


def instancia_ativa(portas=None, verificar_pagina=True):
    """Porta de uma instância saudável do NexusGeo IA, se já houver uma.

    A ordem de checagem é: porta registrada pela instância atual (mais
    precisa) e, depois, a faixa 8501..8510 usada pelo launcher e pelo
    ``iniciar.bat``. Uma instância só é considerada ativa quando o
    healthcheck HTTP responde 2xx e a página raiz é servida pelo
    Streamlit.
    """

    registrada = _ler_registro_instancia()

    if portas is None:
        faixa = range(PORTA_PREFERIDA, PORTA_PREFERIDA + TENTATIVAS_PORTA)
    else:
        faixa = portas

    candidatas = []

    if registrada:
        # A instância registrada pode estar subindo (o registro é gravado
        # antes do servidor aceitar conexões). Espera alguns segundos em
        # vez de abrir um segundo servidor na porta seguinte.
        for _ in range(12):
            if aplicacao_respondendo(registrada):
                break

            if _porta_disponivel(registrada):
                # A porta está livre: a instância antiga morreu.
                break

            time.sleep(0.5)

        candidatas.append(registrada)

    for porta in faixa:
        if porta not in candidatas:
            candidatas.append(porta)

    for porta in candidatas:
        if not aplicacao_respondendo(porta):
            continue

        if verificar_pagina and not pagina_do_aplicativo(porta):
            continue

        return int(porta)

    return None


def abrir_instancia_existente(porta):
    """Abre a aba de uma instância que já está respondendo."""

    try:
        return bool(webbrowser.open(url_aplicativo(porta)))
    except Exception:  # noqa: BLE001 - navegador indisponível
        return False


# ---------------------------------------------------------------------------
# Encerramento garantido da árvore de processos (Windows Job Object)
# ---------------------------------------------------------------------------
#
# O Streamlit roda em um subprocesso do launcher. No Windows, um Job
# Object com ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` garante que a árvore
# inteira morra quando o launcher terminar, inclusive em encerramentos
# que não executam ``atexit`` (X do console do ``iniciar.bat``,
# ``taskkill``, logoff). Sem isso o servidor continuava vivo em segundo
# plano e a pasta do pacote não podia ser apagada/atualizada.

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _IoCounters(ctypes.Structure):
    """``IO_COUNTERS`` do Win32 (parte de ``JOBOBJECT_EXTENDED_LIMIT``)."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _BasicLimitInformation(ctypes.Structure):
    """``JOBOBJECT_BASIC_LIMIT_INFORMATION`` do Win32."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    """``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` do Win32."""

    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JobObjectWindows:
    """Job do Windows que mata os filhos quando o launcher encerra.

    A criação é tolerante a falha (permissão, sistema não Windows): nesse
    caso o encerramento continua coberto por ``SetConsoleCtrlHandler``,
    ``atexit`` e ``taskkill /F /T /PID``. O motivo fica em ``motivo``
    para o diagnóstico.
    """

    def __init__(self):
        self._handle = None
        self.motivo = ""

    @property
    def ativo(self):
        """Indica se o job foi criado com sucesso."""

        return self._handle is not None

    def criar(self):
        """Cria o job com ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``."""

        if os.name != "nt":
            self.motivo = "Job Object disponível apenas no Windows"
            return False

        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            kernel32.CreateJobObjectW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
            ]

            handle = kernel32.CreateJobObjectW(None, None)

            if not handle:
                self.motivo = "CreateJobObjectW falhou"
                return False

            informacao = _ExtendedLimitInformation()
            informacao.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )

            kernel32.SetInformationJobObject.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]

            definido = kernel32.SetInformationJobObject(
                ctypes.c_void_p(handle),
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.cast(
                    ctypes.byref(informacao),
                    ctypes.c_void_p,
                ),
                ctypes.sizeof(informacao),
            )

            if not definido:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
                self.motivo = "SetInformationJobObject falhou"
                return False

            self._handle = handle
            self.motivo = ""

            return True
        except Exception as erro:  # noqa: BLE001 - Win32 indisponível
            self.motivo = f"{type(erro).__name__}: {erro}"

            return False

    def associar(self, processo):
        """Coloca o subprocesso (e futuros descendentes) dentro do job."""

        if not self.ativo or processo is None or os.name != "nt":
            return False

        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]

            handle_processo = kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_TERMINATE,
                False,
                int(processo.pid),
            )

            if not handle_processo:
                return False

            try:
                kernel32.AssignProcessToJobObject.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ]

                return bool(
                    kernel32.AssignProcessToJobObject(
                        ctypes.c_void_p(self._handle),
                        ctypes.c_void_p(handle_processo),
                    )
                )
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle_processo))
        except Exception:  # noqa: BLE001 - Win32 indisponível
            return False

    def fechar(self):
        """Fecha o handle do job.

        Com ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``, fechar o último
        handle encerra todos os processos associados.
        """

        if not self.ativo:
            return

        try:
            ctypes.windll.kernel32.CloseHandle(
                ctypes.c_void_p(self._handle)
            )
        except Exception:  # noqa: BLE001, S110 - Win32 indisponível
            pass

        self._handle = None


# Processo do servidor e job ativos no launcher (usados pelo ``atexit``).
_SERVIDOR = {"processo": None, "job": None}

# Guarda o callback do ``SetConsoleCtrlHandler``: se ele for coletado
# pelo garbage collector, o Windows derruba o processo ao receber o
# evento de controle.
_HANDLER_CONSOLE = None
_ENCERRAMENTO_REGISTRADO = False


def encerrar_arvore_processos(pid=None, processo=None):
    """Encerra o subprocesso e todos os filhos dele.

    No Windows usa ``taskkill /F /T /PID`` (mata a árvore, não só o
    processo principal); em falha, e nos demais sistemas, cai para
    ``proc.terminate()``/``proc.kill()``. Devolve ``True`` quando algum
    encerramento foi disparado.
    """

    encerrou = False

    if pid and os.name == "nt":
        try:
            resultado = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(int(pid))],
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            encerrou = resultado.returncode == 0 or encerrou
        except (OSError, subprocess.SubprocessError):
            pass

    if processo is not None:
        try:
            if processo.poll() is None:
                processo.terminate()
                encerrou = True
        except (OSError, ValueError):
            pass

        if not encerrou:
            try:
                processo.kill()
                encerrou = True
            except (OSError, ValueError):
                pass

    return encerrou


def _limpar_servidor():
    """Encerra servidor/job e remove o registro da instância.

    É acionada pelo ``atexit`` e pelo ``SetConsoleCtrlHandler``; por
    isso precisa ser idempotente e nunca levantar exceção.
    """

    processo = _SERVIDOR.get("processo")
    job = _SERVIDOR.get("job")
    pid = getattr(processo, "pid", None)

    try:
        encerrar_arvore_processos(pid, processo)
    except Exception:  # noqa: BLE001, S110 - limpeza best-effort
        pass

    if job is not None:
        try:
            job.fechar()
        except Exception:  # noqa: BLE001, S110 - limpeza best-effort
            pass

    _SERVIDOR["processo"] = None
    _SERVIDOR["job"] = None

    _remover_registro_instancia()


def _handler_console(evento):
    """Callback do ``SetConsoleCtrlHandler`` (Ctrl+C, X do console...).

    Devolve ``False`` depois de limpar: o tratamento padrão do Windows
    continua valendo e o launcher termina em seguida. O Job Object
    garante o encerramento mesmo que este callback não seja chamado.
    """

    _limpar_servidor()

    return False


def anexar_console_pai():
    """Anexa o executável GUI ao console que o iniciou (``iniciar.bat``).

    O ``NexusGeoIA.exe`` é compilado com ``console=False``: sem esta
    chamada ele não recebe ``CTRL_CLOSE_EVENT`` quando o usuário fecha o
    X do terminal do ``iniciar.bat``, e continuaria rodando em segundo
    plano. Anexar ao console do processo pai permite que o
    ``SetConsoleCtrlHandler`` encerre a árvore imediatamente.

    Devolve ``True`` quando já havia console ou quando a anexação deu
    certo. Em duplo clique (sem console pai) devolve ``False`` sem erro.
    """

    if os.name != "nt":
        return False

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleWindow.restype = ctypes.c_void_p

        if kernel32.GetConsoleWindow():
            return True

        return bool(kernel32.AttachConsole(-1))  # ATTACH_PARENT_PROCESS
    except Exception:  # noqa: BLE001 - console indisponível
        return False


def registrar_limpeza_encerramento():
    """Registra ``atexit`` e ``SetConsoleCtrlHandler`` uma única vez."""

    global _HANDLER_CONSOLE, _ENCERRAMENTO_REGISTRADO

    if _ENCERRAMENTO_REGISTRADO:
        return

    atexit.register(_limpar_servidor)
    _ENCERRAMENTO_REGISTRADO = True

    if os.name != "nt":
        return

    anexar_console_pai()

    try:
        prototipo = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        _HANDLER_CONSOLE = prototipo(_handler_console)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(
            _HANDLER_CONSOLE,
            True,
        )
    except Exception:  # noqa: BLE001 - sem console/Win32 indisponível
        _HANDLER_CONSOLE = None


def _imprimir(mensagem):
    """``print`` tolerante a executável sem console."""

    fluxo = sys.stdout

    if fluxo is None:
        return

    try:
        print(mensagem, file=fluxo)
    except (OSError, ValueError):  # pragma: no cover
        pass


def _mostrar_erro(titulo, mensagem):
    """Mostra o erro em janela quando possível; senão imprime."""

    _imprimir(f"{titulo}: {mensagem}")

    try:
        import tkinter as tk
        from tkinter import messagebox

        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(titulo, mensagem, parent=raiz)
        raiz.destroy()
    except Exception:  # pragma: no cover - sem interface disponível
        pass


def preparar_ambiente():
    """Garante diretórios graváveis, ``sys.path`` e diretório corrente."""

    import config

    config.garantir_diretorios()

    # Reforça o PATH a cada preparação: o setup pode ter instalado o
    # Ollama nesta mesma sessão, depois da primeira chamada.
    adicionar_ollama_ao_path()

    recursos = diretorio_recursos()

    # Falha cedo e com a lista completa quando o bundle está incompleto.
    verificar_recursos()

    if str(recursos) not in sys.path:
        sys.path.insert(0, str(recursos))

    # O Streamlit procura ``.streamlit/config.toml`` no diretório
    # corrente; o bundle do executável inclui essa pasta.
    try:
        os.chdir(recursos)
    except OSError:  # pragma: no cover - pasta somente leitura exótica
        pass

    return recursos


def executar_setup(forcar=False):
    """Executa o assistente de modelos no próprio processo.

    Rodar como função (em vez de subprocesso) mantém o ``tkinter``
    empacotado e o diretório de dados já resolvido.
    """

    import setup_llm

    argumentos = [ARG_FORCAR] if forcar else []

    return setup_llm.main(argumentos)


def configuracao_pendente():
    """Indica se o ``config_local.json`` ainda não foi criado."""

    import setup_llm

    return setup_llm.precisa_configurar()


def argumentos_streamlit(porta, argumentos_extra=None):
    """Linha de comando do CLI do Streamlit para ``porta``.

    Fica isolada em uma função para que o subprocesso, o modo de
    desenvolvimento e os testes usem exatamente a mesma lista.
    """

    app = caminho_app()

    argumentos = [
        "streamlit",
        "run",
        str(app),
        f"--server.port={int(porta)}",
        "--server.address",
        "localhost",
        # O launcher abre a aba depois do healthcheck; deixar o
        # Streamlit também abrir geraria duas abas no navegador.
        "--server.headless=true",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]

    if argumentos_extra:
        argumentos.extend(str(item) for item in argumentos_extra)

    return argumentos


def comando_servidor(porta):
    """Comando que reexecuta este launcher no modo servidor.

    No pacote congelado o ``sys.executable`` é o próprio
    ``NexusGeoIA.exe``; no código-fonte é o interpretador atual rodando
    este arquivo. O argumento interno ``--servidor-streamlit`` evita que
    o subprocesso repita o assistente de modelos e a detecção de
    instância.
    """

    argumentos = [ARG_SERVIDOR, ARG_PORTA, str(int(porta))]

    if getattr(sys, "frozen", False):
        return [str(sys.executable), *argumentos]

    return [str(sys.executable), str(Path(__file__).resolve()), *argumentos]


def executar_servidor_streamlit(porta, argumentos_extra=None):
    """Roda o CLI do Streamlit no processo atual (subprocesso do launcher).

    Registra a porta na pasta de dados enquanto o servidor está de pé,
    para que uma segunda abertura do atalho encontre a instância em vez
    de criar outra.
    """

    app = caminho_app()

    if not app.is_file():
        raise FileNotFoundError(f"app.py não encontrado em {app}")

    preparar_ambiente()

    # O registro é gravado ANTES de importar o CLI do Streamlit: o import
    # leva alguns segundos e, sem isso, uma segunda abertura do atalho
    # nesse intervalo não veria a instância e subiria outro servidor.
    _gravar_registro_instancia(porta)

    try:
        from streamlit.web import cli as cli_streamlit

        # O CLI do Streamlit lê ``sys.argv``; os argumentos do launcher
        # não podem vazar para ele.
        sys.argv = argumentos_streamlit(porta, argumentos_extra)

        try:
            cli_streamlit.main()
        except SystemExit as saida:
            codigo = saida.code

            return int(codigo) if isinstance(codigo, int) else 0

        return 0
    finally:
        _remover_registro_instancia()


def iniciar_streamlit(porta, argumentos_extra=None):
    """Sobe o Streamlit em um subprocesso e espera o encerramento.

    Devolve o código de saída do servidor. O subprocesso é associado a
    um Job Object do Windows (``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``) e
    o encerramento também é registrado em ``atexit`` e
    ``SetConsoleCtrlHandler``: fechar o launcher/terminal mata a árvore
    de processos, sem deixar ``NexusGeoIA.exe`` órfão em segundo plano.

    Levanta ``FileNotFoundError`` quando o ``app.py`` não está no bundle.
    """

    app = caminho_app()

    if not app.is_file():
        raise FileNotFoundError(f"app.py não encontrado em {app}")

    preparar_ambiente()
    registrar_limpeza_encerramento()

    job = JobObjectWindows()

    if not job.criar():
        _imprimir(
            "Aviso: Job Object indisponível "
            f"({job.motivo}); o encerramento usará taskkill/atexit."
        )

    processo = subprocess.Popen(comando_servidor(porta))

    _SERVIDOR["processo"] = processo
    _SERVIDOR["job"] = job

    if job.ativo and not job.associar(processo):
        _imprimir(
            "Aviso: não foi possível associar o servidor ao Job Object; "
            "o encerramento usará taskkill/atexit."
        )

    # O navegador só é aberto quando a porta responde de fato.
    agendar_abertura_navegador(porta)

    try:
        return int(processo.wait())
    except KeyboardInterrupt:  # pragma: no cover - Ctrl+C no console
        return 0
    finally:
        _limpar_servidor()


# Módulos que a cadeia de boot do aplicativo importa. O launcher precisa
# deles resolvidos de dentro do bundle, sem depender do ``.venv``.
MODULOS_CRITICOS = (
    "streamlit",
    "tkinter",
    "docx",
    "openpyxl",
    "pymupdf",
    "certifi",
    "httpx",
    "ollama",
    "pydantic",
    "pypdf",
    "services.llm_service",
    "core.smart_router",
    "core.assistant",
    "core.prompt_manager",
    "services.document_parser",
    "services.report_generator",
    "services.table_extractor",
    "services.external_api_service",
    "database.connection",
    "utils.i18n",
)


def verificar_modulos_criticos(modulos=None):
    """Importa cada módulo e devolve a lista dos que falharam.

    Lista vazia significa que todos os imports do boot resolveram dentro
    do ambiente atual (no executável, dentro de ``_internal``).
    """

    import importlib

    falhas = []

    for modulo in tuple(modulos or MODULOS_CRITICOS):
        try:
            importlib.import_module(modulo)
        except Exception as erro:  # noqa: BLE001 - qualquer erro conta como ausente
            falhas.append(f"{modulo} ({type(erro).__name__}: {erro})")

    return falhas


def verificar_certificados():
    """Valida o ``certifi/cacert.pem`` e o contexto SSL do ``httpx``.

    Reproduz o caminho que quebrou na validação real: o contexto TLS do
    ``httpx`` (usado pelo ``ollama``) precisa abrir o arquivo apontado
    por ``SSL_CERT_FILE``. Devolve um dicionário com os caminhos
    observados ou levanta ``FileNotFoundError``.
    """

    import certifi

    caminho = str(certifi.where())

    if not caminho or not os.path.isfile(caminho):
        raise FileNotFoundError(
            f"certifi/cacert.pem ausente no bundle: {caminho}"
        )

    for variavel in VARIAVEIS_CERTIFICADO:
        valor = os.environ.get(variavel, "").strip()

        if not valor or not os.path.isfile(valor):
            raise FileNotFoundError(
                f"{variavel} inválido: {valor!r} (esperado {caminho})"
            )

    import ssl

    import httpx

    contexto = httpx.create_ssl_context()

    if not isinstance(contexto, ssl.SSLContext):
        raise TypeError(
            "httpx.create_ssl_context() não devolveu um ssl.SSLContext"
        )

    return {
        "certifi": caminho,
        "ssl_cert_file": os.environ.get("SSL_CERT_FILE", ""),
        "requests_ca_bundle": os.environ.get("REQUESTS_CA_BUNDLE", ""),
    }

def executar_verificacao_imports(relatorio=None):
    """Valida imports do bundle (``--verificar-imports``), sem GUI.

    Executa a cadeia que quebrou no pacote congelado — ``certifi``,
    ``services.llm_service`` (que instancia ``ollama.Client`` no import)
    e o próprio ``app`` — e grava um JSON quando ``relatorio`` é
    informado. Devolve o dicionário do relatório.
    """

    verificacoes = []
    falhas = []

    def registrar(nome, executar):
        try:
            detalhe = executar()
        except Exception as erro:  # noqa: BLE001 - qualquer falha reprova
            falhas.append(f"{nome}: {type(erro).__name__}: {erro}")
            verificacoes.append({"nome": nome, "ok": False, "erro": str(erro)})
        else:
            verificacoes.append({"nome": nome, "ok": True, "detalhe": detalhe})

    registrar("certificados", verificar_certificados)

    def _llm_service():
        import services.llm_service  # noqa: F401 - import real

        return "services.llm_service"

    registrar("services_llm_service", _llm_service)

    def _cadeia():
        falhas_modulos = verificar_modulos_criticos()
        if falhas_modulos:
            raise ImportError("; ".join(falhas_modulos))
        return "cadeia completa"

    registrar("imports_criticos", _cadeia)

    def _app():
        import importlib

        modulo = importlib.import_module("app")
        caminho = getattr(modulo, "__file__", "")

        if caminho and not Path(caminho).is_file():
            raise FileNotFoundError(f"app importado de caminho inválido: {caminho}")

        return {"arquivo": caminho}

    registrar("app", _app)

    resultado = {
        "ok": not falhas,
        "congelado": bool(getattr(sys, "frozen", False)),
        "base_recursos": str(diretorio_recursos()),
        "ssl_cert_file": os.environ.get("SSL_CERT_FILE", ""),
        "verificacoes": verificacoes,
        "falhas": falhas,
    }

    if relatorio:
        try:
            Path(relatorio).write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    return resultado


def autoteste(relatorio=None):
    """Valida o bundle do executável sem abrir janela nem servidor.

    Executa as verificações que falham silenciosamente no empacotamento:

    1. ``app.py``, ``prompts/system_base.txt`` e ``.streamlit/config.toml``
       presentes em ``sys._MEIPASS`` (e não na pasta do ``.exe``);
    2. ``certifi/cacert.pem`` presente no bundle, com ``SSL_CERT_FILE`` e
       ``REQUESTS_CA_BUNDLE`` válidos e um contexto SSL do ``httpx``
       criado de verdade — é a cadeia do ``FileNotFoundError`` do
       ``import ollama``;
    3. imports críticos (Streamlit, Tkinter, ``certifi``, ``httpx``,
       ``ollama``, ``pydantic``, ``pypdf``, ``services.llm_service``,
       ``core.smart_router``, ``core.assistant``, ``python-docx``,
       ``openpyxl`` e PyMuPDF) resolvidos de dentro do bundle;
    4. o system prompt é lido pelo mesmo caminho usado em produção;
    5. um ``.docx`` real é gerado — é o que prova que o
       ``docx/templates/default.docx`` viajou para ``_internal``;
    6. um ``.xlsx`` real é gerado pelo motor ``openpyxl`` do pandas;
    7. o ``app.py`` empacotado é importado de verdade (sem ``.venv`` no
       ``PATH``), repetindo o caminho ``app`` -> ``core`` -> ``services``
       que quebrou na validação real.

    Devolve o dicionário do relatório com ``ok`` e a lista de ``falhas``.
    Quando ``relatorio`` é informado, grava o JSON nesse caminho antes de
    devolver (o executável sem console não tem ``stdout``, então o
    arquivo é o canal de saída do teste).
    """

    import json

    verificacoes = []
    falhas = []

    def _gravar_progresso(concluido=False):
        """Grava o relatório parcial após cada verificação.

        Se uma verificação travar (import de uma DLL, extração do
        bundle), o arquivo mostra exatamente onde o autoteste parou -
        informação que um executável sem console não teria como dar.
        """

        if not relatorio:
            return

        parcial = {
            "ok": bool(concluido and not falhas),
            "congelado": bool(getattr(sys, "frozen", False)),
            "base_recursos": str(diretorio_recursos()),
            "verificacoes": verificacoes,
            "falhas": falhas,
            "concluido": concluido,
        }

        try:
            Path(relatorio).write_text(
                json.dumps(parcial, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Sem relatório em disco o código de saída continua válido.
            pass

    def registrar(nome, executar):
        _gravar_progresso()

        try:
            detalhe = executar()
        except Exception as erro:  # noqa: BLE001 - o autoteste reprova em qualquer falha
            falhas.append(f"{nome}: {type(erro).__name__}: {erro}")
            verificacoes.append({"nome": nome, "ok": False, "erro": str(erro)})
            _gravar_progresso()
            return None

        verificacoes.append({"nome": nome, "ok": True, "detalhe": detalhe})
        _gravar_progresso()
        return detalhe

    congelado = bool(getattr(sys, "frozen", False))
    base = diretorio_recursos()

    def _recursos():
        ausentes = recursos_ausentes()

        if ausentes:
            raise FileNotFoundError(
                "; ".join(f"{caminho} ({descricao})"
                          for caminho, descricao in ausentes)
            )

        return str(base)

    registrar("recursos", _recursos)

    def _prompt():
        from core.prompt_manager import (
            DIRETORIO_PROMPTS,
            arquivo_prompt_base,
            carregar_prompt_base,
        )

        texto = carregar_prompt_base()

        if not texto:
            raise ValueError("system prompt vazio")

        if congelado and not str(DIRETORIO_PROMPTS).startswith(str(base)):
            raise AssertionError(
                f"DIRETORIO_PROMPTS fora do bundle: {DIRETORIO_PROMPTS}"
            )

        return {
            "arquivo": str(arquivo_prompt_base()),
            "caracteres": len(texto),
        }

    registrar("system_prompt", _prompt)

    registrar("certificados", verificar_certificados)

    def _imports():
        falhas_modulos = verificar_modulos_criticos()

        if falhas_modulos:
            raise ImportError("; ".join(falhas_modulos))

        return list(MODULOS_CRITICOS)

    registrar("imports_criticos", _imports)

    def _docx():
        from services.report_generator import gerar_parecer_docx

        conteudo = gerar_parecer_docx(
            "Autoteste de empacotamento",
            "## Verificação\n\nGeração do parecer em memória.",
            [{"titulo": "Documento de teste", "ano": "2026",
              "fonte": "Autoteste"}],
            "Síntese integrada",
        )

        # Um .docx é um ZIP: a assinatura PK confirma o arquivo real.
        if not conteudo or not conteudo.startswith(b"PK"):
            raise ValueError("conteúdo .docx inválido")

        return {"bytes": len(conteudo)}

    registrar("parecer_docx", _docx)

    def _excel():
        import pandas as pd

        from services.table_extractor import gerar_excel

        tabela = {
            "titulo": "Autoteste",
            "secao": "Verificação",
            "origem": "autoteste",
            "pagina": 1,
            "formato": "tabela",
            "df_limpo": pd.DataFrame({"A": [1, 2], "B": ["x", "y"]}),
            "df_bruto": pd.DataFrame({"A": [1, 2], "B": ["x", "y"]}),
            "colunas_numericas": ["A"],
            "unidades": {},
            "observacoes": [],
        }

        conteudo = gerar_excel(tabela)

        if not conteudo or not conteudo.startswith(b"PK"):
            raise ValueError("conteúdo .xlsx inválido")

        return {"bytes": len(conteudo)}

    registrar("excel_openpyxl", _excel)

    def _app_empacotado():
        import importlib

        modulo = importlib.import_module("app")
        caminho = getattr(modulo, "__file__", "")

        if caminho and not Path(caminho).is_file():
            raise FileNotFoundError(
                f"app importado de caminho inválido: {caminho}"
            )

        return {"arquivo": caminho}

    registrar("app_empacotado", _app_empacotado)

    resultado = {
        "ok": not falhas,
        "congelado": congelado,
        "base_recursos": str(base),
        "verificacoes": verificacoes,
        "falhas": falhas,
        "concluido": True,
    }

    _gravar_progresso(concluido=True)

    return resultado


def executar_autoteste(relatorio=None):
    """Roda :func:`autoteste` sem nunca abrir diálogo na tela.

    O executável usa ``console=False`` e o ``main`` mostra erros fatais
    em ``messagebox``; num smoke test automatizado essa janela ficaria
    aberta para sempre esperando um clique. Este caminho é o único usado
    pelo modo ``--autoteste``: qualquer falha vira relatório + código de
    saída, jamais uma janela.
    """

    try:
        return autoteste(relatorio=relatorio)
    except BaseException as erro:  # noqa: BLE001 - inclusive SystemExit/MemoryError
        import json
        import traceback

        relatorio_erro = {
            "ok": False,
            "congelado": bool(getattr(sys, "frozen", False)),
            "base_recursos": str(diretorio_recursos()),
            "verificacoes": [],
            "falhas": [
                f"erro fatal no autoteste: {type(erro).__name__}: {erro}"
            ],
            "concluido": False,
            "traceback": traceback.format_exc(),
        }

        _imprimir(relatorio_erro["traceback"])

        if relatorio:
            try:
                Path(relatorio).write_text(
                    json.dumps(relatorio_erro, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

        return relatorio_erro


def porta_do_argumento(argumentos, padrao=PORTA_PREFERIDA):
    """Lê ``--porta <n>`` (ou ``--porta=<n>``) da linha de comando."""

    argumentos = list(argumentos)

    for indice, item in enumerate(argumentos):
        texto = str(item)

        if texto.startswith(ARG_PORTA + "="):
            candidato = texto.split("=", 1)[1]
        elif texto == ARG_PORTA and indice + 1 < len(argumentos):
            candidato = argumentos[indice + 1]
        else:
            continue

        try:
            porta = int(candidato)
        except (TypeError, ValueError):
            return int(padrao)

        return porta if 0 < porta < 65536 else int(padrao)

    return int(padrao)


def main(argv=None):
    """Fluxo completo do executável: setup opcional e Streamlit."""

    argumentos = list(sys.argv[1:] if argv is None else argv)

    # Modo interno do subprocesso: roda só o CLI do Streamlit, sem setup
    # e sem checar instância (o launcher já fez as duas coisas).
    if ARG_SERVIDOR in argumentos:
        return executar_servidor_streamlit(porta_do_argumento(argumentos))

    # Validação de imports do bundle, sem GUI/servidor/navegador.
    if ARG_VERIFICAR_IMPORTS in argumentos:
        resultado = executar_verificacao_imports(
            relatorio=os.getenv(ENV_RELATORIO_IMPORTS)
        )

        for verificacao in resultado["verificacoes"]:
            estado = "OK" if verificacao["ok"] else "FALHA"

            _imprimir(f"[imports] {estado}: {verificacao['nome']}")

        for falha in resultado["falhas"]:
            _imprimir(f"[imports] {falha}")

        return 0 if resultado["ok"] else 1

    # Autoteste tem prioridade absoluta: valida o bundle e sai, sem
    # assistente de modelos, sem porta, sem navegador e sem diálogo. É o
    # gancho usado pelo smoke test automatizado do build.
    if ARG_AUTOTESTE in argumentos or ARG_AUTOTESTE_ALTERNATIVO in argumentos:
        resultado = executar_autoteste(
            relatorio=os.getenv(ENV_RELATORIO_AUTOTESTE)
        )

        for verificacao in resultado["verificacoes"]:
            estado = "OK" if verificacao["ok"] else "FALHA"

            _imprimir(f"[autoteste] {estado}: {verificacao['nome']}")

        for falha in resultado["falhas"]:
            _imprimir(f"[autoteste] {falha}")

        return 0 if resultado["ok"] else 1

    # Antes de criar um servidor novo, adota a instância já saudável.
    # Sem esta checagem cada abertura do atalho subia mais um servidor
    # (8502, 8503, 8504...) e deixava o anterior órfão em segundo plano.
    if ARG_NOVA_INSTANCIA not in argumentos:
        porta_existente = instancia_ativa()

        if porta_existente:
            _imprimir(
                f"{NOME_APLICATIVO} já está em execução em "
                f"{url_aplicativo(porta_existente)}; abrindo essa janela."
            )

            abrir_instancia_existente(porta_existente)

            return 0

    pediu_setup = ARG_SETUP in argumentos
    pediu_forcar = ARG_FORCAR in argumentos

    try:
        if pediu_setup or pediu_forcar or configuracao_pendente():
            codigo = executar_setup(
                forcar=pediu_setup or pediu_forcar
            )

            if codigo != 0:
                _imprimir(
                    "Aviso: o assistente de modelos terminou com "
                    f"código {codigo}. O aplicativo continuará abrindo."
                )

        porta = _encontrar_porta_livre()

        _imprimir(
            f"{config.APP_NAME} v{config.APP_VERSION} em "
            f"{url_aplicativo(porta)} (dados em {DIRETORIO_DADOS})"
        )

        return iniciar_streamlit(porta)
    except Exception as erro:  # erro fatal: mostra de forma legível
        _mostrar_erro(
            f"{config.APP_NAME} v{config.APP_VERSION}",
            f"Não foi possível iniciar o aplicativo.\n\n"
            f"{type(erro).__name__}: {erro}",
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
