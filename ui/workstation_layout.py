"""Layout adaptativo da Workstation GIS Dark Mode (Fase D4).

O módulo concentra a decisão de layout da área principal e os cartões
da grade assimétrica em três colunas. As funções puras
(``has_active_workspace``, ``compute_epistemic_ratios``,
``coletar_evidencias`` e ``contar_fontes_ativas``) não tocam no
runtime do Streamlit, para poderem ser testadas offline; a importação
de ``streamlit`` acontece apenas dentro das funções de renderização,
como em ``ui/governanca.py``.

Semântica epistêmica (exclusiva no CSS de ``app.py``):

* OBSERVED — afirmação ancorada em ``evidence_id``/fonte rastreada;
* INFERRED — síntese interpretativa do modelo.

Os únicos literais sem tradução são os códigos técnicos do contrato
(OBSERVED, INFERRED e evidence_id), preservados de propósito.
"""

from __future__ import annotations

from ui.governanca import CLASSIFICACOES, resumir
from utils.i18n import t, tf

# Chaves das abas do layout ativo. Ficam aqui para o ``app.py`` montar
# os rótulos sem duplicar a lista.
CHAVES_ABAS_ATIVAS = (
    "aba_sintese",
    "aba_mapa_workstation",
    "aba_dados_exportacao",
    "aba_sondagem",
)

CHAVE_CONTAINER_GOVERNANCA = "workstation_governanca"


def _lista(valor):
    """Normaliza None, escalar e coleções em uma lista simples."""

    if valor is None:
        return []

    if isinstance(valor, (list, tuple, set)):
        return list(valor)

    return [valor]


def _texto(valor):
    """Texto curto e sem espaços nas pontas, tolerante a None."""

    if valor is None:
        return ""

    return str(valor).strip()


def _tem_registros(tabela):
    """Indica se uma entrada tabular tem linhas de verdade."""

    if tabela is None:
        return False

    if isinstance(tabela, dict):
        for chave in ("registros", "linhas", "dados", "tabela"):
            if tabela.get(chave):
                return True

        return False

    try:
        return len(tabela) > 0
    except TypeError:
        return bool(tabela)


def _feicao_util(feicao):
    """Feição geográfica com folha CIM ou coordenada válida."""

    if not isinstance(feicao, dict):
        return False

    if _texto(feicao.get("folha_cim")):
        return True

    return feicao.get("lat") is not None and feicao.get("lon") is not None


def feicoes_detectadas(mensagens=None):
    """Feições espaciais gravadas nas mensagens, sem repetição."""

    feicoes = []
    vistos = set()

    for mensagem in _lista(mensagens):
        if not isinstance(mensagem, dict):
            continue

        for feicao in _lista(mensagem.get("feicoes_espaciais")):
            if not _feicao_util(feicao):
                continue

            chave = (
                feicao.get("lat"),
                feicao.get("lon"),
                _texto(feicao.get("nome")),
                _texto(feicao.get("camada")),
                _texto(feicao.get("folha_cim")),
            )

            if chave in vistos:
                continue

            vistos.add(chave)
            feicoes.append(feicao)

    return feicoes


def folhas_cim_detectadas(mensagens=None):
    """Códigos CIM citados nas respostas, em ordem estável e sem repetição."""

    folhas = []

    for feicao in feicoes_detectadas(mensagens):
        folha = _texto(feicao.get("folha_cim")).upper()

        if folha and folha not in folhas:
            folhas.append(folha)

    return folhas


def tem_feicoes_espaciais(mensagens=None):
    """True quando há ponto ou folha CIM em qualquer resposta da sessão."""

    for mensagem in _lista(mensagens):
        if not isinstance(mensagem, dict):
            continue

        for feicao in _lista(mensagem.get("feicoes_espaciais")):
            if _feicao_util(feicao):
                return True

    return False


def has_active_workspace(
    documentos=None,
    mensagens=None,
    tabelas=None,
    evidencias=None,
):
    """Decide entre o layout vazio e o layout ativo da Workstation.

    O workspace fica ativo quando existe QUALQUER um destes sinais:

    * documento anexado na base local;
    * ponto ou folha CIM detectado nas respostas;
    * tabela extraída (de documento ou de fonte externa);
    * evidência rastreada (``evidence_id``) em afirmações OBSERVED.

    Sem nenhum deles, a área principal permanece centralizada, com o
    chat técnico, as sugestões rápidas e o upload.
    """

    for documento in _lista(documentos):
        if _texto(documento):
            return True

    if tem_feicoes_espaciais(mensagens):
        return True

    for tabela in _lista(tabelas):
        if _tem_registros(tabela):
            return True

    for evidencia in _lista(evidencias):
        if isinstance(evidencia, dict) and _texto(
            evidencia.get("evidence_id")
        ):
            return True

        if not isinstance(evidencia, dict) and _texto(evidencia):
            return True

    return False


