"""Oraculo deterministico das tres tarefas comportamentais.

O oraculo nao e um modelo: ele recomputa a resposta a partir da
**entrada bruta** usando as mesmas regras do projeto. Isso torna o
dataset verificavel e da ao benchmark uma linha de base reprodutivel
(se o oraculo divergir do gabarito, o dataset ou o parser mudou).

Regras usadas:

* roteamento de fontes: :func:`core.source_router.fontes_relevantes` e
  :func:`core.source_router.consulta_ana_exclusiva`, com a mesma
  precedencia do modo Automatico;
* workflow: classificador lexical deterministico definido aqui (a
  interface ainda escolhe o workflow manualmente; este e o contrato
  comportamental ensinado ao SLM);
* sondagem: :func:`services.sondagem.analisar_sondagem`;
* governanca: :func:`core.governance.avaliar_governanca`.
"""

from __future__ import annotations

import json
import re
import ssl

from core import governance
from core.source_router import (
    consulta_ana_exclusiva,
    fontes_relevantes,
    normalizar,
)
from finetuning import contrato
from services import sondagem

# Ordem de prioridade em empate lexical. Sondagem vem primeiro por ser
# a tarefa mais especifica (dados de furo); consulta direta e o padrao.
_GRUPOS_WORKFLOW = (
    (
        "sondagem",
        (
            "sondagem",
            "sondagens",
            "furo",
            "furos",
            "testemunho",
            "testemunhos",
            "litologia",
            "litologias",
            "intervalo de sondagem",
            "intervalos de sondagem",
            "perfil de sondagem",
            "drilling",
            "borehole",
            "boreholes",
            "drillhole",
            "drillholes",
            "drill core",
            "core sample",
            "core samples",
            "lithology",
            "depth interval",
            "depth intervals",
        ),
    ),
    (
        "hidrogeologia",
        (
            "hidrogeologia",
            "hidrogeologico",
            "hidrogeologica",
            "aquifero",
            "aquiferos",
            "poco",
            "pocos",
            "vazao",
            "vazoes",
            "nivel d agua",
            "nivel d'agua",
            "niveis d'agua",
            "nivel estatico",
            "nivel dinamico",
            "estacao fluviometrica",
            "estacoes fluviometricas",
            "estacao pluviometrica",
            "hidroweb",
            "hydrogeology",
            "aquifer",
            "aquifers",
            "water well",
            "water wells",
            "well yield",
            "groundwater",
            "water level",
            "streamflow",
            "rain gauge",
        ),
    ),
    (
        "triagem_area",
        (
            "viabilidade mineral",
            "triagem de area",
            "triagem",
            "alvo",
            "alvos",
            "anomalia",
            "anomalias",
            "exploracao mineral",
            "prospecto",
            "prospectos",
            "jazida",
            "jazidas",
            "mineralizacao",
            "mineral viability",
            "area screening",
            "screening",
            "target",
            "targets",
            "anomaly",
            "anomalies",
            "mineral exploration",
            "prospect",
            "ore deposit",
            "mineralization",
        ),
    ),
)

_PREFIXO_DOCUMENTOS_PT = "documentos locais:"
_PREFIXO_DOCUMENTOS_EN = "local documents:"
_PREFIXO_PERGUNTA_PT = "pergunta:"
_PREFIXO_PERGUNTA_EN = "question:"


def _contem_termo(texto_normalizado: str, termo: str) -> bool:
    """Casa uma palavra ou expressao com fronteira de palavra."""

    partes = normalizar(termo).split()

    if not partes:
        return False

    padrao = r"\b" + r"\s+".join(re.escape(parte) for parte in partes)
    return re.search(padrao + r"\b", texto_normalizado) is not None


def classificar_workflow(pergunta: str) -> str:
    """Classifica a pergunta em um dos quatro workflows canonicos.

    O primeiro grupo com ao menos um termo vence, na ordem
    sondagem > hidrogeologia > triagem de area. Perguntas sem termo
    reconhecido (inclusive fora de escopo) caem em consulta direta.
    """

    texto = normalizar(str(pergunta or ""))

    for workflow, termos in _GRUPOS_WORKFLOW:
        if any(_contem_termo(texto, termo) for termo in termos):
            return workflow

    return "consulta_direta"


def intencao_fontes(pergunta: str, documentos_locais: bool) -> str:
    """Replica a precedencia do roteador Automatico para as fontes."""

    if consulta_ana_exclusiva(pergunta):
        return "ANA_ONLY"

    fontes = fontes_relevantes(pergunta)

    if not documentos_locais:
        return "RIGEO_ONLY"

    if "rag" in fontes and "sgb" in fontes:
        return "HIBRIDO"

    if "rag" in fontes:
        return "LOCAL_ONLY"

    if "sgb" in fontes:
        return "RIGEO_ONLY"

    return "LOCAL_ONLY"


