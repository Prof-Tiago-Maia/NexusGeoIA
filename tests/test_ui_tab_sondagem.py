"""AppTests da Aba 4 (grade de sondagem De-Ate) da Fase D3b.

A aba e executada isoladamente com AppTest, sem navegador, rede ou banco
real. Os casos cobrem o resumo, a grade, os filtros, os relatorios de
sobreposicao/lacuna/invalidos, os downloads sanitizados e a paridade
PT-BR/EN das chaves novas.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests._apptest_isolation import isolar_ambiente_apptest
from utils.i18n import TEXTOS_I18N, t

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
BASE_SCRIPTS = RAIZ / "build" / "_tmp_ui_sondagem"

TABELA = (
    "Furo;Prof. de;Prof. ate;Unidade;Litologia;Amostra;Observacao\n"
    "FQ-01;0,00;2,50;;Solo;A-01;Topo\n"
    "FQ-01;2,00;4,00;;Saprolito;A-02;Sobreposicao\n"
    "FQ-01;6,00;8,00;;Rocha;A-03;Lacuna\n"
    "FQ-02;0;150;cm;Granito;A-04;\n"
    "FQ-02;150;300;cm;Granito;A-05;\n"
    "FQ-02;abc;400;cm;Invalida;A-06;\n"
)

CHAVES_SONDAGEM = (
    "aba_sondagem",
    "sondagem_titulo",
    "sondagem_caption",
    "sondagem_texto_rotulo",
    "sondagem_texto_ajuda",
    "sondagem_exemplo",
    "sondagem_analisar",
    "sondagem_limpar",
    "sondagem_erro_cabecalhos",
    "sondagem_erro_tabela_desalinhada",
    "sondagem_sucesso",
    "sondagem_metric_intervalos",
    "sondagem_metric_invalidos",
    "sondagem_metric_sobreposicoes",
    "sondagem_metric_lacunas",
    "sondagem_filtros",
    "sondagem_coluna_furo",
    "sondagem_coluna_de",
    "sondagem_coluna_ate",
    "sondagem_coluna_situacao",
    "sondagem_situacao_valido",
    "sondagem_situacao_sobreposicao",
    "sondagem_situacao_lacuna",
    "sondagem_situacao_invalido",
    "sondagem_motivo_de_negativo",
    "sondagem_exportar_csv",
    "sondagem_exportar_xlsx",
)


def executar_script(nome, corpo):
    """Grava o script no workspace e o executa no AppTest."""

    BASE_SCRIPTS.mkdir(parents=True, exist_ok=True)
    caminho = BASE_SCRIPTS / f"{nome}.py"
    caminho.write_text(corpo, encoding="utf-8")

    return AppTest.from_file(str(caminho), default_timeout=30).run()


class TestAbaSondagemAppTest(unittest.TestCase):
    """Renderizacao da grade, filtros e downloads."""

    def setUp(self):
        isolar_ambiente_apptest(self)

    def _abrir(self, texto=TABELA, idioma="pt"):
        corpo = (
            "import streamlit as st\n"
            "from ui import tab_sondagem\n"
            f"st.session_state['idioma'] = {idioma!r}\n"
            f"texto = {texto!r}\n"
            "tab_sondagem.renderizar_aba_sondagem(texto=texto)\n"
        )
        return executar_script(f"aba_sondagem_{idioma}", corpo)

    def test_resumo_grade_e_relatorios(self):
        at = self._abrir()

        self.assertFalse(at.exception)

        metricas = {
            item.label: item.value for item in at.metric
        }
        self.assertEqual(
            metricas[t("sondagem_metric_intervalos", "pt")],
            "5",
        )
        self.assertEqual(
            metricas[t("sondagem_metric_invalidos", "pt")],
            "1",
        )
        self.assertEqual(
            metricas[t("sondagem_metric_sobreposicoes", "pt")],
            "1",
        )
        self.assertEqual(
            metricas[t("sondagem_metric_lacunas", "pt")],
            "1",
        )

        avisos = " ".join(item.value for item in at.warning)
        self.assertIn(
            t("sondagem_aviso_invalidos", "pt").split("{")[0],
            avisos,
        )
        self.assertIn(
            t("sondagem_aviso_sobreposicoes", "pt").split("{")[0],
            avisos,
        )
        self.assertIn(
            t("sondagem_aviso_lacunas", "pt").split("{")[0],
            avisos,
        )

        tabelas = [item.value for item in at.dataframe]
        principal = tabelas[0]
        self.assertIn(
            t("sondagem_coluna_furo", "pt"),
            list(principal.columns),
        )
        self.assertEqual(len(principal), 5)
        self.assertIn(
            "Sobreposição",
            set(principal[t("sondagem_coluna_situacao", "pt")]),
        )
        self.assertIn(
            "Lacuna",
            set(principal[t("sondagem_coluna_situacao", "pt")]),
        )

        # Grade, invalidos, sobreposicoes e lacunas ficam em tabelas
        # separadas e inspecionaveis.
        self.assertGreaterEqual(len(tabelas), 4)

    def test_filtro_por_furo_reduz_a_grade(self):
        at = self._abrir()
        self.assertFalse(at.exception)

        at.selectbox(key="aba_sondagem_filtro_furo").set_value(
            "FQ-02"
        ).run()
        self.assertFalse(at.exception)

        principal = at.dataframe[0].value
        coluna_furo = t("sondagem_coluna_furo", "pt")
        self.assertEqual(set(principal[coluna_furo]), {"FQ-02"})
        self.assertEqual(len(principal), 2)

    def test_busca_textual_e_situacao(self):
        at = self._abrir()
        self.assertFalse(at.exception)

        at.text_input(key="aba_sondagem_filtro_busca").set_value(
            "saprolito"
        ).run()
        self.assertFalse(at.exception)

        principal = at.dataframe[0].value
        self.assertEqual(len(principal), 1)
        self.assertEqual(
            principal[t("sondagem_coluna_litologia", "pt")].iloc[0],
            "Saprolito",
        )

    def test_limpar_resultado_nao_reanalisa_o_exemplo(self):
        at = self._abrir()
        self.assertFalse(at.exception)

        at.button(key="aba_sondagem_limpar").click().run()

        self.assertFalse(at.exception)
        self.assertIsNone(
            at.session_state.get("aba_sondagem_resultado")
        )
        self.assertEqual(list(at.metric), [])

    def test_downloads_sanitizados_aparecem(self):
        at = self._abrir()
        self.assertFalse(at.exception)

        rotulos = [
            item.label for item in at.get("download_button")
        ]
        self.assertIn(t("sondagem_exportar_csv", "pt"), rotulos)
        self.assertIn(t("sondagem_exportar_xlsx", "pt"), rotulos)

    def test_interface_em_ingles(self):
        at = self._abrir(idioma="en")

        self.assertFalse(at.exception)
        self.assertEqual(
            at.subheader[0].value,
            t("sondagem_titulo", "en"),
        )
        rotulos = [
            item.label for item in at.get("download_button")
        ]
        self.assertIn(t("sondagem_exportar_csv", "en"), rotulos)
        self.assertEqual(
            at.metric[0].label,
            t("sondagem_metric_intervalos", "en"),
        )

    def test_erro_de_cabecalho_e_mostrado(self):
        at = self._abrir(texto="Furo;Litologia\nFQ-01;Solo\n")

        self.assertFalse(at.exception)
        self.assertTrue(
            any(
                t("sondagem_erro_cabecalhos", "pt").split("{")[0]
                in item.value
                for item in at.error
            )
        )

    def test_erro_de_tabela_desalinhada_e_mostrado(self):
        at = self._abrir(
            texto=(
                "Furo;De;Ate\n"
                "FQ-01;0;1,5;extra\n"
            )
        )

        self.assertFalse(at.exception)
        self.assertTrue(
            any(
                t(
                    "sondagem_erro_tabela_desalinhada", "pt"
                ).split("{")[0]
                in item.value
                for item in at.error
            )
        )


class TestParidadeI18n(unittest.TestCase):
    """As chaves novas existem nos dois idiomas e nao sao iguais."""

    def test_chaves_existem_nos_dois_idiomas(self):
        for chave in CHAVES_SONDAGEM:
            with self.subTest(chave=chave):
                self.assertIn(chave, TEXTOS_I18N["pt"])
                self.assertIn(chave, TEXTOS_I18N["en"])
                self.assertNotEqual(t(chave, "pt"), t(chave, "en"))

    def test_exemplo_tem_cabecalhos_nos_dois_idiomas(self):
        self.assertIn("Furo;", t("sondagem_exemplo", "pt"))
        self.assertIn("Hole;", t("sondagem_exemplo", "en"))


class _RespostaOllama:
    """Resposta mínima do endpoint /api/version do Ollama."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": "teste"}


