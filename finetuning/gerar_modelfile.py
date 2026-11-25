"""Gerador do Modelfile determinístico do adaptador LoRA no Ollama.

O treino LoRA produz um adaptador (Safetensors) que o Ollama registra
com FROM (modelo base em GGUF) + ADAPTER (pasta do adaptador). Este
módulo monta o texto do Modelfile com os mesmos parâmetros
determinísticos do benchmark e do treino: temperature 0 e seed 42,
além do num_ctx padrão do projeto. O arquivo é gravado de forma
atômica e idempotente por finetuning.arquivo_seguro.

Nada aqui executa ollama, baixa pesos ou abre o banco: o comando
ollama create é apenas impresso para execução manual em qualquer PC.

Uso::

    ./.venv/Scripts/python.exe -m finetuning.gerar_modelfile
    ./.venv/Scripts/python.exe -m finetuning.gerar_modelfile --sem-adaptador
    ./.venv/Scripts/python.exe -m finetuning.gerar_modelfile --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from finetuning import arquivo_seguro

PASTA = Path(__file__).resolve().parent
NOME_PADRAO = "nexusgeo-qwen3-4b-v2"
BASE_PADRAO = "qwen3:4b"
ADAPTADOR_PADRAO = "finetuning/adaptadores/nexusgeo-qwen3-4b-v2"
NUM_CTX_PADRAO = 32000
TEMPERATURA_PADRAO = 0.0
SEED_PADRAO = 42
ARQUIVO_PADRAO = PASTA / f"Modelfile.{NOME_PADRAO}"


def _validar_nome(nome: str) -> str:
    valor = str(nome or "").strip()

    if not valor or any(caractere.isspace() for caractere in valor):
        raise ValueError(f"nome_invalido:{nome!r}")

    return valor


def _validar_base(base: str) -> str:
    valor = str(base or "").strip()

    if not valor or "\n" in valor:
        raise ValueError(f"modelo_base_invalido:{base!r}")

    return valor


def _caminho_ollama(caminho: str) -> str:
    """Caminho em barras normais, aceito pelo Ollama em Windows/Linux."""

    return str(caminho).replace("\\", "/")


def montar_modelfile(
    nome: str = NOME_PADRAO,
    *,
    base: str = BASE_PADRAO,
    adaptador: str | None = ADAPTADOR_PADRAO,
    num_ctx: int = NUM_CTX_PADRAO,
    temperatura: float = TEMPERATURA_PADRAO,
    seed: int = SEED_PADRAO,
    sistema: str | None = None,
) -> str:
    """Monta o texto do Modelfile, sem tocar no disco nem no Ollama."""

    nome = _validar_nome(nome)
    base = _validar_base(base)

    if int(num_ctx) <= 0:
        raise ValueError(f"num_ctx_invalido:{num_ctx}")

    if float(temperatura) < 0:
        raise ValueError(f"temperatura_invalida:{temperatura}")

    if int(seed) < 0:
        raise ValueError(f"seed_invalida:{seed}")

    linhas = [
        "# NexusGeo IA - Caminho 2 (dataset comportamental v2).",
        "# Gerado por finetuning.gerar_modelfile.py; nao edite a mao.",
        f"# Modelo base: {base}",
    ]

    if adaptador:
        adaptador = _caminho_ollama(adaptador)
        linhas.append(f"# Adaptador LoRA: {adaptador}")

    linhas.append(f"FROM {base}")

    if adaptador:
        linhas.append(f"ADAPTER {adaptador}")

    valor_temperatura = (
        int(temperatura)
        if float(temperatura).is_integer()
        else temperatura
    )
    linhas.extend(
        [
            f"PARAMETER temperature {valor_temperatura}",
            f"PARAMETER seed {int(seed)}",
            f"PARAMETER num_ctx {int(num_ctx)}",
        ]
    )

    if sistema:
        texto = str(sistema).strip().replace('"""', '" "')

        if texto:
            linhas.extend(['SYSTEM """', texto, '"""'])

    return "\n".join(linhas) + "\n"


def gravar_modelfile(caminho, conteudo: str) -> bool:
    """Grava o Modelfile atomicamente; devolve True quando mudou."""

    return arquivo_seguro.gravar_texto_atomico(caminho, conteudo)


def comandos_ollama(nome: str, caminho) -> list[str]:
    """Comandos manuais de registro e teste, apenas como texto."""

    nome = _validar_nome(nome)
    caminho = _caminho_ollama(caminho)

    return [
        f"ollama create {nome} -f {caminho}",
        f"ollama run {nome}",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gera o Modelfile determinístico do adaptador LoRA "
            "para registro manual no Ollama."
        ),
    )
    parser.add_argument("--nome", default=NOME_PADRAO)
    parser.add_argument("--base", default=BASE_PADRAO)
    parser.add_argument("--adaptador", default=ADAPTADOR_PADRAO)
    parser.add_argument(
        "--sem-adaptador",
        action="store_true",
        help="Registra apenas o modelo base, sem ADAPTER.",
    )
    parser.add_argument("--num-ctx", type=int, default=NUM_CTX_PADRAO)
    parser.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURA_PADRAO,
    )
    parser.add_argument("--seed", type=int, default=SEED_PADRAO)
    parser.add_argument(
        "--sistema",
        default=None,
        help="Texto opcional de SYSTEM para o Modelfile.",
    )
    parser.add_argument("--saida", type=Path, default=ARQUIVO_PADRAO)
    parser.add_argument("--json", action="store_true")
    argumentos = parser.parse_args(argv)

    adaptador = None if argumentos.sem_adaptador else argumentos.adaptador

    try:
        conteudo = montar_modelfile(
            argumentos.nome,
            base=argumentos.base,
            adaptador=adaptador,
            num_ctx=argumentos.num_ctx,
            temperatura=argumentos.temperatura,
            seed=argumentos.seed,
            sistema=argumentos.sistema,
        )
        alterado = gravar_modelfile(argumentos.saida, conteudo)
    except (OSError, ValueError) as erro:
        print(f"modelfile_invalido: {erro}", file=sys.stderr)
        return 2

    digest = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    resultado = {
        "nome": argumentos.nome,
        "base": argumentos.base,
        "adaptador": adaptador,
        "arquivo": str(argumentos.saida),
        "sha256": digest,
        "alterado": alterado,
        "comandos": comandos_ollama(
            argumentos.nome,
            argumentos.saida,
        ),
        "conteudo": conteudo,
    }

    if argumentos.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0

    print(
        f"modelfile={resultado['arquivo']} "
        f"sha256={digest} alterado={alterado}"
    )

    for comando in resultado["comandos"]:
        print(comando)

    return 0


if __name__ == "__main__":
    sys.exit(main())
