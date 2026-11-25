"""Barra lateral modular da Fase D1.

O módulo reúne as seções determinísticas da barra lateral:

* seletor de idioma PT-BR/EN com atualização imediata (rerun);
* indicador compacto do Ollama, do modelo ativo e da origem do
  roteamento (SLM local, regra ou fallback determinístico);
* indicador de rede (Online x Cache Offline por Folha CIM) e o
  diretório de persistência resolvido;
* histórico transacional no SQLite, com migração aditiva do JSON
  legado, botão de nova conversa, marcadores de workflow/folha CIM e
  exclusão em cascata;
* encerramento limpo do servidor, das threads auxiliares e dos
  subprocessos iniciados pelo aplicativo, sem resíduos no Windows.

O ``app.py`` continua dono do layout: ele decide onde cada seção
entra e mantém o restante da barra lateral (documentos, fontes e
perfil). Aqui só vive o que a D1 isolou, com estado lido de
``st.session_state`` e persistência delegada a
``services.history_db``.

Todos os textos visíveis vêm de ``utils.i18n`` (PT-BR e EN).
"""

from __future__ import annotations

import os
import sys
import threading
import time

from config import DIRETORIO_DADOS, OLLAMA_MODEL
from services import history_db, llm_service
from services.history_service import agora_iso, novo_session_id
from ui import tab_chat
from utils.i18n import (
    IDIOMA_PADRAO,
    NOMES_IDIOMA,
    ROTULOS_IDIOMA,
    t,
    tf,
)

# ---------------------------------------------------------------------------
# Idioma
# ---------------------------------------------------------------------------


def renderizar_seletor_idioma():
    """Dois botões de bandeira no topo absoluto da barra lateral.

    O botão do idioma ativo é primário. O clique troca a chave
    ``idioma`` e força um rerun: a interface inteira (sidebar, aba de
    consulta e mensagens) é redesenhada no idioma escolhido, sem
    reiniciar a sessão nem perder o estado da conversa.
    """

    import streamlit as st

    idioma = st.session_state.get("idioma", IDIOMA_PADRAO)

    col_pt, col_en = st.columns(2)

    with col_pt:
        if st.button(
            ROTULOS_IDIOMA["pt"],
            key="idioma_pt",
            type="primary" if idioma == "pt" else "secondary",
            width="stretch",
            help=NOMES_IDIOMA["pt"],
        ):
            st.session_state["idioma"] = "pt"
            st.rerun()

    with col_en:
        if st.button(
            ROTULOS_IDIOMA["en"],
            key="idioma_en",
            type="primary" if idioma == "en" else "secondary",
            width="stretch",
            help=NOMES_IDIOMA["en"],
        ):
            st.session_state["idioma"] = "en"
            st.rerun()

    return idioma


# ---------------------------------------------------------------------------
# Indicadores de serviço, rede e persistência
# ---------------------------------------------------------------------------

_CHAVE_ROTEADOR = {
    "llm": "servico_roteador",
    "regra": "servico_roteador_regra",
    "heuristica": "servico_roteador_fallback",
}


def _chave_roteador(roteamento):
    """Chave i18n da origem da decisão de roteamento."""

    origem = ""

    if isinstance(roteamento, dict):
        origem = str(roteamento.get("origem") or "").strip().lower()

    return _CHAVE_ROTEADOR.get(origem, "servico_roteador_pendente")


def renderizar_indicadores_servico(
    modelo=None,
    ollama_online=False,
    roteamento=None,
):
    """Badge do Ollama, modelo ativo e origem do roteador."""

    import streamlit as st

    modelo = modelo or OLLAMA_MODEL
    online = bool(ollama_online)

    st.badge(
        tf(
            "servico_ollama_online" if online else "servico_ollama_offline",
            modelo=modelo,
        ),
        color="green" if online else "red",
        icon=(
            ":material/check_circle:" if online else ":material/error:"
        ),
        help=t("ajuda_servico_ollama"),
    )

    st.caption(
        f"🧭 {t(_chave_roteador(roteamento))}",
        help=t("ajuda_servico_roteador"),
    )


def renderizar_estado_rede(ollama_online=False, folhas_cache=0):
    """Indicador Online x Cache Offline por Folha CIM."""

    import streamlit as st

    folhas = max(int(folhas_cache or 0), 0)

    if ollama_online:
        st.badge(
            t("rede_online"),
            color="green",
            icon=":material/wifi:",
            help=t("ajuda_rede_online"),
        )
        return

    if folhas:
        st.badge(
            t("rede_cache_folha_cim"),
            color="orange",
            icon=":material/wifi_off:",
            help=t("ajuda_rede_cache"),
        )
        st.caption(tf("rede_cache_folhas", n=folhas))
        return

    st.badge(
        t("rede_offline_sem_cache"),
        color="red",
        icon=":material/wifi_off:",
        help=t("ajuda_rede_cache"),
    )


