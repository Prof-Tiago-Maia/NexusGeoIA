"""Testes de mesa da grade de sondagem De-Ate (Fase D3b).

Cobrem tabelas reais em portugues e ingles, virgula/ponto decimal,
metros/centimetros, sobreposicao, lacuna, linha invalida, ordenacao
estavel, exportacao sanitizada e cancelamento cooperativo com um gerador
lento (<= 3 s). Nenhum teste acessa rede ou o banco do usuario.
"""

from __future__ import annotations

import csv
import io
import math
import threading
import time
import unittest

import openpyxl

from services import sondagem
from services.progress_service import (
    CancelamentoSolicitado,
    EventoCancelamento,
)

TABELA_PT = (
    "Furo;Prof. de;Prof. até;Litologia;Amostra;Observação\n"
    "FQ-01;0,00;2,50;Solo residual;A-01;Topo\n"
    "FQ-01;2,50;5,00;Saprolito;A-02;\n"
    "FQ-01;5,00;8,00;Rocha alterada;A-03;\n"
)

TABELA_EN = (
    "Hole;From (m);To (m);Lithology;Sample;Remarks\n"
    "BH-01;0.00;1.50;Topsoil;S-01;Surface\n"
    "BH-01;1.50;3.00;Saprolite;S-02;\n"
)

TABELA_CM = (
    "Furo;De;Ate;Unidade;Litologia;Amostra\n"
    "FQ-02;0;150;cm;Solo coluvial;A-04\n"
    "FQ-02;150;300;cm;Granito sao;A-05\n"
    "FQ-03;0,5 m;1,25 m;;Rocha;A-06\n"
    "FQ-03;125cm;200cm;;Rocha alterada;A-07\n"
)

TABELA_CONFLITOS = (
    "Furo;De;Ate;Litologia\n"
    "FQ-10;0;2;Solo\n"
    "FQ-11;0;5;Granito\n"
    "FQ-10;1,5;4;Saprolito\n"
    "FQ-10;6;8;Rocha\n"
    "FQ-11;7;9;Rocha\n"
)

TABELA_INVALIDA = (
    "Furo;De;Ate;Litologia\n"
    "FQ-20;0;5;Solo\n"
    "FQ-20;5;5;Contato\n"
    "FQ-20;-1;2;Negativo\n"
    "FQ-20;;2;Sem inicio\n"
    ";0;2;Sem furo\n"
    "FQ-20;0;abc;Fim invalido\n"
)

TABELA_INTERVALO = (
    "Furo;Intervalo;Unidade;Litologia\n"
    "FQ-30;0 - 1,5;m;Solo\n"
    "FQ-30;150 - 300;cm;Saprolito\n"
)

TABELA_EXPORTACAO = (
    "Furo;De;Ate;Litologia;Observacao\n"
    "FQ-40;0;-3,1;=Perigo;@SUM(1,2)\n"
    "FQ-40;-1;2;Solo;+62+1\n"
    "FQ-40;0;3;Rocha;-3.100000\n"
)

# Unidade declarada no proprio cabecalho, entre parenteses.
TABELA_UNIDADES_CABECALHO = (
    "Furo;Prof. de (cm);Prof. até (cm);Litologia\n"
    "FQ-60;0;150;Solo\n"
    "FQ-60;150;300;Saprolito\n"
)

TABELA_INTERVALO_CM = (
    "Furo;Intervalo (cm);Litologia\n"
    "FQ-61;0 - 150;Solo\n"
    "FQ-61;150 - 300;Saprolito\n"
)

TABELA_INTERVALO_UNIDADE_CELULA = (
    "Furo;Intervalo;Litologia\n"
    "FQ-62;0 - 150 cm;Solo\n"
    "FQ-62;150 até 300 cm;Saprolito\n"
    "FQ-63;0 até 2,5 m;Rocha\n"
)

