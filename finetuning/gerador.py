r"""Gerador do dataset comportamental bilíngue PT-BR/EN.

O dataset não treina memorização factual: cada exemplo pede um
comportamento curto e verificável (classificar rota, extrair um intervalo
ou normalizar um contrato de governança). O gabarito é calculado pelo
oráculo determinístico, que usa o roteador de fontes, o parser de
sondagem e a governança reais do projeto.

Uso::

    .\.venv\Scripts\python.exe -m finetuning.gerador
    .\.venv\Scripts\python.exe -m finetuning.gerador --resumo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from finetuning import arquivo_seguro, contrato, oraculo
from finetuning.casos_governanca import OMITIR, casos_governanca
from finetuning.casos_sondagem import CASOS_SONDAGEM
from finetuning.casos_workflow import CASOS_WORKFLOW

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DATASETS = Path(__file__).resolve().parent / "datasets"
ARQUIVO_PADRAO = PASTA_DATASETS / f"{contrato.NOME_DATASET}.jsonl"
MANIFESTO_PADRAO = PASTA_DATASETS / f"{contrato.NOME_DATASET}.manifest.json"

INSTRUCOES = {
    contrato.TAREFA_WORKFLOW: {
        "pt": (
            "Classifique o workflow e a intenção de fontes. Responda só "
            'com JSON: {"workflow": "...", "intencao": "..."}.'
        ),
        "en": (
            "Classify the workflow and the source intent. Answer only "
            'with JSON: {"workflow": "...", "intencao": "..."}.'
        ),
    },
    contrato.TAREFA_SONDAGEM: {
        "pt": (
            "Extraia o primeiro intervalo de sondagem da linha. Responda "
            "só com JSON com furo, de_m, ate_m, espessura_m, unidade, "
            "litologia, situacao e motivo. Use de_m/ate_m em metros e "
            'situacao "erro_contrato" com a chave erro se a tabela for '
            "recusada pelo contrato. Com vários intervalos do mesmo furo, "
            "a situacao do primeiro pode ser sobreposicao ou lacuna "
            "conforme a cobertura das demais linhas."
        ),
        "en": (
            "Extract the first drilling interval from the row. Answer only "
            "with JSON containing furo, de_m, ate_m, espessura_m, unidade, "
            "litologia, situacao and motivo. Use de_m/ate_m in metres and "
            'situacao "erro_contrato" with the erro key when the table is '
            "rejected by the contract. With several intervals of the same "
            "hole, the first one's situacao may be sobreposicao or lacuna "
            "according to the coverage of the other rows."
        ),
    },
    contrato.TAREFA_GOVERNANCA: {
        "pt": (
            "Normalize o contrato de governança. Responda só com JSON: "
            '{"formato": "contrato|texto_livre", "classificacoes": [...], '
            '"veredito": "PASS|HOLD|FAIL", "motivo": "..."}.'
        ),
        "en": (
            "Normalize the governance contract. Answer only with JSON: "
            '{"formato": "contrato|texto_livre", "classificacoes": [...], '
            '"veredito": "PASS|HOLD|FAIL", "motivo": "..."}.'
        ),
    },
}

VERIFICADORES = {
    contrato.TAREFA_WORKFLOW: "workflow_intent.v1",
    contrato.TAREFA_SONDAGEM: "sondagem_extract.v1",
    contrato.TAREFA_GOVERNANCA: "governance_label.v1",
}


def _entrada_workflow(idioma, pergunta, documentos):
    if idioma == "pt":
        contexto = "sim" if documentos else "não"
        return f"Documentos locais: {contexto}\nPergunta: {pergunta}"

    contexto = "yes" if documentos else "no"
    return f"Local documents: {contexto}\nQuestion: {pergunta}"


def _registro(tarefa, idioma, par, familia, entrada, esperado, categoria):
    prefixo = contrato.codigo_tarefa_curto(tarefa)

    return {
        "id": f"{prefixo}-{idioma}-{par}",
        "tarefa": tarefa,
        "idioma": idioma,
        "instrucao": INSTRUCOES[tarefa][idioma],
        "entrada": entrada,
        "saida": contrato.json_compacto(esperado),
        "saida_esperada": esperado,
        "verificador": VERIFICADORES[tarefa],
        "metadados": {
            "familia": familia,
            "par": f"{prefixo}-{par}",
            "categoria": categoria,
        },
    }


def _registros_workflow():
    registros = []

    for indice, caso in enumerate(CASOS_WORKFLOW, start=1):
        par = f"{indice:03d}"
        documentos = caso["docs"]

        for idioma in contrato.IDIOMAS:
            pergunta = caso[idioma]
            entrada = _entrada_workflow(idioma, pergunta, documentos)
            esperado = oraculo.saida_workflow(pergunta, documentos)
            registros.append(
                _registro(
                    contrato.TAREFA_WORKFLOW,
                    idioma,
                    par,
                    caso["familia"],
                    entrada,
                    esperado,
                    "documentos" if documentos else "sem_documentos",
                )
            )

    return registros


def _registros_sondagem():
    registros = []

    for indice, caso in enumerate(CASOS_SONDAGEM, start=1):
        par = f"{indice:03d}"

        for idioma in contrato.IDIOMAS:
            entrada = caso[idioma]
            esperado = oraculo.extrair_sondagem(entrada)
            registros.append(
                _registro(
                    contrato.TAREFA_SONDAGEM,
                    idioma,
                    par,
                    caso["familia"],
                    entrada,
                    esperado,
                    esperado.get("situacao", "invalido"),
                )
            )

    return registros


def _texto_bilingue(valor, indice):
    if isinstance(valor, tuple):
        return valor[indice]

    return valor


def _claims_para_idioma(claims, indice):
    if claims is OMITIR:
        return OMITIR

    if not isinstance(claims, list):
        return claims

    montados = []

    for claim in claims:
        if not isinstance(claim, dict):
            montados.append(_texto_bilingue(claim, indice))
            continue

        montados.append(
            {
                chave: _texto_bilingue(valor, indice)
                for chave, valor in claim.items()
            }
        )

    return montados


def _entrada_governanca(caso, indice):
    if "contrato_texto" in caso:
        contrato_bruto = _texto_bilingue(caso["contrato_texto"], indice)
    else:
        contrato_bruto = {}

        if "resposta" in caso:
            contrato_bruto["answer_markdown"] = _texto_bilingue(
                caso["resposta"],
                indice,
            )

        claims = _claims_para_idioma(caso.get("claims", OMITIR), indice)

        if claims is not OMITIR:
            contrato_bruto["claims"] = claims

        if caso.get("veredito", OMITIR) is not OMITIR:
            contrato_bruto["veredito"] = caso["veredito"]

        if caso.get("cerca"):
            contrato_bruto = (
                "```json\n"
                + json.dumps(contrato_bruto, ensure_ascii=False)
                + "\n```"
            )

    entrada = {"evidencias": caso.get("evidencias", [])}
    entrada["contrato"] = contrato_bruto

    if caso.get("falha_fonte"):
        entrada["falha_fonte"] = caso["falha_fonte"]

    return entrada


def _registros_governanca():
    registros = []

    for indice, caso in enumerate(casos_governanca(), start=1):
        par = f"{indice:03d}"

        for posicao, idioma in enumerate(contrato.IDIOMAS):
            entrada = _entrada_governanca(caso, posicao)
            esperado = oraculo.avaliar_governanca_entrada(entrada)
            registros.append(
                _registro(
                    contrato.TAREFA_GOVERNANCA,
                    idioma,
                    par,
                    caso["familia"],
                    contrato.json_compacto(entrada),
                    esperado,
                    esperado.get("veredito", "HOLD").lower(),
                )
            )

    return registros


def gerar_registros() -> list[dict]:
    """Gera todos os registros em ordem determinística."""

    registros = []
    registros.extend(_registros_workflow())
    registros.extend(_registros_sondagem())
    registros.extend(_registros_governanca())
    return registros


def serializar(registros) -> str:
    """Serializa o JSONL canônico (uma linha por exemplo)."""

    linhas = [contrato.json_compacto(registro) for registro in registros]
    return "\n".join(linhas) + "\n"


def hash_registros(registros) -> str:
    """SHA-256 do conteúdo serializado, sem carimbo de tempo.

    O digest é calculado linha a linha, com a mesma codificação de
    serializar (uma linha JSON + quebra de linha), sem montar uma cópia
    integral do dataset em memória. O valor é idêntico ao SHA-256 do
    arquivo gravado.
    """

    digest = hashlib.sha256()

    for registro in registros:
        digest.update(
            contrato.json_compacto(registro).encode("utf-8")
        )
        digest.update(b"\n")

    return digest.hexdigest()


def _impressao_arquivo(arquivo: Path) -> tuple[str, int]:
    """SHA-256 e tamanho do arquivo em blocos, sem carregar tudo."""

    if not arquivo.is_file():
        return hashlib.sha256(b"").hexdigest(), 0

    digest = hashlib.sha256()
    tamanho = 0

    with arquivo.open("rb") as aberto:
        for bloco in iter(
            lambda: aberto.read(arquivo_seguro.TAMANHO_BLOCO),
            b"",
        ):
            digest.update(bloco)
            tamanho += len(bloco)

    return digest.hexdigest(), tamanho


def gerar_manifesto(registros, arquivo: Path, conteudo=None) -> dict:
    """Manifesto com contagens e hash verificável do JSONL.

    conteudo permite reaproveitar os bytes que serão gravados, evitando
    reler o arquivo inteiro só para hashear. Quando omitido, o arquivo é
    lido em blocos (streaming).
    """

    if conteudo is None:
        sha_arquivo, tamanho = _impressao_arquivo(arquivo)
    else:
        dados = bytes(conteudo)
        sha_arquivo = hashlib.sha256(dados).hexdigest()
        tamanho = len(dados)

    por_tarefa = Counter(registro["tarefa"] for registro in registros)
    por_idioma = Counter(registro["idioma"] for registro in registros)
    por_familia = Counter(
        registro["metadados"]["familia"] for registro in registros
    )

    return {
        "nome": contrato.NOME_DATASET,
        "versao": contrato.VERSAO_DATASET,
        "arquivo": arquivo.name,
        "total": len(registros),
        "por_tarefa": dict(sorted(por_tarefa.items())),
        "por_idioma": dict(sorted(por_idioma.items())),
        "por_familia": dict(sorted(por_familia.items())),
        "sha256_registros": hash_registros(registros),
        "sha256_arquivo": sha_arquivo,
        "tamanho_bytes": tamanho,
        "formato": "jsonl",
        "descricao": (
            "Dataset comportamental bilíngue PT-BR/EN; não memoriza "
            "fatos, apenas roteamento, extração e rotulagem."
        ),
    }


def gravar_dataset(
    registros=None,
    destino: Path | None = None,
    manifesto: Path | None = None,
) -> dict:
    """Grava JSONL e manifesto, devolvendo caminhos e resumo.

    A operação é idempotente e sem estado parcial:

    * gerar duas vezes os mesmos registros produz bytes idênticos e não
      reescreve os arquivos (a chave alterado volta False);
    * JSONL e manifesto são gravados em temporário e trocados de forma
      atômica (finetuning.arquivo_seguro);
    * se o manifesto não puder ser gravado, o JSONL anterior é
      restaurado, em vez de ficar um dataset novo com manifesto velho.
    """

    registros = registros if registros is not None else gerar_registros()
    destino = Path(destino or ARQUIVO_PADRAO)
    manifesto = Path(manifesto or MANIFESTO_PADRAO)

    conteudo = serializar(registros).encode("utf-8")
    dados = gerar_manifesto(registros, destino, conteudo=conteudo)
    texto_manifesto = (
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    )

    # Bytes anteriores só entram em memória quando o rollback é
    # possível e necessário; o dataset comportamental tem poucos MB.
    anterior = None

    if destino.is_file():
        try:
            anterior = destino.read_bytes()
        except OSError:
            anterior = None

    alterado_dataset = arquivo_seguro.gravar_bytes_atomico(
        destino,
        conteudo,
    )

    try:
        alterado_manifesto = arquivo_seguro.gravar_texto_atomico(
            manifesto,
            texto_manifesto,
        )
    except OSError:
        # Rollback: o JSONL não pode ficar novo com o manifesto antigo.
        try:
            arquivo_seguro.restaurar_bytes(destino, anterior)
        except OSError:
            pass

        raise

    return {
        "arquivo": str(destino),
        "manifesto": str(manifesto),
        "total": len(registros),
        "sha256_registros": dados["sha256_registros"],
        "alterado": bool(alterado_dataset or alterado_manifesto),
    }


def carregar_registros(caminho: Path | None = None) -> list[dict]:
    """Lê e valida o JSONL; erros apontam a linha exata."""

    caminho = Path(caminho or ARQUIVO_PADRAO)
    registros = []

    for numero, linha in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not linha.strip():
            continue

        try:
            registro = json.loads(linha)
        except ValueError as erro:
            raise ValueError(f"linha {numero}: JSON inválido: {erro}") from erro

        erros = contrato.validar_registro(registro)

        if erros:
            raise ValueError(
                f"linha {numero} ({registro.get('id', '?')}): "
                + "; ".join(erros)
            )

        registros.append(registro)

    return registros


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera o dataset comportamental bilíngue do NexusGeo IA.",
    )
    parser.add_argument("--saida", type=Path, default=ARQUIVO_PADRAO)
    parser.add_argument("--manifesto", type=Path, default=MANIFESTO_PADRAO)
    parser.add_argument("--resumo", action="store_true")
    argumentos = parser.parse_args(argv)

    registros = gerar_registros()
    resultado = gravar_dataset(
        registros,
        destino=argumentos.saida,
        manifesto=argumentos.manifesto,
    )

    if argumentos.resumo:
        resumo = {
            "total": resultado["total"],
            "por_tarefa": dict(Counter(r["tarefa"] for r in registros)),
            "por_idioma": dict(Counter(r["idioma"] for r in registros)),
            "por_familia": dict(
                Counter(r["metadados"]["familia"] for r in registros)
            ),
            "sha256_registros": resultado["sha256_registros"],
        }
        print(json.dumps(resumo, ensure_ascii=False, indent=2))

    print(
        f"dataset={resultado['arquivo']} total={resultado['total']} "
        f"sha256={resultado['sha256_registros']} "
        f"alterado={resultado['alterado']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
