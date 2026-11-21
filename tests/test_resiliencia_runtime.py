"""Testes de resiliencia contra erros ocultos do NexusGeo IA.

Os cenarios cobrem os caminhos que so aparecem em producao:

* ``SSL_CERT_FILE`` apontando para um caminho que nao existe no bundle;
* ``OLLAMA_MODELS`` apontando para um arquivo/diretorio invalido ou sem
  permissao de escrita;
* APIs externas (SGB, USGS, Macrostrat, OpenAlex) em timeout ou HTTP 500;
* PDF vazio/corrompido e entradas espaciais malformadas.

Nenhum teste acessa a rede, abre navegador, inicia a GUI ou depende do
Ollama real. As falhas de rede sao simuladas e os arquivos ficam em uma
pasta temporaria dentro de ``tests/``.
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import requests

import launcher_desktop
import services.document_parser as document_parser
import services.external_api_service as servico
import services.spatial_parser as espacial
import setup_llm


@contextmanager
def area_temporaria():
    """Pasta de trabalho local, limpa antes e depois do teste."""

    base = Path(__file__).resolve().parent / "_tmp_resiliencia"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    try:
        yield base
    finally:
        # PyMuPDF pode manter o arquivo aberto por alguns instantes no
        # Windows; o gc + retry evita deixar lixo em tests/.
        gc.collect()

        for _ in range(5):
            shutil.rmtree(base, ignore_errors=True)

            if not base.exists():
                break

            time.sleep(0.1)


def resposta_http_500():
    """Resposta falsa com status 500, sem abrir conexao."""

    resposta = mock.Mock()
    resposta.status_code = 500
    resposta.encoding = "utf-8"
    resposta.json.return_value = {}
    resposta.raise_for_status.side_effect = requests.HTTPError(
        "500 Server Error",
        response=resposta,
    )

    return resposta


def executar_com_falha_de_rede(funcao, *args, **kwargs):
    """Executa o conector com timeout; falha se a excecao escapar."""

    with mock.patch.object(
        servico.requests,
        "get",
        side_effect=requests.Timeout("tempo esgotado no teste"),
    ):
        return funcao(*args, **kwargs)


def executar_com_http_500(funcao, *args, **kwargs):
    """Executa o conector com HTTP 500; falha se a excecao escapar."""

    with mock.patch.object(
        servico.requests,
        "get",
        return_value=resposta_http_500(),
    ):
        return funcao(*args, **kwargs)


class TestCertificadosResilientes(unittest.TestCase):
    """O launcher corrige TLS invalido antes de importar o projeto."""

    def setUp(self):
        self._ssl_original = os.environ.get("SSL_CERT_FILE")
        self._ca_original = os.environ.get("REQUESTS_CA_BUNDLE")

    def tearDown(self):
        for nome, valor in (
            ("SSL_CERT_FILE", self._ssl_original),
            ("REQUESTS_CA_BUNDLE", self._ca_original),
        ):
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor

    def test_ssl_cert_file_inexistente_e_substituido_pelo_certifi(self):
        with area_temporaria() as base:
            inexistente = base / "certificado_que_nao_existe.pem"

            with mock.patch.dict(
                os.environ,
                {
                    "SSL_CERT_FILE": str(inexistente),
                    "REQUESTS_CA_BUNDLE": str(inexistente),
                },
                clear=False,
            ):
                caminho = launcher_desktop.configurar_certificados()

                self.assertIsNotNone(caminho)
                self.assertTrue(Path(caminho).is_file())
                self.assertEqual(os.environ["SSL_CERT_FILE"], caminho)
                self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], caminho)

    def test_caminho_valido_do_usuario_e_preservado(self):
        with area_temporaria() as base:
            valido = base / "ca_do_usuario.pem"
            valido.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "SSL_CERT_FILE": str(valido),
                    "REQUESTS_CA_BUNDLE": str(valido),
                },
                clear=False,
            ):
                caminho = launcher_desktop.configurar_certificados()

                self.assertEqual(os.environ["SSL_CERT_FILE"], str(valido))
                self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], str(valido))
                self.assertTrue(Path(caminho).is_file())

    def test_sem_certifi_disponivel_nao_quebra_o_launcher(self):
        with mock.patch.dict(sys.modules, {"certifi": None}):
            self.assertIsNone(launcher_desktop.configurar_certificados())


class TestOllamaModelsResilientes(unittest.TestCase):
    """Diretorio de modelos invalido vira orientacao, nunca traceback."""

    def test_variavel_ollama_models_e_respeitada(self):
        with area_temporaria() as base:
            modelos = base / "modelos_ollama"

            with mock.patch.dict(
                os.environ,
                {"OLLAMA_MODELS": str(modelos)},
                clear=False,
            ):
                self.assertEqual(
                    setup_llm.pasta_modelos_ollama(),
                    modelos,
                )

    def test_diretorio_apontando_para_arquivo_nao_quebra_orientacao(self):
        with area_temporaria() as base:
            arquivo = base / "ollama_models"
            arquivo.write_text("nao e um diretorio", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"OLLAMA_MODELS": str(arquivo)},
                clear=False,
            ):
                pasta = setup_llm.pasta_modelos_ollama()
                texto = setup_llm.orientacao_permissao(
                    "Access is denied",
                    "pt",
                    pasta,
                )

                self.assertEqual(pasta, arquivo)
                self.assertTrue(pasta.is_file())
                self.assertIn(str(arquivo), texto)
                self.assertIn("OLLAMA_MODELS", texto)
                self.assertIn("icacls", texto)

    def test_diretorio_sem_escrita_gera_orientacao_bilingue(self):
        with area_temporaria() as base:
            somente_leitura = base / "modelos_sem_escrita"
            somente_leitura.mkdir()

            for mensagem in (
                "Access is denied",
                "Acesso negado",
                "Permission denied",
                "WinError 5",
                "Errno 13",
            ):
                with self.subTest(mensagem=mensagem):
                    self.assertTrue(setup_llm.erro_de_permissao(mensagem))

            with mock.patch.dict(
                os.environ,
                {"OLLAMA_MODELS": str(somente_leitura)},
                clear=False,
            ):
                texto_pt = setup_llm.mensagem_de_download(
                    "Access is denied",
                    "pt",
                )
                texto_en = setup_llm.mensagem_de_download(
                    "Access is denied",
                    "en",
                )

                self.assertIn(str(somente_leitura), texto_pt)
                self.assertIn("OLLAMA_MODELS", texto_pt)
                self.assertIn("OLLAMA_MODELS", texto_en)
                self.assertNotEqual(texto_pt, texto_en)

    def test_diretorio_inexistente_nao_e_criado_por_acidente(self):
        with area_temporaria() as base:
            inexistente = base / "ainda_nao_existe" / "modelos"

            with mock.patch.dict(
                os.environ,
                {"OLLAMA_MODELS": str(inexistente)},
                clear=False,
            ):
                self.assertEqual(
                    setup_llm.pasta_modelos_ollama(),
                    inexistente,
                )
                self.assertFalse(inexistente.exists())


class TestConectoresExternosResilientes(unittest.TestCase):
    """Timeout e HTTP 500 viram lista vazia + aviso, sem excecao."""

    def _validar_falha(self, resultado, fonte):
        self.assertEqual(resultado["total"], 0)
        self.assertEqual(resultado["registros"], [])
        self.assertTrue(resultado["aviso"])
        self.assertIn(fonte, resultado["aviso"])

    def test_openalex_timeout_e_http_500(self):
        for executor in (executar_com_falha_de_rede, executar_com_http_500):
            with self.subTest(executor=executor.__name__):
                resultado = executor(
                    servico.consultar_openalex_detalhado,
                    "gold deposit",
                    limite=3,
                )
                self._validar_falha(resultado, "OpenAlex")

    def test_usgs_timeout_e_http_500(self):
        for executor in (executar_com_falha_de_rede, executar_com_http_500):
            with self.subTest(executor=executor.__name__):
                resultado = executor(
                    servico.consultar_usgs_detalhado,
                    "gold deposit",
                    limite=3,
                )
                self._validar_falha(resultado, "USGS ScienceBase")

    def test_macrostrat_timeout_e_http_500(self):
        for executor in (executar_com_falha_de_rede, executar_com_http_500):
            with self.subTest(executor=executor.__name__):
                resultado = executor(
                    servico.consultar_macrostrat,
                    "Formacao Serra Geral",
                    limite=3,
                )
                self._validar_falha(resultado, "Macrostrat")

    def test_sgb_timeout_nao_propaga_sgb_service_error(self):
        termos = {
            "consultas": ["ouro carajas"],
            "termo": "ouro carajas",
            "termos": ["ouro", "carajas"],
            "origem": "regra",
        }

        with mock.patch.object(
            servico,
            "_consultar_rigeo",
            side_effect=servico.SGBServiceError(
                "Nao foi possivel consultar o RIGeo: timeout"
            ),
        ), mock.patch.object(
            servico,
            "_consultar_geobusca",
            return_value=[],
        ), mock.patch.object(
            servico,
            "_preencher_links_pdf",
        ):
            resultado = servico.consultar_sgb(
                "ouro em Carajas",
                limite=3,
                termos=termos,
            )

        self.assertEqual(resultado["total"], 0)
        self.assertEqual(resultado["registros"], [])
        self.assertTrue(resultado["aviso"])
        self.assertIn("RIGeo", resultado["aviso"])

    def test_sgb_http_500_nao_propaga_requests_http_error(self):
        termos = {
            "consultas": ["ouro carajas"],
            "termo": "ouro carajas",
            "termos": ["ouro", "carajas"],
            "origem": "regra",
        }

        with mock.patch.object(
            servico.requests,
            "get",
            return_value=resposta_http_500(),
        ), mock.patch.object(
            servico,
            "_consultar_geobusca",
            return_value=[],
        ), mock.patch.object(
            servico,
            "_preencher_links_pdf",
        ):
            resultado = servico.consultar_sgb(
                "ouro em Carajas",
                limite=3,
                termos=termos,
            )

        self.assertEqual(resultado["total"], 0)
        self.assertEqual(resultado["registros"], [])
        self.assertTrue(resultado["aviso"])
        self.assertIn("RIGeo", resultado["aviso"])


class TestGeoBuscaFallback(unittest.TestCase):
    """M4: o fallback GeoBusca falha de forma limpa e nunca cai para HTTP."""

    @staticmethod
    def _executar(contexto):
        modulo = types.ModuleType("playwright.sync_api")
        modulo.sync_playwright = lambda: contexto
        pacote = types.ModuleType("playwright")
        pacote.sync_api = modulo

        with mock.patch.dict(
            sys.modules,
            {"playwright": pacote, "playwright.sync_api": modulo},
        ):
            return servico._consultar_geobusca("ouro em Carajas", 3)

    def test_base_http_e_recusada_sem_importar_playwright(self):
        with mock.patch.object(
            servico,
            "GEOBUSCA_BASE_URL",
            "http://geobusca.sgb.gov.br",
        ):
            self.assertFalse(servico._base_geobusca_segura())

            with mock.patch(
                "builtins.__import__",
                side_effect=AssertionError("não deve importar playwright"),
            ):
                self.assertEqual(
                    servico._consultar_geobusca("ouro", 3),
                    [],
                )

    def test_base_https_valida(self):
        with mock.patch.object(
            servico,
            "GEOBUSCA_BASE_URL",
            "https://geobusca.sgb.gov.br",
        ):
            self.assertTrue(servico._base_geobusca_segura())

    def test_falha_tls_no_launch_devolve_lista_vazia(self):
        contexto = mock.MagicMock()
        contexto.__enter__.return_value = contexto
        contexto.__exit__.return_value = False
        contexto.chromium.launch.side_effect = RuntimeError(
            "net::ERR_CERT_AUTHORITY_INVALID"
        )

        self.assertEqual(self._executar(contexto), [])

    def test_falha_de_conexao_na_navegacao_devolve_lista_vazia(self):
        pagina = mock.Mock()
        pagina.goto.side_effect = RuntimeError(
            "net::ERR_CONNECTION_REFUSED"
        )
        navegador = mock.Mock()
        navegador.new_page.return_value = pagina

        contexto = mock.MagicMock()
        contexto.__enter__.return_value = contexto
        contexto.__exit__.return_value = False
        contexto.chromium.launch.return_value = navegador

        self.assertEqual(self._executar(contexto), [])
        navegador.close.assert_called_once()


class TestDocumentosCorrompidos(unittest.TestCase):
    """PDF vazio/corrompido vira ErroConversao legivel, nao OSError."""

    def test_pdf_vazio_e_corrompido_nao_derrubam_o_parser(self):
        if not document_parser.pymupdf_disponivel():
            self.skipTest("PyMuPDF indisponivel no ambiente de teste")

        with area_temporaria() as base:
            cache = base / "cache_md"
            cache.mkdir()

            casos = {
                "vazio.pdf": b"",
                "corrompido.pdf": (
                    b"isto nao e um PDF valido\n"
                    b"sem cabecalho, sem xref e sem objetos\n"
                ),
            }

            with mock.patch.object(
                document_parser,
                "DIRETORIO_CACHE",
                cache,
            ):
                for nome, conteudo in casos.items():
                    caminho = base / nome
                    caminho.write_bytes(conteudo)

                    with self.subTest(arquivo=nome):
                        with self.assertRaises(
                            document_parser.ErroConversao
                        ) as caso:
                            document_parser.converter_arquivo(
                                caminho,
                                forcar=True,
                            )

                        self.assertIn(nome, str(caso.exception))
                        self.assertNotIsInstance(
                            caso.exception,
                            (FileNotFoundError, PermissionError),
                        )

    def test_pdf_inexistente_nao_vaza_file_not_found(self):
        with area_temporaria() as base:
            caminho = base / "nao_existe.pdf"

            with self.assertRaises(document_parser.ErroConversao) as caso:
                document_parser.converter_arquivo(caminho)

            self.assertIn("nao_existe.pdf", str(caso.exception))


class TestEntradasEspaciaisMalformadas(unittest.TestCase):
    """Regex espaciais nunca recebem None, NaN ou coordenada absurda."""

    def test_entradas_nao_textuais_devolvem_lista_vazia(self):
        for entrada in (None, 0, 123, [], {}, object()):
            with self.subTest(tipo=type(entrada).__name__):
                self.assertEqual(
                    espacial.extrair_feicoes_espaciais(entrada),
                    [],
                )

    def test_coordenadas_fora_dos_limites_sao_descartadas(self):
        casos = (
            "Lat: 95.0 / Lon: 10.0",
            "Lat: -3.1 / Lon: 250.0",
            "999,999",
            "1000, -2000",
        )

        for texto in casos:
            with self.subTest(texto=texto):
                self.assertEqual(
                    espacial.extrair_feicoes_espaciais(texto),
                    [],
                )

    def test_lat_rotulada_95_nao_e_invertida(self):
        """Par rotulado com latitude inválida é rejeitado, não trocado."""

        for texto in (
            "Lat: 95 / Lon: -60",
            "Lat: 95.0 / Lon: -60.0",
            "Coordenadas: 95, -60",
            "Coordenadas: 95.0, -60.0",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(
                    espacial.extrair_feicoes_espaciais(texto),
                    [],
                    msg="a latitude 95 não pode virar longitude por inversão",
                )

    def test_par_sem_rotulo_aceita_inversao_quando_aplicavel(self):
        """Sem rótulo, (lon, lat) só é invertido quando a leitura direta falha.

        O par ``-60, -3`` não tem casas decimais e, por decisão do
        detector de pares soltos, não é interpretado como coordenada —
        isso evita confundir medidas comuns com latitude/longitude. Já o
        par decimal ``-120.000, -3.000`` tem latitude direta inválida e
        é invertido para (-3, -120).
        """

        self.assertEqual(
            espacial.extrair_feicoes_espaciais("-60, -3"),
            [],
        )

        # Ambos os eixos são válidos na leitura direta: não há motivo
        # para inverter.
        feicoes = espacial.extrair_feicoes_espaciais("-60.000, -3.000")

        self.assertEqual(
            [(feicao["lat"], feicao["lon"]) for feicao in feicoes],
            [(-60.0, -3.0)],
        )

        feicoes = espacial.extrair_feicoes_espaciais("-120.000, -3.000")

        self.assertEqual(
            [(feicao["lat"], feicao["lon"]) for feicao in feicoes],
            [(-3.0, -120.0)],
        )

    def test_coordenadas_rotuladas_mantem_a_ordem_explicita(self):
        """``Coordenadas: lat, lon`` não pode ser invertido para caber."""

        feicoes = espacial.extrair_feicoes_espaciais(
            "Coordenadas: -3.12, -60.01"
        )

        self.assertEqual(
            [(feicao["lat"], feicao["lon"]) for feicao in feicoes],
            [(-3.12, -60.01)],
        )

        # Mesmo que o par pareça (lon, lat), a ordem declarada manda.
        feicoes = espacial.extrair_feicoes_espaciais(
            "Coordenadas: -60.01, -3.12"
        )

        self.assertEqual(
            [(feicao["lat"], feicao["lon"]) for feicao in feicoes],
            [(-60.01, -3.12)],
        )

    def test_gms_truncado_e_folha_cim_invalida_nao_quebram(self):
        casos = (
            '03°07\'24"S',
            "SA.99",
            "ZZ.00-X-B",
            "SB.21-X-B-IV-9",
            "   ",
        )

        for texto in casos:
            with self.subTest(texto=texto):
                feicoes = espacial.extrair_feicoes_espaciais(texto)

                self.assertIsInstance(feicoes, list)

                for feicao in feicoes:
                    self.assertTrue(
                        espacial.coordenada_valida(
                            feicao["lat"],
                            feicao["lon"],
                        )
                    )

    def test_texto_muito_longo_respeita_o_recorte(self):
        texto = "-3.1234, -60.0123 " + ("x" * 100_000)

        feicoes = espacial.extrair_feicoes_espaciais(texto)

        self.assertIsInstance(feicoes, list)

        for feicao in feicoes:
            self.assertTrue(
                espacial.coordenada_valida(feicao["lat"], feicao["lon"])
            )

    def test_consolidar_com_metadados_e_tabelas_malformados(self):
        metadados = [
            None,
            {"fonte": "ana", "registros": "nao e lista"},
            {
                "fonte": "ana",
                "registros": [
                    {"lat": "abc", "lon": None},
                    {"lat": float("nan"), "lon": 10.0},
                    {"lat": 95.0, "lon": 10.0},
                ],
            },
            {
                "fonte": "macrostrat",
                "registros": [{"lat": -3.1, "lon": -60.0}],
            },
        ]
        tabelas = [
            None,
            {"df_limpo": None},
            {"df_limpo": mock.Mock(empty=True)},
        ]

        resultado = espacial.consolidar_pontos_mapa(
            None,
            metadados,
            tabelas,
        )

        self.assertIsInstance(resultado, list)

        for feicao in resultado:
            self.assertTrue(
                espacial.coordenada_valida(feicao["lat"], feicao["lon"])
            )

    def test_csv_aceita_lista_vazia(self):
        conteudo = espacial.gerar_csv_pontos(None)

        self.assertIsInstance(conteudo, bytes)
        self.assertTrue(conteudo.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"lat", conteudo.lower())


if __name__ == "__main__":
    unittest.main()
