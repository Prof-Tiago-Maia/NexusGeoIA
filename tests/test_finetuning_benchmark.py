"""Testes do harness de benchmark comportamental.

Usam dublês e fixtures locais; o caminho Ollama é exercitado com
urllib.request.urlopen mockado. Nenhum teste acessa rede, banco real ou
treina pesos.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from finetuning import benchmark, contrato, gerador, seguranca, split
from tests import _db_intocado


class PreditorCorreto:
    nome = "correto"

    def prever(self, registro):
        return registro["saida"]


class PreditorQuebrado:
    nome = "quebrado"

    def prever(self, registro):
        return "isto não é JSON"


class PreditorErro:
    nome = "erro"

    def prever(self, registro):
        raise RuntimeError("falha_injetada")


class PreditorLento(PreditorCorreto):
    nome = "lento"

    def prever(self, registro):
        time.sleep(0.01)
        return super().prever(registro)


class RespostaFalsa:
    def __init__(self, corpo, status=200):
        self.corpo = corpo
        self.status = status

    def read(self):
        return json.dumps(self.corpo).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()

    def test_oraculo_acerta_esquema_e_gabarito(self):
        relatorio = benchmark.executar_benchmark(
            self.registros[:12],
            benchmark.PreditorOraculo(),
        )
        global_ = relatorio["metricas"]["global"]

        self.assertEqual(global_["total"], 12)
        self.assertEqual(global_["acuracia"], 1.0)
        self.assertEqual(global_["acuracia_esquema"], 1.0)
        self.assertEqual(global_["taxa_falha_parsing"], 0.0)
        self.assertTrue(relatorio["db_intocado"])

    def test_preditor_quebrado_mede_falha_de_parsing(self):
        relatorio = benchmark.executar_benchmark(
            self.registros[:4],
            PreditorQuebrado(),
        )
        global_ = relatorio["metricas"]["global"]

        self.assertEqual(global_["acuracia"], 0.0)
        self.assertEqual(global_["taxa_falha_parsing"], 1.0)
        self.assertEqual(global_["falhas_parsing"], 4)
        self.assertEqual(relatorio["metricas"]["total_falhas"], 4)

    def test_preditor_com_erro_mede_erro_de_execucao(self):
        relatorio = benchmark.executar_benchmark(
            self.registros[:3],
            PreditorErro(),
        )
        global_ = relatorio["metricas"]["global"]

        self.assertEqual(global_["taxa_erro_execucao"], 1.0)
        self.assertEqual(global_["taxa_falha_parsing"], 0.0)
        self.assertEqual(global_["acuracia"], 0.0)
        erro = relatorio["metricas"]["falhas"][0]["erro_execucao"]
        self.assertIsNotNone(erro)
        self.assertIn("falha_injetada", erro)

    def test_latencia_e_medida_em_milissegundos(self):
        relatorio = benchmark.executar_benchmark(
            self.registros[:2],
            PreditorLento(),
        )
        latencia = relatorio["metricas"]["global"]["latencia_ms"]

        self.assertGreaterEqual(latencia["media"], 8.0)
        self.assertGreaterEqual(latencia["p95"], 8.0)

    def test_extrai_json_de_cerca_e_de_prosa(self):
        cerca = chr(96) * 3
        esperado = {"workflow": "sondagem", "intencao": "RIGEO_ONLY"}

        self.assertEqual(
            benchmark.extrair_json(
                cerca + "json" + chr(10) + json.dumps(esperado) + chr(10) + cerca
            ),
            esperado,
        )
        self.assertEqual(
            benchmark.extrair_json(
                "Resposta: " + json.dumps(esperado) + " fim"
            ),
            esperado,
        )

    def test_comparacao_numerica_tolera_arredondamento(self):
        esperado = {
            "furo": "FQ-01",
            "de_m": 0.0,
            "ate_m": 2.5,
            "espessura_m": 2.5,
            "unidade": "m",
            "litologia": "Areia",
            "situacao": "valido",
            "motivo": "",
        }
        obtido = dict(esperado, ate_m=2.5000000001)

        self.assertTrue(
            benchmark._comparar(contrato.TAREFA_SONDAGEM, esperado, obtido)
        )

    def test_percentil_linear(self):
        self.assertEqual(benchmark._percentil([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(benchmark._percentil([10], 95), 10)
        self.assertIsNone(benchmark._percentil([], 95))

    def test_metrica_por_tarefa_e_idioma(self):
        relatorio = benchmark.executar_benchmark(
            self.registros,
            PreditorCorreto(),
        )
        metricas = relatorio["metricas"]

        for tarefa in contrato.TAREFAS:
            self.assertIn(tarefa, metricas["por_tarefa"])
            self.assertEqual(metricas["por_tarefa"][tarefa]["acuracia"], 1.0)

        self.assertEqual(set(metricas["por_idioma"]), set(contrato.IDIOMAS))

    def test_filtros_por_tarefa_e_limite(self):
        registros = [
            registro
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_WORKFLOW
        ]
        relatorio = benchmark.executar_benchmark(
            registros,
            PreditorCorreto(),
            tarefas=[contrato.TAREFA_WORKFLOW],
            idiomas=["pt"],
            limite=5,
        )

        self.assertEqual(relatorio["dataset"]["avaliados"], 5)
        self.assertEqual(relatorio["filtros"]["idiomas"], ["pt"])
        self.assertEqual(
            set(relatorio["metricas"]["por_tarefa"]),
            {contrato.TAREFA_WORKFLOW},
        )

    def test_preditor_ollama_com_urlopen_mockado(self):
        registro = next(
            registro
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_WORKFLOW
        )
        conteudo = json.dumps(registro["saida_esperada"])
        chamadas = []

        def urlopen_falso(requisicao, timeout=None):
            url = getattr(requisicao, "full_url", str(requisicao))
            chamadas.append(url)

            if url.endswith("/api/tags"):
                return RespostaFalsa({}, 200)

            return RespostaFalsa({"message": {"content": conteudo}})

        with mock.patch(
            "finetuning.benchmark.urllib.request.urlopen",
            side_effect=urlopen_falso,
        ):
            preditor = benchmark.PreditorOllama(
                modelo="modelo-teste",
                host="http://127.0.0.1:11434",
                timeout=5,
            )
            self.assertTrue(preditor.disponivel())
            resposta = preditor.prever(registro)

        self.assertEqual(json.loads(resposta), registro["saida_esperada"])
        self.assertTrue(chamadas)
        self.assertTrue(chamadas[-1].endswith("/api/chat"))

    def test_preditor_ollama_indisponivel(self):
        with mock.patch(
            "finetuning.benchmark.urllib.request.urlopen",
            side_effect=urllib.error.URLError("recusado"),
        ):
            preditor = benchmark.PreditorOllama(host="http://127.0.0.1:1")

        self.assertFalse(preditor.disponivel())

    def test_cli_grava_relatorio_sem_tocar_no_banco(self):
        antes = _db_intocado.capturar()
        pasta = Path("build") / f"_tmp_finetuning_bench_{os.getpid()}"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        saida = pasta / "benchmark.json"
        markdown = pasta / "benchmark.md"

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            codigo = benchmark.main(
                [
                    "--limite",
                    "4",
                    "--json-saida",
                    str(saida),
                    "--relatorio-md",
                    str(markdown),
                ]
            )

        self.assertEqual(codigo, 0)
        self.assertIn("DB_INTOCADO=True", stdout.getvalue())
        relatorio = json.loads(saida.read_text(encoding="utf-8"))
        self.assertEqual(relatorio["dataset"]["avaliados"], 4)
        self.assertTrue(markdown.is_file())
        self.assertIn(
            "Benchmark comportamental",
            markdown.read_text(encoding="utf-8"),
        )

        depois = _db_intocado.capturar()
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )

    def test_auditoria_estatica_aprova_o_pacote(self):
        relatorio = seguranca.auditar_pacote(self.registros)

        self.assertTrue(relatorio["ok"])
        self.assertEqual(relatorio["achados_codigo"], [])
        self.assertEqual(relatorio["problemas_dataset"], [])

    def test_guarda_do_banco_serializavel(self):
        antes = seguranca.capturar_banco()
        depois = seguranca.capturar_banco()
        comparacao = seguranca.comparar_banco(antes, depois)

        self.assertTrue(comparacao["DB_INTOCADO"])
        self.assertIn("principal", comparacao["antes"])

    def test_diagnostico_distingue_tipos_de_falha(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
        )

        class PreditorEstatico:
            nome = "estatico"

            def __init__(self, texto):
                self.texto = texto

            def prever(self, _registro):
                return self.texto

        class PreditorTravado:
            nome = "travado"

            def prever(self, _registro):
                time.sleep(0.2)

        casos = [
            (PreditorQuebrado(), "json_invalido"),
            (
                PreditorEstatico(
                    '{"workflow": "inexistente", "intencao": "INVALIDA"}'
                ),
                "esquema",
            ),
            (
                PreditorEstatico(
                    '{"workflow": "consulta_direta", "intencao": "INVALIDA"}'
                ),
                "esquema",
            ),
        ]

        for preditor, esperado in casos:
            avaliacao = benchmark.avaliar_registro(registro, preditor)
            self.assertEqual(avaliacao["tipo_falha"], esperado)
            self.assertIsNotNone(avaliacao["diagnostico"])

        # Esquema válido, mas com valor diferente do gabarito.
        alternativa = dict(registro["saida_esperada"])

        if alternativa["workflow"] == "consulta_direta":
            alternativa["workflow"] = "sondagem"
        else:
            alternativa["workflow"] = "consulta_direta"

        avaliacao = benchmark.avaliar_registro(
            registro,
            PreditorEstatico(json.dumps(alternativa)),
        )
        self.assertEqual(avaliacao["tipo_falha"], "divergencia_semantica")

        inicio = time.monotonic()
        avaliacao = benchmark.avaliar_registro(
            registro,
            PreditorTravado(),
            prazo_registro_s=0.01,
        )
        self.assertLess(time.monotonic() - inicio, 1.0)
        self.assertEqual(avaliacao["tipo_falha"], "timeout")
        self.assertIn("TimeoutError", avaliacao["erro_execucao"])

    def test_dataset_explicito_inexistente_nao_gera_arquivo(self):
        pasta = Path("build") / f"_tmp_finetuning_dataset_{os.getpid()}"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        destino = pasta / "inexistente.jsonl"

        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            codigo = benchmark.main(["--dataset", str(destino)])

        self.assertEqual(codigo, 2)
        self.assertFalse(destino.exists())
        self.assertIn("Dataset não encontrado", stderr.getvalue())

    def test_prompt_ollama_inclui_codigos_e_determinismo(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_GOVERNANCA
        )
        capturado = {}

        def urlopen_falso(requisicao, timeout=None):
            capturado["carga"] = json.loads(
                requisicao.data.decode("utf-8")
            )
            return RespostaFalsa({"message": {"content": "{}"}})

        with mock.patch(
            "finetuning.benchmark.urllib.request.urlopen",
            side_effect=urlopen_falso,
        ):
            preditor = benchmark.PreditorOllama(
                modelo="qwen3:4b",
                host="http://127.0.0.1:11434",
                seed=7,
            )
            preditor.prever(registro)

        carga = capturado["carga"]
        prompt = carga["messages"][1]["content"]

        self.assertIn("OBSERVED", prompt)
        self.assertIn("INFERRED", prompt)
        self.assertIn("PASS", prompt)
        self.assertIn("HOLD", prompt)
        self.assertIn("FAIL", prompt)
        self.assertIn("contrato_valido", prompt)
        self.assertIn("ordem das claims", prompt)
        self.assertEqual(carga["options"]["temperature"], 0)
        self.assertEqual(carga["options"]["seed"], 7)
        self.assertIs(carga["think"], False)

    def test_prompt_workflow_inclui_definicoes_e_regra_sem_documentos(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
            and item["idioma"] == "pt"
            and "Documentos locais: não" in item["entrada"]
        )
        prompt = benchmark._prompt_usuario(registro)

        for termo in (
            "consulta_direta",
            "triagem_area",
            "hidrogeologia",
            "sondagem",
            "LOCAL_ONLY",
            "RIGEO_ONLY",
            "HIBRIDO",
            "ANA_ONLY",
        ):
            self.assertIn(termo, prompt)

        self.assertIn("Sem documentos locais (docs=não)", prompt)
        self.assertIn("nunca escolha LOCAL_ONLY", prompt)
        self.assertIn("não escolha HIBRIDO por precaução", prompt)
        self.assertIn("RESTRIÇÃO ATIVA (Documentos locais: não)", prompt)

    def test_prompt_workflow_com_documentos_permite_local_only(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
            and item["idioma"] == "pt"
            and "Documentos locais: sim" in item["entrada"]
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("RESTRIÇÃO ATIVA (Documentos locais: sim)", prompt)
        self.assertNotIn("Documentos locais: não): neste item", prompt)
        self.assertIn("não escolha HIBRIDO por precaução", prompt)

    def test_prompt_workflow_em_ingles_trava_sem_documentos(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
            and item["idioma"] == "en"
            and "Local documents: no" in item["entrada"]
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("ACTIVE CONSTRAINT (Local documents: no)", prompt)
        self.assertIn("never choose LOCAL_ONLY or HIBRIDO", prompt)
        self.assertIn("do not choose HIBRIDO by precaution", prompt)

    def test_prompt_sondagem_exige_conversao_e_separa_erro_de_contrato(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_SONDAGEM
            and item["idioma"] == "pt"
            and "150" in item["entrada"]
            and "cm" in item["entrada"]
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("150 cm -> 1.5", prompt)
        self.assertIn("dividindo por 100", prompt)
        self.assertIn("espessura_m = ate_m - de_m", prompt)
        self.assertIn("erro_contrato apenas quando a tabela", prompt)
        self.assertIn("LINHA INVÁLIDA", prompt)
        self.assertIn("ponto e vírgula", prompt)
        self.assertIn("furo_ausente, de_ausente, de_invalido", prompt)
        self.assertIn("nunca omita uma chave", prompt)
        self.assertIn("use sem_linhas", prompt)

    def test_prompt_governanca_cobra_motivo_e_veredito_conservador(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_GOVERNANCA
            and item["idioma"] == "pt"
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("CHAVE EXATA", prompt)
        self.assertIn("nunca mot", prompt)
        self.assertIn("PASS só quando", prompt)
        self.assertIn("HOLD para falta de evidência", prompt)
        self.assertIn("Falha de fonte nunca vira FAIL", prompt)
        self.assertIn("veredito_invalido", prompt)
        self.assertIn('classificacoes: []', prompt)
        self.assertIn("CHECKLIST OBRIGATÓRIO", prompt)
        self.assertIn("MAPA DE MOTIVOS", prompt)

    def test_prompt_workflow_exige_um_codigo_e_evita_hibrido_por_precaucao(
        self,
    ):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
            and item["idioma"] == "pt"
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("exatamente um código em workflow", prompt)
        self.assertIn("nunca junte códigos com |", prompt)
        self.assertIn("sondagem > hidrogeologia", prompt)
        self.assertIn("HIBRIDO exige referência explícita", prompt)
        self.assertIn("não é HIBRIDO", prompt)

    def test_prompt_em_ingles_recebe_as_mesmas_regras(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_WORKFLOW
            and item["idioma"] == "en"
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertIn("DECISION CRITERIA (mandatory)", prompt)
        self.assertIn("never join codes with |", prompt)
        self.assertIn("first group with a recognised term wins", prompt)
        self.assertIn("is not HIBRIDO", prompt)

    def test_outras_tarefas_nao_recebem_restricao_de_documentos(self):
        registro = next(
            item
            for item in self.registros
            if item["tarefa"] == contrato.TAREFA_GOVERNANCA
        )
        prompt = benchmark._prompt_usuario(registro)

        self.assertNotIn("RESTRIÇÃO ATIVA", prompt)
        self.assertNotIn("ACTIVE CONSTRAINT", prompt)

    def test_banco_real_respeita_nexusgeo_db_path(self):
        alvo = Path("build") / "banco_diagnostico.db"

        with mock.patch.dict(
            os.environ,
            {"NEXUSGEO_DB_PATH": str(alvo)},
            clear=False,
        ):
            caminho, origem = seguranca._resolver_banco_real()

        self.assertEqual(origem, "NEXUSGEO_DB_PATH")
        self.assertEqual(caminho, alvo.expanduser().resolve())

    def test_comparar_banco_aponta_arquivo_e_sha256_alterados(self):
        pasta = Path("build") / f"_tmp_finetuning_guarda_{os.getpid()}"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        banco = pasta / "teste.db"
        banco.write_bytes(b"conteudo-a")

        antes = seguranca.capturar_banco(banco)
        banco.write_bytes(b"conteudo-b")
        depois = seguranca.capturar_banco(banco)
        comparacao = seguranca.comparar_banco(antes, depois)

        self.assertFalse(comparacao["DB_INTOCADO"])
        self.assertEqual(
            comparacao["diagnostico"]["veredito"],
            "ALTERADO",
        )
        self.assertIn("Banco alterado", comparacao["diagnostico"]["mensagem"])
        self.assertTrue(
            any(
                item["campo"] == "sha256"
                for item in comparacao["divergencias"]
            )
        )


    def _manifesto_temporario(self, alteracao=None) -> Path:
        """Copia o manifesto real em build/ para simular adulteração."""

        pasta = Path("build") / f"_tmp_finetuning_split_{os.getpid()}"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        manifesto = json.loads(split.ARQUIVO_SPLIT.read_text(encoding="utf-8"))

        if alteracao is not None:
            alteracao(manifesto)

        destino = pasta / "split.json"
        destino.write_text(json.dumps(manifesto), encoding="utf-8")
        return destino

    def test_split_teste_avalia_50_registros_com_manifesto_validado(self):
        relatorio = benchmark.executar_benchmark(
            self.registros,
            PreditorCorreto(),
            split_nome="teste",
        )
        dataset = relatorio["dataset"]
        info_split = dataset["split"]

        self.assertEqual(dataset["total"], len(self.registros))
        self.assertEqual(dataset["avaliados"], 50)
        self.assertEqual(info_split["nome"], "teste")
        self.assertEqual(info_split["pares"], 25)
        self.assertEqual(info_split["registros"], 50)
        self.assertEqual(
            info_split["sha256_dataset"],
            gerador.hash_registros(self.registros),
        )
        self.assertEqual(relatorio["filtros"]["split"], "teste")
        self.assertTrue(relatorio["db_intocado"])
        self.assertEqual(
            {
                tarefa: dados["total"]
                for tarefa, dados in relatorio["metricas"]["por_tarefa"].items()
            },
            {
                contrato.TAREFA_GOVERNANCA: 14,
                contrato.TAREFA_SONDAGEM: 18,
                contrato.TAREFA_WORKFLOW: 18,
            },
        )
        self.assertEqual(
            {
                idioma: dados["total"]
                for idioma, dados in relatorio["metricas"]["por_idioma"].items()
            },
            {"en": 25, "pt": 25},
        )

    def test_split_desconhecido_e_recusado(self):
        with self.assertRaisesRegex(ValueError, "split_desconhecido"):
            benchmark.selecionar_split(self.registros, "inventado")

    def test_split_com_hash_adulterado_e_recusado(self):
        def alterar(manifesto):
            manifesto["sha256_dataset"] = "0" * 64

        destino = self._manifesto_temporario(alterar)

        with self.assertRaisesRegex(ValueError, "split_desatualizado"):
            benchmark.selecionar_split(
                self.registros,
                "teste",
                destino,
            )

    def test_cli_split_teste_grava_relatorio(self):
        pasta = Path("build") / f"_tmp_finetuning_bench_split_{os.getpid()}"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        saida = pasta / "benchmark_split.json"
        markdown = pasta / "benchmark_split.md"

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            codigo = benchmark.main(
                [
                    "--split",
                    "teste",
                    "--limite",
                    "6",
                    "--json-saida",
                    str(saida),
                    "--relatorio-md",
                    str(markdown),
                ]
            )

        self.assertEqual(codigo, 0)
        self.assertIn("DB_INTOCADO=True", stdout.getvalue())
        relatorio = json.loads(saida.read_text(encoding="utf-8"))
        self.assertEqual(relatorio["dataset"]["avaliados"], 6)
        self.assertEqual(relatorio["dataset"]["total"], 300)
        self.assertEqual(relatorio["dataset"]["split"]["nome"], "teste")
        self.assertEqual(relatorio["dataset"]["split"]["registros"], 50)
        self.assertEqual(relatorio["filtros"]["split"], "teste")
        self.assertIn(
            "Split: teste",
            markdown.read_text(encoding="utf-8"),
        )

    def test_cli_recusa_split_com_manifesto_invalido(self):
        def alterar(manifesto):
            manifesto["sha256_dataset"] = "0" * 64

        destino = self._manifesto_temporario(alterar)

        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            codigo = benchmark.main(
                [
                    "--split",
                    "teste",
                    "--split-manifesto",
                    str(destino),
                    "--limite",
                    "1",
                ]
            )

        self.assertEqual(codigo, 2)
        self.assertIn("Split inválido", stderr.getvalue())

if __name__ == "__main__":
    unittest.main()
