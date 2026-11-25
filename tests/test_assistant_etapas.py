"""Etapas, cancelamento e referências leves do orquestrador (D3a).

Cobrem a publicação da etapa antes de cada fonte, a propagação de
CancelamentoSolicitado (nunca engolido como falha de fonte), a falha
explicita de uma fonte opcional em aviso e a passagem apenas da lista de
trechos para o extrator de coordenadas. Sem rede e sem banco real.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from core import assistant
from services.progress_service import (
    ETAPA_ANA,
    ETAPA_GEOSGB,
    ETAPA_INTL_GEO,
    ETAPA_MACROSTRAT,
    ETAPA_PREPARANDO,
    ETAPA_SGB,
    CancelamentoSolicitado,
    EventoCancelamento,
)


class TestEtapasCancelaveis(unittest.TestCase):
    """Cada etapa publica o progresso e propaga o cancelamento."""

    def _verificar_falha(self, nome_conector, chamada, etapa):
        eventos = []

        def conector(*args, **kwargs):
            raise CancelamentoSolicitado(etapa)

        def progresso(etapa_atual, fracao, detalhe):
            eventos.append(etapa_atual)

        with mock.patch.object(
            assistant,
            nome_conector,
            side_effect=conector,
        ), self.assertRaises(CancelamentoSolicitado):
            inicio = time.monotonic()
            chamada(progresso)

        self.assertLess(time.monotonic() - inicio, 3.0)

        self.assertIn(etapa, eventos)

    def test_sgb_publica_a_etapa_e_propaga_cancelamento(self):
        self._verificar_falha(
            "consultar_sgb",
            lambda progresso: assistant.consultar_fonte(
                "ouro em Carajás",
                ["sgb"],
                progresso=progresso,
            ),
            ETAPA_SGB,
        )

    def test_ana_publica_a_etapa_e_propaga_cancelamento(self):
        self._verificar_falha(
            "consultar_ana_estacoes",
            lambda progresso: assistant.consultar_fonte(
                "estação fluviométrica no Amazonas",
                [],
                usar_ana=True,
                progresso=progresso,
            ),
            ETAPA_ANA,
        )

    def test_macrostrat_publica_a_etapa_e_propaga_cancelamento(self):
        self._verificar_falha(
            "consultar_macrostrat",
            lambda progresso: assistant.consultar_fonte(
                "unidade perto de -3,1, -60,0",
                [],
                usar_macrostrat=True,
                progresso=progresso,
            ),
            ETAPA_MACROSTRAT,
        )

    def test_grupo_internacional_nao_engole_cancelamento(self):
        self._verificar_falha(
            "consultar_servicos_geologicos_internacionais",
            lambda progresso: assistant.consultar_fonte(
                "komatiite nickel",
                [],
                usar_intl_geo=True,
                progresso=progresso,
            ),
            ETAPA_INTL_GEO,
        )

    def test_cancelamento_antes_de_comecar_nao_chama_fonte(self):
        evento = EventoCancelamento()
        evento.set()

        with mock.patch.object(
            assistant,
            "consultar_fonte",
        ) as fonte, self.assertRaises(CancelamentoSolicitado) as contexto:
            assistant.responder("pergunta", cancelamento=evento)

        self.assertEqual(contexto.exception.etapa, ETAPA_PREPARANDO)
        fonte.assert_not_called()

    def test_falha_de_fonte_opcional_fica_em_aviso(self):
        eventos = []

        with mock.patch.object(
            assistant,
            "consultar_geosgb_ocorrencias",
            side_effect=ValueError("limite invalido"),
        ):
            dados = assistant.consultar_fonte(
                "ouro",
                [],
                usar_geosgb=True,
                progresso=lambda etapa, fracao, detalhe: eventos.append(etapa),
            )

        self.assertEqual(dados["geosgb"]["total"], 0)
        self.assertIn("limite invalido", dados["geosgb"]["aviso"])
        self.assertIn(ETAPA_GEOSGB, eventos)


class TestReferenciasLeves(unittest.TestCase):
    """O extrator de coordenadas recebe só os trechos, não os dados todos."""

    TRECHOS = (
        {"texto": "sem coordenada"},
        {"texto": "afloramento em -3,12, -60,04"},
    )

    def test_pergunta_tem_prioridade_sobre_os_trechos(self):
        self.assertEqual(
            assistant._coordenadas_de_trechos(
                "ponto em -7,21, -59,88",
                self.TRECHOS,
            ),
            (-7.21, -59.88),
        )

    def test_trechos_sao_usados_quando_a_pergunta_nao_tem_ponto(self):
        self.assertEqual(
            assistant._coordenadas_de_trechos("sem ponto", self.TRECHOS),
            (-3.12, -60.04),
        )

    def test_assinatura_antiga_continua_aceita(self):
        dados = {"documentos": {"trechos": self.TRECHOS}}

        self.assertEqual(
            assistant._coordenadas_da_consulta("sem ponto", dados),
            (-3.12, -60.04),
        )
        self.assertEqual(
            assistant._coordenadas_da_consulta("sem ponto", None),
            (None, None),
        )

    def test_lista_vazia_nao_quebra_a_extracao(self):
        self.assertEqual(
            assistant._coordenadas_de_trechos("sem ponto", []),
            (None, None),
        )
        self.assertEqual(
            assistant._coordenadas_de_trechos("sem ponto", None),
            (None, None),
        )


if __name__ == "__main__":
    unittest.main()