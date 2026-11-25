"""Testes do contrato de progresso e cancelamento (Fase D3a).

Cobrem o caminho do LLM em streaming, o parser de documentos com um PDF
dublado, o upload que remove artefatos parciais, o trabalho em background
e a interface (AppTest) com um responder lento. Nenhum teste acessa a
rede, o Ollama real ou o banco do usuário.
"""

from __future__ import annotations

import gc
import shutil
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from streamlit.testing.v1 import AppTest

from core import assistant
from services import (
    document_parser,
    external_api_service,
    llm_service,
    progress_service,
    rag_service,
)
from services.progress_service import (
    ETAPA_CONCLUIDA,
    ETAPA_LLM,
    ETAPA_PREPARANDO,
    ETAPA_ROTEAMENTO,
    CancelamentoSolicitado,
    EventoCancelamento,
    TrabalhoConsulta,
)
from tests._apptest_isolation import isolar_ambiente_apptest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
BASE_TEMPORARIA = Path(__file__).resolve().parent / "_tmp_d3a"


@contextmanager
def area_temporaria(nome):
    """Pasta local no workspace, limpa antes e depois do teste."""

    base = BASE_TEMPORARIA / nome
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    try:
        yield base
    finally:
        gc.collect()

        for _ in range(5):
            shutil.rmtree(base, ignore_errors=True)

            if not base.exists():
                break

            time.sleep(0.1)


class _Pedaco:
    """Pedaço de streaming compatível com o cliente ollama."""

    def __init__(self, texto):
        self.message = SimpleNamespace(content=texto, thinking="")


class _FluxoLento:
    """Iterador de tokens lento, com close() observável."""

    def __init__(self, intervalo=0.02, limite=500):
        self.intervalo = intervalo
        self.limite = limite
        self.fechado = False
        self.entregues = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.fechado:
            raise StopIteration

        if self.entregues >= self.limite:
            raise StopIteration

        time.sleep(self.intervalo)
        self.entregues += 1

        return _Pedaco("token ")

    def close(self):
        self.fechado = True


class TestCancelamentoLLM(unittest.TestCase):
    """O stream do Ollama é interrompido e fechado em menos de 3 s."""

    def test_cancelamento_fecha_stream_e_respeita_prazo(self):
        fluxo = _FluxoLento(intervalo=0.03, limite=500)
        evento = EventoCancelamento()
        resultado = {}

        def executar():
            try:
                llm_service.gerar_resposta(
                    "pergunta lenta",
                    cancelamento=evento,
                )
            except BaseException as erro:  # noqa: BLE001 - inspeção do teste
                resultado["erro"] = erro

        with mock.patch.object(
            llm_service.cliente,
            "chat",
            return_value=fluxo,
        ):
            thread = threading.Thread(target=executar, daemon=True)
            thread.start()
            time.sleep(0.2)

            inicio = time.monotonic()
            evento.cancelar()
            thread.join(3.0)
            decorrido = time.monotonic() - inicio

        self.assertFalse(thread.is_alive())
        self.assertLess(decorrido, 3.0)
        self.assertIsInstance(resultado.get("erro"), CancelamentoSolicitado)
        self.assertTrue(fluxo.fechado)


class TestTrabalhoEmBackground(unittest.TestCase):
    """TrabalhoConsulta termina sem deixar thread órfã."""

    def test_cancelar_encerra_worker_e_libera_thread(self):
        def lento(controle):
            for _ in range(200):
                controle.verificar(ETAPA_LLM)
                time.sleep(0.02)

            return "nunca"

        trabalho = TrabalhoConsulta(lento).iniciar()
        time.sleep(0.1)

        inicio = time.monotonic()
        terminou = trabalho.cancelar(tempo_limite=2.0)
        decorrido = time.monotonic() - inicio

        self.assertTrue(terminou)
        self.assertLess(decorrido, 3.0)
        self.assertEqual(trabalho.status, progress_service.STATUS_CANCELADO)
        self.assertEqual(progress_service.threads_do_trabalho(), [])

        trabalho.descartar(esperar=True)


class _DocumentoFalso:
    page_count = 5
    needs_pass = False

    def __init__(self):
        self.fechado = False

    def __getitem__(self, indice):
        return SimpleNamespace(get_text=lambda modo: "")

    def close(self):
        self.fechado = True


class _PymupdfFalso:
    def __init__(self):
        self.documento = _DocumentoFalso()

    def open(self, caminho):
        return self.documento