TABELA_COMBINACAO_UNIDADES = (
    "Furo;De;Ate;Unidade\n"
    "FQ-64;150;300;cm\n"
    "FQ-65;1,5 m;4,5 m;cm\n"
    "FQ-66;0;2,5;\n"
)

# Intervalos aninhados e sobrepostos: a espessura total nao pode somar
# a mesma profundidade duas vezes.
TABELA_NINHADA = (
    "Furo;De;Ate\n"
    "FQ-70;0;10\n"
    "FQ-70;2;4\n"
    "FQ-70;3;5\n"
    "FQ-71;0;5\n"
    "FQ-71;4;8\n"
)


class TestCabecalhos(unittest.TestCase):
    """Reconhecimento de cabecalhos PT-BR e EN."""

    def test_mapeia_tabela_portuguesa(self):
        mapa = sondagem.mapear_cabecalhos(
            [
                "Furo",
                "Prof. de (m)",
                "Prof. até (m)",
                "Litologia",
                "Amostra",
                "Observação",
            ]
        )

        self.assertEqual(mapa["furo"], 0)
        self.assertEqual(mapa["de"], 1)
        self.assertEqual(mapa["ate"], 2)
        self.assertEqual(mapa["litologia"], 3)
        self.assertEqual(mapa["amostra"], 4)
        self.assertEqual(mapa["observacao"], 5)

    def test_mapeia_tabela_inglesa(self):
        mapa = sondagem.mapear_cabecalhos(
            [
                "Hole",
                "From (m)",
                "To (m)",
                "Lithology",
                "Sample",
                "Remarks",
                "Unit",
            ]
        )

        self.assertEqual(mapa["furo"], 0)
        self.assertEqual(mapa["de"], 1)
        self.assertEqual(mapa["ate"], 2)
        self.assertEqual(mapa["litologia"], 3)
        self.assertEqual(mapa["amostra"], 4)
        self.assertEqual(mapa["observacao"], 5)
        self.assertEqual(mapa["unidade"], 6)

    def test_aceita_variantes_de_profundidade_e_furo(self):
        mapa = sondagem.mapear_cabecalhos(
            [
                "BH",
                "Depth From (m)",
                "Depth To (m)",
                "Rock Type",
                "Sample No",
            ]
        )

        self.assertEqual(mapa["furo"], 0)
        self.assertEqual(mapa["de"], 1)
        self.assertEqual(mapa["ate"], 2)
        self.assertEqual(mapa["litologia"], 3)
        self.assertEqual(mapa["amostra"], 4)

    def test_intervalo_unico_e_reconhecido(self):
        mapa = sondagem.mapear_cabecalhos(
            ["Furo", "Intervalo", "Unidade", "Litologia"]
        )

        self.assertIn("intervalo", mapa)
        self.assertNotIn("de", mapa)
        self.assertNotIn("ate", mapa)

    def test_cabecalhos_com_unidade_entre_parenteses(self):
        mapa = sondagem.mapear_cabecalhos(
            [
                "Furo",
                "Prof. de (cm)",
                "Prof. até (cm)",
                "Intervalo (m)",
                "Lithology",
            ]
        )

        self.assertEqual(mapa["furo"], 0)
        self.assertEqual(mapa["de"], 1)
        self.assertEqual(mapa["ate"], 2)
        self.assertEqual(mapa["intervalo"], 3)
        self.assertEqual(mapa["litologia"], 4)
        self.assertEqual(
            sondagem.unidades_de_cabecalho(
                ["Furo", "Prof. de (cm)", "Prof. até (cm)"]
            ),
            {"de": "cm", "ate": "cm"},
        )
        self.assertEqual(
            sondagem.unidades_de_cabecalho(
                ["Hole", "From (m)", "To (m)", "Interval (cm)"]
            ),
            {"de": "m", "ate": "m", "intervalo": "cm"},
        )

    def test_cabecalhos_obrigatorios_sao_exigidos(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                "Furo;Litologia\nFQ-01;Solo\n"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "cabecalhos_obrigatorios",
        )

    def test_lista_sem_cabecalhos_e_recusada(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem([["FQ-01", "0", "1"]])

        self.assertEqual(
            contexto.exception.codigo,
            "cabecalhos_ausentes",
        )


class TestNormalizacao(unittest.TestCase):
    """Numeros, unidades e conversao explicita para metros."""

    def test_virgula_e_ponto_decimal(self):
        casos = {
            "2,5": 2.5,
            "2.5": 2.5,
            "1.234,56": 1234.56,
            "1,234.56": 1234.56,
            "-0,5": -0.5,
            "-.5": -0.5,
        }

        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                metros, unidade, origem = (
                    sondagem.converter_profundidade(texto)
                )
                self.assertAlmostEqual(metros, esperado, places=6)
                self.assertEqual(unidade, "m")
                self.assertEqual(origem, "padrao")

    def test_centimetros_sao_convertidos_para_metros(self):
        metros, unidade, origem = sondagem.converter_profundidade(
            "150 cm"
        )

        self.assertAlmostEqual(metros, 1.5, places=6)
        self.assertEqual(unidade, "cm")
        self.assertEqual(origem, "celula")

    def test_unidade_acentuada_e_zero_negativo(self):
        metros, unidade, origem = sondagem.converter_profundidade(
            "150 centímetros"
        )

        self.assertAlmostEqual(metros, 1.5, places=6)
        self.assertEqual(unidade, "cm")
        self.assertEqual(origem, "celula")

        metros, unidade, origem = sondagem.converter_profundidade("-0")

        self.assertEqual(metros, 0.0)
        self.assertEqual(math.copysign(1.0, metros), 1.0)
        self.assertEqual(unidade, "m")
        self.assertEqual(origem, "padrao")

    def test_unidade_da_coluna_vale_quando_a_celula_nao_tem(self):
        metros, unidade, origem = sondagem.converter_profundidade(
            150,
            "cm",
        )

        self.assertAlmostEqual(metros, 1.5, places=6)
        self.assertEqual(unidade, "cm")
        self.assertEqual(origem, "coluna")

    def test_unidade_da_celula_tem_precedencia(self):
        metros, unidade, origem = sondagem.converter_profundidade(
            "150 cm",
            "m",
        )

        self.assertAlmostEqual(metros, 1.5, places=6)
        self.assertEqual(unidade, "cm")
        self.assertEqual(origem, "celula")

    def test_valores_e_unidades_invalidos(self):
        for valor in ("abc", "1,2,3", "1.2.3", "--2", "m"):
            with self.subTest(valor=valor), self.assertRaises(
                sondagem.SondagemError
            ):
                sondagem.converter_profundidade(valor)

        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.converter_profundidade(1.0, "polegadas")

        self.assertEqual(
            contexto.exception.codigo,
            sondagem.MOTIVO_UNIDADE_INVALIDA,
        )


class TestValidacao(unittest.TestCase):
    """Intervalos validos, invalidos, sobreposicoes e lacunas."""

    def test_tabela_portuguesa_continua_valida(self):
        resultado = sondagem.analisar_sondagem(TABELA_PT)

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_validos"], 3)
        self.assertEqual(resultado["total_invalidos"], 0)
        self.assertEqual(resultado["total_furos"], 1)
        self.assertAlmostEqual(
            resultado["intervalos"][2]["ate_m"],
            8.0,
        )

    def test_tabela_inglesa_continua_valida(self):
        resultado = sondagem.analisar_sondagem(TABELA_EN)

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_validos"], 2)
        self.assertAlmostEqual(
            resultado["intervalos"][1]["ate_m"],
            3.0,
        )

    def test_centimetros_e_metros_por_linha(self):
        resultado = sondagem.analisar_sondagem(TABELA_CM)

        self.assertEqual(resultado["total_validos"], 4)
        valores = {
            (item["furo"], item["de_m"], item["ate_m"])
            for item in resultado["intervalos"]
        }
        self.assertIn(("FQ-02", 0.0, 1.5), valores)
        self.assertIn(("FQ-02", 1.5, 3.0), valores)
        self.assertIn(("FQ-03", 0.5, 1.25), valores)
        self.assertIn(("FQ-03", 1.25, 2.0), valores)

    def test_intervalo_unico_aceita_dash_e_a(self):
        resultado = sondagem.analisar_sondagem(TABELA_INTERVALO)

        self.assertEqual(resultado["total_validos"], 2)
        self.assertAlmostEqual(
            resultado["intervalos"][0]["ate_m"],
            1.5,
        )
        self.assertAlmostEqual(
            resultado["intervalos"][1]["ate_m"],
            3.0,
        )

    def test_linha_invalida_nao_descarta_as_validas(self):
        resultado = sondagem.analisar_sondagem(TABELA_INVALIDA)

        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["total_validos"], 1)
        self.assertEqual(resultado["total_invalidos"], 5)
        self.assertEqual(resultado["invalidos"][0]["linha"], 3)
        self.assertEqual(
            resultado["intervalos"][0]["litologia"],
            "Solo",
        )

        codigos = {
            item["linha"]: item["motivos"]
            for item in resultado["invalidos"]
        }
        self.assertIn(
            sondagem.MOTIVO_ATE_NAO_MAIOR,
            codigos[3],
        )
        self.assertIn(
            sondagem.MOTIVO_DE_NEGATIVO,
            codigos[4],
        )
        self.assertIn(
            sondagem.MOTIVO_DE_AUSENTE,
            codigos[5],
        )
        self.assertIn(
            sondagem.MOTIVO_FURO_AUSENTE,
            codigos[6],
        )
        self.assertIn(
            sondagem.MOTIVO_ATE_INVALIDO,
            codigos[7],
        )

    def test_ordem_estavel_por_furo_e_profundidade(self):
        resultado = sondagem.analisar_sondagem(TABELA_CONFLITOS)
        sequencia = [
            (item["furo"], item["de_m"], item["ate_m"])
            for item in resultado["intervalos"]
        ]

        self.assertEqual(
            sequencia,
            [
                ("FQ-10", 0.0, 2.0),
                ("FQ-10", 1.5, 4.0),
                ("FQ-10", 6.0, 8.0),
                ("FQ-11", 0.0, 5.0),
                ("FQ-11", 7.0, 9.0),
            ],
        )

    def test_sobreposicao_e_lacuna_por_furo(self):
        resultado = sondagem.analisar_sondagem(TABELA_CONFLITOS)

        self.assertEqual(resultado["total_sobreposicoes"], 1)
        self.assertEqual(resultado["total_lacunas"], 2)
        self.assertAlmostEqual(
            resultado["sobreposicoes"][0]["sobreposicao_m"],
            0.5,
            places=6,
        )
        self.assertEqual(
            resultado["sobreposicoes"][0]["furo"],
            "FQ-10",
        )
        lacunas = {
            item["furo"]: item["lacuna_m"]
            for item in resultado["lacunas"]
        }
        self.assertAlmostEqual(lacunas["FQ-10"], 2.0)
        self.assertAlmostEqual(lacunas["FQ-11"], 2.0)

        # A sobreposicao de FQ-10 nao contamina FQ-11.
        self.assertAlmostEqual(
            resultado["por_furo"]["FQ-11"]["espessura_total_m"],
            7.0,
        )

    def test_contato_exato_nao_vira_lacuna(self):
        resultado = sondagem.analisar_sondagem(
            "Furo;De;Ate\n"
            "FQ-50;0;2,5\n"
            "FQ-50;2,5;5\n"
        )

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_lacunas"], 0)
        self.assertEqual(resultado["total_sobreposicoes"], 0)

    def test_unidade_no_cabecalho_alimenta_de_e_ate(self):
        resultado = sondagem.analisar_sondagem(
            TABELA_UNIDADES_CABECALHO
        )

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_validos"], 2)
        self.assertEqual(
            [
                (item["de_m"], item["ate_m"])
                for item in resultado["intervalos"]
            ],
            [(0.0, 1.5), (1.5, 3.0)],
        )

        for item in resultado["intervalos"]:
            self.assertEqual(item["unidade"], "cm")
            self.assertEqual(item["origem_unidade_de"], "coluna")
            self.assertEqual(item["origem_unidade_ate"], "coluna")

    def test_intervalo_com_unidade_no_cabecalho(self):
        resultado = sondagem.analisar_sondagem(TABELA_INTERVALO_CM)

        self.assertTrue(resultado["ok"])
        self.assertEqual(
            [
                (item["de_m"], item["ate_m"])
                for item in resultado["intervalos"]
            ],
            [(0.0, 1.5), (1.5, 3.0)],
        )

    def test_intervalo_aceita_unidade_em_qualquer_lado_e_ate_acentuado(self):
        resultado = sondagem.analisar_sondagem(
            TABELA_INTERVALO_UNIDADE_CELULA
        )

        self.assertTrue(resultado["ok"])
        valores = {
            (item["furo"], item["de_m"], item["ate_m"])
            for item in resultado["intervalos"]
        }
        self.assertIn(("FQ-62", 0.0, 1.5), valores)
        self.assertIn(("FQ-62", 1.5, 3.0), valores)
        self.assertIn(("FQ-63", 0.0, 2.5), valores)

        for item in resultado["intervalos"]:
            # A unidade escrita na celula do intervalo vale para os dois
            # limites, inclusive para o lado sem sufixo.
            self.assertEqual(item["origem_unidade_de"], "celula")
            self.assertEqual(item["origem_unidade_ate"], "celula")

    def test_combinacao_de_unidade_celula_coluna_e_padrao(self):
        resultado = sondagem.analisar_sondagem(
            TABELA_COMBINACAO_UNIDADES
        )

        self.assertTrue(resultado["ok"])
        itens = {item["furo"]: item for item in resultado["intervalos"]}

        self.assertEqual(
            (itens["FQ-64"]["de_m"], itens["FQ-64"]["ate_m"]),
            (1.5, 3.0),
        )
        self.assertEqual(itens["FQ-64"]["origem_unidade_de"], "coluna")
        self.assertEqual(
            (itens["FQ-65"]["de_m"], itens["FQ-65"]["ate_m"]),
            (1.5, 4.5),
        )
        self.assertEqual(itens["FQ-65"]["origem_unidade_de"], "celula")
        self.assertEqual(
            (itens["FQ-66"]["de_m"], itens["FQ-66"]["ate_m"]),
            (0.0, 2.5),
        )
        self.assertEqual(itens["FQ-66"]["unidade"], "m")
        self.assertEqual(itens["FQ-66"]["origem_unidade_de"], "padrao")
        self.assertEqual(itens["FQ-66"]["origem_unidade_ate"], "padrao")

    def test_intervalos_aninhados_nao_somam_espessura_duplicada(self):
        resultado = sondagem.analisar_sondagem(TABELA_NINHADA)

        self.assertEqual(resultado["total_sobreposicoes"], 3)
        self.assertEqual(resultado["total_lacunas"], 0)

        aninhados = {
            item["linha"]: item
            for item in resultado["intervalos"]
            if item["furo"] == "FQ-70"
        }

        # 0-10, 2-4 e 3-5: cada linha interna se sobrepoe em 2 m, nao
        # nos 8 m ou 7 m que a distancia ate o fim do intervalo externo
        # sugeriria.
        self.assertAlmostEqual(
            aninhados[3]["sobreposicao_m"], 2.0, places=6
        )
        self.assertAlmostEqual(
            aninhados[4]["sobreposicao_m"], 2.0, places=6
        )
        self.assertEqual(
            resultado["por_furo"]["FQ-70"]["espessura_total_m"],
            10.0,
        )
        self.assertEqual(
            resultado["por_furo"]["FQ-70"]["sobreposicoes"],
            2,
        )

        # Sobreposicao parcial fora do aninhamento: 0-5 e 4-8 cobrem
        # 8 m no total e 1 m de sobreposicao.
        self.assertEqual(
            resultado["por_furo"]["FQ-71"]["espessura_total_m"],
            8.0,
        )
        self.assertAlmostEqual(
            resultado["sobreposicoes"][-1]["sobreposicao_m"],
            1.0,
            places=6,
        )

    def test_zero_negativo_e_normalizado(self):
        resultado = sondagem.analisar_sondagem(
            "Furo;De;Ate\n"
            "FQ-72;-0;1\n"
        )
        item = resultado["intervalos"][0]

        self.assertEqual(item["de_m"], 0.0)
        self.assertEqual(math.copysign(1.0, item["de_m"]), 1.0)
        self.assertEqual(
            resultado["por_furo"]["FQ-72"]["de_m"],
            0.0,
        )
        self.assertEqual(
            math.copysign(
                1.0,
                resultado["por_furo"]["FQ-72"]["de_m"],
            ),
            1.0,
        )

        texto = sondagem.gerar_csv_sondagem(resultado).decode(
            "utf-8-sig"
        )
        self.assertIn("0,0", texto)
        self.assertNotIn("-0,0", texto)


