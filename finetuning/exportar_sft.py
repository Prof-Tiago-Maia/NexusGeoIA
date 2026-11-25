"""Exportação SFT dos splits treino/validação do dataset comportamental v2.

O Caminho 2 parte do mesmo gabarito usado no benchmark: cada registro
vira uma conversa de chat com papéis system, user e assistant. O system
prompt e a mensagem do usuário são obtidos diretamente de
finetuning.benchmark (_prompt_sistema e _prompt_usuario), então treino
e avaliação nunca divergem. A resposta do assistente é o
saida_esperada serializado por finetuning.contrato.json_compacto, com
chaves ordenadas e sem espaços.

O split só é aceito depois de finetuning.split.validar_split
recomputar a atribuição e conferir o SHA-256 do dataset. O manifesto
gerado registra os hashes dos dois JSONL, as contagens por split,
tarefa e idioma, e a prova de interseção zero com o split teste
(tanto por id quanto por metadados.par).

Os artefatos são gravados por finetuning.arquivo_seguro, de forma
atômica e idempotente. Nenhum módulo do pacote abre o banco da
aplicação; a guarda DB_INTOCADO continua válida.

Uso::

    ./.venv/Scripts/python.exe -m finetuning.exportar_sft
    ./.venv/Scripts/python.exe -m finetuning.exportar_sft --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from finetuning import arquivo_seguro, benchmark, contrato, gerador, split

PASTA_DATASETS = Path(__file__).resolve().parent / "datasets"
NOME_BASE = "sft_v2"
ARQUIVO_TREINO = PASTA_DATASETS / f"{NOME_BASE}_treino.jsonl"
ARQUIVO_VALIDACAO = PASTA_DATASETS / f"{NOME_BASE}_validacao.jsonl"
ARQUIVO_MANIFESTO = PASTA_DATASETS / f"{NOME_BASE}.manifest.json"

PAPEIS = ("system", "user", "assistant")
SPLITS_EXPORTADOS = ("treino", "validacao")
SPLIT_AVALIACAO = "teste"


def _sha256_bytes(conteudo: bytes) -> str:
    """SHA-256 de um conteúdo já serializado."""

    return hashlib.sha256(conteudo).hexdigest()


def _sha256_arquivo(caminho: Path) -> str:
    """SHA-256 de um arquivo lido em blocos."""

    digest = hashlib.sha256()

    with Path(caminho).open("rb") as aberto:
        for bloco in iter(
            lambda: aberto.read(arquivo_seguro.TAMANHO_BLOCO),
            b"",
        ):
            digest.update(bloco)

    return digest.hexdigest()


def _prompts_do_benchmark():
    """Referências aos construtores de prompt do benchmark.

    O benchmark é a fonte única da verdade do prompt de avaliação. Se
    as funções privadas forem renomeadas, a exportação falha de forma
    explícita em vez de gerar um prompt parecido e silenciosamente
    divergente.
    """

    sistema = getattr(benchmark, "_prompt_sistema", None)
    usuario = getattr(benchmark, "_prompt_usuario", None)

    if not callable(sistema) or not callable(usuario):
        raise TypeError("benchmark_sem_prompts_esperados")

    return sistema, usuario


def montar_exemplo(registro: dict) -> dict:
    """Converte um registro do dataset em uma linha de chat SFT."""

    identificador = registro.get("id")
    tarefa = registro.get("tarefa")
    idioma = "en" if registro.get("idioma") == "en" else "pt"
    par = (registro.get("metadados") or {}).get("par")
    esperado = registro.get("saida_esperada")

    if not identificador or not tarefa or not par:
        raise ValueError(f"registro_incompleto:{identificador}")

    if not isinstance(esperado, dict):
        raise TypeError(f"gabarito_ausente:{identificador}")

    erros = contrato.validar_saida(tarefa, esperado)

    if erros:
        raise ValueError(
            f"gabarito_invalido:{identificador}:{','.join(erros)}"
        )

    sistema, usuario = _prompts_do_benchmark()

    return {
        "id": identificador,
        "tarefa": tarefa,
        "idioma": idioma,
        "par": par,
        "messages": [
            {"role": "system", "content": sistema(idioma)},
            {"role": "user", "content": usuario(registro)},
            {
                "role": "assistant",
                "content": contrato.json_compacto(esperado),
            },
        ],
    }


def serializar_exemplos(exemplos) -> str:
    """JSONL canônico, uma conversa por linha, ordem preservada."""

    exemplos = list(exemplos)

    if not exemplos:
        raise ValueError("exportacao_vazia")

    return "\n".join(
        contrato.json_compacto(exemplo) for exemplo in exemplos
    ) + "\n"


def _contagens(exemplos) -> dict:
    """Contagens determinísticas de registros, pares, tarefa e idioma."""

    exemplos = list(exemplos)

    return {
        "registros": len(exemplos),
        "pares": len({exemplo["par"] for exemplo in exemplos}),
        "por_tarefa": dict(
            sorted(Counter(exemplo["tarefa"] for exemplo in exemplos).items())
        ),
        "por_idioma": dict(
            sorted(Counter(exemplo["idioma"] for exemplo in exemplos).items())
        ),
    }


def _ids_e_pares(itens) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    pares: set[str] = set()

    for item in itens:
        for identificador in item.get("ids") or []:
            ids.add(identificador)

        par = item.get("par")

        if par:
            pares.add(par)

    return ids, pares


def _prova_anti_vazamento(exemplos, manifesto_split) -> dict:
    """Interseção por id e por par entre a exportação e o split teste."""

    itens_teste = [
        item
        for item in manifesto_split.get("pares") or []
        if item.get("split") == SPLIT_AVALIACAO
    ]
    teste_ids, teste_pares = _ids_e_pares(itens_teste)

    exportados = {
        nome: _ids_e_pares(
            [
                {"ids": [exemplo["id"]], "par": exemplo["par"]}
                for exemplo in exemplos[nome]
            ]
        )
        for nome in SPLITS_EXPORTADOS
    }

    interseccao_ids = {
        nome: sorted(exportados[nome][0] & teste_ids)
        for nome in SPLITS_EXPORTADOS
    }
    interseccao_pares = {
        nome: sorted(exportados[nome][1] & teste_pares)
        for nome in SPLITS_EXPORTADOS
    }
    vazou = any(interseccao_ids.values()) or any(
        interseccao_pares.values()
    )

    if vazou:
        raise ValueError(
            "vazamento_split_teste: "
            f"ids={interseccao_ids} pares={interseccao_pares}"
        )

    return {
        "split_avaliacao": SPLIT_AVALIACAO,
        "teste_registros": len(teste_ids),
        "teste_pares": len(teste_pares),
        "ids_intersecao": interseccao_ids,
        "pares_intersecao": interseccao_pares,
        "intersecao_ids": 0,
        "intersecao_pares": 0,
        "ok": True,
    }


def _manifesto_validado(registros, caminho_split) -> dict:
    manifesto = split.carregar_split(caminho_split)
    problemas = split.validar_split(registros, manifesto)

    if problemas:
        detalhes = "; ".join(
            f"{item.get('codigo')}:{item.get('detalhe')}"
            for item in problemas[:5]
        )
        raise ValueError(f"split_invalido: {detalhes}")

    return manifesto


def _impressao_arquivo(caminho: Path, linhas: int, bytes_: bytes) -> dict:
    return {
        "arquivo": Path(caminho).name,
        "linhas": linhas,
        "bytes": len(bytes_),
        "sha256": _sha256_bytes(bytes_),
    }


def gerar_manifesto(
    exemplos,
    manifesto_split,
    arquivos,
    caminho_dataset,
    caminho_split,
) -> dict:
    """Manifesto verificável da exportação SFT."""

    anti_vazamento = _prova_anti_vazamento(exemplos, manifesto_split)
    por_split = {
        nome: _contagens(exemplos[nome]) for nome in SPLITS_EXPORTADOS
    }

    return {
        "nome": NOME_BASE,
        "versao": contrato.VERSAO_DATASET,
        "gerado_por": "finetuning.exportar_sft",
        "formato": {
            "tipo": "chat",
            "papeis": list(PAPEIS),
            "resposta": "finetuning.contrato.json_compacto",
            "prompts": (
                "finetuning.benchmark._prompt_sistema/"
                "_prompt_usuario"
            ),
        },
        "dataset": {
            "arquivo": Path(caminho_dataset).name,
            "sha256": _sha256_arquivo(Path(caminho_dataset)),
            "registros": manifesto_split.get("total_registros"),
            "pares": manifesto_split.get("total_pares"),
        },
        "split": {
            "arquivo": Path(caminho_split).name,
            "sha256": _sha256_arquivo(Path(caminho_split)),
            "sha256_dataset": manifesto_split.get("sha256_dataset"),
            "politica": manifesto_split.get("politica"),
        },
        "arquivos": arquivos,
        "por_split": por_split,
        "anti_vazamento": anti_vazamento,
        "invariantes": {
            "registros_exportados": sum(
                por_split[nome]["registros"] for nome in SPLITS_EXPORTADOS
            ),
            "pares_exportados": sum(
                por_split[nome]["pares"] for nome in SPLITS_EXPORTADOS
            ),
            "sem_vazamento_teste": anti_vazamento["ok"],
        },
    }


def exportar(
    registros=None,
    *,
    destino_treino=None,
    destino_validacao=None,
    destino_manifesto=None,
    caminho_dataset=None,
    caminho_split=None,
    forcar: bool = False,
) -> dict:
    """Gera os JSONL de treino/validação e o manifesto SFT.

    Devolve caminhos, hashes e contagens. Erros de split, gabarito ou
    vazamento levantam ValueError antes de qualquer gravação.
    """

    caminho_dataset = Path(
        caminho_dataset or gerador.ARQUIVO_PADRAO
    )
    caminho_split = Path(caminho_split or split.ARQUIVO_SPLIT)
    destino_treino = Path(destino_treino or ARQUIVO_TREINO)
    destino_validacao = Path(destino_validacao or ARQUIVO_VALIDACAO)
    destino_manifesto = Path(destino_manifesto or ARQUIVO_MANIFESTO)

    registros = (
        list(registros)
        if registros is not None
        else gerador.carregar_registros(caminho_dataset)
    )
    manifesto_split = _manifesto_validado(registros, caminho_split)

    exemplos = {
        nome: [
            montar_exemplo(registro)
            for registro in split.registros_do_split(
                nome,
                registros,
                caminho_split,
            )
        ]
        for nome in SPLITS_EXPORTADOS
    }

    for nome in SPLITS_EXPORTADOS:
        esperado = (
            (manifesto_split.get("por_split") or {}).get(nome) or {}
        ).get("registros")

        if esperado is not None and esperado != len(exemplos[nome]):
            raise ValueError(
                f"contagem_divergente:{nome}:"
                f"manifesto={esperado} exportado={len(exemplos[nome])}"
            )

        if not exemplos[nome]:
            raise ValueError(f"split_vazio:{nome}")

    anti_vazamento = _prova_anti_vazamento(exemplos, manifesto_split)
    textos = {
        nome: serializar_exemplos(exemplos[nome])
        for nome in SPLITS_EXPORTADOS
    }
    bytes_ = {
        nome: textos[nome].encode("utf-8")
        for nome in SPLITS_EXPORTADOS
    }
    arquivos = {
        "treino": _impressao_arquivo(
            destino_treino,
            len(exemplos["treino"]),
            bytes_["treino"],
        ),
        "validacao": _impressao_arquivo(
            destino_validacao,
            len(exemplos["validacao"]),
            bytes_["validacao"],
        ),
    }
    manifesto = gerar_manifesto(
        exemplos,
        manifesto_split,
        arquivos,
        caminho_dataset,
        caminho_split,
    )
    texto_manifesto = (
        json.dumps(
            manifesto,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    alterados = {
        "treino": arquivo_seguro.gravar_texto_atomico(
            destino_treino,
            textos["treino"],
            forcar=forcar,
        ),
        "validacao": arquivo_seguro.gravar_texto_atomico(
            destino_validacao,
            textos["validacao"],
            forcar=forcar,
        ),
        "manifesto": arquivo_seguro.gravar_texto_atomico(
            destino_manifesto,
            texto_manifesto,
            forcar=forcar,
        ),
    }

    return {
        "treino": {
            **arquivos["treino"],
            "caminho": str(destino_treino),
            "alterado": alterados["treino"],
        },
        "validacao": {
            **arquivos["validacao"],
            "caminho": str(destino_validacao),
            "alterado": alterados["validacao"],
        },
        "manifesto": {
            "caminho": str(destino_manifesto),
            "sha256": _sha256_bytes(texto_manifesto.encode("utf-8")),
            "alterado": alterados["manifesto"],
        },
        "anti_vazamento": anti_vazamento,
        "por_split": manifesto["por_split"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exporta os splits treino/validação do dataset v2 no "
            "formato chat SFT."
        ),
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--split", type=Path, default=split.ARQUIVO_SPLIT)
    parser.add_argument("--treino", type=Path, default=ARQUIVO_TREINO)
    parser.add_argument(
        "--validacao",
        type=Path,
        default=ARQUIVO_VALIDACAO,
    )
    parser.add_argument(
        "--manifesto",
        type=Path,
        default=ARQUIVO_MANIFESTO,
    )
    parser.add_argument("--forcar", action="store_true")
    parser.add_argument("--json", action="store_true")
    argumentos = parser.parse_args(argv)

    try:
        resultado = exportar(
            destino_treino=argumentos.treino,
            destino_validacao=argumentos.validacao,
            destino_manifesto=argumentos.manifesto,
            caminho_dataset=argumentos.dataset,
            caminho_split=argumentos.split,
            forcar=argumentos.forcar,
        )
    except (OSError, ValueError, RuntimeError, TypeError) as erro:
        print(f"exportacao_sft_invalida: {erro}", file=sys.stderr)
        return 2

    if argumentos.json:
        print(
            json.dumps(resultado, ensure_ascii=False, indent=2),
        )
        return 0

    for nome in SPLITS_EXPORTADOS:
        item = resultado[nome]
        print(
            f"sft_{nome}={item['caminho']} "
            f"linhas={item['linhas']} sha256={item['sha256']} "
            f"alterado={item['alterado']}"
        )

    anti = resultado["anti_vazamento"]
    print(
        f"manifesto={resultado['manifesto']['caminho']} "
        f"sha256={resultado['manifesto']['sha256']} "
        f"alterado={resultado['manifesto']['alterado']}"
    )
    print(
        f"teste_registros={anti['teste_registros']} "
        f"teste_pares={anti['teste_pares']} "
        f"intersecao_ids={anti['intersecao_ids']} "
        f"intersecao_pares={anti['intersecao_pares']}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
