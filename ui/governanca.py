"""Renderização leve da governança da resposta (Fase D1).

O contrato de saída é validado por ``core.governance``; este módulo
apenas transforma o resultado em elementos visuais determinísticos:

* veredito PASS (verde), HOLD (âmbar) e FAIL (vermelho);
* contagem de afirmações OBSERVED e INFERRED;
* motivo objetivo do veredito, sempre sem traceback;
* tabela opcional das afirmações auditáveis com o ``evidence_id``.

Todos os textos visíveis vêm de ``utils.i18n``; os únicos literais
são os códigos técnicos do contrato (PASS, HOLD, FAIL, OBSERVED,
INFERRED e evidence_id), que não são traduzidos de propósito.

O módulo é importável fora do Streamlit: as funções puras
(``resumir``, ``cor_veredito``, ``rotulo_veredito``) não tocam no
runtime da interface.
"""

from __future__ import annotations

from core.governance import normalizar_veredito
from utils.i18n import t, tf

COR_VEREDITO = {
    "PASS": "green",
    "HOLD": "orange",
    "FAIL": "red",
}

ICONE_VEREDITO = {
    "PASS": ":material/check_circle:",
    "HOLD": ":material/pause_circle:",
    "FAIL": ":material/error:",
}

CLASSIFICACOES = ("OBSERVED", "INFERRED")


def _dados(resultado):
    """Normaliza ResultadoGovernanca, dicionário ou None em dicionário."""

    if resultado is None:
        return None

    if hasattr(resultado, "para_dict"):
        try:
            dados = resultado.para_dict()
        except Exception:  # noqa: BLE001 - contrato externo imprevisível
            return None
    elif isinstance(resultado, dict):
        dados = resultado
    else:
        return None

    return dados if isinstance(dados, dict) else None


def _afirmacoes(dados):
    """Lista normalizada de afirmações auditáveis."""

    normalizadas = []

    for item in dados.get("afirmacoes") or ():
        if not isinstance(item, dict):
            continue

        classificacao = str(item.get("classificacao") or "INFERRED").upper()

        if classificacao not in CLASSIFICACOES:
            classificacao = "INFERRED"

        normalizadas.append({
            "texto": str(item.get("texto") or ""),
            "classificacao": classificacao,
            "evidence_id": item.get("evidence_id"),
            "motivo": item.get("motivo"),
        })

    return normalizadas


def resumir(resultado):
    """Resumo estável do estado de governança para a interface e testes.

    Devolve ``None`` quando não há resultado. O veredito nunca é
    inventado: um valor ausente ou inválido cai em HOLD, a mesma regra
    conservadora de ``core.governance``.
    """

    dados = _dados(resultado)

    if dados is None:
        return None

    veredito = normalizar_veredito(dados.get("veredito")) or "HOLD"
    afirmacoes = _afirmacoes(dados)

    return {
        "veredito": veredito,
        "motivo": str(dados.get("motivo") or ""),
        "motivo_codigo": str(dados.get("motivo_codigo") or ""),
        "observed": sum(
            1 for item in afirmacoes
            if item["classificacao"] == "OBSERVED"
        ),
        "inferred": sum(
            1 for item in afirmacoes
            if item["classificacao"] == "INFERRED"
        ),
        "afirmacoes": afirmacoes,
        "avisos": [str(aviso) for aviso in dados.get("avisos") or ()],
        "formato": str(dados.get("formato") or ""),
    }


def cor_veredito(veredito):
    """Cor do badge do veredito (verde, âmbar ou vermelho)."""

    return COR_VEREDITO.get(normalizar_veredito(veredito) or "HOLD", "orange")


def rotulo_veredito(veredito, idioma=None):
    """Rótulo traduzido do veredito, com o código técnico preservado."""

    codigo = normalizar_veredito(veredito) or "HOLD"

    return t(f"governanca_veredito_{codigo.lower()}", idioma)


def renderizar_badges(resumo):
    """Desenha os badges do veredito e das classificações."""

    if not resumo:
        return

    import streamlit as st

    veredito = resumo["veredito"]
    motivo = resumo.get("motivo") or ""
    ajuda = " · ".join(parte for parte in (rotulo_veredito(veredito), motivo) if parte)

    st.badge(
        veredito,
        color=cor_veredito(veredito),
        icon=ICONE_VEREDITO.get(veredito, ":material/shield:"),
        help=f"{ajuda}. {t('governanca_ajuda')}",
    )

    st.badge(
        tf("governanca_badge_observed", n=resumo.get("observed", 0)),
        color="blue",
        icon=":material/fact_check:",
    )

    st.badge(
        tf("governanca_badge_inferred", n=resumo.get("inferred", 0)),
        color="gray",
        icon=":material/lightbulb:",
    )

    if motivo:
        st.caption(tf("governanca_motivo", motivo=motivo))


def renderizar_detalhe(resumo, chave=""):
    """Tabela opcional das afirmações auditáveis, em um expander."""

    if not resumo:
        return

    import streamlit as st

    afirmacoes = resumo.get("afirmacoes") or []

    if not afirmacoes:
        st.caption(t("governanca_sem_afirmacoes"))
        return

    rotulo = tf("governanca_afirmacoes", n=len(afirmacoes))
    opcoes = {"expanded": False, "icon": ":material/verified_user:"}

    if chave:
        opcoes["key"] = f"governanca_detalhe_{chave}"

    with st.expander(rotulo, **opcoes):
        linhas = [
            {
                "classificacao": item["classificacao"],
                "texto": item["texto"],
                "evidence_id": item.get("evidence_id") or "—",
            }
            for item in afirmacoes
        ]

        st.dataframe(
            linhas,
            hide_index=True,
            width="stretch",
            column_config={
                "classificacao": t("governanca_coluna_classificacao"),
                "texto": t("governanca_coluna_afirmacao"),
                "evidence_id": t("governanca_coluna_evidencia"),
            },
        )

        for aviso in resumo.get("avisos") or ():
            st.caption(aviso)