class TestCancelamentoParser(unittest.TestCase):
    """O PDF é fechado e nenhum cache parcial é gravado ao cancelar."""

    def test_cancelar_durante_paginas_nao_grava_cache(self):
        with area_temporaria("parser") as raiz:
            cache = raiz / "cache_md"
            cache.mkdir()

            origem = raiz / "relatorio.pdf"
            origem.write_bytes(b"%PDF-1.4\nconteudo minimo\n")

            pymupdf = _PymupdfFalso()
            evento = EventoCancelamento()

            def progresso(etapa, fracao, detalhe):
                if detalhe == "1/5":
                    evento.set()

            with mock.patch.object(
                document_parser,
                "DIRETORIO_CACHE",
                cache,
            ), mock.patch.object(
                document_parser,
                "_importar_pymupdf",
                return_value=pymupdf,
            ), mock.patch.object(
                document_parser,
                "_importar_pymupdf4llm",
                return_value=None,
            ), mock.patch.object(
                document_parser,
                "_extrair_pagina_pdf",
                return_value=("texto tecnico suficiente " * 5, False, []),
            ):
                inicio = time.monotonic()

                with self.assertRaises(CancelamentoSolicitado):
                    document_parser.converter_arquivo(
                        origem,
                        forcar=True,
                        progresso=progresso,
                        cancelamento=evento,
                    )

                decorrido = time.monotonic() - inicio

            self.assertLess(decorrido, 3.0)
            self.assertTrue(pymupdf.documento.fechado)
            self.assertEqual(list(cache.iterdir()), [])
            self.assertTrue(origem.is_file())


class TestCancelamentoUpload(unittest.TestCase):
    """O upload cancelado remove o arquivo e o cache parcial."""

    def test_salvar_documento_cancelado_limpa_destino(self):
        with area_temporaria("upload") as raiz:
            docs = raiz / "docs"
            cache = raiz / "cache_md"
            docs.mkdir()
            cache.mkdir()

            evento = EventoCancelamento()

            def conversao_cancelada(
                caminho,
                forcar=False,
                progresso=None,
                cancelamento=None,
            ):
                if progresso is not None:
                    progresso(ETAPA_PREPARANDO, 0.5, "1/2")

                evento.set()
                raise CancelamentoSolicitado(ETAPA_PREPARANDO)

            with mock.patch.object(  # noqa: SIM117
                rag_service,
                "DIRETORIO_DOCS",
                docs,
            ), mock.patch.object(
                document_parser,
                "DIRETORIO_CACHE",
                cache,
            ), mock.patch.object(
                rag_service.document_parser,
                "converter_arquivo",
                side_effect=conversao_cancelada,
            ), mock.patch.object(
                rag_service.document_parser,
                "remover_cache",
            ) as remover:
                with self.assertRaises(CancelamentoSolicitado):
                    rag_service.salvar_documento(
                        "lento.pdf",
                        b"%PDF-1.4\n",
                        cancelamento=evento,
                    )

            self.assertEqual(list(docs.iterdir()), [])
            self.assertEqual(remover.call_count, 1)
            self.assertEqual(list(cache.iterdir()), [])


class TestProgressoNoOrquestrador(unittest.TestCase):
    """responder publica as etapas e repassa o evento de cancelamento."""

    def test_etapas_e_evento_chegam_ao_llm(self):
        eventos = []
        recebido = {}

        def progresso(etapa, fracao, detalhe):
            eventos.append(etapa)

        def falso_fonte(*args, **kwargs):
            recebido["cancelamento_fonte"] = kwargs.get("cancelamento")
            kwargs["progresso"](ETAPA_PREPARANDO, 0.1, "")
            return {}

        def falso_llm(**kwargs):
            recebido["cancelamento_llm"] = kwargs.get("cancelamento")
            recebido["ao_token"] = kwargs.get("ao_token")
            return "resposta"

        evento = EventoCancelamento()

        with mock.patch.object(
            assistant,
            "decidir_roteamento",
            return_value={
                "intencao": "HIBRIDO",
                "justificativa": "teste",
                "documentos_locais": [],
            },
        ), mock.patch.object(
            assistant,
            "consultar_fonte",
            side_effect=falso_fonte,
        ), mock.patch.object(
            assistant,
            "gerar_resposta",
            side_effect=falso_llm,
        ):
            resultado = assistant.responder(
                "pergunta",
                progresso=progresso,
                cancelamento=evento,
                ao_token=lambda texto: None,
            )

        self.assertEqual(resultado["resposta"], "resposta")
        self.assertIs(recebido["cancelamento_fonte"], evento)
        self.assertIs(recebido["cancelamento_llm"], evento)
        self.assertIsNotNone(recebido["ao_token"])
        self.assertIn(ETAPA_PREPARANDO, eventos)
        self.assertIn(ETAPA_ROTEAMENTO, eventos)
        self.assertIn(ETAPA_CONCLUIDA, eventos)


