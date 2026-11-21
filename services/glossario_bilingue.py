"""Glossário técnico bilíngue (PT-BR ↔ EN) das geociências.

Este módulo é o vocabulário compartilhado por três pontos do sistema:

1. ``services.rag_service._gerar_queries_bilingues`` — fallback
   determinístico da consulta bilíngue, usado quando o Ollama não
   responde ou demora;
2. ``services.rag_service`` — expansão de sinônimos dentro de cada idioma
   (ex.: ``assay`` → ``analysis``), que aproxima a pergunta dos termos
   empregados no documento;
3. ``core.prompt_manager`` — tabela de equivalência PT-BR ↔ EN entregue
   ao modelo junto do contexto, para que a resposta traduza os termos
   técnicos encontrados em documentos em inglês.

O dicionário é **expansível por design**:

- basta acrescentar pares em ``PARES_TERMOS`` (ou chamar
  :func:`registrar_par`) e o novo par passa a valer em todas as camadas;
- o mesmo termo pode aparecer em vários pares, o que cria a rede de
  sinônimos usada pela expansão;
- as chaves são sempre normalizadas por :func:`normalizar_termo`
  (minúsculas, sem acento, hífen e espaços colapsados), então "(REE)",
  "terras raras" e "Elementos Terras Raras" são o mesmo conceito.

Exemplo de identificação de idioma de um trecho::

    >>> detectar_idioma("Leachable TREO grades from wellfield drilling")
    'en'
    >>> detectar_idioma("Os teores lixiviáveis foram obtidos em furos")
    'pt'
"""

import re
import unicodedata


# Idiomas reconhecidos. Valores fora destes rótulos indicam que não foi
# possível decidir com segurança.
IDIOMA_PT = "pt"
IDIOMA_EN = "en"
IDIOMA_INDEFINIDO = "indefinido"


def normalizar_termo(texto):
    """Forma comparável de um termo: minúsculo, sem acento, sem hífen.

    "Elementos-Terras Raras" e "elementos terras raras" chegam iguais:
    o hífen vira espaço e os espaços são colapsados. A função também
    remove pontuação de borda, que costuma sobrar da extração de termos
    da pergunta: "(REE)" vira "ree".
    """

    decomposto = unicodedata.normalize("NFKD", str(texto or "")).casefold()
    texto = "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    )
    texto = re.sub(r"[^0-9a-z]+", " ", texto)

    return " ".join(texto.split())


def compactar_termo(texto):
    """Forma comparável sem espaços — usada para casar compostos.

    É a mesma de :func:`normalizar_termo` sem os espaços, o que a torna
    insensível também ao hífen: "qa/qc", "qa qc" e "qaqc" chegam iguais,
    assim como "neodímio e praseodímio" e "ndpr".
    """

    return normalizar_termo(texto).replace(" ", "")


# ---------------------------------------------------------------------------
# Pares PT-BR ↔ EN
# ---------------------------------------------------------------------------

