"""Idempotência e prazos explícitos do trabalho em background (D3a).

Cobrem cancelamento repetido sem reabrir recursos, no-op depois do
término, iniciar duas vezes sem duplicar execução e os prazos de espera
(2 s para cancelar, 3 s para coletar) sem deixar thread órfã.
"""

from __future__ import annotations

import time
import unittest

from services import progress_service
from services.progress_service import (
    ETAPA_CONCLUIDA,
    ETAPA_LLM,
    STATUS_CANCELADO,
    STATUS_CONCLUIDO,
    TrabalhoConsulta,
)


def _lento(controle):
    for _ in range(300):
        controle.verificar(ETAPA_LLM)
        time.sleep(0.01)

    return "nunca"


class TestCancelamentoIdempotente(unittest.TestCase):
    """cancelar() repetido é no-op e termina dentro do prazo."""

    def test_cancelar_duas_vezes_nao_reabre_nem_espera_de_novo(self):
        trabalho = TrabalhoConsulta(_lento).iniciar()
        time.sleep(0.05)

        inicio = time.monotonic()
        self.assertTrue(trabalho.cancelar())
        primeiro = time.monotonic() - inicio

        inicio = time.monotonic()
        self.assertTrue(trabalho.cancelar())
        segundo = time.monotonic() - inicio

        self.assertLess(primeiro, 3.0)
        self.assertLess(segundo, 3.0)
        self.assertEqual(trabalho.status, STATUS_CANCELADO)
        estado = trabalho.estado()
        self.assertTrue(estado["terminal"])
        self.assertTrue(estado["cancelado"])
        self.assertEqual(progress_service.threads_do_trabalho(), [])
        self.assertEqual(progress_service.executores_do_trabalho(), 0)
        trabalho.descartar(esperar=True)

    def test_cancelar_depois_de_concluir_preserva_a_etapa(self):
        def rapido(controle):
            controle.relatar(ETAPA_CONCLUIDA, 1.0, "")
            return "ok"

        trabalho = TrabalhoConsulta(rapido).iniciar()
        self.assertTrue(trabalho.aguardar(3.0))
        self.assertEqual(trabalho.status, STATUS_CONCLUIDO)
        self.assertEqual(trabalho.resultado, "ok")
        etapa_antes = trabalho.controle.etapa

        self.assertTrue(trabalho.cancelar())

        self.assertEqual(trabalho.status, STATUS_CONCLUIDO)
        self.assertEqual(trabalho.resultado, "ok")
        self.assertEqual(trabalho.controle.etapa, etapa_antes)
        trabalho.descartar(esperar=True)

    def test_cancelar_antes_de_iniciar_e_idempotente(self):
        trabalho = TrabalhoConsulta(_lento)

        self.assertTrue(trabalho.cancelar())
        self.assertTrue(trabalho.cancelar())
        trabalho.iniciar()

        self.assertEqual(trabalho.status, STATUS_CANCELADO)
        self.assertEqual(progress_service.threads_do_trabalho(), [])
        self.assertEqual(progress_service.executores_do_trabalho(), 0)
        trabalho.descartar(esperar=True)

    def test_iniciar_duas_vezes_executa_uma_vez(self):
        execucoes = []

        def conta(controle):
            execucoes.append(1)
            return "ok"

        trabalho = TrabalhoConsulta(conta)
        trabalho.iniciar()
        trabalho.iniciar()
        self.assertTrue(trabalho.aguardar(3.0))

        self.assertEqual(execucoes, [1])
        self.assertEqual(trabalho.status, STATUS_CONCLUIDO)
        trabalho.descartar(esperar=True)

    def test_descartar_repetido_e_seguro(self):
        trabalho = TrabalhoConsulta(_lento).iniciar()
        time.sleep(0.03)
        trabalho.cancelar()

        trabalho.descartar(esperar=True)
        trabalho.descartar(esperar=True)

        self.assertEqual(progress_service.threads_do_trabalho(), [])


class TestPrazosExplicitos(unittest.TestCase):
    """aguardar() nunca bloqueia além do prazo informado."""

    def test_aguardar_respeita_prazo_curto(self):
        trabalho = TrabalhoConsulta(_lento).iniciar()

        try:
            inicio = time.monotonic()
            terminou = trabalho.aguardar(0.05)
            decorrido = time.monotonic() - inicio

            self.assertFalse(terminou)
            self.assertLess(decorrido, 3.0)
        finally:
            trabalho.cancelar()
            trabalho.descartar(esperar=True)

    def test_constantes_de_prazo_sao_explicitas(self):
        self.assertEqual(
            progress_service.TEMPO_LIMITE_CANCELAMENTO_S,
            2.0,
        )
        self.assertEqual(
            progress_service.TEMPO_LIMITE_RESPOSTA_S,
            3.0,
        )

    def test_estado_nao_carrega_o_resultado_pesado(self):
        grande = {"registros": [{"texto": "x" * 1000} for _ in range(200)]}
        trabalho = TrabalhoConsulta(lambda controle: grande).iniciar()
        self.assertTrue(trabalho.aguardar(3.0))

        estado = trabalho.estado()

        # O estado expõe uma referência booleana, não uma cópia do
        # payload: a interface não precisa receber o resultado inteiro
        # a cada polling.
        self.assertTrue(estado["resultado_disponivel"])
        self.assertNotIn("registros", estado)
        self.assertIs(trabalho.resultado, grande)
        trabalho.descartar(esperar=True)

    def test_threads_nao_acumulam_apos_ciclos(self):
        for _ in range(4):
            trabalho = TrabalhoConsulta(_lento).iniciar()
            time.sleep(0.02)
            self.assertTrue(trabalho.cancelar(1.0))
            trabalho.descartar(esperar=True)
            self.assertEqual(progress_service.threads_do_trabalho(), [])
            self.assertEqual(progress_service.executores_do_trabalho(), 0)


if __name__ == "__main__":
    unittest.main()