def _resumos(governancas):
    """Resumos normalizados de governança, ignorando entradas vazias."""

    resumos = []

    for item in _lista(governancas):
        if item is None:
            continue

        resumo = resumir(item)

        if resumo:
            resumos.append(resumo)

    return resumos


def compute_epistemic_ratios(governancas=None):
    """Proporção OBSERVED x INFERRED das afirmações auditáveis.

    Aceita um único resultado de governança, uma lista deles ou None.
    Devolve contagens absolutas e percentuais com uma casa decimal; a
    soma dos dois percentuais é sempre 100 quando há afirmações.
    """

    observed = 0
    inferred = 0

    for resumo in _resumos(governancas):
        observed += int(resumo.get("observed") or 0)
        inferred += int(resumo.get("inferred") or 0)

    total = observed + inferred

    if total <= 0:
        return {
            "observed": observed,
            "inferred": inferred,
            "total": 0,
            "observed_pct": 0.0,
            "inferred_pct": 0.0,
        }

    observed_pct = round(observed * 100.0 / total, 1)

    return {
        "observed": observed,
        "inferred": inferred,
        "total": total,
        "observed_pct": observed_pct,
        "inferred_pct": round(100.0 - observed_pct, 1),
    }


def coletar_evidencias(governancas=None):
    """Ranking dos ``evidence_id`` citados, com aderência OBSERVED.

    A aderência é a proporção de citações OBSERVED daquele
    ``evidence_id`` (0 a 100). O ranking ordena por aderência, depois
    por número de citações e por código, garantindo saída determinística.
    """

    agregado = {}

    for resumo in _resumos(governancas):
        for afirmacao in resumo.get("afirmacoes") or ():
            if not isinstance(afirmacao, dict):
                continue

            evidence_id = _texto(afirmacao.get("evidence_id"))

            if not evidence_id:
                continue

            registro = agregado.setdefault(
                evidence_id,
                {
                    "evidence_id": evidence_id,
                    "citacoes": 0,
                    "observed": 0,
                    "inferred": 0,
                },
            )

            registro["citacoes"] += 1

            if afirmacao.get("classificacao") in CLASSIFICACOES:
                chave = afirmacao["classificacao"].lower()
            else:
                chave = "inferred"

            registro[chave] += 1

    evidencias = []

    for registro in agregado.values():
        citacoes = registro["citacoes"] or 1
        registro["aderencia"] = round(
            registro["observed"] * 100.0 / citacoes,
            1,
        )
        evidencias.append(registro)

    evidencias.sort(
        key=lambda item: (
            -item["aderencia"],
            -item["citacoes"],
            item["evidence_id"],
        )
    )

    return evidencias


def governancas_das_mensagens(mensagens=None):
    """Lista dos resultados de governança gravados nas mensagens."""

    resultados = []

    for mensagem in _lista(mensagens):
        if not isinstance(mensagem, dict):
            continue

        governanca = mensagem.get("governanca")

        if governanca:
            resultados.append(governanca)

    return resultados


def contar_fontes_ativas(conectores=None, local_docs=False):
    """Fontes ativas: conectores ligados + base documental local."""

    ativos = sum(
        1 for ligado in (conectores or {}).values() if ligado
    )

    return ativos + (1 if local_docs else 0)


def renderizar_indicadores(
    fontes_ativas=0,
    alvos_cim=0,
    proporcoes=None,
):
    """Coluna 1: métricas e cartão de governança epistêmica."""

    import streamlit as st

    proporcoes = proporcoes or compute_epistemic_ratios(None)

    st.subheader(t("workstation_indicadores"))
    st.metric(
        t("workstation_fontes_ativas"),
        int(fontes_ativas),
        border=True,
    )
    st.metric(
        t("workstation_alvos_cim"),
        int(alvos_cim),
        border=True,
    )

    with st.container(border=True, key=CHAVE_CONTAINER_GOVERNANCA):
        st.markdown(f"**{t('workstation_governanca_titulo')}**")

        if not proporcoes.get("total"):
            st.caption(t("workstation_sem_afirmacoes"))
            return

        st.html(_html_proporcao(proporcoes))


def _html_proporcao(proporcoes):
    """Chips e barras com a semântica epistêmica definida no CSS."""

    observed_pct = float(proporcoes.get("observed_pct") or 0.0)
    inferred_pct = float(proporcoes.get("inferred_pct") or 0.0)

    return (
        '<div class="nx-epistemic">'
        '<div class="nx-epistemic-linha">'
        f'<span class="nx-chip nx-observed">OBSERVED '
        f'{observed_pct:.1f}%</span>'
        f'<span class="nx-epistemic-valor">'
        f'{int(proporcoes.get("observed") or 0)}</span>'
        "</div>"
        '<div class="nx-bar-track">'
        f'<div class="nx-bar-fill nx-bar-observed" '
        f'style="width:{observed_pct:.1f}%"></div>'
        "</div>"
        '<div class="nx-epistemic-linha">'
        f'<span class="nx-chip nx-inferred">INFERRED '
        f'{inferred_pct:.1f}%</span>'
        f'<span class="nx-epistemic-valor">'
        f'{int(proporcoes.get("inferred") or 0)}</span>'
        "</div>"
        '<div class="nx-bar-track">'
        f'<div class="nx-bar-fill nx-bar-inferred" '
        f'style="width:{inferred_pct:.1f}%"></div>'
        "</div>"
        "</div>"
    )