def renderizar_diretorio_dados():
    """Diretório de persistência resolvido e de onde ele veio."""

    import streamlit as st

    if os.getenv("ASSISTENTE_DATA_DIR", "").strip():
        chave_origem = "dados_origem_env"
    elif getattr(sys, "frozen", False):
        chave_origem = "dados_origem_localappdata"
    else:
        chave_origem = "dados_origem_projeto"

    st.caption(
        tf("dados_diretorio", caminho=str(DIRETORIO_DADOS)),
        help=t("ajuda_dados_diretorio"),
    )
    st.caption(t(chave_origem))


def renderizar_indicadores(modelo=None, ollama_online=False, roteamento=None):
    """Bloco compacto de saúde, rede e persistência da barra lateral."""

    try:
        folhas_cache = history_db.contar_folhas_cache()
    except Exception:  # noqa: BLE001 - indicador nunca derruba a sidebar
        folhas_cache = 0

    renderizar_indicadores_servico(
        modelo=modelo,
        ollama_online=ollama_online,
        roteamento=roteamento,
    )
    renderizar_estado_rede(
        ollama_online=ollama_online,
        folhas_cache=folhas_cache,
    )
    renderizar_diretorio_dados()


# ---------------------------------------------------------------------------
# Estado da conversa
# ---------------------------------------------------------------------------


def _mensagens():
    """Lista de mensagens da sessão, sempre uma lista."""

    import streamlit as st

    mensagens = st.session_state.get("mensagens")

    return mensagens if isinstance(mensagens, list) else []


def folhas_cim_da_conversa(mensagens=None):
    """Folhas CIM citadas nas respostas, em ordem estável e sem repetição."""

    mensagens = mensagens if mensagens is not None else _mensagens()
    folhas = []

    for mensagem in mensagens or ():
        if not isinstance(mensagem, dict):
            continue

        for feicao in mensagem.get("feicoes_espaciais") or ():
            if not isinstance(feicao, dict):
                continue

            folha = str(feicao.get("folha_cim") or "").strip().upper()

            if folha and folha not in folhas:
                folhas.append(folha)

    return folhas


def salvar_conversa_atual():
    """Autosave silencioso da conversa no SQLite.

    Só avisos de falha aparecem na interface: uma gravação bem-sucedida
    não polui a barra lateral a cada resposta.
    """

    import streamlit as st

    mensagens = _mensagens()

    if not mensagens:
        return False

    session_id = st.session_state.get("session_id")

    if not session_id:
        return False

    workflow = tab_chat.workflow_do_rotulo(
        st.session_state.get(tab_chat.CHAVE_WORKFLOW)
    ) or tab_chat.WORKFLOW_PADRAO
    folhas = folhas_cim_da_conversa(mensagens)

    try:
        salvo = history_db.salvar_conversa(
            session_id,
            st.session_state.get("titulo_conversa") or "",
            mensagens,
            workflow=workflow,
            folha_cim=", ".join(folhas[:8]),
        )
    except history_db.HistoricoBDError:
        st.session_state["historico_aviso"] = (
            "erro",
            t("aviso_historico_salvar_erro"),
        )
        return False

    if salvo:
        st.session_state["conversa_ativa_salva"] = True

    return salvo


def abrir_conversa(session_id):
    """Carrega uma conversa do SQLite no estado da sessão."""

    import streamlit as st

    try:
        conversa = history_db.carregar_conversa(session_id)
    except history_db.HistoricoBDError:
        conversa = None

    if conversa is None:
        st.session_state["historico_aviso"] = (
            "erro",
            t("aviso_abrir_erro"),
        )
        return

    mensagens = []

    for indice, mensagem in enumerate(conversa.get("mensagens") or ()):
        mensagem = dict(mensagem)
        mensagem["chave"] = indice
        mensagens.append(mensagem)

    st.session_state.mensagens = mensagens
    st.session_state.session_id = conversa["id"]
    st.session_state.titulo_conversa = conversa.get("titulo") or ""
    st.session_state.criado_em = conversa.get("criado_em")
    st.session_state.conversa_ativa_salva = True
    st.session_state.sequencia_resposta = len(mensagens)
    st.session_state["confirmar_apagar_tudo"] = False
    tab_chat.definir_workflow(conversa.get("workflow"))


def nova_conversa():
    """Grava a conversa atual e abre uma conversa em branco."""

    import streamlit as st

    salvar_conversa_atual()

    st.session_state.session_id = novo_session_id()
    st.session_state.criado_em = agora_iso()
    st.session_state.titulo_conversa = ""
    st.session_state.mensagens = []
    st.session_state.conversa_ativa_salva = False
    st.session_state.sequencia_resposta = 0
    st.session_state["confirmar_apagar_tudo"] = False
    tab_chat.definir_workflow(tab_chat.WORKFLOW_PADRAO)