# Cada tupla é (termo em português, termo em inglês). A lista é
# intencionalmente explícita — é ela que torna a busca bilíngue
# previsível e auditável, sem depender do modelo.
#
# Convenção: o termo em português usa a forma consagrada no jargão do
# SGB (ex.: "ETR" para REE, "teor" para grade), quando existir.
PARES_TERMOS = (
    # Amostragem, sondagem e preparação
    ("sondagem", "drilling"),
    ("sondagem", "drill hole"),
    ("furo de sondagem", "drill hole"),
    ("furos de sondagem", "drillholes"),
    ("furo", "hole"),
    ("testemunho de sondagem", "drill core"),
    ("testemunho", "core"),
    ("perfuração", "drilling"),
    ("praça de sondagem", "drill pad"),
    ("campo de poços", "wellfield"),
    ("campo de poços de lixiviação", "leach wellfield"),
    ("trado", "auger"),
    ("furo a trado", "auger hole"),
    ("sondagem a trado", "augering"),
    ("perfuratriz de trado", "auger rig"),
    ("amostragem", "sampling"),
    ("amostra", "sample"),
    ("amostras", "samples"),
    ("amostra composta", "composite sample"),
    ("testemunho de calha", "channel sample"),
    ("frente de lavra", "mine face"),
    ("intervalo amostrado", "sampled interval"),
    ("teor", "grade"),
    ("teores", "grades"),
    ("alto teor", "high grade"),
    ("baixo teor", "low grade"),
    ("teor médio", "average grade"),
    ("teor de corte", "cut-off grade"),
    ("teor diluído", "diluted grade"),
    ("aglomerado", "agglomerate"),
    ("análise química", "assay"),
    ("análises químicas", "assays"),
    ("resultados analíticos", "assay results"),
    ("ensaio", "assay"),
    ("controle de qualidade", "quality assurance"),
    ("garantia e controle de qualidade", "QA/QC"),
    ("material de referência certificado", "certified reference material"),
    ("branco", "blank"),
    ("duplicata", "duplicate"),

    # Geostatística e estimativa de recursos
    ("modelo de blocos", "block model"),
    ("estimativa de recursos", "resource estimate"),
    ("classificação de recursos", "resource classification"),
    ("medido, indicado e inferido", "measured, indicated and inferred"),
    ("recurso medido", "measured resource"),
    ("recurso indicado", "indicated resource"),
    ("recurso inferido", "inferred resource"),
    ("reserva lavrável", "ore reserve"),
    ("teor de recuperação", "recovery"),
    ("fator de mineração", "mining factor"),
    ("diluição", "dilution"),
    ("acompanhamento estatístico de desvios", "statistical deviation tracking"),
    ("variografia", "variography"),
    ("variograma", "variogram"),
    ("cokrigagem", "cokriging"),
    ("krigagem", "kriging"),
    ("interpolação", "interpolation"),
    ("estimativa inversa ao quadrado da distância", "inverse distance squared"),
    ("interpretação geológica", "geological interpretation"),
    ("modelo geológico", "geological model"),
    ("seção geológica", "cross section"),
    ("mapa geológico", "geological map"),
    ("compilação geológica", "geological compilation"),
    ("revisão geológica", "geological review"),
    ("zonas mineralizadas", "mineralized zones"),
    ("zona de oxidação", "oxidation zone"),
    ("perfil de alteração", "weathering profile"),
    ("intemperismo", "weathering"),
    ("cobertura laterítica", "lateritic cover"),

    # Lavra, mineralogia e tratamento
    ("lavra", "mining"),
    ("mina", "mine"),
    ("mina a céu aberto", "open pit"),
    ("lavra a céu aberto", "open pit mining"),
    ("lavra subterrânea", "underground mining"),
    ("planejamento de mina", "mine planning"),
    ("mina operacional", "operational mine"),
    ("plano de mina", "mine plan"),
    ("vida útil da mina", "mine life"),
    ("operação anual", "annual operation"),
    ("recuperação metalúrgica", "metallurgical recovery"),
    ("metalurgia", "metallurgy"),
    ("beneficiamento", "beneficiation"),
    ("processamento mineral", "mineral processing"),
    ("cominuição", "comminution"),
    ("britagem e moagem", "crushing and grinding"),
    ("lixiviação", "leaching"),
    ("lixiviável", "leachable"),
    ("lixiviação em pilha", "heap leaching"),
    ("pilha de lixiviação", "heap leach"),
    ("lixiviação in situ", "in situ leaching"),
    ("solução lixiviante", "leach solution"),
    ("sulfato de magnésio", "magnesium sulphate"),
    ("flotação", "flotation"),
    ("concentração gravimétrica", "gravity concentration"),
    ("separação magnética", "magnetic separation"),
    ("concentrado", "concentrate"),
    ("rejeitos", "tailings"),
    ("rejeito", "tailings"),
    ("barragem de rejeitos", "tailings dam"),
    ("úmido a seco", "wet to dry"),
    ("teor de umidade", "moisture content"),

    # Metais, minerais e geoquímica
    ("ouro", "gold"),
    ("cobre", "copper"),
    ("ferro", "iron"),
    ("manganês", "manganese"),
    ("niquel", "nickel"),
    ("cobalto", "cobalt"),
    ("zinco", "zinc"),
    ("chumbo", "lead"),
    ("estanho", "tin"),
    ("nióbio", "niobium"),
    ("tântalo", "tantalum"),
    ("terras raras", "rare earths"),
    ("etr elementos terras raras", "rare earth elements"),
    ("etr", "rare earth elements"),
    ("ree", "ETR — Elementos Terras Raras"),
    ("etr - elementos terras raras", "REE"),
    ("troe", "TREO"),
    ("treo oxidos totais de terras raras", "total rare earth oxides"),
    ("óxidos totais de terras raras", "total rare earth oxides"),
    ("disprósio", "dysprosium"),
    ("tórbio", "terbium"),
    ("neodímio", "neodymium"),
    ("praseodímio", "praseodymium"),
    ("neodímio e praseodímio", "ndpr"),
    ("ndpr", "neodymium praseodymium"),
    ("lantânio", "lanthanum"),
    ("cério", "cerium"),
    ("minério de ferro", "iron ore"),
    ("litologia", "lithology"),
    ("litotipo", "lithotype"),
    ("unidade litológica", "lithological unit"),
    ("bauxita", "bauxite"),
    ("hematita", "hematite"),
    ("magnetita", "magnetite"),
    ("goethita", "goethite"),
    ("caulinita", "kaolinite"),
    ("argila", "clay"),
    ("grafita", "graphite"),
    ("lítio", "lithium"),
    ("pesquisa geoquímica", "geochemical survey"),
    ("geoquímica", "geochemistry"),
    ("elementos traço", "trace elements"),
    ("espectrometria de massa", "mass spectrometry"),
    ("separação de minerais pesados", "heavy mineral separation"),
    ("mineral pesado", "heavy mineral"),
    ("amostra de bateia", "pan concentrate"),
    ("platina", "platinum"),
    ("elementos do grupo da platina", "platinum group elements"),
    ("egp", "pge"),

    # Geologia regional e estruturas
    ("província mineral", "mineral province"),
    ("craton", "craton"),
    ("embasamento cristalino", "crystalline basement"),
    ("embasamento", "basement"),
    ("bacia sedimentar", "sedimentary basin"),
    ("sistema de cisalhamento", "shear system"),
    ("zona de cisalhamento", "shear zone"),
    ("falha", "fault"),
    ("dobramento", "folding"),
    ("foliação", "foliation"),
    ("contato litológico", "lithological contact"),
    ("datação radiométrica", "radiometric dating"),
    ("geocronologia", "geochronology"),
    ("espectrometria gama", "gamma-ray spectrometry"),
    ("aerogeofísica", "airborne geophysics"),
    ("levantamento geofísico", "geophysical survey"),
    ("anomalia geofísica", "geophysical anomaly"),
    ("magnetometria", "magnetics"),
    ("modelo digital de terreno", "digital terrain model"),
    ("sensoriamento remoto", "remote sensing"),
    ("imagem de satélite", "satellite imagery"),
    ("sísmica", "seismic"),
    ("sondagem elétrica", "electrical sounding"),

    # Escopo, exploração e autorizações
    ("área de concessão", "tenement"),
    ("área de concessão de pesquisas", "exploration tenement"),
    ("direito minerário", "mining title"),
    ("autorização de pesquisa", "exploration licence"),
    ("requerimento de lavra", "mining lease"),
    ("estudos metalogenéticos", "metallogenic studies"),
    ("potencial mineral", "mineral potential"),
    ("modelo metalogenético", "metallogenic model"),
    ("prospecção", "prospecting"),
    ("exploração mineral", "mineral exploration"),
    ("estudos de exploração", "exploration studies"),
    ("campanha exploratória", "exploration campaign"),
    ("permit", "alvará"),
    ("licenciamento ambiental", "environmental licensing"),
    ("impacto ambiental", "environmental impact"),

    # Termos gerais de busca (usados também na tradução das consultas às
    # bases internacionais, como OpenAlex e USGS ScienceBase).
    ("geologia", "geology"),
    ("geológico", "geological"),
    ("mineração", "mining"),
    ("minério", "ore"),
    ("depósito mineral", "mineral deposit"),
    ("depósito", "deposit"),
    ("depósitos", "deposits"),
    ("rocha", "rock"),
    ("rochas", "rocks"),
    ("solo", "soil"),
    ("água subterrânea", "groundwater"),
    ("recurso mineral", "mineral resource"),
    ("recursos minerais", "mineral resources"),
    ("província", "province"),
    ("mina de ouro", "gold mine"),
    ("teor de ouro", "gold grade"),

    # Parte de relatório e documentos
    ("resuma", "summarize"),
    ("resumir", "summarize"),
    ("mostre", "show"),
    ("liste", "list"),
    ("explique", "explain"),
    ("descreva", "describe"),
    ("aponte", "highlight"),
    ("destaque", "highlight"),
    ("identifique", "identify"),
    ("compare", "compare"),
    ("resumo", "summary"),
    ("resumo executivo", "executive summary"),
    ("destaques", "highlights"),
    ("introdução", "introduction"),
    ("conclusões", "conclusions"),
    ("conclusão", "conclusion"),
    ("recomendações", "recommendations"),
    ("metodologia", "methodology"),
    ("método", "method"),
    ("resultados", "results"),
    ("discussão", "discussion"),
    ("próximos passos", "next steps"),
    ("próximos trabalhos", "future work"),
    ("tabela", "table"),
    ("figura", "figure"),
    ("anexo", "appendix"),
    ("relatório", "report"),
    ("comunicado ao mercado", "announcement"),
    ("comunicado", "releases"),
    ("apêndice", "appendix"),
    ("referências bibliográficas", "references"),
)


