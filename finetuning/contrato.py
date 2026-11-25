"""Contrato comum do dataset comportamental e do benchmark.

O contrato fixa os nomes canonicos das tres tarefas, dos idiomas, das
familias de caso e dos campos de saida. A validacao e deliberadamente
rigida e sem dependencias externas: o mesmo codigo valida o JSONL
gerado e a resposta de um modelo local no benchmark.

Formato de cada registro do JSONL::

    {
      "id": "wf-pt-001",
      "tarefa": "workflow_intent",
      "idioma": "pt",
      "instrucao": "...",
      "entrada": "...",
      "saida": "{\"workflow\":\"sondagem\",...}",
      "saida_esperada": {"workflow": "sondagem", "intencao": "RIGEO_ONLY"},
      "verificador": "workflow_intent.v1",
      "metadados": {"familia": "normal", "par": "wf-001"}
    }
"""

from __future__ import annotations

import json

VERSAO_DATASET = "2.0.0"
NOME_DATASET = "nexusgeoia_behavior_v2"

TAREFA_WORKFLOW = "workflow_intent"
TAREFA_SONDAGEM = "sondagem_extract"
TAREFA_GOVERNANCA = "governance_label"

TAREFAS = (
    TAREFA_WORKFLOW,
    TAREFA_SONDAGEM,
    TAREFA_GOVERNANCA,
)

IDIOMAS = ("pt", "en")

FAMILIA_NORMAL = "normal"
FAMILIA_AMBIGUO = "ambiguo"
FAMILIA_INCOMPLETO = "incompleto"
FAMILIA_NEGATIVO = "negativo"

FAMILIAS = (
    FAMILIA_NORMAL,
    FAMILIA_AMBIGUO,
    FAMILIA_INCOMPLETO,
    FAMILIA_NEGATIVO,
)

WORKFLOWS = (
    "consulta_direta",
    "triagem_area",
    "hidrogeologia",
    "sondagem",
)

INTENCOES = (
    "LOCAL_ONLY",
    "RIGEO_ONLY",
    "HIBRIDO",
    "ANA_ONLY",
)

SITUACOES_SONDAGEM = (
    "valido",
    "sobreposicao",
    "lacuna",
    "sobreposicao_lacuna",
    "invalido",
    "erro_contrato",
)

FORMATOS_GOVERNANCA = ("contrato", "texto_livre")
CLASSIFICACOES_GOVERNANCA = ("OBSERVED", "INFERRED")
VEREDITOS_GOVERNANCA = ("PASS", "HOLD", "FAIL")

# Rotulos usados apenas em relatorios de CLI (nao sao texto de
# interface). Os prompts do dataset sao conteudo de treino, mantidos
# nos dois idiomas dentro do proprio registro.
ROTULOS_TAREFA = {
    TAREFA_WORKFLOW: {
        "pt": "Roteamento de workflow / intenção",
        "en": "Workflow / intent routing",
    },
    TAREFA_SONDAGEM: {
        "pt": "Extração estruturada de sondagem",
        "en": "Structured drilling interval extraction",
    },
    TAREFA_GOVERNANCA: {
        "pt": "Rotulagem de governança",
        "en": "Governance labeling",
    },
}

CAMPOS_OBRIGATORIOS = {
    TAREFA_WORKFLOW: ("workflow", "intencao"),
    TAREFA_SONDAGEM: (
        "furo",
        "de_m",
        "ate_m",
        "espessura_m",
        "unidade",
        "litologia",
        "situacao",
        "motivo",
    ),
    TAREFA_GOVERNANCA: (
        "formato",
        "classificacoes",
        "veredito",
        "motivo",
    ),
}

# Esquema ensinado no prompt do benchmark (curto e verificavel).
ESQUEMAS = {
    TAREFA_WORKFLOW: (
        '{"workflow": "consulta_direta|triagem_area|hidrogeologia|sondagem", '
        '"intencao": "LOCAL_ONLY|RIGEO_ONLY|HIBRIDO|ANA_ONLY"}'
    ),
    TAREFA_SONDAGEM: (
        '{"furo": "...", "de_m": numero|null, "ate_m": numero|null, '
        '"espessura_m": numero|null, "unidade": "m|cm|m/cm|", '
        '"litologia": "...", "situacao": "valido|sobreposicao|lacuna|'
        'sobreposicao_lacuna|invalido|erro_contrato", "motivo": "..."}'
    ),
    TAREFA_GOVERNANCA: (
        '{"formato": "contrato|texto_livre", "classificacoes": '
        '["OBSERVED"|"INFERRED", ...], "veredito": "PASS|HOLD|FAIL", '
        '"motivo": "..."}'
    ),
}


