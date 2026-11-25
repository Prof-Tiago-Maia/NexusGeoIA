"""Aba 1 (Consulta & Evidência): workflow, cartão e proveniência (D1).

Este módulo concentra a superfície de consulta da Fase D1:

* seletor explícito de workflow, antes do envio da pergunta;
* cartão de resposta com badges de governança (OBSERVED/INFERRED e
  veredito PASS/HOLD/FAIL) e o motivo objetivo do veredito;
* gaveta de proveniência com a tabela estruturada de linhagem
  (source_type, locator, retrieved_at e origem Live/Cache Offline).

O módulo não fala com o banco nem com o Ollama: recebe a resposta, o
resultado de ``core.governance`` e os metadados já gravados na
mensagem. Os textos visíveis vêm de ``utils.i18n``; os nomes das
fontes externas são nomes próprios preservados nos dois idiomas.
"""

from __future__ import annotations

from ui import governanca as ui_governanca
from utils.i18n import t, tf

# ---------------------------------------------------------------------------
# Workflow explícito da consulta
# ---------------------------------------------------------------------------

WORKFLOW_CONSULTA_DIRETA = "consulta_direta"
WORKFLOW_TRIAGEM_AREA = "triagem_area"
WORKFLOW_HIDROGEOLOGIA = "hidrogeologia"
WORKFLOW_SONDAGEM = "sondagem"

WORKFLOWS = (
    (WORKFLOW_CONSULTA_DIRETA, "workflow_consulta_direta"),
    (WORKFLOW_TRIAGEM_AREA, "workflow_triagem_area"),
    (WORKFLOW_HIDROGEOLOGIA, "workflow_hidrogeologia"),
    (WORKFLOW_SONDAGEM, "workflow_sondagem"),
)

WORKFLOW_PADRAO = WORKFLOW_CONSULTA_DIRETA

# Campo de sessão que guarda o rótulo exibido pelo selectbox. O valor
# canônico (chave estável, em português) é derivado dele a cada rerun,
# como já acontece com o perfil analítico e com as regiões.
CHAVE_WORKFLOW = "workflow_consulta"


def rotulo_workflow(chave, idioma=None):
    """Rótulo traduzido do workflow; chave desconhecida cai no padrão."""

    for codigo, chave_i18n in WORKFLOWS:
        if codigo == chave:
            return t(chave_i18n, idioma)

    return t("workflow_consulta_direta", idioma)


def workflow_do_rotulo(rotulo):
    """Converte o rótulo exibido (pt ou en) na chave canônica."""

    for codigo, chave_i18n in WORKFLOWS:
        if rotulo in (t(chave_i18n, "pt"), t(chave_i18n, "en")):
            return codigo

    return None


def definir_workflow(chave):
    """Deixa o seletor alinhado a uma conversa reaberta do histórico."""

    import streamlit as st

    st.session_state[CHAVE_WORKFLOW] = rotulo_workflow(chave or WORKFLOW_PADRAO)


_CHAVES_INSTRUCAO = {
    WORKFLOW_CONSULTA_DIRETA: "workflow_instrucao_consulta_direta",
    WORKFLOW_TRIAGEM_AREA: "workflow_instrucao_triagem_area",
    WORKFLOW_HIDROGEOLOGIA: "workflow_instrucao_hidrogeologia",
    WORKFLOW_SONDAGEM: "workflow_instrucao_sondagem",
}


def instrucao_workflow(chave, idioma=None):
    """Instrução curta do workflow, anexada ao system prompt do turno.

    A escolha deixa de ser apenas visual: o fluxo orienta a estrutura da
    resposta sem tocar nas regras de fonte nem na governança.
    """

    chave_i18n = _CHAVES_INSTRUCAO.get(
        chave or WORKFLOW_PADRAO,
        _CHAVES_INSTRUCAO[WORKFLOW_PADRAO],
    )

    return t(chave_i18n, idioma)


def renderizar_seletor_workflow():
    """Selectbox determinístico e devolve a chave canônica do workflow.

    O estado da sessão guarda o rótulo no idioma ativo (o widget
    devolve rótulos), mas o restante da aplicação — histórico, cartão da
    resposta e persistência — usa sempre a chave canônica em português.
    """

    import streamlit as st

    opcoes = [rotulo_workflow(codigo) for codigo, _ in WORKFLOWS]
    atual = st.session_state.get(CHAVE_WORKFLOW)
    canonico = workflow_do_rotulo(atual) or WORKFLOW_PADRAO

    # Normaliza antes de criar o widget: um idioma novo renomeia as
    # opções e a seleção anterior continuaria válida.
    st.session_state[CHAVE_WORKFLOW] = rotulo_workflow(canonico)

    escolhido = st.selectbox(
        t("workflow_titulo"),
        opcoes,
        key=CHAVE_WORKFLOW,
        help=t("workflow_ajuda"),
    )

    chave = workflow_do_rotulo(escolhido) or WORKFLOW_PADRAO
    st.caption(tf("workflow_caption", workflow=rotulo_workflow(chave)))

    return chave


