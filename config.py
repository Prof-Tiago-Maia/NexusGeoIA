"""Configuração central do NexusGeo IA.

O módulo resolve três coisas:

1. **Diretório de dados gravável.** Em desenvolvimento (ou na pasta
   portátil) os dados ficam ao lado do projeto. Quando o aplicativo é
   empacotado e instalado em ``Program Files``, a pasta de instalação é
   somente leitura: nesse caso ``data/``, ``database/`` e o
   ``config_local.json`` vão para ``%LOCALAPPDATA%\\NexusGeoIA``.
   A variável de ambiente ``ASSISTENTE_DATA_DIR`` manda em ambos os
   casos e é o que o ``launcher_desktop.py`` define antes de importar
   este módulo.
2. **Configuração local do assistente de modelos.** O
   ``config_local.json`` (gravado por ``setup_llm.py``) guarda
   ``modelos_instalados`` e ``modelo_padrao``. O modelo padrão do
   ``config_local.json`` tem prioridade sobre ``OLLAMA_MODEL`` do
   ambiente; sem nenhum dos dois, vale ``qwen3:4b``.
3. **Parâmetros do Ollama e dos conectores**, todos ajustáveis por
   variável de ambiente.

Nada aqui abre janela, faz rede ou cria diretórios na importação: o
módulo é seguro para testes e para ser importado pelo Streamlit.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Identidade oficial do produto (fonte única da verdade)
# ---------------------------------------------------------------------------
#
# Nome e versão exibidos na interface, na internacionalização, nos
# pareceres técnicos e nos artefatos de empacotamento. Qualquer módulo
# que precise exibir a identidade do produto deve importar estas
# constantes em vez de repetir literais.
APP_NAME = "NexusGeo IA"
APP_VERSION = "0.9.0"
APP_DISPLAY_NAME = f"{APP_NAME} v{APP_VERSION}"

# Nome sem espaços usado em ``%LOCALAPPDATA%`` e nos atalhos do instalador.
# Mantido igual a ``APP_NAME`` sem espaços (validado em tests/).
NOME_APLICATIVO = "NexusGeoIA"

# Modelo usado quando não há ``config_local.json`` nem ``OLLAMA_MODEL``.
MODELO_FALLBACK = "qwen3:4b"

# Ordem de prioridade do modelo padrão gravado em ``config_local.json``.
PRIORIDADE_MODELOS_PADRAO = (
    "qwen3:14b",
    "qwen3:4b",
    "qwen2.5:3b"
)

VERSAO_CONFIG_LOCAL = 1


# ---------------------------------------------------------------------------
# Diretórios do aplicativo
# ---------------------------------------------------------------------------

def diretorio_do_projeto():
    """Raiz dos arquivos do aplicativo (ou do bundle do PyInstaller).

    No executável empacotado, ``sys._MEIPASS`` aponta para a pasta dos
    dados: no modo ``--onedir`` do PyInstaller 6 é
    ``dist\\NexusGeoIA\\_internal`` (ao lado do ``.exe``). Fora do
    empacotamento a raiz é a pasta deste arquivo.
    """

    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)

        if base:
            return Path(base).resolve()

        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def diretorio_localappdata():
    """Pasta gravável do usuário no Windows (``%LOCALAPPDATA%``).

    Fora do Windows usa o diretório de dados do usuário, para que os
    testes e o desenvolvimento em outras plataformas continuem
    funcionando.
    """

    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")

    if base:
        return Path(base) / NOME_APLICATIVO

    return Path.home() / "AppData" / "Local" / NOME_APLICATIVO


def diretorio_padrao_dados():
    """Diretório gravável padrão, antes de considerar o ambiente.

    - Executável empacotado (``sys.frozen``): ``%LOCALAPPDATA%``, porque
      ``Program Files`` não é gravável para usuários comuns.
    - Desenvolvimento ou pasta portátil: a própria raiz do projeto, para
      que a pasta copiada continue autossuficiente.
    """

    if getattr(sys, "frozen", False):
        return diretorio_localappdata()

    return diretorio_do_projeto()


def _resolver_diretorio_dados():
    """Aplica ``ASSISTENTE_DATA_DIR`` sobre o padrão."""

    configurado = os.getenv("ASSISTENTE_DATA_DIR", "").strip()

    if configurado:
        return Path(configurado).expanduser().resolve()

    return Path(diretorio_padrao_dados()).resolve()


RAIZ_PROJETO = diretorio_do_projeto()

DIRETORIO_DADOS = _resolver_diretorio_dados()

DATA_DIR = DIRETORIO_DADOS / "data"

DATABASE_DIR = DIRETORIO_DADOS / "database"

DB_PATH = DATA_DIR / "atendimentos.db"

CONFIG_LOCAL_PATH = DIRETORIO_DADOS / "config_local.json"


def caminho_config_local():
    """Caminho absoluto do ``config_local.json`` em uso."""

    return CONFIG_LOCAL_PATH


def diretorios_dados():
    """Diretórios graváveis que devem existir para o app funcionar."""

    return (
        DIRETORIO_DADOS,
        DATA_DIR,
        DATA_DIR / "docs",
        DATA_DIR / "historico",
        DATA_DIR / "cache_md",
        DATA_DIR / "cache_ana",
        DATA_DIR / "cache_api",
        DATABASE_DIR
    )


def garantir_diretorios():
    """Cria a árvore de dados gravável e devolve sua raiz."""

    for diretorio in diretorios_dados():
        diretorio.mkdir(parents=True, exist_ok=True)

    return DIRETORIO_DADOS


# ---------------------------------------------------------------------------
# config_local.json (assistente de modelos LLM)
# ---------------------------------------------------------------------------

def normalizar_lista_modelos(valor):
    """Normaliza ``modelos_instalados`` em uma lista de nomes únicos.

    Aceita lista, tupla ou string única e descarta entradas vazias,
    preservando a ordem original.
    """

    if valor is None:
        return []

    if isinstance(valor, str):
        itens = [valor]
    elif isinstance(valor, (list, tuple, set)):
        itens = list(valor)
    else:
        return []

    normalizados = []

    for item in itens:
        if item is None:
            continue

        nome = str(item).strip()

        if nome and nome not in normalizados:
            normalizados.append(nome)

    return normalizados


def carregar_config_local(caminho=None):
    """Lê o ``config_local.json`` e devolve um dicionário.

    Arquivo ausente, JSON inválido ou conteúdo que não seja um objeto
    devolvem ``{}``: a configuração local é um extra e nunca pode
    impedir a abertura do assistente.
    """

    destino = Path(caminho) if caminho is not None else CONFIG_LOCAL_PATH

    try:
        # ``utf-8-sig`` aceita o BOM que o Bloco de Notas e o PowerShell
        # 5.1 acrescentam quando o usuário edita o arquivo à mão.
        texto = destino.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return {}

    try:
        dados = json.loads(texto)
    except (json.JSONDecodeError, ValueError):
        return {}

    return dados if isinstance(dados, dict) else {}


def salvar_config_local(dados, caminho=None):
    """Grava ``config_local.json`` de forma atômica e devolve o caminho.

    A escrita usa um arquivo temporário no mesmo diretório e
    ``os.replace``: uma interrupção no meio do download dos modelos não
    deixa um JSON truncado para trás.
    """

    if not isinstance(dados, dict):
        raise TypeError("config_local.json precisa ser um objeto JSON")

    destino = Path(caminho) if caminho is not None else CONFIG_LOCAL_PATH

    destino.parent.mkdir(parents=True, exist_ok=True)

    descritor, temporario = tempfile.mkstemp(
        prefix=destino.name + ".",
        suffix=".tmp",
        dir=str(destino.parent)
    )

    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            json.dump(
                dados,
                arquivo,
                ensure_ascii=False,
                indent=2
            )
            arquivo.write("\n")

        os.replace(temporario, destino)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise

    return destino


def modelo_padrao_do_config(dados):
    """Escolhe o modelo padrão a partir do conteúdo do ``config_local.json``.

    Vale primeiro o campo ``modelo_padrao``; quando ele está ausente ou
    vazio, aplica a prioridade ``qwen3:14b`` > ``qwen3:4b`` >
    ``qwen2.5:3b`` sobre ``modelos_instalados``. Sem nenhum modelo
    conhecido, tenta o primeiro item da lista.
    """

    if not isinstance(dados, dict):
        return ""

    padrao = str(dados.get("modelo_padrao") or "").strip()

    if padrao:
        return padrao

    instalados = normalizar_lista_modelos(dados.get("modelos_instalados"))

    for preferido in PRIORIDADE_MODELOS_PADRAO:
        if preferido in instalados:
            return preferido

    return instalados[0] if instalados else ""


def resolver_modelo_inicial(config_local=None, ambiente=None):
    """Resolve o modelo padrão na ordem config local > ambiente > fallback.

    ``config_local`` e ``ambiente`` são injetáveis para testes; por
    padrão usam o arquivo em disco e ``os.environ``.
    """

    dados = (
        carregar_config_local()
        if config_local is None
        else config_local
    )

    variaveis = os.environ if ambiente is None else ambiente

    modelo_config = modelo_padrao_do_config(dados)

    if modelo_config:
        return modelo_config

    modelo_ambiente = str(variaveis.get("OLLAMA_MODEL", "") or "").strip()

    return modelo_ambiente or MODELO_FALLBACK


# ---------------------------------------------------------------------------
# Modelo do Ollama
# ---------------------------------------------------------------------------

# Modelo padrão do Ollama.
#
# Precedência: ``config_local.json`` (escolha feita no assistente de
# modelos, gravada por ``setup_llm.py``) > variável de ambiente
# ``OLLAMA_MODEL`` > ``qwen3:4b`` (padrão do instalador offline). A
# interface continua permitindo trocar para qualquer modelo instalado na
# barra lateral, sem reiniciar a aplicação.
_CONFIG_LOCAL_INICIAL = carregar_config_local()

MODELOS_INSTALADOS = normalizar_lista_modelos(
    _CONFIG_LOCAL_INICIAL.get("modelos_instalados")
)

OLLAMA_MODEL = resolver_modelo_inicial(_CONFIG_LOCAL_INICIAL)

OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434"
)

# Janela de contexto (em tokens) usada pelo modelo local.
OLLAMA_NUM_CTX = int(
    os.getenv("OLLAMA_NUM_CTX", "32000")
)

# Orçamento de tokens para a geração completa do Ollama (num_predict).
#
# Modelos com raciocínio interno (como o Qwen3) gastam parte desse
# orçamento em ``message.thinking`` antes de começar a escrever o
# ``message.content``. Com um teto baixo o pensamento consome tudo e a
# resposta final chega vazia. Por isso o padrão sobe para 16384, que
# ainda cabe na janela de contexto, mas nunca corta a resposta final.
OLLAMA_NUM_PREDICT_PADRAO = 16384


def _ler_num_predict():
    """Lê o teto de num_predict do ambiente e o limita ao num_ctx.

    ``num_predict`` maior que ``num_ctx`` não aumenta o que o modelo
    consegue gerar; apenas torna a chamada inconsistente. O limite
    explícito mantém o valor dentro do contexto configurado.
    """

    try:
        valor = int(
            os.getenv(
                "OLLAMA_NUM_PREDICT",
                str(OLLAMA_NUM_PREDICT_PADRAO)
            )
        )
    except ValueError:
        valor = OLLAMA_NUM_PREDICT_PADRAO

    if valor <= 0:
        valor = OLLAMA_NUM_PREDICT_PADRAO

    return min(valor, OLLAMA_NUM_CTX)


OLLAMA_NUM_PREDICT = _ler_num_predict()

# Mantém o modelo carregado na memória entre perguntas.
# "-1" significa sem limite de tempo (evita o cold start).
# A API do Ollama aceita número (-1) ou duração ("30m"), mas rejeita a
# string "-1"; por isso valores puramente numéricos viram int.
_valor_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1")

try:
    OLLAMA_KEEP_ALIVE = int(_valor_keep_alive)
except ValueError:
    OLLAMA_KEEP_ALIVE = _valor_keep_alive

# Serviço Geológico do Brasil (SGB)
RIGEO_BASE_URL = os.getenv(
    "RIGEO_BASE_URL",
    "https://rigeo.sgb.gov.br"
)

GEOBUSCA_BASE_URL = os.getenv(
    "GEOBUSCA_BASE_URL",
    "https://geobusca.sgb.gov.br"
)

SGB_TIMEOUT = float(
    os.getenv("SGB_TIMEOUT", "20")
)


# ---------------------------------------------------------------------------
# Cache local do inventário de estações da ANA/HidroWeb
# ---------------------------------------------------------------------------
#
# O inventário é cadastral: nomes, códigos, coordenadas e status mudam
# pouco. Guardar a resposta normalizada em disco por 15 dias evita
# repetir a consulta a cada pergunta e permite responder quando o
# WebService da ANA ou os serviços abertos do SNIRH estão fora do ar.
# O prazo é configurável por ``ANA_CACHE_VALIDADE_DIAS`` (em dias) e o
# diretório por ``ANA_CACHE_DIR`` (vazio usa ``data/cache_ana`` no
# diretório de dados gravável).
def _ler_validade_cache_ana():
    """Validade do cache da ANA em dias, tolerante a valor inválido."""

    try:
        return max(
            0.0,
            float(os.getenv("ANA_CACHE_VALIDADE_DIAS", "15")),
        )
    except ValueError:
        return 15.0


ANA_CACHE_VALIDADE_DIAS = _ler_validade_cache_ana()

ANA_CACHE_DIR = os.getenv("ANA_CACHE_DIR", "").strip()
