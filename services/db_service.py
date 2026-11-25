"""Persistência SQLite das três camadas de memória do NexusGeo IA.

A Fase D1 separa a memória do assistente em três camadas explícitas:

* Episódica — conversas (chat_sessions) e mensagens (chat_messages),
  com resumo progressivo por sessão e exclusão em cascata;
* Linhagem — fontes de evidência (evidence_sources), vínculo entre
  mensagem e evidência (message_evidence) e afirmações auditáveis
  (claim_records);
* Operacional — cache espacial por folha CIM (spatial_cache) e índice
  de documentos por hash SHA-256 (documents).

O banco usa WAL para permitir leitura durante a escrita (o Streamlit
pode redesenhar enquanto uma resposta é gravada), foreign_keys=ON para
que a cascata seja real e um busy_timeout generoso, necessário no
Windows quando dois processos abrem o mesmo arquivo.

O diretório é resolvido por ASSISTENTE_DATA_DIR ou, quando a variável
não existe, por %LOCALAPPDATA%/NexusGeoIA. O caminho também pode ser
injetado nas funções públicas, o que mantém os testes isolados e
permite reutilizar a camada em CLI.

Nenhuma função daqui abre a interface, acessa a rede ou depende do
Ollama. As operações devolvem dados simples (dict/list) para que a UI e
os testes não precisem conhecer sqlite3.Row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Identidade e localização do banco
# ---------------------------------------------------------------------------

NOME_APLICATIVO = "NexusGeoIA"
ARQUIVO_BANCO = "nexusgeoia.db"
PASTA_DADOS = "data"

# Tempo de espera por lock. O valor de conexão e o busy_timeout do
# SQLite andam juntos; 30 s cobre varreduras do RAG e antivírus do
# Windows sem transformar um lock curto em erro na interface.
TIMEOUT_SEGUNDOS = 30.0
BUSY_TIMEOUT_MS = 30000

VERSAO_SCHEMA = 2

PAPEIS_MENSAGEM = ("user", "assistant", "system")
CLASSIFICACOES_AFIRMACAO = ("OBSERVED", "INFERRED")
VEREDITOS = ("PASS", "HOLD", "FAIL")


def diretorio_dados():
    """Diretório gravável do aplicativo.

    Prioridade: ASSISTENTE_DATA_DIR > %LOCALAPPDATA%/NexusGeoIA >
    %APPDATA%/NexusGeoIA > diretório do usuário. A variável é lida a
    cada chamada para que testes e o launcher possam trocá-la sem
    recarregar o módulo.
    """

    configurado = os.getenv("ASSISTENTE_DATA_DIR", "").strip()

    if configurado:
        return Path(configurado).expanduser().resolve()

    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")

    if base:
        return Path(base).expanduser().resolve() / NOME_APLICATIVO

    return Path.home() / "AppData" / "Local" / NOME_APLICATIVO


def caminho_padrao_banco():
    """Caminho do banco dentro da pasta de dados resolvida."""

    # NEXUSGEO_DB_PATH é uma válvula de escape para diagnósticos e
    # testes de integração; não substitui a convenção do aplicativo.
    explicito = os.getenv("NEXUSGEO_DB_PATH", "").strip()

    if explicito:
        return Path(explicito).expanduser().resolve()

    return diretorio_dados() / PASTA_DADOS / ARQUIVO_BANCO


def _resolver_caminho(caminho_db=None):
    """Normaliza o caminho informado ou devolve o padrão."""

    if caminho_db is None:
        return caminho_padrao_banco()

    return Path(caminho_db).expanduser().resolve()


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------

def conectar(caminho_db=None):
    """Abre uma conexão SQLite já configurada para concorrência no WAL.

    Cada chamada devolve uma conexão independente. Quem usar a conexão
    diretamente é responsável por commit/close; para transações com
    rollback automático, use conexao().
    """

    caminho = _resolver_caminho(caminho_db)

    caminho.parent.mkdir(parents=True, exist_ok=True)

    conexao_sqlite = sqlite3.connect(
        str(caminho),
        timeout=TIMEOUT_SEGUNDOS,
    )
    conexao_sqlite.row_factory = sqlite3.Row

    # Os PRAGMAs são aplicados antes de entregar a conexão ao chamador.
    # Se o SQLite recusar algum deles (arquivo bloqueado, modo WAL
    # indisponível, disco somente leitura), a conexão é fechada aqui
    # para não vazar descritor nem deixar o contexto transacional com
    # uma conexão parcialmente configurada.
    try:
        # foreign_keys é uma configuração por conexão: sem isto a cascata
        # declarada no schema não seria aplicada.
        conexao_sqlite.execute("PRAGMA foreign_keys=ON")
        conexao_sqlite.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conexao_sqlite.execute("PRAGMA synchronous=NORMAL")

        # O modo WAL é persistente no arquivo, mas repetir a cada conexão
        # garante que um banco criado por versão anterior entre no modo novo.
        conexao_sqlite.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        conexao_sqlite.close()
        raise

    return conexao_sqlite


@contextmanager
def conexao(caminho_db=None):
    """Context manager transacional com commit, rollback e fechamento."""

    conexao_sqlite = conectar(caminho_db)

    try:
        yield conexao_sqlite
        conexao_sqlite.commit()
    except BaseException:
        conexao_sqlite.rollback()
        raise
    finally:
        conexao_sqlite.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    resumo TEXT NOT NULL DEFAULT '',
    resumo_atualizado_em TEXT,
    resumo_ate_sequencia INTEGER NOT NULL DEFAULT -1,
    metadados_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL
        REFERENCES chat_sessions(id) ON DELETE CASCADE,
    sequencia INTEGER NOT NULL,
    papel TEXT NOT NULL
        CHECK (papel IN ('user', 'assistant', 'system')),
    conteudo TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    resumida_em TEXT,
    tokens_estimados INTEGER,
    veredito TEXT
        CHECK (veredito IS NULL OR veredito IN ('PASS', 'HOLD', 'FAIL')),
    governanca_json TEXT NOT NULL DEFAULT '{}',
    metadados_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (session_id, sequencia)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_sessao
    ON chat_messages(session_id, sequencia);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL DEFAULT '',
    url TEXT,
    autores TEXT,
    publicado_em TEXT,
    coletado_em TEXT NOT NULL,
    hash_conteudo TEXT,
    versao_fonte TEXT,
    metadados_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_evidence_sources_tipo
    ON evidence_sources(tipo);
CREATE INDEX IF NOT EXISTS idx_evidence_sources_hash
    ON evidence_sources(hash_conteudo);

CREATE TABLE IF NOT EXISTS message_evidence (
    message_id INTEGER NOT NULL
        REFERENCES chat_messages(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL
        REFERENCES evidence_sources(id) ON DELETE CASCADE,
    relacao TEXT NOT NULL DEFAULT 'suporte'
        CHECK (relacao IN ('suporte', 'contraprova', 'contexto')),
    trecho TEXT,
    posicao INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    PRIMARY KEY (message_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_message_evidence_evidencia
    ON message_evidence(evidence_id);

CREATE TABLE IF NOT EXISTS claim_records (
    id TEXT PRIMARY KEY,
    message_id INTEGER NOT NULL
        REFERENCES chat_messages(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    classificacao TEXT NOT NULL
        CHECK (classificacao IN ('OBSERVED', 'INFERRED')),
    -- RESTRICT evita apagar uma fonte ainda usada por uma afirmação
    -- OBSERVED; a linhagem não pode desaparecer em silêncio.
    evidence_id TEXT
        REFERENCES evidence_sources(id) ON DELETE RESTRICT,
    veredito TEXT
        CHECK (veredito IS NULL OR veredito IN ('PASS', 'HOLD', 'FAIL')),
    motivo TEXT,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    CHECK (
        (classificacao = 'INFERRED')
        OR (
            classificacao = 'OBSERVED'
            AND evidence_id IS NOT NULL
            AND length(trim(evidence_id)) > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_claim_records_mensagem
    ON claim_records(message_id, ordem);
CREATE INDEX IF NOT EXISTS idx_claim_records_evidencia
    ON claim_records(evidence_id);

CREATE TABLE IF NOT EXISTS spatial_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folha_cim TEXT NOT NULL CHECK (length(trim(folha_cim)) > 0),
    fonte TEXT NOT NULL DEFAULT 'CIM',
    collected_at TEXT NOT NULL,
    source_version TEXT,
    lat REAL,
    lon REAL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    metadados_json TEXT NOT NULL DEFAULT '{}',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    UNIQUE (folha_cim, fonte)
);

CREATE INDEX IF NOT EXISTS idx_spatial_cache_coletado
    ON spatial_cache(collected_at);
CREATE INDEX IF NOT EXISTS idx_spatial_cache_folha
    ON spatial_cache(folha_cim);

-- Manifesto do pacote offline por folha CIM. As linhas de
-- spatial_cache guardam os registros por fonte; esta tabela guarda a
-- identidade do pacote (cim_code, collected_at, source_version, totais)
-- para a consulta e a exportação funcionarem sem rede.
CREATE TABLE IF NOT EXISTS cim_offline_packages (
    folha_cim TEXT PRIMARY KEY CHECK (length(trim(folha_cim)) > 0),
    cim_code TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source_version TEXT NOT NULL,
    total_registros INTEGER NOT NULL DEFAULT 0,
    totais_json TEXT NOT NULL DEFAULT '{}',
    manifesto_json TEXT NOT NULL DEFAULT '{}',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cim_offline_packages_coletado
    ON cim_offline_packages(collected_at);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    nome TEXT,
    caminho TEXT,
    tamanho INTEGER,
    tipo TEXT,
    indexado_em TEXT NOT NULL,
    metadados_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_documents_nome
    ON documents(nome);
"""


