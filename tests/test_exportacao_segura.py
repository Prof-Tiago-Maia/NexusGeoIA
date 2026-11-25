"""Testes da neutralização central de fórmulas (CSV/XLSX/QGIS) da D2.

Os dados de APIs, documentos e LLM não são confiáveis. Uma célula que
começa com =, +, -, @, tabulação, CR ou LF não pode virar fórmula ao
abrir o arquivo exportado.
"""

from __future__ import annotations

import csv
import io
import json
import unittest

import openpyxl
import pandas as pd

from services.exportacao_segura import (
    PREFIXOS_FORMULA,
    gerar_csv_seguro,
    gerar_geojson_qgis,
    gerar_xlsx_seguro,
    neutralizar_dataframe,
    neutralizar_formula,
    valor_perigoso,
)
from services.spatial_parser import gerar_csv_pontos
from services.table_extractor import gerar_csv, gerar_excel

PREFIXOS = ["=", "+", "-", "@", "\t", "\r", "\n"]


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


class TestFuncaoCentral(unittest.TestCase):
    """O conjunto de prefixos precisa ser exatamente o do Gate D2."""

    def test_prefixos_esperados(self):
        self.assertEqual(set(PREFIXOS_FORMULA), set(PREFIXOS))

        for prefixo in PREFIXOS:
            with self.subTest(prefixo=repr(prefixo)):
                self.assertTrue(valor_perigoso(prefixo + "x"))
                self.assertEqual(
                    neutralizar_formula(prefixo + "x"),
                    "'" + prefixo + "x",
                )

    def test_valores_normais_e_numeros_passam_intactos(self):
        self.assertFalse(valor_perigoso("Granito"))
        self.assertEqual(neutralizar_formula("Granito"), "Granito")
        self.assertEqual(neutralizar_formula(42), 42)
        self.assertEqual(neutralizar_formula(None), None)

    def test_coordenadas_negativas_nao_sao_formulas(self):
        # Regressão D2 -> D3: "-3.100000" começa com "-", mas é uma
        # coordenada numérica e não pode ganhar apóstrofo.
        for valor in (
            "-3.100000",
            "-60.000000",
            "+3.100000",
            "-33.7",
            "-.5",
            "-1e-5",
            "-0.0",
        ):
            with self.subTest(valor=valor):
                self.assertFalse(valor_perigoso(valor))
                self.assertEqual(neutralizar_formula(valor), valor)

        # Texto que apenas começa com sinal continua neutralizado.
        for valor in ("-1-1", "-1+1", "-3.1;=1", "-x"):
            with self.subTest(valor=valor):
                self.assertTrue(valor_perigoso(valor))
                self.assertEqual(
                    neutralizar_formula(valor), "'" + valor
                )

    def test_dataframe_neutraliza_colunas_e_celulas(self):
        df = pd.DataFrame({"=coluna": ["=1+1", "ok"]})
        seguro = neutralizar_dataframe(df)

        self.assertEqual(list(seguro.columns), ["'=coluna"])
        self.assertEqual(seguro.iloc[0, 0], "'=1+1")
        self.assertEqual(seguro.iloc[1, 0], "ok")


class TestCsv(unittest.TestCase):
    """CSV precisa preservar a estrutura e neutralizar cada célula."""

    def test_todos_os_prefixos_em_csv(self):
        df = pd.DataFrame({"nome": [p + "x" for p in PREFIXOS]})
        bruto = gerar_csv_seguro(df).decode("utf-8-sig")
        leitor = csv.reader(io.StringIO(bruto), delimiter=";")
        linhas = list(leitor)

        self.assertEqual(linhas[0][0], "nome")

        for indice, prefixo in enumerate(PREFIXOS, start=1):
            self.assertEqual(linhas[indice][0], "'" + prefixo + "x")

    def test_tabela_de_dados_continua_neutralizando(self):
        conteudo = gerar_csv(_tabela(["=1+1", "+1+1", "-1-1", "@SUM(1,2)"]))

        for valor in ("'=1+1", "'+1+1", "'-1-1", "'@SUM(1,2)"):
            self.assertIn(valor, conteudo.decode("utf-8-sig"))

    def test_csv_de_pontos_para_qgis(self):
        feicoes = [
            {
                "nome": "=Perigo",
                "camada": "Hidrologia (ANA)",
                "lat": -3.1,
                "lon": -60.0,
                "folha_cim": "SA.21",
                "detalhe": "@script",
            }
        ]
        linhas = list(
            csv.reader(
                io.StringIO(
                    gerar_csv_pontos(feicoes).decode("utf-8-sig")
                ),
                delimiter=";",
            )
        )

        self.assertEqual(linhas[0][0], "nome")
        self.assertEqual(linhas[1][0], "'=Perigo")
        self.assertEqual(linhas[1][9], "'@script")


    def test_csv_de_pontos_preserva_coordenadas_negativas(self):
        feicoes = [
            {
                "nome": "Poço negativo",
                "camada": "Hidrogeologia (SIAGAS)",
                "lat": -3.1,
                "lon": -60.0,
                "lat_min": -3.2,
                "lat_max": -3.0,
                "lon_min": -60.1,
                "lon_max": -59.9,
                "folha_cim": "SA.21",
                "detalhe": "Coordenada negativa válida",
            }
        ]
        linhas = list(
            csv.reader(
                io.StringIO(
                    gerar_csv_pontos(feicoes).decode("utf-8-sig")
                ),
                delimiter=";",
            )
        )

        self.assertEqual(
            linhas[1][2:9],
            [
                "-3.100000",
                "-60.000000",
                "SA.21",
                "-3.200000",
                "-3.000000",
                "-60.100000",
                "-59.900000",
            ],
        )

        for celula in linhas[1]:
            self.assertFalse(
                celula.startswith("'"),
                f"célula recebeu apóstrofo indevido: {celula!r}",
            )


