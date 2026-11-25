"""Guarda de integridade do banco real durante a suíte (D2 -> D3).

O ``data/nexusgeoia.db`` é estado local do usuário: a suíte de testes
não pode criar, migrar nem atualizar esse arquivo. Este módulo fornece
uma verificação real por SHA-256 e tamanho em bytes, usada por três
caminhos complementares:

1. no import do pacote ``tests``, um ``atexit`` compara a impressão
   capturada no início com a do fim do processo, grava o relatório e
   imprime ``DB_INTOCADO=True/False``. O callback apenas registra o
   veredito: ele não encerra o processo à força, para não interromper
   outros hooks de finalização nem o encerramento normal do runner;
2. ao executar este arquivo como script, ele roda a suíte completa em
   um subprocesso, compara antes/depois e devolve código de saída 1
   quando a guarda ou a suíte reprovam;
3. os testes de empacotamento reutilizam :func:`capturar` e
   :func:`comparar` para provar que ``launcher_desktop.autoteste()``
   não altera o banco real.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO_REAL = RAIZ / "data" / "nexusgeoia.db"
PASTA_RELATORIOS = RAIZ / "build" / "_tmp_db_guard"
ARQUIVO_RELATORIO = PASTA_RELATORIOS / "relatorio_db_intocado.json"

_GUARDA_REGISTRADA = False
_IMPRESSAO_INICIAL = None
_RESULTADO_FINAL = None


def capturar(caminho=None):
    """Impressão SHA-256 e tamanho em bytes do banco indicado."""

    alvo = Path(caminho or BANCO_REAL)

    if not alvo.is_file():
        return {
            "caminho": str(alvo),
            "existe": False,
            "tamanho": None,
            "sha256": None,
        }

    digest = hashlib.sha256()

    with alvo.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)

    return {
        "caminho": str(alvo),
        "existe": True,
        "tamanho": alvo.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def comparar(antes, depois):
    """Compara duas impressões e devolve o veredito ``DB_INTOCADO``."""

    antes = antes or {}
    depois = depois or {}
    mesmo_tamanho = antes.get("tamanho") == depois.get("tamanho")
    mesmo_hash = antes.get("sha256") == depois.get("sha256")
    mesma_existencia = bool(antes.get("existe")) == bool(
        depois.get("existe")
    )
    intocado = bool(mesma_existencia and mesmo_tamanho and mesmo_hash)

    return {
        "antes": antes,
        "depois": depois,
        "mesma_existencia": mesma_existencia,
        "mesmo_tamanho": mesmo_tamanho,
        "mesmo_sha256": mesmo_hash,
        "intocado": intocado,
        "DB_INTOCADO": intocado,
    }


def _gravar(relatorio):
    """Grava o relatório de guarda, criando a pasta quando necessário."""

    PASTA_RELATORIOS.mkdir(parents=True, exist_ok=True)
    ARQUIVO_RELATORIO.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return ARQUIVO_RELATORIO


def finalizar_guarda(origem="final_da_suite"):
    """Compara a impressão atual com a inicial e registra o veredito.

    Devolve o relatório e nunca encerra o processo. O código de saída é
    responsabilidade de :func:`executar_suite` (fluxo normal da guarda)
    ou do runner que consultar :func:`falha_de_integridade`. Assim a
    falha aparece no relatório e nos testes seguintes sem matar o
    interpretador no meio de outros hooks de ``atexit``.
    """

    global _RESULTADO_FINAL

    if _IMPRESSAO_INICIAL is None:
        raise RuntimeError(
            "a guarda do banco não foi registrada antes da finalização"
        )

    resultado = comparar(_IMPRESSAO_INICIAL, capturar())
    resultado["origem"] = origem
    resultado["executado_em"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    try:
        caminho = _gravar(resultado)
    except OSError as erro:
        # build/ pode estar bloqueado no sandbox: o veredito continua
        # válido pelo stdout e pelo estado do módulo.
        caminho = None
        resultado["erro_relatorio"] = f"{type(erro).__name__}: {erro}"
        print(
            f"AVISO: não foi possível gravar o relatório da guarda: {erro}",
            file=sys.stderr,
            flush=True,
        )

    resultado["relatorio"] = str(caminho) if caminho is not None else None
    _RESULTADO_FINAL = resultado

    if caminho is not None:
        print(
            f"DB_INTOCADO={resultado['intocado']} "
            f"(relatorio: {caminho})",
            flush=True,
        )
    else:
        print(f"DB_INTOCADO={resultado['intocado']}", flush=True)

    if not resultado["intocado"]:
        print(
            "O banco real data/nexusgeoia.db foi alterado durante a "
            "suíte; veja o relatório para comparar hash/tamanho e "
            "execute 'python -B tests/_db_intocado.py' para obter o "
            "código de saída 1.",
            file=sys.stderr,
            flush=True,
        )

    return resultado


def resultado_final():
    """Último veredito registrado pela guarda, ou ``None``."""

    return _RESULTADO_FINAL


def falha_de_integridade():
    """Indica se o último veredito registrado reprovou a guarda."""

    return _RESULTADO_FINAL is not None and not _RESULTADO_FINAL["intocado"]


def _finalizar_no_encerramento():
    """Callback de ``atexit``: registra o veredito sem derrubar o processo."""

    try:
        finalizar_guarda()
    except Exception as erro:  # noqa: BLE001 - shutdown nunca deve falhar
        print(
            "AVISO: não foi possível concluir a guarda do banco: "
            f"{type(erro).__name__}: {erro}",
            file=sys.stderr,
            flush=True,
        )


def registrar_guarda_de_ambiente():
    """Registra a guarda de fim de processo para a suíte em andamento."""

    global _GUARDA_REGISTRADA, _IMPRESSAO_INICIAL

    if _GUARDA_REGISTRADA:
        return

    _GUARDA_REGISTRADA = True
    _IMPRESSAO_INICIAL = capturar()
    atexit.register(_finalizar_no_encerramento)


def executar_suite(argumentos=None):
    """Roda a suíte completa e comprova que o banco real não mudou."""

    extras = list(argumentos or [])
    comando = [sys.executable, "-m", "unittest"]
    comando.extend(extras or ["discover", "-s", "tests", "-v"])

    antes = capturar()
    processo = subprocess.run(comando, cwd=RAIZ, check=False)
    depois = capturar()

    resultado = comparar(antes, depois)
    resultado["origem"] = "suite_completa"
    resultado["comando"] = comando
    resultado["codigo_suite"] = processo.returncode
    resultado["executado_em"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    try:
        caminho = _gravar(resultado)
    except OSError as erro:
        caminho = None
        resultado["erro_relatorio"] = f"{type(erro).__name__}: {erro}"
        print(
            f"AVISO: não foi possível gravar o relatório da guarda: {erro}",
            file=sys.stderr,
            flush=True,
        )

    resultado["relatorio"] = str(caminho) if caminho is not None else None

    print(
        f"DB_INTOCADO={resultado['intocado']} "
        f"(antes: {antes.get('sha256')}, depois: {depois.get('sha256')}, "
        f"relatorio: {caminho})",
        flush=True,
    )

    if not resultado["intocado"]:
        print(
            "A guarda reprovou: o banco real mudou de existência, "
            "tamanho ou SHA-256 durante a suíte.",
            file=sys.stderr,
            flush=True,
        )

    if processo.returncode != 0:
        print(
            f"A suíte de testes reprovou (código {processo.returncode}).",
            file=sys.stderr,
            flush=True,
        )

    return 0 if resultado["intocado"] and processo.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(executar_suite(sys.argv[1:]))
