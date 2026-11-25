"""Aba 4 - grade de sondagem De-Ate e validacao litologica (D3b).

A tela e apenas apresentacao: o parser, a validacao e a exportacao vivem
em services.sondagem. Ela oferece:

* entrada por texto delimitado (CSV/TSV colado), com exemplo bilingue;
* cartao de resumo com intervalos validos, invalidos, sobreposicoes e
  lacunas por furo;
* filtros por furo, litologia, situacao e busca textual;
* tabelas separadas para linhas invalidas, sobreposicoes e lacunas;
* downloads CSV/XLSX sanitizados, sem formulas perigosas.

Os textos visiveis vem de utils.i18n; os codigos de situacao e de motivo
sao estaveis no servico e traduzidos aqui.

Idempotencia e referencias leves: a tela guarda o hash do texto analisado
e a assinatura da grade devolvida pelo servico. Reexecutar a mesma
analise reaproveita o resultado (nao duplica processamento nem perde o
resultado anterior em falha) e os bytes de CSV/XLSX ficam em cache por
assinatura + idioma, evitando reserializar a tabela inteira a cada rerun.
A analise roda com prazo explicito e o cancelamento cooperativo do
servico e traduzido em aviso, nunca em traceback.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from services import progress_service, sondagem
from utils.i18n import t, tf

CHAVE_RESULTADO = "aba_sondagem_resultado"
CHAVE_TEXTO = "aba_sondagem_texto"
CHAVE_ERRO = "aba_sondagem_erro"
CHAVE_INICIALIZADO = "aba_sondagem_inicializado"
# Referencias leves da ultima analise: hash do texto e assinatura da grade.
CHAVE_ASSINATURA_TEXTO = "aba_sondagem_assinatura_texto"
CHAVE_ASSINATURA_RESULTADO = "aba_sondagem_assinatura_resultado"
# Bytes de exportacao por assinatura + idioma (cache de sessao).
CHAVE_EXPORTACOES = "aba_sondagem_exportacoes"

# Prazo explicito da etapa de analise na interface. O parser e rapido;
# uma tabela patologica precisa falhar com mensagem em vez de prender a
# pagina.
TEMPO_LIMITE_ANALISE_S = 20.0

SITUACOES_I18N = {
    sondagem.SITUACAO_VALIDO: "sondagem_situacao_valido",
    sondagem.SITUACAO_SOBREPOSICAO: "sondagem_situacao_sobreposicao",
    sondagem.SITUACAO_LACUNA: "sondagem_situacao_lacuna",
    sondagem.SITUACAO_SOBREPOSICAO_LACUNA:
        "sondagem_situacao_sobreposicao_lacuna",
    sondagem.SITUACAO_INVALIDO: "sondagem_situacao_invalido",
}

MOTIVOS_I18N = {
    sondagem.MOTIVO_FURO_AUSENTE: "sondagem_motivo_furo_ausente",
    sondagem.MOTIVO_DE_AUSENTE: "sondagem_motivo_de_ausente",
    sondagem.MOTIVO_ATE_AUSENTE: "sondagem_motivo_ate_ausente",
    sondagem.MOTIVO_DE_INVALIDO: "sondagem_motivo_de_invalido",
    sondagem.MOTIVO_ATE_INVALIDO: "sondagem_motivo_ate_invalido",
    sondagem.MOTIVO_INTERVALO_INVALIDO:
        "sondagem_motivo_intervalo_invalido",
    sondagem.MOTIVO_DE_NEGATIVO: "sondagem_motivo_de_negativo",
    sondagem.MOTIVO_ATE_NAO_MAIOR: "sondagem_motivo_ate_nao_maior",
    sondagem.MOTIVO_UNIDADE_INVALIDA: "sondagem_motivo_unidade_invalida",
}

ROTULOS_EXPORTACAO = {
    "linha": "sondagem_coluna_linha",
    "furo": "sondagem_coluna_furo",
    "de_original": "sondagem_coluna_de_original",
    "ate_original": "sondagem_coluna_ate_original",
    "unidade": "sondagem_coluna_unidade",
    "de_m": "sondagem_coluna_de",
    "ate_m": "sondagem_coluna_ate",
    "espessura_m": "sondagem_coluna_espessura",
    "litologia": "sondagem_coluna_litologia",
    "amostra": "sondagem_coluna_amostra",
    "observacao": "sondagem_coluna_observacao",
    "situacao": "sondagem_coluna_situacao",
    "motivo": "sondagem_coluna_motivo",
}


def _rotulo_situacao(codigo):
    """Rotulo traduzido de um codigo estavel de situacao."""

    return t(
        SITUACOES_I18N.get(
            codigo,
            "sondagem_situacao_desconhecida",
        )
    )


def _texto_motivos(item):
    """Junta os motivos traduzidos de uma linha invalida."""

    motivos = item.get("motivos") or []

    if not motivos:
        return t("sondagem_motivo_generico")

    return "; ".join(
        t(MOTIVOS_I18N.get(codigo, "sondagem_motivo_generico"))
        for codigo in motivos
    )


def _rotulos_exportacao():
    """Mapa de coluna tecnica para rotulo do idioma ativo."""

    return {
        campo: t(chave)
        for campo, chave in ROTULOS_EXPORTACAO.items()
    }


def _mensagem_erro(erro):
    """Traduz o erro de contrato devolvido pelo parser."""

    if isinstance(erro, sondagem.SondagemError):
        if erro.codigo == "cabecalhos_obrigatorios":
            return tf(
                "sondagem_erro_cabecalhos",
                campos=erro.detalhe or "furo, de, ate",
            )

        if erro.codigo == "tabela_vazia":
            return t("sondagem_erro_tabela_vazia")

        if erro.codigo == "sem_linhas":
            return t("sondagem_erro_sem_linhas")

        if erro.codigo == "cabecalhos_ausentes":
            return t("sondagem_erro_cabecalhos_ausentes")

        if erro.codigo == "tabela_desalinhada":
            return tf(
                "sondagem_erro_tabela_desalinhada",
                linhas=erro.detalhe or "?",
            )

        if erro.codigo == sondagem.CODIGO_TEMPO_EXCEDIDO:
            return tf(
                "sondagem_erro_tempo_excedido",
                segundos=erro.detalhe or "?",
            )

    return t("sondagem_erro_leitura")


def _dataframe_intervalos(intervalos):
    """Grade principal com cabecalhos traduzidos."""

    return pd.DataFrame(
        {
            t("sondagem_coluna_linha"): [
                item.get("linha") for item in intervalos
            ],
            t("sondagem_coluna_furo"): [
                item.get("furo") or "" for item in intervalos
            ],
            t("sondagem_coluna_de"): [
                item.get("de_m") for item in intervalos
            ],
            t("sondagem_coluna_ate"): [
                item.get("ate_m") for item in intervalos
            ],
            t("sondagem_coluna_espessura"): [
                item.get("espessura_m") for item in intervalos
            ],
            t("sondagem_coluna_litologia"): [
                item.get("litologia") or "" for item in intervalos
            ],
            t("sondagem_coluna_amostra"): [
                item.get("amostra") or "" for item in intervalos
            ],
            t("sondagem_coluna_observacao"): [
                item.get("observacao") or "" for item in intervalos
            ],
            t("sondagem_coluna_situacao"): [
                _rotulo_situacao(item.get("situacao"))
                for item in intervalos
            ],
        }
    )


def _dataframe_invalidos(invalidos):
    """Relatorio de linhas recusadas, sem descartar o restante."""

    return pd.DataFrame(
        {
            t("sondagem_coluna_linha"): [
                item.get("linha") for item in invalidos
            ],
            t("sondagem_coluna_furo"): [
                item.get("furo") or "" for item in invalidos
            ],
            t("sondagem_coluna_de_original"): [
                item.get("de_original") or "" for item in invalidos
            ],
            t("sondagem_coluna_ate_original"): [
                item.get("ate_original") or "" for item in invalidos
            ],
            t("sondagem_coluna_litologia"): [
                item.get("litologia") or "" for item in invalidos
            ],
            t("sondagem_coluna_motivo"): [
                _texto_motivos(item) for item in invalidos
            ],
        }
    )


def _dataframe_sobreposicoes(sobreposicoes):
    """Tabela de conflitos de profundidade entre intervalos do mesmo furo."""

    return pd.DataFrame(
        {
            t("sondagem_coluna_furo"): [
                item.get("furo") for item in sobreposicoes
            ],
            t("sondagem_coluna_linha"): [
                item.get("linha") for item in sobreposicoes
            ],
            t("sondagem_coluna_de"): [
                item.get("de_m") for item in sobreposicoes
            ],
            t("sondagem_coluna_ate"): [
                item.get("ate_m") for item in sobreposicoes
            ],
            t("sondagem_coluna_anterior"): [
                item.get("anterior_linha")
                for item in sobreposicoes
            ],
            t("sondagem_coluna_sobreposicao"): [
                item.get("sobreposicao_m")
                for item in sobreposicoes
            ],
        }
    )


def _dataframe_lacunas(lacunas):
    """Tabela de vaos entre intervalos consecutivos do mesmo furo."""

    return pd.DataFrame(
        {
            t("sondagem_coluna_furo"): [
                item.get("furo") for item in lacunas
            ],
            t("sondagem_coluna_linha"): [
                item.get("linha") for item in lacunas
            ],
            t("sondagem_coluna_de"): [
                item.get("de_m") for item in lacunas
            ],
            t("sondagem_coluna_ate"): [
                item.get("ate_m") for item in lacunas
            ],
            t("sondagem_coluna_anterior"): [
                item.get("anterior_linha") for item in lacunas
            ],
            t("sondagem_coluna_lacuna"): [
                item.get("lacuna_m") for item in lacunas
            ],
        }
    )


def _filtrar(intervalos, furo, litologias, situacoes, busca):
    """Aplica os filtros da grade preservando a ordem canonica."""

    termo = (busca or "").strip().casefold()
    filtrados = []

    for item in intervalos:
        if furo and item.get("furo") != furo:
            continue

        if litologias and item.get("litologia") not in litologias:
            continue

        if situacoes and item.get("situacao") not in situacoes:
            continue

        if termo:
            texto = " ".join(
                str(item.get(campo) or "")
                for campo in (
                    "furo",
                    "litologia",
                    "amostra",
                    "observacao",
                )
            ).casefold()

            if termo not in texto:
                continue

        filtrados.append(item)

    return filtrados


def _painel_filtros(intervalos, chave):
    """Desenha os filtros e devolve a tupla de selecao.

    Recebe apenas a lista de intervalos (referencia) em vez do
    dicionario de resultado inteiro: os filtros nao precisam dos
    relatorios, dos invalidos nem dos metadados da analise.
    """

    intervalos = intervalos or []
    furos = sorted(
        {item["furo"] for item in intervalos},
        key=str.casefold,
    )
    litologias = sorted(
        {
            item["litologia"]
            for item in intervalos
            if item.get("litologia")
        },
        key=str.casefold,
    )
    presentes = [
        situacao
        for situacao in sondagem.SITUACOES
        if any(
            item.get("situacao") == situacao
            for item in intervalos
        )
    ]

    st.markdown(f"**{t('sondagem_filtros')}**")
    colunas = st.columns([0.28, 0.36, 0.36])

    opcoes_furo = [t("sondagem_filtro_todos_furos"), *furos]
    chave_furo = f"{chave}_filtro_furo"

    if st.session_state.get(chave_furo) not in opcoes_furo:
        st.session_state[chave_furo] = opcoes_furo[0]

    with colunas[0]:
        furo_escolhido = st.selectbox(
            t("sondagem_filtro_furo"),
            opcoes_furo,
            key=chave_furo,
        )

    chave_litologia = f"{chave}_filtro_litologia"

    with colunas[1]:
        litologias_escolhidas = st.multiselect(
            t("sondagem_filtro_litologia"),
            litologias,
            default=litologias,
            key=chave_litologia,
        )

    chave_situacao = f"{chave}_filtro_situacao"

    with colunas[2]:
        situacoes_escolhidas = st.multiselect(
            t("sondagem_filtro_situacao"),
            presentes,
            default=presentes,
            format_func=_rotulo_situacao,
            key=chave_situacao,
        )

    busca = st.text_input(
        t("sondagem_filtro_busca"),
        placeholder=t("sondagem_busca_placeholder"),
        key=f"{chave}_filtro_busca",
    )
    furo = (
        None
        if furo_escolhido == t("sondagem_filtro_todos_furos")
        else furo_escolhido
    )

    return furo, litologias_escolhidas, situacoes_escolhidas, busca


def _renderizar_resultado(resultado, chave):
    """Cartao, filtros, grade, relatorios e downloads."""

    total_validos = resultado.get("total_validos", 0)
    total_invalidos = resultado.get("total_invalidos", 0)
    total_sobreposicoes = resultado.get("total_sobreposicoes", 0)
    total_lacunas = resultado.get("total_lacunas", 0)

    st.caption(
        tf(
            "sondagem_sucesso",
            n=total_validos,
            furos=resultado.get("total_furos", 0),
        )
    )

    colunas = st.columns(4)

    with colunas[0]:
        st.metric(
            t("sondagem_metric_intervalos"),
            total_validos,
        )

    with colunas[1]:
        st.metric(
            t("sondagem_metric_invalidos"),
            total_invalidos,
        )

    with colunas[2]:
        st.metric(
            t("sondagem_metric_sobreposicoes"),
            total_sobreposicoes,
        )

    with colunas[3]:
        st.metric(
            t("sondagem_metric_lacunas"),
            total_lacunas,
        )

    if total_invalidos:
        st.warning(
            tf("sondagem_aviso_invalidos", n=total_invalidos),
            icon=":material/error:",
        )

    if total_sobreposicoes:
        st.warning(
            tf(
                "sondagem_aviso_sobreposicoes",
                n=total_sobreposicoes,
            ),
            icon=":material/warning:",
        )

    if total_lacunas:
        st.warning(
            tf("sondagem_aviso_lacunas", n=total_lacunas),
            icon=":material/straighten:",
        )

    furo, litologias, situacoes, busca = _painel_filtros(
        resultado.get("intervalos") or [],
        chave,
    )
    filtrados = _filtrar(
        resultado.get("intervalos") or [],
        furo,
        litologias,
        situacoes,
        busca,
    )

    if filtrados:
        st.dataframe(
            _dataframe_intervalos(filtrados),
            width="stretch",
            hide_index=True,
            alt=tf(
                "sondagem_grade_alt",
                n=len(filtrados),
            ),
        )
        st.caption(
            tf(
                "sondagem_contagem_exibida",
                exibidos=len(filtrados),
                total=total_validos,
            )
        )
    else:
        st.info(
            t("sondagem_sem_resultado_filtro"),
            icon=":material/filter_alt_off:",
        )

    if total_invalidos:
        with st.expander(
            tf("sondagem_invalidos_titulo", n=total_invalidos),
            expanded=False,
        ):
            st.dataframe(
                _dataframe_invalidos(resultado.get("invalidos") or []),
                width="stretch",
                hide_index=True,
                alt=t("sondagem_invalidos_alt"),
            )

    if total_sobreposicoes:
        with st.expander(
            tf(
                "sondagem_sobreposicoes_titulo",
                n=total_sobreposicoes,
            ),
            expanded=False,
        ):
            st.dataframe(
                _dataframe_sobreposicoes(
                    resultado.get("sobreposicoes") or []
                ),
                width="stretch",
                hide_index=True,
                alt=t("sondagem_sobreposicoes_alt"),
            )

    if total_lacunas:
        with st.expander(
            tf("sondagem_lacunas_titulo", n=total_lacunas),
            expanded=False,
        ):
            st.dataframe(
                _dataframe_lacunas(
                    resultado.get("lacunas") or []
                ),
                width="stretch",
                hide_index=True,
                alt=t("sondagem_lacunas_alt"),
            )

    st.caption(t("sondagem_aviso_neutralizacao"))
    _exportacoes(resultado, chave)


def _assinatura_vigente(resultado):
    """Assinatura leve da grade, reaproveitando a do servico quando ha."""

    assinatura = (resultado or {}).get("assinatura")

    if isinstance(assinatura, str) and assinatura:
        return assinatura

    return sondagem.assinatura_resultado(resultado or {})


def _bytes_exportacao(resultado, formato):
    """Bytes de CSV/XLSX em cache por assinatura e idioma.

    A geracao e deterministica: a mesma grade no mesmo idioma produz os
    mesmos bytes. Guardar o resultado por assinatura evita reserializar
    a tabela inteira (e recriar o XLSX em memoria) a cada rerun — a tela
    apenas reutiliza a referencia leve. O dicionario e podado para a
    assinatura vigente, entao o cache nao cresce entre analises.
    """

    assinatura = _assinatura_vigente(resultado)
    idioma = str(st.session_state.get("idioma") or "pt")
    chave_cache = f"{formato}:{idioma}"
    cache = st.session_state.get(CHAVE_EXPORTACOES)

    if not isinstance(cache, dict):
        cache = {}

    entrada = cache.get(assinatura)

    if not isinstance(entrada, dict):
        entrada = {}

    dados = entrada.get(chave_cache)

    if dados is None:
        rotulos = _rotulos_exportacao()

        if formato == "csv":
            dados = sondagem.gerar_csv_sondagem(
                resultado,
                rotulos=rotulos,
            )
        else:
            dados = sondagem.gerar_xlsx_sondagem(
                resultado,
                rotulos=rotulos,
            )

        entrada[chave_cache] = dados

    st.session_state[CHAVE_EXPORTACOES] = {assinatura: entrada}

    return dados


def _exportacoes(resultado, chave):
    """CSV e XLSX sanitizados, em memoria, com cache por assinatura."""

    colunas = st.columns(2)

    with colunas[0]:
        st.download_button(
            t("sondagem_exportar_csv"),
            data=_bytes_exportacao(resultado, "csv"),
            file_name=t("sondagem_arquivo_csv"),
            mime="text/csv",
            key=f"{chave}_csv",
            icon=":material/download:",
            width="stretch",
            help=t("sondagem_ajuda_csv"),
        )

    with colunas[1]:
        st.download_button(
            t("sondagem_exportar_xlsx"),
            data=_bytes_exportacao(resultado, "xlsx"),
            file_name=t("sondagem_arquivo_xlsx"),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            key=f"{chave}_xlsx",
            icon=":material/download:",
            width="stretch",
            help=t("sondagem_ajuda_xlsx"),
        )


def _analisar_etapa(texto_atual, cancelamento=None):
    """Executa a analise uma unica vez por texto (idempotente).

    Devolve (resultado, erro). Quando o texto nao mudou desde a ultima
    analise bem-sucedida, devolve a grade ja armazenada sem reexecutar o
    parser. Em falha ou cancelamento devolve erro e preserva a grade
    anterior: a tela nunca fica com estado parcial nem perde um
    resultado valido por causa de uma tentativa malsucedida.
    """

    assinatura_texto = sondagem.hash_texto(texto_atual)
    atual = st.session_state.get(CHAVE_RESULTADO)

    if (
        atual is not None
        and st.session_state.get(CHAVE_ASSINATURA_TEXTO)
        == assinatura_texto
    ):
        return atual, None

    try:
        novo = sondagem.analisar_sondagem(
            texto_atual,
            cancelamento=cancelamento,
            prazo_s=TEMPO_LIMITE_ANALISE_S,
        )
    except progress_service.CancelamentoSolicitado:
        return None, t("sondagem_erro_cancelada")
    except sondagem.SondagemError as erro:
        return None, _mensagem_erro(erro)

    st.session_state[CHAVE_RESULTADO] = novo
    st.session_state[CHAVE_ASSINATURA_TEXTO] = assinatura_texto
    st.session_state[CHAVE_ASSINATURA_RESULTADO] = _assinatura_vigente(novo)
    st.session_state.pop(CHAVE_EXPORTACOES, None)

    return novo, None


def renderizar_aba_sondagem(
    texto=None,
    resultado=None,
    chave="aba_sondagem",
    cancelamento=None,
):
    """Renderiza a Aba 4 completa e devolve o resultado em uso.

    cancelamento e opcional e segue o contrato de
    services.progress_service: quando o Event e setado, a analise levanta
    CancelamentoSolicitado e a tela mostra o aviso traduzido sem gravar
    grade parcial.
    """

    st.subheader(t("sondagem_titulo"))
    st.caption(t("sondagem_caption"))

    if texto is not None:
        st.session_state[CHAVE_TEXTO] = texto

    if resultado is not None:
        st.session_state[CHAVE_RESULTADO] = resultado
        st.session_state[CHAVE_ASSINATURA_RESULTADO] = _assinatura_vigente(
            resultado
        )
        # Uma grade injetada por outro chamador nao tem relacao provada
        # com o texto da caixa: a proxima analise deve reexecutar.
        st.session_state.pop(CHAVE_ASSINATURA_TEXTO, None)
        st.session_state.pop(CHAVE_EXPORTACOES, None)

    st.session_state.setdefault(CHAVE_TEXTO, t("sondagem_exemplo"))
    primeira_abertura = CHAVE_INICIALIZADO not in st.session_state
    st.session_state[CHAVE_INICIALIZADO] = True

    texto_atual = st.text_area(
        t("sondagem_texto_rotulo"),
        key=CHAVE_TEXTO,
        height=230,
        help=t("sondagem_texto_ajuda"),
    )

    colunas = st.columns([0.62, 0.38])

    with colunas[0]:
        analisar = st.button(
            t("sondagem_analisar"),
            key=f"{chave}_analisar",
            icon=":material/fact_check:",
            type="primary",
            width="stretch",
        )

    with colunas[1]:
        limpar = st.button(
            t("sondagem_limpar"),
            key=f"{chave}_limpar",
            icon=":material/restart_alt:",
            width="stretch",
        )

    if limpar:
        for chave_estado in (
            CHAVE_RESULTADO,
            CHAVE_ERRO,
            CHAVE_ASSINATURA_TEXTO,
            CHAVE_ASSINATURA_RESULTADO,
            CHAVE_EXPORTACOES,
        ):
            st.session_state.pop(chave_estado, None)

    if analisar:
        _, erro = _analisar_etapa(texto_atual, cancelamento)

        if erro:
            st.session_state[CHAVE_ERRO] = erro
        else:
            st.session_state.pop(CHAVE_ERRO, None)

    # Primeira abertura: o exemplo bilingue ja aparece analisado. Isso
    # deixa a grade inspecionavel sem exigir um clique inicial. O flag
    # impede que "Limpar resultado" seja desfeito por uma nova analise
    # automatica no mesmo rerun.
    if (
        primeira_abertura
        and CHAVE_RESULTADO not in st.session_state
        and CHAVE_ERRO not in st.session_state
        and texto_atual.strip()
    ):
        _, erro = _analisar_etapa(texto_atual, cancelamento)

        if erro:
            st.session_state[CHAVE_ERRO] = erro

    erro = st.session_state.get(CHAVE_ERRO)

    if erro:
        st.error(erro, icon=":material/error:")

    resultado_atual = st.session_state.get(CHAVE_RESULTADO)

    if resultado_atual is not None:
        _renderizar_resultado(resultado_atual, chave)

    return resultado_atual