def renderizar_rastreabilidade(
    evidencias=None,
    modelo=None,
    online=False,
    proporcoes=None,
):
    """Coluna 3: ranking de evidências e cartão fixo de governança."""

    import streamlit as st

    evidencias = list(evidencias or ())
    proporcoes = proporcoes or compute_epistemic_ratios(None)

    st.subheader(t("workstation_rastreabilidade_titulo"))

    if evidencias:
        st.dataframe(
            evidencias,
            hide_index=True,
            width="stretch",
            alt=t("workstation_evidencias_alt"),
            column_config={
                "evidence_id": st.column_config.TextColumn(
                    t("workstation_coluna_evidencia"),
                    width="medium",
                ),
                "citacoes": st.column_config.NumberColumn(
                    t("workstation_coluna_citacoes"),
                    width="small",
                ),
                "aderencia": st.column_config.ProgressColumn(
                    t("workstation_coluna_aderencia"),
                    help=t("workstation_ajuda_aderencia"),
                    min_value=0,
                    max_value=100,
                    format="%.0f%%",
                ),
            },
        )
    else:
        st.caption(t("workstation_sem_evidencias"))

    with st.container(border=True, key="workstation_motor"):
        st.markdown(f"**{t('workstation_motor_titulo')}**")

        st.badge(
            t("workstation_modo_online") if online
            else t("workstation_modo_offline"),
            color="green" if online else "red",
            icon=(
                ":material/wifi:" if online
                else ":material/wifi_off:"
            ),
        )

        st.caption(
            tf(
                "workstation_modelo_ativo",
                modelo=modelo or t("workstation_modelo_fallback"),
            )
        )

        st.caption(t("workstation_criterios"))
        st.html(
            '<div class="nx-epistemic-linha">'
            '<span class="nx-chip nx-observed">OBSERVED</span>'
            '<span class="nx-chip nx-inferred">INFERRED</span>'
            "</div>"
        )
        st.caption(t("workstation_criterio_observed"))
        st.caption(t("workstation_criterio_inferred"))

        if proporcoes.get("total"):
            st.caption(
                tf(
                    "workstation_resumo_proporcao",
                    observed=proporcoes.get("observed_pct", 0.0),
                    inferred=proporcoes.get("inferred_pct", 0.0),
                )
            )


def _registros_mapa(feicoes):
    """Registros mínimos (lat/lon) para o ``st.map``."""

    registros = []

    for feicao in feicoes or ():
        if not _feicao_util(feicao):
            continue

        lat = feicao.get("lat")
        lon = feicao.get("lon")

        if lat is None or lon is None:
            continue

        registros.append(
            {
                "nome": _texto(feicao.get("nome")),
                "camada": _texto(feicao.get("camada")),
                "folha_cim": _texto(feicao.get("folha_cim")),
                "lat": float(lat),
                "lon": float(lon),
            }
        )

    return registros


def renderizar_mapa_workspace(mensagens=None, feicoes=None):
    """Aba "Mapa Espacial": ``st.map`` com pontos e folhas detectados."""

    import pandas as pd
    import streamlit as st

    from services.spatial_parser import gerar_csv_pontos

    lista = (
        list(feicoes)
        if feicoes is not None
        else feicoes_detectadas(mensagens)
    )
    registros = _registros_mapa(lista)

    if not registros:
        st.info(
            t("workstation_mapa_vazio"),
            icon=":material/map:",
        )
        return

    st.caption(
        tf("workstation_mapa_contagem", n=len(registros))
    )

    tabela = pd.DataFrame(registros)

    st.map(
        tabela,
        latitude="lat",
        longitude="lon",
        color="#00B4D8",
        size=60,
        height=420,
        alt=tf("workstation_mapa_alt", n=len(registros)),
    )

    st.dataframe(
        tabela,
        hide_index=True,
        width="stretch",
        alt=t("workstation_mapa_tabela_alt"),
        column_config={
            "nome": t("workstation_coluna_nome"),
            "camada": t("workstation_coluna_camada"),
            "folha_cim": t("workstation_coluna_folha"),
            "lat": st.column_config.NumberColumn(
                "lat", format="%.5f"
            ),
            "lon": st.column_config.NumberColumn(
                "lon", format="%.5f"
            ),
        },
    )

    st.download_button(
        t("workstation_baixar_csv"),
        data=gerar_csv_pontos(lista),
        file_name="workstation_pontos.csv",
        mime="text/csv",
        key="workstation_baixar_csv",
        icon=":material/download:",
    )
