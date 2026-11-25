"""Idempotência, referências leves e prazo explícito da grade de sondagem.

Cobrem a assinatura estável do resultado, o hash canônico do texto, o
prazo por etapa (SondagemError com código tempo_excedido), a precedência
do cancelamento e a estabilidade da exportação. Nenhum teste escreve no
banco real, acessa rede ou usa a interface.
"""

from __future__ import annotations

import threading
import time
import unittest

from services import sondagem
from services.progress_service import (
    CancelamentoSolicitado,
    EventoCancelamento,
)

TABELA = (
    "Furo;De;Ate;Litologia;Amostra\n"
    "FQ-01;0;2,5;Solo;A-01\n"
    "FQ-01;2,5;5;Rocha;A-02\n"
    "FQ-02;0;1,5;Saprolito;A-03\n"
)


class _GeradorLento:
    """Gerador de linhas com pausa observável entre registros."""

    def __init__(self, total=500, intervalo=0.05):
        self.total = total
        self.intervalo = intervalo
        self.consumidos = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.consumidos >= self.total:
            raise StopIteration

        time.sleep(self.intervalo)
        self.consumidos += 1
        return ["FQ-99", str(self.consumidos), str(self.consumidos + 1)]


class TestIdempotenciaDaAnalise(unittest.TestCase):
    """Reexecutar a mesma etapa devolve a mesma assinatura."""

    def test_analises_repetidas_tem_a_mesma_assinatura(self):
        primeira = sondagem.analisar_sondagem(TABELA)
        segunda = sondagem.analisar_sondagem(TABELA)

        self.assertEqual(primeira["assinatura"], segunda["assinatura"])
        self.assertEqual(
            sondagem.assinatura_resultado(primeira),
            primeira["assinatura"],
        )
        self.assertEqual(primeira["intervalos"], segunda["intervalos"])
        self.assertEqual(primeira["invalidos"], segunda["invalidos"])

    def test_assinatura_muda_quando_a_grade_muda(self):
        base = sondagem.analisar_sondagem(TABELA)
        outra = sondagem.analisar_sondagem(
            TABELA.replace("Solo", "Areia")
        )

        self.assertNotEqual(base["assinatura"], outra["assinatura"])

    def test_hash_do_texto_tolera_crlf_espacos_e_linhas_vazias(self):
        variante = (
            "\ufeff\r\n"
            + TABELA.replace("\n", "\r\n")
            + "\r\n   \r\n"
        )

        self.assertEqual(
            sondagem.hash_texto(TABELA),
            sondagem.hash_texto(variante),
        )
        self.assertEqual(len(sondagem.hash_texto(TABELA)), 64)
        self.assertNotEqual(
            sondagem.hash_texto(TABELA),
            sondagem.hash_texto(TABELA + "FQ-03;0;1;X\n"),
        )

    def test_hash_e_assinatura_nao_mutam_a_grade(self):
        resultado = sondagem.analisar_sondagem(TABELA)
        antes = sondagem.assinatura_resultado(resultado, incluir_invalidos=True)

        sondagem.hash_texto(TABELA)
        sondagem.assinatura_resultado(resultado)
        sondagem.montar_dataframe(resultado, incluir_invalidos=True)
        depois = sondagem.assinatura_resultado(resultado, incluir_invalidos=True)

        self.assertEqual(antes, depois)


class TestPrazoDaEtapa(unittest.TestCase):
    """prazo_s é explícito e não devolve grade parcial."""

    def test_prazo_expirado_vira_erro_de_contrato_em_menos_de_3s(self):
        gerador = _GeradorLento(total=500, intervalo=0.05)
        inicio = time.monotonic()

        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                gerador,
                cabecalhos=["Furo", "De", "Ate"],
                prazo_s=0.12,
            )

        self.assertLess(time.monotonic() - inicio, 3.0)
        self.assertEqual(
            contexto.exception.codigo,
            sondagem.CODIGO_TEMPO_EXCEDIDO,
        )
        self.assertLess(gerador.consumidos, gerador.total)

    def test_prazo_none_mantem_o_comportamento_de_lote(self):
        resultado = sondagem.analisar_sondagem(TABELA, prazo_s=None)

        self.assertEqual(resultado["total_validos"], 3)
        self.assertTrue(resultado["assinatura"])

    def test_cancelamento_tem_precedencia_sobre_o_prazo(self):
        evento = EventoCancelamento()
        evento.set()
        inicio = time.monotonic()

        with self.assertRaises(CancelamentoSolicitado):
            sondagem.analisar_sondagem(
                TABELA,
                cancelamento=evento,
                prazo_s=0.0,
            )

        self.assertLess(time.monotonic() - inicio, 3.0)

    def test_prazo_nao_interrompe_tabela_pequena(self):
        resultado = sondagem.analisar_sondagem(TABELA, prazo_s=30.0)

        self.assertEqual(resultado["total_validos"], 3)


class TestExportacaoIdempotente(unittest.TestCase):
    """A exportação é determinística e a grade não é consumida."""

    def test_csv_e_xlsx_repetidos_sao_identicos(self):
        resultado = sondagem.analisar_sondagem(TABELA)

        self.assertEqual(
            sondagem.gerar_csv_sondagem(resultado),
            sondagem.gerar_csv_sondagem(resultado),
        )
        self.assertEqual(
            sondagem.gerar_xlsx_sondagem(resultado),
            sondagem.gerar_xlsx_sondagem(resultado),
        )

    def test_exportacao_nao_altera_a_assinatura(self):
        resultado = sondagem.analisar_sondagem(TABELA)
        antes = sondagem.assinatura_resultado(resultado)

        sondagem.gerar_csv_sondagem(resultado)
        sondagem.gerar_xlsx_sondagem(resultado)

        self.assertEqual(antes, sondagem.assinatura_resultado(resultado))

    def test_cancelamento_durante_geracao_lento(self):
        gerador = _GeradorLento(total=400, intervalo=0.05)
        evento = EventoCancelamento()

        def cancelar():
            time.sleep(0.2)
            evento.cancelar()

        threading.Thread(target=cancelar, daemon=True).start()
        inicio = time.monotonic()

        with self.assertRaises(CancelamentoSolicitado):
            sondagem.analisar_sondagem(
                gerador,
                cabecalhos=["Furo", "De", "Ate"],
                cancelamento=evento,
            )

        self.assertLess(time.monotonic() - inicio, 3.0)


if __name__ == "__main__":
    unittest.main()