class TestColunasEDelimitadores(unittest.TestCase):
    """Largura de campos e separador nao confundem virgula decimal."""

    def test_virgula_decimal_com_ponto_e_virgula(self):
        cabecalhos, linhas, deslocamento = sondagem.ler_tabela_texto(
            "Furo;De;Ate\n"
            "FQ-01;0,0;1,5\n"
            "FQ-01;1,5;3,25\n"
        )

        self.assertEqual(cabecalhos, ["Furo", "De", "Ate"])
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0], ["FQ-01", "0,0", "1,5"])
        self.assertEqual(deslocamento, 1)

    def test_tabulacao_e_escolhida_pela_tabela_inteira(self):
        resultado = sondagem.analisar_sondagem(
            "Furo\tDe\tAte\n"
            "FQ-01\t0\t1,5\n"
        )

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total_validos"], 1)

    def test_coluna_extra_e_recusada(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                "Furo;De;Ate\n"
                "FQ-01;0;1,5;extra\n"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "tabela_desalinhada",
        )
        self.assertIn("2", contexto.exception.detalhe)

    def test_virgula_decimal_com_separador_errado_e_recusada(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                "Furo,De,Ate\n"
                "FQ-01,0,1,5\n"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "tabela_desalinhada",
        )

    def test_lista_com_coluna_extra_e_recusada(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                [["FQ-01", "0", "1", "extra"]],
                cabecalhos=["Furo", "De", "Ate"],
            )

        self.assertEqual(
            contexto.exception.codigo,
            "tabela_desalinhada",
        )

    def test_linha_curta_e_recusada(self):
        with self.assertRaises(sondagem.SondagemError) as contexto:
            sondagem.analisar_sondagem(
                "Furo;De;Ate\n"
                "FQ-01;0\n"
            )

        self.assertEqual(
            contexto.exception.codigo,
            "tabela_desalinhada",
        )


