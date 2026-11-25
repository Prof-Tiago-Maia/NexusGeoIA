"""Timeouts explícitos e cache atômico do serviço de fontes externas.

Cobrem o timeout padrão de requisicao_http quando o chamador não informa
um prazo, a preservação de um timeout explícito, a gravação atômica do
cache de conectores internacionais (sem arquivo temporário residual) e a
idempotência de gravar/ler/fallback. Nenhum teste acessa a rede real.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock

from services import external_api_service as servico
from services.progress_service import EventoCancelamento

BASE = Path(__file__).resolve().parent / "_tmp_external_timeout"


class _SessaoFalsa:
    """Sessão requests falsa que registra os kwargs da requisição."""

    def __init__(self, resposta):
        self.resposta = resposta
        self.kwargs = None
        self.fechada = False

    def request(self, metodo, url, **kwargs):
        self.kwargs = kwargs
        return self.resposta

    def close(self):
        self.fechada = True


class _RespostaFalsa:
    status_code = 200
    encoding = "utf-8"

    def close(self):
        return None

    def raise_for_status(self):
        return None

    def json(self):
        return {}


class TestTimeoutExplicito(unittest.TestCase):
    """Nenhuma requisição sai sem prazo."""

    def test_timeout_padrao_e_aplicado_quando_omitido(self):
        chamadas = []

        def get_falso(url, **kwargs):
            chamadas.append((url, kwargs))
            return _RespostaFalsa()

        with mock.patch.object(servico.requests, "get", side_effect=get_falso):
            resposta = servico.requisicao_http(
                "GET",
                "https://exemplo.invalid/dados",
            )

        self.assertIsInstance(resposta, _RespostaFalsa)
        self.assertEqual(
            chamadas[0][1]["timeout"],
            servico.TIMEOUT_HTTP_PADRAO,
        )

    def test_timeout_explicito_do_conector_e_preservado(self):
        chamadas = []

        def get_falso(url, **kwargs):
            chamadas.append(kwargs)
            return _RespostaFalsa()

        with mock.patch.object(servico.requests, "get", side_effect=get_falso):
            servico.requisicao_http(
                "GET",
                "https://exemplo.invalid/dados",
                timeout=(1.5, 2.5),
            )

        self.assertEqual(chamadas[0]["timeout"], (1.5, 2.5))

    def test_caminho_cancelavel_tambem_recebe_timeout(self):
        sessao = _SessaoFalsa(_RespostaFalsa())
        evento = EventoCancelamento()

        aberta = servico.requisicao_http(
            "GET",
            "https://exemplo.invalid/dados",
            cancelamento=evento,
            sessao=sessao,
        )
        aberta.close()

        self.assertEqual(
            sessao.kwargs["timeout"],
            servico.TIMEOUT_HTTP_PADRAO,
        )


class TestCacheAtomico(unittest.TestCase):
    """O cache grava por troca atômica e nunca deixa .tmp para trás."""

    def setUp(self):
        shutil.rmtree(BASE, ignore_errors=True)
        BASE.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)
        self._patch = mock.patch.object(servico, "CACHE_API_DIR", BASE)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _arquivo(self):
        return servico._geo_cache_arquivo(
            "teste",
            {"termo": "komatiite", "limite": 3},
        )

    def test_gravar_e_ler_repetidamente_e_idempotente(self):
        caminho = self._arquivo()
        registros = [{"titulo": "A", "link": "https://a.invalid"}]

        self.assertIsNone(servico._geo_cache_gravar(caminho, registros))
        self.assertTrue(caminho.is_file())
        self.assertEqual(
            servico._geo_cache_ler(caminho),
            registros,
        )

        servico._geo_cache_gravar(caminho, registros)

        self.assertEqual(
            servico._geo_cache_ler(caminho),
            registros,
        )
        self.assertEqual(
            [item.name for item in BASE.iterdir() if item.suffix == ".tmp"],
            [],
        )

    def test_falha_na_troca_remove_o_temporario(self):
        caminho = self._arquivo()

        with mock.patch.object(
            servico.os,
            "replace",
            side_effect=OSError("disco cheio"),
        ):
            servico._geo_cache_gravar(caminho, [{"titulo": "A"}])

        self.assertFalse(caminho.exists())
        self.assertEqual(list(BASE.iterdir()), [])

    def test_cache_nao_grava_resultado_vazio(self):
        chamadas = []

        def produtor():
            chamadas.append(1)
            return []

        primeiro = servico._geo_com_cache(
            "teste_vazio",
            {"termo": "sem-resultado"},
            produtor,
        )
        segundo = servico._geo_com_cache(
            "teste_vazio",
            {"termo": "sem-resultado"},
            produtor,
        )

        self.assertEqual(primeiro, [])
        self.assertEqual(segundo, [])
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(
            [item for item in BASE.iterdir() if item.suffix == ".json"],
            [],
        )

    def test_cache_evita_nova_chamada_ao_produtor(self):
        chamadas = []

        def produtor():
            chamadas.append(1)
            return [{"titulo": "A", "link": "https://a.invalid"}]

        primeiro = servico._geo_com_cache(
            "teste_hit",
            {"termo": "ouro"},
            produtor,
        )
        segundo = servico._geo_com_cache(
            "teste_hit",
            {"termo": "ouro"},
            produtor,
        )

        self.assertEqual(primeiro, segundo)
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(len(servico._geo_cache_ler(self._arquivo_hit()) or []), 1)

    def _arquivo_hit(self):
        return servico._geo_cache_arquivo(
            "teste_hit",
            {"termo": "ouro"},
        )


if __name__ == "__main__":
    unittest.main()