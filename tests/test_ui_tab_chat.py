"""Testes da Aba 1 (workflow, cartão e proveniência) da Fase D1."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests._apptest_isolation import isolar_ambiente_apptest
from ui import tab_chat

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
BASE_SCRIPTS = RAIZ / "build" / "_tmp_ui_scripts"


def executar_script(nome, corpo):
    """Grava o script no workspace e o executa no AppTest."""

    BASE_SCRIPTS.mkdir(parents=True, exist_ok=True)
    caminho = BASE_SCRIPTS / f"{nome}.py"
    caminho.write_text(corpo, encoding="utf-8")

    return AppTest.from_file(str(caminho), default_timeout=30).run()


class _RespostaOllama:
    """Resposta mínima do endpoint ``/api/version`` do Ollama."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": "teste"}


class TestWorkflow(unittest.TestCase):
    """Conversão entre rótulo exibido e chave canônica."""

    def test_rotulo_e_reverso_nos_dois_idiomas(self):
        for codigo, _chave in tab_chat.WORKFLOWS:
            for idioma in ("pt", "en"):
                rotulo = tab_chat.rotulo_workflow(codigo, idioma)

                self.assertEqual(
                    tab_chat.workflow_do_rotulo(rotulo),
                    codigo,
                )

    def test_rotulo_desconhecido_cai_no_padrao(self):
        self.assertEqual(
            tab_chat.rotulo_workflow("inexistente", "pt"),
            tab_chat.rotulo_workflow(tab_chat.WORKFLOW_PADRAO, "pt"),
        )
        self.assertIsNone(tab_chat.workflow_do_rotulo("Fluxo inventado"))

    def test_instrucao_do_workflow_nos_dois_idiomas(self):
        self.assertIn(
            "Hidrogeologia",
            tab_chat.instrucao_workflow("hidrogeologia", "pt"),
        )
        self.assertIn(
            "Hydrogeology",
            tab_chat.instrucao_workflow("hidrogeologia", "en"),
        )
        # Chave desconhecida cai na instrução do fluxo padrão.
        self.assertIn(
            "Consulta Direta",
            tab_chat.instrucao_workflow("inexistente", "pt"),
        )


class TestProveniencia(unittest.TestCase):
    """Montagem e normalização das linhas de linhagem."""

    def test_monta_linhas_com_origem_e_cache(self):
        dados = {
            "sgb": {
                "registros": [
                    {
                        "titulo": "Artigo RIGeo",
                        "link": "https://exemplo.test/rigeo",
                    },
                ],
            },
            "anm": {
                "registros": [
                    {"processo": "850.000/2020", "titulo": "Processo"},
                ],
                "origem": "cache",
                "cache": {"usado": True, "idade_s": 12.0},
            },
            "ana": {
                "registros": [
                    {
                        "codigo": "12345",
                        "coletado_em": "2026-02-02T10:00:00-04:00",
                    },
                ],
            },
        }

        linhas = tab_chat.montar_proveniencia(
            dados=dados,
            documentos=["estudo.pdf"],
            criado_em="2026-02-03T08:00:00-04:00",
        )

        self.assertEqual(len(linhas), 4)
        self.assertEqual(
            {linha["origem"] for linha in linhas},
            {"live", "cache", "local"},
        )
        self.assertEqual(linhas[0]["source_type"], "ANA / HidroWeb")
        self.assertEqual(linhas[0]["locator"], "12345")
        self.assertEqual(
            linhas[0]["retrieved_at"],
            "2026-02-02T10:00:00-04:00",
        )

        anm = next(
            linha for linha in linhas if "ANM" in linha["source_type"]
        )
        self.assertEqual(anm["origem"], "cache")
        self.assertEqual(anm["locator"], "850.000/2020")

        local = next(
            linha for linha in linhas if linha["origem"] == "local"
        )
        self.assertEqual(local["source_type"], "Base Documental Local")
        self.assertEqual(local["locator"], "estudo.pdf")

    def test_reconstroi_da_mensagem_legada(self):
        mensagem = {
            "role": "assistant",
            "content": "Resposta",
            "fonte": "sgb",
            "criado_em": "2026-02-03T08:00:00-04:00",
            "artigos_rigeo": [
                {"titulo": "A", "link": "https://exemplo.test/a"},
            ],
            "roteamento": {"documentos_locais": ["doc.pdf"]},
        }

        linhas = tab_chat.proveniencia_da_mensagem(mensagem)

        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["source_type"], "RIGeo / SGB")
        self.assertEqual(linhas[0]["retrieved_at"], mensagem["criado_em"])
        self.assertEqual(linhas[1]["origem"], "local")

    def test_proveniencia_gravada_tem_precedencia(self):
        mensagem = {
            "proveniencia": [
                {
                    "source_type": "Fonte",
                    "locator": "x",
                    "retrieved_at": "2026-01-01",
                    "origem": "desconhecida",
                },
            ],
        }

        linhas = tab_chat.proveniencia_da_mensagem(mensagem)

        self.assertEqual(len(linhas), 1)
        # Origem inválida cai no estado Live, nunca quebra a gaveta.
        self.assertEqual(linhas[0]["origem"], "live")


