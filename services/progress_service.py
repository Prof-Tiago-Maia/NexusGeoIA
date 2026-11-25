"""Contrato de progresso por etapa e cancelamento cooperativo (Fase D3a).

Este modulo e a unica fonte de verdade para dois contratos usados pela
interface, pelo orquestrador (core.assistant), pelo LLM
(services.llm_service) e pelo pipeline documental
(services.document_parser / services.rag_service):

* **progresso por etapa** - um callback com a assinatura
  (etapa, fracao, detalhe), em que etapa e uma chave de utils.i18n
  (PT-BR e EN com paridade estrita), fracao e um float entre 0.0 e 1.0
  quando o andamento e mensuravel (ou None) e detalhe e um texto tecnico
  curto, sem traducao propria;
* **cancelamento** - um threading.Event (ou a subclasse
  EventoCancelamento) verificado antes e depois de cada pagina,
  conector/fonte e trecho do LLM. O cancelamento levanta
  CancelamentoSolicitado, que os chamadores tratam como fluxo normal
  (nao como erro de integracao).

O modulo nao importa streamlit: a interface apenas observa o estado
thread-safe de ControleProgresso / TrabalhoConsulta.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoTimeout
from typing import Any

# Callback padronizado: (etapa, fracao, detalhe).
ProgressoCallback = Callable[[str, float | None, str], None]

# Callback opcional de streaming de texto (cada trecho entregue pelo LLM).
TokenCallback = Callable[[str], None]

Fechamento = Callable[[], None]

# ---------------------------------------------------------------------------
# Etapas canonicas (chaves de utils.i18n, com paridade PT-BR / EN)
# ---------------------------------------------------------------------------

ETAPA_PREPARANDO = "progresso_etapa_preparando"
ETAPA_ROTEAMENTO = "progresso_etapa_roteamento"
ETAPA_SGB = "progresso_etapa_sgb"
ETAPA_DOCUMENTOS = "progresso_etapa_documentos"
ETAPA_DOCUMENTOS_CONSULTAS = "progresso_etapa_documentos_consultas"
ETAPA_DOCUMENTOS_INDICE = "progresso_etapa_documentos_indice"
ETAPA_DOCUMENTO_PAGINA = "progresso_etapa_documento_pagina"
ETAPA_DOCUMENTO_OCR = "progresso_etapa_documento_ocr"
ETAPA_ANA = "progresso_etapa_ana"
ETAPA_WEB = "progresso_etapa_web"
ETAPA_OPENALEX = "progresso_etapa_openalex"
ETAPA_USGS = "progresso_etapa_usgs"
ETAPA_INTL_GEO = "progresso_etapa_intl_geo"
ETAPA_GEOSGB = "progresso_etapa_geosgb"
ETAPA_ANM = "progresso_etapa_anm"
ETAPA_MACROSTRAT = "progresso_etapa_macrostrat"
ETAPA_SIAGAS = "progresso_etapa_siagas"
ETAPA_GEOSSIT = "progresso_etapa_geossit"
ETAPA_LLM = "progresso_etapa_llm"
ETAPA_CONCLUIDA = "progresso_etapa_concluida"
ETAPA_CANCELANDO = "progresso_etapa_cancelando"
ETAPA_CANCELADA = "progresso_etapa_cancelada"
ETAPA_ERRO = "progresso_etapa_erro"

ETAPAS = (
    ETAPA_PREPARANDO,
    ETAPA_ROTEAMENTO,
    ETAPA_SGB,
    ETAPA_DOCUMENTOS,
    ETAPA_DOCUMENTOS_CONSULTAS,
    ETAPA_DOCUMENTOS_INDICE,
    ETAPA_DOCUMENTO_PAGINA,
    ETAPA_DOCUMENTO_OCR,
    ETAPA_ANA,
    ETAPA_WEB,
    ETAPA_OPENALEX,
    ETAPA_USGS,
    ETAPA_INTL_GEO,
    ETAPA_GEOSGB,
    ETAPA_ANM,
    ETAPA_MACROSTRAT,
    ETAPA_SIAGAS,
    ETAPA_GEOSSIT,
    ETAPA_LLM,
    ETAPA_CONCLUIDA,
    ETAPA_CANCELANDO,
    ETAPA_CANCELADA,
    ETAPA_ERRO,
)

# Etapa exibida para cada chave de fonte do dicionario de dados.
ETAPA_POR_FONTE = {
    "sgb": ETAPA_SGB,
    "documentos": ETAPA_DOCUMENTOS,
    "ana": ETAPA_ANA,
    "web": ETAPA_WEB,
    "openalex": ETAPA_OPENALEX,
    "usgs": ETAPA_USGS,
    "intl_geo": ETAPA_INTL_GEO,
    "geosgb": ETAPA_GEOSGB,
    "anm": ETAPA_ANM,
    "macrostrat": ETAPA_MACROSTRAT,
    "siagas": ETAPA_SIAGAS,
    "geossit": ETAPA_GEOSSIT,
}

# ---------------------------------------------------------------------------
# Status de um trabalho em background
# ---------------------------------------------------------------------------

STATUS_PENDENTE = "pendente"
STATUS_EXECUTANDO = "executando"
STATUS_CONCLUIDO = "concluido"
STATUS_CANCELADO = "cancelado"
STATUS_ERRO = "erro"

STATUS_TERMINAIS = (STATUS_CONCLUIDO, STATUS_CANCELADO, STATUS_ERRO)

# Prazos explicitos dos fluxos cancelaveis. O cancelamento devolve o
# controle para a interface em ate 2 s e a coleta do resultado nunca
# espera mais de 3 s; quem chama deve tratar False como "ainda rodando"
# em vez de bloquear o st.chat_input.
TEMPO_LIMITE_CANCELAMENTO_S = 2.0
TEMPO_LIMITE_RESPOSTA_S = 3.0

# Executores vivos criados por TrabalhoConsulta. O registro permite
# provar (em testes e em diagnostico) que cancelar e iniciar uma nova
# consulta em sequencia nao acumula ThreadPoolExecutor nem threads.
_TRAVA_EXECUTORES = threading.Lock()
_EXECUTORES_ATIVOS: set[ThreadPoolExecutor] = set()


def _registrar_executor(executor: ThreadPoolExecutor) -> None:
    with _TRAVA_EXECUTORES:
        _EXECUTORES_ATIVOS.add(executor)


def _esquecer_executor(executor: ThreadPoolExecutor | None) -> None:
    if executor is None:
        return

    with _TRAVA_EXECUTORES:
        _EXECUTORES_ATIVOS.discard(executor)


def executores_do_trabalho() -> int:
    """Quantidade de executores ainda nao encerrados (diagnostico)."""

    with _TRAVA_EXECUTORES:
        return len(_EXECUTORES_ATIVOS)


class CancelamentoSolicitado(RuntimeError):
    """Fluxo normal de cancelamento cooperativo solicitado pelo usuario."""

    def __init__(self, etapa: str | None = None):
        self.etapa = etapa
        super().__init__(
            "Operacao cancelada"
            + (f" na etapa {etapa}." if etapa else ".")
        )


# ---------------------------------------------------------------------------
# Evento de cancelamento com fechamento de recursos
# ---------------------------------------------------------------------------

class EventoCancelamento(threading.Event):
    """threading.Event que tambem fecha streams/conexoes registrados.

    Herdar de threading.Event mantem a compatibilidade com qualquer
    chamador que aceite apenas is_set/set. Os fechamentos sao executados
    uma unica vez, em ordem reversa de registro, e nunca levantam
    excecao: o cancelamento precisa terminar mesmo se o recurso ja
    tiver sido fechado por outro caminho.
    """

    def __init__(self) -> None:
        super().__init__()
        self._trava = threading.Lock()
        self._fechamentos: list[Fechamento] = []

    def registrar_fechamento(self, fechamento: Fechamento | None):
        """Registra um fechamento e devolve o proprio callback."""

        if fechamento is None:
            return None

        with self._trava:
            self._fechamentos.append(fechamento)

        return fechamento

    def remover_fechamento(self, fechamento: Fechamento | None) -> None:
        if fechamento is None:
            return

        with self._trava:
            try:
                self._fechamentos.remove(fechamento)
            except ValueError:
                pass

    def fechar_recursos(self) -> int:
        """Executa todos os fechamentos pendentes e devolve a quantidade."""

        with self._trava:
            fechamentos = list(reversed(self._fechamentos))
            self._fechamentos.clear()

        for fechamento in fechamentos:
            try:
                fechamento()
            except Exception:  # noqa: BLE001, S110
                pass

        return len(fechamentos)

    def cancelar(self) -> None:
        """Marca o evento e fecha imediatamente os recursos registrados."""

        self.set()
        self.fechar_recursos()


# ---------------------------------------------------------------------------
# Funcoes de contrato
# ---------------------------------------------------------------------------

def evento_ativo(cancelamento: Any) -> bool:
    """Indica se o evento de cancelamento (ou equivalente) esta setado."""

    if cancelamento is None:
        return False

    try:
        return bool(cancelamento.is_set())
    except Exception:  # noqa: BLE001
        return False


def verificar_cancelamento(cancelamento: Any, etapa: str | None = None) -> None:
    """Levanta CancelamentoSolicitado se o evento estiver setado."""

    if evento_ativo(cancelamento):
        raise CancelamentoSolicitado(etapa)


def relatar(
    progresso: ProgressoCallback | None,
    etapa: str,
    fracao: float | None = None,
    detalhe: str = "",
) -> None:
    """Entrega uma atualizacao ao callback sem derrubar o fluxo.

    Um callback de interface nunca pode interromper a consulta: erros do
    observador sao silenciados, como ja acontecia no parser de documentos.
    """

    if progresso is None:
        return

    if fracao is not None:
        try:
            fracao = max(0.0, min(1.0, float(fracao)))
        except (TypeError, ValueError):
            fracao = None

    try:
        progresso(etapa, fracao, str(detalhe or ""))
    except Exception:  # noqa: BLE001, S110
        pass


# ---------------------------------------------------------------------------
# Controle de progresso (estado thread-safe observado pela UI)
# ---------------------------------------------------------------------------

class ControleProgresso:
    """Estado mutavel compartilhado entre a thread de trabalho e a UI."""

    def __init__(self, cancelamento: Any | None = None) -> None:
        self.evento = cancelamento if cancelamento is not None else EventoCancelamento()
        self._trava = threading.Lock()
        self._etapa = ETAPA_PREPARANDO
        self._fracao: float | None = None
        self._detalhe = ""
        self._texto_parcial = ""
        self._historico: list[str] = []
        self._atualizado_em = time.monotonic()

    # -- Estado ---------------------------------------------------------

    def relatar(
        self,
        etapa: str,
        fracao: float | None = None,
        detalhe: str = "",
    ) -> None:
        """Atualiza a etapa atual; chamado pela thread de trabalho."""

        with self._trava:
            self._etapa = str(etapa or ETAPA_PREPARANDO)
            self._fracao = fracao
            self._detalhe = str(detalhe or "")
            self._atualizado_em = time.monotonic()

            if not self._historico or self._historico[-1] != self._etapa:
                self._historico.append(self._etapa)
                del self._historico[:-24]

    def anexar_texto(self, texto: str) -> None:
        """Acumula o texto parcial entregue em streaming pelo LLM."""

        pedaco = str(texto or "")

        if not pedaco:
            return

        with self._trava:
            self._texto_parcial += pedaco

            # Um stream muito longo nao precisa manter todo o buffer na
            # memoria so para a previa da interface.
            if len(self._texto_parcial) > 200_000:
                self._texto_parcial = self._texto_parcial[-200_000:]

            self._atualizado_em = time.monotonic()

    def estado(self) -> dict:
        """Copia imutavel do estado atual, segura para a UI."""

        with self._trava:
            return {
                "etapa": self._etapa,
                "fracao": self._fracao,
                "detalhe": self._detalhe,
                "texto_parcial": self._texto_parcial,
                "historico": list(self._historico),
                "atualizado_em": self._atualizado_em,
            }

    @property
    def etapa(self) -> str:
        with self._trava:
            return self._etapa

    @property
    def cancelado(self) -> bool:
        return evento_ativo(self.evento)

    # -- Cancelamento ---------------------------------------------------

    def verificar(self, etapa: str | None = None) -> None:
        verificar_cancelamento(self.evento, etapa or self.etapa)

    def registrar_fechamento(self, fechamento: Fechamento | None):
        registrar = getattr(self.evento, "registrar_fechamento", None)

        if callable(registrar):
            return registrar(fechamento)

        return None

    def remover_fechamento(self, fechamento: Fechamento | None) -> None:
        remover = getattr(self.evento, "remover_fechamento", None)

        if callable(remover):
            remover(fechamento)

    def cancelar(self) -> None:
        """Solicita o cancelamento e fecha os recursos registrados."""

        cancelar = getattr(self.evento, "cancelar", None)

        if callable(cancelar):
            cancelar()
        else:
            self.evento.set()

        self.relatar(ETAPA_CANCELANDO, None, "")


# ---------------------------------------------------------------------------
# Trabalho em background (UI responsiva)
# ---------------------------------------------------------------------------

class TrabalhoConsulta:
    """Executa uma operacao longa em uma thread controlada.

    A funcao executar recebe o ControleProgresso e devolve o resultado.
    A UI nunca chama st.* daqui: apenas consulta estado(), chama
    cancelar() e coleta o resultado.
    """

    def __init__(
        self,
        executar: Callable[[ControleProgresso], Any],
        *,
        nome: str = "consulta",
        controle: ControleProgresso | None = None,
    ) -> None:
        self._executar = executar
        self.controle = controle or ControleProgresso()
        self._trava = threading.Lock()
        self._status = STATUS_PENDENTE
        self._resultado = None
        self._erro: BaseException | None = None
        self._iniciado_em: float | None = None
        self._finalizado_em: float | None = None
        self._nome = str(nome or "consulta")
        # O executor nasce apenas em iniciar(): um trabalho criado pela
        # interface e descartado antes do clique nao abre thread alguma.
        self._executor: ThreadPoolExecutor | None = None
        self._future = None

    # -- Ciclo de vida --------------------------------------------------

    def iniciar(self) -> TrabalhoConsulta:
        with self._trava:
            if self._status != STATUS_PENDENTE:
                return self

            self._status = STATUS_EXECUTANDO
            self._iniciado_em = time.monotonic()
            executor = self._executor

            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix=f"nexusgeo-{self._nome}",
                )
                self._executor = executor
                _registrar_executor(executor)

            self._future = executor.submit(self._rodar)

        return self

    def _rodar(self) -> None:
        try:
            # O worker nao comeca nem termina uma etapa depois de um
            # cancelamento: a verificacao vale para qualquer funcao
            # executar, mesmo as que nao consultam fontes externas.
            self.controle.verificar()
            resultado = self._executar(self.controle)
            self.controle.verificar()
        except CancelamentoSolicitado as erro:
            self._definir(STATUS_CANCELADO, erro=erro)
        except BaseException as erro:  # noqa: BLE001 - repassado a UI
            self._definir(STATUS_ERRO, erro=erro)
        else:
            if self.controle.cancelado:
                self._definir(
                    STATUS_CANCELADO,
                    erro=CancelamentoSolicitado(self.controle.etapa),
                )
            else:
                self._definir(STATUS_CONCLUIDO, resultado=resultado)
        finally:
            # Nunca fazer join da propria thread: o worker apenas marca
            # o executor como encerrado. cancelar()/descartar() fazem o
            # join definitivo quando o Future ja terminou.
            executor = self._executor

            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:  # noqa: BLE001, S110
                    pass

                _esquecer_executor(executor)

    def _definir(
        self,
        status: str,
        *,
        resultado: Any = None,
        erro: BaseException | None = None,
    ) -> None:
        with self._trava:
            if self._status in STATUS_TERMINAIS:
                return

            self._status = status
            self._resultado = resultado
            self._erro = erro
            self._finalizado_em = time.monotonic()

    # -- Observacao -----------------------------------------------------

    @property
    def resultado(self) -> Any:
        with self._trava:
            return self._resultado

    @property
    def erro(self) -> BaseException | None:
        with self._trava:
            return self._erro

    @property
    def status(self) -> str:
        with self._trava:
            return self._status

    def estado(self) -> dict:
        with self._trava:
            status = self._status
            resultado = self._resultado
            erro = self._erro
            iniciado = self._iniciado_em
            finalizado = self._finalizado_em

        estado = dict(self.controle.estado())
        estado.update({
            "status": status,
            "terminal": status in STATUS_TERMINAIS,
            "cancelado": (
                status == STATUS_CANCELADO or self.controle.cancelado
            ),
            "resultado_disponivel": resultado is not None,
            "erro": None if erro is None else type(erro).__name__,
            "erro_mensagem": None if erro is None else str(erro),
            "decorrido_s": (
                None
                if iniciado is None
                else round((finalizado or time.monotonic()) - iniciado, 3)
            ),
        })

        return estado

    # -- Encerramento ---------------------------------------------------

    def aguardar(
        self,
        tempo_limite: float = TEMPO_LIMITE_RESPOSTA_S,
    ) -> bool:
        """Aguarda a thread terminar; devolve True se ja terminou.

        O prazo e explicito e o retorno False nunca e ambíguo: significa
        que o worker ainda esta rodando. A interface usa isso para
        redesenhar o progresso em vez de esperar indefinidamente.
        """

        future = self._future

        if future is None:
            return self.status in STATUS_TERMINAIS

        if future.cancelled():
            return True

        try:
            future.result(timeout=max(0.0, float(tempo_limite)))
        except FuturoTimeout:
            return False
        except Exception:  # noqa: BLE001, S110
            # A excecao real ja foi guardada em _erro por _rodar.
            pass

        return self.status in STATUS_TERMINAIS

    def cancelar(
        self,
        tempo_limite: float = TEMPO_LIMITE_CANCELAMENTO_S,
    ) -> bool:
        """Solicita o cancelamento, fecha recursos e aguarda o encerramento.

        A ordem importa: o Event e setado primeiro (fechando respostas e
        sessoes HTTP registradas), depois o Future e cancelado e o
        executor recusa novas tarefas. O join definitivo so acontece se
        o worker realmente terminou dentro do prazo; assim a interface
        nunca prende o st.chat_input por mais de tempo_limite.

        A operacao e idempotente: repetir o cancelamento de um trabalho
        ja terminal devolve True na hora, sem reescrever a etapa
        concluida, sem reabrir recursos e sem esperar a thread de novo.
        """

        status = self.status

        if status in STATUS_TERMINAIS:
            # Fecha eventuais recursos pendentes sem reescrever a etapa
            # terminal nem esperar pela thread de novo.
            fechar = getattr(self.controle.evento, "fechar_recursos", None)

            if callable(fechar):
                try:
                    fechar()
                except Exception:  # noqa: BLE001, S110
                    pass

            self._encerrar_executor(esperar=False)
            return True

        future = self._future
        executor = self._executor
        self.controle.cancelar()

        if status == STATUS_PENDENTE:
            # Trabalho criado e nunca iniciado: não existe thread para
            # aguardar, mas o estado precisa ficar terminal para a UI.
            self._definir(
                STATUS_CANCELADO,
                erro=CancelamentoSolicitado(self.controle.etapa),
            )
            self._encerrar_executor(esperar=True)
            return True

        if future is not None:
            future.cancel()

        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001, S110
                pass

        terminou = self.aguardar(tempo_limite)

        if terminou and self.status == STATUS_EXECUTANDO:
            self._definir(
                STATUS_CANCELADO,
                erro=CancelamentoSolicitado(self.controle.etapa),
            )

        if terminou:
            self._encerrar_executor(esperar=True)

        return terminou

    def _encerrar_executor(self, esperar: bool) -> None:
        """Faz shutdown idempotente; com esperar, faz join das threads."""

        executor = self._executor

        if executor is None:
            return

        try:
            executor.shutdown(wait=bool(esperar), cancel_futures=True)
        except Exception:  # noqa: BLE001
            return

        if esperar:
            _esquecer_executor(executor)

    def descartar(self, esperar: bool = False) -> None:
        """Libera o executor; com esperar faz join da thread de trabalho."""

        future = self._future

        if future is not None:
            future.cancel()

        if esperar:
            self.aguardar(TEMPO_LIMITE_RESPOSTA_S)

        # wait=True so quando o worker ja terminou: um join incondicional
        # poderia prender a interface por causa de uma fonte lenta.
        self._encerrar_executor(
            esperar=bool(esperar and self.status in STATUS_TERMINAIS)
        )


def threads_do_trabalho(prefixo: str = "nexusgeo-consulta") -> list[str]:
    """Nomes das threads de trabalho ainda vivas (diagnostico e testes)."""

    return sorted(
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive() and thread.name.startswith(prefixo)
    )