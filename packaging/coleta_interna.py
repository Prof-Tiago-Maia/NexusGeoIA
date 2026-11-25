"""Descoberta dos módulos internos que entram no bundle do PyInstaller.

Este módulo é a fonte única da lista de pacotes do projeto (core,
services, ui, adapters e utils) e dos módulos de raiz (config e
setup_llm). Ele é usado em dois lugares:

1. packaging/build_portatil.ps1 executa este arquivo para gerar
   build/modulos_internos.json com um hiddenimport explícito para
   cada .py real do projeto. O equivalente na linha de comando do
   PyInstaller seria --hidden-import para cada módulo descoberto;
   como o build usa um .spec (e o PyInstaller proíbe opções de
   makespec nesse modo), o manifesto é consumido pelo próprio .spec.
2. packaging/assistente.spec lê o manifesto e também chama
   collect_submodules/collect_data_files para cada pacote —
   equivalente a --collect-submodules e --collect-data.

Os testes offline importam montar_manifesto() e comparam o resultado
com os .py que existem no disco, garantindo que nenhum módulo fique
de fora do executável.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Pacotes internos do projeto. A ordem é estável e aparece no log do
# build (--collect-submodules e --collect-data são conferidos para cada
# um deles).
PACOTES_INTERNOS = ("core", "services", "ui", "adapters", "utils")

# Módulos soltos na raiz que o aplicativo importa por nome.
MODULOS_RAIZ = ("config", "setup_llm")

# Pastas de recursos lidas por caminho em tempo de execução. Além de
# irem para _internal pelo .spec, elas são copiadas para a raiz do
# pacote portátil pelo build_portatil.ps1.
DIRETORIOS_DADOS = ("prompts", ".streamlit", "ui", "finetuning")

VERSAO_MANIFESTO = 1


def nome_do_modulo(raiz, arquivo):
    """Converte core/governance.py em core.governance.

    __init__.py representa o próprio pacote (ui/__init__.py -> ui).
    Arquivos dentro de __pycache__ nunca entram.
    """

    relativo = Path(arquivo).resolve().relative_to(Path(raiz).resolve())

    if "__pycache__" in relativo.parts:
        return ""

    partes = list(relativo.with_suffix("").parts)

    if not partes:
        return ""

    if partes[-1] == "__init__":
        partes.pop()

    return ".".join(partes)


def _arquivos_py(raiz, pacote):
    pasta = Path(raiz) / pacote

    if not pasta.is_dir():
        return []

    return sorted(
        arquivo
        for arquivo in pasta.rglob("*.py")
        if "__pycache__" not in arquivo.parts and arquivo.is_file()
    )


def descobrir_modulos(raiz):
    """Lista, sem duplicatas, todos os módulos internos do projeto."""

    raiz = Path(raiz)
    modulos = set(MODULOS_RAIZ)

    for pacote in PACOTES_INTERNOS:
        for arquivo in _arquivos_py(raiz, pacote):
            nome = nome_do_modulo(raiz, arquivo)

            if nome:
                modulos.add(nome)

    return sorted(modulos)


def descobrir_pacotes(raiz):
    """Pacotes internos que existem de fato no projeto."""

    raiz = Path(raiz)

    return [
        pacote
        for pacote in PACOTES_INTERNOS
        if (raiz / pacote).is_dir()
    ]


def descobrir_dados(raiz):
    """Pastas de recursos de runtime presentes no projeto."""

    raiz = Path(raiz)

    return [
        relativo
        for relativo in DIRETORIOS_DADOS
        if (raiz / relativo).is_dir()
    ]


def montar_manifesto(raiz):
    """Monta o manifesto consumido pelo assistente.spec."""

    raiz = Path(raiz).resolve()

    return {
        "versao": VERSAO_MANIFESTO,
        "raiz": str(raiz),
        "pacotes": descobrir_pacotes(raiz),
        "modulos_raiz": list(MODULOS_RAIZ),
        "modulos": descobrir_modulos(raiz),
        "dados": descobrir_dados(raiz),
    }


def validar_manifesto(manifesto, raiz):
    """Confere que o manifesto cobre todos os .py reais do projeto.

    Devolve a lista de módulos ausentes (vazia quando está completo).
    A checagem é a mesma usada pelos testes offline e pelo build.
    """

    esperados = set(descobrir_modulos(raiz))
    presentes = set(manifesto.get("modulos") or [])

    return sorted(esperados - presentes)


def escrever_manifesto(raiz, destino):
    """Grava o manifesto em JSON e devolve o dicionário gravado."""

    manifesto = montar_manifesto(raiz)

    faltando = validar_manifesto(manifesto, raiz)

    if faltando:
        raise RuntimeError(
            "manifesto incompleto; módulos ausentes: " + ", ".join(faltando)
        )

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return manifesto


def main(argv=None):
    """CLI usada pelo build_portatil.ps1.

    Imprime as contagens e grava o manifesto no caminho informado. O
    código de saída é diferente de zero quando a descoberta ou a
    validação falha.
    """

    parser = argparse.ArgumentParser(
        description="Descobre os módulos internos para o PyInstaller."
    )
    parser.add_argument(
        "--raiz",
        default=str(Path(__file__).resolve().parent.parent),
        help="Raiz do projeto (padrão: pasta acima de packaging/).",
    )
    parser.add_argument(
        "--saida",
        default="",
        help="Arquivo JSON de saída (padrão: build/modulos_internos.json).",
    )
    args = parser.parse_args(argv)

    raiz = Path(args.raiz).resolve()
    saida = Path(args.saida) if args.saida else raiz / "build" / "modulos_internos.json"

    try:
        manifesto = escrever_manifesto(raiz, saida)
    except (OSError, RuntimeError) as erro:
        print(f"ERRO: {erro}")
        return 1

    print(f"Pacotes internos: {', '.join(manifesto['pacotes'])}")
    print(f"Módulos explícitos: {len(manifesto['modulos'])}")
    print(f"Dados de runtime: {', '.join(manifesto['dados'])}")
    print(f"Manifesto: {saida}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
