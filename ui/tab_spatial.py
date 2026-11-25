"""Aba 2 — resolução espacial, pacote offline e mapa por fonte (D2).

A tela é apenas apresentação: a geometria e a persistência ficam em
``adapters.spatial_cim`` e ``services.db_service``. Nenhuma consulta
externa é feita aqui; o pacote offline é lido do SQLite local.

A ordem da tela segue a decisão do usuário:

1. cartão de resolução (coordenadas ou folha CIM);
2. gerenciador do pacote offline da folha;
3. consulta desconectada do pacote;
4. mapa interativo por fonte, prévia tabular e exportações sanitizadas.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from adapters import spatial_cim
from config import APP_VERSION
from services.exportacao_segura import (
    escapar_tooltip,
    gerar_geojson_qgis,
    gerar_xlsx_seguro,
)
from services.spatial_parser import CAMADAS, gerar_csv_pontos
from utils.i18n import t, tf

CHAVE_RESULTADO = "aba_espacial_resultado"
CHAVE_PACOTE = "aba_espacial_pacote_folha"
CHAVE_MODO = "aba_espacial_modo"


def _texto(valor):
    """Texto de uma célula, sem ``None`` nem NaN."""

    if valor is None:
        return ""

    if isinstance(valor, float) and pd.isna(valor):
        return ""

    return str(valor)


def _feicoes_das_mensagens(mensagens):
    """Reúne as feições espaciais gravadas nas mensagens da sessão."""

    feicoes = []
    vistos = set()

    for mensagem in mensagens or []:
        for feicao in mensagem.get("feicoes_espaciais") or []:
            if not isinstance(feicao, dict):
                continue

            lat = feicao.get("lat")
            lon = feicao.get("lon")

            if lat is None or lon is None:
                continue

            chave = (
                round(float(lat), 5),
                round(float(lon), 5),
                _texto(feicao.get("nome")),
                _texto(feicao.get("camada")),
            )

            if chave in vistos:
                continue

            vistos.add(chave)
            feicoes.append(feicao)

    return feicoes


def _rotulo_erro(resultado):
    """Traduz o código estável de erro devolvido pelo adaptador."""

    erro = (resultado or {}).get("erro")
    mapa = {
        spatial_cim.ERRO_COORDENADA_AUSENTE: "espacial_coordenada_ausente",
        spatial_cim.ERRO_COORDENADA_INVALIDA: "espacial_coordenada_invalida",
        spatial_cim.ERRO_INVERSAO_INDEVIDA: "espacial_inversao_indevida",
        spatial_cim.ERRO_FOLHA_INVALIDA: "espacial_folha_invalida",
        spatial_cim.ERRO_PACOTE_SEM_DADOS: "espacial_pacote_sem_dados",
    }

    return t(mapa.get(erro, "espacial_erro_generico"))


def _cartao_resolucao(resultado):
    """Cartão com coordenadas normalizadas e hierarquia cartográfica."""

    if not resultado:
        return

    with st.container(border=True, key="aba_espacial_cartao"):
        st.markdown(f"**{t('espacial_cartao_titulo')}**")

        if not resultado.get("ok"):
            st.error(_rotulo_erro(resultado))
            return

        coordenadas = resultado.get("coordenadas") or {}
        par = coordenadas.get("par") or (
            f"{resultado['lat']:.6f}, {resultado['lon']:.6f}"
        )

        colunas = st.columns(2)

        with colunas[0]:
            st.metric(
                t("espacial_resultado_coordenadas"),
                coordenadas.get("formatado") or par,
            )

        with colunas[1]:
            st.metric(
                t("espacial_folha_cim"),
                resultado.get("codigo") or resultado.get("folha_cim") or "—",
            )

        if coordenadas.get("invertida"):
            st.warning(
                tf("espacial_inversao_detectada", par=par),
                icon=":material/swap_vert:",
            )

        if resultado.get("pacote_disponivel"):
            st.success(
                t("espacial_pacote_disponivel"),
                icon=":material/download_done:",
            )
        else:
            st.info(
                t("espacial_pacote_indisponivel"),
                icon=":material/cloud_off:",
            )

        hierarquia = resultado.get("hierarquia") or []

        if hierarquia:
            st.markdown(f"**{t('espacial_hierarquia')}**")
            tabela = pd.DataFrame(
                {
                    t("espacial_escala"): [
                        nivel["escala"] for nivel in hierarquia
                    ],
                    t("espacial_codigo"): [
                        nivel["codigo"] for nivel in hierarquia
                    ],
                    t("espacial_centroide"): [
                        f"{nivel['lat']:.6f}, {nivel['lon']:.6f}"
                        for nivel in hierarquia
                    ],
                    t("espacial_limites"): [
                        nivel["limites"] for nivel in hierarquia
                    ],
                }
            )
            st.dataframe(
                tabela,
                width="stretch",
                hide_index=True,
                alt=t("espacial_hierarquia"),
            )


def _entrada_resolucao():
    """Formulário de resolução; devolve o resultado ou ``None``."""

    modo_coordenadas = t("espacial_modo_coordenadas")
    modo_folha = t("espacial_modo_folha")

    modo = st.segmented_control(
        t("espacial_modo"),
        [modo_coordenadas, modo_folha],
        default=modo_coordenadas,
        key=CHAVE_MODO,
    ) or modo_coordenadas

    resultado = None
    rotulado = False
    lat = lon = None
    codigo = None

    if modo == modo_coordenadas:
        colunas = st.columns(2)

        with colunas[0]:
            lat = st.text_input(
                t("espacial_latitude"),
                key="aba_espacial_lat",
                placeholder="-3.1234",
            )

        with colunas[1]:
            lon = st.text_input(
                t("espacial_longitude"),
                key="aba_espacial_lon",
                placeholder="-60.0123",
            )

        rotulado = st.toggle(
            t("espacial_rotulado"),
            key="aba_espacial_rotulado",
            help=t("espacial_ajuda_rotulado"),
        )
    else:
        codigo = st.text_input(
            t("espacial_folha_cim"),
            key="aba_espacial_codigo",
            placeholder=t("espacial_placeholder_folha"),
        )

    colunas_acoes = st.columns([1, 1, 3], vertical_alignment="bottom")

    with colunas_acoes[0]:
        resolver = st.button(
            t("espacial_consultar"),
            key="aba_espacial_resolver",
            type="primary",
            width="stretch",
        )

    with colunas_acoes[1]:
        limpar = st.button(
            t("espacial_limpar"),
            key="aba_espacial_limpar",
            width="stretch",
        )

    if limpar:
        st.session_state.pop(CHAVE_RESULTADO, None)
        resultado = None
    elif resolver:
        if modo == modo_folha:
            resultado = spatial_cim.resolver_consulta_espacial(
                codigo=codigo
            )
        else:
            resultado = spatial_cim.resolver_consulta_espacial(
                lat=lat,
                lon=lon,
                rotulado=rotulado,
            )

        st.session_state[CHAVE_RESULTADO] = resultado
    else:
        resultado = st.session_state.get(CHAVE_RESULTADO)

    _cartao_resolucao(resultado)

    return resultado


def _folha_padrao(resultado, feicoes):
    """Folha sugerida: resultado atual, feições ou a primeira disponível."""

    if resultado and resultado.get("ok"):
        return resultado.get("folha_cim") or "SA.20"

    contagem = {}

    for feicao in feicoes:
        folha = feicao.get("folha_cim")

        if folha:
            contagem[str(folha)] = contagem.get(str(folha), 0) + 1

    if contagem:
        return max(contagem, key=contagem.get)

    return "SA.20"


def _opcoes_folha(resultado, feicoes):
    """Opções do seletor de pacote, sem duplicatas."""

    opcoes = []

    for folha in [
        (resultado or {}).get("folha_cim"),
        *[feicao.get("folha_cim") for feicao in feicoes],
        *[
            item.get("manifesto", {}).get("cim_code")
            for item in spatial_cim.listar_pacotes_offline()
        ],
    ]:
        if folha and str(folha) not in opcoes:
            opcoes.append(str(folha))

    return opcoes or ["SA.20"]


def _feicao_da_folha(resultado):
    """Registro mínimo da própria folha, para o pacote nunca ficar vazio."""

    if not resultado or not resultado.get("ok"):
        return []

    return [
        {
            "nome": f"Folha {resultado.get('codigo')}",
            "camada": "Folhas CIM",
            "fonte": "cim_base",
            "lat": resultado.get("lat"),
            "lon": resultado.get("lon"),
            "lat_min": resultado.get("lat_min"),
            "lat_max": resultado.get("lat_max"),
            "lon_min": resultado.get("lon_min"),
            "lon_max": resultado.get("lon_max"),
            "folha_cim": resultado.get("folha_cim"),
            "detalhe": (
                f"Folha CIM {resultado.get('codigo')} · escala "
                f"{resultado.get('escala')} · {resultado.get('limites')}"
            ),
            "cor_hex": CAMADAS["folhas_cim"][1],
        }
    ]


def _gerenciador_pacote(resultado, feicoes):
    """Baixa/atualiza e exibe o pacote offline da folha CIM."""

    st.subheader(t("espacial_pacote_titulo"))
    st.caption(t("espacial_pacote_caption"))
    st.caption(t("espacial_pacote_memoria"))

    opcoes = _opcoes_folha(resultado, feicoes)
    padrao = _folha_padrao(resultado, feicoes)

    if st.session_state.get(CHAVE_PACOTE) not in opcoes:
        st.session_state[CHAVE_PACOTE] = padrao

    folha = st.selectbox(
        t("espacial_pacote_folha"),
        opcoes,
        key=CHAVE_PACOTE,
    )

    feicoes_pacote = list(feicoes)
    feicoes_pacote.extend(_feicao_da_folha(resultado))

    if st.button(
        t("espacial_pacote_baixar"),
        key="aba_espacial_baixar_pacote",
        type="primary",
        width="stretch",
        icon=":material/cloud_download:",
    ):
        try:
            pacote = spatial_cim.salvar_pacote_offline(
                folha,
                feicoes=feicoes_pacote,
                source_version=f"NexusGeo IA v{APP_VERSION}",
            )
        except Exception as erro:  # noqa: BLE001 - a UI mostra o motivo
            st.error(
                tf("espacial_pacote_erro", erro=str(erro)),
                icon=":material/error:",
            )
        else:
            if pacote.get("ok"):
                manifesto = pacote.get("manifesto", {}).get(
                    "manifesto", {}
                )
                fontes = len(manifesto.get("totais_por_fonte") or {})
                st.success(
                    tf(
                        "espacial_pacote_criado",
                        total=manifesto.get("total_registros", 0),
                        fontes=fontes,
                    ),
                    icon=":material/check_circle:",
                )
            else:
                # Folha divergente da resolução atual ou sem feições
                # compatíveis: o adaptador recusa o snapshot vazio, de
                # modo que o pacote anterior permanece intacto.
                if pacote.get("erro") == spatial_cim.ERRO_PACOTE_SEM_DADOS:
                    st.warning(
                        _rotulo_erro(pacote),
                        icon=":material/filter_alt_off:",
                    )
                else:
                    st.error(
                        _rotulo_erro(pacote),
                        icon=":material/error:",
                    )

    pacote = spatial_cim.obter_pacote_offline(folha)

    if not pacote:
        st.info(
            t("espacial_pacote_indisponivel"),
            icon=":material/cloud_off:",
        )
        return None

    manifesto = pacote.get("manifesto") or {}
    fontes = pacote.get("fontes") or []

    colunas = st.columns(3)

    with colunas[0]:
        st.metric(
            t("espacial_pacote_collected_at"),
            manifesto.get("collected_at") or "—",
        )

    with colunas[1]:
        st.metric(
            t("espacial_pacote_source_version"),
            manifesto.get("source_version") or "—",
        )

    with colunas[2]:
        st.metric(
            t("espacial_pacote_total"),
            manifesto.get("total_registros", 0),
        )

    if fontes:
        st.markdown(f"**{t('espacial_pacote_fontes')}**")
        tabela = pd.DataFrame(
            {
                t("espacial_pacote_fonte"): [
                    item.get("fonte") for item in fontes
                ],
                t("espacial_pacote_registros"): [
                    item.get("total", 0) for item in fontes
                ],
            }
        )
        st.dataframe(
            tabela,
            width="stretch",
            hide_index=True,
            alt=t("espacial_pacote_fontes"),
        )

    colunas_exportacao = st.columns(2)

    with colunas_exportacao[0]:
        st.download_button(
            t("espacial_pacote_exportar_manifesto"),
            data=json.dumps(
                manifesto, ensure_ascii=False, indent=2
            ).encode("utf-8"),
            file_name=f"pacote_offline_{folha}.json",
            mime="application/json",
            key="aba_espacial_manifesto",
            icon=":material/download:",
            width="stretch",
        )

    with colunas_exportacao[1]:
        offline = spatial_cim.consultar_pacote_offline(folha)
        st.download_button(
            t("espacial_pacote_exportar_dados"),
            data=gerar_csv_pontos(offline.get("feicoes") or []),
            file_name=f"pacote_offline_{folha}.csv",
            mime="text/csv",
            key="aba_espacial_offline_csv",
            icon=":material/download:",
            width="stretch",
        )

    if st.button(
        t("espacial_pacote_remover"),
        key="aba_espacial_remover_pacote",
        icon=":material/delete:",
    ):
        spatial_cim.remover_pacote_offline(folha)
        st.success(
            t("espacial_pacote_removido"),
            icon=":material/check_circle:",
        )

    return folha


def _consulta_offline(folha):
    """Mostra a leitura desconectada do pacote e sua tabela de prévia."""

    if not folha:
        return []

    st.subheader(t("espacial_offline_titulo"))
    st.caption(t("espacial_offline_caption"))

    pacote = spatial_cim.consultar_pacote_offline(folha)

    if not pacote.get("disponivel"):
        st.info(
            tf("espacial_pacote_nao_encontrado", folha=folha),
            icon=":material/cloud_off:",
        )
        return []

    fontes = [
        item.get("fonte") for item in pacote.get("fontes") or []
    ]

    # Pacote existente, porém sem registros na folha: o aviso correto é
    # "sem dados", não "pacote offline indisponível".
    total_pacote = int(
        (pacote.get("manifesto") or {}).get("total_registros") or 0
    )

    if total_pacote <= 0 and not fontes:
        st.info(
            t("espacial_pacote_sem_dados"),
            icon=":material/filter_alt_off:",
        )
        return []

    opcoes = [t("espacial_offline_todas"), *fontes]

    if st.session_state.get("aba_espacial_offline_fonte") not in opcoes:
        st.session_state["aba_espacial_offline_fonte"] = opcoes[0]

    filtro = st.selectbox(
        t("espacial_offline_fonte"),
        opcoes,
        key="aba_espacial_offline_fonte",
    )

    fonte = None if filtro == t("espacial_offline_todas") else filtro
    consulta = spatial_cim.consultar_pacote_offline(folha, fonte=fonte)
    feicoes = consulta.get("feicoes") or []

    if not feicoes:
        st.info(
            t("espacial_offline_sem_dados"),
            icon=":material/database_off:",
        )
        return []

    tabela = _tabela_previa(feicoes)
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        alt=t("espacial_tabela_alt"),
    )

    return feicoes


def _tabela_previa(feicoes):
    """DataFrame da prévia tabular, com cabeçalhos traduzidos."""

    return pd.DataFrame(
        {
            t("espacial_coluna_nome"): [
                _texto(feicao.get("nome")) for feicao in feicoes
            ],
            t("espacial_coluna_fonte"): [
                _texto(
                    feicao.get("fonte")
                    or feicao.get("camada")
                    or "—"
                )
                for feicao in feicoes
            ],
            t("espacial_coluna_latitude"): [
                feicao.get("lat") for feicao in feicoes
            ],
            t("espacial_coluna_longitude"): [
                feicao.get("lon") for feicao in feicoes
            ],
            t("espacial_coluna_folha"): [
                _texto(feicao.get("folha_cim")) for feicao in feicoes
            ],
        }
    )


def _renderizar_mapa(feicoes, chave="aba_espacial"):
    """Mapa interativo com tooltip, filtro por fonte e prévia tabular."""

    if not feicoes:
        st.info(
            t("espacial_sem_feicoes_sessao"),
            icon=":material/map:",
        )
        return

    st.subheader(t("espacial_mapa_titulo"))

    fontes = sorted(
        {
            _texto(
                feicao.get("fonte")
                or feicao.get("camada")
                or t("outras_fontes")
            )
            for feicao in feicoes
        }
    )

    selecionadas = st.multiselect(
        t("espacial_mapa_fontes"),
        fontes,
        default=fontes,
        key=f"{chave}_fontes_mapa",
    )

    filtradas = [
        feicao
        for feicao in feicoes
        if _texto(
            feicao.get("fonte")
            or feicao.get("camada")
            or t("outras_fontes")
        ) in selecionadas
    ]

    if not filtradas:
        st.caption(t("espacial_mapa_sem_feicoes"))
        return

    registros = []

    for feicao in filtradas:
        lat = feicao.get("lat")
        lon = feicao.get("lon")

        if lat is None or lon is None:
            continue

        registros.append(
            {
                "nome": escapar_tooltip(feicao.get("nome")),
                "fonte": escapar_tooltip(
                    feicao.get("fonte")
                    or feicao.get("camada")
                    or t("outras_fontes")
                ),
                "folha": escapar_tooltip(feicao.get("folha_cim")),
                "lat": float(lat),
                "lon": float(lon),
                "cor_rgb": _cor_rgb(feicao.get("cor_hex")),
            }
        )

    if not registros:
        st.caption(t("espacial_mapa_sem_feicoes"))
        return

    try:
        import pydeck as pdk
    except ImportError:  # pragma: no cover - pydeck acompanha o Streamlit
        st.map(
            pd.DataFrame(registros),
            latitude="lat",
            longitude="lon",
            color="cor_rgb",
            size=60,
            height=420,
            alt=tf("espacial_mapa_alt", n=len(registros)),
        )
    else:
        camada = pdk.Layer(
            "ScatterplotLayer",
            data=registros,
            get_position="[lon, lat]",
            get_fill_color="cor_rgb",
            get_radius=18000,
            pickable=True,
            auto_highlight=True,
        )
        deck = pdk.Deck(
            layers=[camada],
            initial_view_state=pdk.ViewState(
                latitude=sum(item["lat"] for item in registros)
                / len(registros),
                longitude=sum(item["lon"] for item in registros)
                / len(registros),
                zoom=5,
                pitch=0,
            ),
            tooltip={"html": t("espacial_mapa_tooltip")},
        )
        st.pydeck_chart(
            deck,
            height=420,
            alt=tf("espacial_mapa_alt", n=len(registros)),
        )

    st.markdown(f"**{t('espacial_tabela_titulo')}**")
    st.dataframe(
        _tabela_previa(filtradas),
        width="stretch",
        hide_index=True,
        alt=t("espacial_tabela_alt"),
    )
    st.caption(t("espacial_aviso_neutralizacao"))

    _exportacoes(filtradas)


def _cor_rgb(valor):
    """Converte ``#RRGGBB`` em ``[R, G, B]`` para o pydeck."""

    texto = _texto(valor).strip().lstrip("#")

    if len(texto) != 6:
        return [31, 111, 235]

    try:
        return [
            int(texto[0:2], 16),
            int(texto[2:4], 16),
            int(texto[4:6], 16),
        ]
    except ValueError:
        return [31, 111, 235]