class TestCancelamentoAppTest(unittest.TestCase):
    """AppTest: cancelar não salva resposta e não deixa trabalho ativo."""

    def test_botao_cancelar_descarta_resposta(self):
        def responder_lento(**kwargs):
            evento = kwargs.get("cancelamento")
            progresso = kwargs.get("progresso")

            if progresso is not None:
                progresso(ETAPA_LLM, None, "")

            for _ in range(200):
                if evento is not None and evento.is_set():
                    raise CancelamentoSolicitado(ETAPA_LLM)

                time.sleep(0.02)

            return {
                "resposta": "Resposta que não deve ser salva.",
                "fonte": "Ollama",
                "roteamento": {},
                "dados": {},
                "busca_rigeo": {},
            }

        isolar_ambiente_apptest(self)

        with mock.patch(
            "core.assistant.responder",
            side_effect=responder_lento,
        ), mock.patch(
            "services.llm_service.listar_modelos_locais",
            return_value=["nexusgeo-qwen3-4b-v2-q4"],
        ), mock.patch(
            "services.llm_service.garantir_ollama_ativo",
            return_value=True,
        ), mock.patch(
            "services.history_service.gerar_titulo",
            return_value="Pergunta lenta",
        ):
            at = AppTest.from_file(APP, default_timeout=30).run()
            at.chat_input[0].set_value("pergunta lenta").run()

            self.assertEqual(
                at.session_state["_consulta_trabalho"].status,
                progress_service.STATUS_EXECUTANDO,
            )

            botoes = [
                botao
                for botao in at.button
                if botao.key and botao.key.startswith("cancelar_consulta_")
            ]

            self.assertTrue(botoes, "o fragmento deve exibir o botão Cancelar")
            botoes[0].click().run()

            self.assertIsNone(at.session_state.get("_consulta_trabalho"))
            assistentes = [
                mensagem
                for mensagem in at.session_state["mensagens"]
                if mensagem.get("role") == "assistant"
            ]
            self.assertEqual(assistentes, [])
            self.assertIn(
                "cancelada",
                " ".join(aviso.value for aviso in at.warning).lower(),
            )

        prazo = time.monotonic() + 3.0

        while (
            progress_service.threads_do_trabalho()
            and time.monotonic() < prazo
        ):
            time.sleep(0.05)

        self.assertEqual(progress_service.threads_do_trabalho(), [])



class _SessaoHTTPFalsa:
    """Sessão requests falsa que bloqueia até receber close()."""

    def __init__(self, resposta=None):
        self.iniciou = threading.Event()
        self.liberou = threading.Event()
        self.fechada = False
        self.resposta = resposta

    def request(self, metodo, url, **kwargs):
        self.iniciou.set()
        self.liberou.wait(5.0)

        if self.resposta is not None:
            return self.resposta

        raise RuntimeError("conexão interrompida pelo cancelamento")

    def close(self):
        self.fechada = True
        self.liberou.set()


class _RespostaHTTPFalsa:
    """Resposta requests falsa com close() observável."""

    def __init__(self):
        self.status_code = 200
        self.encoding = "utf-8"
        self.content = b"{}"
        self.fechada = False

    def raise_for_status(self):
        return None

    def json(self):
        return {}

    def close(self):
        self.fechada = True