# ---------------------------------------------------------------------------
# Proveniência (linhagem da resposta)
# ---------------------------------------------------------------------------

# (chave em dados, campo equivalente na mensagem, rótulo da fonte). A
# ordem é a mesma do restante da interface e do parecer técnico.
FONTES_PROVENIENCIA = (
    ("ana", "estacoes_ana", "ANA / HidroWeb"),
    ("sgb", "artigos_rigeo", "RIGeo / SGB"),
    ("web", "web", "Pesquisa na Web"),
    ("openalex", "openalex", "OpenAlex"),
    ("usgs", "usgs", "USGS ScienceBase"),
    ("intl_geo", "intl_geo", "Serviços Geológicos Internacionais"),
    ("geosgb", "geosgb", "GeoSGB / SGB"),
    ("anm", "anm", "ANM / SIGMINE"),
    ("macrostrat", "macrostrat", "Macrostrat"),
    ("siagas", "siagas", "SIAGAS / RIMAS"),
    ("geossit", "geossit", "INDE / GEOSSIT"),
)

ORIGEM_LIVE = "live"
ORIGEM_CACHE = "cache"
ORIGEM_LOCAL = "local"

# Limite de linhas por resposta: a gaveta é um resumo auditável, não
# uma cópia completa das tabelas já exibidas no expander de fontes.
LIMITE_PROVENIENCIA = 60


def rotulo_origem(origem, idioma=None):
    """Tradução de live/cache/local para a coluna origem."""

    chaves = {
        ORIGEM_LIVE: "proveniencia_origem_live",
        ORIGEM_CACHE: "proveniencia_origem_cache",
        ORIGEM_LOCAL: "proveniencia_origem_local",
    }

    return t(chaves.get(origem, "proveniencia_origem_live"), idioma)


def _registros(valor):
    """Lista de registros de um grupo de dados ou de um campo do histórico."""

    if isinstance(valor, list):
        return [item for item in valor if isinstance(item, dict)]

    if isinstance(valor, dict):
        return [
            item
            for item in (valor.get("registros") or [])
            if isinstance(item, dict)
        ]

    return []


def _localizador(registro):
    """URL, código ou título mais estável do registro."""

    for campo in (
        "link",
        "link_pdf",
        "doi",
        "processo",
        "codigo",
        "titulo",
        "nome",
        "arquivo",
    ):
        valor = registro.get(campo)

        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    return ""


def _coletado(registro, grupo_coletado, padrao):
    """Data de coleta do registro, do grupo ou da mensagem."""

    for valor in (
        registro.get("coletado_em"),
        registro.get("retrieved_at"),
        registro.get("data_coleta"),
        grupo_coletado,
        padrao,
    ):
        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    return ""


def _cache_do_grupo(grupo):
    """Indica se o grupo veio do cache offline do conector."""

    if not isinstance(grupo, dict):
        return False

    cache = grupo.get("cache")

    if isinstance(cache, dict) and cache.get("usado"):
        return True

    return str(grupo.get("origem") or "").strip().lower() == "cache"


def montar_proveniencia(
    dados=None,
    documentos=None,
    roteamento=None,
    criado_em="",
    limite=LIMITE_PROVENIENCIA,
):
    """Monta as linhas auditáveis de proveniência de uma resposta.

    ``dados`` é o dicionário devolvido por ``core.assistant.responder``
    (ou uma reconstrução a partir da mensagem gravada). Cada linha tem
    as quatro colunas do contrato: source_type, locator, retrieved_at e
    origem (live, cache ou local). O resultado é estável e sem
    consultas: só reorganiza o que já veio das fontes.
    """

    dados = dados if isinstance(dados, dict) else {}
    roteamento = roteamento if isinstance(roteamento, dict) else {}
    linhas = []

    for chave, _campo, rotulo in FONTES_PROVENIENCIA:
        grupo = dados.get(chave)
        registros = _registros(grupo)
        grupo_coletado = None

        if isinstance(grupo, dict):
            grupo_coletado = (
                grupo.get("coletado_em") or grupo.get("consultado_em")
            )

        cache = _cache_do_grupo(grupo)

        for registro in registros:
            registro_cache = cache or (
                str(registro.get("origem") or "").strip().lower()
                == "cache"
            )

            linhas.append({
                "source_type": rotulo,
                "locator": _localizador(registro),
                "retrieved_at": _coletado(
                    registro,
                    grupo_coletado,
                    criado_em,
                ),
                "origem": ORIGEM_CACHE if registro_cache else ORIGEM_LIVE,
            })

    nomes_documentos = documentos

    if nomes_documentos is None:
        nomes_documentos = roteamento.get("documentos_locais") or []

    for documento in nomes_documentos or ():
        nome = documento

        if isinstance(documento, dict):
            nome = (
                documento.get("nome")
                or documento.get("titulo")
                or documento.get("arquivo")
            )

        nome = str(nome or "").strip()

        if not nome:
            continue

        linhas.append({
            "source_type": "Base Documental Local",
            "locator": nome,
            "retrieved_at": str(criado_em or ""),
            "origem": ORIGEM_LOCAL,
        })

    if isinstance(limite, int) and limite > 0:
        return linhas[:limite]

    return linhas