# ---------------------------------------------------------------------------
# Estruturas derivadas (índices construídos uma única vez)
# ---------------------------------------------------------------------------

def _chave_par(pt, en):
    """Chave estável de um par PT↔EN, já normalizada."""

    return (normalizar_termo(pt), normalizar_termo(en))


def _montar_indices(pares):
    """Constrói os mapas PT→{EN} e EN→{PT} a partir da lista de pares.

    A função evita formatos "meio traçados" na lista de pares: qualquer
    entrada que perca uma das pontas na normalização é descartada.

    Os valores guardam a **forma original** do par (com acento e caixa),
    porque é ela que aparece na tabela de equivalência entregue ao
    modelo. A normalização serve só para o casamento.
    """

    pt_para_en = {}
    en_para_pt = {}

    for termo_pt, termo_en in pares:
        chave_pt = normalizar_termo(termo_pt)
        chave_en = normalizar_termo(termo_en)

        if not chave_pt or not chave_en or chave_pt == chave_en:
            continue

        pt_para_en.setdefault(chave_pt, set()).add(termo_en.strip())
        en_para_pt.setdefault(chave_en, set()).add(termo_pt.strip())

    return pt_para_en, en_para_pt


def _indexar_compacto(mapa, direcao):
    """Segundo índice, indexado pela forma compacta (sem espaços).

    Permite casar "qa qc" com "qa/qc" e "cut off" com "cut-off" sem
    duplicar pares na lista principal.
    """

    indice = {}

    for chave, valores in mapa.items():
        indice[(direcao, compactar_termo(chave))] = valores

    return indice