class TestTrocaIdiomaPreservaAba(unittest.TestCase):
    """PT-BR <-> EN mantém a aba de sondagem selecionada."""

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

        self._patch_requests = patch(
            "requests.get",
            return_value=_RespostaOllama(),
        )
        self._patch_requests.start()
        self.addCleanup(self._patch_requests.stop)

    def _rotulos(self, idioma):
        return [
            t(chave, idioma)
            for chave in (
                "aba_consulta",
                "aba_espacial",
                "aba_dados",
                "aba_sondagem",
            )
        ]

    def test_pt_para_en_e_volta_mantem_a_quarta_aba(self):
        at = AppTest.from_file(APP, default_timeout=60).run()

        self.assertFalse(at.exception)

        rotulo_pt = t("aba_sondagem", "pt")
        at.session_state["aba_navegacao"] = rotulo_pt
        at.run()

        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_navegacao"], rotulo_pt
        )
        self.assertTrue(
            any(
                item.label == t("sondagem_texto_rotulo", "pt")
                for item in at.text_area
            )
        )

        at.button(key="idioma_en").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            [aba.label for aba in at.tabs],
            self._rotulos("en"),
        )
        self.assertEqual(
            at.session_state["aba_navegacao"],
            t("aba_sondagem", "en"),
        )
        self.assertTrue(
            any(
                item.label == t("sondagem_texto_rotulo", "en")
                for item in at.text_area
            )
        )
        self.assertTrue(
            any(
                t("sondagem_titulo", "en") in item.value
                for item in at.subheader
            )
        )

        # Um rerun sem novo clique não pode perder a aba escolhida.
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_navegacao"],
            t("aba_sondagem", "en"),
        )

        at.button(key="idioma_pt").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_navegacao"],
            t("aba_sondagem", "pt"),
        )
        self.assertEqual(
            [aba.label for aba in at.tabs],
            self._rotulos("pt"),
        )


class TestContratoDeLayout(unittest.TestCase):
    """app.py preserva um unico chat_input, sidebar e ponto de abas."""

    def setUp(self):
        self.codigo = Path(APP).read_text(encoding="utf-8")

    def test_um_unico_chat_input_e_uma_sidebar(self):
        self.assertEqual(self.codigo.count("st.chat_input("), 1)
        self.assertEqual(self.codigo.count("with st.sidebar:"), 1)
        self.assertEqual(self.codigo.count("st.tabs("), 1)

    def test_quarta_aba_delega_para_o_modulo(self):
        self.assertIn(
            "ui_tab_sondagem.renderizar_aba_sondagem()",
            self.codigo,
        )
        self.assertIn('t("aba_sondagem")', self.codigo)


if __name__ == "__main__":
    unittest.main()