class TestExportacao(unittest.TestCase):
    """CSV/XLSX sanitizados sem perder numeros negativos validos."""

    def _resultado(self):
        return sondagem.analisar_sondagem(TABELA_EXPORTACAO)

    def test_csv_neutraliza_formulas_e_preserva_negativos(self):
        resultado = self._resultado()
        bruto = sondagem.gerar_csv_sondagem(resultado)
        linhas = list(
            csv.reader(
                io.StringIO(bruto.decode("utf-8-sig")),
                delimiter=";",
            )
        )

        cabecalho = linhas[0]
        coluna_litologia = cabecalho.index("litologia")
        coluna_observacao = cabecalho.index("observacao")
        coluna_de_original = cabecalho.index("de_original")
        coluna_de_m = cabecalho.index("de_m")

        self.assertEqual(linhas[1][coluna_litologia], "'=Perigo")
        self.assertEqual(
            linhas[1][coluna_observacao],
            "'@SUM(1,2)",
        )
        self.assertEqual(linhas[2][coluna_observacao], "'+62+1")
        # Numero negativo textual nao recebe apostrofo e o valor
        # numerico calculado continua legivel.
        self.assertEqual(linhas[2][coluna_de_original], "-1")
        self.assertEqual(linhas[2][coluna_de_m], "-1,0")
        self.assertEqual(
            linhas[3][coluna_observacao],
            "-3.100000",
        )

    def test_xlsx_neutraliza_formulas_como_texto(self):
        resultado = self._resultado()
        livro = openpyxl.load_workbook(
            io.BytesIO(sondagem.gerar_xlsx_sondagem(resultado))
        )
        aba = livro["Sondagem"]

        cabecalhos = [
            celula.value for celula in aba[1]
        ]
        coluna_litologia = cabecalhos.index("litologia") + 1
        coluna_de_m = cabecalhos.index("de_m") + 1

        celula = aba.cell(row=2, column=coluna_litologia)
        self.assertEqual(celula.value, "=Perigo")
        self.assertEqual(celula.data_type, "s")
        self.assertEqual(
            aba.cell(row=2, column=coluna_de_m).value,
            0.0,
        )
        self.assertEqual(
            aba.cell(row=2, column=coluna_de_m).data_type,
            "n",
        )

    def test_exportacao_inclui_linha_invalida(self):
        resultado = self._resultado()
        bruto = sondagem.gerar_csv_sondagem(resultado)
        texto = bruto.decode("utf-8-sig")

        self.assertIn("invalido", texto)
        self.assertIn("ate_nao_maior_que_de", texto)
        self.assertIn("de_negativo", texto)