class TestXlsx(unittest.TestCase):
    """XLSX precisa manter o valor original, mas como texto."""

    def test_prefixos_no_xlsx_sao_texto(self):
        df = pd.DataFrame({"nome": [p + "x" for p in PREFIXOS]})
        livro = openpyxl.load_workbook(io.BytesIO(gerar_xlsx_seguro(df)))
        aba = livro["Feicoes"]

        for linha, prefixo in enumerate(PREFIXOS, start=2):
            celula = aba.cell(row=linha, column=1)
            self.assertEqual(celula.value, prefixo + "x")
            self.assertEqual(celula.data_type, "s")

    def test_xlsx_mantem_coordenadas_como_numeros(self):
        df = pd.DataFrame(
            {
                "lat": [-3.1, -33.7],
                "lon": [-60.0, -53.4],
                "lat_texto": ["-3.100000", "-33.700000"],
            }
        )
        livro = openpyxl.load_workbook(io.BytesIO(gerar_xlsx_seguro(df)))
        aba = livro["Feicoes"]

        self.assertEqual(aba.cell(row=2, column=1).value, -3.1)
        self.assertEqual(aba.cell(row=2, column=1).data_type, "n")
        self.assertEqual(aba.cell(row=2, column=2).value, -60.0)
        self.assertEqual(aba.cell(row=2, column=2).data_type, "n")
        # Mesmo quando a origem é texto, nada de apóstrofo: o valor
        # numérico permanece legível para o Excel e o QGIS.
        self.assertEqual(
            aba.cell(row=2, column=3).value, "-3.100000"
        )

    def test_exportacao_existente_de_tabela(self):
        livro = openpyxl.load_workbook(
            io.BytesIO(gerar_excel(_tabela(["=1+1", "@x", "-2"])))
        )
        aba = livro["Dados"]

        for linha, valor in enumerate(["=1+1", "@x", "-2"], start=2):
            celula = aba.cell(row=linha, column=1)
            self.assertEqual(celula.value, valor)
            self.assertEqual(celula.data_type, "s")


class TestQGIS(unittest.TestCase):
    """GeoJSON precisa sair como FeatureCollection com atributos seguros."""

    def test_geojson_neutraliza_atributos(self):
        feicoes = [
            {
                "nome": "=Perigo",
                "camada": "@camada",
                "folha_cim": "SA.21",
                "detalhe": "+detalhe",
                "lat": -3.1,
                "lon": -60.0,
                "cor_hex": "#1F6FEB",
            }
        ]
        documento = json.loads(gerar_geojson_qgis(feicoes))

        self.assertEqual(documento["type"], "FeatureCollection")
        self.assertEqual(len(documento["features"]), 1)

        feature = documento["features"][0]
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [-60.0, -3.1])
        self.assertEqual(feature["properties"]["nome"], "'=Perigo")
        self.assertEqual(feature["properties"]["camada"], "'@camada")
        self.assertEqual(feature["properties"]["detalhe"], "'+detalhe")

    def test_geojson_ignora_feicoes_sem_coordenada(self):
        documento = json.loads(
            gerar_geojson_qgis(
                [
                    {"nome": "válida", "lat": -3.1, "lon": -60.0},
                    {"nome": "sem coordenada"},
                    {"nome": "fora", "lat": 999, "lon": 999},
                ]
            )
        )

        self.assertEqual(len(documento["features"]), 1)


if __name__ == "__main__":
    unittest.main()
