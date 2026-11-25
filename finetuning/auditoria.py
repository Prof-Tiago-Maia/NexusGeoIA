r"""Auditoria estática do pacote de fine-tuning e do dataset.

Executa quatro verificações independentes:

1. AST dos módulos de finetuning (imports proibidos, eval/exec, referência
   textual ao banco fora do módulo de guarda);
2. contrato, unicidade e paridade bilíngue do JSONL;
3. integridade e atualidade do split treino/validação/teste;
4. guarda SHA-256 do banco real antes/depois (DB_INTOCADO).

Uso::

    .\.venv\Scripts\python.exe -m finetuning.auditoria
    .\.venv\Scripts\python.exe -m finetuning.auditoria --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finetuning import arquivo_seguro, gerador, seguranca, split

PASTA_RELATORIOS = Path(__file__).resolve().parent / "relatorios"


def executar_auditoria(caminho_dataset=None, caminho_split=None) -> dict:
    """Executa a auditoria completa e devolve o relatório.

    A auditoria é somente leitura sobre os artefatos e o banco real: duas
    execuções com os mesmos arquivos devolvem o mesmo relatório (sem
    carimbo de tempo), o que a torna idempotente e comparável entre
    revisões.

    Além do dataset, confere o split treino/validação/teste: hash do
    dataset, cobertura de todos os registros e atribuição recomputada.
    Um split ausente, velho ou com par dividido entre conjuntos reprova
    a auditoria.
    """

    antes = seguranca.capturar_banco()
    problemas = []
    registros = None

    try:
        registros = gerador.carregar_registros(caminho_dataset)
    except (OSError, ValueError) as erro:
        problemas.append(
            {
                "linha": 0,
                "id": "dataset",
                "codigo": "dataset_invalido",
                "detalhe": str(erro),
            }
        )

    relatorio = seguranca.auditar_pacote(registros or [])
    problemas_split = []
    resumo_split = None

    if registros is not None:
        try:
            manifesto = split.carregar_split(caminho_split)
        except (OSError, ValueError) as erro:
            problemas_split.append(
                {
                    "linha": 0,
                    "id": "split",
                    "codigo": "split_invalido",
                    "detalhe": str(erro),
                }
            )
        else:
            for problema in split.validar_split(registros, manifesto):
                problemas_split.append(
                    {
                        "linha": 0,
                        "id": "split",
                        "codigo": problema["codigo"],
                        "detalhe": problema.get("detalhe", ""),
                    }
                )

            resumo_split = {
                "total_pares": manifesto.get("total_pares"),
                "total_registros": manifesto.get("total_registros"),
                "por_split": manifesto.get("por_split"),
            }

    relatorio["split"] = resumo_split
    relatorio["problemas_dataset"].extend(problemas)
    relatorio["problemas_dataset"].extend(problemas_split)
    relatorio["ok"] = (
        not relatorio["achados_codigo"]
        and not relatorio["problemas_dataset"]
    )

    depois = seguranca.capturar_banco()
    banco = seguranca.comparar_banco(antes, depois)
    relatorio["db"] = banco
    relatorio["db_intocado"] = banco["DB_INTOCADO"]

    return relatorio


def _escrever(relatorio: dict, caminho: Path) -> None:
    """Grava o relatório em temporário e troca de forma atômica."""

    arquivo_seguro.gravar_texto_atomico(
        caminho,
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Audita o pacote de fine-tuning e o dataset.",
    )
    parser.add_argument("--dataset", type=Path, default=gerador.ARQUIVO_PADRAO)
    parser.add_argument("--split", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--saida", type=Path, default=None)
    argumentos = parser.parse_args(argv)

    relatorio = executar_auditoria(
        Path(argumentos.dataset),
        argumentos.split,
    )
    erro_saida = None

    if argumentos.saida:
        try:
            _escrever(relatorio, Path(argumentos.saida))
        except OSError as erro:
            # Falha de escrita é reportada como etapa explícita; o
            # relatório continua sendo impresso na saída padrão.
            erro_saida = erro
            print(
                "Falha ao gravar o relatório em "
                f"{argumentos.saida}: {erro}",
                file=sys.stderr,
            )

    if argumentos.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        print(
            f"auditoria_ok={relatorio['ok']} "
            f"registros={relatorio['total_registros']} "
            f"achados_codigo={len(relatorio['achados_codigo'])} "
            f"problemas_dataset={len(relatorio['problemas_dataset'])}"
        )

    print(f"DB_INTOCADO={relatorio['db_intocado']}")

    if erro_saida is not None:
        return 1

    return 0 if relatorio["ok"] and relatorio["db_intocado"] else 1


if __name__ == "__main__":
    sys.exit(main())
