"""Roteamento inteligente da fonte "Automático".

A decisão tem duas camadas:

1. **Regra objetiva:** sem documentos locais carregados, a consulta vai
   direto para o RIGeo — exceto quando a pergunta é uma consulta
   exclusiva de recursos hídricos (cita ANA, HidroWeb, SNIRH ou estação
   fluviométrica/pluviométrica sem geologia, mineração, SGB ou pedido
   de documento). Nesse caso a rota é dedicada à ANA:
   ``INTENCAO_ANA``, sem busca genérica no RIGeo, com o conector do
   HidroWeb ligado automaticamente.
2. **Classificação pelo Ollama:** com documentos locais, o modelo
   escolhido na barra lateral decide entre ``LOCAL_ONLY``,
   ``RIGEO_ONLY`` e ``HIBRIDO``. A decisão volta para a interface junto
   com a justificativa e as fontes que serão consultadas.

Se o Ollama falhar ou devolver uma classe inválida, o roteador cai numa
heurística por palavras-chave (a mesma lógica usada pelo restante do
projeto) e registra o motivo em ``aviso``. A heurística também reconhece
a consulta exclusiva da ANA. A consulta nunca é interrompida apenas
porque o classificador não respondeu.
"""

from pathlib import Path

from config import OLLAMA_MODEL
from core.source_router import (
    consulta_ana_exclusiva,
    fontes_relevantes
)
from services.llm_service import (
    ClassificacaoIntencaoError,
    classificar_intencao_fontes
)
from services.rag_service import listar_documentos


INTENCAO_LOCAL = "LOCAL_ONLY"
INTENCAO_RIGEO = "RIGEO_ONLY"
INTENCAO_HIBRIDO = "HIBRIDO"
INTENCAO_ANA = "ANA_ONLY"

# As chaves são as mesmas usadas em ``core.assistant.consultar_fonte`` e
# no dicionário de dados entregue ao modelo. A rota da ANA não consulta
# o RIGeo nem os documentos: ela só liga o conector do HidroWeb.
FONTES_POR_INTENCAO = {
    INTENCAO_LOCAL: ("documentos",),
    INTENCAO_RIGEO: ("sgb",),
    INTENCAO_HIBRIDO: ("sgb", "documentos"),
    INTENCAO_ANA: (),
}


def nomes_documentos(documentos):
    """Normaliza caminhos ou nomes em uma lista de nomes de arquivo."""

    nomes = []

    for documento in documentos or []:
        nome = Path(str(documento)).name.strip()

        if nome:
            nomes.append(nome)

    return nomes


def _intencao_por_heuristica(pergunta):
    """Alternativa sem LLM, usando os termos já conhecidos do projeto."""

    # Consulta exclusiva de recursos hídricos: a rota dedicada da ANA
    # vale também quando o classificador falha, para a pergunta não cair
    # na base documental por omissão.
    if consulta_ana_exclusiva(pergunta):
        return INTENCAO_ANA

    fontes = fontes_relevantes(pergunta)
    tem_documentos = "rag" in fontes
    tem_sgb = "sgb" in fontes

    if tem_documentos and tem_sgb:
        return INTENCAO_HIBRIDO

    if tem_documentos:
        return INTENCAO_LOCAL

    if tem_sgb:
        return INTENCAO_RIGEO

    # Com documentos carregados, uma pergunta sem termo reconhecido é
    # mais segura na base local: o RAG devolve vazio quando não há
    # aderência e o modelo ainda pode responder com conhecimento geral.
    return INTENCAO_LOCAL


def _justificativa_heuristica(intencao):
    rotulos = {
        INTENCAO_LOCAL: "somente os documentos locais",
        INTENCAO_RIGEO: "somente o RIGeo",
        INTENCAO_HIBRIDO: "os documentos locais e o RIGeo",
        INTENCAO_ANA: "somente o inventário de estações da ANA/HidroWeb"
    }

    return (
        "Classificação por palavras-chave: a pergunta aponta para "
        f"{rotulos[intencao]}."
    )


def _montar_resultado(
    intencao,
    origem,
    justificativa,
    documentos,
    modelo=None,
    aviso=None,
    usar_ana=False
):
    """Monta o contrato devolvido ao orquestrador e à interface."""

    return {
        "modo": "automatico",
        "intencao": intencao,
        "fontes": list(FONTES_POR_INTENCAO[intencao]),
        "origem": origem,
        "justificativa": justificativa,
        "modelo": modelo,
        "documentos_locais": documentos,
        # A rota dedicada liga o conector da ANA mesmo que a caixa da
        # barra lateral esteja desmarcada.
        "usar_ana": bool(usar_ana or intencao == INTENCAO_ANA),
        "aviso": aviso,
    }


def decidir_roteamento(
    pergunta,
    documentos=None,
    modelo=None,
    historico=None
):
    """Decide quais fontes a pergunta "Automático" deve consultar.

    ``documentos`` pode ser a lista devolvida por
    ``services.rag_service.listar_documentos``. Quando é ``None``, a
    lista é lida agora. O resultado contém a classe, as fontes em
    ordem de consulta, a origem da decisão (``regra``, ``llm`` ou
    ``heuristica``), a justificativa e os nomes dos documentos locais.
    """

    lista_documentos = (
        listar_documentos()
        if documentos is None
        else documentos
    )
    nomes = nomes_documentos(lista_documentos)

    if not nomes:
        # Antes da regra geral (RIGeo), reconhece a consulta exclusiva de
        # recursos hídricos: a ANA/HidroWeb é a fonte certa e a busca
        # genérica no RIGeo só acrescentaria artigos sem relação.
        if consulta_ana_exclusiva(pergunta):
            return _montar_resultado(
                INTENCAO_ANA,
                origem="regra",
                justificativa=(
                    "A pergunta cita explicitamente a ANA/HidroWeb e não "
                    "menciona geologia, mineração, SGB nem documentos "
                    "locais; a consulta vai direto ao inventário de "
                    "estações, sem busca genérica no RIGeo."
                ),
                documentos=[],
                modelo=None,
                usar_ana=True,
            )

        return _montar_resultado(
            INTENCAO_RIGEO,
            origem="regra",
            justificativa=(
                "Nenhum documento local carregado; a consulta segue "
                "direto para o RIGeo."
            ),
            documentos=[],
            modelo=None,
        )

    modelo_escolhido = modelo or OLLAMA_MODEL

    try:
        classificacao = classificar_intencao_fontes(
            pergunta,
            nomes,
            historico=historico,
            modelo=modelo_escolhido
        )
    except ClassificacaoIntencaoError as erro:
        intencao = _intencao_por_heuristica(pergunta)

        return _montar_resultado(
            intencao,
            origem="heuristica",
            justificativa=_justificativa_heuristica(
                intencao
            ),
            documentos=nomes,
            modelo=modelo_escolhido,
            aviso=f"Roteador LLM indisponível: {erro}",
        )

    return _montar_resultado(
        classificacao["intencao"],
        origem="llm",
        justificativa=classificacao.get("justificativa", ""),
        documentos=nomes,
        modelo=classificacao.get("modelo", modelo_escolhido),
    )