class TestCancelamentoHTTP(unittest.TestCase):
    """Sessão e resposta abertas são fechadas quando o Event é setado."""

    def test_cancelamento_fecha_sessao_bloqueada(self):
        sessao = _SessaoHTTPFalsa()
        evento = EventoCancelamento()
        resultado = {}

        def executar():
            try:
                external_api_service.requisicao_http(
                    "GET",
                    "https://exemplo.invalid/dados",
                    cancelamento=evento,
                )
            except BaseException as erro:  # noqa: BLE001 - inspeção
                resultado["erro"] = erro

        with mock.patch.object(
            external_api_service.requests,
            "Session",
            return_value=sessao,
        ):
            thread = threading.Thread(target=executar, daemon=True)
            thread.start()
            self.assertTrue(sessao.iniciou.wait(2.0))

            inicio = time.monotonic()
            evento.cancelar()
            thread.join(3.0)
            decorrido = time.monotonic() - inicio

        self.assertFalse(thread.is_alive())
        self.assertLess(decorrido, 3.0)
        self.assertTrue(sessao.fechada)
        self.assertIsInstance(resultado.get("erro"), CancelamentoSolicitado)

    def test_cancelamento_fecha_resposta_ativa(self):
        resposta = _RespostaHTTPFalsa()
        sessao = _SessaoHTTPFalsa(resposta=resposta)
        evento = EventoCancelamento()

        with mock.patch.object(
            external_api_service.requests,
            "Session",
            return_value=sessao,
        ):
            aberta = external_api_service.requisicao_http(
                "GET",
                "https://exemplo.invalid/dados",
                cancelamento=evento,
            )

        self.assertFalse(resposta.fechada)
        evento.cancelar()
        self.assertTrue(resposta.fechada)
        self.assertTrue(sessao.fechada)
        self.assertTrue(aberta.fechada)

    def test_conector_sgb_aborta_e_fecha_sessao(self):
        sessao = _SessaoHTTPFalsa()
        evento = EventoCancelamento()
        resultado = {}

        def executar():
            try:
                external_api_service.consultar_sgb(
                    "ouro em Carajás",
                    limite=1,
                    termos={
                        "consultas": ["ouro carajas"],
                        "termo": "ouro carajas",
                        "termos": ["ouro", "carajas"],
                        "origem": "regra",
                    },
                    cancelamento=evento,
                )
            except BaseException as erro:  # noqa: BLE001 - inspeção
                resultado["erro"] = erro

        with mock.patch.object(
            external_api_service.requests,
            "Session",
            return_value=sessao,
        ):
            thread = threading.Thread(target=executar, daemon=True)
            thread.start()
            self.assertTrue(sessao.iniciou.wait(2.0))

            evento.cancelar()
            thread.join(3.0)

        self.assertFalse(thread.is_alive())
        self.assertTrue(sessao.fechada)
        self.assertIsInstance(resultado.get("erro"), CancelamentoSolicitado)


    def test_leitura_normal_fecha_resposta_e_remove_registro(self):
        resposta = _RespostaHTTPFalsa()
        sessao = _SessaoHTTPFalsa(resposta=resposta)
        evento = EventoCancelamento()

        with mock.patch.object(
            external_api_service.requests,
            "Session",
            return_value=sessao,
        ):
            aberta = external_api_service.requisicao_http(
                "GET",
                "https://exemplo.invalid/dados",
                cancelamento=evento,
            )

        self.assertEqual(aberta.json(), {})
        self.assertTrue(resposta.fechada)
        self.assertEqual(evento.fechar_recursos(), 0)


class TestSequenciaDeConsultas(unittest.TestCase):
    """Cancelar e iniciar de novo não acumula executor nem thread."""

    @staticmethod
    def _lento(controle):
        for _ in range(500):
            controle.verificar(ETAPA_LLM)
            time.sleep(0.01)

        return "nunca"

    def test_multiplas_sequencias_cancelar_iniciar(self):
        for _ in range(6):
            trabalho = TrabalhoConsulta(self._lento).iniciar()
            time.sleep(0.04)

            inicio = time.monotonic()
            terminou = trabalho.cancelar(tempo_limite=1.5)
            decorrido = time.monotonic() - inicio

            self.assertTrue(terminou)
            self.assertLess(decorrido, 3.0)
            self.assertEqual(
                trabalho.status,
                progress_service.STATUS_CANCELADO,
            )
            trabalho.descartar(esperar=True)
            self.assertEqual(progress_service.threads_do_trabalho(), [])
            self.assertEqual(progress_service.executores_do_trabalho(), 0)

    def test_cancelar_antes_de_iniciar_nao_abre_thread(self):
        trabalho = TrabalhoConsulta(self._lento)
        self.assertTrue(trabalho.cancelar(tempo_limite=0.5))
        trabalho.iniciar()
        self.assertEqual(trabalho.status, progress_service.STATUS_CANCELADO)
        self.assertEqual(progress_service.threads_do_trabalho(), [])
        self.assertEqual(progress_service.executores_do_trabalho(), 0)
        trabalho.descartar(esperar=True)


if __name__ == "__main__":
    unittest.main()
