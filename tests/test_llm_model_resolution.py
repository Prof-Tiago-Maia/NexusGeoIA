"""Testes da resolução do modelo padrão do Ollama.

Cobrem a prioridade do modelo fine-tuned local
(nexusgeo-qwen3-4b-v2-q4), o fallback silencioso para qwen3:4b
(inclusive quando /api/tags falha) e o respeito a um modelo
explicitamente configurado. Offline: nenhuma chamada real é feita ao
Ollama.
"""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from services import llm_service


class RespostaTagsFalsa:
    """Resposta mínima de /api/tags compatível com urlopen."""

    def __init__(self, dados):
        self._conteudo = json.dumps(dados).encode("utf-8")

    def read(self):
        return self._conteudo

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _tags(*nomes):
    """Monta o JSON de /api/tags no formato do servidor Ollama."""

    return {"models": [{"name": nome} for nome in nomes]}


class TestListInstalledOllamaModels(unittest.TestCase):
    """Leitura de /api/tags com timeout curto e fallback silencioso."""

    def test_le_nomes_do_endpoint(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=RespostaTagsFalsa(
                _tags("nexusgeo-qwen3-4b-v2-q4", "qwen3:4b")
            ),
        ) as urlopen:
            nomes = llm_service.list_installed_ollama_models(
                "127.0.0.1:11434"
            )

        self.assertEqual(
            nomes,
            ["nexusgeo-qwen3-4b-v2-q4", "qwen3:4b"],
        )
        self.assertEqual(
            urlopen.call_args.args[0],
            "http://127.0.0.1:11434/api/tags",
        )
        self.assertEqual(
            urlopen.call_args.kwargs["timeout"],
            llm_service.TEMPO_LIMITE_TAGS_OLLAMA,
        )
        self.assertEqual(
            llm_service.TEMPO_LIMITE_TAGS_OLLAMA,
            3.0,
        )

    def test_normaliza_host_com_esquema_e_barra_final(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=RespostaTagsFalsa(_tags("qwen3:4b")),
        ) as urlopen:
            llm_service.list_installed_ollama_models(
                "http://localhost:11434/"
            )

        self.assertEqual(
            urlopen.call_args.args[0],
            "http://localhost:11434/api/tags",
        )

    def test_servico_indisponivel_devolve_lista_vazia(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=OSError("Ollama fora do ar"),
        ):
            self.assertEqual(
                llm_service.list_installed_ollama_models(),
                [],
            )

    def test_json_invalido_devolve_lista_vazia(self):
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=ValueError("JSON inválido"),
        ):
            self.assertEqual(
                llm_service.list_installed_ollama_models(),
                [],
            )

    def test_resposta_sem_models_devolve_lista_vazia(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=RespostaTagsFalsa({"models": "inesperado"}),
        ):
            self.assertEqual(
                llm_service.list_installed_ollama_models(),
                [],
            )


class TestResolveDefaultOllamaModel(unittest.TestCase):
    """Prioridade, fallback e escolha explícita do modelo padrão."""

    def test_prefere_q4_quando_instalado(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["llama3:8b", "nexusgeo-qwen3-4b-v2-q4", "qwen3:4b"],
        ):
            self.assertEqual(
                llm_service.resolve_default_ollama_model(),
                "nexusgeo-qwen3-4b-v2-q4",
            )

    def test_prefere_q4_mesmo_com_tag_latest(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["nexusgeo-qwen3-4b-v2-q4:latest", "qwen3:4b"],
        ):
            self.assertEqual(
                llm_service.resolve_default_ollama_model(),
                "nexusgeo-qwen3-4b-v2-q4",
            )

    def test_cai_para_v2_quando_q4_ausente(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["nexusgeo-qwen3-4b-v2", "qwen3:4b"],
        ):
            self.assertEqual(
                llm_service.resolve_default_ollama_model(),
                "nexusgeo-qwen3-4b-v2",
            )

    def test_fallback_qwen3_4b_quando_nenhum_preferido(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["llama3:8b", "mistral:7b"],
        ):
            self.assertEqual(
                llm_service.resolve_default_ollama_model(),
                "qwen3:4b",
            )

    def test_fallback_quando_api_tags_falha(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=[],
        ):
            self.assertEqual(
                llm_service.resolve_default_ollama_model(),
                "qwen3:4b",
            )

    def test_modelo_configurado_tem_prioridade(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["nexusgeo-qwen3-4b-v2-q4"],
        ) as listar:
            self.assertEqual(
                llm_service.resolve_default_ollama_model(
                    configured_model="llama3:8b"
                ),
                "llama3:8b",
            )

        listar.assert_not_called()

    def test_repassa_o_host_para_a_consulta(self):
        with mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=[],
        ) as listar:
            llm_service.resolve_default_ollama_model(
                ollama_host="http://10.0.0.2:11434"
            )

        listar.assert_called_once_with("http://10.0.0.2:11434")


