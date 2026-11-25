"""Montador de contexto com orçamento de tokens (Fase D1).

O roteiro de UX do dashboard define quatro faixas para a janela do
modelo local:

* 15% — identidade, regras e estado espacial;
* 45% — evidências recuperadas;
* 25% — sessão e resumo progressivo (incluindo a pergunta atual);
* 15% — margem reservada para a geração.

Este módulo não chama o Ollama e não estima tokens com um tokenizer
externo: usa uma heurística estável (4 caracteres por token), suficiente
para impedir que um contexto grande estoure a janela e para manter a
D1 determinística nos testes. A margem de 15% nunca entra no texto
enviado ao modelo; ela fica reservada para a resposta.

As evidências são ordenadas por score/relevância quando o chamador
fornece esse campo. Mensagens antigas são descartadas antes das novas,
e a pergunta atual tem prioridade dentro da faixa de sessão.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

CARACTERES_POR_TOKEN = 4

PERCENTUAIS_CONTEXTO = {
    "identidade": 0.15,
    "evidencias": 0.45,
    "sessao": 0.25,
    "margem_geracao": 0.15,
}

# Alias mantido para leitura do roteiro e para integrações futuras.
PERCENTUAIS_ROTEIRO = PERCENTUAIS_CONTEXTO

MARGEM_GERACAO = PERCENTUAIS_CONTEXTO["margem_geracao"]

_ROTULOS_SECAO = {
    "identidade": "identidade_regras",
    "evidencias": "evidencias",
    "sessao": "sessao_resumo",
}

_PAPEIS_MENSAGEM = {
    "user": "Usuário",
    "assistant": "Assistente",
    "system": "Sistema",
}


def estimar_tokens(texto, caracteres_por_token=CARACTERES_POR_TOKEN):
    """Estima tokens por contagem de caracteres, com mínimo de 1."""

    if texto is None:
        return 0

    if not isinstance(caracteres_por_token, int) or caracteres_por_token <= 0:
        raise ValueError("caracteres_por_token deve ser um inteiro positivo.")

    tamanho = len(str(texto))

    if tamanho == 0:
        return 0

    return max(1, math.ceil(tamanho / caracteres_por_token))


def _normalizar_percentuais(percentuais=None):
    """Valida as quatro faixas e devolve frações que somam 1."""

    origem = dict(PERCENTUAIS_CONTEXTO)

    if percentuais:
        desconhecidas = set(percentuais) - set(origem)

        if desconhecidas:
            raise ValueError(
                "Faixa de contexto desconhecida: "
                + ", ".join(sorted(desconhecidas))
            )

        origem.update(percentuais)

    valores = {}

    for chave, valor_bruto in origem.items():
        try:
            valores[chave] = float(valor_bruto)
        except (TypeError, ValueError) as erro:
            raise ValueError(
                f"Percentual inválido para {chave}."
            ) from erro

        if valores[chave] < 0:
            raise ValueError(f"Percentual negativo para {chave}.")

    total = sum(valores.values())

    # Aceita tanto 0.15 quanto 15 (porcentagem) e normaliza para fração.
    if total > 1.5:
        valores = {
            chave: valor / 100.0 for chave, valor in valores.items()
        }
        total = sum(valores.values())

    if abs(total - 1.0) > 0.01:
        raise ValueError("Os percentuais de contexto devem somar 100%.")

    if valores["margem_geracao"] <= 0:
        raise ValueError("A margem de geração deve ser maior que zero.")

    return valores


def calcular_orcamento(limite_tokens, percentuais=None):
    """Divide a janela em tokens por faixa, deixando a margem intacta."""

    if not isinstance(limite_tokens, int) or limite_tokens <= 0:
        raise ValueError("limite_tokens deve ser um inteiro positivo.")

    fracoes = _normalizar_percentuais(percentuais)

    identidade = math.floor(limite_tokens * fracoes["identidade"])
    evidencias = math.floor(limite_tokens * fracoes["evidencias"])
    sessao = math.floor(limite_tokens * fracoes["sessao"])
    margem = limite_tokens - identidade - evidencias - sessao

    return {
        "limite_tokens": limite_tokens,
        "identidade": identidade,
        "evidencias": evidencias,
        "sessao": sessao,
        "margem_geracao": margem,
        "entrada": identidade + evidencias + sessao,
        "percentuais": fracoes,
    }


def _limitar_texto(texto, limite_tokens):
    """Corta um texto para caber no limite, sem ultrapassar a estiva."""

    texto = str(texto or "")

    if limite_tokens <= 0:
        return "", bool(texto)

    if estimar_tokens(texto) <= limite_tokens:
        return texto, False

    if limite_tokens <= 2:
        corte = texto[:max(0, limite_tokens * CARACTERES_POR_TOKEN)]
        return corte, True

    capacidade = max(
        0,
        limite_tokens * CARACTERES_POR_TOKEN - 1,
    )
    corte = texto[:capacidade]

    # Prefere terminar em uma quebra de linha ou espaço próximo do fim,
    # evitando cortar uma palavra no meio quando há alternativa.
    for separador in ("\n", " "):
        posicao = corte.rfind(separador)

        if posicao >= int(capacidade * 0.6):
            corte = corte[:posicao]
            break

    resultado = corte.rstrip() + "…"

    while estimar_tokens(resultado) > limite_tokens and len(resultado) > 1:
        resultado = resultado[:-2] + "…"

    return resultado, True


@dataclass(frozen=True)
class BlocoContexto:
    """Uma faixa do contexto já ajustada ao seu orçamento."""

    nome: str
    conteudo: str
    limite_tokens: int
    truncado: bool = False

    @property
    def tokens_estimados(self):
        """Tokens aproximados do conteúdo deste bloco."""

        return estimar_tokens(self.conteudo)

    def para_dict(self):
        """Representação serializável do bloco."""

        return {
            "nome": self.nome,
            "conteudo": self.conteudo,
            "limite_tokens": self.limite_tokens,
            "tokens_estimados": self.tokens_estimados,
            "truncado": self.truncado,
        }


@dataclass(frozen=True)
class ContextoMontado:
    """Resultado completo do montador, com orçamento e descartes."""

    texto: str
    blocos: tuple[BlocoContexto, ...]
    orcamento: dict[str, Any] = field(default_factory=dict)
    descartes: tuple[str, ...] = ()

    @property
    def tokens_estimados(self):
        """Tokens aproximados do texto final, incluindo as tags."""

        return estimar_tokens(self.texto)

    @property
    def tokens_disponiveis(self):
        """Soma das faixas de entrada (sem a margem de geração)."""

        return sum(
            bloco.limite_tokens for bloco in self.blocos
        )

    @property
    def margem_geracao_tokens(self):
        """Margem reservada para a resposta do modelo."""

        return int(self.orcamento.get("margem_geracao", 0))

    def bloco(self, nome):
        """Devolve um bloco pelo nome, ou None."""

        for bloco in self.blocos:
            if bloco.nome == nome:
                return bloco

        return None

    def para_dict(self):
        """Representação serializável do contexto completo."""

        return {
            "texto": self.texto,
            "blocos": [bloco.para_dict() for bloco in self.blocos],
            "orcamento": self.orcamento,
            "descartes": list(self.descartes),
            "tokens_estimados": self.tokens_estimados,
            "tokens_disponiveis": self.tokens_disponiveis,
            "margem_geracao_tokens": self.margem_geracao_tokens,
        }


def _score_evidencia(item):
    """Score numérico opcional, usado para priorizar a recuperação."""

    if not isinstance(item, dict):
        return None

    for chave in ("score", "relevancia", "rank", "similaridade"):
        valor = item.get(chave)

        if valor is None or isinstance(valor, bool):
            continue

        try:
            return float(valor)
        except (TypeError, ValueError):
            continue

    return None


def _formatar_evidencia(item, indice):
    """Formata uma evidência heterogênea como bloco textual estável."""

    if item is None:
        return ""

    if isinstance(item, str):
        return item.strip()

    if not isinstance(item, dict):
        return str(item).strip()

    evidence_id = (
        item.get("evidence_id")
        or item.get("evidencia_id")
        or item.get("id")
        or f"E{indice + 1}"
    )
    fonte = item.get("fonte") or item.get("source") or ""
    titulo = item.get("titulo") or item.get("title") or ""
    texto = (
        item.get("texto")
        or item.get("conteudo")
        or item.get("content")
        or item.get("trecho")
        or item.get("resumo")
        or ""
    )

    cabecalho = f"[{evidence_id}]"

    if fonte:
        cabecalho += f" {fonte}"

    if titulo:
        cabecalho += f" — {titulo}"

    if texto:
        return f"{cabecalho}\n{texto}".strip()

    return cabecalho


def _montar_evidencias(itens, limite_tokens, descartes):
    """Empacota evidências priorizadas até o limite da faixa."""

    if not itens:
        return "", False

    itens = list(itens)
    pontuados = [(item, _score_evidencia(item)) for item in itens]

    if any(score is not None for _, score in pontuados):
        pontuados.sort(
            key=lambda par: (
                par[1] is not None,
                par[1] if par[1] is not None else float("-inf"),
            ),
            reverse=True,
        )

    # Sem score, a ordem de recuperação original é preservada.
    ordenados = [item for item, _ in pontuados]

    partes = []
    truncado = False

    for indice, item in enumerate(ordenados):
        formatado = _formatar_evidencia(item, indice)

        if not formatado:
            continue

        tentativa = "\n\n".join([*partes, formatado])

        if estimar_tokens(tentativa) <= limite_tokens:
            partes.append(formatado)
            continue

        if not partes:
            corte, _ = _limitar_texto(formatado, limite_tokens)
            if corte:
                partes.append(corte)
                truncado = True
            continue

        descartes.append(f"evidencia:{indice}")

    return "\n\n".join(partes), truncado


def _formatar_mensagem(mensagem):
    """Formata uma mensagem de histórico para o bloco de sessão."""

    if isinstance(mensagem, str):
        return mensagem.strip()

    if not isinstance(mensagem, dict):
        return str(mensagem).strip()

    papel = str(mensagem.get("role") or "assistant").strip().lower()
    rotulo = _PAPEIS_MENSAGEM.get(papel, "Assistente")
    conteudo = str(
        mensagem.get("content")
        or mensagem.get("conteudo")
        or ""
    ).strip()

    if not conteudo:
        return ""

    return f"{rotulo}: {conteudo}"


def _montar_sessao(
    pergunta,
    resumo,
    mensagens,
    limite_tokens,
    descartes,
):
    """Monta pergunta, resumo progressivo e histórico recente."""

    if limite_tokens <= 0:
        return "", bool(pergunta or resumo or mensagens)

    partes = []
    truncado = False

    pergunta = str(pergunta or "").strip()

    if pergunta:
        texto_pergunta = f"Pergunta atual:\n{pergunta}"
        texto_pergunta, cortou = _limitar_texto(
            texto_pergunta,
            limite_tokens,
        )
        partes.append(texto_pergunta)
        truncado = truncado or cortou

    restante = limite_tokens - estimar_tokens("\n\n".join(partes))

    resumo = str(resumo or "").strip()

    if resumo and restante > 2:
        limite_resumo = max(1, int(restante * 0.4))
        texto_resumo, cortou = _limitar_texto(
            f"Resumo progressivo:\n{resumo}",
            min(restante, limite_resumo),
        )
        partes.append(texto_resumo)
        truncado = truncado or cortou
        restante = limite_tokens - estimar_tokens("\n\n".join(partes))

    if mensagens and restante > 2:
        selecionadas = []

        for indice_invertido, mensagem in enumerate(reversed(list(mensagens))):
            formatada = _formatar_mensagem(mensagem)

            if not formatada:
                continue

            tentativa = "\n".join([formatada, *selecionadas])
            if estimar_tokens(tentativa) <= restante:
                selecionadas.insert(0, formatada)
                continue

            if not selecionadas:
                corte, _ = _limitar_texto(formatada, restante)

                if corte:
                    selecionadas.insert(0, corte)
                    truncado = True
                    continue

            descartes.append(
                f"mensagem:{len(list(mensagens)) - 1 - indice_invertido}"
            )

        if selecionadas:
            partes.append(
                "Histórico recente:\n" + "\n".join(selecionadas)
            )

    texto = "\n\n".join(parte for parte in partes if parte)

    if estimar_tokens(texto) > limite_tokens:
        texto, _ = _limitar_texto(texto, limite_tokens)
        truncado = True

    return texto, truncado


def _montar_texto_final(blocos):
    """Concatena os blocos com tags simples e estáveis."""

    partes = []

    for bloco in blocos:
        if not bloco.conteudo:
            continue

        tag = _ROTULOS_SECAO[bloco.nome]
        partes.append(
            f"<{tag}>\n{bloco.conteudo}\n</{tag}>"
        )

    return "\n\n".join(partes)


def montar_contexto(
    identidade="",
    evidencias=None,
    resumo_sessao="",
    mensagens=None,
    pergunta="",
    limite_tokens=None,
    percentuais=None,
    sessao=None,
    historico=None,
):
    """Monta o contexto nas faixas 15/45/25, reservando 15% para geração.

    Parâmetros aceitos por conveniência:

    * sessao: dicionário com resumo/mensagens, alternativa aos argumentos;
    * historico: alias de mensagens, mantido para chamadores antigos;
    * limite_tokens: quando None, usa OLLAMA_NUM_CTX de config.py.

    Devolve ContextoMontado com texto, blocos, orçamento e descartes.
    """

    if limite_tokens is None:
        from config import OLLAMA_NUM_CTX

        limite_tokens = OLLAMA_NUM_CTX

    if not isinstance(limite_tokens, int) or limite_tokens <= 0:
        raise ValueError("limite_tokens deve ser um inteiro positivo.")

    if sessao is not None:
        if not isinstance(sessao, dict):
            raise ValueError("sessao deve ser um dicionário.")

        if not resumo_sessao:
            resumo_sessao = (
                sessao.get("resumo")
                or sessao.get("rolling_summary")
                or ""
            )

        if mensagens is None:
            mensagens = sessao.get("mensagens") or sessao.get("messages")

    if mensagens is None and historico is not None:
        mensagens = historico

    percentuais = _normalizar_percentuais(percentuais)
    orcamento = calcular_orcamento(limite_tokens, percentuais)

    descartes = []

    identidade_texto, identidade_truncada = _limitar_texto(
        identidade,
        orcamento["identidade"],
    )

    evidencias_texto, evidencias_truncadas = _montar_evidencias(
        evidencias,
        orcamento["evidencias"],
        descartes,
    )

    sessao_texto, sessao_truncada = _montar_sessao(
        pergunta,
        resumo_sessao,
        mensagens or [],
        orcamento["sessao"],
        descartes,
    )

    blocos = (
        BlocoContexto(
            nome="identidade",
            conteudo=identidade_texto,
            limite_tokens=orcamento["identidade"],
            truncado=identidade_truncada,
        ),
        BlocoContexto(
            nome="evidencias",
            conteudo=evidencias_texto,
            limite_tokens=orcamento["evidencias"],
            truncado=evidencias_truncadas,
        ),
        BlocoContexto(
            nome="sessao",
            conteudo=sessao_texto,
            limite_tokens=orcamento["sessao"],
            truncado=sessao_truncada,
        ),
    )

    texto = _montar_texto_final(blocos)

    return ContextoMontado(
        texto=texto,
        blocos=blocos,
        orcamento=orcamento,
        descartes=tuple(descartes),
    )


# Alias semântico para chamadores que preferem o verbo "construir".
construir_contexto = montar_contexto
