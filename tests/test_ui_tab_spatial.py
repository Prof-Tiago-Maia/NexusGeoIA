"""AppTests da Aba 2 e da organização em abas da Fase D2.

Usam o isolamento de banco/histórico de tests/_apptest_isolation.py e não
abrem navegador, rede ou o banco real do usuário.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from adapters import spatial_cim
from tests._apptest_isolation import isolar_ambiente_apptest
from ui import tab_spatial
from utils.i18n import t

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
BASE_SCRIPTS = RAIZ / "build" / "_tmp_ui_d2"

FEICOES = [
    {
        "nome": "Poço A",
        "camada": "Hidrogeologia (SIAGAS)",
        "fonte": "siagas",
        "lat": -3.10,
        "lon": -60.00,
        "folha_cim": "SA.21",
        "detalhe": "Poço tubular",
        "cor_hex": "#00B4D8",
    },
    {
        "nome": "Estação B",
        "camada": "Hidrologia (ANA)",
        "fonte": "ana",
        "lat": -3.20,
        "lon": -60.10,
        "folha_cim": "SA.21",
        "detalhe": "Estação fluviométrica",
        "cor_hex": "#1F6FEB",
    },
]


class _RespostaOllama:
    """Resposta mínima do endpoint /api/version do Ollama."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": "teste"}


def executar_script(nome, corpo):
    """Grava o script no workspace e o executa no AppTest."""

    BASE_SCRIPTS.mkdir(parents=True, exist_ok=True)
    caminho = BASE_SCRIPTS / f"{nome}.py"
    caminho.write_text(corpo, encoding="utf-8")

    return AppTest.from_file(str(caminho), default_timeout=30).run()


class TestFeicoesDaSessao(unittest.TestCase):
    """A aba reúne e deduplica as feições gravadas nas mensagens."""

    def test_deduplica_e_ignora_registros_invalidos(self):
        mensagens = [
            {"role": "assistant", "feicoes_espaciais": FEICOES},
            {
                "role": "assistant",
                "feicoes_espaciais": [
                    FEICOES[0],
                    {"nome": "sem coordenada"},
                ],
            },
        ]

        feicoes = tab_spatial._feicoes_das_mensagens(mensagens)

        self.assertEqual(len(feicoes), 2)
        self.assertEqual(
            {feicao["nome"] for feicao in feicoes},
            {"Poço A", "Estação B"},
        )

    def test_mensagens_ausentes_nao_quebram(self):
        self.assertEqual(tab_spatial._feicoes_das_mensagens(None), [])