class TestRenderizacao(unittest.TestCase):
    """Seletor de workflow, cartão e gaveta no AppTest."""

    def test_seletor_tem_quatro_workflows_em_portugues(self):
        at = executar_script(
            "workflow_pt",
            "import streamlit as st\n"
            "from ui import tab_chat\n"
            "st.session_state['idioma'] = 'pt'\n"
            "wf = tab_chat.renderizar_seletor_workflow()\n"
            "st.write(wf)\n",
        )

        self.assertFalse(at.exception)

        seletor = at.selectbox(key="workflow_consulta")
        self.assertEqual(len(seletor.options), 4)
        self.assertEqual(seletor.value, "Consulta Direta")
        self.assertEqual(
            list(seletor.options),
            [
                "Consulta Direta",
                "Triagem de Área / Viabilidade Mineral",
                "Hidrogeologia",
                "Sondagem & Litologia",
            ],
        )

    def test_seletor_traduzido_em_ingles(self):
        at = executar_script(
            "workflow_en",
            "import streamlit as st\n"
            "from ui import tab_chat\n"
            "st.session_state['idioma'] = 'en'\n"
            "tab_chat.renderizar_seletor_workflow()\n",
        )

        self.assertFalse(at.exception)

        seletor = at.selectbox(key="workflow_consulta")
        self.assertEqual(seletor.value, "Direct Query")
        self.assertIn("Hydrogeology", list(seletor.options))

    def test_cartao_e_gaveta_de_proveniencia(self):
        governanca = {
            "veredito": "PASS",
            "motivo": "Contrato válido.",
            "afirmacoes": [
                {
                    "texto": "Há ouro.",
                    "classificacao": "OBSERVED",
                    "evidence_id": "ev_1",
                },
            ],
        }
        linhas = [
            {
                "source_type": "RIGeo / SGB",
                "locator": "https://exemplo.test/a",
                "retrieved_at": "2026-01-01T00:00:00-04:00",
                "origem": "cache",
            },
            {
                "source_type": "Base Documental Local",
                "locator": "estudo.pdf",
                "retrieved_at": "2026-01-02T00:00:00-04:00",
                "origem": "local",
            },
        ]

        at = executar_script(
            "cartao_proveniencia",
            "import json\n"
            "import streamlit as st\n"
            "from ui import tab_chat\n"
            "st.session_state['idioma'] = 'pt'\n"
            f"governanca = json.loads({json.dumps(governanca)!r})\n"
            f"linhas = json.loads({json.dumps(linhas)!r})\n"
            "tab_chat.renderizar_cartao_resposta("
            "    'Resposta técnica com evidência.',"
            "    governanca,"
            "    workflow='triagem_area',"
            "    chave='teste',"
            ")\n"
            "tab_chat.renderizar_gaveta_proveniencia(linhas, chave='teste')\n",
        )

        self.assertFalse(at.exception)

        markdown = " ".join(item.value for item in at.markdown)
        self.assertIn("Resposta técnica com evidência.", markdown)
        self.assertIn("PASS", markdown)
        self.assertIn("OBSERVED · 1", markdown)
        self.assertIn("Triagem de Área / Viabilidade Mineral", markdown)

        # A gaveta existe e traz a tabela estruturada nas quatro colunas.
        self.assertEqual(len(at.expander), 2)  # governança + proveniência
        self.assertEqual(len(at.dataframe), 2)

        tabela = at.dataframe[1].value
        self.assertEqual(
            list(tabela.columns),
            ["source_type", "locator", "retrieved_at", "origem"],
        )
        valores = tabela.to_dict(orient="records")
        self.assertEqual(valores[0]["origem"], "Cache Offline")
        self.assertEqual(valores[1]["origem"], "Local")


class TestIntegracaoApp(unittest.TestCase):
    """O app.py monta o seletor e os indicadores D1 na ordem certa."""

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

    def test_seletor_e_indicadores_aparecem_sem_excecao(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)

        seletor = at.selectbox(key="workflow_consulta")
        self.assertEqual(seletor.value, "Consulta Direta")
        self.assertEqual(len(seletor.options), 4)

        textos = " ".join(
            [item.value for item in at.markdown]
            + [item.value for item in at.caption]
        )
        self.assertIn("Ollama online", textos)
        self.assertIn("Persistência:", textos)
        self.assertIn("Roteador:", textos)

    def test_nova_conversa_na_barra_lateral(self):
        at = AppTest.from_file(APP, default_timeout=30).run()

        self.assertFalse(at.exception)
        self.assertTrue(at.button(key="sidebar_nova_conversa").label)


if __name__ == "__main__":
    unittest.main()