"""Treino LoRA portátil do Qwen3-4B sobre o SFT v2 (Caminho 2).

O script é CLI e não importa torch/transformers/peft/trl no topo: com
--dry-run ele valida os JSONL exportados, inspeciona as bibliotecas
instaladas, detecta GPU/CUDA e a precisão efetiva (bf16 nativo, fp16
em CUDA sem bf16, fp32 em CPU/fallback) e imprime o plano completo,
sem baixar pesos e sem exigir o stack de treino no ambiente virtual.

O treino real usa LoRA conservador (r=8, alpha=16 por padrão, alvos
q/k/v/o/gate/up/down), gradient checkpointing, batch pequeno com
acumulação de gradiente, seed 42 e saída em adaptadores/. Ao final,
--gerar-modelfile grava o Modelfile determinístico para o Ollama.

A construção de ``SFTConfig``, ``SFTTrainer`` e
``AutoModelForCausalLM.from_pretrained`` é resolvida por inspeção da
assinatura instalada (ver ``resolver_argumentos``), então o mesmo
script cobre tanto ``trl >= 1.0``/``transformers >= 5.0``
(``eval_strategy``, ``dtype``, ``processing_class``) quanto as
versões antigas (``evaluation_strategy``, ``torch_dtype``,
``tokenizer``), sem condicionais presas a um número de versão.

A partir do ``trl >= 1.0`` o ``SFTTrainer`` recusa listas puras em
``train_dataset``/``eval_dataset`` e exige ``Dataset`` ou
``IterableDataset``. Por isso ``converter_para_dataset`` converte os
registros conversacionais com ``datasets.Dataset.from_list`` antes de
montar o treinador, preservando a coluna ``messages``.

Nenhum caminho deste módulo abre o banco da aplicação; a guarda
DB_INTOCADO permanece válida.

Uso::

    ./.venv/Scripts/python.exe -m finetuning.treinar_lora --dry-run
    ./.venv/Scripts/python.exe -m finetuning.treinar_lora \
        --modelo-base Qwen/Qwen3-4B --epocas 3 --batch 1
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
import random
import sys
from collections import Counter
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _versao
from pathlib import Path

from finetuning import contrato, gerar_modelfile

PASTA = Path(__file__).resolve().parent
PASTA_DATASETS = PASTA / "datasets"
ARQUIVO_TREINO_PADRAO = PASTA_DATASETS / "sft_v2_treino.jsonl"
ARQUIVO_VALIDACAO_PADRAO = PASTA_DATASETS / "sft_v2_validacao.jsonl"
ARQUIVO_MANIFESTO_PADRAO = PASTA_DATASETS / "sft_v2.manifest.json"
MODELO_PADRAO = "Qwen/Qwen3-4B"
SAIDA_PADRAO = PASTA / "adaptadores" / "nexusgeo-qwen3-4b-v2"
MODELFILE_PADRAO = PASTA / "Modelfile.nexusgeo-qwen3-4b-v2"

SEED = 42
PAPEIS = ("system", "user", "assistant")
BIBLIOTECAS_OBRIGATORIAS = (
    "torch",
    "transformers",
    "peft",
    "trl",
    "datasets",
    "accelerate",
)
BIBLIOTECAS_OPCIONAIS = ("bitsandbytes",)
BIBLIOTECAS = BIBLIOTECAS_OBRIGATORIAS + BIBLIOTECAS_OPCIONAIS
PRECISOES = ("auto", "bf16", "fp16", "fp32")
ALVOS_LORA = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)
TIPOS_TORCH = {
    "bf16": "torch.bfloat16",
    "fp16": "torch.float16",
    "fp32": "torch.float32",
}

# Nomes concorrentes por conceito, do mais novo (trl >= 1.0 e
# transformers >= 5.0) para o mais antigo. A escolha real vem da
# assinatura instalada em tempo de execução; se ela não puder ser lida,
# assume-se a API mais nova, que é o alvo desta correção.
ALIASES_SFT_CONFIG = (
    ("eval_strategy", ("eval_strategy", "evaluation_strategy")),
    ("dtype", ("dtype", "torch_dtype")),
)
ALIASES_SFT_TRAINER = (
    ("processing_class", ("processing_class", "tokenizer")),
)
ALIASES_CARGA_MODELO = (
    ("dtype", ("dtype", "torch_dtype")),
)
AUSENTE = object()


def _garantir_saida_utf8() -> None:
    """Emite JSON/avisos em UTF-8 mesmo no console cp1252 do Windows."""

    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def _status_biblioteca(nome: str) -> dict:
    """Presença e versão sem importar o pacote pesado."""

    try:
        encontrada = importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError):
        encontrada = False

    versao = None

    if encontrada:
        try:
            versao = _versao(nome)
        except PackageNotFoundError:
            versao = None

    return {"instalada": encontrada, "versao": versao}


def status_bibliotecas() -> dict:
    """Mapa biblioteca -> presença/versão para o plano de treino."""

    return {nome: _status_biblioteca(nome) for nome in BIBLIOTECAS}


def selecionar_precisao(
    precisao: str = "auto",
    *,
    cuda_disponivel: bool = False,
    bf16_suportado: bool = False,
) -> tuple[str, str]:
    """Precisão efetiva e motivo, sem depender de torch instalado.

    auto: bf16 em CUDA com suporte nativo, fp16 em CUDA sem bf16 e
    fp32 em CPU. Pedidos explícitos são respeitados quando o hardware
    suporta; caso contrário o script cai para a melhor opção segura e
    registra o motivo no plano.
    """

    if precisao not in PRECISOES:
        raise ValueError(f"precisao_desconhecida:{precisao}")

    if precisao == "fp32":
        return "fp32", "solicitada fp32"

    if not cuda_disponivel:
        return (
            "fp32",
            "sem CUDA disponível; CPU/fallback usa fp32",
        )

    if precisao == "bf16":
        if bf16_suportado:
            return "bf16", "solicitada bf16 com suporte nativo"

        return (
            "fp16",
            "bf16 solicitada sem suporte nativo; fallback fp16",
        )

    if precisao == "fp16":
        return "fp16", "solicitada fp16"

    if bf16_suportado:
        return "bf16", "CUDA com bf16 nativo"

    return "fp16", "CUDA sem bf16 nativo; fp16 escolhido"


def detectar_ambiente(
    precisao: str = "auto",
    dispositivo: str = "auto",
) -> dict:
    """Detecta dispositivo, GPUs, bf16 nativo e precisão efetiva."""

    bibliotecas = status_bibliotecas()
    avisos: list[str] = []
    torch = None

    if bibliotecas["torch"]["instalada"]:
        try:
            import torch
        except Exception as erro:  # noqa: BLE001 - ambiente do usuário
            avisos.append(
                f"torch_import_falhou:{type(erro).__name__}:{erro}"
            )
            torch = None

    cuda_disponivel = bool(
        torch is not None and torch.cuda.is_available()
    )
    gpus = []
    bf16_nativo = False

    if cuda_disponivel:
        bf16_nativo = bool(torch.cuda.is_bf16_supported())

        for indice in range(torch.cuda.device_count()):
            propriedades = torch.cuda.get_device_properties(indice)
            gpus.append(
                {
                    "indice": indice,
                    "nome": torch.cuda.get_device_name(indice),
                    "memoria_gb": round(
                        propriedades.total_memory / (1024**3),
                        1,
                    ),
                    "capacidade": (
                        f"{propriedades.major}.{propriedades.minor}"
                    ),
                }
            )

    efetivo = "cuda" if cuda_disponivel else "cpu"

    if dispositivo == "cpu":
        efetivo = "cpu"
    elif dispositivo == "cuda" and not cuda_disponivel:
        avisos.append(
            "cuda_solicitada_indisponivel: usando CPU"
        )

    precisao_efetiva, motivo = selecionar_precisao(
        precisao,
        cuda_disponivel=(efetivo == "cuda"),
        bf16_suportado=bf16_nativo and efetivo == "cuda",
    )

    return {
        "dispositivo": efetivo,
        "dispositivo_solicitado": dispositivo,
        "cuda_disponivel": cuda_disponivel,
        "bf16_nativo": bf16_nativo,
        "gpus": gpus,
        "precisao": {
            "solicitada": precisao,
            "efetiva": precisao_efetiva,
            "motivo": motivo,
        },
        "torch": bibliotecas["torch"],
        "bibliotecas": bibliotecas,
        "bibliotecas_ausentes": [
            nome
            for nome, item in bibliotecas.items()
            if not item["instalada"]
        ],
        "avisos": avisos,
    }


def _validar_mensagens(mensagens) -> None:
    if not isinstance(mensagens, list):
        raise TypeError("messages_nao_e_lista")

    papeis = tuple(
        item.get("role") if isinstance(item, dict) else None
        for item in mensagens
    )

    if papeis != PAPEIS:
        raise ValueError(f"papeis_invalidos:{papeis}")

    for item in mensagens:
        conteudo = item.get("content")

        if not isinstance(conteudo, str) or not conteudo.strip():
            raise ValueError(f"conteudo_vazio:{item.get('role')}")


def validar_sft(caminho) -> dict:
    """Valida estrutura, gabarito JSON e unicidade de um JSONL SFT."""

    caminho = Path(caminho)

    if not caminho.is_file():
        raise FileNotFoundError(f"sft_ausente:{caminho}")

    texto = caminho.read_text(encoding="utf-8")
    linhas = texto.splitlines()
    ids: set[str] = set()
    por_tarefa: Counter = Counter()
    por_idioma: Counter = Counter()

    if not linhas:
        raise ValueError(f"sft_vazio:{caminho}")

    for numero, linha in enumerate(linhas, start=1):
        if not linha.strip():
            raise ValueError(f"linha_vazia:{numero}")

        try:
            exemplo = json.loads(linha)
        except ValueError as erro:
            raise ValueError(
                f"json_invalido:{numero}:{erro}"
            ) from erro

        if not isinstance(exemplo, dict):
            raise TypeError(f"linha_nao_e_objeto:{numero}")

        identificador = exemplo.get("id")
        tarefa = exemplo.get("tarefa")
        idioma = exemplo.get("idioma")
        par = exemplo.get("par")

        if not identificador or not tarefa or not idioma or not par:
            raise ValueError(f"metadados_ausentes:{numero}")

        if identificador in ids:
            raise ValueError(f"id_duplicado:{identificador}")

        ids.add(identificador)
        _validar_mensagens(exemplo.get("messages"))

        resposta = exemplo["messages"][2]["content"]

        try:
            objeto = json.loads(resposta)
        except ValueError as erro:
            raise ValueError(
                f"assistant_json_invalido:{identificador}:{erro}"
            ) from erro

        if not isinstance(objeto, dict):
            raise TypeError(
                f"assistant_nao_e_objeto:{identificador}"
            )

        erros = contrato.validar_saida(tarefa, objeto)

        if erros:
            raise ValueError(
                f"assistant_fora_do_contrato:{identificador}:"
                f"{','.join(erros)}"
            )

        por_tarefa[tarefa] += 1
        por_idioma[idioma] += 1

    dados = texto.encode("utf-8")

    return {
        "arquivo": str(caminho),
        "linhas": len(linhas),
        "bytes": len(dados),
        "sha256": hashlib.sha256(dados).hexdigest(),
        "por_tarefa": dict(sorted(por_tarefa.items())),
        "por_idioma": dict(sorted(por_idioma.items())),
    }


def carregar_exemplos(caminho) -> list[dict]:
    """Carrega o JSONL no formato conversacional aceito pelo TRL."""

    exemplos = []

    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        if linha.strip():
            exemplos.append({"messages": json.loads(linha)["messages"]})

    return exemplos


def converter_para_dataset(exemplos, fabrica=None):
    """Converte registros ``{"messages": [...]}`` em ``Dataset``.

    O ``SFTTrainer`` do ``trl >= 1.0`` não aceita mais uma lista de
    dicionários em ``train_dataset``/``eval_dataset``: ele exige uma
    instância de ``datasets.Dataset`` ou ``IterableDataset``.
    ``Dataset.from_list`` mantém cada registro como um dicionário com a
    chave ``messages``, que é exatamente o formato conversacional lido
    pelo ``SFTTrainer``.

    ``fabrica`` permite injetar um dublê com ``from_list`` e validar a
    conversão nos testes sem exigir ``datasets`` instalado no ambiente
    virtual principal.
    """

    if not isinstance(exemplos, (list, tuple)):
        raise TypeError("dataset_entrada_nao_e_lista")

    registros = list(exemplos)

    if not registros:
        raise ValueError("dataset_sem_registros")

    for registro in registros:
        if not isinstance(registro, dict):
            raise TypeError("dataset_registro_nao_e_objeto")

        _validar_mensagens(registro.get("messages"))

    if fabrica is None:
        from datasets import Dataset

        fabrica = Dataset

    return fabrica.from_list(registros)


def carregar_manifesto(caminho) -> dict:
    try:
        manifesto = json.loads(
            Path(caminho).read_text(encoding="utf-8")
        )
    except ValueError as erro:
        raise ValueError(f"manifesto_json_invalido:{erro}") from erro

    if not isinstance(manifesto, dict) or "arquivos" not in manifesto:
        raise ValueError("manifesto_sft_invalido")

    return manifesto


def conferir_manifesto(manifesto, treino, validacao) -> dict:
    """Confere hashes, contagens e a prova anti-vazamento do manifesto."""

    formato = manifesto.get("formato") or {}

    if formato.get("tipo") != "chat":
        raise ValueError("manifesto_formato_divergente")

    if tuple(formato.get("papeis") or ()) != PAPEIS:
        raise ValueError("manifesto_papeis_divergentes")

    for nome, dados in (
        ("treino", treino),
        ("validacao", validacao),
    ):
        declarado = (manifesto.get("arquivos") or {}).get(nome) or {}

        if declarado.get("sha256") != dados["sha256"]:
            raise ValueError(f"manifesto_sha256_divergente:{nome}")

        if declarado.get("linhas") != dados["linhas"]:
            raise ValueError(f"manifesto_linhas_divergentes:{nome}")

    anti = manifesto.get("anti_vazamento") or {}

    if not anti.get("ok") or anti.get("intersecao_ids") != 0:
        raise ValueError("manifesto_vazamento_teste")

    if anti.get("intersecao_pares") != 0:
        raise ValueError("manifesto_vazamento_teste")

    return {
        "nome": str(manifesto.get("nome", "")),
        "sha256_dataset": (manifesto.get("dataset") or {}).get("sha256"),
        "teste_registros": anti.get("teste_registros"),
        "teste_pares": anti.get("teste_pares"),
        "anti_vazamento_ok": True,
    }


def montar_plano(
    argumentos,
    ambiente: dict,
    treino: dict,
    validacao: dict,
    manifesto: dict | None,
) -> dict:
    """Plano determinístico impresso no dry-run e usado no treino."""

    lote_efetivo = argumentos.batch * argumentos.grad_accum
    passos_por_epoca = math.ceil(treino["linhas"] / lote_efetivo)
    passos_totais = passos_por_epoca * argumentos.epocas
    ausentes = ambiente["bibliotecas_ausentes"]
    faltantes = [
        nome
        for nome in ausentes
        if nome in BIBLIOTECAS_OBRIGATORIAS
        or (argumentos.quantizar_4bit and nome == "bitsandbytes")
    ]

    return {
        "modo": "dry-run" if argumentos.dry_run else "treino",
        "modelo_base": argumentos.modelo_base,
        "modelo_local": Path(argumentos.modelo_base).is_dir(),
        "seed": SEED,
        "dispositivo": {
            "efetivo": ambiente["dispositivo"],
            "solicitado": ambiente["dispositivo_solicitado"],
            "gpus": ambiente["gpus"],
            "cuda_disponivel": ambiente["cuda_disponivel"],
            "bf16_nativo": ambiente["bf16_nativo"],
        },
        "precisao": ambiente["precisao"],
        "lora": {
            "r": argumentos.rank,
            "lora_alpha": argumentos.alpha,
            "lora_dropout": argumentos.lora_dropout,
            "target_modules": list(ALVOS_LORA),
            "task_type": "CAUSAL_LM",
        },
        "treinamento": {
            "epocas": argumentos.epocas,
            "batch_por_dispositivo": argumentos.batch,
            "acumulacao_gradiente": argumentos.grad_accum,
            "batch_efetivo": lote_efetivo,
            "passos_por_epoca": passos_por_epoca,
            "passos_totais": passos_totais,
            "taxa_aprendizado": argumentos.taxa,
            "scheduler": "cosine",
            "warmup_ratio": argumentos.warmup,
            "max_seq": argumentos.max_seq,
            "gradient_checkpointing": True,
            "quantizar_4bit": bool(argumentos.quantizar_4bit),
        },
        "dataset": {
            "treino": treino,
            "validacao": validacao,
            "manifesto": manifesto,
            "formato": "messages",
            "conversao": "datasets.Dataset.from_list",
        },
        "saida": str(argumentos.saida_dir),
        "ollama": {
            "nome": argumentos.nome_ollama,
            "modelfile": str(argumentos.modelfile),
            "gerar_modelfile": bool(argumentos.gerar_modelfile),
        },
        "bibliotecas": ambiente["bibliotecas"],
        "bibliotecas_ausentes": ausentes,
        "bibliotecas_faltantes_para_treinar": faltantes,
        "pronto_para_treinar": not faltantes,
        "avisos": ambiente["avisos"],
    }


def _fixar_semente(torch) -> None:
    """Semente determinística em Python, numpy opcional e torch."""

    random.seed(SEED)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

    try:
        import numpy
    except Exception:  # noqa: BLE001 - numpy pode não existir
        numpy = None

    if numpy is not None:
        numpy.random.seed(SEED)

    torch.manual_seed(SEED)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def inspecionar_assinatura(alvo) -> tuple[frozenset[str], bool]:
    """Nomes de parâmetro aceitos e se a assinatura aceita extras.

    Para classes inspeciona ``alvo.__init__`` — assim ``SFTConfig`` e
    ``SFTTrainer`` (dataclasses) expõem todos os campos do ``__init__``
    gerado —; para callables inspeciona o próprio callable, caso de
    ``AutoModelForCausalLM.from_pretrained``. Quando a assinatura não
    está disponível devolve conjunto vazio e ``True``, e o chamador passa
    os nomes pedidos sem filtrar em vez de descartá-los às cegas.
    """

    try:
        if inspect.isclass(alvo):
            assinatura = inspect.signature(alvo.__init__)
        else:
            assinatura = inspect.signature(alvo)
    except (AttributeError, TypeError, ValueError):
        return frozenset(), True

    nomes: set[str] = set()
    aceita_extras = False

    for nome, parametro in assinatura.parameters.items():
        if parametro.kind is inspect.Parameter.VAR_KEYWORD:
            aceita_extras = True
        elif parametro.kind is not inspect.Parameter.VAR_POSITIONAL:
            nomes.add(nome)

    return frozenset(nomes), aceita_extras


def _escolher_nome(
    assinatura: tuple[frozenset[str], bool],
    candidatos: tuple[str, ...],
) -> str | None:
    """Primeiro nome aceito; com ``**kwargs`` prevalece o mais novo."""

    nomes, aceita_extras = assinatura

    for nome in candidatos:
        if nome in nomes:
            return nome

    return candidatos[0] if aceita_extras else None


def resolver_argumentos(
    opcoes: dict,
    assinatura: tuple[frozenset[str], bool],
    aliases,
    *,
    filtrar: bool = True,
) -> tuple[dict, list[str]]:
    """Traduz conceitos abstratos para os nomes aceitos na assinatura.

    ``opcoes`` pode trazer qualquer variante listada em ``aliases``; o
    valor é remontado com o nome efetivo e os nomes antigos não são
    repetidos. Com ``filtrar``, chaves fora da assinatura são
    descartadas (por exemplo ``max_length`` em versões antigas do TRL) e
    registradas em avisos. Sem assinatura legível nada é filtrado.
    """

    ajustadas = dict(opcoes)
    avisos: list[str] = []

    for conceito, candidatos in aliases:
        valor = AUSENTE

        for nome in candidatos:
            if valor is AUSENTE and nome in ajustadas:
                valor = ajustadas[nome]

            ajustadas.pop(nome, None)

        if valor is AUSENTE:
            continue

        efetivo = _escolher_nome(assinatura, candidatos)

        if efetivo is None:
            avisos.append(f"parametro_ignorado:{conceito}")
            continue

        ajustadas[efetivo] = valor

    nomes, aceita_extras = assinatura

    if filtrar and not aceita_extras:
        descartados = sorted(
            chave for chave in ajustadas if chave not in nomes
        )

        if descartados:
            avisos.append(
                "parametros_nao_suportados:" + ",".join(descartados)
            )
            ajustadas = {
                chave: valor
                for chave, valor in ajustadas.items()
                if chave in nomes
            }

    return ajustadas, avisos


def montar_argumentos_sft(opcoes: dict, classe) -> tuple[dict, list[str]]:
    """Opções do ``SFTConfig`` na assinatura instalada do TRL."""

    return resolver_argumentos(
        opcoes,
        inspecionar_assinatura(classe),
        ALIASES_SFT_CONFIG,
    )


def montar_argumentos_treinador(
    opcoes: dict,
    classe,
) -> tuple[dict, list[str]]:
    """Opções do ``SFTTrainer`` (``processing_class`` x ``tokenizer``).

    O filtro fica desligado de propósito: ``peft_config`` e os datasets
    são essenciais, e uma incompatibilidade deve falhar de forma
    explícita em vez de treinar sem o adaptador LoRA.
    """

    return resolver_argumentos(
        opcoes,
        inspecionar_assinatura(classe),
        ALIASES_SFT_TRAINER,
        filtrar=False,
    )


def montar_argumentos_carga(opcoes: dict, classe) -> tuple[dict, list[str]]:
    """Opções de ``from_pretrained`` (``dtype`` x ``torch_dtype``)."""

    return resolver_argumentos(
        opcoes,
        inspecionar_assinatura(classe.from_pretrained),
        ALIASES_CARGA_MODELO,
    )


def executar_treino(
    argumentos,
    ambiente: dict,
    treino: dict,
    validacao: dict,
) -> dict:
    """Treino LoRA real; só chamado fora do dry-run e com libs prontas."""

    import torch
    from peft import LoraConfig
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        set_seed,
    )
    from trl import SFTConfig, SFTTrainer

    set_seed(SEED)
    _fixar_semente(torch)

    precisao = ambiente["precisao"]["efetiva"]
    tipos = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }
    base = argumentos.modelo_base
    tokenizer = AutoTokenizer.from_pretrained(base)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    carga = {"dtype": tipos[precisao]}

    if argumentos.quantizar_4bit:
        from transformers import BitsAndBytesConfig

        carga["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=tipos[precisao],
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        carga["device_map"] = "auto"
    elif ambiente["dispositivo"] == "cuda":
        carga["device_map"] = "auto"

    opcoes_carga, avisos_carga = montar_argumentos_carga(
        carga,
        AutoModelForCausalLM,
    )
    modelo = AutoModelForCausalLM.from_pretrained(base, **opcoes_carga)

    if hasattr(modelo, "gradient_checkpointing_enable"):
        modelo.gradient_checkpointing_enable()

    if getattr(modelo, "config", None) is not None:
        modelo.config.use_cache = False

    lora = LoraConfig(
        r=argumentos.rank,
        lora_alpha=argumentos.alpha,
        lora_dropout=argumentos.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(ALVOS_LORA),
    )
    exemplos_treino = carregar_exemplos(argumentos.treino)
    exemplos_validacao = carregar_exemplos(argumentos.validacao)
    # trl >= 1.0 exige Dataset/IterableDataset em train_dataset e
    # eval_dataset; Dataset.from_list preserva a coluna "messages".
    dataset_treino = converter_para_dataset(exemplos_treino)
    dataset_validacao = converter_para_dataset(exemplos_validacao)
    comum = {
        "output_dir": str(argumentos.saida_dir),
        "num_train_epochs": argumentos.epocas,
        "per_device_train_batch_size": argumentos.batch,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": argumentos.grad_accum,
        "learning_rate": argumentos.taxa,
        "lr_scheduler_type": "cosine",
        "warmup_ratio": argumentos.warmup,
        "logging_steps": argumentos.logging_steps,
        "save_strategy": "epoch",
        "save_total_limit": 2,
        "bf16": precisao == "bf16",
        "fp16": precisao == "fp16",
        "gradient_checkpointing": True,
        "seed": SEED,
        "data_seed": SEED,
        "report_to": "none",
        "eval_strategy": "epoch",
        "max_length": argumentos.max_seq,
        "packing": False,
    }
    # fp32 é o padrão do TrainingArguments quando bf16 e fp16 são False;
    # não existe campo "fp32" e passá-lo quebraria a dataclass.
    opcoes_sft, avisos_sft = montar_argumentos_sft(comum, SFTConfig)
    config = SFTConfig(**opcoes_sft)
    opcoes_treinador, avisos_treinador = montar_argumentos_treinador(
        {
            "model": modelo,
            "args": config,
            "train_dataset": dataset_treino,
            "eval_dataset": dataset_validacao,
            "peft_config": lora,
            "processing_class": tokenizer,
        },
        SFTTrainer,
    )
    treinador = SFTTrainer(**opcoes_treinador)
    resultado = treinador.train()
    treinador.save_model(str(argumentos.saida_dir))
    tokenizer.save_pretrained(str(argumentos.saida_dir))
    metricas = dict(getattr(resultado, "metrics", {}) or {})

    return {
        "saida": str(argumentos.saida_dir),
        "metricas": {
            chave: valor
            for chave, valor in metricas.items()
            if isinstance(valor, (int, float, str))
        },
        "treino": treino,
        "validacao": validacao,
        "compatibilidade": {
            "sft_config": avisos_sft,
            "sft_trainer": avisos_treinador,
            "modelo": avisos_carga,
        },
    }


def _resolver_manifesto(argumentos) -> Path | None:
    if argumentos.manifesto is not None:
        return Path(argumentos.manifesto)

    treino_padrao = Path(argumentos.treino).resolve() == (
        ARQUIVO_TREINO_PADRAO.resolve()
    )
    validacao_padrao = Path(argumentos.validacao).resolve() == (
        ARQUIVO_VALIDACAO_PADRAO.resolve()
    )

    if treino_padrao and validacao_padrao:
        return ARQUIVO_MANIFESTO_PADRAO

    return None


def main(argv=None) -> int:
    _garantir_saida_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Treino LoRA portátil do Qwen3-4B sobre o SFT v2, com "
            "dry-run sem pesos e gerador de Modelfile."
        ),
    )
    parser.add_argument("--modelo-base", default=MODELO_PADRAO)
    parser.add_argument("--treino", type=Path, default=ARQUIVO_TREINO_PADRAO)
    parser.add_argument(
        "--validacao",
        type=Path,
        default=ARQUIVO_VALIDACAO_PADRAO,
    )
    parser.add_argument("--manifesto", type=Path, default=None)
    parser.add_argument("--saida-dir", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--nome-ollama", default=gerar_modelfile.NOME_PADRAO)
    parser.add_argument(
        "--modelfile",
        type=Path,
        default=MODELFILE_PADRAO,
    )
    parser.add_argument("--gerar-modelfile", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--precisao", choices=PRECISOES, default="auto")
    parser.add_argument(
        "--dispositivo",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument("--epocas", type=int, default=3)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--taxa", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--warmup", type=float, default=0.03)
    parser.add_argument("--max-seq", type=int, default=1024)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--quantizar-4bit", action="store_true")
    argumentos = parser.parse_args(argv)

    for nome in ("epocas", "batch", "grad_accum", "rank", "alpha"):
        if getattr(argumentos, nome) <= 0:
            print(
                f"treino_invalido:{nome}_deve_ser_positivo",
                file=sys.stderr,
            )
            return 2

    if argumentos.max_seq <= 0:
        print("treino_invalido:max_seq_deve_ser_positivo", file=sys.stderr)
        return 2

    manifesto_info = None
    try:
        treino = validar_sft(argumentos.treino)
        validacao = validar_sft(argumentos.validacao)
        caminho_manifesto = _resolver_manifesto(argumentos)

        if caminho_manifesto is not None:
            if Path(caminho_manifesto).is_file():
                manifesto = carregar_manifesto(caminho_manifesto)
                manifesto_info = conferir_manifesto(
                    manifesto,
                    treino,
                    validacao,
                )
            else:
                manifesto_info = {
                    "arquivo": str(caminho_manifesto),
                    "aviso": "manifesto_ausente",
                }
    except (OSError, ValueError, TypeError) as erro:
        print(f"sft_invalido: {erro}", file=sys.stderr)
        return 2

    ambiente = detectar_ambiente(
        argumentos.precisao,
        argumentos.dispositivo,
    )
    plano = montar_plano(
        argumentos,
        ambiente,
        treino,
        validacao,
        manifesto_info,
    )
    plano["dry_run"] = bool(argumentos.dry_run)

    if argumentos.dry_run:
        print(json.dumps(plano, ensure_ascii=False, indent=2))
        return 0

    faltantes = plano["bibliotecas_faltantes_para_treinar"]

    if faltantes:
        print(
            "treino_indisponivel: instale "
            + ", ".join(faltantes)
            + " no ambiente virtual antes de treinar (o dry-run não "
            "exige essas bibliotecas).",
            file=sys.stderr,
        )
        return 2

    try:
        resultado = executar_treino(
            argumentos,
            ambiente,
            treino,
            validacao,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as erro:
        print(f"treino_falhou: {erro}", file=sys.stderr)
        return 1

    resultado["plano"] = plano

    if argumentos.gerar_modelfile:
        conteudo = gerar_modelfile.montar_modelfile(
            argumentos.nome_ollama,
            base=gerar_modelfile.BASE_PADRAO,
            adaptador=str(argumentos.saida_dir),
            num_ctx=gerar_modelfile.NUM_CTX_PADRAO,
            temperatura=gerar_modelfile.TEMPERATURA_PADRAO,
            seed=SEED,
        )
        alterado = gerar_modelfile.gravar_modelfile(
            argumentos.modelfile,
            conteudo,
        )
        resultado["modelfile"] = {
            "arquivo": str(argumentos.modelfile),
            "sha256": hashlib.sha256(
                conteudo.encode("utf-8")
            ).hexdigest(),
            "alterado": alterado,
        }

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