_PT_PARA_EN, _EN_PARA_PT = _montar_indices(PARES_TERMOS)
_INDICE_COMPACTO = {}
_INDICE_COMPACTO.update(_indexar_compacto(_PT_PARA_EN, IDIOMA_EN))
_INDICE_COMPACTO.update(_indexar_compacto(_EN_PARA_PT, IDIOMA_PT))

# Chaves compactas: comparação insensível a espaço, hífen e barra.
_SIGLAS_COMPACTAS = frozenset(
    {
        "ree",
        "etr",
        "troe",
        "ndpr",
        "egp",
        "pge",
        "qaqc",
        "dy",
        "tb",
    }
)


def registrar_par(termo_pt, termo_en):
    """Acrescenta um par PT↔EN ao glossário em tempo de execução.

    Útil para vocabulário específico de um projeto ou de um lote de
    documentos. O novo par passa a valer imediatamente em todas as
    camadas; nunca sobrescreve pares existentes.
    """

    chave_pt = normalizar_termo(termo_pt)
    chave_en = normalizar_termo(termo_en)

    if not chave_pt or not chave_en or chave_pt == chave_en:
        return False

    _PT_PARA_EN.setdefault(chave_pt, set()).add(chave_en)
    _EN_PARA_PT.setdefault(chave_en, set()).add(chave_pt)

    return True


