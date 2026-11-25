"""Testes unitários do montador de contexto (D1).

Validam as faixas 15/45/25/15, o corte por orçamento, a prioridade das
evidências por score, a preferência por mensagens recentes e a margem
de geração que nunca entra no texto enviado ao modelo.
"""

from __future__ import annotations

import unittest

from core import context_builder


class TestOrcamento(unittest.TestCase):
    """Divisão da janela e validação dos percentuais."""

    def test_percentuais_do_roteiro_somam_cem(self):
        total = sum(context_builder.PERCENTUAIS_CONTEXTO.values())

        self.assertAlmostEqual(total, 1.0)
        self.assertEqual(
            context_builder.PERCENTUAIS_CONTEXTO["identidade"],
            0.15,
        )
        self.assertEqual(
            context_builder.PERCENTUAIS_CONTEXTO["evidencias"],
            0.45,
        )
        self.assertEqual(
            context_builder.PERCENTUAIS_CONTEXTO["sessao"],
            0.25,
        )
        self.assertEqual(
            context_builder.PERCENTUAIS_CONTEXTO["margem_geracao"],
            0.15,
        )

    def test_orcamento_de_mil_tokens(self):
        orcamento = context_builder.calcular_orcamento(1000)

        self.assertEqual(orcamento["identidade"], 150)
        self.assertEqual(orcamento["evidencias"], 450)
        self.assertEqual(orcamento["sessao"], 250)
        self.assertEqual(orcamento["margem_geracao"], 150)
        self.assertEqual(orcamento["entrada"], 850)

    def test_percentuais_em_porcentagem_sao_aceitos(self):
        orcamento = context_builder.calcular_orcamento(
            1000,
            {
                "identidade": 15,
                "evidencias": 45,
                "sessao": 25,
                "margem_geracao": 15,
            },
        )

        self.assertEqual(orcamento["identidade"], 150)
        self.assertEqual(orcamento["margem_geracao"], 150)

    def test_soma_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            context_builder.calcular_orcamento(
                1000,
                {
                    "identidade": 20,
                    "evidencias": 45,
                    "sessao": 25,
                    "margem_geracao": 15,
                },
            )

    def test_limite_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            context_builder.calcular_orcamento(0)


class TestBlocos(unittest.TestCase):
    """Corte e composição dos três blocos de entrada."""

    def test_cada_bloco_respeita_seu_teto(self):
        identidade = "R" * 4000
        evidencias = [
            {
                "evidence_id": "ev_1",
                "fonte": "RIGeo",
                "texto": "E" * 4000,
            }
        ]
        mensagens = [
            {"role": "user", "content": "M" * 2000},
            {"role": "assistant", "content": "N" * 2000},
        ]

        contexto = context_builder.montar_contexto(
            identidade=identidade,
            evidencias=evidencias,
            resumo_sessao="Resumo " * 500,
            mensagens=mensagens,
            pergunta="Pergunta " * 500,
            limite_tokens=200,
        )

        for bloco in contexto.blocos:
            self.assertLessEqual(
                bloco.tokens_estimados,
                bloco.limite_tokens,
                msg=bloco.nome,
            )

        self.assertEqual(contexto.tokens_disponiveis, 170)
        self.assertEqual(contexto.margem_geracao_tokens, 30)
        self.assertTrue(contexto.bloco("identidade").truncado)

    def test_texto_final_usa_tags_das_tres_faixas(self):
        contexto = context_builder.montar_contexto(
            identidade="Regras",
            evidencias=["Evidência"],
            mensagens=[{"role": "user", "content": "Oi"}],
            pergunta="Qual o potencial?",
            limite_tokens=1000,
        )

        self.assertIn("<identidade_regras>", contexto.texto)
        self.assertIn("<evidencias>", contexto.texto)
        self.assertIn("<sessao_resumo>", contexto.texto)
        self.assertIn("Qual o potencial?", contexto.texto)

    def test_sem_conteudo_devolve_texto_vazio(self):
        contexto = context_builder.montar_contexto(limite_tokens=1000)

        self.assertEqual(contexto.texto, "")
        self.assertEqual(contexto.tokens_estimados, 0)
        self.assertEqual(len(contexto.blocos), 3)

    def test_estimar_tokens_tem_minimo_de_um(self):
        self.assertEqual(context_builder.estimar_tokens(""), 0)
        self.assertEqual(context_builder.estimar_tokens("a"), 1)
        self.assertEqual(context_builder.estimar_tokens("a" * 8), 2)


class TestEvidencias(unittest.TestCase):
    """Prioridade e descarte das evidências."""

    def test_score_maior_entra_primeiro(self):
        contexto = context_builder.montar_contexto(
            evidencias=[
                {
                    "evidence_id": "ev_baixa",
                    "texto": "B" * 120,
                    "score": 0.1,
                },
                {
                    "evidence_id": "ev_alta",
                    "texto": "A" * 120,
                    "score": 0.9,
                },
            ],
            limite_tokens=100,
        )

        conteudo = contexto.bloco("evidencias").conteudo

        self.assertIn("ev_alta", conteudo)
        self.assertNotIn("ev_baixa", conteudo)
        self.assertIn("evidencia:1", contexto.descartes)

    def test_evidencia_sem_score_mantem_ordem_de_entrada(self):
        contexto = context_builder.montar_contexto(
            evidencias=[
                {"evidence_id": "ev_1", "texto": "primeira"},
                {"evidence_id": "ev_2", "texto": "segunda"},
            ],
            limite_tokens=1000,
        )

        conteudo = contexto.bloco("evidencias").conteudo

        self.assertLess(
            conteudo.find("ev_1"),
            conteudo.find("ev_2"),
        )


class TestSessao(unittest.TestCase):
    """Resumo progressivo e histórico recente."""

    def test_mensagem_mais_recente_tem_prioridade(self):
        mensagens = [
            {"role": "user", "content": "antiga " * 40},
            {"role": "assistant", "content": "antiga resposta " * 40},
            {"role": "user", "content": "nova " * 40},
        ]

        contexto = context_builder.montar_contexto(
            mensagens=mensagens,
            pergunta="pergunta",
            limite_tokens=100,
        )

        sessao = contexto.bloco("sessao").conteudo

        self.assertIn("nova", sessao)
        self.assertNotIn("antiga resposta", sessao)
        self.assertTrue(
            any(
                descarte.startswith("mensagem:")
                for descarte in contexto.descartes
            )
        )

    def test_resumo_progressivo_entra_no_contexto(self):
        contexto = context_builder.montar_contexto(
            resumo_sessao="A conversa tratou de granito no Amazonas.",
            mensagens=[{"role": "user", "content": "Pergunta anterior"}],
            pergunta="E o ouro?",
            limite_tokens=500,
        )

        sessao = contexto.bloco("sessao").conteudo

        self.assertIn("Resumo progressivo", sessao)
        self.assertIn("granito no Amazonas", sessao)
        self.assertIn("Pergunta anterior", sessao)

    def test_sessao_em_dicionario_e_alias_historico(self):
        contexto = context_builder.construir_contexto(
            sessao={
                "resumo": "Resumo pelo dicionário.",
                "mensagens": [
                    {"role": "assistant", "content": "Mensagem do dicionário"}
                ],
            },
            pergunta="Pergunta",
            limite_tokens=500,
        )

        sessao = contexto.bloco("sessao").conteudo

        self.assertIn("Resumo pelo dicionário", sessao)
        self.assertIn("Mensagem do dicionário", sessao)


if __name__ == "__main__":
    unittest.main()
