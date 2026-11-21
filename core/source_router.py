import re
import unicodedata


# Termos que indicam consulta a documentos locais (RAG). As formas
# singular e plural precisam estar explícitas porque o casamento usa
# fronteira de palavra. Documentos carregados não disparam o RAG por si
# sós: a fonte só entra no modo Automático quando a pergunta cita estes
# termos.
PALAVRAS_DOCUMENTOS = [
    "documento",
    "documentos",
    "arquivo",
    "arquivos",
    "pdf",
    "pdfs",
    "artigo",
    "artigos",
    "manual",
    "manuais",
    "apostila",
    "apostilas",
    "texto",
    "textos"
]

# Termos ligados às geociências, à exploração mineral e à metalogênese.
PALAVRAS_SGB = [
    "geologia",
    "geologias",
    "geologico",
    "geologicos",
    "geologica",
    "geologicas",
    "mapeamento",
    "mapeamentos",
    "geoquimica",
    "geoquimico",
    "geoquimicos",
    "geoquimicas",
    "geofisica",
    "geofisico",
    "geofisicos",
    "geofisicas",
    "mineral",
    "minerais",
    "mineracao",
    "minerio",
    "minerios",
    "mineralizacao",
    "mineralizacoes",
    "jazida",
    "jazidas",
    "deposito",
    "depositos",
    "hidrotermal",
    "hidrotermais",
    "metalogenese",
    "metalogenetico",
    "metalogeneticos",
    "metalogenetica",
    "metalogeneticas",
    "paragenese",
    "craton",
    "cratons",
    "greenstone",
    "greenstones",
    "ouro",
    "cobre",
    "estanho",
    "granito",
    "granitos",
    "granitico",
    "graniticos",
    "bacia",
    "bacias",
    "provincia",
    "provincias",
    "tectonica",
    "tectonico",
    "tectonicos",
    "cisalhamento",
    "sgb",
    "rigeo",
    "geobusca",
    "cprm",
    "litologia",
    "estratigrafia",
    "afloramento",
    "afloramentos"
]

# Expressões de mais de uma palavra, casadas como sequência.
EXPRESSOES_SGB = [
    "terras raras",
    "terra rara",
    "elementos terras raras"
]

# Vocabulário exclusivo de recursos hídricos da ANA/HidroWeb. A sigla
# "ANA" não entra aqui porque é também nome próprio: ela só é
# reconhecida em maiúsculas, na própria pergunta.
PALAVRAS_ANA = [
    "hidroweb",
    "snirh",
    "fluviometrica",
    "fluviometricas",
    "fluviometrico",
    "fluviometricos",
    "pluviometrica",
    "pluviometricas",
    "pluviometrico",
    "pluviometricos",
    "hidrometrica",
    "hidrometricas",
    "hidrometrico",
    "hidrometricos",
    "telemetrica",
    "telemetricas",
    "telemetrico",
    "telemetricos"
]

EXPRESSOES_ANA = [
    "agencia nacional de aguas",
    "agencia nacional da agua",
    "agencia nacional de agua"
]

# Sinais de que a pergunta pertence ao acervo geocientífico do RIGeo.
# "bacia" fica de fora: é vocabulário hidrológico comum ("bacia do rio
# Negro") e não indica geologia nem mineração.
PALAVRAS_GEOLOGIA_MINERACAO = [
    palavra
    for palavra in PALAVRAS_SGB
    if palavra not in {"bacia", "bacias"}
]


def normalizar(texto):
    texto = unicodedata.normalize(
        "NFKD",
        texto.lower()
    )

    return "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )


def contem_palavra(texto, palavras):
    return any(
        re.search(
            rf"\b{re.escape(palavra)}\b",
            texto
        )
        for palavra in palavras
    )


def contem_expressao(texto, expressoes):
    """Casa expressões de várias palavras no texto já normalizado."""

    for expressao in expressoes:
        padrao = (
            r"\b"
            + r"\s+".join(
                re.escape(parte)
                for parte in normalizar(expressao).split()
            )
            + r"\b"
        )

        if re.search(padrao, texto):
            return True

    return False


def fontes_relevantes(pergunta):
    """Retorna o conjunto de fontes que a pergunta pode exigir.

    A fonte ``rag`` entra apenas quando a pergunta cita termos de
    documentos; a fonte ``sgb`` entra com termos de geociências,
    exploração mineral e metalogênese.
    """

    texto = normalizar(pergunta)
    fontes = set()

    if contem_palavra(texto, PALAVRAS_DOCUMENTOS):
        fontes.add("rag")

    if (
        contem_palavra(texto, PALAVRAS_SGB)
        or contem_expressao(texto, EXPRESSOES_SGB)
    ):
        fontes.add("sgb")

    return fontes


def consulta_ana_exclusiva(pergunta):
    """Diz se a pergunta pede apenas o inventário de estações da ANA.

    O caso é o de uma consulta de recursos hídricos explícita — cita
    "ANA" (em maiúsculas), "HidroWeb", "SNIRH", "estação fluviométrica"
    ou "estação pluviométrica" — sem menção a geologia, mineração ou SGB
    e sem pedido de documento/arquivo local. Nesse caso não faz sentido
    disparar a busca genérica no RIGeo, que devolveria artigos sem
    relação com a estação procurada: o roteador usa a rota dedicada da
    ANA, que consulta só o inventário do HidroWeb.
    """

    original = pergunta or ""
    texto = normalizar(original)

    cita_servico = (
        re.search(r"\bANA\b", original) is not None
        or contem_palavra(texto, PALAVRAS_ANA)
        or contem_expressao(texto, EXPRESSOES_ANA)
    )

    if not cita_servico:
        return False

    # Geologia, mineração ou SGB pedem o acervo do RIGeo junto com a
    # ANA; a rota deixa de ser exclusiva.
    if (
        contem_palavra(texto, PALAVRAS_GEOLOGIA_MINERACAO)
        or contem_expressao(texto, EXPRESSOES_SGB)
    ):
        return False

    # Pedido explícito de documento/arquivo mantém o RAG no circuito.
    if contem_palavra(texto, PALAVRAS_DOCUMENTOS):
        return False

    return True


def identificar_fonte(pergunta):
    fontes = fontes_relevantes(pergunta)

    if len(fontes) >= 2:
        return "multipla"

    if not fontes:
        return "geral"

    return next(iter(fontes))
