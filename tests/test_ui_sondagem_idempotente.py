"""Idempotência e cache de referências leves na Aba 4 (D3b).

Cobrem: reexecutar a mesma análise não chama o parser de novo; falha de
contrato preserva a grade anterior; o cache de exportação é indexado pela
assinatura da grade e não acumula entradas; "Limpar resultado" zera as
referências leves. Sem navegador, rede ou banco real.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import sondagem
from tests._apptest_isolation import isolar_ambiente_apptest
from utils.i18n import t

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "build" / "_tmp_ui_sondagem_idempotente"

TABELA = (
    "Furo;De;Ate;Litologia\n"
    "FQ-01;0;2,5;Solo\n"
    "FQ-01;2,5;5;Rocha\n"
)

INVALIDA = "Furo;Litologia\nFQ-01;Solo\n"


def _script(nome, tabela):
    """Script AppTest que mantém o texto na sessão e renderiza a aba."""

    BASE.mkdir(parents=True, exist_ok=True)
    caminho = BASE / f"{nome}.py"
    corpo = (
        "import streamlit as st\n"
        "from ui import tab_sondagem\n"
        "st.session_state['idioma'] = 'pt'\n"
        f"st.session_state.setdefault('aba_sondagem_texto', {tabela!r})\n"
        "tab_sondagem.renderizar_aba_sondagem()\n"
    )
    caminho.write_text(corpo, encoding="utf-8")

    return str(caminho)


class TestAbaSondagemIdempotente(unittest.TestCase):
    """A tela não duplica processamento nem perde resultado válido."""

    def setUp(self):
        isolar_ambiente_apptest(self)
        shutil.rmtree(BASE, ignore_errors=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)

    def _abrir(self, nome="idempotente", tabela=TABELA):
        return AppTest.from_file(
            _script(nome, tabela),
            default_timeout=30,
        ).run()

    def test_rerun_sem_mudanca_nao_reanalisa(self):
        real = sondagem.analisar_sondagem

        with patch.object(
            sondagem,
            "analisar_sondagem",
            wraps=real,
        ) as analisar:
            at = self._abrir()
            self.assertFalse(at.exception)
            self.assertEqual(analisar.call_count, 1)

            assinatura = at.session_state["aba_sondagem_assinatura_texto"]

            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(analisar.call_count, 1)
            self.assertEqual(
                at.session_state["aba_sondagem_assinatura_texto"],
                assinatura,
            )

    def test_analisar_de_novo_com_o_mesmo_texto_reaproveita_a_grade(self):
        real = sondagem.analisar_sondagem

        with patch.object(
            sondagem,
            "analisar_sondagem",
            wraps=real,
        ) as analisar:
            at = self._abrir("reanalise")
            self.assertEqual(analisar.call_count, 1)
            resultado_antes = at.session_state["aba_sondagem_resultado"]

            at.button(key="aba_sondagem_analisar").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(analisar.call_count, 1)
        self.assertIs(
            at.session_state["aba_sondagem_resultado"],
            resultado_antes,
        )

    def test_falha_preserva_a_grade_anterior(self):
        at = self._abrir("falha")
        self.assertFalse(at.exception)
        resultado_antes = at.session_state["aba_sondagem_resultado"]
        assinatura_antes = resultado_antes["assinatura"]

        at.text_area(key="aba_sondagem_texto").set_value(INVALIDA).run()
        at.button(key="aba_sondagem_analisar").click().run()

        self.assertFalse(at.exception)
        self.assertTrue(
            any(
                t("sondagem_erro_cabecalhos", "pt").split("{")[0]
                in item.value
                for item in at.error
            )
        )
        preservado = at.session_state["aba_sondagem_resultado"]
        self.assertIsNotNone(preservado)
        self.assertEqual(preservado["assinatura"], assinatura_antes)

    def test_cache_de_exportacao_usa_assinatura_da_grade(self):
        at = self._abrir("cache")
        self.assertFalse(at.exception)

        assinatura = at.session_state["aba_sondagem_resultado"]["assinatura"]
        cache = at.session_state["aba_sondagem_exportacoes"]

        self.assertEqual(list(cache), [assinatura])
        self.assertIn("csv:pt", cache[assinatura])
        self.assertIn("xlsx:pt", cache[assinatura])
        csv_antes = cache[assinatura]["csv:pt"]

        at.run()
        cache_depois = at.session_state["aba_sondagem_exportacoes"]

        self.assertEqual(list(cache_depois), [assinatura])
        self.assertEqual(cache_depois[assinatura]["csv:pt"], csv_antes)

    def test_limpar_remove_referencias_e_cache(self):
        at = self._abrir("limpar")
        self.assertFalse(at.exception)

        at.button(key="aba_sondagem_limpar").click().run()

        self.assertFalse(at.exception)
        self.assertIsNone(at.session_state.get("aba_sondagem_resultado"))
        self.assertIsNone(
            at.session_state.get("aba_sondagem_assinatura_texto")
        )
        self.assertIsNone(
            at.session_state.get("aba_sondagem_exportacoes")
        )


if __name__ == "__main__":
    unittest.main()