def normalizar_proveniencia(linhas):
    """Valida linhas já persistidas, preservando apenas o contrato."""

    normalizadas = []

    for linha in linhas or ():
        if not isinstance(linha, dict):
            continue

        origem = str(linha.get("origem") or ORIGEM_LIVE).lower()

        if origem not in (ORIGEM_LIVE, ORIGEM_CACHE, ORIGEM_LOCAL):
            origem = ORIGEM_LIVE

        normalizadas.append({
            "source_type": str(linha.get("source_type") or ""),
            "locator": str(linha.get("locator") or ""),
            "retrieved_at": str(linha.get("retrieved_at") or ""),
            "origem": origem,
        })

    return normalizadas


def proveniencia_da_mensagem(mensagem):
    """Recupera a proveniência gravada ou a reconstrói da mensagem antiga."""

    if not isinstance(mensagem, dict):
        return []

    gravada = mensagem.get("proveniencia")

    if isinstance(gravada, list) and gravada:
        return normalizar_proveniencia(gravada)

    dados = {}

    for chave, campo, _rotulo in FONTES_PROVENIENCIA:
        valor = mensagem.get(campo)

        if valor:
            dados[chave] = valor

    return montar_proveniencia(
        dados=dados,
        roteamento=mensagem.get("roteamento") or {},
        criado_em=mensagem.get("criado_em") or "",
    )


def renderizar_gaveta_proveniencia(linhas, chave=""):
    """Expander com a tabela estruturada de proveniência."""

    linhas = normalizar_proveniencia(linhas)

    if not linhas:
        return

    import streamlit as st

    opcoes = {"expanded": False, "icon": ":material/receipt_long:"}

    if chave:
        opcoes["key"] = f"proveniencia_{chave}"

    with st.expander(t("proveniencia_expander"), **opcoes):
        st.caption(tf("proveniencia_contagem", n=len(linhas)))
        st.caption(t("proveniencia_ajuda"))

        tabela = [
            {
                "source_type": linha["source_type"],
                "locator": linha["locator"],
                "retrieved_at": linha["retrieved_at"],
                "origem": rotulo_origem(linha["origem"]),
            }
            for linha in linhas
        ]

        st.dataframe(
            tabela,
            hide_index=True,
            width="stretch",
            column_config={
                "source_type": st.column_config.TextColumn(
                    "source_type",
                    width="medium",
                ),
                "locator": st.column_config.TextColumn(
                    "locator",
                    width="large",
                ),
                "retrieved_at": st.column_config.TextColumn(
                    "retrieved_at",
                    width="medium",
                ),
                "origem": st.column_config.TextColumn(
                    "origem",
                    width="small",
                ),
            },
        )


def renderizar_cartao_resposta(
    resposta,
    governanca=None,
    workflow=None,
    chave="",
):
    """Cartão da resposta: workflow, governança e texto em Markdown.

    O veredito vem de ``core.governance`` (via ``ui.governanca``) e
    nunca inclui traceback: o motivo é o texto objetivo devolvido pelo
    contrato. ``governanca`` pode ser ``ResultadoGovernanca`` ou o
    dicionário persistido na mensagem.
    """

    import streamlit as st

    resumo = ui_governanca.resumir(governanca)
    opcoes = {"border": True}

    if chave:
        opcoes["key"] = f"cartao_resposta_{chave}"

    with st.container(**opcoes):
        if workflow:
            st.badge(
                tf("workflow_badge", workflow=rotulo_workflow(workflow)),
                color="blue",
                icon=":material/alt_route:",
            )

        if resumo is not None:
            ui_governanca.renderizar_badges(resumo)

        st.markdown(str(resposta or ""))

        if resumo is not None:
            ui_governanca.renderizar_detalhe(resumo, chave)