def inicializar_banco(caminho_db=None):
    """Cria o schema completo (idempotente) e devolve o caminho usado."""

    caminho = _resolver_caminho(caminho_db)

    with conexao(caminho) as conexao_sqlite:
        conexao_sqlite.executescript(_SQL_SCHEMA)
        conexao_sqlite.execute(
            """
            INSERT INTO schema_meta (chave, valor)
            VALUES ('versao_schema', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (str(VERSAO_SCHEMA),),
        )

    return caminho


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def agora_iso(momento=None):
    """Data/hora local em ISO 8601, com deslocamento de fuso."""

    referencia = momento or datetime.now(timezone.utc)
    return referencia.astimezone().isoformat(timespec="seconds")


def _json_texto(valor, padrao=None):
    """Serializa um objeto JSON com fallback seguro e determinístico."""

    if valor is None:
        valor = {} if padrao is None else padrao

    try:
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({"valor": str(valor)}, ensure_ascii=False)


def _json_objeto(texto, padrao=None):
    """Lê um campo JSON; devolve a estrutura padrão quando inválido."""

    padrao = {} if padrao is None else padrao

    if not texto:
        return padrao

    try:
        valor = json.loads(texto)
    except (TypeError, ValueError):
        return padrao

    return valor


def _linha_sessao(linha):
    """Converte sqlite3.Row de sessão em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["metadados"] = _json_objeto(dados.pop("metadados_json", "{}"))

    return dados


def _linha_mensagem(linha):
    """Converte sqlite3.Row de mensagem em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["metadados"] = _json_objeto(dados.pop("metadados_json", "{}"))
    dados["governanca"] = _json_objeto(
        dados.pop("governanca_json", "{}")
    )

    return dados


def _linha_evidencia(linha):
    """Converte uma fonte de evidência em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["metadados"] = _json_objeto(dados.pop("metadados_json", "{}"))

    return dados


def _linha_afirmacao(linha):
    """Converte uma afirmação em dicionário público."""

    return dict(linha) if linha is not None else None


def _linha_cache(linha):
    """Converte uma entrada de cache espacial em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["payload"] = _json_objeto(dados.pop("payload_json", "{}"))
    dados["metadados"] = _json_objeto(dados.pop("metadados_json", "{}"))

    return dados


def _linha_pacote(linha):
    """Converte uma linha do manifesto offline em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["manifesto"] = _json_objeto(
        dados.pop("manifesto_json", "{}")
    )
    dados["totais_por_fonte"] = _json_objeto(
        dados.pop("totais_json", "{}")
    )

    return dados


def _linha_documento(linha):
    """Converte um documento indexado em dicionário público."""

    if linha is None:
        return None

    dados = dict(linha)
    dados["metadados"] = _json_objeto(dados.pop("metadados_json", "{}"))

    return dados


def _normalizar_titulo(titulo):
    """Título curto, sem quebras de linha, para a lista do histórico."""

    return " ".join(str(titulo or "").split())


def _normalizar_sha256(valor):
    """Valida e normaliza um hash SHA-256 em hexadecimal."""

    texto = str(valor or "").strip().lower()

    if len(texto) != 64 or any(
        caractere not in "0123456789abcdef" for caractere in texto
    ):
        raise ValueError("O hash SHA-256 deve ter 64 caracteres hexadecimais.")

    return texto


# ---------------------------------------------------------------------------
# Camada episódica: sessões
# ---------------------------------------------------------------------------

def criar_sessao(
    session_id=None,
    titulo="",
    metadados=None,
    criado_em=None,
    caminho_db=None,
):
    """Cria uma sessão episódica (idempotente por session_id)."""

    identificador = str(session_id or "").strip() or (
        f"sessao_{uuid.uuid4().hex}"
    )
    momento = criado_em or agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute(
            """
            INSERT INTO chat_sessions (
                id, titulo, criado_em, atualizado_em, metadados_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                identificador,
                _normalizar_titulo(titulo),
                momento,
                momento,
                _json_texto(metadados),
            ),
        )

    return identificador


def obter_sessao(session_id, caminho_db=None):
    """Devolve a sessão com contagem de mensagens, ou None."""

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            """
            SELECT s.*,
                   (
                       SELECT COUNT(*)
                       FROM chat_messages m
                       WHERE m.session_id = s.id
                   ) AS total_mensagens
            FROM chat_sessions s
            WHERE s.id = ?
            """,
            (str(session_id),),
        ).fetchone()

    return _linha_sessao(linha)


def listar_sessoes(limite=50, caminho_db=None):
    """Lista sessões da mais recente para a mais antiga."""

    if not isinstance(limite, int) or limite <= 0:
        raise ValueError("O limite deve ser um inteiro positivo.")

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(
            """
            SELECT s.*,
                   (
                       SELECT COUNT(*)
                       FROM chat_messages m
                       WHERE m.session_id = s.id
                   ) AS total_mensagens
            FROM chat_sessions s
            ORDER BY s.atualizado_em DESC, s.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

    return [_linha_sessao(linha) for linha in linhas]


def atualizar_titulo_sessao(session_id, titulo, caminho_db=None):
    """Atualiza o título e devolve True quando a sessão existe."""

    with conexao(caminho_db) as conexao_sqlite:
        resultado = conexao_sqlite.execute(
            """
            UPDATE chat_sessions
            SET titulo = ?, atualizado_em = ?
            WHERE id = ?
            """,
            (_normalizar_titulo(titulo), agora_iso(), str(session_id)),
        )

    return resultado.rowcount > 0


def atualizar_resumo_sessao(
    session_id,
    resumo,
    ate_sequencia=None,
    caminho_db=None,
):
    """Grava o resumo progressivo e a última sequência coberta.

    ate_sequencia é o índice da última mensagem já resumida. Quando ele
    não é informado, a maior sequência existente é usada, o que facilita
    a chamada depois de uma rodada de compactação.
    """

    momento = agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        if ate_sequencia is None:
            linha = conexao_sqlite.execute(
                """
                SELECT COALESCE(MAX(sequencia), -1) AS ultima
                FROM chat_messages
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
            ate_sequencia = int(linha["ultima"])

        resultado = conexao_sqlite.execute(
            """
            UPDATE chat_sessions
            SET resumo = ?,
                resumo_atualizado_em = ?,
                resumo_ate_sequencia = ?,
                atualizado_em = ?
            WHERE id = ?
            """,
            (
                str(resumo or ""),
                momento,
                int(ate_sequencia),
                momento,
                str(session_id),
            ),
        )

    return resultado.rowcount > 0


def excluir_sessao(session_id, caminho_db=None):
    """Exclui a sessão; a cascata remove mensagens, vínculos e claims."""

    with conexao(caminho_db) as conexao_sqlite:
        resultado = conexao_sqlite.execute(
            "DELETE FROM chat_sessions WHERE id = ?",
            (str(session_id),),
        )

    return resultado.rowcount > 0


# ---------------------------------------------------------------------------
# Camada episódica: mensagens
# ---------------------------------------------------------------------------

def adicionar_mensagem(
    session_id,
    papel,
    conteudo,
    criado_em=None,
    resumida_em=None,
    veredito=None,
    governanca=None,
    metadados=None,
    caminho_db=None,
):
    """Acrescenta uma mensagem e devolve o id inteiro gerado."""

    if papel not in PAPEIS_MENSAGEM:
        raise ValueError(
            "Papel inválido: use 'user', 'assistant' ou 'system'."
        )

    if veredito is not None and veredito not in VEREDITOS:
        raise ValueError("Veredito inválido: use PASS, HOLD ou FAIL.")

    texto = str(conteudo or "")
    momento = criado_em or agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        # Reserva o lock de escrita antes de calcular a próxima sequência:
        # duas sessões do Streamlit não podem receber o mesmo número.
        conexao_sqlite.execute("BEGIN IMMEDIATE")

        linha = conexao_sqlite.execute(
            """
            SELECT COALESCE(MAX(sequencia), -1) + 1 AS proxima
            FROM chat_messages
            WHERE session_id = ?
            """,
            (str(session_id),),
        ).fetchone()
        sequencia = int(linha["proxima"])

        cursor = conexao_sqlite.execute(
            """
            INSERT INTO chat_messages (
                session_id, sequencia, papel, conteudo, criado_em,
                resumida_em, tokens_estimados, veredito,
                governanca_json, metadados_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(session_id),
                sequencia,
                papel,
                texto,
                momento,
                resumida_em,
                max(1, len(texto) // 4),
                veredito,
                _json_texto(governanca),
                _json_texto(metadados),
            ),
        )
        mensagem_id = int(cursor.lastrowid)

        conexao_sqlite.execute(
            """
            UPDATE chat_sessions
            SET atualizado_em = ?
            WHERE id = ?
            """,
            (momento, str(session_id)),
        )

    return mensagem_id


def listar_mensagens(session_id, limite=None, caminho_db=None):
    """Lista mensagens em ordem cronológica, com limite opcional."""

    if limite is not None and (
        not isinstance(limite, int) or limite <= 0
    ):
        raise ValueError("O limite deve ser um inteiro positivo.")

    sql = """
        SELECT *
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY sequencia ASC, id ASC
    """
    parametros = [str(session_id)]

    if limite is not None:
        sql += " LIMIT ?"
        parametros.append(limite)

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(sql, parametros).fetchall()

    return [_linha_mensagem(linha) for linha in linhas]


def marcar_mensagens_resumidas(
    session_id,
    ate_sequencia,
    caminho_db=None,
):
    """Marca até uma sequência como já coberta pelo resumo progressivo."""

    momento = agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        resultado = conexao_sqlite.execute(
            """
            UPDATE chat_messages
            SET resumida_em = ?
            WHERE session_id = ?
              AND sequencia <= ?
              AND resumida_em IS NULL
            """,
            (momento, str(session_id), int(ate_sequencia)),
        )

    return resultado.rowcount


# ---------------------------------------------------------------------------
# Camada de linhagem
# ---------------------------------------------------------------------------

def registrar_evidencia(
    evidence_id=None,
    tipo="documento",
    titulo="",
    url=None,
    autores=None,
    publicado_em=None,
    coletado_em=None,
    hash_conteudo=None,
    versao_fonte=None,
    metadados=None,
    caminho_db=None,
):
    """Registra (ou atualiza) uma fonte de evidência e devolve seu id."""

    identificador = str(evidence_id or "").strip() or (
        f"ev_{uuid.uuid4().hex}"
    )

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute(
            """
            INSERT INTO evidence_sources (
                id, tipo, titulo, url, autores, publicado_em,
                coletado_em, hash_conteudo, versao_fonte, metadados_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tipo = excluded.tipo,
                titulo = excluded.titulo,
                url = excluded.url,
                autores = excluded.autores,
                publicado_em = excluded.publicado_em,
                coletado_em = excluded.coletado_em,
                hash_conteudo = excluded.hash_conteudo,
                versao_fonte = excluded.versao_fonte,
                metadados_json = excluded.metadados_json
            """,
            (
                identificador,
                str(tipo or "documento"),
                str(titulo or ""),
                str(url) if url else None,
                str(autores) if autores else None,
                str(publicado_em) if publicado_em else None,
                coletado_em or agora_iso(),
                str(hash_conteudo) if hash_conteudo else None,
                str(versao_fonte) if versao_fonte else None,
                _json_texto(metadados),
            ),
        )

    return identificador


def obter_evidencia(evidence_id, caminho_db=None):
    """Lê uma fonte de evidência pelo id."""

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            "SELECT * FROM evidence_sources WHERE id = ?",
            (str(evidence_id),),
        ).fetchone()

    return _linha_evidencia(linha)


def vincular_evidencia(
    message_id,
    evidence_id,
    relacao="suporte",
    trecho=None,
    posicao=0,
    caminho_db=None,
):
    """Vincula uma fonte a uma mensagem; idempotente pelo par."""

    if relacao not in ("suporte", "contraprova", "contexto"):
        raise ValueError(
            "Relação inválida: use 'suporte', 'contraprova' ou 'contexto'."
        )

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute(
            """
            INSERT INTO message_evidence (
                message_id, evidence_id, relacao, trecho, posicao, criado_em
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, evidence_id) DO UPDATE SET
                relacao = excluded.relacao,
                trecho = excluded.trecho,
                posicao = excluded.posicao
            """,
            (
                int(message_id),
                str(evidence_id),
                relacao,
                str(trecho) if trecho else None,
                int(posicao),
                agora_iso(),
            ),
        )

    return True


def listar_evidencias_da_mensagem(message_id, caminho_db=None):
    """Lista as fontes vinculadas a uma mensagem."""

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(
            """
            SELECT e.*, me.relacao, me.trecho, me.posicao
            FROM message_evidence me
            JOIN evidence_sources e ON e.id = me.evidence_id
            WHERE me.message_id = ?
            ORDER BY me.posicao ASC, e.id ASC
            """,
            (int(message_id),),
        ).fetchall()

    return [dict(linha) for linha in linhas]


def registrar_afirmacao(
    message_id,
    texto,
    classificacao,
    evidence_id=None,
    veredito=None,
    motivo=None,
    ordem=0,
    claim_id=None,
    caminho_db=None,
):
    """Grava uma afirmação auditável.

    OBSERVED exige evidence_id; a regra é validada aqui e também pelo
    CHECK do schema. INFERRED pode ou não apontar para uma fonte de
    contexto.
    """

    classificacao = str(classificacao or "").strip().upper()

    if classificacao not in CLASSIFICACOES_AFIRMACAO:
        raise ValueError(
            "Classificação inválida: use OBSERVED ou INFERRED."
        )

    if veredito is not None and veredito not in VEREDITOS:
        raise ValueError("Veredito inválido: use PASS, HOLD ou FAIL.")

    evidence_id = str(evidence_id or "").strip() or None

    if classificacao == "OBSERVED" and evidence_id is None:
        raise ValueError("Afirmação OBSERVED exige um evidence_id.")

    identificador = str(claim_id or "").strip() or (
        f"cl_{uuid.uuid4().hex}"
    )

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute(
            """
            INSERT INTO claim_records (
                id, message_id, texto, classificacao, evidence_id,
                veredito, motivo, ordem, criado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identificador,
                int(message_id),
                str(texto or ""),
                classificacao,
                evidence_id,
                veredito,
                str(motivo) if motivo else None,
                int(ordem),
                agora_iso(),
            ),
        )

    return identificador


def listar_afirmacoes(message_id, caminho_db=None):
    """Lista as afirmações de uma mensagem, na ordem gravada."""

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(
            """
            SELECT *
            FROM claim_records
            WHERE message_id = ?
            ORDER BY ordem ASC, id ASC
            """,
            (int(message_id),),
        ).fetchall()

    return [_linha_afirmacao(linha) for linha in linhas]


# ---------------------------------------------------------------------------
# Camada operacional: cache espacial
# ---------------------------------------------------------------------------

def salvar_cache_espacial(
    folha_cim,
    payload,
    collected_at=None,
    source_version=None,
    fonte="CIM",
    lat=None,
    lon=None,
    metadados=None,
    caminho_db=None,
):
    """Grava/atualiza o cache de uma folha CIM e devolve o id."""

    folha = str(folha_cim or "").strip().upper()

    if not folha:
        raise ValueError("A folha CIM é obrigatória.")

    momento = agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        # BEGIN IMMEDIATE reserva o lock de escrita antes do UPSERT. No
        # Windows, dois reruns do Streamlit podem disputar o arquivo; sem
        # esta reserva o SQLite promove um lock de leitura a escrita no
        # meio da transação e devolve "database is locked".
        conexao_sqlite.execute("BEGIN IMMEDIATE")
        conexao_sqlite.execute(
            """
            INSERT INTO spatial_cache (
                folha_cim, fonte, collected_at, source_version,
                lat, lon, payload_json, metadados_json,
                criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(folha_cim, fonte) DO UPDATE SET
                collected_at = excluded.collected_at,
                source_version = excluded.source_version,
                lat = excluded.lat,
                lon = excluded.lon,
                payload_json = excluded.payload_json,
                metadados_json = excluded.metadados_json,
                atualizado_em = excluded.atualizado_em
            """,
            (
                folha,
                str(fonte or "CIM"),
                collected_at or momento,
                str(source_version) if source_version else None,
                float(lat) if lat is not None else None,
                float(lon) if lon is not None else None,
                _json_texto(payload),
                _json_texto(metadados),
                momento,
                momento,
            ),
        )

        linha = conexao_sqlite.execute(
            """
            SELECT id
            FROM spatial_cache
            WHERE folha_cim = ? AND fonte = ?
            """,
            (folha, str(fonte or "CIM")),
        ).fetchone()

    return int(linha["id"])


def obter_cache_espacial(folha_cim, fonte=None, caminho_db=None):
    """Lê o cache de uma folha (todas as fontes ou uma específica)."""

    folha = str(folha_cim or "").strip().upper()

    sql = "SELECT * FROM spatial_cache WHERE folha_cim = ?"
    parametros = [folha]

    if fonte is not None:
        sql += " AND fonte = ?"
        parametros.append(str(fonte))

    sql += " ORDER BY atualizado_em DESC, id DESC"

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(sql, parametros).fetchall()

    return [_linha_cache(linha) for linha in linhas]


def salvar_pacote_offline_cim(
    manifesto,
    fontes,
    caminho_db=None,
):
    """Grava o manifesto e os registros por fonte de uma folha CIM.

    A gravação é atômica: o manifesto e todas as linhas de
    ``spatial_cache`` entram em um único ``BEGIN IMMEDIATE``. Uma
    atualização substitui o snapshot anterior da folha, de modo que uma
    fonte removida do pacote também desaparece do cache offline.

    ``manifesto`` é o dicionário devolvido por
    ``adapters.spatial_cim.montar_pacote_offline``; ``fontes`` mapeia
    o nome da fonte para ``{"total": n, "registros": [...]}``.
    """

    if not isinstance(manifesto, dict):
        raise TypeError("O manifesto do pacote precisa ser um dicionário.")

    folha = str(
        manifesto.get("cim_code")
        or manifesto.get("folha_cim")
        or ""
    ).strip().upper()

    if not folha:
        raise ValueError("A folha CIM do pacote é obrigatória.")

    agora = agora_iso()
    collected_at = str(manifesto.get("collected_at") or agora)
    source_version = str(manifesto.get("source_version") or "local")
    totais = dict(manifesto.get("totais_por_fonte") or {})

    linhas = []

    for fonte, entrada in (fontes or {}).items():
        if not isinstance(entrada, dict):
            continue

        registros = entrada.get("registros") or []
        total = len(registros)

        if fonte not in totais:
            totais[fonte] = total

        linhas.append(
            (
                folha,
                str(fonte),
                collected_at,
                source_version,
                _json_texto({"registros": registros}),
                {
                    "total": total,
                    "cim_code": folha,
                },
            )
        )

    manifesto_atualizado = dict(manifesto)
    manifesto_atualizado["cim_code"] = folha
    manifesto_atualizado["folha_cim"] = folha
    manifesto_atualizado["collected_at"] = collected_at
    manifesto_atualizado["source_version"] = source_version
    manifesto_atualizado["totais_por_fonte"] = totais
    manifesto_atualizado["total_registros"] = int(
        sum(int(valor) for valor in totais.values())
    )

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute("BEGIN IMMEDIATE")

        conexao_sqlite.execute(
            """
            INSERT INTO cim_offline_packages (
                folha_cim, cim_code, collected_at, source_version,
                total_registros, totais_json, manifesto_json,
                criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(folha_cim) DO UPDATE SET
                cim_code = excluded.cim_code,
                collected_at = excluded.collected_at,
                source_version = excluded.source_version,
                total_registros = excluded.total_registros,
                totais_json = excluded.totais_json,
                manifesto_json = excluded.manifesto_json,
                atualizado_em = excluded.atualizado_em
            """,
            (
                folha,
                str(manifesto_atualizado.get("cim_code") or folha),
                collected_at,
                source_version,
                int(manifesto_atualizado["total_registros"]),
                _json_texto(totais),
                _json_texto(manifesto_atualizado),
                agora,
                agora,
            ),
        )

        # O snapshot é substituído por inteiro: fontes que saíram do
        # pacote não podem continuar respondendo a uma consulta offline.
        conexao_sqlite.execute(
            "DELETE FROM spatial_cache WHERE folha_cim = ?",
            (folha,),
        )

        for (
            folha_linha,
            fonte,
            coletado,
            versao,
            payload_json,
            metadados,
        ) in linhas:
            conexao_sqlite.execute(
                """
                INSERT INTO spatial_cache (
                    folha_cim, fonte, collected_at, source_version,
                    lat, lon, payload_json, metadados_json,
                    criado_em, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folha_linha,
                    fonte,
                    coletado,
                    versao,
                    manifesto_atualizado.get("lat"),
                    manifesto_atualizado.get("lon"),
                    payload_json,
                    _json_texto(metadados),
                    agora,
                    agora,
                ),
            )

    return obter_pacote_offline_cim(folha, caminho_db=caminho_db)


def obter_pacote_offline_cim(folha_cim, caminho_db=None):
    """Lê o manifesto e as fontes de um pacote offline.

    Devolve ``None`` quando a folha nunca foi baixada. O retorno tem a
    forma ``{"manifesto": {...}, "fontes": [...]}``, com o payload de
    cada fonte já desserializado.
    """

    folha = str(folha_cim or "").strip().upper()

    if not folha:
        return None

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            """
            SELECT *
            FROM cim_offline_packages
            WHERE folha_cim = ?
            """,
            (folha,),
        ).fetchone()

        if linha is None:
            return None

        registros = conexao_sqlite.execute(
            """
            SELECT *
            FROM spatial_cache
            WHERE folha_cim = ?
            ORDER BY fonte ASC, id ASC
            """,
            (folha,),
        ).fetchall()

    pacote = _linha_pacote(linha)
    manifesto = pacote["manifesto"] or {}
    manifesto.setdefault("cim_code", folha)
    manifesto.setdefault("folha_cim", folha)
    manifesto.setdefault("collected_at", pacote["collected_at"])
    manifesto.setdefault("source_version", pacote["source_version"])
    manifesto.setdefault("total_registros", pacote["total_registros"])
    manifesto.setdefault("totais_por_fonte", pacote["totais_por_fonte"])

    fontes = []

    for registro in registros:
        dados = _linha_cache(registro)
        fontes.append(
            {
                "fonte": dados["fonte"],
                "total": int(
                    (dados.get("metadados") or {}).get("total")
                    or len((dados.get("payload") or {}).get("registros") or [])
                ),
                "collected_at": dados["collected_at"],
                "source_version": dados["source_version"],
                "payload": dados.get("payload") or {},
            }
        )

    return {
        "manifesto": manifesto,
        "fontes": fontes,
    }


def pacote_offline_disponivel(folha_cim, caminho_db=None):
    """Diz se a folha tem pacote offline gravado no SQLite."""

    folha = str(folha_cim or "").strip().upper()

    if not folha:
        return False

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            """
            SELECT 1 AS disponivel
            FROM cim_offline_packages
            WHERE folha_cim = ?
            LIMIT 1
            """,
            (folha,),
        ).fetchone()

    return linha is not None


def listar_pacotes_offline_cim(caminho_db=None):
    """Lista os manifestos offline, do mais recente para o mais antigo."""

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(
            """
            SELECT *
            FROM cim_offline_packages
            ORDER BY atualizado_em DESC, folha_cim ASC
            """
        ).fetchall()

    return [_linha_pacote(linha) for linha in linhas]


def remover_pacote_offline_cim(folha_cim, caminho_db=None):
    """Remove o manifesto e as linhas de cache de uma folha.

    Devolve ``True`` quando havia algo para remover. A operação usa
    ``BEGIN IMMEDIATE`` para que manifesto e cache saiam juntos.
    """

    folha = str(folha_cim or "").strip().upper()

    if not folha:
        return False

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute("BEGIN IMMEDIATE")
        pacote = conexao_sqlite.execute(
            "DELETE FROM cim_offline_packages WHERE folha_cim = ?",
            (folha,),
        ).rowcount
        conexao_sqlite.execute(
            "DELETE FROM spatial_cache WHERE folha_cim = ?",
            (folha,),
        )

    return bool(pacote)



# ---------------------------------------------------------------------------
# Camada operacional: índice de documentos por hash
# ---------------------------------------------------------------------------

def registrar_documento(
    sha256,
    nome=None,
    caminho=None,
    tamanho=None,
    tipo=None,
    metadados=None,
    indexado_em=None,
    caminho_db=None,
):
    """Indexa um documento por SHA-256; reindexar atualiza os metadados."""

    hash_normalizado = _normalizar_sha256(sha256)
    momento = indexado_em or agora_iso()

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute("BEGIN IMMEDIATE")
        conexao_sqlite.execute(
            """
            INSERT INTO documents (
                sha256, nome, caminho, tamanho, tipo,
                indexado_em, metadados_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
                nome = excluded.nome,
                caminho = excluded.caminho,
                tamanho = excluded.tamanho,
                tipo = excluded.tipo,
                indexado_em = excluded.indexado_em,
                metadados_json = excluded.metadados_json
            """,
            (
                hash_normalizado,
                str(nome) if nome else None,
                str(caminho) if caminho else None,
                int(tamanho) if tamanho is not None else None,
                str(tipo) if tipo else None,
                momento,
                _json_texto(metadados),
            ),
        )

    return hash_normalizado


def obter_documento_por_hash(sha256, caminho_db=None):
    """Busca um documento pelo hash, sem carregar o conteúdo."""

    try:
        hash_normalizado = _normalizar_sha256(sha256)
    except ValueError:
        return None

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            "SELECT * FROM documents WHERE sha256 = ?",
            (hash_normalizado,),
        ).fetchone()

    return _linha_documento(linha)


def listar_documentos(limite=100, caminho_db=None):
    """Lista os documentos indexados, do mais recente para o mais antigo."""

    if not isinstance(limite, int) or limite <= 0:
        raise ValueError("O limite deve ser um inteiro positivo.")

    with conexao(caminho_db) as conexao_sqlite:
        linhas = conexao_sqlite.execute(
            """
            SELECT *
            FROM documents
            ORDER BY indexado_em DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

    return [_linha_documento(linha) for linha in linhas]


# ---------------------------------------------------------------------------
# Conversa completa: gravação atômica e limpeza em lote
# ---------------------------------------------------------------------------

def substituir_conversa(
    session_id,
    titulo,
    mensagens,
    metadados=None,
    criado_em=None,
    caminho_db=None,
):
    """Grava a conversa inteira em uma única transação.

    A operação apaga as mensagens da sessão e reinsere a lista recebida
    dentro de um BEGIN IMMEDIATE: ou a conversa fica inteira, ou o
    estado anterior permanece. É o caminho usado pelo autosave da
    interface D1, que antes reescrevia o arquivo JSON completo.

    mensagens aceita dicionários com papel/role, conteudo/content,
    governanca, veredito e metadados. As demais chaves do chamador
    ficam fora do SQLite, porque a serialização de linhagem é
    responsabilidade da camada de histórico.

    Devolve a quantidade de mensagens gravadas.
    """

    identificador = str(session_id or "").strip()

    if not identificador:
        raise ValueError("O id da sessão é obrigatório.")

    momento = agora_iso()
    registros = []

    for sequencia, mensagem in enumerate(mensagens or ()):
        if not isinstance(mensagem, dict):
            raise TypeError(
                "Cada mensagem precisa ser um dicionário."
            )

        papel = mensagem.get("papel") or mensagem.get("role")

        if papel not in PAPEIS_MENSAGEM:
            raise ValueError(
                "Papel inválido: use 'user', 'assistant' ou 'system'."
            )

        conteudo = mensagem.get("conteudo")

        if conteudo is None:
            conteudo = mensagem.get("content")

        governanca = mensagem.get("governanca")
        veredito = mensagem.get("veredito")

        if veredito is None and isinstance(governanca, dict):
            veredito = governanca.get("veredito")

        if veredito is not None:
            veredito = str(veredito).strip().upper()

            if veredito not in VEREDITOS:
                veredito = None

        texto = str(conteudo or "")
        registros.append(
            (
                identificador,
                int(sequencia),
                str(papel),
                texto,
                str(mensagem.get("criado_em") or momento),
                mensagem.get("resumida_em"),
                max(1, len(texto) // 4),
                veredito,
                _json_texto(
                    governanca if isinstance(governanca, dict) else None
                ),
                _json_texto(mensagem.get("metadados")),
            )
        )

    titulo_normalizado = _normalizar_titulo(titulo)
    criado = criado_em or momento

    with conexao(caminho_db) as conexao_sqlite:
        # Reserva o lock antes de apagar e reinserir: outra sessão do
        # Streamlit nunca lê a conversa pela metade.
        conexao_sqlite.execute("BEGIN IMMEDIATE")

        conexao_sqlite.execute(
            """
            INSERT INTO chat_sessions (
                id, titulo, criado_em, atualizado_em, metadados_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                titulo = excluded.titulo,
                atualizado_em = excluded.atualizado_em,
                metadados_json = excluded.metadados_json
            """,
            (
                identificador,
                titulo_normalizado,
                str(criado),
                momento,
                _json_texto(metadados),
            ),
        )

        conexao_sqlite.execute(
            "DELETE FROM chat_messages WHERE session_id = ?",
            (identificador,),
        )

        if registros:
            conexao_sqlite.executemany(
                """
                INSERT INTO chat_messages (
                    session_id, sequencia, papel, conteudo, criado_em,
                    resumida_em, tokens_estimados, veredito,
                    governanca_json, metadados_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                registros,
            )

    return len(registros)


def excluir_todas_sessoes(caminho_db=None):
    """Apaga todas as sessões em uma transação e devolve a quantidade.

    A cascata do schema remove mensagens, vínculos de evidência e
    afirmações; as fontes de evidência em si são preservadas.
    """

    with conexao(caminho_db) as conexao_sqlite:
        conexao_sqlite.execute("BEGIN IMMEDIATE")
        total = int(
            conexao_sqlite.execute(
                "SELECT COUNT(*) AS total FROM chat_sessions"
            ).fetchone()["total"]
        )
        conexao_sqlite.execute("DELETE FROM chat_sessions")

    return total


def contar_folhas_cache(caminho_db=None):
    """Quantidade de folhas CIM distintas no cache espacial."""

    with conexao(caminho_db) as conexao_sqlite:
        linha = conexao_sqlite.execute(
            """
            SELECT COUNT(DISTINCT folha_cim) AS total
            FROM spatial_cache
            """
        ).fetchone()

    return int(linha["total"])


# ---------------------------------------------------------------------------
# Diagnóstico rápido da memória
# ---------------------------------------------------------------------------

def resumo_memoria(caminho_db=None):
    """Contagens por camada, úteis para o dashboard e para os testes."""

    with conexao(caminho_db) as conexao_sqlite:
        def contar(tabela):
            return int(
                conexao_sqlite.execute(
                    f"SELECT COUNT(*) AS total FROM {tabela}"
                ).fetchone()["total"]
            )

        modo = conexao_sqlite.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]

        return {
            "journal_mode": str(modo).lower(),
            "sessoes": contar("chat_sessions"),
            "mensagens": contar("chat_messages"),
            "evidencias": contar("evidence_sources"),
            "vinculos": contar("message_evidence"),
            "afirmacoes": contar("claim_records"),
            "cache_espacial": contar("spatial_cache"),
            "pacotes_offline": contar("cim_offline_packages"),
            "documentos": contar("documents"),
        }
