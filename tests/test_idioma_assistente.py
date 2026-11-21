"""Testes offline da instrução de idioma injetada em ``responder``.

As consultas externas, o roteador e a geração pelo LLM são totalmente
mockados: nenhum teste toca a rede, o Ollama ou o disco de documentos.
"""

import unittest
from unittest.mock import patch

import core.assistant as assistant
from utils.i18n import instrucao_idioma_resposta


class TestIdiomaNoPrompt(unittest.TestCase):
    """``responder(..., idioma=...)`` orienta o idioma da resposta."""

    def _responder(self, **kwargs):
        capturado = {}

        def fake_prompt(dados, texto_base=None, pergunta=None):
            return "PROMPT BASE DO TESTE"

        def fake_gerar(**parametros):
            capturado.update(parametros)
            return "RESPOSTA DE TESTE"

        with patch.object(
            assistant,
            "decidir_roteamento",
            return_value={
                "intencao": "GERAL",
                "justificativa": "teste",
                "origem": "teste",
                "documentos_locais": [],
            },
        ), patch.object(
            assistant,
            "consultar_fonte",
            return_value={},
        ), patch.object(
            assistant,
            "montar_prompt_sistema",
            side_effect=fake_prompt,
        ), patch.object(
            assistant,
            "gerar_resposta",
            side_effect=fake_gerar,
        ):
            resultado = assistant.responder(
                "pergunta de teste",
                usar_sgb=False,
                usar_documentos=False,
                **kwargs,
            )

        return resultado, capturado

    def test_portugues_injeta_instrucao_pt_br(self):
        resultado, capturado = self._responder(idioma="pt")
        prompt = capturado["prompt_sistema"]

        self.assertTrue(prompt.startswith("PROMPT BASE DO TESTE"))
        self.assertTrue(
            prompt.endswith(instrucao_idioma_resposta("pt"))
        )
        self.assertIn("Português do Brasil", prompt)
        self.assertEqual(resultado["roteamento"]["idioma"], "pt")

    def test_ingles_injeta_instrucao_em_ingles(self):
        resultado, capturado = self._responder(idioma="en")
        prompt = capturado["prompt_sistema"]

        self.assertTrue(
            prompt.endswith(instrucao_idioma_resposta("en"))
        )
        self.assertIn("English", prompt)
        self.assertNotIn("Português do Brasil", prompt)
        self.assertEqual(resultado["roteamento"]["idioma"], "en")

    def test_idioma_omitido_usa_portugues(self):
        resultado, capturado = self._responder()

        self.assertIn(
            instrucao_idioma_resposta("pt"),
            capturado["prompt_sistema"],
        )
        self.assertEqual(resultado["roteamento"]["idioma"], "pt")

    def test_idioma_desconhecido_cai_no_portugues(self):
        resultado, capturado = self._responder(idioma="es")

        self.assertIn(
            instrucao_idioma_resposta("pt"),
            capturado["prompt_sistema"],
        )
        self.assertEqual(resultado["roteamento"]["idioma"], "pt")


if __name__ == "__main__":
    unittest.main()
