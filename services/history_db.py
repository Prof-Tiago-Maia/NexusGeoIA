"""Histórico transacional de conversas em SQLite (Fase D1).

Este módulo é a ponte entre a interface (Streamlit) e o schema de
memória episódica de ``services.db_service``. Ele substitui, para
efeito de histórico, a pasta ``data/historico`` com um arquivo JSON por
conversa: as sessões e mensagens passam a viver em ``chat_sessions`` e
``chat_messages``, com exclusão em cascata e gravação atômica.

Responsabilidades:

* normalizar as mensagens da sessão (texto + metadados de fontes,
  governança e proveniência) para o contrato do SQLite;
* gravar a conversa inteira em uma única transação, sem deixar a
  sessão pela metade quando o Streamlit interrompe o script;
* migrar, uma única vez e de forma aditiva, o histórico JSON legado
  de ``data/historico`` — os arquivos originais não são apagados;
* devolver dicionários simples, sem ``sqlite3.Row``, para a UI e para
  os testes.

O módulo não abre interface e não acessa a rede. O banco padrão fica
em ``config.DATA_DIR/nexusgeoia.db`` (ou ``NEXUSGEO_DB_PATH``), o mesmo
diretório gravável resolvido por ``ASSISTENTE_DATA_DIR``. Qualquer
caminho pode ser injetado nas funções públicas, o que mantém os testes
isolados.
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
from pathlib import Path

from config import DATA_DIR
from services import db_service, history_service

ARQUIVO_BANCO = "nexusgeoia.db"

# Marca gravada em schema_meta depois da primeira migração. Sem ela, a
# varredura de data/historico se repetiria a cada rerun do Streamlit.
CHAVE_MIGRACAO = "historico_json_migrado"
VERSAO_MIGRACAO = "1"

# Papéis aceitos no histórico; mensagens de sistema também são
# preservadas, porque o resumo progressivo pode usá-las no futuro.
PAPEIS = ("user", "assistant", "system")

# Campos que já têm coluna própria em chat_messages. Todo o resto da
# mensagem vira metadados_json.
_CAMPOS_ESTRUTURAIS = frozenset({
    "role",
    "content",
    "papel",
    "conteudo",
    "chave",
    "criado_em",
    "resumida_em",
    "veredito",
    "governanca",
    "metadados",
})

_INICIALIZADOS: set[str] = set()


class HistoricoBDError(RuntimeError):
    """Falha de persistência do histórico SQLite.

    A mensagem é técnica e pronta para log; a interface traduz o aviso
    pelas chaves de ``utils.i18n``.
    """


def _traduzir_erros_sqlite(mensagem):
    """Converte qualquer ``sqlite3.Error`` em ``HistoricoBDError``.

    As funções públicas desta camada expõem apenas o erro de domínio do
    histórico. O decorador cobre os caminhos que ainda não tinham um
    ``try/except`` próprio (por exemplo, a migração do JSON legado) e
    preserva o tipo quando a falha já foi traduzida internamente.
    """

    def decorador(funcao):
        @functools.wraps(funcao)
        def envolvida(*args, **kwargs):
            try:
                return funcao(*args, **kwargs)
            except HistoricoBDError:
                raise
            except sqlite3.Error as erro:
                raise HistoricoBDError(mensagem) from erro

        return envolvida

    return decorador


def _em_ambiente_de_teste():
    """Indica se a inicialização deve pular a migração do JSON legado.

    A suíte automatizada aponta o banco para uma pasta temporária, mas
    não pode varrer o ``data/historico`` real do projeto. O aplicativo
    normal não define essa variável, então a migração aditiva continua
    sendo disparada na inicialização padrão.
    """

    valor = os.getenv("NEXUSGEO_TEST_MODE", "").strip().lower()

    return valor in {"1", "true", "sim", "yes", "on"}


# ---------------------------------------------------------------------------
# Caminho e schema
# ---------------------------------------------------------------------------


def caminho_banco(caminho_db=None):
    """Caminho absoluto do banco do histórico.

    Prioridade: argumento explícito > NEXUSGEO_DB_PATH >
    ``config.DATA_DIR/nexusgeoia.db``. A variável de ambiente é lida a
    cada chamada para que testes e diagnósticos possam trocar o alvo
    sem recarregar o módulo.
    """

    if caminho_db is not None:
        return Path(caminho_db).expanduser().resolve()

    explicito = os.getenv("NEXUSGEO_DB_PATH", "").strip()

    if explicito:
        return Path(explicito).expanduser().resolve()

    return (Path(DATA_DIR) / ARQUIVO_BANCO).resolve()


def _garantir_schema(caminho):
    """Cria o schema uma vez por processo e devolve o caminho."""

    chave = str(caminho)

    if chave in _INICIALIZADOS:
        return caminho

    try:
        db_service.inicializar_banco(caminho)
    except (sqlite3.Error, OSError) as erro:
        raise HistoricoBDError(
            "Não foi possível abrir o banco do histórico."
        ) from erro

    _INICIALIZADOS.add(chave)

    return caminho


@_traduzir_erros_sqlite(
    "Não foi possível inicializar o banco do histórico."
)
def inicializar(caminho_db=None):
    """Garante o schema e, no banco padrão, dispara a migração legada."""

    caminho = _garantir_schema(caminho_banco(caminho_db))

    # A migração só roda no banco padrão do aplicativo. Um caminho
    # explícito é tratado como isolado (testes, diagnóstico, backup) e
    # não importa silenciosamente o histórico real do usuário. No
    # ambiente de teste a varredura também é pulada para não ler
    # ``data/historico`` real do projeto.
    if caminho_db is None and not _em_ambiente_de_teste():
        _migrar_uma_vez(caminho)

    return caminho


# ---------------------------------------------------------------------------
# Normalização das mensagens
# ---------------------------------------------------------------------------


def _serializavel(valor):
    """Indica se o valor sobrevive a um ciclo JSON sem perda relevante."""

    try:
        json.dumps(valor, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return False

    return True


def normalizar_mensagem(mensagem):
    """Converte uma mensagem da UI no contrato de db_service."""

    if not isinstance(mensagem, dict):
        return None

    papel = mensagem.get("role") or mensagem.get("papel")

    if papel not in PAPEIS:
        papel = "assistant"

    conteudo = mensagem.get("content")

    if conteudo is None:
        conteudo = mensagem.get("conteudo")

    metadados = {}

    for campo, valor in mensagem.items():
        if campo in _CAMPOS_ESTRUTURAIS:
            continue

        if valor in (None, "", [], {}):
            continue

        if _serializavel(valor):
            metadados[campo] = valor

    normalizada = {
        "role": str(papel),
        "content": str(conteudo or ""),
        "metadados": metadados,
    }

    if mensagem.get("criado_em"):
        normalizada["criado_em"] = str(mensagem["criado_em"])

    governanca = mensagem.get("governanca")

    if isinstance(governanca, dict) and governanca:
        normalizada["governanca"] = governanca

        veredito = governanca.get("veredito")

        if veredito in db_service.VEREDITOS:
            normalizada["veredito"] = veredito

    return normalizada


def normalizar_mensagens(mensagens):
    """Lista limpa de mensagens, sem entradas inválidas."""

    return [
        normalizada
        for normalizada in (
            normalizar_mensagem(mensagem)
            for mensagem in mensagens or ()
        )
        if normalizada is not None
    ]


def _resolver_titulo(titulo, mensagens):
    """Título efetivo: o informado ou o gerado da primeira pergunta."""

    if isinstance(titulo, str) and titulo.strip():
        return " ".join(titulo.split())

    for mensagem in mensagens or ():
        if mensagem.get("role") == "user":
            return history_service.gerar_titulo(mensagem.get("content"))

    return history_service.TITULO_PADRAO


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


@_traduzir_erros_sqlite(
    "Não foi possível listar as conversas do banco local."
)
def listar_conversas(limite=50, caminho_db=None):
    """Resumos das conversas, da mais recente para a mais antiga."""

    caminho = inicializar(caminho_db)

    try:
        sessoes = db_service.listar_sessoes(
            limite=limite,
            caminho_db=caminho,
        )
    except sqlite3.Error as erro:
        raise HistoricoBDError(
            "Não foi possível listar as conversas do banco local."
        ) from erro

    conversas = []

    for sessao in sessoes:
        metadados = sessao.get("metadados") or {}

        conversas.append({
            "id": sessao["id"],
            "titulo": sessao["titulo"],
            "criado_em": sessao["criado_em"],
            "atualizado_em": sessao["atualizado_em"],
            "total_mensagens": int(sessao.get("total_mensagens") or 0),
            "workflow": metadados.get("workflow"),
            "folha_cim": metadados.get("folha_cim"),
        })

    return conversas


@_traduzir_erros_sqlite(
    "Não foi possível carregar a conversa do banco local."
)
def carregar_conversa(session_id, caminho_db=None):
    """Carrega uma conversa completa ou ``None`` quando não existe."""

    caminho = inicializar(caminho_db)

    try:
        sessao = db_service.obter_sessao(session_id, caminho_db=caminho)
        linhas = (
            db_service.listar_mensagens(session_id, caminho_db=caminho)
            if sessao is not None
            else []
        )
    except sqlite3.Error as erro:
        raise HistoricoBDError(
            "Não foi possível carregar a conversa do banco local."
        ) from erro

    if sessao is None:
        return None

    mensagens = []

    for linha in linhas:
        mensagem = dict(linha.get("metadados") or {})
        mensagem["role"] = linha["papel"]
        mensagem["content"] = linha["conteudo"]
        mensagem["criado_em"] = linha["criado_em"]

        governanca = linha.get("governanca") or {}

        if isinstance(governanca, dict) and governanca:
            mensagem["governanca"] = governanca

        mensagens.append(mensagem)

    metadados = sessao.get("metadados") or {}

    return {
        "id": sessao["id"],
        "titulo": sessao["titulo"],
        "criado_em": sessao["criado_em"],
        "atualizado_em": sessao["atualizado_em"],
        "workflow": metadados.get("workflow"),
        "folha_cim": metadados.get("folha_cim"),
        "mensagens": mensagens,
    }


# ---------------------------------------------------------------------------
# Gravação e exclusão
# ---------------------------------------------------------------------------


@_traduzir_erros_sqlite(
    "Não foi possível gravar a conversa no banco local."
)
def salvar_conversa(
    session_id,
    titulo="",
    mensagens=None,
    workflow=None,
    folha_cim=None,
    caminho_db=None,
    criado_em=None,
):
    """Grava (ou substitui) a conversa inteira em uma transação.

    Conversa sem mensagens não é gravada: a sessão existente é removida
    para a lista não acumular entradas vazias. Devolve ``True`` quando
    há uma conversa no banco e ``False`` quando não havia o que salvar.
    Falhas de SQLite sobem como :class:`HistoricoBDError`.
    """

    caminho = _garantir_schema(caminho_banco(caminho_db))
    mensagens = normalizar_mensagens(mensagens)

    if not mensagens:
        excluir_conversa(session_id, caminho)
        return False

    metadados = {}

    if workflow:
        metadados["workflow"] = str(workflow)

    if folha_cim:
        metadados["folha_cim"] = str(folha_cim)

    try:
        db_service.substituir_conversa(
            session_id,
            _resolver_titulo(titulo, mensagens),
            mensagens,
            metadados=metadados,
            criado_em=criado_em,
            caminho_db=caminho,
        )
    except (sqlite3.Error, TypeError, ValueError, OSError) as erro:
        raise HistoricoBDError(
            "Não foi possível gravar a conversa no banco local."
        ) from erro

    return True


@_traduzir_erros_sqlite(
    "Não foi possível excluir a conversa do banco local."
)
def excluir_conversa(session_id, caminho_db=None):
    """Exclui a sessão; a cascata remove mensagens e afirmações."""

    caminho = _garantir_schema(caminho_banco(caminho_db))

    try:
        return db_service.excluir_sessao(session_id, caminho_db=caminho)
    except sqlite3.Error as erro:
        raise HistoricoBDError(
            "Não foi possível excluir a conversa do banco local."
        ) from erro


@_traduzir_erros_sqlite(
    "Não foi possível apagar o histórico do banco local."
)
def excluir_todas_conversas(caminho_db=None):
    """Apaga todas as conversas e devolve a quantidade removida."""

    caminho = _garantir_schema(caminho_banco(caminho_db))

    try:
        return db_service.excluir_todas_sessoes(caminho_db=caminho)
    except sqlite3.Error as erro:
        raise HistoricoBDError(
            "Não foi possível apagar o histórico do banco local."
        ) from erro


def contar_folhas_cache(caminho_db=None):
    """Folhas CIM em cache; devolve 0 quando o banco não responde."""

    try:
        caminho = _garantir_schema(caminho_banco(caminho_db))
        return db_service.contar_folhas_cache(caminho_db=caminho)
    except (HistoricoBDError, sqlite3.Error, OSError):
        return 0


# ---------------------------------------------------------------------------
# Migração do histórico JSON legado
# ---------------------------------------------------------------------------


def _ler_migracao(caminho):
    """Indica se a migração já foi concluída para este banco."""

    with db_service.conexao(caminho) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            "SELECT valor FROM schema_meta WHERE chave = ?",
            (CHAVE_MIGRACAO,),
        ).fetchone()

    return linha is not None


def _gravar_migracao(caminho):
    """Marca a migração como concluída (idempotente)."""

    with db_service.conexao(caminho) as conexao_sqlite:
        conexao_sqlite.execute(
            """
            INSERT INTO schema_meta (chave, valor)
            VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (CHAVE_MIGRACAO, VERSAO_MIGRACAO),
        )


