"""Testes de neutralização de fórmulas nas exportações CSV/XLSX.

Os dados de APIs públicas, documentos e respostas do LLM não são
confiáveis. Um título começando com "=" não pode virar fórmula quando
o usuário abre o arquivo exportado no Excel ou no LibreOffice.
"""

from __future__ import annotations

import io
import unittest

import openpyxl
import pandas as pd

from services.table_extractor import gerar_csv, gerar_excel


def _tabela(valores, coluna="nome"):
    df = pd.DataFrame({coluna: valores})

    return {
        "titulo": "Teste de fórmula",
        "secao": "Segurança",
        "origem": "teste",
        "pagina": 1,
        "formato": "tabela",
        "df_limpo": df,
        "df_bruto": df.copy(),
        "colunas_numericas": [],
        "unidades": {},
        "observacoes": [],
    }


class TestFormulasCsv(unittest.TestCase):
    """O CSV precisa neutralizar os quatro prefixos perigosos."""

    def test_prefixos_perigosos_recebem_apostrofo(self):
        conteudo = gerar_csv(
            _tabela(["=1+1", "+1+1", "-1-1", "@SUM(1,2)"])
        ).decode("utf-8-sig")

        for valor in ("'=1+1", "'+1+1", "'-1-1", "'@SUM(1,2)"):
            self.assertIn(valor, conteudo)

    def test_texto_normal_nao_e_alterado(self):
        conteudo = gerar_csv(_tabela(["Granito", "Arenito"])).decode(
            "utf-8-sig"
        )

        self.assertIn("Granito", conteudo)
        self.assertIn("Arenito", conteudo)
        self.assertNotIn("'Granito", conteudo)

    def test_cabecalho_perigoso_tambem_e_neutralizado(self):
        conteudo = gerar_csv(_tabela(["x"], coluna="=coluna")).decode(
            "utf-8-sig"
        )

        self.assertIn("'=coluna", conteudo)


class TestFormulasExcel(unittest.TestCase):
    """O XLSX precisa manter as células como texto, nunca como fórmula."""

    def _carregar(self, tabela):
        conteudo = gerar_excel(tabela)
        return openpyxl.load_workbook(io.BytesIO(conteudo))

    def test_celulas_perigosas_sao_texto(self):
        livro = self._carregar(
            _tabela(["=1+1", "+1+1", "-1-1", "@SUM(1,2)"])
        )
        aba = livro["Dados"]

        for linha, valor in enumerate(
            ["=1+1", "+1+1", "-1-1", "@SUM(1,2)"],
            start=2,
        ):
            celula = aba.cell(row=linha, column=1)

            self.assertEqual(celula.value, valor)
            self.assertEqual(celula.data_type, "s")

    def test_texto_normal_permanece_texto(self):
        livro = self._carregar(_tabela(["Granito", "Arenito"]))
        aba = livro["Dados"]

        self.assertEqual(aba["A2"].value, "Granito")
        self.assertEqual(aba["A2"].data_type, "s")

    def test_cabecalho_perigoso_e_texto(self):
        livro = self._carregar(_tabela(["x"], coluna="=coluna"))
        aba = livro["Dados"]

        self.assertEqual(aba["A1"].value, "=coluna")
        self.assertEqual(aba["A1"].data_type, "s")