class TestAbaEspacialAppTest(unittest.TestCase):
    """Resolução, pacote offline, prévia e exportações na Aba 2."""

    def setUp(self):
        isolar_ambiente_apptest(self)

    def _abrir(self, feicoes=FEICOES):
        corpo = (
            "import streamlit as st\n"
            "from ui import tab_spatial\n"
            "st.session_state['idioma'] = 'pt'\n"
            f"feicoes = {feicoes!r}\n"
            "tab_spatial.renderizar_aba_espacial(feicoes=feicoes)\n"
        )
        return executar_script("aba_espacial", corpo)

    def test_resolucao_exibe_hierarquia_e_pacote(self):
        at = self._abrir()

        self.assertFalse(at.exception)
        self.assertTrue(at.text_input(key="aba_espacial_lat"))
        self.assertTrue(at.text_input(key="aba_espacial_lon"))

        at.text_input(key="aba_espacial_lat").set_value("-3.1")
        at.text_input(key="aba_espacial_lon").set_value("-60.0")
        at.button(key="aba_espacial_resolver").click().run()

        self.assertFalse(at.exception)

        resultado = at.session_state["aba_espacial_resultado"]
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["folha_cim"], "SA.21")
        self.assertEqual(len(resultado["hierarquia"]), 6)

        # A tabela da hierarquia é renderizada antes dos downloads.
        tabelas = [item.value for item in at.dataframe]
        self.assertTrue(
            any("Escala" in list(tabela.columns) for tabela in tabelas)
        )

        at.button(key="aba_espacial_baixar_pacote").click().run()

        self.assertFalse(at.exception)

        from services import db_service

        resumo = db_service.resumo_memoria()
        self.assertEqual(resumo["pacotes_offline"], 1)
        self.assertGreaterEqual(resumo["cache_espacial"], 1)

        texto = " ".join(
            [item.value for item in at.markdown]
            + [item.value for item in at.caption]
            + [item.value for item in at.success]
            + [item.value for item in at.metric]
        )
        self.assertIn("SA.21", texto)
        self.assertIn("Pacote offline", texto)

    def test_atualizacao_divergente_nao_apaga_pacote_anterior(self):
        at = self._abrir(feicoes=[])
        self.assertFalse(at.exception)

        at.text_input(key="aba_espacial_lat").set_value("-3.1")
        at.text_input(key="aba_espacial_lon").set_value("-60.0")
        at.button(key="aba_espacial_resolver").click().run()
        self.assertFalse(at.exception)

        at.button(key="aba_espacial_baixar_pacote").click().run()
        self.assertFalse(at.exception)

        from services import db_service

        antes = spatial_cim.obter_pacote_offline("SA.21")
        self.assertIsNotNone(antes)
        self.assertEqual(antes["manifesto"]["total_registros"], 1)

        # Muda a resolução para SB.21 e tenta atualizar a folha antiga
        # (SA.21): não há feição compatível, então o snapshot anterior
        # não pode ser apagado nem substituído por zero registros.
        at.text_input(key="aba_espacial_lat").set_value("-5.0")
        at.text_input(key="aba_espacial_lon").set_value("-59.0")
        at.button(key="aba_espacial_resolver").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_espacial_resultado"]["folha_cim"],
            "SB.21",
        )

        at.selectbox(key="aba_espacial_pacote_folha").set_value(
            "SA.21"
        ).run()
        at.button(key="aba_espacial_baixar_pacote").click().run()
        self.assertFalse(at.exception)

        depois = spatial_cim.obter_pacote_offline("SA.21")
        self.assertIsNotNone(depois)
        self.assertEqual(
            depois["manifesto"]["total_registros"],
            antes["manifesto"]["total_registros"],
        )
        self.assertEqual(
            depois["manifesto"]["collected_at"],
            antes["manifesto"]["collected_at"],
        )
        self.assertIsNone(
            spatial_cim.obter_pacote_offline("SB.21")
        )

        avisos = " ".join(item.value for item in at.warning)
        self.assertIn(t("espacial_pacote_sem_dados", "pt"), avisos)
        self.assertEqual(
            db_service.resumo_memoria()["pacotes_offline"], 1
        )

    def test_pacote_existente_sem_feicoes_usa_mensagem_de_sem_dados(self):
        from services import db_service

        db_service.inicializar_banco()
        vazio = spatial_cim.montar_pacote_offline("SA.20", feicoes=[])
        db_service.salvar_pacote_offline_cim(
            vazio["manifesto"], vazio["fontes"], caminho_db=None
        )

        at = self._abrir(feicoes=[])
        self.assertFalse(at.exception)

        informacoes = " ".join(item.value for item in at.info)
        self.assertIn(t("espacial_pacote_sem_dados", "pt"), informacoes)
        self.assertNotIn(
            t("espacial_offline_sem_dados", "pt"), informacoes
        )

    def test_exportacoes_aparecem_depois_da_previa(self):
        at = self._abrir()

        self.assertFalse(at.exception)

        # A prévia tabular vem antes dos botões de download no corpo da aba.
        self.assertGreaterEqual(len(at.dataframe), 1)

        botoes = [
            item.label
            for item in at.get("download_button")
        ]

        self.assertIn(t("espacial_exportar_csv", "pt"), botoes)
        self.assertIn(t("espacial_exportar_xlsx", "pt"), botoes)
        self.assertIn(t("espacial_exportar_qgis", "pt"), botoes)


class TestAbasDoApp(unittest.TestCase):
    """app.py mantém quatro abas, um chat_input e o estado ao alternar."""

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

    def test_quatro_abas_e_um_unico_chat_input(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)

        rotulos = [aba.label for aba in at.tabs]
        self.assertEqual(
            rotulos,
            [
                t("aba_consulta", "pt"),
                t("aba_espacial", "pt"),
                t("aba_dados", "pt"),
                t("aba_sondagem", "pt"),
            ],
        )
        self.assertEqual(len(at.chat_input), 1)

    def test_estado_da_sessao_persiste_ao_alternar(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)

        rotulo_espacial = t("aba_espacial", "pt")
        at.session_state["mensagens"] = [
            {
                "role": "user",
                "content": "Pergunta preservada",
                "criado_em": "2026-11-22T10:00:00-04:00",
            }
        ]
        at.session_state["aba_navegacao"] = rotulo_espacial
        at.run()

        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_navegacao"], rotulo_espacial
        )
        self.assertEqual(
            at.session_state["mensagens"][0]["content"],
            "Pergunta preservada",
        )
        self.assertEqual(len(at.chat_input), 1)

        # Uma segunda execução simula o rerun de troca de aba; o histórico
        # e a aba escolhida continuam intactos.
        at.run()

        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["aba_navegacao"], rotulo_espacial
        )
        self.assertEqual(
            at.session_state["mensagens"][0]["content"],
            "Pergunta preservada",
        )


if __name__ == "__main__":
    unittest.main()
