"""Testes de interface (AppTest) do seletor bilíngue de bandeiras.

O AppTest roda o próprio ``app.py`` em processo, sem navegador, sem
servidor e sem rede: a lista de modelos do Ollama, o início do serviço e
a consulta a ``/api/version`` são mockados.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services.external_api_service import REGIAO_TODAS
from utils.i18n import NOMES_IDIOMA, ROTULOS_IDIOMA

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")


class _RespostaOllama:
    """Resposta mínima do endpoint ``/api/version`` do Ollama."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": "teste"}


class TestSeletorBilingue(unittest.TestCase):
    """Botões de bandeira, tradução da interface e idioma do LLM."""

    def setUp(self):
        self._patch_modelos = patch(
            "services.llm_service.listar_modelos_locais",
            return_value=["qwen3:14b"],
        )
        self._patch_modelos.start()
        self.addCleanup(self._patch_modelos.stop)

        self._patch_ollama = patch(
            "services.llm_service.garantir_ollama_ativo",
            return_value=True,
        )
        self._patch_ollama.start()
        self.addCleanup(self._patch_ollama.stop)

        self._patch_requests = patch(
            "requests.get",
            return_value=_RespostaOllama(),
        )
        self._patch_requests.start()
        self.addCleanup(self._patch_requests.stop)

    def test_dois_botoes_de_bandeira_no_topo_da_barra_lateral(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["idioma"], "pt")

        botao_pt = at.button(key="idioma_pt")
        botao_en = at.button(key="idioma_en")

        self.assertEqual(botao_pt.label, ROTULOS_IDIOMA["pt"])
        self.assertEqual(botao_en.label, ROTULOS_IDIOMA["en"])
        self.assertEqual(botao_pt.proto.help, NOMES_IDIOMA["pt"])
        self.assertEqual(botao_en.proto.help, NOMES_IDIOMA["en"])
        # O idioma ativo aparece como botão primário.
        self.assertEqual(botao_pt.proto.type, "primary")
        self.assertEqual(botao_en.proto.type, "secondary")

    def test_interface_comeca_em_portugues(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        subtitulos = " ".join(item.value for item in at.subheader)
        markdown = " ".join(item.value for item in at.markdown)
        captions = " ".join(item.value for item in at.caption)

        self.assertIn("Base de documentos", subtitulos)
        self.assertIn("Fontes de Dados Ativas", subtitulos)
        self.assertIn("Como usar o NexusGeo IA", markdown)
        self.assertIn("Adicione Documentos Locais", markdown)
        self.assertIn("Dica:", captions)
        self.assertEqual(
            at.chat_input[0].placeholder,
            "Digite sua pergunta...",
        )

    def test_clique_em_en_traduz_a_interface(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.button(key="idioma_en").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["idioma"], "en")

        subtitulos = " ".join(item.value for item in at.subheader)
        markdown = " ".join(item.value for item in at.markdown)
        captions = " ".join(item.value for item in at.caption)

        self.assertIn("Document Base (Upload)", subtitulos)
        self.assertIn("Active Data Sources", subtitulos)
        self.assertIn("Conversation History", subtitulos)
        self.assertIn("How to use NexusGeo IA", markdown)
        self.assertIn("Add Local Documents", markdown)
        self.assertIn("Tip:", captions)
        self.assertEqual(
            at.chat_input[0].placeholder,
            "Type your question...",
        )

        # Os rótulos dos toggles e das seções também acompanham o idioma.
        self.assertEqual(
            at.toggle(key="local_docs_enabled").label,
            "📄 Local Document Base (PDF/MD/TXT)",
        )
        self.assertIn(
            "SGB / RIGeo",
            at.toggle(key="rigeo_enabled").label,
        )
        self.assertEqual(
            at.button(key="novo_chat").label,
            "➕ New Chat",
        )

    def test_volta_para_portugues(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.button(key="idioma_en").click().run()
        at.button(key="idioma_pt").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["idioma"], "pt")

        subtitulos = " ".join(item.value for item in at.subheader)
        markdown = " ".join(item.value for item in at.markdown)

        self.assertIn("Fontes de Dados Ativas", subtitulos)
        self.assertIn("Como usar o NexusGeo IA", markdown)

    def test_regioes_em_ingles_chegam_canonicas_ao_backend(self):
        capturado = {}

        def fake_responder(**parametros):
            capturado.update(parametros)
            return {
                "resposta": "Resposta de teste.",
                "fonte": "Ollama",
                "roteamento": {
                    "intencao": "GERAL",
                    "justificativa": "teste",
                    "origem": "teste",
                    "documentos_locais": [],
                    "usar_documentos": False,
                },
                "dados": {},
                "busca_rigeo": {},
            }

        with patch(
            "core.assistant.responder",
            side_effect=fake_responder,
        ), patch(
            "services.history_service.salvar_conversa",
            return_value="data/historico/teste.json",
        ), patch(
            "services.history_service.gerar_titulo",
            return_value="Pergunta de teste",
        ):
            at = AppTest.from_file(APP, default_timeout=40).run()
            at.button(key="idioma_en").click().run()
            at.toggle(key="intl_geo_enabled").set_value(True).run()

            seletor = at.multiselect(key="intl_geo_regioes")

            # O rótulo exibido acompanha o idioma...
            self.assertEqual(
                list(seletor.options)[0],
                "🌎 All Regions (Global)",
            )
            self.assertEqual(seletor.value, ["🌎 All Regions (Global)"])

            at.chat_input[0].set_value("gold worldwide")
            at.run()

        self.assertFalse(at.exception)
        # ...mas o backend recebe a opção canônica em português.
        self.assertEqual(
            capturado.get("intl_geo_regioes"),
            [REGIAO_TODAS],
        )

    def test_resposta_recebe_o_idioma_ativo(self):
        capturado = {}

        def fake_responder(**parametros):
            capturado.update(parametros)
            return {
                "resposta": "Resposta de teste.",
                "fonte": "Ollama",
                "roteamento": {
                    "intencao": "GERAL",
                    "justificativa": "teste",
                    "origem": "teste",
                    "documentos_locais": [],
                    "usar_documentos": False,
                },
                "dados": {},
                "busca_rigeo": {},
            }

        with patch(
            "core.assistant.responder",
            side_effect=fake_responder,
        ), patch(
            "services.history_service.salvar_conversa",
            return_value="data/historico/teste.json",
        ), patch(
            "services.history_service.gerar_titulo",
            return_value="Pergunta de teste",
        ):
            at = AppTest.from_file(APP, default_timeout=40).run()
            at.button(key="idioma_en").click().run()
            at.chat_input[0].set_value("gold in Canada")
            at.run()

        self.assertFalse(at.exception)
        self.assertEqual(capturado.get("idioma"), "en")


if __name__ == "__main__":
    unittest.main()