def saida_workflow(pergunta: str, documentos_locais: bool) -> dict:
    """Resposta canonica da tarefa de roteamento."""

    return {
        "workflow": classificar_workflow(pergunta),
        "intencao": intencao_fontes(pergunta, documentos_locais),
    }


def ler_entrada_workflow(entrada: str) -> tuple[str, bool]:
    """Le o contexto e a pergunta do texto de entrada do dataset."""

    documentos = None
    pergunta = None

    for linha in str(entrada or "").splitlines():
        linha_limpa = linha.strip()
        minuscula = normalizar(linha_limpa)

        for prefixo in (_PREFIXO_DOCUMENTOS_PT, _PREFIXO_DOCUMENTOS_EN):
            if minuscula.startswith(prefixo):
                valor = linha_limpa.split(":", 1)[1].strip().lower()
                documentos = valor in {"sim", "yes", "true", "1"}

        for prefixo in (_PREFIXO_PERGUNTA_PT, _PREFIXO_PERGUNTA_EN):
            if minuscula.startswith(prefixo):
                pergunta = linha_limpa.split(":", 1)[1].strip()

    if documentos is None or pergunta is None:
        raise ValueError("entrada_workflow_invalida")

    return pergunta, documentos


def extrair_sondagem(tabela: str) -> dict:
    """Extrai o primeiro intervalo da tabela com o parser real."""

    try:
        resultado = sondagem.analisar_sondagem(tabela)
    except sondagem.SondagemError as erro:
        return {"situacao": "erro_contrato", "erro": erro.codigo}

    itens = list(resultado.get("intervalos") or [])
    itens.extend(resultado.get("invalidos") or [])

    if not itens:
        return {"situacao": "erro_contrato", "erro": "sem_linhas"}

    item = min(itens, key=lambda registro: registro.get("linha") or 0)

    return {
        "furo": item.get("furo") or "",
        "de_m": item.get("de_m"),
        "ate_m": item.get("ate_m"),
        "espessura_m": item.get("espessura_m"),
        "unidade": item.get("unidade") or "",
        "litologia": item.get("litologia") or "",
        "situacao": item.get("situacao") or "invalido",
        "motivo": item.get("motivo") or "",
    }


class ErroHTTPErrorFonte(Exception):
    """Falha HTTP sintetica com nome reconhecido pelo classificador."""

    def __init__(self, codigo: int):
        self.code = codigo
        super().__init__("http indisponivel no oraculo")


def _erro_fonte(codigo: str):
    """Converte o codigo do dataset em uma excecao de fonte real."""

    if codigo == "timeout":
        return TimeoutError("tempo esgotado no oraculo")

    if codigo == "tls":
        return ssl.SSLError(1, "certificado invalido no oraculo")

    if codigo == "http_503":
        return ErroHTTPErrorFonte(503)

    if codigo == "rede":
        return ConnectionError("rede indisponivel no oraculo")

    return RuntimeError("fonte indisponivel no oraculo")


def avaliar_governanca_entrada(entrada) -> dict:
    """Avalia o contrato de governanca e devolve o resumo canonico."""

    if isinstance(entrada, str):
        entrada = json.loads(entrada)

    if not isinstance(entrada, dict):
        raise TypeError("entrada_governanca_invalida")

    codigo_falha = entrada.get("falha_fonte")
    erro = _erro_fonte(str(codigo_falha)) if codigo_falha else None

    resultado = governance.avaliar_governanca(
        entrada.get("contrato"),
        evidencias_validas=entrada.get("evidencias"),
        erro_fonte=erro,
    )

    return {
        "formato": resultado.formato,
        "classificacoes": [
            afirmacao.classificacao for afirmacao in resultado.afirmacoes
        ],
        "veredito": resultado.veredito,
        "motivo": resultado.motivo_codigo,
    }


def prever(registro: dict) -> dict:
    """Recomputa a saida esperada de um registro, sem olhar o gabarito."""

    tarefa = registro.get("tarefa")
    entrada = registro.get("entrada", "")

    if tarefa == contrato.TAREFA_WORKFLOW:
        pergunta, documentos = ler_entrada_workflow(entrada)
        return saida_workflow(pergunta, documentos)

    if tarefa == contrato.TAREFA_SONDAGEM:
        return extrair_sondagem(entrada)

    if tarefa == contrato.TAREFA_GOVERNANCA:
        return avaliar_governanca_entrada(entrada)

    raise ValueError(f"tarefa_desconhecida:{tarefa}")
