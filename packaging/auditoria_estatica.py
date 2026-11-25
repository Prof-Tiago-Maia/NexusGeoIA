"""Auditoria estatica offline do NexusGeo IA.

Executa, sem abrir a interface, sem rede e sem importar o projeto:

1. compilacao de todos os ``.py`` versionaveis (fora de ``.venv``,
   ``build``, ``dist``, caches e testes temporarios), equivalente ao
   ``py_compile`` mas sem escrever ``.pyc`` no repositorio;
2. leitura AST dos imports de nivel de modulo para montar o grafo
   interno e detectar **imports circulares de importacao** (imports
   locais dentro de funcoes sao deliberadamente ignorados: eles existem
   justamente para quebrar ciclos em tempo de carga);
3. verificacao de imports internos que apontam para modulos
   inexistentes (o erro que so aparece no PyInstaller ou no primeiro
   uso);
4. aviso de imports de nivel de modulo sem uso aparente.

O codigo de saida e 0 quando compilacao, imports internos e ciclos
estao limpos. Avisos de import nao usado nao reprovam por padrao; use
``--falhar-avisos`` para transforma-los em erro. Variaveis nao usadas e
redefinicoes ficam a cargo do ``ruff`` (F401/F811/F821/F841), que tem
analise semantica mais precisa; o protocolo da skill
``qa-windows-release`` documenta a linha de base.

Uso:
    .\\.venv\\Scripts\\python.exe packaging\\auditoria_estatica.py
    .\\.venv\\Scripts\\python.exe packaging\\auditoria_estatica.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Pastas que nunca entram na auditoria: ambiente virtual, artefatos de
# build/distribuicao, caches, controle de versao e testes temporarios.
PASTAS_EXCLUIDAS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".dsh",
}

# Pacotes internos do projeto. Um import que comece por um destes nomes
# precisa resolver para um modulo realmente existente.
PACOTES_INTERNOS = {"adapters", "app", "config", "core", "database",
                    "finetuning", "launcher_desktop", "services",
                    "setup_llm", "ui", "utils"}


def _caminho_relativo(raiz: Path, caminho: Path) -> Path:
    return caminho.relative_to(raiz)


def _deve_ignorar(caminho: Path, raiz: Path) -> bool:
    relativo = _caminho_relativo(raiz, caminho)

    if any(parte in PASTAS_EXCLUIDAS for parte in relativo.parts):
        return True

    # tests/_tmp_* guarda fixtures efemeras dos testes.
    return any(
        parte.startswith("_tmp") for parte in relativo.parts
    )


def listar_python(raiz: Path) -> list[Path]:
    """Lista os ``.py`` auditaveis em ordem deterministica."""

    arquivos = []

    for caminho in raiz.rglob("*.py"):
        if caminho.is_file() and not _deve_ignorar(caminho, raiz):
            arquivos.append(caminho)

    return sorted(arquivos)


def modulo_de(raiz: Path, caminho: Path) -> str:
    """Converte ``core/assistant.py`` em ``core.assistant``."""

    partes = list(_caminho_relativo(raiz, caminho).with_suffix("").parts)

    if partes and partes[-1] == "__init__":
        partes.pop()

    return ".".join(partes)


def compilar(arquivos: list[Path]) -> list[dict]:
    """Compila cada arquivo em memoria e devolve as falhas encontradas.

    ``compile()`` faz a mesma checagem de sintaxe do ``py_compile`` sem
    escrever ``.pyc``: a auditoria nao altera ``__pycache__`` do
    repositorio e nao falha quando essa pasta estiver bloqueada por
    permissao (sandbox, antivirus ou ACL).
    """

    falhas = []

    for caminho in arquivos:
        try:
            origem = caminho.read_text(encoding="utf-8")
            compile(origem, str(caminho), "exec")
        except (OSError, SyntaxError, UnicodeDecodeError) as erro:
            detalhe = (
                f"{type(erro).__name__}: {erro}"
                if not isinstance(erro, SyntaxError)
                else f"SyntaxError: {erro.msg} (linha {erro.lineno})"
            )
            falhas.append({
                "arquivo": str(caminho),
                "erro": detalhe,
            })

    return falhas


def _resolver_base_relativa(modulo: str, node: ast.ImportFrom) -> str:
    """Resolve ``from .x``/``from ..x`` para o nome absoluto."""

    base = node.module or ""

    if not node.level:
        return base

    partes = modulo.split(".")

    # Em ``pacote/__init__.py`` o modulo atual e o proprio pacote; nos
    # demais arquivos o ponto de partida e o pacote que os contem.
    if modulo.endswith(".__init__") or not partes:
        pacote = partes[:-1]
    else:
        pacote = partes[:-1]

    subir = node.level - 1

    if subir > 0:
        pacote = pacote[:-subir] if subir <= len(pacote) else []

    if base:
        pacote = pacote + base.split(".")

    return ".".join(pacote)


def _alvos_do_import(node: ast.AST, modulo: str) -> set[str]:
    """Nomes de modulo que um import de nivel de modulo referencia."""

    alvos: set[str] = set()

    if isinstance(node, ast.Import):
        for alias in node.names:
            alvos.add(alias.name)
        return alvos

    if isinstance(node, ast.ImportFrom):
        base = _resolver_base_relativa(modulo, node)

        if base:
            alvos.add(base)

        for alias in node.names:
            if alias.name != "*" and base:
                alvos.add(f"{base}.{alias.name}")

    return alvos


def _nomes_importados(arvore: ast.Module) -> dict[str, str]:
    """Nomes ligados por imports de nivel de modulo e sua origem."""

    nomes: dict[str, str] = {}

    for node in arvore.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                ligado = alias.asname or alias.name.split(".")[0]
                nomes[ligado] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue

            for alias in node.names:
                if alias.name == "*":
                    continue

                ligado = alias.asname or alias.name
                nomes[ligado] = f"{node.module or '.'}.{alias.name}"

    return nomes


def _nomes_usados(arvore: ast.Module) -> set[str]:
    """Nomes lidos no modulo, incluindo ``__all__`` explicito."""

    usados: set[str] = set()

    for node in ast.walk(arvore):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            usados.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Nao ha como saber aqui se a string e __all__; incluir todos
            # os literais deixa o aviso conservador (menos falso positivo).
            usados.add(node.value)

    return usados


def analisar_imports(
    raiz: Path,
    arquivos: list[Path],
) -> tuple[dict[str, set[str]], dict[str, Path], list[dict], list[dict]]:
    """Monta o grafo de imports de nivel de modulo.

    Devolve ``(grafo, modulos, imports_quebrados, avisos)``.
    """

    modulos: dict[str, Path] = {}
    arvores: dict[str, ast.Module] = {}

    for caminho in arquivos:
        modulo = modulo_de(raiz, caminho)
        modulos[modulo] = caminho

        try:
            arvores[modulo] = ast.parse(
                caminho.read_text(encoding="utf-8"),
                filename=str(caminho),
            )
        except (OSError, SyntaxError, UnicodeDecodeError):
            # py_compile ja reporta o erro; o grafo apenas ignora o
            # arquivo para nao duplicar a falha.
            continue

    grafo: dict[str, set[str]] = {modulo: set() for modulo in modulos}
    quebrados: list[dict] = []
    avisos: list[dict] = []

    for modulo, arvore in arvores.items():
        importados = _nomes_importados(arvore)
        usados = _nomes_usados(arvore)

        for nome, origem in sorted(importados.items()):
            if nome.startswith("_") or nome in usados:
                continue

            avisos.append({
                "modulo": modulo,
                "nome": nome,
                "origem": origem,
                "aviso": "import de nivel de modulo sem uso aparente",
            })

        for node in arvore.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            # Grafo: qualquer alvo que exista vira aresta. Atributos de
            # "from x import y" so entram quando y e um submodulo real.
            for alvo in sorted(_alvos_do_import(node, modulo)):
                if alvo in modulos and alvo != modulo:
                    grafo[modulo].add(alvo)

            # Imports quebrados: apenas o modulo-base de cada declaracao.
            # "from services.x import funcao" referencia o modulo
            # services.x; "funcao" e atributo, nao um modulo.
            candidatos: list[str] = []

            if isinstance(node, ast.Import):
                candidatos = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _resolver_base_relativa(modulo, node)

                if base:
                    candidatos = [base]

            for alvo in candidatos:
                if not alvo or alvo in modulos:
                    continue

                raiz_alvo = alvo.split(".")[0]

                if raiz_alvo not in PACOTES_INTERNOS:
                    continue

                if "." not in alvo and any(
                    existente.startswith(alvo + ".")
                    for existente in modulos
                ):
                    # Namespace package ou pacote sem __init__.py.
                    continue

                quebrados.append({
                    "modulo": modulo,
                    "import": alvo,
                    "arquivo": str(modulos.get(modulo, "")),
                })

    return grafo, modulos, quebrados, avisos


def detectar_ciclos(grafo: dict[str, set[str]]) -> list[list[str]]:
    """Devolve todos os ciclos do grafo, sem repetir o mesmo ciclo."""

    estado: dict[str, int] = {}
    pilha: list[str] = []
    ciclos: list[list[str]] = []
    vistos: set[tuple[str, ...]] = set()

    def visitar(modulo: str) -> None:
        estado[modulo] = 1
        pilha.append(modulo)

        for vizinho in sorted(grafo.get(modulo, ())):
            if estado.get(vizinho, 0) == 0:
                visitar(vizinho)
            elif estado.get(vizinho) == 1:
                inicio = pilha.index(vizinho)
                ciclo = pilha[inicio:] + [vizinho]

                # Normaliza a rotacao para deduplicar o mesmo ciclo.
                corpo = ciclo[:-1]
                menor = min(range(len(corpo)), key=lambda i: corpo[i])
                canonico = tuple(corpo[menor:] + corpo[:menor])

                if canonico not in vistos:
                    vistos.add(canonico)
                    ciclos.append(ciclo)

        pilha.pop()
        estado[modulo] = 2

    for modulo in sorted(grafo):
        if estado.get(modulo, 0) == 0:
            visitar(modulo)

    return ciclos


def executar(raiz: Path, falhar_avisos: bool = False) -> dict:
    """Executa a auditoria e devolve o relatorio serializavel."""

    arquivos = listar_python(raiz)
    falhas_compilacao = compilar(arquivos)
    grafo, modulos, quebrados, avisos = analisar_imports(raiz, arquivos)
    ciclos = detectar_ciclos(grafo)

    aprovado = not falhas_compilacao and not quebrados and not ciclos

    if falhar_avisos and avisos:
        aprovado = False

    return {
        "ok": aprovado,
        "raiz": str(raiz),
        "arquivos": len(arquivos),
        "modulos": len(modulos),
        "falhas_compilacao": falhas_compilacao,
        "imports_quebrados": quebrados,
        "ciclos": ciclos,
        "avisos": avisos,
    }


def imprimir(relatorio: dict, verboso: bool) -> None:
    """Imprime o relatorio objetivo em pt-BR."""

    print("=" * 60)
    print(" AUDITORIA ESTATICA - NexusGeo IA")
    print("=" * 60)
    print(f"Raiz: {relatorio['raiz']}")
    print(f"Arquivos .py: {relatorio['arquivos']}")
    print(f"Modulos internos: {relatorio['modulos']}")
    print()

    if relatorio["falhas_compilacao"]:
        print(f"[FAIL] compilacao: {len(relatorio['falhas_compilacao'])} falha(s)")

        for falha in relatorio["falhas_compilacao"]:
            print(f"  - {falha['arquivo']}: {falha['erro']}")
    else:
        print("[PASS] compilacao de todos os .py versionaveis")

    if relatorio["imports_quebrados"]:
        print(f"[FAIL] imports internos quebrados: {len(relatorio['imports_quebrados'])}")

        for item in relatorio["imports_quebrados"]:
            print(f"  - {item['modulo']}: {item['import']}")
    else:
        print("[PASS] imports internos resolvem para modulos existentes")

    if relatorio["ciclos"]:
        print(f"[FAIL] imports circulares: {len(relatorio['ciclos'])}")

        for ciclo in relatorio["ciclos"]:
            print("  - " + " -> ".join(ciclo))
    else:
        print("[PASS] nenhum import circular de nivel de modulo")

    if relatorio["avisos"]:
        print(f"[AVISO] imports sem uso aparente: {len(relatorio['avisos'])}")

        if verboso:
            for aviso in relatorio["avisos"]:
                print(
                    f"  - {aviso['modulo']}: {aviso['nome']} "
                    f"(de {aviso['origem']})"
                )
        else:
            print("  Use --verboso para listar.")
    else:
        print("[PASS] nenhum import de nivel de modulo sem uso aparente")

    print()
    print(f"RESULTADO: {'PASS' if relatorio['ok'] else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auditoria estatica offline do NexusGeo IA.",
    )
    parser.add_argument(
        "--raiz",
        default=str(Path(__file__).resolve().parent.parent),
        help="Raiz do projeto (padrao: pasta pai de packaging/).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime o relatorio em JSON.",
    )
    parser.add_argument(
        "--verboso",
        action="store_true",
        help="Lista cada aviso de import sem uso.",
    )
    parser.add_argument(
        "--falhar-avisos",
        action="store_true",
        help="Reprova tambem quando houver import sem uso aparente.",
    )

    args = parser.parse_args(argv)
    raiz = Path(args.raiz).resolve()

    if not raiz.is_dir():
        print(f"Raiz invalida: {raiz}", file=sys.stderr)
        return 2

    relatorio = executar(raiz, falhar_avisos=args.falhar_avisos)

    if args.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        imprimir(relatorio, args.verboso)

    return 0 if relatorio["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