@_traduzir_erros_sqlite(
    "Não foi possível migrar o histórico JSON legado."
)
def migrar_historico_json(diretorio=None, caminho_db=None, forcar=False):
    """Importa o histórico JSON legado de forma aditiva e idempotente.

    Cada arquivo ``*.json`` de ``data/historico`` é lido pelo serviço
    legado e gravado no SQLite apenas quando o ``session_id`` ainda não
    existe no banco. Os arquivos originais ficam intactos: a migração
    pode ser repetida sem duplicar conversas e sem risco de perda.

    Devolve a quantidade de conversas efetivamente importadas. Falhas
    em um arquivo isolado não interrompem os demais. A marca em
    ``schema_meta`` evita varrer a pasta a cada rerun; ``forcar=True``
    ignora a marca (usado nos testes e em recuperação manual).
    """

    caminho = _garantir_schema(caminho_banco(caminho_db))

    if not forcar and _ler_migracao(caminho):
        return 0

    pasta = Path(diretorio) if diretorio is not None else (
        history_service.DIRETORIO_HISTORICO
    )

    try:
        arquivos = sorted(pasta.glob("*.json"))
    except OSError:
        arquivos = []

    migradas = 0

    for arquivo in arquivos:
        if arquivo.name.startswith("."):
            continue

        conversa = history_service.ler_conversa_de_arquivo(arquivo)

        if not conversa:
            continue

        session_id = str(conversa.get("id") or arquivo.stem)

        if db_service.obter_sessao(session_id, caminho_db=caminho):
            continue

        try:
            salvo = salvar_conversa(
                session_id,
                conversa.get("titulo") or "",
                conversa.get("mensagens") or [],
                caminho_db=caminho,
                criado_em=conversa.get("criado_em"),
            )
        except (HistoricoBDError, ValueError, OSError):
            continue

        if salvo:
            migradas += 1

    _gravar_migracao(caminho)

    return migradas


def _migrar_uma_vez(caminho):
    """Executa a migração legada uma única vez por banco."""

    if _ler_migracao(caminho):
        return 0

    return migrar_historico_json(caminho_db=caminho)


# ---------------------------------------------------------------------------
# Compatibilidade com o serviço legado
# ---------------------------------------------------------------------------

# A interface antiga importava estas funções de ``history_service``.
# Mantê-las aqui, com o mesmo nome, deixa a migração incremental e
# permite que integrações externas apontem apenas para o novo módulo.
listar_sessoes = listar_conversas