def total_de_pares():
    """Quantidade de chaves únicas em português registradas."""

    return len(_PT_PARA_EN)


# ---------------------------------------------------------------------------
# Tradução de termos
# ---------------------------------------------------------------------------

def _lista_ordenada(valores):
    """Ordena de forma estável: frase curta primeiro, depois alfabético.

    O primeiro equivalente sugerido ao modelo deve ser o mais direto
    ("tailings" antes de "wet to dry").
    """

    return sorted(valores, key=lambda valor: (len(valor), valor))


def traduzir_termo(termo, direcao=IDIOMA_EN):
    """Equivalente(s) do termo no idioma de destino.

    ``direcao`` é o idioma de saída: ``"en"`` traduz PT→EN e ``"pt"``
    traduz EN→PT. Devolve a lista de equivalências, já ordenada; lista
    vazia quando o termo não está no glossário.

    O casamento tenta a forma normalizada e, em seguida, a forma
    compacta (sem espaços): assim "qa qc" encontra a entrada "qa/qc" e
    "neodimio e praseodimio" encontra "ndpr".
    """

    chave = normalizar_termo(termo)

    if not chave:
        return []

    mapa = _EN_PARA_PT if direcao == IDIOMA_PT else _PT_PARA_EN

    encontrados = mapa.get(chave)

    if not encontrados:
        encontrados = _INDICE_COMPACTO.get((direcao, compactar_termo(termo)))

    return _lista_ordenada(encontrados or ())


def termos_conhecidos(termo):
    """Indica se o termo (ou a expressão) está no glossário."""

    chave = normalizar_termo(termo)

    if chave in _PT_PARA_EN or chave in _EN_PARA_PT:
        return True

    compacta = compactar_termo(termo)

    return any(
        compactar_termo(existente) == compacta
        for existente in set(_PT_PARA_EN) | set(_EN_PARA_PT)
    )


def expressoes_conhecidas():
    """Devolve as chaves conhecidas que têm mais de uma palavra.

    A busca bilíngue usa essa lista para casar expressões compostas
    ("furo de sondagem") antes de olhar palavra por palavra. As chaves
    são retornadas no formato compacto (sem espaços), porque é essa a
    forma insensível ao hífen usada no casamento.
    """

    compactas = {compactar_termo(chave) for chave in _PT_PARA_EN}
    compactas |= {compactar_termo(chave) for chave in _EN_PARA_PT}

    return sorted(
        (chave for chave in compactas if len(chave) > 1),
        key=lambda chave: (-len(chave), chave),
    )


# ---------------------------------------------------------------------------
# Expansão de sinônimos dentro do mesmo idioma
# ---------------------------------------------------------------------------

# Sinônimos internos: termos que aparecem em documentos mas raramente na
# pergunta do usuário. Cada entrada é (origem, destino) e o casamento é
# feito no texto já normalizado.
SINONIMOS_EN = (
    ("assay", "analysis"),
    ("assays", "analyses"),
    ("grade", "content"),
    ("drillhole", "hole"),
    ("drillholes", "holes"),
    ("holes", "drilling"),
    ("rec", "recovery"),
    ("met", "metallurgical"),
    ("res", "resource"),
    ("reserve", "reserves"),
    ("mineralisation", "mineralization"),
    ("characterisation", "characterization"),
    ("analyse", "analysis"),
    ("analysed", "assayed"),
    ("augering", "auger"),
    ("wellfield", "holes"),
)

