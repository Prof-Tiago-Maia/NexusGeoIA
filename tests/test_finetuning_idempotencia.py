"""Idempotência, atomicidade e prazos do pacote de fine-tuning.

Cobrem a geração repetida do dataset (mesmos bytes, alterado=False), o
rollback quando o manifesto não pôde ser gravado, ausência de arquivos
temporários, o digest em streaming, a auditoria repetível e o prazo por
registro do benchmark. Nenhum teste treina pesos, acessa rede ou toca no
banco real.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from finetuning import auditoria, benchmark, gerador
from tests import _db_intocado

BASE = Path(__file__).resolve().parent / "_tmp_finetuning_idempotente"

REGISTROS = [
    {
        "id": "wf-pt-001",
        "tarefa": "workflow_intent",
        "idioma": "pt",
        "metadados": {"familia": "teste", "par": "wf-001"},
        "entrada": "Pergunta: teste",
        "saida": "{}",
    },
    {
        "id": "wf-en-001",
        "tarefa": "workflow_intent",
        "idioma": "en",
        "metadados": {"familia": "teste", "par": "wf-001"},
        "entrada": "Question: test",
        "saida": "{}",
    },
]


class TestGravacaoIdempotente(unittest.TestCase):
    """Gravar duas vezes não reescreve nem deixa artefato parcial."""

    def setUp(self):
        shutil.rmtree(BASE, ignore_errors=True)
        BASE.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)
        self.dataset = BASE / "dataset.jsonl"
        self.manifesto = BASE / "dataset.manifest.json"

    def test_segunda_gravacao_e_no_op(self):
        primeira = gerador.gravar_dataset(
            REGISTROS,
            destino=self.dataset,
            manifesto=self.manifesto,
        )
        bytes_antes = self.dataset.read_bytes()
        manifesto_antes = self.manifesto.read_bytes()

        segunda = gerador.gravar_dataset(
            REGISTROS,
            destino=self.dataset,
            manifesto=self.manifesto,
        )

        self.assertTrue(primeira["alterado"])
        self.assertFalse(segunda["alterado"])
        self.assertEqual(
            primeira["sha256_registros"],
            segunda["sha256_registros"],
        )
        self.assertEqual(bytes_antes, self.dataset.read_bytes())
        self.assertEqual(manifesto_antes, self.manifesto.read_bytes())
        self.assertEqual(self.temporarios(), [])

    def test_falha_no_manifesto_restaura_o_dataset(self):
        gerador.gravar_dataset(
            REGISTROS,
            destino=self.dataset,
            manifesto=self.manifesto,
        )
        bytes_antes = self.dataset.read_bytes()

        manifesto_invalido = BASE / "manifesto_como_pasta"
        manifesto_invalido.mkdir()
        outros = [dict(REGISTROS[0], entrada="Pergunta: outra")]

        with self.assertRaises(OSError):
            gerador.gravar_dataset(
                outros,
                destino=self.dataset,
                manifesto=manifesto_invalido,
            )

        self.assertEqual(bytes_antes, self.dataset.read_bytes())
        self.assertEqual(self.temporarios(), [])

    def test_digest_em_streaming_confere_com_o_arquivo(self):
        gerador.gravar_dataset(
            REGISTROS,
            destino=self.dataset,
            manifesto=self.manifesto,
        )
        esperado = hashlib.sha256(
            gerador.serializar(REGISTROS).encode("utf-8")
        ).hexdigest()

        self.assertEqual(gerador.hash_registros(REGISTROS), esperado)
        self.assertEqual(
            hashlib.sha256(self.dataset.read_bytes()).hexdigest(),
            esperado,
        )

    def test_manifesto_aponta_para_os_bytes_gravados(self):
        gerador.gravar_dataset(
            REGISTROS,
            destino=self.dataset,
            manifesto=self.manifesto,
        )
        manifesto = json.loads(self.manifesto.read_text(encoding="utf-8"))

        self.assertEqual(manifesto["total"], len(REGISTROS))
        self.assertEqual(
            manifesto["tamanho_bytes"],
            self.dataset.stat().st_size,
        )
        self.assertEqual(
            manifesto["sha256_arquivo"],
            hashlib.sha256(self.dataset.read_bytes()).hexdigest(),
        )

    def temporarios(self):
        return [item.name for item in BASE.iterdir() if item.suffix == ".tmp"]


class TestAuditoriaIdempotente(unittest.TestCase):
    """Duas auditorias com os mesmos arquivos são iguais."""

    def test_auditoria_repetida_devolve_o_mesmo_relatorio(self):
        antes = _db_intocado.capturar()
        primeira = auditoria.executar_auditoria()
        segunda = auditoria.executar_auditoria()
        depois = _db_intocado.capturar()

        self.assertEqual(primeira, segunda)
        self.assertTrue(primeira["db_intocado"])
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )

    def test_relatorio_e_gravado_sem_temporario_residual(self):
        base = BASE / "relatorios"
        base.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)
        caminho = base / "auditoria.json"

        relatorio = auditoria.executar_auditoria()
        auditoria._escrever(relatorio, caminho)
        primeiro = caminho.read_bytes()
        auditoria._escrever(relatorio, caminho)

        self.assertEqual(primeiro, caminho.read_bytes())
        self.assertEqual(
            [item for item in base.iterdir() if item.suffix == ".tmp"],
            [],
        )


class _PreditorTravado:
    nome = "travado"

    def prever(self, registro):
        time.sleep(2.0)
        return "{}"


class TestBenchmarkComPrazo(unittest.TestCase):
    """Um preditor travado vira falha explícita dentro do prazo."""

    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()[:2]

    def setUp(self):
        shutil.rmtree(BASE, ignore_errors=True)
        BASE.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, BASE, ignore_errors=True)

    def test_prazo_por_registro_encerra_em_menos_de_3s(self):
        antes = _db_intocado.capturar()
        inicio = time.monotonic()

        relatorio = benchmark.executar_benchmark(
            self.registros,
            _PreditorTravado(),
            prazo_registro_s=0.1,
        )

        decorrido = time.monotonic() - inicio
        depois = _db_intocado.capturar()

        self.assertLess(decorrido, 3.0)
        self.assertEqual(relatorio["prazo_registro_s"], 0.1)
        self.assertEqual(
            relatorio["metricas"]["global"]["taxa_erro_execucao"],
            1.0,
        )
        self.assertIn(
            "TimeoutError",
            relatorio["metricas"]["falhas"][0]["erro_execucao"],
        )
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )

    def test_relatorio_json_atomico_e_idempotente(self):
        caminho = BASE / "benchmark.json"
        relatorio = benchmark.executar_benchmark(
            self.registros,
            benchmark.PreditorOraculo(),
        )

        benchmark._json_para_arquivo(relatorio, caminho)
        primeiro = caminho.read_bytes()
        benchmark._json_para_arquivo(relatorio, caminho)

        self.assertEqual(primeiro, caminho.read_bytes())
        self.assertEqual(
            [item for item in BASE.iterdir() if item.suffix == ".tmp"],
            [],
        )

    def test_falha_de_escrita_nao_deixa_relatorio_parcial(self):
        caminho = BASE / "benchmark_falha.json"
        relatorio = benchmark.executar_benchmark(
            self.registros,
            benchmark.PreditorOraculo(),
        )

        with mock.patch.object(
            benchmark.arquivo_seguro.os,
            "replace",
            side_effect=OSError("sem espaco"),
        ), self.assertRaises(OSError):
            benchmark._json_para_arquivo(relatorio, caminho)

        self.assertFalse(caminho.exists())
        self.assertEqual(
            [item for item in BASE.iterdir() if item.suffix == ".tmp"],
            [],
        )


if __name__ == "__main__":
    unittest.main()