class TestModeloPadraoDoSistema(unittest.TestCase):
    """O serviço usa o modelo local preferido, com cache por processo."""

    def tearDown(self):
        llm_service.limpar_cache_modelo_padrao()

    def test_prefere_q4_quando_ollama_esta_no_fallback(self):
        with mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            llm_service.MODELO_FALLBACK,
        ), mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["nexusgeo-qwen3-4b-v2-q4"],
        ):
            llm_service.limpar_cache_modelo_padrao()

            self.assertEqual(
                llm_service.modelo_padrao_do_sistema(),
                "nexusgeo-qwen3-4b-v2-q4",
            )

    def test_modelo_configurado_explicitamente_e_respeitado(self):
        with mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            "llama3:8b",
        ), mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["nexusgeo-qwen3-4b-v2-q4"],
        ) as listar:
            self.assertEqual(
                llm_service.modelo_padrao_do_sistema(),
                "llama3:8b",
            )

        listar.assert_not_called()

    def test_cache_evita_consultas_repetidas(self):
        with mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            llm_service.MODELO_FALLBACK,
        ), mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=["qwen3:4b"],
        ) as listar:
            llm_service.limpar_cache_modelo_padrao()

            llm_service.modelo_padrao_do_sistema()
            llm_service.modelo_padrao_do_sistema()

        listar.assert_called_once()

    def test_qwen3_4b_quando_ollama_indisponivel(self):
        with mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            llm_service.MODELO_FALLBACK,
        ), mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=[],
        ):
            llm_service.limpar_cache_modelo_padrao()

            self.assertEqual(
                llm_service.modelo_padrao_do_sistema(),
                "qwen3:4b",
            )


class TestListarModelosLocaisCache(unittest.TestCase):
    """A lista de modelos instalados alimenta o cache do padrão."""

    def tearDown(self):
        llm_service.limpar_cache_modelo_padrao()

    def test_lista_alimenta_cache_com_o_modelo_preferido(self):
        resposta = SimpleNamespace(
            models=[
                SimpleNamespace(model="llama3:8b"),
                SimpleNamespace(model="nexusgeo-qwen3-4b-v2-q4"),
            ]
        )

        with mock.patch.object(
            llm_service.cliente,
            "list",
            return_value=resposta,
        ), mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            llm_service.MODELO_FALLBACK,
        ):
            llm_service.limpar_cache_modelo_padrao()

            nomes = llm_service.listar_modelos_locais()

            self.assertEqual(
                nomes,
                ["llama3:8b", "nexusgeo-qwen3-4b-v2-q4"],
            )
            self.assertEqual(
                llm_service.modelo_padrao_do_sistema(),
                "nexusgeo-qwen3-4b-v2-q4",
            )

    def test_sem_consulta_de_rede_usa_o_fallback(self):
        with mock.patch.object(
            llm_service,
            "OLLAMA_MODEL",
            llm_service.MODELO_FALLBACK,
        ), mock.patch.object(
            llm_service,
            "list_installed_ollama_models",
            return_value=[],
        ) as listar:
            llm_service.limpar_cache_modelo_padrao()

            self.assertEqual(
                llm_service.modelo_padrao_do_sistema(
                    consultar_ollama=False
                ),
                "qwen3:4b",
            )

        listar.assert_not_called()


class TestConstantes(unittest.TestCase):
    """A ordem dos modelos preferidos é a documentada."""

    def test_ordem_de_preferencia(self):
        self.assertEqual(
            llm_service.PREFERRED_LOCAL_MODELS,
            (
                "nexusgeo-qwen3-4b-v2-q4",
                "nexusgeo-qwen3-4b-v2",
                "qwen3:4b",
            ),
        )


if __name__ == "__main__":
    unittest.main()
