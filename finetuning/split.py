"""Divisão determinística treino/validação/teste do dataset comportamental.

O split é feito por **par bilíngue** (`metadados.par`): o registro PT-BR
e o registro EN do mesmo caso caem sempre no mesmo conjunto, evitando
vazamento de gabarito entre treino e avaliação. A atribuição é
estratificada por tarefa e ordenada por SHA-256 de uma sal fixa, então
não depende de `hash()`, do sistema operacional nem da ordem de
inserção do JSONL.

O manifesto gravado em `datasets/<dataset>.split.json` registra a
política, as contagens e o SHA-256 dos registros; a auditoria compara
esse hash e a atribuição recomputada, detectando split velho quando o
dataset muda.

Uso::

    ./.venv/Scripts/python.exe -m finetuning.split
    ./.venv/Scripts/python.exe -m finetuning.split --resumo
    ./.venv/Scripts/python.exe -m finetuning.split --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from finetuning import arquivo_seguro, contrato

PASTA_DATASETS = Path(__file__).resolve().parent / "datasets"
ARQUIVO_SPLIT = (
    PASTA_DATASETS / f"{contrato.NOME_DATASET}.split.json"
)

SPLITS = ("treino", "validacao", "teste")
FRACAO_TREINO = 0.70
FRACAO_VALIDACAO = 0.15
SAL = "nexusgeoia-behavior-split-v2"
AGRUPAMENTO = "metadados.par"
ESTRATIFICACAO = "tarefa"


def _hash_registros(registros) -> str:
    """SHA-256 canônico dos registros, sem duplicar a serialização."""

    from finetuning import gerador

    return gerador.hash_registros(registros)


def _carregar_registros(caminho=None):
    from finetuning import gerador

    return gerador.carregar_registros(caminho)


def _chave_ordenacao(par: str) -> str:
    """Posição estável do par no sorteio determinístico."""

    return hashlib.sha256(f"{SAL}:{par}".encode()).hexdigest()


def agrupar_pares(registros) -> dict[str, list[dict]]:
    """Agrupa os registros pelo par bilíngue, preservando a ordem."""

    grupos: dict[str, list[dict]] = {}

    for registro in registros:
        par = registro.get("metadados", {}).get("par")

        if not isinstance(par, str) or not par:
            raise ValueError("registro_sem_par")

        grupos.setdefault(par, []).append(registro)

    return grupos


def _cortes(quantidade: int) -> tuple[int, int, int]:
    """Cortes 70/15/15 com pelo menos um grupo em cada split quando possível."""

    if quantidade <= 0:
        return 0, 0, 0

    if quantidade < 3:
        return quantidade, 0, 0

    treino = max(1, int(quantidade * FRACAO_TREINO))
    validacao = max(1, int(quantidade * FRACAO_VALIDACAO))

    if treino + validacao > quantidade - 1:
        validacao = 1
        treino = quantidade - 2

    teste = quantidade - treino - validacao
    return treino, validacao, teste


def atribuir_splits(registros) -> dict[str, str]:
    """Devolve `par -> split` de forma determinística e estratificada."""

    grupos = agrupar_pares(registros)
    por_tarefa: dict[str, list[str]] = {}

    for par, itens in grupos.items():
        tarefas = {item.get("tarefa") for item in itens}

        if len(tarefas) != 1:
            raise ValueError(f"par_com_tarefas_divergentes:{par}")

        por_tarefa.setdefault(next(iter(tarefas)), []).append(par)

    atribuicao: dict[str, str] = {}

    for tarefa in sorted(por_tarefa):
        pares = sorted(por_tarefa[tarefa], key=_chave_ordenacao)
        treino, validacao, teste = _cortes(len(pares))

        for indice, par in enumerate(pares):
            if indice < treino:
                atribuicao[par] = "treino"
            elif indice < treino + validacao:
                atribuicao[par] = "validacao"
            else:
                atribuicao[par] = "teste"

        if teste < 0:
            raise ValueError(f"split_negativo:{tarefa}")

    return atribuicao


def _resumo_split(itens, registros_por_id) -> dict:
    """Contagens de pares, registros, tarefas e idiomas de um split."""

    ids = []

    for item in itens:
        ids.extend(item["ids"])

    registros = [registros_por_id[identificador] for identificador in ids]

    return {
        "pares": len(itens),
        "registros": len(registros),
        "por_tarefa": dict(
            sorted(Counter(r["tarefa"] for r in registros).items())
        ),
        "por_idioma": dict(
            sorted(Counter(r["idioma"] for r in registros).items())
        ),
        "por_familia": dict(
            sorted(
                Counter(
                    r["metadados"]["familia"] for r in registros
                ).items()
            )
        ),
    }


def gerar_split(registros=None) -> dict:
    """Monta o manifesto do split a partir dos registros carregados."""

    registros = (
        list(registros)
        if registros is not None
        else _carregar_registros()
    )
    grupos = agrupar_pares(registros)
    atribuicao = atribuir_splits(registros)
    registros_por_id = {registro["id"]: registro for registro in registros}
    itens_por_split = {nome: [] for nome in SPLITS}

    for par in sorted(grupos):
        itens = sorted(
            grupos[par],
            key=lambda registro: (registro["idioma"], registro["id"]),
        )
        split = atribuicao[par]
        itens_por_split[split].append(
            {
                "par": par,
                "tarefa": itens[0]["tarefa"],
                "familia": itens[0]["metadados"]["familia"],
                "split": split,
                "ids": [registro["id"] for registro in itens],
            }
        )

    pares = [
        item
        for nome in SPLITS
        for item in sorted(itens_por_split[nome], key=lambda i: i["par"])
    ]

    return {
        "nome": contrato.NOME_DATASET,
        "versao": contrato.VERSAO_DATASET,
        "arquivo_dataset": f"{contrato.NOME_DATASET}.jsonl",
        "sha256_dataset": _hash_registros(registros),
        "total_pares": len(grupos),
        "total_registros": len(registros),
        "politica": {
            "agrupamento": AGRUPAMENTO,
            "estratificacao": ESTRATIFICACAO,
            "sal": SAL,
            "fracoes": {
                "treino": FRACAO_TREINO,
                "validacao": FRACAO_VALIDACAO,
                "teste": round(1 - FRACAO_TREINO - FRACAO_VALIDACAO, 2),
            },
            "ordenacao": "sha256(sal:par)",
        },
        "por_split": {
            nome: _resumo_split(itens_por_split[nome], registros_por_id)
            for nome in SPLITS
        },
        "pares": pares,
    }


def validar_split(registros, manifesto) -> list[dict]:
    """Confere integridade e atualidade do split contra o dataset."""

    problemas: list[dict] = []

    if not isinstance(manifesto, dict):
        return [{"codigo": "split_invalido", "detalhe": "nao_e_objeto"}]

    if manifesto.get("sha256_dataset") != _hash_registros(registros):
        problemas.append(
            {
                "codigo": "split_desatualizado",
                "detalhe": "sha256_dataset_divergente",
            }
        )

    esperado = atribuir_splits(registros)
    declarado = {}
    vistos = set()

    for item in manifesto.get("pares") or []:
        if not isinstance(item, dict):
            problemas.append(
                {"codigo": "split_invalido", "detalhe": "par_nao_e_objeto"}
            )
            continue

        par = item.get("par")
        declarado[par] = item.get("split")

        for identificador in item.get("ids") or []:
            if identificador in vistos:
                problemas.append(
                    {
                        "codigo": "split_id_duplicado",
                        "detalhe": identificador,
                    }
                )

            vistos.add(identificador)

    if set(declarado) != set(esperado):
        problemas.append(
            {
                "codigo": "split_pares_divergentes",
                "detalhe": sorted(set(esperado) ^ set(declarado))[:10],
            }
        )

    for par, split in esperado.items():
        if declarado.get(par) != split:
            problemas.append(
                {
                    "codigo": "split_atribuicao_divergente",
                    "detalhe": f"{par}:{declarado.get(par)}!={split}",
                }
            )

    if len(vistos) != len(registros):
        problemas.append(
            {
                "codigo": "split_registros_divergentes",
                "detalhe": (len(vistos), len(registros)),
            }
        )

    return problemas


def gravar_split(registros=None, destino=None) -> dict:
    """Grava o manifesto do split de forma atômica e idempotente."""

    registros = (
        list(registros)
        if registros is not None
        else _carregar_registros()
    )
    destino = Path(destino or ARQUIVO_SPLIT)
    manifesto = gerar_split(registros)
    texto = json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n"
    alterado = arquivo_seguro.gravar_texto_atomico(destino, texto)

    return {
        "arquivo": str(destino),
        "total_pares": manifesto["total_pares"],
        "total_registros": manifesto["total_registros"],
        "sha256_dataset": manifesto["sha256_dataset"],
        "alterado": alterado,
    }


def carregar_split(caminho=None) -> dict:
    """Lê o manifesto do split e valida o JSON mínimo."""

    caminho = Path(caminho or ARQUIVO_SPLIT)

    try:
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError as erro:
        raise ValueError(f"split_json_invalido: {erro}") from erro

    if not isinstance(manifesto, dict) or "pares" not in manifesto:
        raise ValueError("split_json_invalido: pares ausente")

    return manifesto


def registros_do_split(nome, registros=None, caminho=None) -> list[dict]:
    """Registros de um split, na ordem canônica do dataset."""

    if nome not in SPLITS:
        raise ValueError(f"split_desconhecido:{nome}")

    registros = (
        list(registros)
        if registros is not None
        else _carregar_registros()
    )
    manifesto = carregar_split(caminho)
    ids = {
        identificador
        for item in manifesto["pares"]
        if item.get("split") == nome
        for identificador in item.get("ids") or []
    }

    return [
        registro
        for registro in registros
        if registro["id"] in ids
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera o split determinístico do dataset comportamental.",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--saida", type=Path, default=ARQUIVO_SPLIT)
    parser.add_argument("--resumo", action="store_true")
    parser.add_argument("--json", action="store_true")
    argumentos = parser.parse_args(argv)

    registros = _carregar_registros(argumentos.dataset)
    resultado = gravar_split(registros, destino=argumentos.saida)
    manifesto = carregar_split(argumentos.saida)
    problemas = validar_split(registros, manifesto)

    if argumentos.json:
        print(json.dumps(manifesto, ensure_ascii=False, indent=2))
    elif argumentos.resumo:
        print(
            json.dumps(
                {
                    "total_pares": manifesto["total_pares"],
                    "total_registros": manifesto["total_registros"],
                    "por_split": manifesto["por_split"],
                    "sha256_dataset": manifesto["sha256_dataset"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            f"split={resultado['arquivo']} "
            f"pares={resultado['total_pares']} "
            f"registros={resultado['total_registros']} "
            f"alterado={resultado['alterado']}"
        )

    for problema in problemas:
        print(
            f"split_invalido: {problema['codigo']} "
            f"{problema.get('detalhe', '')}",
            file=sys.stderr,
        )

    return 0 if not problemas else 1


if __name__ == "__main__":
    sys.exit(main())
