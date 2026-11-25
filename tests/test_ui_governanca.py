"""Testes da renderização e do estado de governança (Fase D1).

Metade dos casos exercita as funções puras de ``ui.governanca`` (sem
runtime da interface); a outra metade roda um script mínimo no
``AppTest`` para confirmar badges, motivo objetivo e tabela de
afirmações. Nenhum teste acessa a rede ou o banco.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import governanca

PASS_DADOS = {
    "answer_markdown": "Resposta técnica.",
    "veredito": "PASS",
    "motivo": "Contrato válido: todas as afirmações OBSERVED têm evidência.",
    "motivo_codigo": "contrato_valido",
    "formato": "contrato",
    "avisos": [],
    "afirmacoes": [
        {
            "texto": "Há ouro no alvo.",
            "classificacao": "OBSERVED",
            "evidence_id": "ev_1",
        },
        {
            "texto": "Pode haver mineralização.",
            "classificacao": "INFERRED",
            "evidence_id": None,
        },
    ],
}

HOLD_DADOS = {
    "answer_markdown": "Resposta em formato livre.",
    "veredito": "HOLD",
    "motivo": "Formato livre detectado: revisão humana necessária.",
    "motivo_codigo": "texto_livre",
    "formato": "texto_livre",
    "avisos": ["Formato livre detectado."],
    "afirmacoes": [],
}


BASE_SCRIPTS = Path(__file__).resolve().parent.parent / "build" / "_tmp_ui_scripts"


def executar_script(nome, corpo):
    """Grava o script no workspace e o executa no AppTest.

    O AppTest.from_string criaria o arquivo em %TEMP%; no ambiente de
    teste do Windows essa pasta pode ser somente leitura. Escrever em
    build/_tmp_ui_scripts mantém o teste dentro do workspace.
    """

    BASE_SCRIPTS.mkdir(parents=True, exist_ok=True)
    caminho = BASE_SCRIPTS / f"{nome}.py"
    caminho.write_text(corpo, encoding="utf-8")

    return AppTest.from_file(str(caminho), default_timeout=30).run()


class TestResumoGovernanca(unittest.TestCase):
    """Funções puras: veredito, cores, contagens e fallback."""

    def test_conta_observed_e_inferred(self):
        resumo = governanca.resumir(PASS_DADOS)

        self.assertEqual(resumo["veredito"], "PASS")
        self.assertEqual(resumo["observed"], 1)
        self.assertEqual(resumo["inferred"], 1)
        self.assertEqual(len(resumo["afirmacoes"]), 2)

    def test_cores_do_veredito(self):
        self.assertEqual(governanca.cor_veredito("PASS"), "green")
        self.assertEqual(governanca.cor_veredito("HOLD"), "orange")
        self.assertEqual(governanca.cor_veredito("FAIL"), "red")
        # Valor desconhecido cai no estado conservador (âmbar).
        self.assertEqual(governanca.cor_veredito("talvez"), "orange")

    def test_veredito_ausente_vira_hold(self):
        resumo = governanca.resumir({"afirmacoes": []})

        self.assertEqual(resumo["veredito"], "HOLD")
        self.assertEqual(governanca.cor_veredito(resumo["veredito"]), "orange")

    def test_resultado_none_devolve_none(self):
        self.assertIsNone(governanca.resumir(None))

    def test_rotulo_do_veredito_nos_dois_idiomas(self):
        self.assertIn("contrato válido", governanca.rotulo_veredito("PASS", "pt"))
        self.assertIn("valid contract", governanca.rotulo_veredito("PASS", "en"))
        self.assertIn("revisão", governanca.rotulo_veredito("HOLD", "pt"))

    def test_classificacao_desconhecida_vira_inferred(self):
        resumo = governanca.resumir({
            "veredito": "PASS",
            "afirmacoes": [
                {"texto": "x", "classificacao": "TALVEZ"},
            ],
        })

        self.assertEqual(resumo["inferred"], 1)
        self.assertEqual(resumo["observed"], 0)


class TestRenderizacaoGovernanca(unittest.TestCase):
    """Badges, motivo e tabela de afirmações no AppTest."""

    def test_pass_renderiza_badges_e_tabela(self):
        dados = json.dumps(PASS_DADOS, ensure_ascii=False)
        at = executar_script(
            "governanca_pass",
            "import json\n"
            "import streamlit as st\n"
            "from ui import governanca\n"
            f"dados = json.loads({dados!r})\n"
            "resumo = governanca.resumir(dados)\n"
            "governanca.renderizar_badges(resumo)\n"
            "governanca.renderizar_detalhe(resumo, 'teste')\n"
        )

        self.assertFalse(at.exception)

        markdown = " ".join(item.value for item in at.markdown)
        self.assertIn("PASS", markdown)
        self.assertIn("OBSERVED · 1", markdown)
        self.assertIn("INFERRED · 1", markdown)

        captions = " ".join(item.value for item in at.caption)
        self.assertIn("Motivo objetivo:", captions)
        self.assertIn("Contrato válido", captions)

        self.assertEqual(len(at.dataframe), 1)
        self.assertEqual(len(at.expander), 1)

    def test_hold_mostra_motivo_objetivo_sem_traceback(self):
        dados = json.dumps(HOLD_DADOS, ensure_ascii=False)
        at = executar_script(
            "governanca_hold",
            "import json\n"
            "import streamlit as st\n"
            "from ui import governanca\n"
            f"dados = json.loads({dados!r})\n"
            "governanca.renderizar_badges(governanca.resumir(dados))\n"
        )

        self.assertFalse(at.exception)

        textos = " ".join(
            [item.value for item in at.markdown]
            + [item.value for item in at.caption]
        )

        self.assertIn("HOLD", textos)
        self.assertIn("Formato livre", textos)
        self.assertNotIn("Traceback", textos)
        self.assertNotIn("Exception", textos)


if __name__ == "__main__":
    unittest.main()