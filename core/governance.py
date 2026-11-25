"""Governança do contrato de saída do LLM (Fase D1).

O modelo local é livre para produzir Markdown, mas a camada de governança
precisa de uma estrutura mínima para auditar o que foi afirmado. O
contrato esperado é::

    {
      "answer_markdown": "...",
      "claims": [
        {"texto": "...", "classificacao": "OBSERVED", "evidence_id": "ev_1"},
        {"texto": "...", "classificacao": "INFERRED"}
      ],
      "veredito": "PASS"
    }

Regras aplicadas nesta versão enxuta:

* OBSERVED exige evidence_id. Sem ele, a afirmação é rebaixada para
  INFERRED e o resultado vira HOLD, nunca um traceback;
* INFERRED não precisa de evidência, mas se apontar para um id fora do
  catálogo recebido, o vínculo é removido e o resultado vira HOLD;
* o veredito final é PASS, HOLD ou FAIL. O modelo não tem autoridade
  para declarar PASS quando a validação encontra um problema;
* texto livre, JSON inválido ou contrato incompleto caem no fallback
  seguro: a resposta é preservada e o veredito é HOLD;
* falhas de rede, TLS, timeout e HTTP viram HOLD com motivo objetivo,
  sem expor traceback, URL ou detalhe interno na interface.

Os textos de motivo são resolvidos por utils.i18n (chaves
governanca_motivo_*), mantendo a regra de interface bilíngue do projeto.
O módulo não abre interface, não acessa a rede e não importa Streamlit.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import unicodedata
import urllib.error
from dataclasses import dataclass, field
from typing import Any

from utils.i18n import tf

CLASSIFICACOES = ("OBSERVED", "INFERRED")
VEREDITOS = ("PASS", "HOLD", "FAIL")

VEREDITO_FALHA_FONTE = "HOLD"
VEREDITO_FALLBACK = "HOLD"

_CHAVES_CONTRATO = (
    "answer_markdown",
    "answer",
    "resposta",
    "claims",
    "afirmacoes",
    "veredito",
    "verdict",
    "governance_verdict",
)

_CHAVES_RESPOSTA = (
    "answer_markdown",
    "answer",
    "resposta",
    "texto",
    "content",
    "markdown",
)

_CHAVES_AFIRMACOES = (
    "claims",
    "afirmacoes",
    "claims_records",
    "claim_records",
    "afirmacoes_estruturadas",
)

_CHAVES_VEREDITO = (
    "veredito",
    "verdict",
    "governance_verdict",
)

_CHAVES_TEXTO_AFIRMACAO = (
    "texto",
    "text",
    "afirmacao",
    "claim",
    "conteudo",
)

_CHAVES_CLASSIFICACAO = (
    "classificacao",
    "classification",
    "tipo",
    "kind",
)

_CHAVES_EVIDENCIA = (
    "evidence_id",
    "evidencia_id",
    "evidence",
    "evidencia",
    "source_id",
)

_MOTIVOS_I18N = {
    "texto_livre": "governanca_motivo_texto_livre",
    "resposta_vazia": "governanca_motivo_resposta_vazia",
    "contrato_invalido": "governanca_motivo_contrato_invalido",
    "observado_sem_evidencia": "governanca_motivo_observado_sem_evidencia",
    "evidencia_desconhecida": "governanca_motivo_evidencia_desconhecida",
    "classificacao_desconhecida": "governanca_motivo_classificacao_desconhecida",
    "veredito_invalido": "governanca_motivo_veredito_invalido",
    "falha_declarada": "governanca_motivo_falha_declarada",
    "veredito_declarado_hold": "governanca_motivo_veredito_hold",
    "fonte_timeout": "governanca_motivo_fonte_timeout",
    "fonte_tls": "governanca_motivo_fonte_tls",
    "fonte_rede": "governanca_motivo_fonte_rede",
    "fonte_http": "governanca_motivo_fonte_http",
    "fonte_indisponivel": "governanca_motivo_fonte_indisponivel",
    "contrato_valido": "governanca_motivo_contrato_valido",
}


def _sem_acento(texto):
    """Maiúsculas sem acento, para comparar classificações e vereditos."""

    decomposto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    ).strip().upper()


def _motivo(codigo, idioma=None, **valores):
    """Traduz um código de motivo mantendo fallback para o próprio código."""

    chave = _MOTIVOS_I18N.get(codigo)

    if not chave:
        return str(codigo)

    return tf(chave, idioma, **valores)


def normalizar_veredito(valor):
    """Normaliza PASS/HOLD/FAIL; devolve None para valor desconhecido."""

    normalizado = _sem_acento(valor)

    if normalizado in VEREDITOS:
        return normalizado

    return None


def normalizar_classificacao(valor):
    """Normaliza OBSERVED/INFERRED e sinônimos em português e inglês."""

    normalizado = _sem_acento(valor)

    if normalizado in ("OBSERVED", "OBSERVADO", "OBSERVADA", "OBSERVACAO",
                       "OBSERVATION", "FATO", "FACT"):
        return "OBSERVED"

    if normalizado in ("INFERRED", "INFERIDO", "INFERIDA", "INFERENCIA",
                       "INFERENCE", "ESTIMATIVA", "HIPOTESE", "HYPOTHESIS"):
        return "INFERRED"

    return None


def classificar_afirmacao(texto, evidence_id=None):
    """Classifica uma afirmação a partir da presença de evidência.

    É a regra mínima da D1: com evidence_id, OBSERVED; sem ele,
    INFERRED. O texto é aceito mas não altera a decisão.
    """

    del texto

    if str(evidence_id or "").strip():
        return "OBSERVED"

    return "INFERRED"


# ---------------------------------------------------------------------------
# Falhas de fonte: indisponibilidade vira HOLD, nunca traceback
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FalhaFonte:
    """Descrição pública e estável de uma fonte indisponível."""

    categoria: str
    motivo_codigo: str
    motivo: str
    status_http: int | None = None
    tipo_tecnico: str = ""
    veredito: str = VEREDITO_FALHA_FONTE

    def para_dict(self):
        """Representação serializável para logs e testes."""

        return {
            "categoria": self.categoria,
            "motivo_codigo": self.motivo_codigo,
            "motivo": self.motivo,
            "status_http": self.status_http,
            "tipo_tecnico": self.tipo_tecnico,
            "veredito": self.veredito,
        }


def _status_http(erro):
    """Extrai um status HTTP inteiro de exceções conhecidas."""

    resposta = getattr(erro, "response", None)
    status = getattr(resposta, "status_code", None)

    if status is None:
        status = getattr(erro, "code", None)

    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _categoria_falha(erro):
    """Classifica a exceção sem revelar a mensagem original na UI."""

    nome = type(erro).__name__.lower()
    status = _status_http(erro)

    if isinstance(erro, ssl.SSLError):
        return "tls", status

    if isinstance(erro, ssl.CertificateError):
        return "tls", status

    if "ssl" in nome or "certificate" in nome or "certificado" in nome:
        return "tls", status

    if isinstance(erro, (TimeoutError, socket.timeout)):
        return "timeout", status

    if "timeout" in nome or "timedout" in nome:
        return "timeout", status

    if isinstance(erro, urllib.error.HTTPError):
        return "http", status or getattr(erro, "code", None)

    if "httperror" in nome or "http_error" in nome:
        return "http", status

    motivo_interno = getattr(erro, "reason", None)

    if motivo_interno is not None:
        nome_interno = type(motivo_interno).__name__.lower()

        if isinstance(motivo_interno, ssl.SSLError):
            return "tls", status

        if isinstance(motivo_interno, (TimeoutError, socket.timeout)):
            return "timeout", status

        if "timeout" in nome_interno:
            return "timeout", status

        if "ssl" in nome_interno or "certificate" in nome_interno:
            return "tls", status

    if isinstance(erro, (ConnectionError, urllib.error.URLError, OSError)):
        return "rede", status

    if "connection" in nome or "network" in nome or "unreachable" in nome:
        return "rede", status

    return "indisponivel", status


def classificar_falha_fonte(erro, idioma=None):
    """Converte uma exceção de fonte em FalhaFonte com veredito HOLD.

    A mensagem pública é objetiva e não inclui a mensagem crua da
    exceção, o traceback, a URL ou cabeçalhos — dados que poderiam
    vazar caminho local, credencial ou detalhe de TLS.
    """

    categoria, status = _categoria_falha(erro)

    if categoria == "timeout":
        codigo = "fonte_timeout"
    elif categoria == "tls":
        codigo = "fonte_tls"
    elif categoria == "http":
        codigo = "fonte_http"
    elif categoria == "rede":
        codigo = "fonte_rede"
    else:
        codigo = "fonte_indisponivel"

    if codigo == "fonte_http":
        motivo = _motivo(codigo, idioma, status=status or "?")
    else:
        motivo = _motivo(codigo, idioma)

    return FalhaFonte(
        categoria=categoria,
        motivo_codigo=codigo,
        motivo=motivo,
        status_http=status,
        tipo_tecnico=type(erro).__name__,
        veredito=VEREDITO_FALHA_FONTE,
    )


# ---------------------------------------------------------------------------
# Afirmações e resultado da governança
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Afirmacao:
    """Afirmação normalizada e pronta para a camada de linhagem."""

    texto: str
    classificacao: str
    evidence_id: str | None = None
    motivo_codigo: str | None = None
    motivo: str | None = None

    def para_dict(self):
        """Representação serializável da afirmação."""

        return {
            "texto": self.texto,
            "classificacao": self.classificacao,
            "evidence_id": self.evidence_id,
            "motivo_codigo": self.motivo_codigo,
            "motivo": self.motivo,
        }


@dataclass(frozen=True)
class ResultadoGovernanca:
    """Resposta validada, afirmações e veredito final."""

    answer_markdown: str
    afirmacoes: tuple[Afirmacao, ...]
    veredito: str
    motivo_codigo: str
    motivo: str
    formato: str
    veredito_declarado: str | None = None
    avisos: tuple[str, ...] = ()
    falha_fonte: FalhaFonte | None = None
    contrato: dict[str, Any] = field(default_factory=dict)

    def para_dict(self):
        """Representação completa para persistência e testes."""

        return {
            "answer_markdown": self.answer_markdown,
            "afirmacoes": [
                afirmacao.para_dict() for afirmacao in self.afirmacoes
            ],
            "veredito": self.veredito,
            "motivo_codigo": self.motivo_codigo,
            "motivo": self.motivo,
            "formato": self.formato,
            "veredito_declarado": self.veredito_declarado,
            "avisos": list(self.avisos),
            "falha_fonte": (
                self.falha_fonte.para_dict()
                if self.falha_fonte is not None
                else None
            ),
            "contrato": self.contrato,
        }


# ---------------------------------------------------------------------------
# Extração do contrato
# ---------------------------------------------------------------------------

def _primeiro_valor(payload, chaves):
    """Primeiro valor presente entre as chaves, ou um sentinela."""

    for chave in chaves:
        if chave in payload:
            return payload[chave]

    return _AUSENTE


_AUSENTE = object()

_PADRAO_BLOCO_JSON = re.compile(
    r"\x60{3}(?:json|JSON)?\s*(.*?)\x60{3}",
    re.DOTALL,
)


def _candidatos_json(texto):
    """Candidatos a JSON, do mais explícito ao mais tolerante."""

    candidatos = []

    for bruto in _PADRAO_BLOCO_JSON.findall(texto):
        candidatos.append(bruto.strip())

    candidatos.append(texto.strip())

    inicio = texto.find("{")
    fim = texto.rfind("}")

    if inicio != -1 and fim > inicio:
        candidatos.append(texto[inicio:fim + 1].strip())

    return candidatos


def extrair_contrato(texto):
    """Extrai um contrato JSON de texto livre ou de bloco cercado.

    Só aceita objetos que tenham ao menos uma chave conhecida do
    contrato; um JSON qualquer dentro da resposta não é confundido com
    o contrato de governança. Devolve None quando não encontra nada.
    """

    if not isinstance(texto, str) or not texto.strip():
        return None

    for candidato in _candidatos_json(texto):
        if not candidato:
            continue

        try:
            objeto = json.loads(candidato)
        except (TypeError, ValueError):
            continue

        if isinstance(objeto, dict) and any(
            chave in objeto for chave in _CHAVES_CONTRATO
        ):
            return objeto

    return None


def _payload_de_entrada(saida_modelo):
    """Normaliza a entrada para um dicionário de contrato ou None."""

    if isinstance(saida_modelo, dict):
        if any(chave in saida_modelo for chave in _CHAVES_CONTRATO):
            return saida_modelo

        return None

    if isinstance(saida_modelo, str):
        return extrair_contrato(saida_modelo)

    return None


def _texto_de_saida(saida_modelo):
    """Texto bruto da resposta, usado no fallback de formato livre."""

    if isinstance(saida_modelo, str):
        return saida_modelo.strip()

    if isinstance(saida_modelo, dict):
        valor = _primeiro_valor(saida_modelo, _CHAVES_RESPOSTA)

        if valor is not _AUSENTE and valor is not None:
            return str(valor).strip()

        return ""

    if saida_modelo is None:
        return ""

    return str(saida_modelo).strip()


def _texto_resposta(payload):
    """Resposta Markdown do contrato, sempre como string."""

    valor = _primeiro_valor(payload, _CHAVES_RESPOSTA)

    if valor is _AUSENTE or valor is None:
        return ""

    return str(valor).strip()


def _texto_afirmacao(item):
    """Texto de uma afirmação em formato dict ou string."""

    if isinstance(item, str):
        return item.strip()

    if not isinstance(item, dict):
        return ""

    valor = _primeiro_valor(item, _CHAVES_TEXTO_AFIRMACAO)

    if valor is _AUSENTE or valor is None:
        return ""

    return str(valor).strip()


def _avaliar_afirmacoes(
    lista,
    evidencias_validas,
    idioma,
    problemas,
    avisos,
):
    """Normaliza a lista de afirmações e registra os problemas."""

    afirmacoes = []
    catalogo = None

    if evidencias_validas is not None:
        catalogo = {str(item) for item in evidencias_validas}

    for item in lista:
        texto = _texto_afirmacao(item)

        if not texto:
            problemas.append("contrato_invalido")
            avisos.append(
                _motivo("contrato_invalido", idioma)
            )
            continue

        if isinstance(item, dict):
            classificacao_bruta = _primeiro_valor(
                item,
                _CHAVES_CLASSIFICACAO,
            )
            evidence_bruto = _primeiro_valor(item, _CHAVES_EVIDENCIA)
        else:
            classificacao_bruta = _AUSENTE
            evidence_bruto = _AUSENTE

        evidence_id = (
            str(evidence_bruto).strip()
            if evidence_bruto is not _AUSENTE and evidence_bruto is not None
            else ""
        ) or None

        if classificacao_bruta is _AUSENTE:
            classificacao = classificar_afirmacao(texto, evidence_id)
        else:
            classificacao = normalizar_classificacao(classificacao_bruta)

            if classificacao is None:
                problemas.append("classificacao_desconhecida")
                avisos.append(
                    _motivo("classificacao_desconhecida", idioma)
                )
                classificacao = "INFERRED"

        motivo_codigo = None
        motivo = None

        if (
            catalogo is not None
            and evidence_id is not None
            and evidence_id not in catalogo
        ):
            problemas.append("evidencia_desconhecida")
            motivo_codigo = "evidencia_desconhecida"
            motivo = _motivo(motivo_codigo, idioma)
            avisos.append(motivo)
            evidence_id = None

        if classificacao == "OBSERVED" and evidence_id is None:
            classificacao = "INFERRED"
            problemas.append("observado_sem_evidencia")
            motivo_codigo = "observado_sem_evidencia"
            motivo = _motivo(motivo_codigo, idioma)
            avisos.append(motivo)

        afirmacoes.append(
            Afirmacao(
                texto=texto,
                classificacao=classificacao,
                evidence_id=evidence_id,
                motivo_codigo=motivo_codigo,
                motivo=motivo,
            )
        )

    return afirmacoes


def _resultado(
    answer_markdown,
    afirmacoes,
    veredito,
    motivo_codigo,
    formato,
    idioma,
    veredito_declarado=None,
    avisos=(),
    falha_fonte=None,
    contrato=None,
):
    """Monta o ResultadoGovernanca com motivo já traduzido."""

    return ResultadoGovernanca(
        answer_markdown=answer_markdown,
        afirmacoes=tuple(afirmacoes),
        veredito=veredito,
        motivo_codigo=motivo_codigo,
        motivo=_motivo(motivo_codigo, idioma),
        formato=formato,
        veredito_declarado=veredito_declarado,
        avisos=tuple(dict.fromkeys(avisos)),
        falha_fonte=falha_fonte,
        contrato=contrato or {},
    )


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def avaliar_governanca(
    saida_modelo,
    evidencias_validas=None,
    erro_fonte=None,
    idioma=None,
):
    """Valida o contrato, classifica afirmações e calcula o veredito.

    Ordem de precedência do veredito:

    1. fonte indisponível -> HOLD (mesmo que o modelo tenha declarado
       outra coisa);
    2. resposta vazia -> FAIL;
    3. formato livre ou contrato com problema -> HOLD;
    4. FAIL declarado pelo modelo -> FAIL;
    5. HOLD declarado pelo modelo -> HOLD;
    6. tudo válido -> PASS.

    A função nunca levanta exceção por causa da saída do modelo.
    """

    falha = (
        classificar_falha_fonte(erro_fonte, idioma)
        if erro_fonte is not None
        else None
    )

    payload = _payload_de_entrada(saida_modelo)

    if payload is None:
        texto = _texto_de_saida(saida_modelo)

        if falha is not None:
            return _resultado(
                texto,
                [],
                "HOLD",
                falha.motivo_codigo,
                "texto_livre",
                idioma,
                avisos=[falha.motivo],
                falha_fonte=falha,
            )

        if not texto:
            return _resultado(
                "",
                [],
                "FAIL",
                "resposta_vazia",
                "texto_livre",
                idioma,
            )

        return _resultado(
            texto,
            [],
            "HOLD",
            "texto_livre",
            "texto_livre",
            idioma,
            avisos=[_motivo("texto_livre", idioma)],
        )

    answer_markdown = _texto_resposta(payload)
    problemas = []
    avisos = []

    if falha is not None:
        return _resultado(
            answer_markdown,
            [],
            "HOLD",
            falha.motivo_codigo,
            "contrato",
            idioma,
            avisos=[falha.motivo],
            falha_fonte=falha,
            contrato=payload,
        )

    if not answer_markdown:
        return _resultado(
            "",
            [],
            "FAIL",
            "resposta_vazia",
            "contrato",
            idioma,
            contrato=payload,
        )

    declarado_bruto = _primeiro_valor(payload, _CHAVES_VEREDITO)
    veredito_declarado = None

    if declarado_bruto is not _AUSENTE and declarado_bruto is not None:
        veredito_declarado = normalizar_veredito(declarado_bruto)

        if veredito_declarado is None:
            problemas.append("veredito_invalido")
            avisos.append(_motivo("veredito_invalido", idioma))

    claims_bruto = _primeiro_valor(payload, _CHAVES_AFIRMACOES)

    if claims_bruto is _AUSENTE:
        problemas.append("contrato_invalido")
        avisos.append(_motivo("contrato_invalido", idioma))
        lista_claims = []
    elif claims_bruto is None:
        lista_claims = []
    elif isinstance(claims_bruto, list):
        lista_claims = claims_bruto
    else:
        problemas.append("contrato_invalido")
        avisos.append(_motivo("contrato_invalido", idioma))
        lista_claims = []

    afirmacoes = _avaliar_afirmacoes(
        lista_claims,
        evidencias_validas,
        idioma,
        problemas,
        avisos,
    )

    if veredito_declarado == "FAIL":
        return _resultado(
            answer_markdown,
            afirmacoes,
            "FAIL",
            "falha_declarada",
            "contrato",
            idioma,
            veredito_declarado=veredito_declarado,
            avisos=avisos + [_motivo("falha_declarada", idioma)],
            contrato=payload,
        )

    if problemas:
        veredito = "HOLD"
        motivo_codigo = problemas[0]
    elif veredito_declarado == "HOLD":
        veredito = "HOLD"
        motivo_codigo = "veredito_declarado_hold"
        avisos.append(_motivo(motivo_codigo, idioma))
    else:
        veredito = "PASS"
        motivo_codigo = "contrato_valido"

    return _resultado(
        answer_markdown,
        afirmacoes,
        veredito,
        motivo_codigo,
        "contrato",
        idioma,
        veredito_declarado=veredito_declarado,
        avisos=avisos,
        contrato=payload,
    )


def resultado_falha_fonte(erro, answer_markdown="", idioma=None):
    """Atalho para converter uma falha de fonte em HOLD auditável."""

    falha = classificar_falha_fonte(erro, idioma)

    return _resultado(
        str(answer_markdown or "").strip(),
        [],
        "HOLD",
        falha.motivo_codigo,
        "texto_livre",
        idioma,
        avisos=[falha.motivo],
        falha_fonte=falha,
    )


# Aliases com nomes usados pelo restante do projeto e por integrações.
analisar_saida = avaliar_governanca
validar_contrato = avaliar_governanca
parse_saida = extrair_contrato