def excluir_conversa(session_id):
    """Exclui uma conversa; se for a ativa, volta ao estado vazio."""

    import streamlit as st

    try:
        excluida = history_db.excluir_conversa(session_id)
    except history_db.HistoricoBDError:
        st.session_state["historico_aviso"] = (
            "erro",
            t("aviso_historico_excluir_erro"),
        )
        return

    if session_id == st.session_state.get("session_id"):
        st.session_state.session_id = novo_session_id()
        st.session_state.criado_em = agora_iso()
        st.session_state.titulo_conversa = ""
        st.session_state.mensagens = []
        st.session_state.conversa_ativa_salva = False
        st.session_state.sequencia_resposta = 0

    if excluida:
        st.session_state["historico_aviso"] = (
            "sucesso",
            t("aviso_conversa_excluida"),
        )


def apagar_todo_historico():
    """Apaga todas as conversas do SQLite e reinicia a sessão."""

    import streamlit as st

    try:
        apagadas = history_db.excluir_todas_conversas()
    except history_db.HistoricoBDError:
        st.session_state["historico_aviso"] = (
            "erro",
            t("aviso_historico_excluir_erro"),
        )
        st.session_state["confirmar_apagar_tudo"] = False
        return

    st.session_state.mensagens = []
    st.session_state.titulo_conversa = ""
    st.session_state.conversa_ativa_salva = False
    st.session_state.sequencia_resposta = 0
    st.session_state.session_id = novo_session_id()
    st.session_state.criado_em = agora_iso()
    st.session_state["confirmar_apagar_tudo"] = False
    tab_chat.definir_workflow(tab_chat.WORKFLOW_PADRAO)

    if apagadas:
        st.session_state["historico_aviso"] = (
            "sucesso",
            tf("aviso_historico_apagado", n=apagadas),
        )
    else:
        st.session_state["historico_aviso"] = (
            "sucesso",
            t("aviso_sem_conversas"),
        )


def cancelar_apagar_tudo():
    """Desarma a confirmação de exclusão total."""

    import streamlit as st

    st.session_state["confirmar_apagar_tudo"] = False


def _texto_curto(valor):
    """Texto em uma linha, para títulos e datas do histórico."""

    return " ".join(str(valor or "").split())


def _rotulo_conversa(conversa):
    """Rótulo do item do histórico: ícone (ou data) e título curto."""

    import streamlit as st

    titulo = _texto_curto(conversa.get("titulo")) or t("nova_conversa")

    if st.session_state.get("session_id") == conversa["id"]:
        return f":material/chat: {titulo}"

    return f":material/forum: {titulo}"


def _marcador_conversa(conversa):
    """Linha compacta com o workflow e a folha CIM da conversa."""

    partes = []
    workflow = conversa.get("workflow")

    if workflow:
        partes.append(
            tf(
                "historico_workflow_marcador",
                workflow=tab_chat.rotulo_workflow(workflow),
            )
        )

    folha = _texto_curto(conversa.get("folha_cim"))

    if folha:
        partes.append(tf("historico_folha_marcador", folha=folha))

    return " · ".join(partes)


def _exibir_aviso_historico():
    """Mostra e descarta o aviso pendente das ações do histórico."""

    import streamlit as st

    aviso = st.session_state.pop("historico_aviso", None)

    if not aviso:
        return

    tipo_aviso, mensagem_aviso = aviso

    if tipo_aviso == "sucesso":
        st.success(mensagem_aviso, icon=":material/check_circle:")
    else:
        st.error(mensagem_aviso, icon=":material/error:")