class _GeradorLento:
    """Gerador de linhas com pausa observavel entre registros."""

    def __init__(self, total=2000, intervalo=0.02):
        self.total = total
        self.intervalo = intervalo
        self.consumidos = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.consumidos >= self.total:
            raise StopIteration

        time.sleep(self.intervalo)
        self.consumidos += 1
        return ["FQ-99", str(self.consumidos), str(self.consumidos + 1)]


class TestCancelamentoSondagem(unittest.TestCase):
    """O parser respeita o Event e encerra em menos de 3 s."""

    def test_cancelamento_interrompe_gerador_lento(self):
        gerador = _GeradorLento(total=2000, intervalo=0.02)
        evento = EventoCancelamento()
        resultado = {}

        def executar():
            try:
                sondagem.analisar_sondagem(
                    gerador,
                    cabecalhos=["Furo", "De", "Ate"],
                    cancelamento=evento,
                )
            except BaseException as erro:  # noqa: BLE001 - inspecao
                resultado["erro"] = erro

        thread = threading.Thread(target=executar, daemon=True)
        thread.start()
        time.sleep(0.15)

        inicio = time.monotonic()
        evento.cancelar()
        thread.join(3.0)
        decorrido = time.monotonic() - inicio

        self.assertFalse(thread.is_alive())
        self.assertLess(decorrido, 3.0)
        self.assertIsInstance(
            resultado.get("erro"),
            CancelamentoSolicitado,
        )
        self.assertLess(gerador.consumidos, gerador.total)

    def test_cancelamento_antes_de_iniciar_nao_processa(self):
        evento = EventoCancelamento()
        evento.set()

        inicio = time.monotonic()

        with self.assertRaises(CancelamentoSolicitado):
            sondagem.analisar_sondagem(
                "Furo;De;Ate\nFQ-01;0;1\n",
                cancelamento=evento,
            )

        self.assertLess(time.monotonic() - inicio, 3.0)


if __name__ == "__main__":
    unittest.main()
