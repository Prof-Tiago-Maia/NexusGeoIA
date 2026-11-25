"""Testes do layout adaptativo da Workstation GIS (Fase D4).

O foco é o contrato das funções puras de ui.workstation_layout:
has_active_workspace (estado vazio, parcial e completo) e
compute_epistemic_ratios (proporção OBSERVED x INFERRED). Um bloco final
roda as duas colunas de cartões no AppTest para garantir que a
renderização não toca a rede nem o banco.

Nenhum teste abre data/nexusgeoia.db: os dados são dicionários em
memória, no mesmo formato devolvido por
core.governance.ResultadoGovernanca.para_dict().
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import workstation_layout

BASE_SCRIPTS = Path(__file__).resolve().parent.parent / "build" / "_tmp_ui_scripts"

GOVERNANCA_PARCIAL = {
    "veredito": "HOLD",
    "motivo": "Classificação parcial.",
    "motivo_codigo": "parcial",
    "formato": "contrato",
    "avisos": [],
    "afirmacoes": [
        {
            "texto": "Teor de ouro confirmado.",
            "classificacao": "OBSERVED",
            "evidence_id": "ev_ouro",
        },
        {
            "texto": "A zona pode se estender ao sul.",
            "classificacao": "INFERRED",
            "evidence_id": None,
        },
    ],
}

GOVERNANCA_COMPLETA = {
    "veredito": "PASS",
    "motivo": "Contrato válido.",
    "motivo_codigo": "contrato_valido",
    "formato": "contrato",
    "avisos": [],
    "afirmacoes": [
        {
            "texto": "Ocorrência de ouro no alvo.",
            "classificacao": "OBSERVED",
            "evidence_id": "ev_ouro",
        },
        {
            "texto": "Teor medido em 12 amostras.",
            "classificacao": "OBSERVED",
            "evidence_id": "ev_amostras",
        },
        {
            "texto": "A estrutura mergulha a leste.",
            "classificacao": "OBSERVED",
            "evidence_id": "ev_ouro",
        },
        {
            "texto": "Há potencial para sulfetos em profundidade.",
            "classificacao": "INFERRED",
            "evidence_id": None,
        },
    ],
}

MENSAGEM_COM_FOLHA = {
    "role": "assistant",
    "content": "Folha SB.21-X-B citada.",
    "feicoes_espaciais": [
        {
            "nome": "Alvo A",
            "camada": "Folhas CIM",
            "folha_cim": "SB.21-X-B",
            "lat": -3.1,
            "lon": -60.0,
        }
    ],
}

MENSAGEM_SO_TEXTO = {
    "role": "assistant",
    "content": "Resposta sem coordenada nem folha.",
}


class TestEstadoDoWorkspace(unittest.TestCase):
    """has_active_workspace: vazio, parcial e completo."""

    def test_estado_vazio_mantem_layout_centralizado(self):
        self.assertFalse(workstation_layout.has_active_workspace())
        self.assertFalse(
            workstation_layout.has_active_workspace(
                documentos=[],
                mensagens=[MENSAGEM_SO_TEXTO],
                tabelas=[],
                evidencias=[],
            )
        )

    def test_documento_anexado_ativa_o_workspace(self):
        self.assertTrue(
            workstation_layout.has_active_workspace(
                documentos=["relatorio.pdf"],
            )
        )

    def test_folha_cim_ativa_o_workspace(self):
        self.assertTrue(
            workstation_layout.has_active_workspace(
                mensagens=[MENSAGEM_SO_TEXTO, MENSAGEM_COM_FOLHA],
            )
        )

    def test_ponto_isolado_ativa_o_workspace(self):
        mensagem = {
            "role": "assistant",
            "feicoes_espaciais": [{"lat": -7.2, "lon": -59.8}],
        }

        self.assertTrue(
            workstation_layout.has_active_workspace(mensagens=[mensagem])
        )

    def test_tabela_extraida_ativa_o_workspace(self):
        self.assertTrue(
            workstation_layout.has_active_workspace(
                tabelas=[{"fonte": "ANA", "registros": [{"codigo": "1"}]}],
            )
        )
        self.assertFalse(
            workstation_layout.has_active_workspace(
                tabelas=[{"fonte": "ANA", "registros": []}],
            )
        )

    def test_evidencia_ativa_o_workspace(self):
        self.assertTrue(
            workstation_layout.has_active_workspace(
                evidencias=[{"evidence_id": "ev_ouro", "aderencia": 100}],
            )
        )

    def test_estado_completo_soma_todos_os_sinais(self):
        self.assertTrue(
            workstation_layout.has_active_workspace(
                documentos=["relatorio.pdf"],
                mensagens=[MENSAGEM_COM_FOLHA],
                tabelas=[{"fonte": "ANM", "registros": [{"processo": "1"}]}],
                evidencias=[{"evidence_id": "ev_ouro"}],
            )
        )

    def test_feicoes_e_folhas_sem_repeticao(self):
        feicoes = workstation_layout.feicoes_detectadas(
            [MENSAGEM_COM_FOLHA, MENSAGEM_COM_FOLHA]
        )

        self.assertEqual(len(feicoes), 1)
        self.assertEqual(
            workstation_layout.folhas_cim_detectadas(
                [MENSAGEM_COM_FOLHA, MENSAGEM_COM_FOLHA]
            ),
            ["SB.21-X-B"],
        )


class TestProporcaoEpistemica(unittest.TestCase):
    """compute_epistemic_ratios: vazio, parcial e completo."""

    def test_vazio_devolve_zero(self):
        for entrada in (None, [], [None], {"afirmacoes": []}):
            with self.subTest(entrada=entrada):
                proporcao = workstation_layout.compute_epistemic_ratios(
                    entrada
                )

                self.assertEqual(proporcao["total"], 0)
                self.assertEqual(proporcao["observed_pct"], 0.0)
                self.assertEqual(proporcao["inferred_pct"], 0.0)

    def test_parcial_metade_a_metade(self):
        proporcao = workstation_layout.compute_epistemic_ratios(
            GOVERNANCA_PARCIAL
        )

        self.assertEqual(proporcao["observed"], 1)
        self.assertEqual(proporcao["inferred"], 1)
        self.assertEqual(proporcao["total"], 2)
        self.assertEqual(proporcao["observed_pct"], 50.0)
        self.assertEqual(proporcao["inferred_pct"], 50.0)

    def test_completo_setenta_e_cinco_por_cento(self):
        proporcao = workstation_layout.compute_epistemic_ratios(
            [GOVERNANCA_COMPLETA]
        )

        self.assertEqual(proporcao["observed"], 3)
        self.assertEqual(proporcao["inferred"], 1)
        self.assertEqual(proporcao["total"], 4)
        self.assertEqual(proporcao["observed_pct"], 75.0)
        self.assertEqual(proporcao["inferred_pct"], 25.0)

    def test_percentuais_somam_cem(self):
        proporcao = workstation_layout.compute_epistemic_ratios(
            [GOVERNANCA_PARCIAL, GOVERNANCA_COMPLETA]
        )

        self.assertAlmostEqual(
            proporcao["observed_pct"] + proporcao["inferred_pct"],
            100.0,
        )

    def test_ranking_de_evidencias_por_aderencia(self):
        evidencias = workstation_layout.coletar_evidencias(
            [GOVERNANCA_PARCIAL, GOVERNANCA_COMPLETA]
        )

        self.assertEqual(evidencias[0]["evidence_id"], "ev_ouro")
        self.assertEqual(evidencias[0]["citacoes"], 3)
        self.assertEqual(evidencias[0]["observed"], 3)
        self.assertEqual(evidencias[0]["aderencia"], 100.0)

        self.assertEqual(evidencias[1]["evidence_id"], "ev_amostras")
        self.assertEqual(evidencias[1]["aderencia"], 100.0)


class TestFontesAtivas(unittest.TestCase):
    """Contagem usada no cartão de indicadores."""

    def test_conectores_e_base_local(self):
        self.assertEqual(
            workstation_layout.contar_fontes_ativas({}, local_docs=False),
            0,
        )
        self.assertEqual(
            workstation_layout.contar_fontes_ativas(
                {"ana_enabled": True, "anm_enabled": False},
                local_docs=True,
            ),
            2,
        )


class TestRenderizacaoWorkstation(unittest.TestCase):
    """As duas colunas renderizam no AppTest sem erro."""

    def _executar(self, nome, corpo):
        BASE_SCRIPTS.mkdir(parents=True, exist_ok=True)
        caminho = BASE_SCRIPTS / f"{nome}.py"
        caminho.write_text(corpo, encoding="utf-8")

        return AppTest.from_file(str(caminho), default_timeout=30).run()

    def test_colunas_indicadores_e_rastreabilidade(self):
        at = self._executar(
            "workstation_colunas",
            "from ui import workstation_layout\n"
            "dados = {\n"
            "    'veredito': 'PASS',\n"
            "    'afirmacoes': [\n"
            "        {'texto': 'a', 'classificacao': 'OBSERVED',\n"
            "         'evidence_id': 'ev_1'},\n"
            "        {'texto': 'b', 'classificacao': 'INFERRED'},\n"
            "    ],\n"
            "}\n"
            "proporcao = workstation_layout.compute_epistemic_ratios(dados)\n"
            "evidencias = workstation_layout.coletar_evidencias(dados)\n"
            "workstation_layout.renderizar_indicadores(\n"
            "    fontes_ativas=2, alvos_cim=1, proporcoes=proporcao)\n"
            "workstation_layout.renderizar_rastreabilidade(\n"
            "    evidencias=evidencias, modelo='qwen3:4b', online=True,\n"
            "    proporcoes=proporcao)\n",
        )

        self.assertFalse(at.exception)
        self.assertGreaterEqual(len(at.metric), 2)
        self.assertGreaterEqual(len(at.dataframe), 1)


if __name__ == "__main__":
    unittest.main()
