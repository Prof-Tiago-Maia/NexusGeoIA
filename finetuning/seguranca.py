"""Guarda do banco real e auditoria estática do pacote de fine-tuning.

O benchmark nunca abre data/nexusgeoia.db. Para provar isso, este módulo
captura SHA-256 e tamanho do banco e dos arquivos auxiliares (-wal e
-shm) antes e depois da execução. A comparação produz o veredito
DB_INTOCADO.

A auditoria estática percorre a AST dos módulos de finetuning e recusa
imports proibidos (sqlite3, database, serviços de persistência,
streamlit), chamadas dinâmicas (eval/exec/compile/__import__) e
referências textuais ao banco fora do próprio módulo de guarda.

O caminho do banco é resolvido como no restante do projeto
(NEXUSGEO_DB_PATH, ASSISTENTE_DATA_DIR e config.DATA_DIR), com fallback
para raiz/data/nexusgeoia.db.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

from finetuning import contrato

RAIZ = Path(__file__).resolve().parent.parent
PASTA_PACOTE = Path(__file__).resolve().parent
BANCO_FALLBACK = RAIZ / "data" / "nexusgeoia.db"
ARQUIVO_BANCO = "nexusgeoia.db"


def _normalizar(caminho) -> Path:
    """Caminho absoluto, expandindo ~ e resolvendo links simbólicos."""

    return Path(caminho).expanduser().resolve()


def _resolver_banco_real() -> tuple[Path, str]:
    """Resolve o banco de produção com a mesma precedência do projeto.

    A ordem é a de services/history_db.caminho_banco: variável
    explícita NEXUSGEO_DB_PATH > config.DATA_DIR (que já aplica
    ASSISTENTE_DATA_DIR sobre o diretório padrão) > fallback para a
    raiz do repositório. O fallback só é usado quando o módulo config
    não pode ser importado, por exemplo em uma cópia isolada do pacote.
    """

    explicito = os.getenv("NEXUSGEO_DB_PATH", "").strip()

    if explicito:
        return _normalizar(explicito), "NEXUSGEO_DB_PATH"

    try:
        from config import DATA_DIR
    except Exception:  # noqa: BLE001 - pacote pode rodar sem o projeto
        data_dir = None
    else:
        data_dir = Path(DATA_DIR)

    if data_dir is not None:
        configurado = os.getenv("ASSISTENTE_DATA_DIR", "").strip()
        origem = (
            "config.DATA_DIR (ASSISTENTE_DATA_DIR)"
            if configurado
            else "config.DATA_DIR"
        )
        return _normalizar(data_dir / ARQUIVO_BANCO), origem

    configurado = os.getenv("ASSISTENTE_DATA_DIR", "").strip()

    if configurado:
        return (
            _normalizar(Path(configurado) / "data" / ARQUIVO_BANCO),
            "ASSISTENTE_DATA_DIR",
        )

    return _normalizar(BANCO_FALLBACK), "fallback_raiz"


BANCO_REAL, ORIGEM_BANCO = _resolver_banco_real()


def _arquivos_banco(caminho: Path) -> tuple[Path, ...]:
    """Banco principal e sidecars -wal/-shm de um mesmo caminho."""

    return (
        caminho,
        Path(str(caminho) + "-wal"),
        Path(str(caminho) + "-shm"),
    )


ARQUIVOS_BANCO = _arquivos_banco(BANCO_REAL)

IMPORTACOES_PROIBIDAS = (
    "sqlite3",
    "database",
    "services.db_service",
    "services.history_db",
    "services.history_service",
    "streamlit",
)

CHAMADAS_PROIBIDAS = ("eval", "exec", "compile", "__import__")
ATRIBUTOS_PROIBIDOS = ("sqlite3.connect",)


def _hash_arquivo(caminho: Path) -> str | None:
    if not caminho.is_file():
        return None

    digest = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)

    return digest.hexdigest()


def _impressao(caminho: Path) -> dict:
    return {
        "caminho": str(caminho),
        "existe": caminho.is_file(),
        "tamanho": caminho.stat().st_size if caminho.is_file() else None,
        "sha256": _hash_arquivo(caminho),
    }


def capturar_banco(caminho=None) -> dict:
    """Impressão SHA-256 do banco principal e dos sidecars do SQLite.

    Sem argumento, o alvo é o banco de produção resolvido por
    :func:`_resolver_banco_real` no import do módulo. Um caminho
    explícito serve a testes e diagnósticos e não altera a guarda.
    """

    alvo = _normalizar(caminho) if caminho is not None else BANCO_REAL
    arquivos = _arquivos_banco(alvo)

    return {
        "caminho": str(alvo),
        "origem": (
            ORIGEM_BANCO if caminho is None else "argumento_explicito"
        ),
        "principal": _impressao(arquivos[0]),
        "sidecars": [_impressao(item) for item in arquivos[1:]],
    }


def _rotulos(impressao: dict) -> list[tuple[str, dict]]:
    """Pares (rótulo, impressão) do principal e dos sidecars."""

    itens = [("principal", impressao.get("principal") or {})]

    for indice, sidecar in enumerate(impressao.get("sidecars") or []):
        nome = Path(str(sidecar.get("caminho") or "")).name
        itens.append((
            f"sidecar[{indice}] ({nome or 'desconhecido'})",
            sidecar,
        ))

    return itens


def _divergencias(antes: dict, depois: dict) -> list[dict]:
    """Lista campo a campo o que mudou entre duas impressões."""

    divergencias = []
    mapa_antes = dict(_rotulos(antes))
    mapa_depois = dict(_rotulos(depois))
    ordem = [rotulo for rotulo, _ in _rotulos(antes)]

    for rotulo in mapa_depois:
        if rotulo not in ordem:
            ordem.append(rotulo)

    for rotulo in ordem:
        impressao_antes = mapa_antes.get(rotulo)
        impressao_depois = mapa_depois.get(rotulo)

        if impressao_antes is None or impressao_depois is None:
            divergencias.append(
                {
                    "arquivo": rotulo,
                    "campo": "arquivo",
                    "antes": impressao_antes is not None,
                    "depois": impressao_depois is not None,
                }
            )
            continue

        for campo in ("existe", "tamanho", "sha256"):
            if impressao_antes.get(campo) != impressao_depois.get(campo):
                divergencias.append(
                    {
                        "arquivo": rotulo,
                        "campo": campo,
                        "antes": impressao_antes.get(campo),
                        "depois": impressao_depois.get(campo),
                    }
                )

    if antes.get("caminho") != depois.get("caminho"):
        divergencias.append(
            {
                "arquivo": "snapshot",
                "campo": "caminho",
                "antes": antes.get("caminho"),
                "depois": depois.get("caminho"),
            }
        )

    return divergencias


def _mensagem_comparacao(antes: dict, depois: dict, divergencias) -> str:
    """Mensagem legível com o veredito e os campos divergentes."""

    arquivos = len(_rotulos(antes))

    if not divergencias and antes == depois:
        return (
            "Banco intocado: tamanho e SHA-256 idênticos antes e depois "
            f"({antes.get('caminho')}; {arquivos} arquivo(s) comparado(s))."
        )

    if not divergencias:
        return (
            "Snapshots diferentes em metadados, sem divergência de "
            "tamanho ou SHA-256 nos arquivos do banco."
        )

    detalhes = [
        (
            f"{item['arquivo']} {item['campo']}: "
            f"{item['antes']} -> {item['depois']}"
        )
        for item in divergencias[:6]
    ]
    excedente = ""

    if len(divergencias) > 6:
        excedente = f" (+{len(divergencias) - 6} divergência(s))"

    return "Banco alterado: " + "; ".join(detalhes) + excedente


def comparar_banco(antes: dict, depois: dict) -> dict:
    """Compara duas impressões e devolve o veredito DB_INTOCADO.

    Além do booleano, o retorno traz a lista de divergências por
    arquivo e campo e um diagnóstico legível para o relatório.
    """

    divergencias = _divergencias(antes, depois)
    intocado = not divergencias and antes == depois

    return {
        "antes": antes,
        "depois": depois,
        "intocado": intocado,
        "DB_INTOCADO": intocado,
        "divergencias": divergencias,
        "diagnostico": {
            "veredito": "INTOCADO" if intocado else "ALTERADO",
            "arquivos_comparados": len(_rotulos(antes)),
            "mensagem": _mensagem_comparacao(antes, depois, divergencias),
        },
    }


def _modulo_importado(no) -> str:
    if isinstance(no, ast.Import):
        return ",".join(alias.name for alias in no.names)

    if isinstance(no, ast.ImportFrom):
        base = no.module or ""
        return base

    return ""


def _importacao_proibida(modulo: str) -> bool:
    for proibido in IMPORTACOES_PROIBIDAS:
        if modulo == proibido or modulo.startswith(proibido + "."):
            return True

    return False


def _atributo_completo(no) -> str:
    partes = []
    atual = no

    while isinstance(atual, ast.Attribute):
        partes.append(atual.attr)
        atual = atual.value

    if isinstance(atual, ast.Name):
        partes.append(atual.id)

    return ".".join(reversed(partes))


def _docstrings(arvore) -> set[int]:
    """Ids das constantes que são docstrings (documentação, não código)."""

    identificadores = set()

    for no in ast.walk(arvore):
        if not isinstance(
            no,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue

        if not no.body:
            continue

        primeiro = no.body[0]

        if (
            isinstance(primeiro, ast.Expr)
            and isinstance(primeiro.value, ast.Constant)
            and isinstance(primeiro.value.value, str)
        ):
            identificadores.add(id(primeiro.value))

    return identificadores


def auditar_codigo(caminhos=None) -> list[dict]:
    """Analisa a AST dos módulos e devolve as ocorrências proibidas."""

    caminhos = caminhos or sorted(PASTA_PACOTE.glob("*.py"))
    achados = []

    for caminho in caminhos:
        caminho = Path(caminho)
        origem = caminho.read_text(encoding="utf-8")

        try:
            arvore = ast.parse(origem, filename=str(caminho))
        except SyntaxError as erro:
            achados.append(
                {
                    "arquivo": str(caminho),
                    "linha": erro.lineno,
                    "codigo": "sintaxe",
                    "detalhe": erro.msg,
                }
            )
            continue

        docstrings = _docstrings(arvore)

        for no in ast.walk(arvore):
            if isinstance(no, (ast.Import, ast.ImportFrom)):
                modulo = _modulo_importado(no)

                if _importacao_proibida(modulo):
                    achados.append(
                        {
                            "arquivo": str(caminho),
                            "linha": getattr(no, "lineno", 0),
                            "codigo": "import_proibido",
                            "detalhe": modulo,
                        }
                    )

            if isinstance(no, ast.Call):
                nome = ""

                if isinstance(no.func, ast.Name):
                    nome = no.func.id
                elif isinstance(no.func, ast.Attribute):
                    nome = _atributo_completo(no.func)

                if nome in CHAMADAS_PROIBIDAS or nome in ATRIBUTOS_PROIBIDOS:
                    achados.append(
                        {
                            "arquivo": str(caminho),
                            "linha": getattr(no, "lineno", 0),
                            "codigo": "chamada_proibida",
                            "detalhe": nome,
                        }
                    )

            if (
                isinstance(no, ast.Constant)
                and isinstance(no.value, str)
                and "nexusgeoia.db" in no.value
                and caminho.name != "seguranca.py"
                and id(no) not in docstrings
            ):
                    achados.append(
                        {
                            "arquivo": str(caminho),
                            "linha": getattr(no, "lineno", 0),
                            "codigo": "referencia_banco",
                            "detalhe": no.value[:120],
                        }
                    )

    return achados


def _chave_ordenacao(par: str) -> tuple[str, int]:
    prefixo, _, numero = par.rpartition("-")
    try:
        return prefixo, int(numero)
    except ValueError:
        return par, 0


def auditar_registros(registros) -> list[dict]:
    """Valida esquema, unicidade e paridade bilíngue do dataset."""

    problemas = []
    vistos = set()
    pares = {}

    for indice, registro in enumerate(registros, start=1):
        erros = contrato.validar_registro(registro)

        for erro in erros:
            problemas.append(
                {
                    "linha": indice,
                    "id": registro.get("id", "?"),
                    "codigo": "registro_invalido",
                    "detalhe": erro,
                }
            )

        identificador = registro.get("id")

        if identificador in vistos:
            problemas.append(
                {
                    "linha": indice,
                    "id": identificador,
                    "codigo": "id_duplicado",
                    "detalhe": identificador,
                }
            )

        vistos.add(identificador)
        pares.setdefault(registro.get("metadados", {}).get("par"), {})[
            registro.get("idioma")
        ] = registro

    for par, idiomas in sorted(pares.items(), key=lambda item: item[0] or ""):
        if None in idiomas or set(idiomas) != set(contrato.IDIOMAS):
            problemas.append(
                {
                    "linha": 0,
                    "id": par,
                    "codigo": "par_incompleto",
                    "detalhe": sorted(idiomas),
                }
            )
            continue

        pt = idiomas["pt"]
        en = idiomas["en"]

        if pt.get("tarefa") != en.get("tarefa"):
            problemas.append(
                {
                    "linha": 0,
                    "id": par,
                    "codigo": "tarefa_divergente",
                    "detalhe": (pt.get("tarefa"), en.get("tarefa")),
                }
            )

        if (
            pt.get("tarefa") != contrato.TAREFA_SONDAGEM
            and pt.get("saida_esperada") != en.get("saida_esperada")
        ):
            problemas.append(
                {
                    "linha": 0,
                    "id": par,
                    "codigo": "gabarito_divergente",
                    "detalhe": par,
                }
            )

    return problemas


def auditar_pacote(registros=None) -> dict:
    """Executa a auditoria completa e devolve um relatório serializável."""

    achados = auditar_codigo()

    from finetuning import gerador

    if registros is None:
        registros = gerador.carregar_registros()

    problemas = auditar_registros(registros)

    return {
        "ok": not achados and not problemas,
        "arquivos_auditados": len(list(PASTA_PACOTE.glob("*.py"))),
        "achados_codigo": achados,
        "problemas_dataset": problemas,
        "total_registros": len(registros),
        "sha256_registros": gerador.hash_registros(registros),
    }


if __name__ == "__main__":
    relatorio = auditar_pacote()
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    raise SystemExit(0 if relatorio["ok"] else 1)