def _exportacoes(feicoes):
    """Prévia tabular seguida de CSV, XLSX e GeoJSON sanitizados."""

    tabela = _tabela_previa(feicoes)
    colunas = st.columns(3)

    with colunas[0]:
        st.download_button(
            t("espacial_exportar_csv"),
            data=gerar_csv_pontos(feicoes),
            file_name="pontos_espaciais_qgis.csv",
            mime="text/csv",
            key="aba_espacial_csv",
            icon=":material/download:",
            width="stretch",
            help=t("espacial_ajuda_csv"),
        )

    with colunas[1]:
        st.download_button(
            t("espacial_exportar_xlsx"),
            data=gerar_xlsx_seguro(tabela),
            file_name="pontos_espaciais.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            key="aba_espacial_xlsx",
            icon=":material/download:",
            width="stretch",
            help=t("espacial_ajuda_xlsx"),
        )

    with colunas[2]:
        st.download_button(
            t("espacial_exportar_qgis"),
            data=gerar_geojson_qgis(feicoes),
            file_name="pontos_espaciais_qgis.geojson",
            mime="application/geo+json",
            key="aba_espacial_geojson",
            icon=":material/download:",
            width="stretch",
            help=t("espacial_ajuda_qgis"),
        )


def renderizar_aba_espacial(
    mensagens=None,
    feicoes=None,
    chave="aba_espacial",
):
    """Renderiza a Aba 2 completa e devolve a folha selecionada."""

    st.subheader(t("espacial_titulo"))
    st.caption(t("espacial_caption"))

    feicoes_sessao = (
        list(feicoes)
        if feicoes is not None
        else _feicoes_das_mensagens(mensagens)
    )

    resultado = _entrada_resolucao()
    folha = _gerenciador_pacote(resultado, feicoes_sessao)
    offline = _consulta_offline(folha)

    # O mapa usa as feições da sessão e, quando há pacote offline, também
    # os registros gravados. Assim a aba funciona tanto online quanto
    # depois do download da folha.
    combinadas = list(feicoes_sessao)

    for feicao in offline:
        if feicao not in combinadas:
            combinadas.append(feicao)

    _renderizar_mapa(combinadas, chave=chave)

    return folha
