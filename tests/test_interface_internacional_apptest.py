"""Testes de interface (AppTest) do grupo internacional, sem navegador.

O AppTest roda o próprio ``app.py`` em processo, sem servidor e sem
Chromium. A lista de modelos do Ollama é mockada para que o teste seja
determinístico e não dependa de serviço local.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services.external_api_service import (
    FONTE_CANADA,
    OPCOES_REGIOES_INTERNACIONAIS,
    REGIAO_TODAS,
)
from tests._apptest_isolation import isolar_ambiente_apptest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")


class _RespostaOllama:
    """Resposta mínima do endpoint ``/api/version`` do Ollama."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": "teste"}


class TestInterfaceServicosInternacionais(unittest.TestCase):
    """Toggle mestre, seletor condicional e guia inicial."""

    def setUp(self):
        isolar_ambiente_apptest(self)

        self._patch_modelos = patch(
            "services.llm_service.listar_modelos_locais",
            return_value=["nexusgeo-qwen3-4b-v2-q4"],
        )
        self._patch_modelos.start()
        self.addCleanup(self._patch_modelos.stop)

        self._patch_ollama = patch(
            "services.llm_service.garantir_ollama_ativo",
            return_value=True,
        )
        self._patch_ollama.start()
        self.addCleanup(self._patch_ollama.stop)

        # O badge do cabeçalho consulta /api/version. A resposta fake
        # mantém o AppTest inteiramente offline.
        self._patch_requests = patch(
            "requests.get",
            return_value=_RespostaOllama(),
        )
        self._patch_requests.start()
        self.addCleanup(self._patch_requests.stop)

    def test_seletor_so_aparece_com_o_toggle_ligado(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)
        self.assertFalse(at.toggle(key="intl_geo_enabled").value)
        self.assertNotIn(
            "usgs_enabled",
            {item.key for item in at.toggle},
        )
        self.assertEqual(
            [item for item in at.multiselect if item.key == "intl_geo_regioes"],
            [],
        )

        at.toggle(key="intl_geo_enabled").set_value(True).run()

        self.assertFalse(at.exception)
        seletor = at.multiselect(key="intl_geo_regioes")
        self.assertEqual(list(seletor.options), list(OPCOES_REGIOES_INTERNACIONAIS))
        self.assertEqual(seletor.value, [REGIAO_TODAS])

    def test_selecao_de_regioes_e_preservada(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.toggle(key="intl_geo_enabled").set_value(True).run()

        escolhidas = [
            OPCOES_REGIOES_INTERNACIONAIS[3],
            OPCOES_REGIOES_INTERNACIONAIS[4],
        ]
        at.multiselect(key="intl_geo_regioes").set_value(escolhidas).run()

        self.assertFalse(at.exception)
        self.assertEqual(
            at.multiselect(key="intl_geo_regioes").value,
            escolhidas,
        )

    def test_guia_inicial_lista_as_bases_brasileiras_e_internacionais(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)
        texto = " ".join(item.value for item in at.caption)

        for termo in (
            "RIGeo",
            "ANA / HidroWeb",
            "SIAGAS / RIMAS",
            "SGB / GeoSGB",
            "ANM / SIGMINE",
            "INDE / GEOSSIT",
            "Macrostrat",
            "OpenAlex",
            "Serviços Geológicos Internacionais",
            "OneGeology",
            "Arábia Saudita",
            "Índia",
        ):
            self.assertIn(termo, texto)

    def test_guia_inicial_traz_dicas_de_combinacao_de_fontes(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)
        texto = " ".join(
            item.value for item in at.markdown
        ) + " " + " ".join(
            item.value for item in at.caption
        )

        for termo in (
            "Combinação de Fontes por Tipo de Consulta",
            "Serviços Geológicos Internacionais",
            "OpenAlex",
            "Macrostrat",
            "SGB / RIGeo",
            "GeoSGB",
            "ANM / SIGMINE",
            "ANA / HidroWeb",
            "SIAGAS",
            "GeoNet",
            "GSJ",
            "USGS",
            "Base Documental Local",
        ):
            self.assertIn(termo, texto)

    def test_resposta_mockada_exibe_fonte_e_tabela_internacional(self):
        contrato = {
            "fonte": "Serviços Geológicos Internacionais",
            "pergunta": "ouro no Canadá",
            "termo_busca": "gold canada",
            "regioes": [OPCOES_REGIOES_INTERNACIONAIS[3]],
            "limite": 16,
            "total": 1,
            "por_fonte": {FONTE_CANADA: 1},
            "registros": [{
                "titulo": "Gold in Canada",
                "autores": "NRCan",
                "ano": "2024",
                "resumo": "Estudo de ouro.",
                "link": "https://exemplo.org/canada",
                "link_pdf": None,
                "fonte": FONTE_CANADA,
                "lat": 45.0,
                "lon": -75.0,
            }],
            "aviso": None,
        }
        resultado = {
            "resposta": "Ouro no Canadá (teste).",
            "fonte": "Serviços Geológicos Internacionais",
            "roteamento": {
                "intencao": "GERAL",
                "justificativa": "teste",
                "origem": "teste",
                "documentos_locais": [],
                "usar_documentos": False,
            },
            "dados": {"intl_geo": contrato},
            "busca_rigeo": {},
        }

        with patch(
            "core.assistant.responder",
            return_value=resultado,
        ), patch(
            "services.history_service.gerar_titulo",
            return_value="Ouro no Canadá",
        ):
            at = AppTest.from_file(APP, default_timeout=40).run()
            at.chat_input[0].set_value("ouro no Canadá")
            at.run()

        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["mensagens"]), 2)

        texto = " ".join(item.value for item in at.markdown)
        self.assertIn("Ouro no Canadá (teste).", texto)
        self.assertIn("Serviços Geológicos Internacionais (1)", texto)
        self.assertIn("Gold in Canada", texto)


if __name__ == "__main__":
    unittest.main()