SINONIMOS_PT = (
    ("analises", "ensaios"),
    ("analises quimicas", "teores"),
    ("ensaios", "teores"),
    ("furos", "sondagens"),
    ("teores", "teor"),
    ("rejeito", "rejeitos"),
    ("lixiviacao", "lixiviavel"),
    ("mineralizacoes", "mineralizacao"),
    ("recuperacoes", "recuperacao"),
)


def _expandir_sinonimos(texto, pares):
    """Acrescenta ao texto os sinônimos internos encontrados nele."""

    normalizado = normalizar_termo(texto)
    extras = []

    for origem, destino in pares:
        if re.search(rf"\b{re.escape(origem)}\b", normalizado):
            extras.append(destino)

    return extras


def expandir_termos(texto, idioma):
    """Termos extras (mesmo idioma) úteis para casar com o documento.

    Junta duas fontes: os sinônimos internos (``SINONIMOS_EN`` e
    ``SINONIMOS_PT``) e as equivalências do glossário daquele idioma em
    que **o texto já usa o termo do outro idioma** (ex.: um documento que
    mistura "tailings" e "rejeitos").

    O casamento é por token inteiro (e por expressão composta):

    - o texto vira um conjunto de tokens compactos;
    - uma entrada de uma palavra ("grade") só casa como token completo,
      nunca dentro de "upgrade";
    - uma entrada de várias palavras ("drill core") casa quando o
      segmento correspondente do texto, sem espaços, está presente.
    """

    pares = SINONIMOS_EN if idioma == IDIOMA_EN else SINONIMOS_PT
    extras = _expandir_sinonimos(texto, pares)
    compacto = compactar_termo(texto)
    tokens = re.findall(r"[a-z0-9]+", normalizar_termo(texto))
    mapa = _EN_PARA_PT if idioma == IDIOMA_EN else _PT_PARA_EN

    for origem, destinos in mapa.items():
        chave = compactar_termo(origem)

        if not chave:
            continue

        if " " in origem:
            casou = chave in compacto
        else:
            casou = chave in tokens

        if casou:
            extras.extend(destinos)

    vistos = set()
    resultado = []

    for termo in extras:
        if termo and termo not in vistos:
            vistos.add(termo)
            resultado.append(termo)

    return resultado


# ---------------------------------------------------------------------------
# Detecção de idioma por marcadores (leve e determinística)
# ---------------------------------------------------------------------------

# Palavras funcionais são o indício mais confiável de idioma em textos
# técnicos curtos: o vocabulário substantivo é compartilhado.
_MARCADORES_EN = frozenset("""
    the and of in on at to for from with by as is are was were be been
    this that these those which whose while where through between
    within along above below under over during since than then there
    their its it they we you our has have had will would should could
    not also more most less very such both each other only into
    however therefore thus therefore whereas although because
""".split())

_MARCADORES_PT = frozenset("""
    o a os as um uma uns umas de do da dos das em no na nos nas
    ao aos pela pelo pelas pelos com sem por para que qual quais
    se nao mais muito como tambem foi foram ser sao esta estao este
    esta estes estas esse essa e ou mas porem entao assim entre
    sobre apos antes desde conforme segundo quando onde cujo cada
    todo toda todos todas pelo tem haver ate
""".split())


def _contar_marcadores(tokens, marcadores):
    return sum(1 for token in tokens if token in marcadores)


def detectar_idioma(texto):
    """Estima o idioma de um trecho: ``"pt"``, ``"en"`` ou ``"indefinido"``.

    A regra olha apenas palavras funcionais e acentuação — os dois sinais
    que distinguem os idiomas em textos técnicos, cujo vocabulário é
    majoritariamente latino e compartilhado ("drilling", "drill core").

    A decisão exige margem clara: um empate, ou um texto sem marcadores
    de nenhum dos dois idiomas (como uma tabela de números), devolve
    ``"indefinido"`` em vez de chutar.
    """

    texto = str(texto or "")

    if not texto.strip():
        return IDIOMA_INDEFINIDO

    # Acentos fortes do português (ã, õ, ç, é...) quase não ocorrem em
    # inglês; uma ou duas ocorrências só contam de verdade com marcadores.
    acentos = len(re.findall(r"[ãõçáéíóúâêôàÃÕÇÁÉÍÓÚÂÊÔ]", texto))
    tokens = re.findall(r"[a-z]+", normalizar_termo(texto))

    total_en = _contar_marcadores(tokens, _MARCADORES_EN)
    total_pt = _contar_marcadores(tokens, _MARCADORES_PT) + acentos

    if total_en == total_pt:
        return IDIOMA_INDEFINIDO

    return IDIOMA_EN if total_en > total_pt else IDIOMA_PT


