"""Testes do TLS do conector ANM (M2).

O conector não pode desligar a verificação de certificado
automaticamente. Só o opt-out explícito ANM_SSL_VERIFY=0 permite
verify=False; um erro de certificado deve falhar e usar o cache.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

import requests

from services import external_api_service as servico


def _resposta_json():
    resposta = mock.Mock()
    resposta.status_code = 200
    resposta.encoding = "utf-8"
    resposta.json.return_value = {"features": []}
    resposta.raise_for_status.return_value = None
    return resposta


class TestAnmTls(unittest.TestCase):
    """A verificação TLS é o padrão; o opt-out é explícito."""

    def setUp(self):
        self._falha_original = servico._ANM_FALHA_ATE
        self._ssl_original = servico._ANM_SSL_FALHOU
        servico._ANM_FALHA_ATE = 0.0
        servico._ANM_SSL_FALHOU = False

    def tearDown(self):
        servico._ANM_FALHA_ATE = self._falha_original
        servico._ANM_SSL_FALHOU = self._ssl_original

    def test_padrao_verifica_tls(self):
        resposta = _resposta_json()

        with mock.patch.object(
            servico,
            "ANM_SSL_VERIFY",
            True,
        ), mock.patch.object(
            servico.requests,
            "get",
            return_value=resposta,
        ) as get:
            dados, respondeu, tls = servico._requisitar_anm(
                "https://geo.anm.gov.br/teste",
                {},
                time.monotonic() + 30,
            )

        self.assertTrue(respondeu)
        self.assertEqual(tls, "verificada")
        self.assertNotEqual(get.call_args.kwargs.get("verify"), False)
        self.assertEqual(get.call_count, 1)

    def test_erro_de_certificado_nao_repete_sem_tls(self):
        with mock.patch.object(
            servico,
            "ANM_SSL_VERIFY",
            True,
        ), mock.patch.object(
            servico.requests,
            "get",
            side_effect=requests.exceptions.SSLError("cadeia incompleta"),
        ) as get:
            dados, respondeu, tls = servico._requisitar_anm(
                "https://geo.anm.gov.br/teste",
                {},
                time.monotonic() + 30,
            )

        self.assertFalse(respondeu)
        self.assertEqual(get.call_count, 1)
        self.assertFalse(
            any(
                chamada.kwargs.get("verify") is False
                for chamada in get.call_args_list
            )
        )

    def test_opt_out_explicito_permite_sem_verificacao(self):
        resposta = _resposta_json()

        with mock.patch.object(
            servico,
            "ANM_SSL_VERIFY",
            False,
        ), mock.patch.object(
            servico.requests,
            "get",
            return_value=resposta,
        ) as get:
            dados, respondeu, tls = servico._requisitar_anm(
                "https://geo.anm.gov.br/teste",
                {},
                time.monotonic() + 30,
            )

        self.assertTrue(respondeu)
        self.assertEqual(tls, "verificacao-desligada")
        self.assertIs(get.call_args.kwargs.get("verify"), False)
