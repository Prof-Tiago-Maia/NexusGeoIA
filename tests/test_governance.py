"""Testes unitários da governança do contrato de saída (D1).

Cobrem parsing do JSON, classificação OBSERVED/INFERRED, vereditos
PASS/HOLD/FAIL, fallback de texto livre e conversão de falhas de
rede/TLS/timeout em HOLD sem traceback. Nenhum teste acessa a rede.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

import requests

from core import governance

CERCA = chr(96) * 3


def contrato_fenceado(contrato):
    """Serializa um contrato dentro de um bloco cercado de Markdown."""

    return (
        f"{CERCA}json\n"
        f"{json.dumps(contrato, ensure_ascii=False)}\n"
        f"{CERCA}"
    )


class TestClassificacao(unittest.TestCase):
    """Regras de OBSERVED e INFERRED."""

    def test_com_evidencia_e_observed(self):
        self.assertEqual(
            governance.classificar_afirmacao("Há granito.", "ev_1"),
            "OBSERVED",
        )

    def test_sem_evidencia_e_inferred(self):
        self.assertEqual(
            governance.classificar_afirmacao("Provável granito."),
            "INFERRED",
        )

    def test_normaliza_sinonimos(self):
        self.assertEqual(
            governance.normalizar_classificacao("observado"),
            "OBSERVED",
        )
        self.assertEqual(
            governance.normalizar_classificacao("inferência"),
            "INFERRED",
        )
        self.assertIsNone(
            governance.normalizar_classificacao("talvez")
        )


class TestParsingContrato(unittest.TestCase):
    """Extração do JSON e decisão do veredito."""

    def test_contrato_valido_com_observed_e_inferred_e_pass(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta técnica.",
                "claims": [
                    {
                        "texto": "O mapa mostra granito.",
                        "classificacao": "OBSERVED",
                        "evidence_id": "ev_mapa",
                    },
                    {
                        "texto": "Pode haver mineralização.",
                        "classificacao": "INFERRED",
                    },
                ],
                "veredito": "PASS",
            },
            evidencias_validas=["ev_mapa"],
        )

        self.assertEqual(resultado.veredito, "PASS")
        self.assertEqual(resultado.motivo_codigo, "contrato_valido")
        self.assertEqual(resultado.formato, "contrato")
        self.assertEqual(len(resultado.afirmacoes), 2)
        self.assertEqual(
            resultado.afirmacoes[0].classificacao, "OBSERVED"
        )
        self.assertEqual(
            resultado.afirmacoes[1].classificacao, "INFERRED"
        )

    def test_bloco_json_cercado_e_aceito(self):
        resultado = governance.avaliar_governanca(
            contrato_fenceado(
                {
                    "answer_markdown": "Texto",
                    "claims": [],
                    "veredito": "PASS",
                }
            )
        )

        self.assertEqual(resultado.formato, "contrato")
        self.assertEqual(resultado.veredito, "PASS")
        self.assertEqual(resultado.answer_markdown, "Texto")

    def test_observed_sem_evidencia_vira_inferred_e_hold(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [
                    {
                        "texto": "O granito ocorre aqui.",
                        "classificacao": "OBSERVED",
                    }
                ],
                "veredito": "PASS",
            }
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(
            resultado.motivo_codigo,
            "observado_sem_evidencia",
        )
        self.assertEqual(
            resultado.afirmacoes[0].classificacao,
            "INFERRED",
        )
        self.assertIsNone(resultado.afirmacoes[0].evidence_id)

    def test_evidencia_fora_do_catalogo_vira_hold(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [
                    {
                        "texto": "O granito ocorre aqui.",
                        "classificacao": "OBSERVED",
                        "evidence_id": "ev_fantasma",
                    }
                ],
                "veredito": "PASS",
            },
            evidencias_validas=["ev_mapa"],
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(
            resultado.motivo_codigo,
            "evidencia_desconhecida",
        )
        self.assertEqual(
            resultado.afirmacoes[0].classificacao,
            "INFERRED",
        )

    def test_veredito_fail_declarado_prevalece_sobre_pass(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [],
                "veredito": "FAIL",
            }
        )

        self.assertEqual(resultado.veredito, "FAIL")
        self.assertEqual(resultado.motivo_codigo, "falha_declarada")

    def test_veredito_hold_declarado_e_preservado(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [],
                "veredito": "HOLD",
            }
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(
            resultado.motivo_codigo,
            "veredito_declarado_hold",
        )

    def test_veredito_invalido_gera_hold(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [],
                "veredito": "TALVEZ",
            }
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(
            resultado.motivo_codigo,
            "veredito_invalido",
        )

    def test_contrato_sem_lista_de_afirmacoes_gera_hold(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "veredito": "PASS",
            }
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(
            resultado.motivo_codigo,
            "contrato_invalido",
        )

    def test_resposta_vazia_gera_fail(self):
        resultado = governance.avaliar_governanca(
            {"answer_markdown": "", "claims": []}
        )

        self.assertEqual(resultado.veredito, "FAIL")
        self.assertEqual(resultado.motivo_codigo, "resposta_vazia")


class TestFallbackTextoLivre(unittest.TestCase):
    """O modelo local pode devolver texto sem contrato."""

    def test_texto_livre_e_preservado_com_hold(self):
        texto = (
            "O granito da região apresenta textura fanerítica. "
            "Não há coordenadas suficientes para o mapa."
        )

        resultado = governance.avaliar_governanca(texto)

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.formato, "texto_livre")
        self.assertEqual(resultado.motivo_codigo, "texto_livre")
        self.assertEqual(resultado.answer_markdown, texto)
        self.assertEqual(resultado.afirmacoes, ())

    def test_json_invalido_nao_quebra_e_cai_no_texto_livre(self):
        texto = '{"answer_markdown": "sem fechamento"'

        resultado = governance.avaliar_governanca(texto)

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.formato, "texto_livre")
        self.assertEqual(resultado.answer_markdown, texto)

    def test_saida_vazia_gera_fail(self):
        resultado = governance.avaliar_governanca("   ")

        self.assertEqual(resultado.veredito, "FAIL")
        self.assertEqual(resultado.motivo_codigo, "resposta_vazia")

    def test_extrair_contrato_ignora_json_sem_chaves_conhecidas(self):
        self.assertIsNone(
            governance.extrair_contrato('{"foo": "bar"}')
        )


class TestFalhasDeFonte(unittest.TestCase):
    """Timeout, TLS, rede e HTTP viram HOLD com motivo objetivo."""

    def test_timeout_vira_hold_sem_traceback(self):
        resultado = governance.avaliar_governanca(
            "Resposta parcial",
            erro_fonte=requests.exceptions.ReadTimeout("segredo interno"),
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.motivo_codigo, "fonte_timeout")
        self.assertEqual(
            resultado.falha_fonte.categoria,
            "timeout",
        )
        self.assertNotIn("Traceback", resultado.motivo)
        self.assertNotIn("segredo interno", resultado.motivo)
        self.assertEqual(
            resultado.motivo,
            "Tempo esgotado ao consultar a fonte.",
        )

    def test_tls_vira_hold(self):
        resultado = governance.resultado_falha_fonte(
            requests.exceptions.SSLError("certificado inválido")
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.motivo_codigo, "fonte_tls")
        self.assertEqual(resultado.falha_fonte.categoria, "tls")
        self.assertNotIn("certificado inválido", resultado.motivo)

    def test_rede_vira_hold(self):
        resultado = governance.resultado_falha_fonte(
            requests.exceptions.ConnectionError("sem rota")
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.motivo_codigo, "fonte_rede")
        self.assertEqual(resultado.falha_fonte.categoria, "rede")

    def test_http_500_vira_hold_com_status(self):
        resposta = mock.Mock()
        resposta.status_code = 503
        erro = requests.exceptions.HTTPError(
            "serviço fora",
            response=resposta,
        )

        falha = governance.classificar_falha_fonte(erro)

        self.assertEqual(falha.veredito, "HOLD")
        self.assertEqual(falha.categoria, "http")
        self.assertEqual(falha.status_http, 503)
        self.assertIn("503", falha.motivo)

    def test_erro_declarado_fail_nao_sobrepoe_falha_de_fonte(self):
        resultado = governance.avaliar_governanca(
            {
                "answer_markdown": "Resposta",
                "claims": [],
                "veredito": "FAIL",
            },
            erro_fonte=TimeoutError("demorou"),
        )

        self.assertEqual(resultado.veredito, "HOLD")
        self.assertEqual(resultado.motivo_codigo, "fonte_timeout")

    def test_motivos_em_ingles(self):
        resultado = governance.resultado_falha_fonte(
            TimeoutError("demorou"),
            idioma="en",
        )

        self.assertEqual(
            resultado.motivo,
            "Timed out while querying the source.",
        )


if __name__ == "__main__":
    unittest.main()
