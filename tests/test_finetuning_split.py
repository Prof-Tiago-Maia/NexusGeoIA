"""Testes do split determinístico treino/validação/teste.

Verificam integridade do manifesto, ausência de vazamento entre pares
PT-BR/EN, determinismo, recomputação do oráculo e a guarda do banco.
Nenhum teste acessa rede, banco real ou treina pesos.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import unittest
from pathlib import Path

from finetuning import contrato, gerador, oraculo, split
from tests import _db_intocado

BASE = Path(__file__).resolve().parent / "_tmp_finetuning_split"


class TestSplitDeterministico(unittest.TestCase):
    """O split agrupa pares e não deixa gabarito vazar."""

    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()
        cls.manifesto = split.carregar_split()
        cls.por_id = {registro["id"]: registro for registro in cls.registros}

    def setUp(self):
        shutil.rmtree(BASE, ignore_errors=True)
        BASE.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)

    def test_manifesto_existe_e_confere_com_o_dataset(self):
        self.assertTrue(split.ARQUIVO_SPLIT.is_file())
        self.assertEqual(
            self.manifesto["sha256_dataset"],
            gerador.hash_registros(self.registros),
        )
        self.assertEqual(self.manifesto["total_registros"], 300)
        self.assertEqual(self.manifesto["total_pares"], 150)
        self.assertEqual(split.validar_split(self.registros, self.manifesto), [])

    def test_todos_os_registros_aparecem_uma_unica_vez(self):
        ids = [
            identificador
            for item in self.manifesto["pares"]
            for identificador in item["ids"]
        ]

        self.assertEqual(len(ids), len(self.registros))
        self.assertEqual(set(ids), set(self.por_id))

    def test_par_bilingue_nao_vaza_entre_splits(self):
        pares = {}

        for item in self.manifesto["pares"]:
            pares[item["par"]] = item["split"]

            with self.subTest(par=item["par"]):
                self.assertEqual(len(item["ids"]), 2)
                idiomas = {
                    self.por_id[identificador]["idioma"]
                    for identificador in item["ids"]
                }
                self.assertEqual(idiomas, {"pt", "en"})

        self.assertEqual(len(pares), 150)
        self.assertEqual(len(set(pares.values())), 3)

        # Recomputa a atribuição a partir dos registros: os dois idiomas
        # do mesmo par precisam cair no mesmo conjunto.
        atribuicao = split.atribuir_splits(self.registros)
        split_por_par = {}

        for registro in self.registros:
            par = registro["metadados"]["par"]
            split_por_par.setdefault(par, set()).add(
                atribuicao[par]
            )
            self.assertEqual(split_por_par[par], {atribuicao[par]})

        self.assertEqual(
            {par: next(iter(valores)) for par, valores in split_por_par.items()},
            pares,
        )

    def test_cada_split_tem_as_tres_tarefas_e_os_dois_idiomas(self):
        for nome in split.SPLITS:
            registros = split.registros_do_split(
                nome,
                self.registros,
            )
            self.assertTrue(registros, nome)
            self.assertEqual(
                {registro["tarefa"] for registro in registros},
                set(contrato.TAREFAS),
                nome,
            )
            self.assertEqual(
                {registro["idioma"] for registro in registros},
                {"pt", "en"},
                nome,
            )

    def test_split_e_deterministico_entre_geracoes(self):
        primeiro = split.gerar_split(self.registros)
        segundo = split.gerar_split(self.registros)

        self.assertEqual(primeiro, segundo)
        self.assertEqual(
            split.atribuir_splits(self.registros),
            split.atribuir_splits(list(reversed(self.registros))),
        )

    def test_oraculo_recomputa_os_registros_de_todos_os_splits(self):
        for nome in split.SPLITS:
            for registro in split.registros_do_split(nome, self.registros):
                with self.subTest(split=nome, id=registro["id"]):
                    self.assertEqual(
                        oraculo.prever(registro),
                        registro["saida_esperada"],
                    )

    def test_manifesto_velho_e_detectado(self):
        alterado = copy.deepcopy(self.manifesto)
        alterado["pares"][0]["split"] = (
            "teste"
            if alterado["pares"][0]["split"] != "teste"
            else "treino"
        )
        problemas = split.validar_split(self.registros, alterado)
        codigos = {problema["codigo"] for problema in problemas}

        self.assertIn("split_atribuicao_divergente", codigos)

        desatualizado = copy.deepcopy(self.manifesto)
        desatualizado["sha256_dataset"] = "0" * 64
        self.assertIn(
            "split_desatualizado",
            {
                problema["codigo"]
                for problema in split.validar_split(
                    self.registros,
                    desatualizado,
                )
            },
        )

    def test_gravacao_atomica_e_idempotente(self):
        destino = BASE / "split.json"
        primeiro = split.gravar_split(self.registros, destino=destino)
        bytes_antes = destino.read_bytes()

        self.assertTrue(primeiro["alterado"])
        self.assertEqual(primeiro["total_pares"], 150)

        segundo = split.gravar_split(self.registros, destino=destino)
        self.assertFalse(segundo["alterado"])
        self.assertEqual(bytes_antes, destino.read_bytes())
        self.assertEqual(
            [item for item in BASE.iterdir() if item.suffix == ".tmp"],
            [],
        )

        carregado = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(carregado["total_pares"], 150)

    def test_gravacao_nao_toca_no_banco_real(self):
        antes = _db_intocado.capturar()
        split.gravar_split(self.registros, destino=BASE / "split.json")
        depois = _db_intocado.capturar()

        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )

    def test_cli_grava_split_sem_tocar_no_banco(self):
        destino = BASE / "split_cli.json"
        antes = _db_intocado.capturar()

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            codigo = split.main(["--saida", str(destino), "--resumo"])

        depois = _db_intocado.capturar()

        self.assertEqual(codigo, 0)
        self.assertTrue(destino.is_file())
        self.assertIn("total_pares", stdout.getvalue())
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )


if __name__ == "__main__":
    unittest.main()