def renderizar_historico():
    """Lista o histórico SQLite e o bloco de exclusão em duas etapas.

    Devolve a quantidade de conversas listadas, usada pelo botão de
    exclusão em lote. Uma falha de banco não derruba a barra lateral:
    vira aviso e a lista fica vazia.
    """

    import streamlit as st

    st.subheader(t("secao_historico"))

    if st.button(
        t("sidebar_nova_conversa"),
        key="sidebar_nova_conversa",
        type="primary",
        width="stretch",
        help=t("ajuda_sidebar_nova_conversa"),
    ):
        nova_conversa()
        st.rerun()

    try:
        conversas = history_db.listar_conversas()
    except history_db.HistoricoBDError:
        conversas = []
        st.error(t("historico_sqlite_erro"))

    if not conversas:
        st.caption(t("historico_vazio"))
        _exibir_aviso_historico()
        return 0

    st.caption(tf("historico_contagem", n=len(conversas)))

    with st.container(key="historico_lista"):
        for conversa in conversas:
            session_id = conversa["id"]
            ativa = st.session_state.get("session_id") == session_id

            with st.container(key=f"historico_item_{session_id}"):
                col_titulo, col_del = st.columns(
                    [0.84, 0.16],
                    gap="small",
                    vertical_alignment="center",
                )

                with col_titulo:
                    st.button(
                        _rotulo_conversa(conversa),
                        key=f"abrir_{session_id}",
                        width="stretch",
                        type="primary" if ativa else "secondary",
                        disabled=ativa,
                        help=(
                            t("historico_aberta")
                            if ativa
                            else tf(
                                "historico_abrir",
                                data=_texto_curto(
                                    conversa.get("atualizado_em")
                                ),
                            )
                        ),
                        on_click=abrir_conversa,
                        args=(session_id,),
                    )

                    marcador = _marcador_conversa(conversa)

                    if marcador:
                        st.caption(marcador)

                with col_del:
                    st.button(
                        "",
                        key=f"historico_excluir_{session_id}",
                        icon=":material/delete:",
                        type="tertiary",
                        help=tf(
                            "historico_excluir",
                            titulo=conversa.get("titulo") or "",
                        ),
                        on_click=excluir_conversa,
                        args=(session_id,),
                    )

        mensagens = _mensagens()

        if not st.session_state.get("conversa_ativa_salva") and mensagens:
            st.caption(t("historico_nao_salva"))

    # Exclusão em duas etapas, logo abaixo da lista que ela apaga.
    if st.session_state.get("confirmar_apagar_tudo"):
        st.warning(
            t("confirmar_apagar_texto"),
            title=t("confirmar_apagar_titulo"),
        )

        if st.button(
            t("botao_apagar_confirmado"),
            key="apagar_todo_historico_confirmado",
            type="primary",
            width="stretch",
            help=t("ajuda_apagar_confirmado"),
            on_click=apagar_todo_historico,
        ):
            st.rerun()

        if st.button(
            t("botao_cancelar"),
            key="cancelar_apagar_tudo",
            width="stretch",
            help=t("ajuda_cancelar"),
            on_click=cancelar_apagar_tudo,
        ):
            st.rerun()
    elif st.button(
        t("botao_apagar_tudo"),
        key="apagar_todo_historico",
        type="secondary",
        width="stretch",
        disabled=not conversas,
        help=t("ajuda_apagar_tudo"),
    ):
        st.session_state["confirmar_apagar_tudo"] = True
        st.rerun()

    _exibir_aviso_historico()

    return len(conversas)


# ---------------------------------------------------------------------------
# Encerramento limpo
# ---------------------------------------------------------------------------


def _aguardar_threads(limite=1.0):
    """Aguarda por pouco tempo threads auxiliares não-daemon."""

    atual = threading.current_thread()
    principal = threading.main_thread()
    prazo = time.monotonic() + max(float(limite), 0.0)

    for thread in threading.enumerate():
        if thread in (atual, principal) or thread.daemon:
            continue

        restante = prazo - time.monotonic()

        if restante <= 0:
            break

        try:
            thread.join(min(restante, 0.25))
        except RuntimeError:
            continue


def encerrar_servidor():
    """Finaliza servidor, threads auxiliares e subprocessos filhos.

    A ordem é deliberada: primeiro os processos iniciados pelo próprio
    aplicativo (por exemplo, o serviço do Ollama), depois o runtime do
    Streamlit, depois uma curta espera pelas threads auxiliares. Um
    ``threading.Timer`` daemon garante a saída do processo caso a API
    interna do Streamlit mude — nunca deixa um processo residual no
    Windows.

    Devolve um dicionário com o que foi feito, útil para testes e log.
    """

    processos = 0

    try:
        processos = llm_service.encerrar_processos_iniciados()
    except Exception:  # noqa: BLE001 - encerramento nunca levanta
        processos = 0

    parou = False

    try:
        from streamlit.runtime import Runtime

        Runtime.instance().stop()
        parou = True
    except Exception:  # noqa: BLE001 - API interna indisponível
        parou = False

    _aguardar_threads(1.0 if parou else 0.2)

    def _sair_a_forca():
        """Sai do processo do servidor depois de desenhar o aviso."""

        os._exit(0)

    segundos = 5.0 if parou else 0.5
    timer = threading.Timer(segundos, _sair_a_forca)
    timer.daemon = True
    timer.start()

    return {"parou": parou, "processos": processos}


def renderizar_botao_encerramento():
    """Botão discreto de encerramento no fim da barra lateral."""

    import streamlit as st

    if st.button(
        t("encerrar_servidor"),
        key="encerrar_servidor",
        width="stretch",
        help=t("ajuda_encerrar_servidor"),
    ):
        encerrar_servidor()
        st.info(t("aviso_encerrando_servidor"))
        st.stop()