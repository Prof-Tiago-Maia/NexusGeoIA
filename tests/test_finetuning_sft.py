"""Testes da exportação SFT e do plano de treino LoRA (Caminho 2).

Cobrem contagens exatas (206 treino / 44 validação), interseção
estritamente vazia com o split teste por id e por par, reutilização
fiel dos prompts do benchmark, validade do JSON da resposta do
assistente, manifesto/hashes, idempotência, geração do Modelfile, o
dry-run do treino com seleção automática de precisão e a compatibilidade
das assinaturas do TRL/transformers (``eval_strategy`` x
``evaluation_strategy``, ``processing_class`` x ``tokenizer`` e
``dtype`` x ``torch_dtype``), exercitada contra classes stub.

Nenhum teste baixa pesos, treina, chama Ollama ou abre o banco real.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from finetuning import (
    benchmark,
    contrato,
    exportar_sft,
    gerador,
    gerar_modelfile,
    seguranca,
    split,
    treinar_lora,
)
from tests import _db_intocado

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(__file__).resolve().parent / "_tmp_finetuning_sft"
LINHAS_TREINO = 206
LINHAS_VALIDACAO = 44
LINHAS_TESTE = 50
PARES_TESTE = 25


class TestExportacaoSFT(unittest.TestCase):
    """Exportação determinística dos splits treino/validação."""

    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()
        cls.manifesto_split = split.carregar_split()
        cls.por_id = {registro["id"]: registro for registro in cls.registros}
        cls.pasta = BASE / "exportacao"
        shutil.rmtree(cls.pasta, ignore_errors=True)
        cls.pasta.mkdir(parents=True)
        cls.addClassCleanup(
            shutil.rmtree,
            cls.pasta,
            ignore_errors=True,
        )
        pasta = cls.pasta
        cls.treino = pasta / "sft_v2_treino.jsonl"
        cls.validacao = pasta / "sft_v2_validacao.jsonl"
        cls.manifesto = pasta / "sft_v2.manifest.json"
        cls.resultado = exportar_sft.exportar(
            cls.registros,
            destino_treino=cls.treino,
            destino_validacao=cls.validacao,
            destino_manifesto=cls.manifesto,
        )
        cls.exemplos = {
            nome: cls._ler(caminho)
            for nome, caminho in (
                ("treino", cls.treino),
                ("validacao", cls.validacao),
            )
        }
        cls.manifesto_sft = json.loads(
            cls.manifesto.read_text(encoding="utf-8")
        )

    @staticmethod
    def _ler(caminho):
        return [
            json.loads(linha)
            for linha in Path(caminho).read_text(
                encoding="utf-8"
            ).splitlines()
            if linha.strip()
        ]

    def test_contagens_exatas_de_treino_e_validacao(self):
        self.assertEqual(len(self.exemplos["treino"]), LINHAS_TREINO)
        self.assertEqual(len(self.exemplos["validacao"]), LINHAS_VALIDACAO)

        for nome, exemplos in self.exemplos.items():
            ids = [exemplo["id"] for exemplo in exemplos]

            with self.subTest(split=nome):
                self.assertEqual(len(ids), len(set(ids)))

            for exemplo in exemplos:
                papeis = [
                    mensagem["role"]
                    for mensagem in exemplo["messages"]
                ]
                self.assertEqual(
                    papeis,
                    ["system", "user", "assistant"],
                    exemplo["id"],
                )
                self.assertTrue(
                    all(
                        mensagem["content"].strip()
                        for mensagem in exemplo["messages"]
                    )
                )

    def test_split_de_cada_exemplo_confere_com_o_manifesto(self):
        atribuicao = split.atribuir_splits(self.registros)

        for nome, exemplos in self.exemplos.items():
            for exemplo in exemplos:
                self.assertEqual(
                    atribuicao[exemplo["par"]],
                    nome,
                    exemplo["id"],
                )

    def test_intersecao_com_teste_e_vazia_por_id_e_por_par(self):
        itens_teste = [
            item
            for item in self.manifesto_split["pares"]
            if item["split"] == "teste"
        ]
        ids_teste = {
            identificador
            for item in itens_teste
            for identificador in item["ids"]
        }
        pares_teste = {item["par"] for item in itens_teste}

        self.assertEqual(len(ids_teste), LINHAS_TESTE)
        self.assertEqual(len(pares_teste), PARES_TESTE)

        for nome, exemplos in self.exemplos.items():
            ids = {exemplo["id"] for exemplo in exemplos}
            pares = {exemplo["par"] for exemplo in exemplos}

            with self.subTest(split=nome):
                self.assertEqual(ids & ids_teste, set())
                self.assertEqual(pares & pares_teste, set())

        anti = self.manifesto_sft["anti_vazamento"]
        self.assertTrue(anti["ok"])
        self.assertEqual(anti["intersecao_ids"], 0)
        self.assertEqual(anti["intersecao_pares"], 0)
        self.assertEqual(anti["teste_registros"], LINHAS_TESTE)
        self.assertEqual(anti["teste_pares"], PARES_TESTE)
        self.assertEqual(anti["ids_intersecao"]["treino"], [])
        self.assertEqual(anti["ids_intersecao"]["validacao"], [])
        self.assertEqual(anti["pares_intersecao"]["treino"], [])
        self.assertEqual(anti["pares_intersecao"]["validacao"], [])

    def test_prompt_reutiliza_exatamente_o_benchmark(self):
        for exemplos in self.exemplos.values():
            for exemplo in exemplos:
                registro = self.por_id[exemplo["id"]]
                idioma = (
                    "en" if registro["idioma"] == "en" else "pt"
                )
                sistema, usuario, assistente = exemplo["messages"]

                with self.subTest(id=exemplo["id"]):
                    self.assertEqual(
                        sistema["content"],
                        benchmark._prompt_sistema(idioma),
                    )
                    self.assertEqual(
                        usuario["content"],
                        benchmark._prompt_usuario(registro),
                    )

                    resposta = json.loads(assistente["content"])
                    self.assertIsInstance(resposta, dict)
                    self.assertEqual(
                        resposta,
                        registro["saida_esperada"],
                    )
                    self.assertEqual(
                        assistente["content"],
                        contrato.json_compacto(
                            registro["saida_esperada"]
                        ),
                    )
                    self.assertEqual(
                        contrato.validar_saida(
                            registro["tarefa"],
                            resposta,
                        ),
                        [],
                    )

    def test_manifesto_registra_hashes_e_contagens(self):
        for nome, caminho in (
            ("treino", self.treino),
            ("validacao", self.validacao),
        ):
            dados = caminho.read_bytes()
            declarado = self.manifesto_sft["arquivos"][nome]

            with self.subTest(split=nome):
                self.assertEqual(
                    declarado["sha256"],
                    hashlib.sha256(dados).hexdigest(),
                )
                self.assertEqual(declarado["bytes"], len(dados))
                self.assertEqual(
                    declarado["linhas"],
                    len(dados.splitlines()),
                )
                self.assertEqual(
                    self.manifesto_sft["por_split"][nome]["registros"],
                    len(self.exemplos[nome]),
                )
                self.assertEqual(
                    self.manifesto_sft["por_split"][nome]["por_tarefa"],
                    self.manifesto_split["por_split"][nome][
                        "por_tarefa"
                    ],
                )
                self.assertEqual(
                    self.manifesto_sft["por_split"][nome]["por_idioma"],
                    self.manifesto_split["por_split"][nome][
                        "por_idioma"
                    ],
                )

        self.assertEqual(
            self.manifesto_sft["dataset"]["sha256"],
            gerador.hash_registros(self.registros),
        )
        self.assertEqual(
            self.manifesto_sft["split"]["sha256_dataset"],
            self.manifesto_split["sha256_dataset"],
        )
        self.assertEqual(
            self.manifesto_sft["invariantes"]["registros_exportados"],
            LINHAS_TREINO + LINHAS_VALIDACAO,
        )
        self.assertTrue(
            self.manifesto_sft["invariantes"]["sem_vazamento_teste"]
        )

    def test_reexportacao_e_idempotente_e_atomica(self):
        resultado = exportar_sft.exportar(
            self.registros,
            destino_treino=self.treino,
            destino_validacao=self.validacao,
            destino_manifesto=self.manifesto,
        )

        for nome in ("treino", "validacao", "manifesto"):
            self.assertFalse(resultado[nome]["alterado"], nome)

        self.assertEqual(
            resultado["treino"]["sha256"],
            self.resultado["treino"]["sha256"],
        )
        self.assertEqual(
            resultado["validacao"]["sha256"],
            self.resultado["validacao"]["sha256"],
        )
        self.assertEqual(
            sorted(
                caminho.name
                for caminho in self.pasta.glob("*.tmp")
            ),
            [],
        )

    def test_split_adulterado_e_recusado_antes_de_gravar(self):
        pasta = self.pasta / "adulterado"
        pasta.mkdir()
        manifesto = json.loads(
            split.ARQUIVO_SPLIT.read_text(encoding="utf-8")
        )
        manifesto["sha256_dataset"] = "0" * 64
        caminho = pasta / "split.json"
        caminho.write_text(
            json.dumps(manifesto, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "split_invalido"):
            exportar_sft.exportar(
                self.registros,
                destino_treino=pasta / "treino.jsonl",
                destino_validacao=pasta / "validacao.jsonl",
                destino_manifesto=pasta / "manifesto.json",
                caminho_split=caminho,
            )

        self.assertFalse((pasta / "treino.jsonl").exists())
        self.assertFalse((pasta / "validacao.jsonl").exists())

    def test_auditoria_estatica_aceita_os_novos_modulos(self):
        achados = seguranca.auditar_codigo(
            [
                Path(exportar_sft.__file__),
                Path(treinar_lora.__file__),
                Path(gerar_modelfile.__file__),
            ]
        )

        self.assertEqual(achados, [])


class TestTreinoLora(unittest.TestCase):
    """Seleção de precisão, ambiente e dry-run sem bibliotecas."""

    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()
        cls.pasta = BASE / "lora"
        shutil.rmtree(cls.pasta, ignore_errors=True)
        cls.pasta.mkdir(parents=True)
        cls.addClassCleanup(
            shutil.rmtree,
            cls.pasta,
            ignore_errors=True,
        )
        pasta = cls.pasta
        cls.treino = pasta / "sft_v2_treino.jsonl"
        cls.validacao = pasta / "sft_v2_validacao.jsonl"
        cls.manifesto = pasta / "sft_v2.manifest.json"
        exportar_sft.exportar(
            cls.registros,
            destino_treino=cls.treino,
            destino_validacao=cls.validacao,
            destino_manifesto=cls.manifesto,
        )

    def test_selecao_automatica_de_precisao(self):
        casos = [
            ("auto", True, True, "bf16"),
            ("auto", True, False, "fp16"),
            ("auto", False, False, "fp32"),
            ("fp32", True, True, "fp32"),
            ("bf16", True, False, "fp16"),
            ("bf16", False, False, "fp32"),
            ("fp16", True, True, "fp16"),
        ]

        for pedida, cuda, bf16, esperada in casos:
            with self.subTest(
                precisao=pedida,
                cuda=cuda,
                bf16=bf16,
            ):
                efetiva, motivo = treinar_lora.selecionar_precisao(
                    pedida,
                    cuda_disponivel=cuda,
                    bf16_suportado=bf16,
                )
                self.assertEqual(efetiva, esperada)
                self.assertTrue(motivo)

        with self.assertRaises(ValueError):
            treinar_lora.selecionar_precisao("fp8")

    def test_ambiente_detectado_e_coerente(self):
        ambiente = treinar_lora.detectar_ambiente()

        self.assertIn(ambiente["dispositivo"], {"cpu", "cuda"})
        self.assertIn(
            ambiente["precisao"]["efetiva"],
            set(treinar_lora.PRECISOES) - {"auto"},
        )
        self.assertEqual(
            set(ambiente["bibliotecas"]),
            set(treinar_lora.BIBLIOTECAS),
        )

        if not ambiente["cuda_disponivel"]:
            self.assertEqual(ambiente["dispositivo"], "cpu")
            self.assertEqual(ambiente["precisao"]["efetiva"], "fp32")

    def test_dry_run_cli_executa_sem_bibliotecas_de_treino(self):
        pasta = self.pasta
        saida_dir = pasta / "adaptador"
        modelfile = pasta / "Modelfile.teste"
        comando = [
            sys.executable,
            "-m",
            "finetuning.treinar_lora",
            "--dry-run",
            "--treino",
            str(self.treino),
            "--validacao",
            str(self.validacao),
            "--manifesto",
            str(self.manifesto),
            "--saida-dir",
            str(saida_dir),
            "--modelfile",
            str(modelfile),
            "--gerar-modelfile",
        ]
        ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
        processo = subprocess.run(
            comando,
            check=False,
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=ambiente,
            timeout=120,
        )

        self.assertEqual(processo.returncode, 0, processo.stderr)
        plano = json.loads(processo.stdout)
        self.assertTrue(plano["dry_run"])
        self.assertEqual(plano["seed"], 42)
        self.assertEqual(
            plano["dataset"]["treino"]["linhas"],
            LINHAS_TREINO,
        )
        self.assertEqual(
            plano["dataset"]["validacao"]["linhas"],
            LINHAS_VALIDACAO,
        )
        self.assertEqual(plano["lora"]["r"], 8)
        self.assertEqual(plano["lora"]["lora_alpha"], 16)
        self.assertTrue(
            plano["treinamento"]["gradient_checkpointing"]
        )
        self.assertEqual(
            plano["treinamento"]["passos_por_epoca"],
            math.ceil(LINHAS_TREINO / 8),
        )
        self.assertEqual(
            plano["treinamento"]["passos_totais"],
            math.ceil(LINHAS_TREINO / 8) * 3,
        )
        self.assertTrue(plano["dataset"]["manifesto"]["anti_vazamento_ok"])
        self.assertIn("datasets", plano["bibliotecas"])
        self.assertEqual(
            plano["dataset"]["conversao"],
            "datasets.Dataset.from_list",
        )
        self.assertIsInstance(plano["pronto_para_treinar"], bool)
        self.assertIn(
            plano["precisao"]["efetiva"],
            {"bf16", "fp16", "fp32"},
        )
        self.assertFalse(saida_dir.exists())
        self.assertFalse(modelfile.exists())

    def test_validar_sft_recusa_arquivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            treinar_lora.validar_sft(
                self.pasta / "nao_existe.jsonl"
            )


class _DatasetFalso:
    """Dublê mínimo de ``datasets.Dataset`` (sem importar a biblioteca)."""

    def __init__(self, registros):
        self.registros = list(registros)

    @classmethod
    def from_list(cls, registros):
        return cls(registros)


class TestConversaoDataset(unittest.TestCase):
    """Conversão para ``datasets.Dataset`` exercitada com dublê.

    O ``trl >= 1.0`` recusa listas em ``train_dataset``/``eval_dataset``
    (``'train_dataset' must be a 'Dataset' or 'IterableDataset', got
    'list'``). A conversão usa ``Dataset.from_list``, que preserva a
    coluna ``messages``; aqui a fábrica é injetada para não depender de
    ``datasets`` instalado no `.venv` principal.
    """

    @classmethod
    def setUpClass(cls):
        if not treinar_lora.ARQUIVO_TREINO_PADRAO.is_file():
            raise unittest.SkipTest("JSONL de treino padrão ausente")

        cls.exemplos = treinar_lora.carregar_exemplos(
            treinar_lora.ARQUIVO_TREINO_PADRAO
        )

    def test_datasets_entra_nas_bibliotecas_obrigatorias(self):
        self.assertIn("datasets", treinar_lora.BIBLIOTECAS_OBRIGATORIAS)
        self.assertIn("datasets", treinar_lora.BIBLIOTECAS)
        self.assertIn("datasets", treinar_lora.status_bibliotecas())

    def test_from_list_recebe_os_registros_messages_intactos(self):
        dataset = treinar_lora.converter_para_dataset(
            self.exemplos,
            _DatasetFalso,
        )

        self.assertIsInstance(dataset, _DatasetFalso)
        self.assertEqual(len(dataset.registros), len(self.exemplos))
        self.assertEqual(dataset.registros, self.exemplos)

        for registro in dataset.registros:
            self.assertEqual(set(registro), {"messages"})
            self.assertEqual(
                tuple(
                    mensagem["role"]
                    for mensagem in registro["messages"]
                ),
                treinar_lora.PAPEIS,
            )

    def test_conversao_nao_altera_a_lista_de_origem(self):
        exemplos = treinar_lora.carregar_exemplos(
            treinar_lora.ARQUIVO_VALIDACAO_PADRAO
        )
        copia = json.loads(json.dumps(exemplos))

        treinar_lora.converter_para_dataset(exemplos, _DatasetFalso)

        self.assertEqual(exemplos, copia)

    def test_recusa_entradas_invalidas(self):
        mensagens_validas = self.exemplos[0]["messages"]
        casos = (
            ({"messages": mensagens_validas}, TypeError),
            (None, TypeError),
            ((), ValueError),
            ([], ValueError),
            (["nao_e_objeto"], TypeError),
            ([{"messages": []}], ValueError),
            ([{"messages": mensagens_validas[:2]}], ValueError),
        )

        for entrada, erro in casos:
            with self.subTest(entrada=repr(entrada)[:60]):
                with self.assertRaises(erro):
                    treinar_lora.converter_para_dataset(
                        entrada,
                        _DatasetFalso,
                    )

    def test_conversao_real_quando_datasets_esta_instalado(self):
        if importlib.util.find_spec("datasets") is None:
            self.skipTest("datasets não instalado no .venv principal")

        dataset = treinar_lora.converter_para_dataset(self.exemplos)

        self.assertEqual(len(dataset), len(self.exemplos))
        self.assertIn("messages", dataset.column_names)
        self.assertEqual(
            dataset[0]["messages"],
            self.exemplos[0]["messages"],
        )


class _SFTConfigNovo:
    """Assinatura mínima do ``trl >= 1.18``/``transformers >= 5.0``."""

    def __init__(
        self,
        output_dir=None,
        num_train_epochs=None,
        eval_strategy=None,
        dtype=None,
        bf16=None,
        fp16=None,
        seed=None,
        max_length=None,
        packing=None,
    ):
        self.recebidos = {
            "output_dir": output_dir,
            "num_train_epochs": num_train_epochs,
            "eval_strategy": eval_strategy,
            "dtype": dtype,
            "bf16": bf16,
            "fp16": fp16,
            "seed": seed,
            "max_length": max_length,
            "packing": packing,
        }


class _SFTConfigAntigo:
    """Assinatura do ``trl < 1.0`` (``evaluation_strategy``/``torch_dtype``)."""

    def __init__(
        self,
        output_dir=None,
        evaluation_strategy=None,
        torch_dtype=None,
        bf16=None,
        seed=None,
        max_seq_length=None,
    ):
        self.recebidos = {
            "output_dir": output_dir,
            "evaluation_strategy": evaluation_strategy,
            "torch_dtype": torch_dtype,
            "bf16": bf16,
            "seed": seed,
            "max_seq_length": max_seq_length,
        }


class _SFTConfigComExtras:
    """Assinatura que repassa tudo por ``**kwargs``."""

    def __init__(self, **kwargs):
        self.recebidos = dict(kwargs)


class _SFTConfigDesconhecido:
    """Assinatura sem os nomes esperados e sem ``**kwargs``."""

    def __init__(self, foo=None):
        self.foo = foo


class _TreinadorNovo:
    """``SFTTrainer`` com ``processing_class`` (TRL recente)."""

    def __init__(
        self,
        model=None,
        args=None,
        train_dataset=None,
        eval_dataset=None,
        peft_config=None,
        processing_class=None,
    ):
        self.recebidos = {
            "model": model,
            "args": args,
            "train_dataset": train_dataset,
            "eval_dataset": eval_dataset,
            "peft_config": peft_config,
            "processing_class": processing_class,
        }


class _TreinadorAntigo:
    """``SFTTrainer`` com ``tokenizer`` (TRL antigo)."""

    def __init__(
        self,
        model=None,
        args=None,
        train_dataset=None,
        eval_dataset=None,
        peft_config=None,
        tokenizer=None,
    ):
        self.recebidos = {
            "model": model,
            "args": args,
            "train_dataset": train_dataset,
            "eval_dataset": eval_dataset,
            "peft_config": peft_config,
            "tokenizer": tokenizer,
        }


class _ModeloNovo:
    """``from_pretrained`` com ``dtype`` (transformers >= 5.0)."""

    @classmethod
    def from_pretrained(
        cls,
        modelo,
        *args,
        dtype=None,
        device_map=None,
        **kwargs,
    ):
        return {"dtype": dtype, "device_map": device_map}


class _ModeloAntigo:
    """``from_pretrained`` com ``torch_dtype`` (transformers < 5.0)."""

    @classmethod
    def from_pretrained(
        cls,
        modelo,
        *args,
        torch_dtype=None,
        device_map=None,
        **kwargs,
    ):
        return {"torch_dtype": torch_dtype, "device_map": device_map}


class TestCompatibilidadeAssinaturas(unittest.TestCase):
    """Mapeamento portátil das assinaturas do TRL/transformers.

    Os dublês reproduzem as duas pontas: ``trl >= 1.18``, alvo desta
    correção (``eval_strategy``/``dtype``/``processing_class``), e o
    contrato anterior (``evaluation_strategy``/``torch_dtype``/
    ``tokenizer``). Nenhuma biblioteca pesada é importada.
    """

    OPCOES = {
        "output_dir": "adaptadores/teste",
        "num_train_epochs": 3,
        "eval_strategy": "epoch",
        "dtype": "bf16",
        "bf16": True,
        "fp16": False,
        "seed": 42,
        "max_length": 1024,
        "packing": False,
    }

    def test_sft_config_novo_usa_eval_strategy_e_dtype(self):
        opcoes = dict(self.OPCOES, fp32=True)
        argumentos, avisos = treinar_lora.montar_argumentos_sft(
            opcoes,
            _SFTConfigNovo,
        )
        config = _SFTConfigNovo(**argumentos)

        self.assertEqual(config.recebidos["eval_strategy"], "epoch")
        self.assertEqual(config.recebidos["dtype"], "bf16")
        self.assertEqual(config.recebidos["max_length"], 1024)
        self.assertEqual(config.recebidos["num_train_epochs"], 3)
        self.assertNotIn("evaluation_strategy", argumentos)
        self.assertNotIn("torch_dtype", argumentos)
        self.assertNotIn("fp32", argumentos)
        self.assertEqual(
            avisos,
            ["parametros_nao_suportados:fp32"],
        )

    def test_sft_config_antigo_traduz_para_evaluation_strategy(self):
        argumentos, avisos = treinar_lora.montar_argumentos_sft(
            self.OPCOES,
            _SFTConfigAntigo,
        )
        config = _SFTConfigAntigo(**argumentos)

        self.assertEqual(
            config.recebidos["evaluation_strategy"],
            "epoch",
        )
        self.assertEqual(config.recebidos["torch_dtype"], "bf16")
        self.assertNotIn("eval_strategy", argumentos)
        self.assertNotIn("dtype", argumentos)
        self.assertNotIn("max_length", argumentos)
        self.assertTrue(
            any(
                aviso.startswith("parametros_nao_suportados:")
                for aviso in avisos
            ),
            avisos,
        )

    def test_sft_config_com_kwargs_preserva_nomes_novos(self):
        opcoes = dict(self.OPCOES, fp32=True)
        argumentos, avisos = treinar_lora.montar_argumentos_sft(
            opcoes,
            _SFTConfigComExtras,
        )
        config = _SFTConfigComExtras(**argumentos)

        self.assertEqual(config.recebidos, opcoes)
        self.assertEqual(avisos, [])

    def test_sft_config_sem_aliases_registra_aviso(self):
        argumentos, avisos = treinar_lora.montar_argumentos_sft(
            {"eval_strategy": "epoch"},
            _SFTConfigDesconhecido,
        )

        self.assertEqual(argumentos, {})
        self.assertEqual(avisos, ["parametro_ignorado:eval_strategy"])

    def test_assinatura_indisponivel_assume_api_nova(self):
        argumentos, avisos = treinar_lora.montar_argumentos_sft(
            {"eval_strategy": "epoch", "max_length": 1024},
            dict,
        )

        self.assertEqual(
            argumentos,
            {"eval_strategy": "epoch", "max_length": 1024},
        )
        self.assertEqual(avisos, [])

    def test_treinador_prefere_processing_class(self):
        opcoes = {
            "model": "modelo",
            "args": "config",
            "train_dataset": [],
            "eval_dataset": [],
            "peft_config": "lora",
            "processing_class": "tokenizer",
        }
        argumentos, avisos = treinar_lora.montar_argumentos_treinador(
            opcoes,
            _TreinadorNovo,
        )
        treinador = _TreinadorNovo(**argumentos)

        self.assertEqual(
            treinador.recebidos["processing_class"],
            "tokenizer",
        )
        self.assertEqual(treinador.recebidos["peft_config"], "lora")
        self.assertNotIn("tokenizer", argumentos)
        self.assertEqual(avisos, [])

        argumentos, avisos = treinar_lora.montar_argumentos_treinador(
            opcoes,
            _TreinadorAntigo,
        )
        treinador = _TreinadorAntigo(**argumentos)

        self.assertEqual(treinador.recebidos["tokenizer"], "tokenizer")
        self.assertEqual(treinador.recebidos["peft_config"], "lora")
        self.assertNotIn("processing_class", argumentos)
        self.assertEqual(avisos, [])

    def test_carga_do_modelo_usa_dtype_ou_torch_dtype(self):
        opcoes = {"dtype": "torch.bfloat16", "device_map": "auto"}

        for classe, chave in (
            (_ModeloNovo, "dtype"),
            (_ModeloAntigo, "torch_dtype"),
        ):
            with self.subTest(classe=classe.__name__):
                argumentos, avisos = treinar_lora.montar_argumentos_carga(
                    opcoes,
                    classe,
                )
                resultado = classe.from_pretrained("base", **argumentos)

                self.assertEqual(argumentos[chave], "torch.bfloat16")
                self.assertNotIn(
                    "torch_dtype" if chave == "dtype" else "dtype",
                    argumentos,
                )
                self.assertEqual(resultado[chave], "torch.bfloat16")
                self.assertEqual(resultado["device_map"], "auto")
                self.assertEqual(avisos, [])


class TestModelfile(unittest.TestCase):
    """Template determinístico de registro no Ollama."""

    def test_parametros_deterministicos_e_caminho_normalizado(self):
        texto = gerar_modelfile.montar_modelfile(
            "modelo-teste",
            base="qwen3:4b",
            adaptador="C:\\tmp\\adaptador",
            num_ctx=32768,
        )

        self.assertIn("FROM qwen3:4b", texto)
        self.assertIn("ADAPTER C:/tmp/adaptador", texto)
        self.assertIn("PARAMETER temperature 0", texto)
        self.assertIn("PARAMETER seed 42", texto)
        self.assertIn("PARAMETER num_ctx 32768", texto)
        self.assertTrue(texto.endswith("\n"))

    def test_sem_adaptador_omite_adapter(self):
        texto = gerar_modelfile.montar_modelfile(
            "modelo-base-teste",
            adaptador=None,
        )

        self.assertNotIn("ADAPTER", texto)
        self.assertIn("PARAMETER temperature 0", texto)
        self.assertIn("PARAMETER seed 42", texto)

    def test_cli_grava_atomicamente_e_e_idempotente(self):
        pasta = BASE / "modelfile"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        destino = pasta / "Modelfile.teste"
        argumentos = [
            "--nome",
            "modelo-teste",
            "--saida",
            str(destino),
            "--json",
        ]
        with contextlib.redirect_stdout(io.StringIO()) as saida:
            codigo = gerar_modelfile.main(argumentos)

        self.assertEqual(codigo, 0)
        primeiro = json.loads(saida.getvalue())
        self.assertTrue(primeiro["alterado"])
        self.assertTrue(destino.is_file())
        self.assertIn(
            "PARAMETER seed 42",
            destino.read_text(encoding="utf-8"),
        )

        with contextlib.redirect_stdout(io.StringIO()) as saida:
            codigo = gerar_modelfile.main(argumentos)

        self.assertEqual(codigo, 0)
        segundo = json.loads(saida.getvalue())
        self.assertFalse(segundo["alterado"])
        self.assertEqual(primeiro["sha256"], segundo["sha256"])

    def test_nome_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            gerar_modelfile.montar_modelfile("nome com espaco")

    def test_modelfile_do_repositorio_usa_os_mesmos_parametros(self):
        if not gerar_modelfile.ARQUIVO_PADRAO.is_file():
            self.skipTest("Modelfile padrão ainda não gerado")

        texto = gerar_modelfile.ARQUIVO_PADRAO.read_text(
            encoding="utf-8"
        )

        self.assertIn("PARAMETER temperature 0", texto)
        self.assertIn("PARAMETER seed 42", texto)
        self.assertIn(
            f"FROM {gerar_modelfile.BASE_PADRAO}",
            texto,
        )


class TestGuardaBanco(unittest.TestCase):
    """A exportação e o dry-run não podem tocar o banco real."""

    def test_exportacao_e_dry_run_preservam_db_intocado(self):
        pasta = BASE / "guarda"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        antes = _db_intocado.capturar()
        treino = pasta / "treino.jsonl"
        validacao = pasta / "validacao.jsonl"
        manifesto = pasta / "manifesto.json"
        exportar_sft.exportar(
            gerador.carregar_registros(),
            destino_treino=treino,
            destino_validacao=validacao,
            destino_manifesto=manifesto,
        )
        processo = subprocess.run(
            [
                sys.executable,
                "-m",
                "finetuning.treinar_lora",
                "--dry-run",
                "--treino",
                str(treino),
                "--validacao",
                str(validacao),
                "--manifesto",
                str(manifesto),
                "--saida-dir",
                str(pasta / "adaptador"),
            ],
            check=False,
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=120,
        )
        depois = _db_intocado.capturar()
        comparacao = _db_intocado.comparar(antes, depois)

        self.assertEqual(processo.returncode, 0, processo.stderr)
        self.assertTrue(comparacao["DB_INTOCADO"])
