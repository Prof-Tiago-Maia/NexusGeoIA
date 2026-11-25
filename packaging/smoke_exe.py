"""Smoke test real do executável compilado (NexusGeoIA.exe --self-test).

Este script é a etapa obrigatória do build_portatil.ps1: executa o
binário gerado em modo de autodiagnóstico, lê o relatório JSON gravado
em ASSISTENTE_SELFTEST_REPORT e reprova o build quando qualquer
verificação falha. O executável é console=False; o relatório em disco é
o canal de saída do teste (o stdout pode nem existir).

Uso:

    python packaging/smoke_exe.py --exe dist/NexusGeoIA/NexusGeoIA.exe

Código de saída 0 somente quando todas as verificações obrigatórias
passam. Não abre navegador, servidor nem janela.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Verificações que o --self-test do launcher precisa produzir.
VERIFICACOES_OBRIGATORIAS = (
    "recursos_runtime",
    "modulos_internos",
    "banco_sqlite_wal",
    "modelo_oficial",
    "app_py_dry_run",
)

# Verificações extras que também devem constar no relatório.
VERIFICACOES_RECOMENDADAS = ("certificados",)


def validar_relatorio(dados):
    """Valida o JSON do self-test e devolve a lista de problemas."""

    problemas = []

    if not isinstance(dados, dict):
        return ["relatório não é um objeto JSON"]

    if dados.get("ok") is not True:
        problemas.append(f"ok diferente de true: {dados.get('ok')!r}")

    if dados.get("concluido") is not True:
        problemas.append(
            f"concluido diferente de true: {dados.get('concluido')!r}"
        )

    falhas = dados.get("falhas") or []

    if falhas:
        problemas.append("falhas: " + "; ".join(str(item) for item in falhas))

    verificacoes = dados.get("verificacoes") or []
    nomes = set()

    for verificacao in verificacoes:
        if not isinstance(verificacao, dict):
            problemas.append("verificação inválida no relatório")
            continue

        nome = str(verificacao.get("nome") or "")
        nomes.add(nome)

        if verificacao.get("ok") is not True:
            problemas.append(
                f"{nome}: {verificacao.get('erro') or 'reprovada'}"
            )

    for obrigatoria in VERIFICACOES_OBRIGATORIAS:
        if obrigatoria not in nomes:
            problemas.append(f"verificação obrigatória ausente: {obrigatoria}")

    for recomendada in VERIFICACOES_RECOMENDADAS:
        if recomendada not in nomes:
            problemas.append(f"verificação esperada ausente: {recomendada}")

    return problemas


def _ambiente_do_self_test(dados_dir):
    """Ambiente isolado: nenhum dado do usuário é tocado."""

    ambiente = dict(os.environ)
    ambiente["ASSISTENTE_DATA_DIR"] = str(dados_dir)
    ambiente.pop("NEXUSGEO_DB_PATH", None)
    ambiente.pop("NEXUSGEO_TEST_MODE", None)

    return ambiente


def executar_self_test(exe, relatorio, timeout=1800, dados_dir=None):
    """Executa o .exe com --self-test e devolve (codigo, relatorio_json)."""

    exe = Path(exe).resolve()
    relatorio = Path(relatorio).resolve()

    if not exe.is_file():
        return 1, {"falhas": [f"executável ausente: {exe}"]}

    if relatorio.is_file():
        relatorio.unlink()

    temporario = None

    if dados_dir is None:
        temporario = Path(tempfile.mkdtemp(prefix="nexusgeo_smoke_"))
        dados_dir = temporario

    dados_dir = Path(dados_dir)
    dados_dir.mkdir(parents=True, exist_ok=True)

    ambiente = _ambiente_do_self_test(dados_dir)
    ambiente["ASSISTENTE_SELFTEST_REPORT"] = str(relatorio)

    argumentos = [str(exe), "--self-test"]
    criacao = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    inicio = time.monotonic()
    duracao = 0.0

    try:
        processo = subprocess.run(
            argumentos,
            cwd=str(exe.parent),
            env=ambiente,
            timeout=timeout,
            creationflags=criacao,
            check=False,
        )
        codigo = int(processo.returncode)
    except subprocess.TimeoutExpired:
        codigo = -2
    except OSError as erro:
        return 1, {
            "falhas": [f"não foi possível executar {exe}: {erro}"],
        }
    except Exception as erro:  # noqa: BLE001 - falha do próprio smoke
        return 1, {
            "falhas": [f"erro inesperado ao executar {exe}: {erro}"],
        }
    finally:
        duracao = time.monotonic() - inicio

        if temporario is not None:
            shutil.rmtree(temporario, ignore_errors=True)

    dados = {}

    if relatorio.is_file():
        try:
            dados = json.loads(relatorio.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erro:
            dados = {"falhas": [f"relatório ilegível: {erro}"]}

    dados["_codigo"] = codigo
    dados["_duracao_s"] = round(duracao, 1)

    if codigo == -2:
        dados.setdefault("falhas", []).append(
            f"self-test excedeu {timeout} s e foi encerrado"
        )

    return codigo, dados


def main(argv=None):
    """CLI do smoke test; devolve 0 somente com todas as verificações OK."""

    parser = argparse.ArgumentParser(
        description="Executa NexusGeoIA.exe --self-test e valida o relatório."
    )
    parser.add_argument("--exe", required=True, help="Caminho do .exe gerado.")
    parser.add_argument(
        "--relatorio",
        default="build/self_test.json",
        help="Arquivo JSON de saída do self-test.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Tempo máximo em segundos (padrão: 1800).",
    )
    parser.add_argument(
        "--dados",
        default="",
        help="Pasta de dados descartável (padrão: temporário do sistema).",
    )
    args = parser.parse_args(argv)

    codigo, dados = executar_self_test(
        args.exe,
        args.relatorio,
        timeout=args.timeout,
        dados_dir=Path(args.dados) if args.dados else None,
    )

    problemas = validar_relatorio(dados) if codigo == 0 else [
        f"o executável devolveu código {codigo}",
    ]

    if codigo == 0 and not problemas:
        print("Self-test do executável: OK")

        for verificacao in dados.get("verificacoes") or []:
            print(f"  OK: {verificacao.get('nome')}")

        return 0

    print("Self-test do executável: FALHOU", file=sys.stderr)

    for problema in problemas:
        print(f"  - {problema}", file=sys.stderr)

    for falha in dados.get("falhas") or []:
        print(f"  falha: {falha}", file=sys.stderr)

    if dados.get("traceback"):
        print(dados["traceback"], file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
