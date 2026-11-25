"""Benchmark reproduzível do dataset comportamental.

O harness avalia três dimensões sem treinar pesos e sem tocar no banco
real:

* acurácia de rótulo/esquema (comparação com o gabarito verificado);
* taxa de falha de parsing (JSON inválido ou fora do esquema);
* latência por registro (média, p50 e p95 em milissegundos).

Preditores disponíveis:

* oraculo (padrão): recomputa a resposta com as regras do projeto;
* falha: dublê que sempre levanta exceção, usado em testes;
* ruido: dublê que devolve texto sem JSON, para medir falha de parsing;
* ollama: opcional, conversa com um endpoint local em /api/chat.

O benchmark não abre data/nexusgeoia.db; a guarda SHA-256 antes/depois
produz o veredito DB_INTOCADO.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from finetuning import (
    arquivo_seguro,
    contrato,
    gerador,
    oraculo,
    seguranca,
    split as split_mod,
)

TOLERANCIA_NUMERICA = 1e-9
MAX_FALHAS_RELATORIO = 12
SEMENTE_PADRAO = 42

# Catálogos de saída enviados no prompt. Eles espelham os códigos
# estáveis do contrato (finetuning/contrato.py), do parser de sondagem
# (services/sondagem.py) e da governança (core/governance.py), para que
# o modelo local não invente rótulos e o benchmark consiga separar
# erro de esquema de divergência semântica.
MOTIVOS_SONDAGEM = (
    "furo_ausente",
    "de_ausente",
    "ate_ausente",
    "de_invalido",
    "ate_invalido",
    "intervalo_invalido",
    "de_negativo",
    "ate_nao_maior_que_de",
    "unidade_invalida",
)

ERROS_SONDAGEM = (
    "cabecalhos_ausentes",
    "cabecalhos_obrigatorios",
    "numero_invalido",
    "sem_linhas",
    "tabela_desalinhada",
    "tabela_invalida",
    "tabela_vazia",
    "tempo_excedido",
    "intervalo_invalido",
    "unidade_invalida",
)

MOTIVOS_GOVERNANCA = (
    "classificacao_desconhecida",
    "contrato_invalido",
    "contrato_valido",
    "evidencia_desconhecida",
    "falha_declarada",
    "fonte_http",
    "fonte_indisponivel",
    "fonte_rede",
    "fonte_timeout",
    "fonte_tls",
    "observado_sem_evidencia",
    "resposta_vazia",
    "texto_livre",
    "veredito_declarado_hold",
    "veredito_invalido",
)

# Definições objetivas ensinadas no prompt da tarefa de roteamento.
# Elas espelham o PROMPT_ROTEADOR (services/llm_service.py) e a
# precedência determinística de finetuning/oraculo.intencao_fontes, para
# que o modelo local decida com os mesmos critérios do gabarito.
DEFINICOES_WORKFLOW = {
    "pt": (
        "DEFINIÇÕES DE WORKFLOW (vence o primeiro que casar, nesta ordem):",
        (
            "- sondagem: furo, sondagem, testemunho, litologia, intervalo "
            "ou profundidade de sondagem."
        ),
        (
            "- hidrogeologia: aquífero, poço, vazão, nível d'água ou "
            "estático, estação fluviométrica/pluviométrica, HidroWeb."
        ),
        (
            "- triagem_area: viabilidade mineral, alvo, anomalia, "
            "prospecto, jazida, mineralização, exploração mineral, "
            "triagem de área."
        ),
        (
            "- consulta_direta: pergunta geral, conceitual, administrativa "
            "ou fora de escopo, sem o vocabulário acima; é o padrão."
        ),
        "DEFINIÇÕES DE INTENÇÃO DE FONTES:",
        (
            "- LOCAL_ONLY: resposta apenas dos documentos locais; exige "
            "documentos locais disponíveis e citação explícita de "
            "documento, arquivo, PDF ou base local, sem pedido do SGB."
        ),
        (
            "- RIGEO_ONLY: resposta do acervo RIGeo (SGB); consulta "
            "geocientífica que não depende dos documentos locais, ou "
            "qualquer pergunta quando não há documentos locais. É o padrão."
        ),
        (
            "- HIBRIDO: precisa combinar documentos locais e RIGeo; exige "
            "pedido explícito, ou claramente implícito, de comparação ou "
            "complementação das duas fontes."
        ),
        (
            "- ANA_ONLY: consulta exclusiva do inventário de estações da "
            "ANA/HidroWeb (ANA em maiúsculas, HidroWeb, SNIRH, estação "
            "fluviométrica ou pluviométrica), sem termos de geologia, "
            "mineração ou SGB e sem pedido de documento."
        ),
        "REGRAS DE CONSISTÊNCIA:",
        (
            "1. Citação explícita de documento, arquivo, PDF ou base "
            "local, sem pedido do acervo SGB, indica LOCAL_ONLY."
        ),
        (
            "2. Citação explícita de RIGeo, SGB ou acervo, sem referência "
            "à base local, indica RIGEO_ONLY."
        ),
        (
            "3. Pedido de comparação, complementação ou uso das duas "
            "fontes indica HIBRIDO; não escolha HIBRIDO por precaução."
        ),
        (
            "4. Sem documentos locais (docs=não), nunca escolha LOCAL_ONLY "
            "nem HIBRIDO: use RIGEO_ONLY ou, em consulta exclusiva de "
            "estações da ANA/HidroWeb, ANA_ONLY."
        ),
        (
            "5. Haver documentos não basta para LOCAL_ONLY nem para "
            "HIBRIDO: a pergunta precisa citar os documentos ou pedir as "
            "duas fontes; HIBRIDO exige os documentos locais disponíveis "
            "(docs=sim)."
        ),
        (
            "6. ANA_ONLY vale mesmo sem documentos locais e tem "
            "precedência sobre RIGEO_ONLY."
        ),
    ),
    "en": (
        "WORKFLOW DEFINITIONS (the first match wins, in this order):",
        (
            "- sondagem: borehole, drilling, core sample, lithology, "
            "drilling interval or depth."
        ),
        (
            "- hidrogeologia: aquifer, water well, well yield, water level "
            "or static level, streamflow or rain gauge station, HidroWeb."
        ),
        (
            "- triagem_area: mineral viability, target, anomaly, prospect, "
            "ore deposit, mineralization, mineral exploration, area "
            "screening."
        ),
        (
            "- consulta_direta: general, conceptual, administrative or "
            "out-of-scope question without the vocabulary above; it is the "
            "default."
        ),
        "SOURCE INTENT DEFINITIONS:",
        (
            "- LOCAL_ONLY: answer only from the local documents; requires "
            "local documents to be available and an explicit reference to "
            "a document, file, PDF or local base, without an SGB request."
        ),
        (
            "- RIGEO_ONLY: answer from the RIGeo (SGB) collection; a "
            "geoscience query that does not depend on local documents, or "
            "any question when there are no local documents. It is the "
            "default."
        ),
        (
            "- HIBRIDO: must combine local documents and RIGeo; requires "
            "an explicit, or clearly implicit, request to compare or "
            "complement both sources."
        ),
        (
            "- ANA_ONLY: exclusive query of the ANA/HidroWeb station "
            "inventory (upper-case ANA, HidroWeb, SNIRH, streamflow or "
            "rain gauge station) without geology, mining or SGB terms and "
            "without a document request."
        ),
        "CONSISTENCY RULES:",
        (
            "1. An explicit reference to a document, file, PDF or local "
            "base, without an SGB request, means LOCAL_ONLY."
        ),
        (
            "2. An explicit reference to RIGeo, SGB or the collection, "
            "without a local base reference, means RIGEO_ONLY."
        ),
        (
            "3. A request to compare, complement or use both sources means "
            "HIBRIDO; do not choose HIBRIDO by precaution."
        ),
        (
            "4. Without local documents (docs=no), never choose LOCAL_ONLY "
            "or HIBRIDO: use RIGEO_ONLY or, for an exclusive ANA/HidroWeb "
            "station query, ANA_ONLY."
        ),
        (
            "5. Having documents is not enough for LOCAL_ONLY or HIBRIDO: "
            "the question must cite the documents or ask for both sources; "
            "HIBRIDO requires local documents to be available (docs=yes)."
        ),
        (
            "6. ANA_ONLY applies even without local documents and takes "
            "precedence over RIGEO_ONLY."
        ),
    ),
}

_PREFIXOS_DOCUMENTOS = ("documentos locais:", "local documents:")


DIAGNOSTICOS = {
    "timeout": "timeout no prazo do registro",
    "erro_execucao": "erro de execução do preditor",
    "json_invalido": "JSON inválido ou ausente",
    "esquema": "saída fora do esquema",
    "divergencia_semantica": "esquema válido, semântica divergente",
}


class Preditor(Protocol):
    """Contrato mínimo de um preditor avaliado pelo harness."""

    nome: str

    def prever(self, registro: dict) -> str:
        """Devolve a resposta bruta (texto JSON) para um registro."""


class PreditorOraculo:
    """Linha de base determinística, sem rede e sem banco."""

    nome = "oraculo"

    def prever(self, registro: dict) -> str:
        return contrato.json_compacto(oraculo.prever(registro))


class PreditorFalha:
    """Dublê que falha sempre, para provar a taxa de erro do harness."""

    nome = "falha"

    def prever(self, registro: dict) -> str:
        raise RuntimeError(f"falha_injetada:{registro.get('id')}")


class PreditorRuido:
    """Dublê que devolve texto não JSON, para medir falha de parsing."""

    nome = "ruido"

    def prever(self, registro: dict) -> str:
        return f"resposta sem JSON para {registro.get('id')}"


class PreditorOllama:
    """Preditor opcional contra o endpoint local do Ollama.

    A requisição usa temperature=0 e seed fixo, pede JSON puro e tenta
    desabilitar o raciocínio (think=false). Modelos ou endpoints antigos
    que recusam o campo recebem uma segunda tentativa sem ele; a decisão
    fica memorizada na instância para os próximos registros.
    """

    nome = "ollama"

    def __init__(self, modelo=None, host=None, timeout=60, seed=SEMENTE_PADRAO):
        host_padrao, modelo_padrao = _config_ollama()
        self.host = (
            host or os.getenv("OLLAMA_HOST") or host_padrao
        ).rstrip("/")
        self.modelo = modelo or os.getenv("OLLAMA_MODEL") or modelo_padrao
        self.timeout = int(timeout)
        self.seed = int(seed)
        self._think_suportado = True
        self._cancelado = threading.Event()
        self._trava = threading.Lock()
        self._resposta_ativa = None

    def disponivel(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self.host}/api/tags",
                timeout=min(self.timeout, 10),
            ) as resposta:
                return getattr(resposta, "status", 200) == 200
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def cancelar(self) -> bool:
        """Solicita cancelamento e fecha a resposta HTTP ativa.

        Fechar o socket desbloqueia a thread que passou do prazo. O
        retorno indica se havia uma resposta aberta para fechar; quando
        o socket ainda está em conexão, o prazo de socket do urllib é a
        última barreira e o diagnóstico registra a thread ainda ativa.
        """

        self._cancelado.set()

        with self._trava:
            resposta = self._resposta_ativa

        if resposta is None:
            return False

        try:
            resposta.close()
        except Exception:  # noqa: BLE001 - fechamento é best-effort
            return False

        return True

    def _post(self, carga: dict) -> dict:
        if self._cancelado.is_set():
            raise RuntimeError("preditor_cancelado")

        requisicao = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(carga).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                requisicao,
                timeout=self.timeout,
            ) as resposta:
                with self._trava:
                    self._resposta_ativa = resposta

                try:
                    dados = resposta.read()
                finally:
                    with self._trava:
                        self._resposta_ativa = None
        except urllib.error.HTTPError as erro:
            if (
                self._think_suportado
                and "think" in carga
                and erro.code in (400, 404, 422)
            ):
                # Endpoint antigo sem suporte a think: repete uma vez sem
                # o campo e memoriza para não pagar o custo em cada item.
                self._think_suportado = False
                carga.pop("think", None)

                with contextlib.suppress(Exception):
                    erro.close()

                return self._post(carga)

            with contextlib.suppress(Exception):
                erro.close()

            raise

        return json.loads(dados.decode("utf-8"))

    def prever(self, registro: dict) -> str:
        self._cancelado.clear()

        idioma = registro.get("idioma", "pt")
        carga = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": _prompt_sistema(idioma)},
                {"role": "user", "content": _prompt_usuario(registro)},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "seed": self.seed,
            },
        }

        if self._think_suportado:
            carga["think"] = False

        corpo = self._post(carga)
        conteudo = (corpo.get("message") or {}).get("content") or ""

        if not conteudo.strip():
            raise RuntimeError("ollama_resposta_vazia")

        return conteudo


def _config_ollama():
    try:
        from config import OLLAMA_HOST, OLLAMA_MODEL
    except Exception:  # noqa: BLE001 - fallback de CLI fora do app
        return "http://localhost:11434", "qwen3:4b"

    return OLLAMA_HOST, OLLAMA_MODEL


def _codigos(valores) -> str:
    """Lista canônica de códigos para o prompt."""

    return " | ".join(valores)


def _catalogo_tarefa(tarefa: str, idioma: str) -> list[str]:
    """Enumerações aceitas pela tarefa, para reduzir saída inventada."""

    if tarefa == contrato.TAREFA_WORKFLOW:
        return [
            f"- workflow: {_codigos(contrato.WORKFLOWS)}",
            f"- intencao: {_codigos(contrato.INTENCOES)}",
            *DEFINICOES_WORKFLOW["en" if idioma == "en" else "pt"],
        ]

    if tarefa == contrato.TAREFA_SONDAGEM:
        if idioma == "en":
            return [
                f"- situacao: {_codigos(contrato.SITUACOES_SONDAGEM)}",
                (
                    "- erro (required when situacao=erro_contrato): "
                    + _codigos(ERROS_SONDAGEM)
                ),
                (
                    "- motivo: one or more codes separated by semicolon "
                    "(empty text when there is no reason): "
                    + _codigos(MOTIVOS_SONDAGEM)
                ),
                '- unidade: m | cm | m/cm | ""',
            ]

        return [
            f"- situacao: {_codigos(contrato.SITUACOES_SONDAGEM)}",
            (
                "- erro (obrigatório quando situacao=erro_contrato): "
                + _codigos(ERROS_SONDAGEM)
            ),
            (
                "- motivo: um ou mais códigos separados por ponto e vírgula "
                "(texto vazio quando não houver motivo): "
                + _codigos(MOTIVOS_SONDAGEM)
            ),
            '- unidade: m | cm | m/cm | ""',
        ]


    if tarefa == contrato.TAREFA_GOVERNANCA:
        if idioma == "en":
            return [
                f"- formato: {_codigos(contrato.FORMATOS_GOVERNANCA)}",
                (
                    "- classificacoes: "
                    f"{_codigos(contrato.CLASSIFICACOES_GOVERNANCA)} "
                    "(one item per claim, in the same order as the contract "
                    "claims; [] when there are no claims)"
                ),
                f"- veredito: {_codigos(contrato.VEREDITOS_GOVERNANCA)}",
                f"- motivo: {_codigos(MOTIVOS_GOVERNANCA)}",
            ]

        return [
            f"- formato: {_codigos(contrato.FORMATOS_GOVERNANCA)}",
            (
                "- classificacoes: "
                f"{_codigos(contrato.CLASSIFICACOES_GOVERNANCA)} "
                "(um item por afirmação, na mesma ordem das claims do "
                "contrato; [] quando não houver claims)"
            ),
            f"- veredito: {_codigos(contrato.VEREDITOS_GOVERNANCA)}",
            f"- motivo: {_codigos(MOTIVOS_GOVERNANCA)}",
        ]

    return []


def _regras_tarefa(tarefa: str, idioma: str) -> list[str]:
    """Regras objetivas por tarefa, derivadas do oráculo e do contrato.

    Elas atacam os erros recorrentes do preditor local: conversão de
    unidades, confusão entre os estados invalido e erro_contrato, viés
    otimista de governança e escolha de rótulos compostos no workflow.
    """

    if tarefa == contrato.TAREFA_SONDAGEM:
        if idioma == "en":
            return [
                "RULES FOR THE EXTRACTION (mandatory):",
            (
                "1. DEFAULT IS METRES: de_m, ate_m and espessura_m are "
                "always in metres. When no unit is declared in the "
                "header, the Unit column or the Interval cell, the "
                "numbers are already in metres: do not divide and use "
                'unidade "m".'
            ),
            (
                "2. CONVERT ONLY WITH cm: convert to metres only when "
                "the declared unit is cm, centimetre(s) or centimeters "
                "(including the header, such as From (cm)), dividing by "
                "100 (150 cm -> 1.5; 2.5 cm -> 0.025). Never treat "
                "metres as centimetres: never divide a value marked with "
                "m nor a value with no declared unit; the same explicit "
                "unit applies to From and To."
            ),
            (
                "3. DECIMAL: use a dot (1,25 -> 1.25); a comma is "
                "decimal only when there is no dot (1.234,5 -> 1234.5; "
                "1.234 -> 1234)."
            ),
            (
                "4. THICKNESS: espessura_m = ate_m - de_m; use null "
                "when de_m or ate_m is null."
            ),
            (
                "5. UNIT: use the source unit code (m, cm or m/cm). "
                "When From and To declare different units, use "
                '"<from>/<to>" (0 m and 150 cm -> m/cm). With no '
                'declared unit -> m; an unrecognised unit (miles, '
                'feet) -> "".'
            ),
            (
                "6. STATUS erro_contrato: use erro_contrato only when "
                "the table is rejected by the contract: header without "
                "the From/To columns (nor Interval) -> erro "
                '"cabecalhos_obrigatorios"; valid header without a data '
                'row -> erro "sem_linhas"; row with more cells than the '
                'header -> erro "tabela_desalinhada". Then answer only '
                '{"situacao": "erro_contrato", "erro": "<code>"}, with '
                "no other fields and no motivo. If the From/To columns "
                "(or Interval) are missing, do not extract an interval: "
                "use cabecalhos_obrigatorios. If there is no data row, "
                "use sem_linhas."
            ),
            (
                "7. INVALID ROW: if the row exists but a value is "
                "invalid (missing from/to, invalid number, invalid "
                "unit, negative value or inverted interval), use "
                'situacao "invalido", keep furo, de_m, ate_m, '
                "espessura_m, unidade and litologia (null or empty when "
                "absent) and fill motivo. Do not use erro_contrato here "
                "and never invent a plausible number for an invalid "
                "cell: keep null."
            ),
            (
                "8. MOTIVO: include only the codes whose condition "
                "really occurred; a valid value generates no motivo. "
                'Separate with "; " (semicolon plus space), no '
                "repetition and no invention, in this order: "
                "furo_ausente, de_ausente, de_invalido, "
                "unidade_invalida, ate_ausente, ate_invalido, "
                "intervalo_invalido, de_negativo, "
                'ate_nao_maior_que_de; use "" when there is no problem.'
            ),
            (
                "9. REQUIRED KEYS: always send the eight keys (furo, "
                "de_m, ate_m, espessura_m, unidade, litologia, situacao, "
                'motivo); use "" or null when there is no value, but '
                "never omit a key. With erro_contrato send only situacao "
                "and erro."
            ),
            (
                "10. MULTIPLE ROWS: the answer is the first data row of "
                "the table. When other rows describe the same hole, its "
                "situacao is sobreposicao if the interval intersects "
                "coverage already occupied by another row, or lacuna if "
                "its de_m lies beyond the coverage that precedes it. "
                "motivo keeps only the row-validation codes (\"\" when the "
                "row itself is valid); never invent an overlap code in "
                "motivo."
            ),
            ]


        return [
            "REGRAS DA EXTRAÇÃO (obrigatórias):",
            (
                "1. PADRÃO EM METROS: de_m, ate_m e espessura_m são "
                "sempre em metros. Se nenhuma unidade for declarada no "
                "cabeçalho, na coluna Unidade ou na célula Intervalo, os "
                "números já estão em metros: não divida e use unidade "
                '"m".'
            ),
            (
                "2. CONVERSÃO SÓ COM cm: converta para metros apenas "
                "quando a unidade declarada for cm, centímetro(s) ou "
                "centimeters (inclusive no cabeçalho, como Prof. de "
                "(cm)), dividindo por 100 (150 cm -> 1.5; 2,5 cm -> "
                "0.025). Nunca trate metros como centímetros: não divida "
                "valor marcado com m nem valor sem unidade declarada; a "
                "mesma unidade explícita vale para De e Até."
            ),
            (
                "3. DECIMAL: use ponto (1,25 -> 1.25); a vírgula só é "
                "decimal quando não houver ponto (1.234,5 -> 1234.5; "
                "1.234 -> 1234)."
            ),
            (
                "4. ESPESSURA: espessura_m = ate_m - de_m; use null "
                "quando de_m ou ate_m for null."
            ),
            (
                "5. UNIDADE: use o código da unidade de origem (m, cm "
                "ou m/cm). Se De e Até declararem unidades diferentes, "
                'use "<de>/<ate>" (0 m e 150 cm -> m/cm). Sem unidade '
                'declarada -> m; unidade não reconhecida (milhas, pés) '
                '-> "".'
            ),
            (
                "6. SITUAÇÃO erro_contrato: use erro_contrato apenas "
                "quando a tabela for recusada pelo contrato: cabeçalho "
                "sem as colunas De/Até (nem Intervalo) -> erro "
                '"cabecalhos_obrigatorios"; cabeçalho válido sem linha '
                'de dados -> erro "sem_linhas"; linha com mais células '
                'que o cabeçalho -> erro "tabela_desalinhada". Nesses '
                'casos responda só {"situacao": "erro_contrato", '
                '"erro": "<código>"}, sem os demais campos e sem motivo. '
                "Se faltarem as colunas De/Até (ou Intervalo), não "
                "extraia intervalo: use cabecalhos_obrigatorios. Se não "
                "houver linha de dados, use sem_linhas."
            ),
            (
                "7. LINHA INVÁLIDA: se a linha existe mas um valor é "
                "inválido (de/até ausente, número inválido, unidade "
                "inválida, valor negativo ou intervalo invertido), use "
                'situacao "invalido", preserve furo, de_m, ate_m, '
                "espessura_m, unidade e litologia (null ou vazio quando "
                "ausente) e preencha motivo. Não use erro_contrato nesse "
                "caso e nunca invente um número plausível para uma "
                "célula inválida: mantenha null."
            ),
            (
                "8. MOTIVO: inclua só os códigos cuja condição realmente "
                "ocorreu; valor válido não gera motivo. Separe por "
                '"; " (ponto e vírgula e espaço), sem repetir e sem '
                "inventar, nesta ordem: furo_ausente, de_ausente, "
                "de_invalido, unidade_invalida, ate_ausente, "
                "ate_invalido, intervalo_invalido, de_negativo, "
                'ate_nao_maior_que_de; use "" quando não houver problema.'
            ),
            (
                "9. CHAVES OBRIGATÓRIAS: envie sempre as oito chaves "
                "(furo, de_m, ate_m, espessura_m, unidade, litologia, "
                'situacao, motivo); use "" ou null quando não houver '
                "valor, mas nunca omita uma chave. Em erro_contrato "
                "envie somente situacao e erro."
            ),
            (
                "10. VÁRIAS LINHAS: a resposta é a primeira linha de "
                "dados da tabela. Quando outras linhas descrevem o mesmo "
                "furo, a situacao é sobreposicao se o intervalo cruzar "
                "cobertura já ocupada por outra linha, ou lacuna se o de_m "
                "estiver além da cobertura que o antecede. motivo mantém "
                'apenas os códigos de validação da linha ("" quando a '
                "linha é válida); nunca invente um código de sobreposição "
                "em motivo."
            ),
        ]


    if tarefa == contrato.TAREFA_GOVERNANCA:
        if idioma == "en":
            return [
                "RULES FOR THE GOVERNANCE LABEL (mandatory):",
                (
                    "1. EXACT KEY: always emit motivo; never mot, motive "
                    "or motivo_codigo."
                ),
                (
                    "2. CLASSIFICACOES: one item per claim, in input "
                    "order. OBSERVED only when the claim carries an "
                    "evidence_id present in evidencias; without "
                    "evidence_id, or with an id outside the catalogue, the "
                    "item is INFERRED. An unknown declared classification "
                    "becomes INFERRED. Missing or empty claims -> []; "
                    "classificacoes never copies evidencias and is not "
                    "filled when no claim applies."
                ),
                (
                    "3. PASS only when formato=contrato, answer_markdown "
                    "is non-empty, claims is a present list, the declared "
                    "verdict is absent or PASS, every classification is "
                    "known and every OBSERVED has a valid evidence_id. "
                    "Missing evidence, inconsistency or a source/contract "
                    "failure is never PASS."
                ),
                (
                    "4. HOLD for missing evidence "
                    "(observado_sem_evidencia), evidence outside the "
                    "catalogue (evidencia_desconhecida), unknown "
                    "classification (classificacao_desconhecida), missing "
                    "claims (contrato_invalido), free text (texto_livre), "
                    "invalid declared verdict (veredito_invalido, with "
                    "verdict HOLD) and source failure (fonte_timeout, "
                    "fonte_tls, fonte_http, fonte_rede, "
                    "fonte_indisponivel). A declared HOLD stays HOLD with "
                    "motivo veredito_declarado_hold."
                ),
                (
                    "5. FAIL only for an empty answer (motivo "
                    "resposta_vazia) or a declared FAIL verdict (motivo "
                    "falha_declarada). A source failure never becomes FAIL."
                ),
                (
                    "6. Precedence: source failure > empty answer > "
                    "contract problem > declared FAIL > declared HOLD > "
                    "PASS. With several problems, motivo is the first "
                    "detected: veredito_invalido, contrato_invalido, "
                    "classificacao_desconhecida, evidencia_desconhecida, "
                    "observado_sem_evidencia."
                ),
                (
                    "7. formato: contrato when the input is a recognised "
                    "contract object; texto_livre for free text, including "
                    "empty text."
                ),
                (
                    "8. classificacoes: [] when no claim applies; never "
                    '["OBSERVED"] by default. With a source failure, '
                    "classificacoes is [] and formato follows the input "
                    "(contrato or texto_livre)."
                ),
                (
                    "9. MOTIVO MAP: falha_fonte=timeout -> fonte_timeout; "
                    "tls -> fonte_tls; http_503 -> fonte_http; rede -> "
                    "fonte_rede; any other -> fonte_indisponivel. Empty "
                    "string contract -> resposta_vazia (FAIL); non-empty "
                    "free-text contract -> texto_livre (HOLD). Missing "
                    "claims or claims not a list -> contrato_invalido. An "
                    "evidence_id outside evidencias -> "
                    "evidencia_desconhecida (not "
                    "observado_sem_evidencia). OBSERVED without "
                    "evidence_id -> observado_sem_evidencia. A verdict "
                    "outside PASS/HOLD/FAIL -> veredito_invalido."
                ),
                (
                    "10. MANDATORY CHECKLIST: (a) if falha_fonte exists: "
                    "veredito HOLD, motivo=fonte_* by its value, "
                    "formato=contrato when the contract is an object "
                    "(else texto_livre), classificacoes=[] and DO NOT "
                    "evaluate claims; (b) otherwise, if answer_markdown is "
                    "absent or empty: FAIL/resposta_vazia; (c) otherwise, "
                    "if claims is not a present list: HOLD/"
                    "contrato_invalido; (d) otherwise, recompute each item "
                    "from its evidence_id and report the first problem in "
                    "the item 6 order; (e) with no problem and no declared "
                    "HOLD/FAIL: PASS/contrato_valido."
                ),
            ]

        return [
            "REGRAS DA ROTULAGEM DE GOVERNANÇA (obrigatórias):",
            (
                "1. CHAVE EXATA: emita sempre motivo; nunca mot, motive "
                "ou motivo_codigo."
            ),
            (
                "2. CLASSIFICACOES: um item por claim, na ordem da "
                "entrada. OBSERVED só quando a claim tiver evidence_id "
                "presente em evidencias; sem evidence_id, ou com id fora "
                "do catálogo, o item é INFERRED. Classificação declarada "
                "desconhecida vira INFERRED. Claims ausente ou vazia -> "
                "[]; classificacoes nunca copia evidencias e não é "
                "preenchida quando nenhuma claim se aplica."
            ),
            (
                "3. PASS só quando formato=contrato, answer_markdown não "
                "vazio, claims presente e em lista, veredito declarado "
                "ausente ou PASS, todas as classificações conhecidas e "
                "todo OBSERVED com evidence_id válido. Falta de evidência, "
                "inconsistência ou falha de fonte/contrato nunca é PASS."
            ),
            (
                "4. HOLD para falta de evidência (observado_sem_evidencia), "
                "evidência fora do catálogo (evidencia_desconhecida), "
                "classificação desconhecida (classificacao_desconhecida), "
                "claims ausente (contrato_invalido), texto livre "
                "(texto_livre), veredito declarado inválido "
                "(veredito_invalido, com veredito HOLD) e falha de fonte "
                "(fonte_timeout, fonte_tls, fonte_http, fonte_rede, "
                "fonte_indisponivel). HOLD declarado continua HOLD com "
                "motivo veredito_declarado_hold."
            ),
            (
                "5. FAIL só para resposta vazia (motivo resposta_vazia) ou "
                "veredito FAIL declarado (motivo falha_declarada). Falha "
                "de fonte nunca vira FAIL."
            ),
            (
                "6. Precedência: falha de fonte > resposta vazia > "
                "problema de contrato > FAIL declarado > HOLD declarado > "
                "PASS. Com vários problemas, motivo é o primeiro "
                "detectado: veredito_invalido, contrato_invalido, "
                "classificacao_desconhecida, evidencia_desconhecida, "
                "observado_sem_evidencia."
            ),
            (
                "7. formato: contrato quando a entrada for um objeto de "
                "contrato reconhecido; texto_livre para texto livre, "
                "inclusive vazio."
            ),
            (
                "8. classificacoes: [] quando nenhuma claim se aplicar; "
                'nunca ["OBSERVED"] por padrão. Em falha de fonte, '
                "classificacoes é [] e formato segue a entrada (contrato "
                "ou texto_livre)."
            ),
            (
                "9. MAPA DE MOTIVOS: falha_fonte=timeout -> fonte_timeout; "
                "tls -> fonte_tls; http_503 -> fonte_http; rede -> "
                "fonte_rede; qualquer outro -> fonte_indisponivel. "
                "Contrato string vazia -> resposta_vazia (FAIL); contrato "
                "string não vazia -> texto_livre (HOLD). Claims ausente ou "
                "fora de lista -> contrato_invalido. evidence_id fora de "
                "evidencias -> evidencia_desconhecida (não "
                "observado_sem_evidencia). OBSERVED sem evidence_id -> "
                "observado_sem_evidencia. Veredito fora de PASS/HOLD/FAIL "
                "-> veredito_invalido."
            ),
            (
                "10. CHECKLIST OBRIGATÓRIO: (a) se existir falha_fonte: "
                "veredito HOLD, motivo=fonte_* conforme o valor, "
                "formato=contrato quando o contrato for objeto (senão "
                "texto_livre), classificacoes=[] e NÃO avalie claims; (b) "
                "senão, se answer_markdown estiver ausente ou vazio: "
                "FAIL/resposta_vazia; (c) senão, se claims não for uma "
                "lista presente: HOLD/contrato_invalido; (d) senão, "
                "recalcule cada item pelo evidence_id e informe o "
                "primeiro problema na ordem do item 6; (e) sem problema e "
                "sem HOLD/FAIL declarado: PASS/contrato_valido."
            ),
        ]

    if tarefa == contrato.TAREFA_WORKFLOW:
        if idioma == "en":
            return [
                "DECISION CRITERIA (mandatory):",
                (
                    "1. Choose exactly one code for workflow and exactly "
                    "one for intencao; never join codes with |, / or a "
                    "comma. The | in the schema only separates the "
                    "possible values."
                ),
                (
                    "2. Workflow: apply the precedence sondagem > "
                    "hidrogeologia > triagem_area > consulta_direta; the "
                    "first group with a recognised term wins, even when "
                    "another group also appears in the question."
                ),
                (
                    "3. HIBRIDO requires an explicit reference to both "
                    "sources in the same question: the local base "
                    "(document, file, PDF, attachment, local base) and the "
                    "SGB/RIGeo collection. Comparing two values from the "
                    "same source, or using compare without naming both "
                    "sources, is not HIBRIDO."
                ),
                (
                    "4. With local documents available and no SGB request, "
                    "a cited document/PDF/attachment means LOCAL_ONLY; a "
                    "cited SGB/RIGeo collection without the local base "
                    "means RIGEO_ONLY."
                ),
                (
                    "5. Without local documents (docs=no), use RIGEO_ONLY "
                    "or, for an exclusive ANA/HidroWeb station query, "
                    "ANA_ONLY; never LOCAL_ONLY or HIBRIDO."
                ),
                (
                    "6. ANA_ONLY only for an exclusive ANA/HidroWeb "
                    "station query, without geology, mining or SGB terms "
                    "and without a document request."
                ),
            ]

        return [
            "CRITÉRIOS DE DECISÃO (obrigatórios):",
            (
                "1. Escolha exatamente um código em workflow e exatamente "
                "um em intencao; nunca junte códigos com |, / ou vírgula. "
                "O | do esquema apenas separa os valores possíveis."
            ),
            (
                "2. Workflow: aplique a precedência sondagem > "
                "hidrogeologia > triagem_area > consulta_direta; o "
                "primeiro grupo com termo reconhecido vence, mesmo que "
                "outro grupo também apareça na pergunta."
            ),
            (
                "3. HIBRIDO exige referência explícita às duas fontes na "
                "mesma pergunta: base local (documento, arquivo, PDF, "
                "anexo, base local) e acervo SGB/RIGeo. Comparar dois "
                "valores da mesma fonte, ou usar compare sem citar as "
                "duas fontes, não é HIBRIDO."
            ),
            (
                "4. Com documentos locais disponíveis e sem pedido do "
                "SGB, documento/PDF/anexo citado indica LOCAL_ONLY; "
                "acervo SGB/RIGeo citado sem base local indica RIGEO_ONLY."
            ),
            (
                "5. Sem documentos locais (docs=não), use RIGEO_ONLY ou, "
                "em consulta exclusiva de estações ANA/HidroWeb, ANA_ONLY; "
                "nunca LOCAL_ONLY nem HIBRIDO."
            ),
            (
                "6. ANA_ONLY só em consulta exclusiva de estações "
                "ANA/HidroWeb, sem termos de geologia, mineração ou SGB e "
                "sem pedido de documento."
            ),
        ]

    return []


def _prompt_sistema(idioma: str) -> str:
    if idioma == "en":
        return (
            "You are a behavior evaluator for NexusGeo IA. Answer only with "
            "one valid JSON object, without markdown, code fences, comments "
            "or any reasoning outside the JSON. Use exactly the schema keys "
            "and the allowed codes; never translate or invent codes. Use a "
            "dot as decimal separator and null for missing values. In "
            "classificacoes, keep one item per claim in the same order as "
            "the contract claims and use [] when there are no claims. Each "
            "enum field takes exactly one valid code; never concatenate "
            "codes with |. Apply the task rules before answering. Do not "
            "emit any text before or after the JSON object."
        )

    return (
        "Você é um avaliador de comportamento do NexusGeo IA. Responda "
        "apenas com um único objeto JSON válido, sem markdown, sem cercas "
        "de código, sem comentários e sem raciocínio fora do JSON. Use "
        "exatamente as chaves do esquema e os códigos permitidos; nunca "
        "traduza nem invente códigos. Use ponto como separador decimal e "
        "null para valor ausente. Em classificacoes, mantenha um item por "
        "afirmação na mesma ordem das claims do contrato e use [] quando "
        "não houver claims. Cada campo de enumeração recebe exatamente um "
        "código válido; nunca concatene códigos com |. Aplique as regras da "
        "tarefa antes de responder. Não emita texto antes ou depois do "
        "objeto JSON."
    )


def _documentos_locais(entrada):
    """Lê o campo de documentos locais da entrada do workflow.

    Devolve True/False quando a linha existe e None quando a entrada não
    declara o contexto, para o prompt não afirmar um estado inventado.
    """

    for linha in str(entrada or "").splitlines():
        minuscula = linha.strip().lower()

        for prefixo in _PREFIXOS_DOCUMENTOS:
            if minuscula.startswith(prefixo):
                valor = minuscula.split(":", 1)[1].strip()
                return valor in {"sim", "yes", "true", "1"}

    return None


def _bloco_documentos(idioma: str, documentos) -> list[str]:
    """Restrição ativa de fontes conforme o contexto de documentos.

    É a parte objetiva da regra do roteador: sem documentos locais o
    modelo não pode escolher LOCAL_ONLY nem HIBRIDO, e HIBRIDO nunca é
    escolhido por precaução.
    """

    if documentos is None:
        return []

    if idioma == "en":
        if documentos:
            return [
                (
                    "ACTIVE CONSTRAINT (Local documents: yes): a document, "
                    "file, PDF or local base cited without an SGB request "
                    "means LOCAL_ONLY; SGB or the collection cited without "
                    "a local base reference means RIGEO_ONLY; HIBRIDO only "
                    "when the question asks for both sources. Never choose "
                    "HIBRIDO by precaution."
                )
            ]

        return [
            (
                "ACTIVE CONSTRAINT (Local documents: no): in this item "
                "LOCAL_ONLY and HIBRIDO are forbidden. Choose RIGEO_ONLY, "
                "or ANA_ONLY only for an exclusive ANA/HidroWeb station "
                "query; never choose HIBRIDO by precaution."
            )
        ]

    if documentos:
        return [
            (
                "RESTRIÇÃO ATIVA (Documentos locais: sim): documento, "
                "arquivo, PDF ou base local citados sem pedido do SGB "
                "indicam LOCAL_ONLY; SGB ou acervo citados sem referência "
                "à base local indicam RIGEO_ONLY; HIBRIDO só quando a "
                "pergunta pedir as duas fontes. Não escolha HIBRIDO por "
                "precaução."
            )
        ]

    return [
        (
            "RESTRIÇÃO ATIVA (Documentos locais: não): neste item "
            "LOCAL_ONLY e HIBRIDO são proibidos. Escolha RIGEO_ONLY ou, "
            "somente em consulta exclusiva de estações da ANA/HidroWeb, "
            "ANA_ONLY; não escolha HIBRIDO por precaução."
        )
    ]


def _prompt_usuario(registro: dict) -> str:
    """Mensagem do usuário com tarefa, códigos válidos, entrada e esquema."""

    idioma = "en" if registro.get("idioma") == "en" else "pt"
    tarefa = registro.get("tarefa")
    rotulo = contrato.ROTULOS_TAREFA.get(tarefa, {}).get(idioma, tarefa)
    documentos = (
        _documentos_locais(registro.get("entrada"))
        if tarefa == contrato.TAREFA_WORKFLOW
        else None
    )

    if idioma == "en":
        partes = [
            f"TASK: {rotulo}",
            f"INSTRUCTION: {registro.get('instrucao', '')}",
            "VALID CODES (use only these):",
            *_catalogo_tarefa(tarefa, idioma),
            *_regras_tarefa(tarefa, idioma),
            *_bloco_documentos(idioma, documentos),
            f"INPUT:\n{registro.get('entrada', '')}",
            f"SCHEMA (strict JSON): {contrato.ESQUEMAS.get(tarefa, '')}",
            (
                "Answer only with the JSON object, with no text before or "
                "after it."
            ),
        ]
    else:
        partes = [
            f"TAREFA: {rotulo}",
            f"INSTRUÇÃO: {registro.get('instrucao', '')}",
            "CÓDIGOS VÁLIDOS (use somente estes):",
            *_catalogo_tarefa(tarefa, idioma),
            *_regras_tarefa(tarefa, idioma),
            *_bloco_documentos(idioma, documentos),
            f"ENTRADA:\n{registro.get('entrada', '')}",
            f"ESQUEMA (JSON estrito): {contrato.ESQUEMAS.get(tarefa, '')}",
            (
                "Responda somente com o objeto JSON, sem texto antes ou "
                "depois dele."
            ),
        ]

    return "\n".join(partes)


def extrair_json(texto) -> dict:
    """Extrai o primeiro objeto JSON de uma resposta bruta."""

    if isinstance(texto, dict):
        return texto

    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("resposta_vazia")

    bruto = texto.strip()
    cerca = chr(96) * 3
    cercado = re.search(
        cerca + r"(?:json|JSON)?s*(.*?)" + cerca,
        bruto,
        re.DOTALL,
    )

    if cercado:
        bruto = cercado.group(1).strip()

    try:
        objeto = json.loads(bruto)
    except ValueError:
        objeto = None

    if isinstance(objeto, dict):
        return objeto

    decodificador = json.JSONDecoder()

    for indice, caractere in enumerate(bruto):
        if caractere != "{":
            continue

        try:
            objeto, _ = decodificador.raw_decode(bruto[indice:])
        except ValueError:
            continue

        if isinstance(objeto, dict):
            return objeto

    raise ValueError("json_invalido")


def _mesmo_numero(esperado, obtido) -> bool:
    if esperado is None or obtido is None:
        return esperado is None and obtido is None

    if isinstance(esperado, bool) or isinstance(obtido, bool):
        return False

    try:
        return abs(float(esperado) - float(obtido)) <= TOLERANCIA_NUMERICA
    except (TypeError, ValueError):
        return False


def _comparar_sondagem(esperado: dict, obtido: dict) -> bool:
    if (
        esperado.get("situacao") == "erro_contrato"
        or obtido.get("situacao") == "erro_contrato"
    ):
        return (
            esperado.get("situacao") == obtido.get("situacao")
            and esperado.get("erro") == obtido.get("erro")
        )

    for campo in ("furo", "unidade", "litologia", "situacao", "motivo"):
        if (esperado.get(campo) or "") != (obtido.get(campo) or ""):
            return False

    for campo in ("de_m", "ate_m", "espessura_m"):
        if not _mesmo_numero(esperado.get(campo), obtido.get(campo)):
            return False

    return True


def _comparar(tarefa: str, esperado: dict, obtido: dict) -> bool:
    if tarefa == contrato.TAREFA_WORKFLOW:
        return (
            esperado.get("workflow") == obtido.get("workflow")
            and esperado.get("intencao") == obtido.get("intencao")
        )

    if tarefa == contrato.TAREFA_SONDAGEM:
        return _comparar_sondagem(esperado, obtido)

    if tarefa == contrato.TAREFA_GOVERNANCA:
        return (
            esperado.get("formato") == obtido.get("formato")
            and esperado.get("classificacoes") == obtido.get("classificacoes")
            and esperado.get("veredito") == obtido.get("veredito")
            and esperado.get("motivo") == obtido.get("motivo")
        )

    return False


def rotulo_principal(tarefa: str, saida) -> str:
    """Rótulo usado na matriz de confusão do relatório."""

    if not isinstance(saida, dict):
        return "<falha>"

    if tarefa == contrato.TAREFA_WORKFLOW:
        return str(saida.get("workflow", "<ausente>"))

    if tarefa == contrato.TAREFA_SONDAGEM:
        return str(saida.get("situacao", "<ausente>"))

    if tarefa == contrato.TAREFA_GOVERNANCA:
        return str(saida.get("veredito", "<ausente>"))

    return "<desconhecido>"


def _cancelar_preditor(preditor) -> bool:
    """Pede cancelamento cooperativo ao preditor, quando ele oferece."""

    cancelar = getattr(preditor, "cancelar", None)

    if not callable(cancelar):
        return False

    try:
        return bool(cancelar())
    except Exception:  # noqa: BLE001 - limpeza é best-effort
        return False


def _executar_preditor(preditor, registro, prazo_s=None):
    """Executa o preditor com prazo explícito por registro.

    Sem prazo o caminho é direto (rápido, sem thread). Com prazo, uma
    thread daemon executa a previsão e o harness espera no máximo
    prazo_s: um preditor travado é registrado como TimeoutError e o
    benchmark segue para o próximo registro, em vez de ficar preso.

    No timeout, o preditor recebe uma chance de cancelar e fechar a
    resposta HTTP ativa. O diagnóstico informa se o cancelamento foi
    solicitado e se a thread ainda estava presa em uma conexão; assim,
    um vazamento de thread/socket não passa silenciosamente.
    """

    if prazo_s is None:
        return preditor.prever(registro)

    resultado = {}

    def alvo():
        try:
            resultado["valor"] = preditor.prever(registro)
        except BaseException as erro:  # noqa: BLE001 - repassado abaixo
            resultado["erro"] = erro

    thread = threading.Thread(
        target=alvo,
        name="nexusgeo-bench-preditor",
        daemon=True,
    )
    thread.start()
    thread.join(max(0.0, float(prazo_s)))

    if thread.is_alive():
        cancelado = _cancelar_preditor(preditor)

        if cancelado:
            thread.join(0.25)

        estado = (
            "encerrada"
            if not thread.is_alive()
            else "ainda ativa (daemon)"
        )
        raise TimeoutError(
            f"preditor excedeu {float(prazo_s):.3f}s; "
            f"cancelamento={'solicitado' if cancelado else 'nao_aplicavel'}; "
            f"thread {estado}"
        )

    if "erro" in resultado:
        raise resultado["erro"]

    return resultado.get("valor")


def avaliar_registro(
    registro: dict,
    preditor: Preditor,
    prazo_registro_s: float | None = None,
) -> dict:
    """Executa um preditor, mede latência e compara com o gabarito."""

    inicio = time.perf_counter()
    bruto = None
    erro_execucao = None
    tipo_falha = None

    try:
        bruto = _executar_preditor(
            preditor,
            registro,
            prazo_registro_s,
        )
    except Exception as erro:  # noqa: BLE001 - falha de preditor é medida
        erro_execucao = f"{type(erro).__name__}: {erro}"
        tipo_falha = (
            "timeout" if isinstance(erro, TimeoutError) else "erro_execucao"
        )

    latencia_ms = (time.perf_counter() - inicio) * 1000
    esperado = registro.get("saida_esperada")

    resultado = {
        "id": registro.get("id"),
        "tarefa": registro.get("tarefa"),
        "idioma": registro.get("idioma"),
        "familia": registro.get("metadados", {}).get("familia"),
        "latencia_ms": round(latencia_ms, 3),
        "erro_execucao": erro_execucao,
        "tipo_falha": tipo_falha,
        "diagnostico": DIAGNOSTICOS.get(tipo_falha),
        "falha_parsing": False,
        "esquema_ok": False,
        "correto": False,
        "rotulo_esperado": rotulo_principal(registro.get("tarefa"), esperado),
        "rotulo_obtido": "<falha>",
    }

    if erro_execucao:
        return resultado

    try:
        obtido = extrair_json(bruto)
    except ValueError as erro:
        resultado["falha_parsing"] = True
        resultado["erro_parsing"] = str(erro)
        resultado["resposta_bruta"] = str(bruto)[:400]
        resultado["tipo_falha"] = "json_invalido"
        resultado["diagnostico"] = DIAGNOSTICOS["json_invalido"]
        return resultado

    erros_esquema = contrato.validar_saida(registro.get("tarefa"), obtido)
    mesma_semantica = _comparar(registro.get("tarefa"), esperado, obtido)
    resultado["esquema_ok"] = not erros_esquema
    resultado["rotulo_obtido"] = rotulo_principal(
        registro.get("tarefa"),
        obtido,
    )
    resultado["correto"] = bool(resultado["esquema_ok"] and mesma_semantica)

    if erros_esquema:
        tipo_falha = "esquema"
    elif not mesma_semantica:
        tipo_falha = "divergencia_semantica"

    resultado["tipo_falha"] = tipo_falha
    resultado["diagnostico"] = DIAGNOSTICOS.get(tipo_falha)

    if not resultado["correto"]:
        resultado["erros_esquema"] = erros_esquema
        resultado["esperado"] = esperado
        resultado["obtido"] = obtido

    return resultado


def _percentil(valores, percentual: float):
    if not valores:
        return None

    ordenados = sorted(valores)

    if len(ordenados) == 1:
        return ordenados[0]

    posicao = (len(ordenados) - 1) * percentual / 100
    base = math.floor(posicao)
    resto = posicao - base

    if base + 1 < len(ordenados):
        return ordenados[base] + (
            ordenados[base + 1] - ordenados[base]
        ) * resto

    return ordenados[base]


def _falhas_por_tipo(itens: list[dict]) -> dict:
    """Contagem determinística por categoria de falha diagnósticada."""

    contagem = {}

    for item in itens:
        tipo = item.get("tipo_falha")

        if tipo:
            contagem[tipo] = contagem.get(tipo, 0) + 1

    return dict(sorted(contagem.items()))


def _resumo(itens: list[dict]) -> dict:
    total = len(itens)
    latencias = [item["latencia_ms"] for item in itens]

    def taxa(quantidade):
        return round(quantidade / total, 6) if total else 0.0

    return {
        "total": total,
        "corretos": sum(1 for item in itens if item["correto"]),
        "acuracia": taxa(sum(1 for item in itens if item["correto"])),
        "esquema_ok": sum(1 for item in itens if item["esquema_ok"]),
        "acuracia_esquema": taxa(
            sum(1 for item in itens if item["esquema_ok"])
        ),
        "falhas_parsing": sum(
            1 for item in itens if item["falha_parsing"]
        ),
        "taxa_falha_parsing": taxa(
            sum(1 for item in itens if item["falha_parsing"])
        ),
        "erros_execucao": sum(
            1 for item in itens if item["erro_execucao"]
        ),
        "taxa_erro_execucao": taxa(
            sum(1 for item in itens if item["erro_execucao"])
        ),
        "falhas_por_tipo": _falhas_por_tipo(itens),
        "latencia_ms": {
            "media": round(sum(latencias) / total, 3) if total else None,
            "p50": round(_percentil(latencias, 50), 3) if latencias else None,
            "p95": round(_percentil(latencias, 95), 3) if latencias else None,
            "min": round(min(latencias), 3) if latencias else None,
            "max": round(max(latencias), 3) if latencias else None,
        },
    }


def _agrupar(avaliacoes: list[dict], chave: str) -> dict:
    grupos = {}

    for item in avaliacoes:
        grupos.setdefault(item.get(chave) or "<sem>", []).append(item)

    return {
        nome: _resumo(itens)
        for nome, itens in sorted(grupos.items(), key=lambda par: par[0])
    }


def calcular_metricas(avaliacoes: list[dict]) -> dict:
    """Métricas globais, por tarefa, idioma e família, com confusão."""

    confusao = {}

    for item in avaliacoes:
        esperado = item["rotulo_esperado"]
        obtido = item["rotulo_obtido"]
        confusao.setdefault(esperado, {})
        confusao[esperado][obtido] = (
            confusao[esperado].get(obtido, 0) + 1
        )

    falhas = [
        {
            "id": item["id"],
            "tarefa": item["tarefa"],
            "idioma": item["idioma"],
            "erro_execucao": item["erro_execucao"],
            "tipo_falha": item.get("tipo_falha"),
            "diagnostico": item.get("diagnostico"),
            "falha_parsing": item["falha_parsing"],
            "erro_parsing": item.get("erro_parsing"),
            "erros_esquema": item.get("erros_esquema", []),
            "esperado": item.get("esperado"),
            "obtido": item.get("obtido"),
        }
        for item in avaliacoes
        if not item["correto"]
    ]

    return {
        "global": _resumo(avaliacoes),
        "por_tarefa": _agrupar(avaliacoes, "tarefa"),
        "por_idioma": _agrupar(avaliacoes, "idioma"),
        "por_familia": _agrupar(avaliacoes, "familia"),
        "confusao": confusao,
        "falhas": falhas[:MAX_FALHAS_RELATORIO],
        "total_falhas": len(falhas),
    }


def _filtrar(registros, tarefas=None, idiomas=None, limite=None):
    filtrados = [
        registro
        for registro in registros
        if (not tarefas or registro.get("tarefa") in tarefas)
        and (not idiomas or registro.get("idioma") in idiomas)
    ]

    if limite is not None:
        filtrados = filtrados[: int(limite)]

    return filtrados


def selecionar_split(
    registros,
    nome: str,
    caminho_manifesto=None,
) -> tuple[list[dict], dict]:
    """Seleciona os registros de um split validando o manifesto SHA-256.

    O manifesto é a fonte da verdade: além de conferir o SHA-256 do
    dataset completo, a validação recomputa a atribuição e recusa
    manifesto velho, adulterado ou com contagem divergente. Sem essa
    checagem, um split silenciosamente desatualizado contaminaria a
    avaliação sem que o relatório denunciasse o problema.
    """

    if nome not in split_mod.SPLITS:
        raise ValueError(f"split_desconhecido:{nome}")

    manifesto = split_mod.carregar_split(caminho_manifesto)
    problemas = split_mod.validar_split(registros, manifesto)

    if problemas:
        detalhes = "; ".join(
            f"{item.get('codigo')}:{item.get('detalhe')}"
            for item in problemas[:5]
        )
        raise ValueError(f"split_invalido: {detalhes}")

    ids = {
        identificador
        for item in manifesto.get("pares") or []
        if item.get("split") == nome
        for identificador in item.get("ids") or []
    }
    selecionados = [
        registro for registro in registros if registro.get("id") in ids
    ]
    resumo = (manifesto.get("por_split") or {}).get(nome) or {}

    if resumo.get("registros") not in (None, len(selecionados)):
        raise ValueError(
            "split_contagem_divergente: "
            f"manifesto={resumo.get('registros')} "
            f"selecionados={len(selecionados)}"
        )

    info = {
        "nome": nome,
        "manifesto": str(
            Path(
                caminho_manifesto
                if caminho_manifesto is not None
                else split_mod.ARQUIVO_SPLIT
            )
        ),
        "sha256_dataset": manifesto.get("sha256_dataset"),
        "total_registros_dataset": manifesto.get("total_registros"),
        "pares": resumo.get("pares", len(selecionados) // 2),
        "registros": len(selecionados),
        "por_tarefa": resumo.get("por_tarefa") or {},
        "por_idioma": resumo.get("por_idioma") or {},
    }

    return selecionados, info


def executar_benchmark(
    registros,
    preditor: Preditor,
    tarefas=None,
    idiomas=None,
    limite=None,
    incluir_resultados=False,
    caminho_dataset=None,
    prazo_registro_s: float | None = None,
    split_nome=None,
    caminho_split=None,
) -> dict:
    """Executa o benchmark e devolve um relatório serializável.

    prazo_registro_s é o tempo máximo por registro. None mantém o
    caminho rápido e delega o prazo ao próprio preditor (o preditor
    Ollama já usa timeout de socket); quando informado, um registro
    travado vira falha de execução explícita (TimeoutError) e o harness
    continua, sem interromper a execução inteira.

    split_nome restringe a avaliação a um split do manifesto,
    validando antes o SHA-256 do dataset completo e a atribuição
    declarada. Os filtros de tarefa, idioma e limite continuam sendo
    aplicados depois do recorte do split.
    """

    total_dataset = len(registros)
    info_split = None

    if split_nome is not None:
        registros, info_split = selecionar_split(
            registros,
            split_nome,
            caminho_split,
        )

    filtrados = _filtrar(registros, tarefas, idiomas, limite)
    antes = seguranca.capturar_banco()
    inicio = time.perf_counter()
    avaliacoes = [
        avaliar_registro(registro, preditor, prazo_registro_s)
        for registro in filtrados
    ]
    duracao_ms = (time.perf_counter() - inicio) * 1000
    depois = seguranca.capturar_banco()
    banco = seguranca.comparar_banco(antes, depois)

    relatorio = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preditor": getattr(preditor, "nome", type(preditor).__name__),
        "modelo": getattr(preditor, "modelo", None),
        "dataset": {
            "arquivo": str(caminho_dataset or gerador.ARQUIVO_PADRAO),
            "total": total_dataset,
            "avaliados": len(filtrados),
            "sha256": gerador.hash_registros(filtrados),
            "split": info_split,
        },
        "filtros": {
            "tarefas": list(tarefas) if tarefas else [],
            "idiomas": list(idiomas) if idiomas else [],
            "limite": limite,
            "split": split_nome,
        },
        "duracao_ms": round(duracao_ms, 3),
        "prazo_registro_s": prazo_registro_s,
        "metricas": calcular_metricas(avaliacoes),
        "db": banco,
        "db_intocado": banco["DB_INTOCADO"],
    }

    if incluir_resultados:
        relatorio["resultados"] = avaliacoes

    return relatorio


def _json_para_arquivo(relatorio: dict, caminho: Path) -> None:
    """Grava o relatório JSON de forma atômica (sem artefato parcial)."""

    arquivo_seguro.gravar_texto_atomico(
        caminho,
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
    )


def _pct(valor) -> str:
    if valor is None:
        return "-"

    return f"{100 * valor:.2f}%"


def _ms(valor) -> str:
    return "-" if valor is None else f"{valor:.3f}"


def _linhas_diagnostico(global_: dict) -> list[str]:
    """Tabela de contagem por categoria de falha."""

    tipos = global_.get("falhas_por_tipo") or {}

    if not tipos:
        return ["| - | 0 | nenhuma falha |"]

    return [
        (
            f"| {tipo} | {quantidade} | "
            f"{DIAGNOSTICOS.get(tipo, 'não classificado')} |"
        )
        for tipo, quantidade in tipos.items()
    ]


def relatorio_markdown(relatorio: dict) -> str:
    """Renderiza o relatório em Markdown, sem depender da interface."""

    metricas = relatorio["metricas"]
    global_ = metricas["global"]
    linhas = [
        "# Benchmark comportamental — NexusGeo IA",
        "",
        f"- Preditor: {relatorio['preditor']}",
        f"- Modelo: {relatorio['modelo'] or '-'}",
        f"- Dataset: {relatorio['dataset']['arquivo']}",
        (
            f"- Registros avaliados: {relatorio['dataset']['avaliados']} "
            f"de {relatorio['dataset']['total']}"
        ),
        f"- SHA-256 dos registros avaliados: {relatorio['dataset']['sha256']}",
        *(
            [
                (
                    f"- Split: {relatorio['dataset']['split']['nome']} "
                    f"({relatorio['dataset']['split']['registros']} "
                    "registros, "
                    f"{relatorio['dataset']['split']['pares']} pares)"
                ),
                (
                    "- SHA-256 do dataset no manifesto: "
                    f"{relatorio['dataset']['split']['sha256_dataset']}"
                ),
                (
                    "- Manifesto do split: "
                    f"{relatorio['dataset']['split']['manifesto']}"
                ),
            ]
            if relatorio["dataset"].get("split")
            else []
        ),
        f"- Duração: {relatorio['duracao_ms']:.3f} ms",
        f"- DB_INTOCADO: {relatorio['db_intocado']}",
        "",
        "## Métricas globais",
        "",
        "| Métrica | Valor |",
        "| --- | --- |",
        f"| Acurácia de rótulo/esquema | {_pct(global_['acuracia'])} |",
        f"| Esquema válido | {_pct(global_['acuracia_esquema'])} |",
        f"| Falha de parsing | {_pct(global_['taxa_falha_parsing'])} |",
        f"| Erro de execução | {_pct(global_['taxa_erro_execucao'])} |",
        f"| Latência média (ms) | {_ms(global_['latencia_ms']['media'])} |",
        f"| Latência p50 (ms) | {_ms(global_['latencia_ms']['p50'])} |",
        f"| Latência p95 (ms) | {_ms(global_['latencia_ms']['p95'])} |",
        "",
        "## Diagnóstico das falhas",
        "",
        "| Tipo | Falhas | Descrição |",
        "| --- | ---: | --- |",
        *_linhas_diagnostico(global_),
        "",
        "## Por tarefa",
        "",
        "| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for tarefa, dados in metricas["por_tarefa"].items():
        rotulo = contrato.ROTULOS_TAREFA.get(tarefa, {}).get("pt", tarefa)
        linhas.append(
            f"| {rotulo} | {dados['total']} | {_pct(dados['acuracia'])} | "
            f"{_pct(dados['acuracia_esquema'])} | "
            f"{_pct(dados['taxa_falha_parsing'])} | "
            f"{_ms(dados['latencia_ms']['p95'])} |"
        )

    linhas.extend(
        [
            "",
            "## Por idioma",
            "",
            "| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )

    for idioma, dados in metricas["por_idioma"].items():
        linhas.append(
            f"| {idioma} | {dados['total']} | {_pct(dados['acuracia'])} | "
            f"{_pct(dados['taxa_falha_parsing'])} | "
            f"{_ms(dados['latencia_ms']['p95'])} |"
        )

    linhas.extend(
        [
            "",
            "## Falhas (amostra)",
            "",
            "| ID | Tarefa | Motivo |",
            "| --- | --- | --- |",
        ]
    )

    if metricas["falhas"]:
        for falha in metricas["falhas"]:
            motivo = (
                falha.get("diagnostico")
                or falha.get("tipo_falha")
                or falha.get("erro_execucao")
                or ("parsing" if falha.get("falha_parsing") else "divergência")
            )
            linhas.append(f"| {falha['id']} | {falha['tarefa']} | {motivo} |")
    else:
        linhas.append("| - | - | nenhuma falha |")

    linhas.append("")
    return "\n".join(linhas)


def _escrever_markdown(relatorio: dict, caminho: Path) -> None:
    """Grava o relatório Markdown de forma atômica."""

    arquivo_seguro.gravar_texto_atomico(
        caminho,
        relatorio_markdown(relatorio),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o dataset comportamental do NexusGeo IA.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=(
            "JSONL do dataset. Sem o argumento, usa o dataset padrão e o "
            "gera se ainda não existir. Um caminho explícito inexistente "
            "é erro e não gera arquivo."
        ),
    )
    parser.add_argument(
        "--split",
        choices=split_mod.SPLITS,
        default=None,
        help=(
            "Restringe a avaliação a um split do manifesto (treino, "
            "validacao ou teste), validando o SHA-256 do dataset e a "
            "atribuição declarada."
        ),
    )
    parser.add_argument(
        "--split-manifesto",
        type=Path,
        default=None,
        help=(
            "Manifesto .split.json alternativo. Sem o argumento, usa o "
            "manifesto padrão do dataset comportamental."
        ),
    )
    parser.add_argument(
        "--preditor",
        choices=("oraculo", "falha", "ruido", "ollama"),
        default="oraculo",
    )
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument(
        "--tarefa",
        action="append",
        choices=contrato.TAREFAS,
        default=None,
    )
    parser.add_argument(
        "--idioma",
        action="append",
        choices=contrato.IDIOMAS,
        default=None,
    )
    parser.add_argument("--ollama-modelo", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--ollama-seed", type=int, default=SEMENTE_PADRAO)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--prazo-registro",
        type=float,
        default=None,
        help=(
            "Tempo máximo por registro, em segundos. Sem valor, o prazo "
            "é o do próprio preditor."
        ),
    )
    parser.add_argument("--json-saida", type=Path, default=None)
    parser.add_argument("--relatorio-md", type=Path, default=None)
    parser.add_argument("--resultados", action="store_true")
    parser.add_argument("--json", action="store_true")
    argumentos = parser.parse_args(argv)

    if argumentos.dataset is None:
        # Sem --dataset, o dataset padrão pode ser gerado (comportamento
        # histórico do gerador). Um caminho explícito nunca é criado.
        caminho = Path(gerador.ARQUIVO_PADRAO)

        if not caminho.is_file():
            try:
                gerador.gravar_dataset(destino=caminho)
            except OSError as erro:
                print(
                    "Não foi possível gerar o dataset padrão em "
                    f"{caminho}: {erro}",
                    file=sys.stderr,
                )
                return 2
    else:
        caminho = Path(argumentos.dataset).expanduser()

        if not caminho.exists():
            print(
                f"Dataset não encontrado: {caminho}. Nenhum arquivo foi "
                "gerado; informe um JSONL existente em --dataset ou rode "
                "'python -m finetuning.gerador' para criar o dataset padrão.",
                file=sys.stderr,
            )
            return 2

        if not caminho.is_file():
            print(
                "--dataset deve apontar para um arquivo JSONL, não para um "
                f"diretório: {caminho}",
                file=sys.stderr,
            )
            return 2

    registros = gerador.carregar_registros(caminho)

    if argumentos.split is not None:
        # Falha cedo, antes de contatar o Ollama, quando o manifesto
        # está velho, adulterado ou a atribuição não fecha com o
        # dataset informado.
        try:
            selecionar_split(
                registros,
                argumentos.split,
                argumentos.split_manifesto,
            )
        except ValueError as erro:
            print(f"Split inválido: {erro}", file=sys.stderr)
            return 2

    if argumentos.preditor == "oraculo":
        preditor = PreditorOraculo()
    elif argumentos.preditor == "falha":
        preditor = PreditorFalha()
    elif argumentos.preditor == "ruido":
        preditor = PreditorRuido()
    else:
        preditor = PreditorOllama(
            modelo=argumentos.ollama_modelo,
            host=argumentos.ollama_host,
            timeout=argumentos.timeout,
            seed=argumentos.ollama_seed,
        )

        if not preditor.disponivel():
            print(
                f"Ollama indisponível em {preditor.host}; "
                "use --preditor oraculo ou inicie o serviço local.",
                file=sys.stderr,
            )
            return 2

    relatorio = executar_benchmark(
        registros,
        preditor,
        tarefas=argumentos.tarefa,
        idiomas=argumentos.idioma,
        limite=argumentos.limite,
        incluir_resultados=argumentos.resultados,
        caminho_dataset=caminho,
        prazo_registro_s=argumentos.prazo_registro,
        split_nome=argumentos.split,
        caminho_split=argumentos.split_manifesto,
    )

    try:
        if argumentos.json_saida:
            _json_para_arquivo(relatorio, Path(argumentos.json_saida))

        if argumentos.relatorio_md:
            _escrever_markdown(relatorio, Path(argumentos.relatorio_md))
    except OSError as erro:
        # A falha de escrita é o erro da etapa de relatório: mensagem
        # clara no stderr e código 1, sem traceback nem artefato parcial.
        print(
            f"Falha ao gravar o relatório do benchmark: {erro}",
            file=sys.stderr,
        )
        return 1

    if argumentos.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        global_ = relatorio["metricas"]["global"]
        print(
            f"preditor={relatorio['preditor']} "
            f"total={global_['total']} "
            f"acuracia={_pct(global_['acuracia'])} "
            f"esquema={_pct(global_['acuracia_esquema'])} "
            f"falha_parsing={_pct(global_['taxa_falha_parsing'])} "
            f"p50_ms={_ms(global_['latencia_ms']['p50'])} "
            f"p95_ms={_ms(global_['latencia_ms']['p95'])}"
        )

    print(f"DB_INTOCADO={relatorio['db_intocado']}")

    return 0 if relatorio["db_intocado"] else 1


if __name__ == "__main__":
    sys.exit(main())
