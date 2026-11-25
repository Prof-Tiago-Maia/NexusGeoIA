"""Progresso por etapa e cancelamento da consulta na interface (Fase D3a).

O trabalho longo roda em uma thread controlada (services.progress_service)
e este fragmento apenas observa o estado thread-safe. O fragmento com
run_every mantém o botão Cancelar clicável enquanto o restante do script
já retornou ao Streamlit, sem prender o st.chat_input nem a sessão.
"""

from __future__ import annotations

import streamlit as st

from services.progress_service import (
    STATUS_CANCELADO,
    STATUS_CONCLUIDO,
    STATUS_ERRO,
    STATUS_EXECUTANDO,
)
from utils.i18n import t

# Intervalo de atualização do fragmento. O cancelamento em si é
# imediato: o clique seta o threading.Event e fecha o stream do LLM.
INTERVALO_ATUALIZACAO_S = 0.5

# O clique precisa devolver a interface em menos de 3 s. O serviço
# fecha Event/sessões e cancela o Future antes de aguardar; 1,5 s deixa
# margem para o rerun do Streamlit mesmo quando uma fonte demora a sair.
LIMITE_CANCELAMENTO_S = 1.5

LIMITE_TEXTO_PARCIAL = 4000


def _rotulo_etapa(estado):
    """Texto traduzido da etapa atual, com detalhe técnico opcional."""

    etapa = t(estado.get("etapa") or "progresso_etapa_preparando")
    detalhe = str(estado.get("detalhe") or "").strip()

    if detalhe:
        return f"{etapa} · {detalhe}"

    return etapa


def _previa(estado):
    """Últimos caracteres do texto parcial entregue em streaming."""

    texto = str(estado.get("texto_parcial") or "")

    if len(texto) > LIMITE_TEXTO_PARCIAL:
        return texto[-LIMITE_TEXTO_PARCIAL:]

    return texto


@st.fragment(run_every=INTERVALO_ATUALIZACAO_S)
def renderizar_progresso_consulta(trabalho, chave=""):
    """Mostra etapa, prévia opcional e o botão de cancelamento."""

    if trabalho is None:
        return

    estado = trabalho.estado()
    status = estado.get("status")

    st.caption(t("progresso_titulo"))
    st.markdown(f"**{_rotulo_etapa(estado)}**")

    fracao = estado.get("fracao")

    if isinstance(fracao, (int, float)) and 0.0 <= float(fracao) <= 1.0:
        st.progress(float(fracao))

    texto = _previa(estado)

    if texto:
        with st.expander(t("progresso_texto_parcial"), expanded=True):
            st.markdown(texto)

    if status == STATUS_EXECUTANDO:
        if st.button(
            t("botao_cancelar_consulta"),
            key=f"cancelar_consulta_{chave or 'atual'}",
            type="secondary",
            width="stretch",
            help=t("ajuda_cancelar_consulta"),
        ):
            # O Event é setado e o stream é fechado imediatamente; o
            # worker cooperativo termina em poucos instantes.
            trabalho.cancelar(tempo_limite=LIMITE_CANCELAMENTO_S)
            st.rerun(scope="app")

        return

    if status == STATUS_CANCELADO:
        st.caption(t("status_cancelado"))
    elif status == STATUS_ERRO:
        st.caption(t("progresso_etapa_erro"))
    elif status == STATUS_CONCLUIDO:
        st.caption(t("progresso_etapa_concluida"))

    # O trabalho terminou enquanto este fragmento estava visível:
    # devolve o controle ao script principal para consolidar (ou
    # descartar) o resultado.
    st.rerun(scope="app")