def json_compacto(valor) -> str:
    """Serializa JSON deterministico, sem espacos e sem ASCII forcado."""

    return json.dumps(
        valor,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _erro(campo: str, detalhe: str) -> str:
    return f"{campo}:{detalhe}"


def _validar_numero(valor) -> bool:
    """Aceita int/float finito, recusando bool (subclasse de int)."""

    if isinstance(valor, bool):
        return False

    if isinstance(valor, (int, float)):
        return True

    return valor is None


def validar_saida(tarefa: str, saida) -> list[str]:
    """Valida o esquema da resposta de uma tarefa.

    Devolve uma lista de codigos estaveis (vazia quando o esquema esta
    correto). A comparacao com o gabarito e feita no benchmark.
    """

    erros: list[str] = []

    if not isinstance(saida, dict):
        return [_erro("saida", "nao_e_objeto")]

    if tarefa == TAREFA_WORKFLOW:
        if saida.get("workflow") not in WORKFLOWS:
            erros.append(_erro("workflow", "invalido"))
        if saida.get("intencao") not in INTENCOES:
            erros.append(_erro("intencao", "invalida"))
        return erros

    if tarefa == TAREFA_SONDAGEM:
        if saida.get("situacao") == "erro_contrato":
            if not isinstance(saida.get("erro"), str) or not saida["erro"]:
                erros.append(_erro("erro", "invalido"))
            return erros

        for campo in CAMPOS_OBRIGATORIOS[TAREFA_SONDAGEM]:
            if campo not in saida:
                erros.append(_erro(campo, "ausente"))

        for campo in ("de_m", "ate_m", "espessura_m"):
            if campo in saida and not _validar_numero(saida[campo]):
                erros.append(_erro(campo, "tipo_invalido"))

        if "unidade" in saida and not isinstance(saida["unidade"], str):
            erros.append(_erro("unidade", "tipo_invalido"))

        for campo in ("furo", "litologia", "motivo"):
            if campo in saida and not isinstance(saida[campo], str):
                erros.append(_erro(campo, "tipo_invalido"))

        if saida.get("situacao") not in SITUACOES_SONDAGEM:
            erros.append(_erro("situacao", "invalida"))

        return erros

    if tarefa == TAREFA_GOVERNANCA:
        if saida.get("formato") not in FORMATOS_GOVERNANCA:
            erros.append(_erro("formato", "invalido"))

        classificacoes = saida.get("classificacoes")

        if not isinstance(classificacoes, list):
            erros.append(_erro("classificacoes", "nao_e_lista"))
        else:
            for indice, item in enumerate(classificacoes):
                if item not in CLASSIFICACOES_GOVERNANCA:
                    erros.append(
                        _erro(f"classificacoes[{indice}]", "invalida")
                    )

        if saida.get("veredito") not in VEREDITOS_GOVERNANCA:
            erros.append(_erro("veredito", "invalido"))

        if not isinstance(saida.get("motivo"), str):
            erros.append(_erro("motivo", "tipo_invalido"))

        return erros

    return [_erro("tarefa", "desconhecida")]


def validar_registro(registro) -> list[str]:
    """Valida o registro completo do JSONL (metadados e coerencia)."""

    erros: list[str] = []

    if not isinstance(registro, dict):
        return [_erro("registro", "nao_e_objeto")]

    for campo in (
        "id",
        "tarefa",
        "idioma",
        "instrucao",
        "entrada",
        "saida",
        "saida_esperada",
        "verificador",
        "metadados",
    ):
        if campo not in registro:
            erros.append(_erro(campo, "ausente"))

    if erros:
        return erros

    if registro["tarefa"] not in TAREFAS:
        erros.append(_erro("tarefa", "desconhecida"))

    if registro["idioma"] not in IDIOMAS:
        erros.append(_erro("idioma", "desconhecido"))

    for campo in ("id", "instrucao", "entrada", "saida", "verificador"):
        if not isinstance(registro[campo], str) or not registro[campo]:
            erros.append(_erro(campo, "vazio_ou_tipo_invalido"))

    if len(registro.get("saida", "")) > 600:
        erros.append(_erro("saida", "longa_demais"))

    if len(registro.get("entrada", "")) > 1600:
        erros.append(_erro("entrada", "longa_demais"))

    metadados = registro.get("metadados")

    if not isinstance(metadados, dict):
        erros.append(_erro("metadados", "nao_e_objeto"))
    else:
        if metadados.get("familia") not in FAMILIAS:
            erros.append(_erro("metadados.familia", "invalida"))

        if not isinstance(metadados.get("par"), str):
            erros.append(_erro("metadados.par", "ausente"))

    esperado = registro.get("saida_esperada")
    erros.extend(validar_saida(registro["tarefa"], esperado))

    try:
        declarado = json.loads(registro["saida"])
    except (TypeError, ValueError):
        erros.append(_erro("saida", "json_invalido"))
    else:
        if declarado != esperado:
            erros.append(_erro("saida", "divergente_do_gabarito"))

    return erros


def codigo_tarefa_curto(tarefa: str) -> str:
    """Prefixo curto de id por tarefa, usado pelo gerador."""

    return {
        TAREFA_WORKFLOW: "wf",
        TAREFA_SONDAGEM: "sd",
        TAREFA_GOVERNANCA: "gv",
    }.get(tarefa, "xx")
