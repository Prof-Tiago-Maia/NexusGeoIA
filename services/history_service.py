"""Persistência local leve do histórico de conversas da interface.

Cada conversa é gravada como um único arquivo JSON em
``data/historico/<session_id>.json``. O formato foi escolhido por três
motivos:

- **Portabilidade:** uma pasta de arquivos de texto acompanha o projeto
  em qualquer empacotamento portátil (PyInstaller, zip, pendrive), sem
  servidor, banco embutido ou permissão especial;
- **Resiliência:** cada conversa é independente; um arquivo corrompido é
  ignorado na listagem e não derruba as demais sessões;
- **Leveza:** um arquivo por conversa, com escrita atômica (arquivo
  temporário + ``os.replace``), para que uma interrupção no meio da
  gravação nunca deixe um JSON pela metade.

Estrutura de cada arquivo::

    {
      "id": "20261117_143750_a1b2c3d4",
      "titulo": "Potencial de ETR no Amazonas...",
      "criado_em": "2026-11-17T14:37:50-04:00",
      "atualizado_em": "2026-11-17T14:40:12-04:00",
      "mensagens": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "...", "fonte": "sgb",
         "roteamento": {...}, "artigos_rigeo": [...], "busca_rigeo": {...},
         "estacoes_ana": [...], "siagas": {...}, "macrostrat": {...},
         "geossit": {...}, "geosgb": {...}, "anm": {...}, "web": {...},
         "openalex": {...}, "usgs": {...}, "feicoes_espaciais": [...],
         "perfil_analitico": "Hidrogeologia & Recursos Hídricos"}
      ]
    }

O ``session_id`` também é usado pela interface como prefixo das chaves
dos widgets (``st.expander``, ``st.link_button`` e cartões de fontes),
o que garante chaves únicas por conversa e evita o erro
``StreamlitDuplicateElementKey`` ao alternar entre sessões.

As funções públicas não lançam exceção em situação normal de disco
(arquivo ausente, JSON inválido ou permissão negada): devolvem ``None``,
lista vazia ou ``False``, de modo que a interface continue funcionando
mesmo com o histórico indisponível.
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from config import DATA_DIR


# ---------------------------------------------------------------------------
# Diretório de armazenamento
# ---------------------------------------------------------------------------

# O caminho é resolvido por ``config`` (e não pelo diretório corrente):
# assim o histórico continua sendo encontrado mesmo quando o aplicativo
# é iniciado por um atalho, pelo ``iniciar.bat`` ou a partir de outro
# diretório de trabalho. No executável instalado em ``Program Files`` a
# pasta fica em ``%LOCALAPPDATA%\\NexusGeoIA\\data``.
DIRETORIO_HISTORICO = DATA_DIR / "historico"

EXTENSAO_CONVERSA = ".json"

# Sufixo do arquivo temporário usado na escrita atômica. Um arquivo que
# termine assim é lixo de uma gravação interrompida e é ignorado.
SUFIXO_TEMPORARIO = ".tmp"

TITULO_PADRAO = "Nova conversa"

# Título automático: primeiros 42 caracteres da primeira pergunta.
TAMANHO_MAXIMO_TITULO = 42

# Versão do formato gravado, para evoluções futuras sem quebrar a
# leitura dos arquivos antigos.
VERSAO_FORMATO = 1


class HistoricoError(OSError):
    """Erro de gravação do histórico com mensagem pronta para a interface.

    Herda de ``OSError`` para que quem já captura falhas de disco
    continue funcionando sem mudanças.
    """


# ---------------------------------------------------------------------------
# Validação dos identificadores
# ---------------------------------------------------------------------------

# O identificador vira nome de arquivo: aceita apenas letras, números,
# hífen e sublinhado. Além de ser o formato gerado por ``novo_session_id``,
# essa regra bloqueia travessia de diretório (``../``) caso um valor
# adulterado chegue às funções de leitura ou exclusão.
_PADRAO_ID_VALIDO = re.compile(r"[A-Za-z0-9_-]{1,80}")


def id_valido(session_id):
    """Indica se o texto pode ser usado como identificador de conversa."""

    return bool(
        isinstance(session_id, str)
        and _PADRAO_ID_VALIDO.fullmatch(session_id)
    )


def novo_session_id(momento=None):
    """Gera um identificador curto e ordenável por data de criação.

    Formato ``YYYYMMDD_HHMMSS_<8 hex>``; o sufixo aleatório evita
    colisão quando duas conversas nascem no mesmo segundo.
    """

    momento = momento or datetime.now()

    return (
        f"{momento.strftime('%Y%m%d_%H%M%S')}_"
        f"{os.urandom(4).hex()}"
    )


# ---------------------------------------------------------------------------
# Datas ISO
# ---------------------------------------------------------------------------

def agora_iso(momento=None):
    """Data/hora atual em ISO 8601, com deslocamento do fuso local."""

    return (momento or datetime.now()).astimezone().isoformat(
        timespec="seconds"
    )


def _data_iso(valor):
    """Normaliza uma data do estado da sessão em ISO 8601.

    A sessão guarda a data de criação em memória; quando ela não vem da
    ISO de ``str`` (ausente ou inválida), a hora atual assume.
    """

    if isinstance(valor, datetime):
        return valor.astimezone().isoformat(timespec="seconds")

    if isinstance(valor, str) and valor.strip():
        return valor.strip()

    return agora_iso()


def _chave_ordenacao(texto_iso):
    """Converte a ISO em algo comparável, mesmo com fusos diferentes.

    Datas com deslocamento explícito viram um número comparável; datas
    sem fuso caem em um segundo critério, já que não dá para convertê-las
    sem adivinhar o fuso.
    """

    try:
        momento = datetime.fromisoformat(texto_iso)

        if momento.tzinfo is None:
            return (1, momento.timestamp(), "")

        return (0, momento.timestamp(), "")
    except (TypeError, ValueError):
        return (2, 0.0, str(texto_iso or ""))


# ---------------------------------------------------------------------------
# Título automático
# ---------------------------------------------------------------------------

def gerar_titulo(texto):
    """Título curto a partir da primeira pergunta do usuário.

    O texto é reduzido a uma linha, sem marcação Markdown e sem
    reticências pendentes; quando passa de 42 caracteres, o corte
    respeita a última palavra inteira e recebe ``...``.
    """

    titulo = " ".join(str(texto or "").split())

    if not titulo:
        return TITULO_PADRAO

    # Remove a marcação mais comum de Markdown (código, negrito, itálico,
    # títulos e citações), que não faz sentido em um título curto.
    titulo = re.sub(r"[`*_#>~]", "", titulo)
    titulo = " ".join(titulo.split())

    if not titulo:
        return TITULO_PADRAO

    if len(titulo) <= TAMANHO_MAXIMO_TITULO:
        return titulo

    corte = titulo[:TAMANHO_MAXIMO_TITULO]
    ultimo_espaco = corte.rfind(" ")

    # Só quebra na palavra quando isso não perde quase todo o título
    # (palavras muito longas, como URLs, são cortadas no limite).
    if ultimo_espaco >= TAMANHO_MAXIMO_TITULO // 2:
        corte = corte[:ultimo_espaco]

    return corte.rstrip(" .,;:-") + "..."


def _primeira_pergunta(mensagens):
    """Conteúdo da primeira mensagem do usuário, ou ``""``."""

    for mensagem in mensagens or ():
        if isinstance(mensagem, dict) and mensagem.get("role") == "user":
            return str(mensagem.get("content") or "")

    return ""


def _resolver_titulo(titulo, mensagens):
    """Título efetivo: o informado, o automático ou o padrão."""

    if isinstance(titulo, str) and titulo.strip():
        return titulo.strip()

    pergunta = _primeira_pergunta(mensagens)

    if pergunta.strip():
        return gerar_titulo(pergunta)

    return TITULO_PADRAO


# ---------------------------------------------------------------------------
# Normalização das mensagens
# ---------------------------------------------------------------------------

# Chaves preservadas em cada mensagem. Elas formam o contrato usado pela
# interface: ``content`` é o texto e as demais alimentam a legenda de
# fonte, o expander "📚 Fontes e Metadados Consultados" e os cartões do
# RIGeo com os links de PDF.
#
# ``chave`` e ``criado_em`` são campos de execução (prefixo dos widgets
# e data da mensagem): não entram no arquivo para manter o JSON leve, e
# a interface recria a chave a partir do índice ao reabrir a conversa.
_CAMPOS_MENSAGEM = (
    "role",
    "content",
    "fonte",
    "roteamento",
    "artigos_rigeo",
    "busca_rigeo",
    "estacoes_ana",
    "siagas",
    "macrostrat",
    "geossit",
    "geosgb",
    "anm",
    "web",
    "openalex",
    "usgs",
    "intl_geo",
    "feicoes_espaciais",
    "perfil_analitico",
)

_PAPEIS_VALIDOS = ("user", "assistant")


def _normalizar_mensagem(mensagem):
    """Cópia segura de uma mensagem, sem referências externas.

    A cópia evita gravar o próprio objeto do ``st.session_state`` e
    garante que a estrutura salva continue serializável em JSON.
    """

    if not isinstance(mensagem, dict):
        return None

    papel = mensagem.get("role")

    if papel not in _PAPEIS_VALIDOS:
        papel = "assistant"

    normalizada = {
        "role": papel,
        "content": str(mensagem.get("content") or ""),
    }

    for campo in _CAMPOS_MENSAGEM[2:]:
        valor = mensagem.get(campo)

        if valor in (None, "", [], {}):
            continue

        if isinstance(valor, (dict, list)):
            try:
                normalizada[campo] = json.loads(json.dumps(valor))
            except (TypeError, ValueError):
                # Metadado não serializável (objeto exótico vindo de uma
                # consulta): descartado, para não perder a conversa toda.
                continue
        else:
            normalizada[campo] = valor

    return normalizada


def _normalizar_mensagens(mensagens):
    """Lista de mensagens prontas para serialização."""

    return [
        normalizada
        for normalizada in (
            _normalizar_mensagem(mensagem)
            for mensagem in mensagens or ()
        )
        if normalizada is not None
    ]


# ---------------------------------------------------------------------------
# Caminhos e leitura
# ---------------------------------------------------------------------------

def garantir_diretorio():
    """Cria ``data/historico`` se ainda não existir e devolve o caminho."""

    DIRETORIO_HISTORICO.mkdir(parents=True, exist_ok=True)

    return DIRETORIO_HISTORICO


def caminho_conversa(session_id):
    """Caminho do arquivo de uma conversa (``None`` se o id for inválido)."""

    if not id_valido(session_id):
        return None

    return DIRETORIO_HISTORICO / f"{session_id}{EXTENSAO_CONVERSA}"


def _ler_arquivo(caminho):
    """Lê e valida o JSON de uma conversa; ``None`` se não der para usar."""

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None

    if not isinstance(dados, dict):
        return None

    mensagens = _normalizar_mensagens(dados.get("mensagens"))

    return {
        "id": caminho.stem,
        "titulo": _resolver_titulo(dados.get("titulo"), mensagens),
        "criado_em": _data_iso(dados.get("criado_em")),
        "atualizado_em": _data_iso(dados.get("atualizado_em")),
        "mensagens": mensagens,
    }


def listar_conversas():
    """Resumos das conversas salvas, da mais recente para a mais antiga.

    Cada item traz ``id``, ``titulo``, ``criado_em``, ``atualizado_em`` e
    ``total_mensagens``, sem carregar o conteúdo das mensagens — a
    barra lateral só precisa dos metadados para montar a lista.
    """

    try:
        arquivos = list(DIRETORIO_HISTORICO.glob(f"*{EXTENSAO_CONVERSA}"))
    except OSError:
        return []

    conversas = []

    for caminho in arquivos:
        if not id_valido(caminho.stem):
            continue

        dados = _ler_arquivo(caminho)

        if dados is None:
            continue

        conversas.append({
            "id": dados["id"],
            "titulo": dados["titulo"],
            "criado_em": dados["criado_em"],
            "atualizado_em": dados["atualizado_em"],
            "total_mensagens": len(dados["mensagens"]),
        })

    # Ordem cronológica decrescente. O id (que começa pela data de
    # criação) desempata conversas atualizadas no mesmo segundo e
    # garante uma ordenação estável entre execuções.
    conversas.sort(
        key=lambda conversa: (
            _chave_ordenacao(conversa["atualizado_em"]),
            conversa["id"],
        ),
        reverse=True,
    )

    return conversas


def carregar_conversa(session_id):
    """Lê uma conversa completa; ``None`` se ela não existir ou estiver inválida."""

    caminho = caminho_conversa(session_id)

    if caminho is None or not caminho.is_file():
        return None

    return _ler_arquivo(caminho)


# ---------------------------------------------------------------------------
# Gravação e exclusão
# ---------------------------------------------------------------------------

def _gravar_atomico(caminho, dados):
    """Grava o JSON em arquivo temporário e o move para o destino final.

    ``os.replace`` é atômico no mesmo volume: ou o arquivo antigo
    permanece inteiro, ou o novo assume. Uma interrupção no meio nunca
    deixa um JSON truncado legível.
    """

    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)

    descritor, temporario = tempfile.mkstemp(
        dir=str(caminho.parent),
        prefix=f".{caminho.stem}_",
        suffix=SUFIXO_TEMPORARIO
    )

    try:
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())

        os.replace(temporario, caminho)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass

        raise


def salvar_conversa(session_id, titulo, mensagens):
    """Grava (ou sobrescreve) a conversa ``<session_id>.json``.

    - ``titulo`` vazio faz o título ser gerado a partir da primeira
      pergunta, com queda para ``"Nova conversa"``;
    - ``criado_em`` é preservado do arquivo existente; só
      ``atualizado_em`` acompanha a gravação (é ele que ordena a lista);
    - uma conversa sem mensagens **não** é gravada, e um arquivo vazio
      que já exista é removido, para que a lista não acumule conversas
      sem conteúdo.

    Devolve ``True`` quando há um arquivo no disco ao final, ``False``
    quando não havia o que salvar e ``None`` quando o identificador é
    inválido. Falhas de disco sobem como :class:`HistoricoError`.
    """

    caminho = caminho_conversa(session_id)

    if caminho is None:
        return None

    mensagens_normalizadas = _normalizar_mensagens(mensagens)

    if not mensagens_normalizadas:
        excluir_conversa(session_id)
        return False

    titulo = _resolver_titulo(titulo, mensagens_normalizadas)
    agora = agora_iso()
    criado_em = agora

    existente = _ler_arquivo(caminho) if caminho.is_file() else None

    if existente is not None:
        criado_em = existente["criado_em"]

    dados = {
        "versao": VERSAO_FORMATO,
        "id": session_id,
        "titulo": titulo,
        "criado_em": criado_em,
        "atualizado_em": agora,
        "mensagens": mensagens_normalizadas,
    }

    try:
        garantir_diretorio()
        _gravar_atomico(caminho, dados)
    except OSError as erro:
        raise HistoricoError(
            f"Não foi possível salvar a conversa em {caminho}: {erro}"
        ) from erro

    return True


def excluir_conversa(session_id):
    """Apaga o arquivo da conversa.

    Devolve ``True`` quando o arquivo foi removido, ``False`` quando ele
    não existia (inclusive id inválido; a operação é idempotente, como
    o protocolo HTTP usado pelo Streamlit) e lança
    :class:`HistoricoError` quando o disco recusa a exclusão.
    """

    caminho = caminho_conversa(session_id)

    if caminho is None:
        return False

    try:
        caminho.unlink()
    except FileNotFoundError:
        return False
    except OSError as erro:
        raise HistoricoError(
            f"Não foi possível excluir a conversa {session_id}: {erro}"
        ) from erro

    return True


def excluir_todas_conversas():
    """Apaga todos os arquivos de conversa de ``data/historico``.

    A limpeza é seletiva de propósito: só entram na exclusão os arquivos
    ``.json`` cujo nome segue o formato de identificador gerado por
    :func:`novo_session_id`. Ficam intactos:

    - ``.gitkeep`` e qualquer outro arquivo oculto (nome começando por
      ponto), incluindo os temporários ``.tmp`` da escrita atômica;
    - arquivos que não sejam ``.json`` e arquivos com nome fora do
      padrão de identificador.

    Os documentos indexados em ``data/docs`` não são tocados: este
    serviço cuida somente do histórico de conversas.

    Devolve a quantidade de arquivos efetivamente apagados. Uma falha de
    disco em qualquer arquivo interrompe a operação com
    :class:`HistoricoError`, informando o que já havia sido removido,
    para que o usuário saiba do resultado parcial.
    """

    try:
        arquivos = list(DIRETORIO_HISTORICO.glob(f"*{EXTENSAO_CONVERSA}"))
    except OSError:
        return 0

    apagadas = 0
    falhas = []

    for caminho in arquivos:
        # Preserva arquivos ocultos (``.gitkeep``, temporários da escrita
        # atômica e qualquer outro marcador de diretório).
        if caminho.name.startswith("."):
            continue

        if not caminho.is_file() or not id_valido(caminho.stem):
            continue

        try:
            caminho.unlink()
        except FileNotFoundError:
            # Outro processo já removeu o arquivo: nada a fazer.
            continue
        except OSError as erro:
            falhas.append(f"{caminho.name}: {erro}")
        else:
            apagadas += 1

    if falhas:
        raise HistoricoError(
            "Não foi possível apagar todo o histórico "
            f"({apagadas} conversa(s) removida(s)): " + "; ".join(falhas)
        )

    return apagadas