def rotulo_idioma(idioma):
    """Rótulo legível do idioma, para mensagens e para a interface."""

    return {
        IDIOMA_PT: "português",
        IDIOMA_EN: "inglês",
    }.get(idioma, "indefinido")


# ---------------------------------------------------------------------------
# Tabela de equivalência entregue ao modelo
# ---------------------------------------------------------------------------

LIMITE_TABELA_EQUIVALENCIA = 40
MAX_CARACTERES_EQUIVALENCIA = 90


def _formatar_equivalente(termo):
    """Siglas saem em caixa alta; o restante mantém a forma do glossário."""

    chave = compactar_termo(termo)

    if chave in _SIGLAS_COMPACTAS:
        return termo.upper()

    return termo


def normalizar_lista(valores):
    """Normaliza uma lista de equivalências para uso interno.

    ``traduzir_termo`` devolve a forma original (com acento e caixa),
    que é a que aparece no prompt. Quem precisa comparar ou montar
    queries usa esta função, que aplica :func:`normalizar_termo` a cada
    valor, remove repetidos e mantém a ordem (frase curta primeiro).
    """

    vistos = set()
    resultado = []

    for valor in _lista_ordenada(valores):
        chave = normalizar_termo(valor)

        if chave and chave not in vistos:
            vistos.add(chave)
            resultado.append(chave)

    return resultado


def montar_tabela_equivalencia(termos_em_ingles, limite=LIMITE_TABELA_EQUIVALENCIA):
    """Monta as linhas "termo em inglês → termo em PT-BR" do contexto.

    ``termos_em_ingles`` é um iterável de termos (normalmente os
    encontrados na pergunta e nos trechos recuperados). Só entram os que
    o glossário reconhece; a lista sai ordenada e limitada a ``limite``
    linhas para não inflar o prompt.

    Devolve ``[(termo_en, equivalencias_pt), ...]`` — lista vazia
    quando nenhum termo é conhecido, caso em que o prompt não exibe a
    seção.
    """

    encontrados = {}

    for bruto in termos_em_ingles or ():
        termo = " ".join(str(bruto or "").split())

        if not termo:
            continue

        equivalente_pt = traduzir_termo(termo, IDIOMA_PT)

        if not equivalente_pt:
            continue

        # Um termo e um subconjunto dele (ex.: "gold" e "gold mine")
        # não precisam aparecer duas vezes: a expressão mais curta vale
        # pelo contexto do glossário. A comparação usa a forma
        # compacta, então "REE" e "Terras Raras" continuam distintos
        # mesmo que o texto compactado de uma contenha a outra.
        chave = compactar_termo(termo)
        ja_coberto = any(
            chave_existente in chave and chave_existente != chave
            and len(chave_existente) >= 4
            for chave_existente in encontrados
        )

        if ja_coberto:
            continue

        linha = " / ".join(
            _formatar_equivalente(valor)
            for valor in equivalente_pt[:2]
        )

        if len(linha) > MAX_CARACTERES_EQUIVALENCIA:
            linha = linha[:MAX_CARACTERES_EQUIVALENCIA].rstrip()

        encontrados[chave] = (
            _formatar_equivalente(termo),
            linha,
        )

    linhas = list(encontrados.values())
    # Siglas e termos curtos primeiro: são os mais estáveis na resposta
    # ("REE", "teor"), e os compostos ficam por último.
    linhas.sort(
        key=lambda par: (
            0 if compactar_termo(par[0]) in _SIGLAS_COMPACTAS else 1,
            len(par[0].split()),
            par[0].casefold(),
        )
    )

    return linhas[:limite] if limite else linhas
