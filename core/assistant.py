"""Orquestração das fontes de informação do assistente.

O roteamento é orientado aos toggles da barra lateral: cada fonte ligada
pelo usuário entra na consulta, sem exceção. O roteador inteligente de
``core.smart_router`` continua classificando a intenção em ``LOCAL_ONLY``,
``RIGEO_ONLY``, ``HIBRIDO`` ou ``ANA_ONLY``, mas só para registrar a
justificativa e otimizar os filtros da pergunta (município, UF,
substância e rio). A decisão — inclusive a lista de fontes efetivas —
volta em ``resultado["roteamento"]`` para a interface exibir e para o
histórico da conversa.

A base documental local (``usar_documentos=True``) e o acervo RIGeo
(``usar_sgb=True``) são os dois toggles de acervo. Antes de consultar o
RIGeo, a pergunta em linguagem natural passa por
``services.external_api_service.extrair_termos``: stopwords e palavras
conversacionais ("quais", "estudos", "abordam", "potencial"...) saem da
frase, e só os termos geocientíficos (topônimos, unidades
litoestratigráficas, folhas cartográficas, minerais) vão para a busca.
O planejamento e o termo efetivo ficam em ``resultado["busca_rigeo"]``,
que a interface mostra no ``st.status``.

A fonte opcional ANA/HidroWeb (``usar_ana=True``) acrescenta o
inventário público de estações fluviométricas e pluviométricas. Os
registros ficam em ``dados["ana"]`` e só chegam ao contexto do LLM
quando o conector devolve estações. O conector tem três camadas
(cache local em disco, serviços abertos do SNIRH e fallback SOAP); se a
resposta vier do cache, ``dados["ana"]["fonte"]`` e a etiqueta da fonte
nesta orquestração passam a ``"ANA / HidroWeb (cache local)"``, para que
a interface, o histórico e o prompt preservem a rastreabilidade. A
classificação ``ANA_ONLY`` continua marcando a pergunta, mas é o toggle
``ana_enabled`` que liga ou desliga o conector.

A pesquisa na Web aberta (``usar_web=True``) é independente dos demais
toggles e roda sempre em conjunto com as fontes ativas. Os resultados
ficam em ``dados["web"]`` e o system prompt recebe a instrução de
distinguir a Web aberta das bases geocientíficas oficiais e dos
documentos locais. ``web_apenas_tecnico=True`` restringe a busca a
domínios técnicos e institucionais.

As bases internacionais abertas (``usar_openalex=True`` e
``usar_intl_geo=True``) também são fontes adicionais. A pergunta é
traduzida para o inglês por
``services.external_api_service.planejar_termo_ingles`` — extração de
termos do RIGeo + glossário PT↔EN + preparação geológica final — e o
planejamento fica em ``dados["busca_externa"]``. O OpenAlex mantém o
conector próprio; os dez serviços geológicos (OneGeology, USGS
ScienceBase, NRCan/GSC, EGDI, Geoscience Australia/GSQ, GSJ/AIST,
GeoNet/GNS, CGS/Digital Earth Africa, NGD e GSI/Bhukosh) são
consultados pelo orquestrador unificado, com filtro de regiões. O
resultado consolidado fica em ``dados["intl_geo"]``, com a origem exata
de cada registro em ``fonte``. Quando a pergunta pede uma distribuição
metalogenética global (por exemplo, komatiitos mineralizados no mundo),
o system prompt recebe uma instrução extra: apresentar primeiro os
achados concretos das bases ativas e, em seção separada, complementar
com o consenso geocientífico de referência, deixando explícita a
diferença entre as duas camadas.
A fonte SGB pode ser desligada (``usar_sgb=False``) para uma consulta só
às bases internacionais.

O conector do GeoSGB (``usar_geosgb=True``) acrescenta as ocorrências
minerais do Serviço Geológico do Brasil: a substância e a UF são
extraídas da pergunta e o WFS OGC devolve GeoJSON. Os registros ficam em
``dados["geosgb"]``, no mesmo schema das demais fontes (com ``lat`` e
``lon``), e ``core.prompt_manager`` injeta uma tabela Markdown compacta
no contexto do LLM para apoiar análises regionais e de potencialidade
mineral.

O conector da ANM (``usar_anm=True``) é o par regulatório do GeoSGB e
vem de outra agência: consulta o SIGMINE, o cadastro público de
processos minerários da Agência Nacional de Mineração (ArcGIS REST, com
o WFS OGC do mesmo serviço como segunda tentativa). O recorte — a
substância, o titular ou a UF — também sai da própria pergunta. Os
registros ficam em ``dados["anm"]``, no mesmo schema das demais fontes,
e ``core.prompt_manager`` injeta a tabela de processos (número, ano,
fase, titular, substância, área e UF) no contexto. As duas bases são
independentes e nunca se substituem: uma ocorrência do GeoSGB não é um
processo da ANM.

Os três conectores geológicos da última fase seguem o mesmo contrato,
ligados por toggles próprios:

- **Macrostrat** (``usar_macrostrat=True``): unidades
  litoestratigráficas com idade, litologia e ambiente deposicional. As
  coordenadas usadas na consulta espacial saem da pergunta ou, na falta
  delas, do texto de um documento local recuperado nesta mesma
  consulta. O resultado fica em ``dados["macrostrat"]``.
- **SIAGAS / RIMAS** (``usar_siagas=True``): poços tubulares do
  Serviço Geológico do Brasil, com profundidade, níveis estático e
  dinâmico, vazão, aquífero e coordenadas. O resultado fica em
  ``dados["siagas"]``.
- **INDE / GEOSSIT** (``usar_geossit=True``): inventário de geossítios
  e sítios da geodiversidade, com categoria, município/UF, relevância e
  coordenadas. O resultado fica em ``dados["geossit"]``.

Quando o SIAGAS e a ANA devolvem registros na mesma consulta,
``core.prompt_manager`` acrescenta a instrução de cruzar águas
subterrâneas com águas superficiais; quando a Macrostrat devolve
unidades, a tabela estratigráfica contextualiza os aquíferos e as
unidades geológicas locais.

O parâmetro ``modo`` continua aceito para chamadores antigos (modos
manuais restringem as fontes como antes), mas a interface atual envia
apenas os toggles. ``limite`` e ``comunidade`` afetam apenas a consulta
ao RIGeo.
"""

import re
import unicodedata

from core.prompt_manager import montar_prompt_sistema
from core.smart_router import (
    INTENCAO_LOCAL,
    INTENCAO_RIGEO,
    decidir_roteamento,
    nomes_documentos,
)
from core.source_router import fontes_relevantes, identificar_fonte
from services.external_api_service import (
    ANM_LIMITE_PADRAO,
    FONTE_USGS_INTERNACIONAL,
    GEOSGB_LIMITE_PADRAO,
    GEOSSIT_LIMITE_PADRAO,
    MACROSTRAT_LIMITE_PADRAO,
    OPCOES_REGIOES_INTERNACIONAIS,
    REGIAO_TODAS,
    SIAGAS_LIMITE_PADRAO,
    WEB_LIMITE_PADRAO,
    consultar_ana_estacoes,
    consultar_anm_processos,
    consultar_geosgb_ocorrencias,
    consultar_geossit_inde,
    consultar_macrostrat,
    consultar_openalex_detalhado,
    consultar_servicos_geologicos_internacionais,
    consultar_sgb,
    consultar_siagas_pocos,
    consultar_web_detalhado,
    extrair_filtros_consulta,
    extrair_termos,
    planejar_termo_ingles,
)

OPCAO_USGS_INTERNACIONAL = OPCOES_REGIOES_INTERNACIONAIS[2]
from services.llm_service import gerar_resposta
from services.rag_service import consultar_documentos
from utils.i18n import instrucao_idioma_resposta, normalizar_idioma

MODOS = {
    "Automático": "automatico",
    "Geologia (SGB)": "sgb",
    "Documentos (RAG)": "rag",
    "Conhecimento geral": "geral"
}

FONTES_POR_MODO = {
    "Geologia (SGB)": ("sgb",),
    "Documentos (RAG)": ("documentos",),
    "Conhecimento geral": (),
}

INTENCAO_POR_MODO = {
    "Geologia (SGB)": INTENCAO_RIGEO,
    "Documentos (RAG)": INTENCAO_LOCAL,
    "Conhecimento geral": "GERAL",
}


def resolver_fonte(pergunta, modo):
    """Resolve a fonte de um modo manual ou pela heurística antiga.

    Mantida para compatibilidade com chamadores que ainda usam a
    assinatura anterior. O fluxo principal de ``responder`` usa
    :func:`core.smart_router.decidir_roteamento`.
    """

    if modo != "Automático":
        return MODOS[modo]

    return identificar_fonte(pergunta)


def _roteamento_manual(modo, documentos=None):
    """Descreve a escolha feita pelo usuário na barra lateral."""

    if modo not in FONTES_POR_MODO:
        raise ValueError(f"Modo de fonte desconhecido: {modo}")

    return {
        "modo": "manual",
        "intencao": INTENCAO_POR_MODO[modo],
        "fontes": list(FONTES_POR_MODO[modo]),
        "origem": "manual",
        "justificativa": (
            "Fonte escolhida manualmente na interface: "
            f"{modo}."
        ),
        "modelo": None,
        "documentos_locais": nomes_documentos(documentos),
        "aviso": None,
    }


def _base_externa_indisponivel(fonte, termo_en, limite, erro):
    """Contrato mínimo de uma base internacional que não pôde ser consultada.

    Mantém as mesmas chaves do retorno dos conectores, com ``total``
    zero e o motivo em ``aviso``, para a interface exibir a falha no
    ``st.status`` e no expander de fontes sem interromper a resposta.
    """

    return {
        "fonte": fonte,
        "pergunta": termo_en,
        "termo_busca": termo_en,
        "limite": limite,
        "total": 0,
        "registros": [],
        "aviso": str(erro),
    }


# Coordenadas decimais na pergunta ou no texto de um documento:
# "-3,1, -60,0", "lat -3.1 lon -60.0", "3.1 S 60.0 W". Só pares com
# parte decimal são aceitos; números inteiros soltos ("2024, 15")
# ficam de fora para não virarem um ponto no mapa por acidente.
_PADRAO_COORDENADAS = re.compile(
    r"(?P<lat>-?\d{1,2}[.,]\d+)"
    r"(?:\s*°?\s*(?P<hlat>[NSns]))?"
    r"\s*[,;/]\s*"
    r"(?P<lon>-?\d{1,3}[.,]\d+)"
    r"(?:\s*°?\s*(?P<hlon>[EWew]))?"
)


def _coordenada_numero(texto, hemisferio):
    """Converte o texto de uma coordenada em ``float`` com sinal.

    A vírgula decimal do português é aceita e o hemisfério (S/W) torna o
    valor negativo quando o usuário não escreveu o sinal.
    """

    try:
        valor = float(str(texto).replace(",", "."))
    except (TypeError, ValueError):
        return None

    if hemisferio and hemisferio.upper() in ("S", "W") and valor > 0:
        valor = -valor

    return valor


def _extrair_coordenadas(texto):
    """Primeiro par latitude/longitude válido encontrado no texto.

    Devolve ``(lat, lon)`` em graus decimais ou ``(None, None)``. A
    validação de faixa acontece aqui: um par fora de -90..90/-180..180
    é descartado, porque provavelmente é outra grandeza (idade, cota,
    área).
    """

    for achado in _PADRAO_COORDENADAS.finditer(str(texto or "")):
        latitude = _coordenada_numero(
            achado.group("lat"),
            achado.group("hlat")
        )
        longitude = _coordenada_numero(
            achado.group("lon"),
            achado.group("hlon")
        )

        if latitude is None or longitude is None:
            continue

        if not -90.0 <= latitude <= 90.0:
            continue

        if not -180.0 <= longitude <= 180.0:
            continue

        return latitude, longitude

    return None, None


def _coordenadas_da_consulta(pergunta, dados=None):
    """Coordenadas da pergunta ou, na falta delas, de um documento local.

    A Macrostrat aceita um ponto e devolve a unidade geológica daquele
    local. O ponto pode estar escrito na pergunta ("-3,1, -60,0") ou no
    texto de um trecho recuperado dos documentos locais ativos — é onde
    o usuário costuma colar a coordenada de um afloramento. A pergunta
    tem prioridade: se ela traz o par, os documentos não são varridos.
    """

    latitude, longitude = _extrair_coordenadas(pergunta)

    if latitude is not None:
        return latitude, longitude

    trechos = ((dados or {}).get("documentos") or {}).get("trechos") or []

    for trecho in trechos:
        latitude, longitude = _extrair_coordenadas(
            (trecho or {}).get("texto")
        )

        if latitude is not None:
            return latitude, longitude

    return None, None


# Termos que indicam uma pergunta sobre distribuição geográfica ampla.
_TERMOS_DISTRIBUICAO_GLOBAL = frozenset({
    "mundo", "mundial", "mundiais", "global", "globais",
    "internacional", "internacionais", "distribuicao", "distribuicoes",
    "panorama", "ocorrencia mundial", "world", "worldwide",
    "global distribution", "distribution",
})

# Termos que indicam foco metalogenético/mineral. A combinação com os
# termos acima é o gatilho da instrução de síntese equilibrada.
_TERMOS_METALOGENETICOS = frozenset({
    "metalogen", "komatiit", "kimberlit", "laterit", "greenstone",
    "cinturao", "craton", "provincia", "deposito", "ocorrencia",
    "mineraliz", "mineral", "ni-cu", "cu-ni", "egp", "pge",
    "ouro", "niquel", "cobre", "ferro", "litio", "terras raras",
    "bauxita", "vms", "sedex", "iocg",
})


def _normalizar_texto_simples(texto):
    """Forma comparável de um texto: minúsculo e sem acento."""

    decomposto = unicodedata.normalize("NFKD", str(texto or ""))

    return "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    ).casefold()


def _pergunta_metalogenetica_global(pergunta):
    """Diz se a pergunta pede distribuição metalogenética ampla.

    A síntese geocientífica só é acrescentada quando o assunto combina
    uma escala global ("mundo", "global", "distribuição") com um foco
    mineral/metalogenético. Perguntas locais continuam respondidas
    apenas com os registros recuperados.
    """

    texto = _normalizar_texto_simples(pergunta)

    if not texto:
        return False

    escala_global = any(
        termo in texto for termo in _TERMOS_DISTRIBUICAO_GLOBAL
    )
    foco_mineral = any(
        termo in texto for termo in _TERMOS_METALOGENETICOS
    )

    return escala_global and foco_mineral


# Instrução acrescentada ao system prompt quando a pergunta é uma
# distribuição metalogenética global. Ela resolve o caso em que os
# catálogos públicos devolvem apenas ocorrências pontuais: primeiro os
# achados concretos com fonte, depois o consenso geocientífico
# consolidado, sempre separando as duas camadas.
INSTRUCAO_SINTESE_METALOGENETICA_GLOBAL = """SÍNTESE METALOGENÉTICA GLOBAL — regra obrigatória para esta resposta:
1. Apresente PRIMEIRO os achados concretos recuperados nas bases ativas, um a um, com o serviço geológico de origem, o título e o link. Diga o que cada registro comprova e não os trate como um ranking estatístico fechado.
2. Se os catálogos públicos trouxerem apenas ocorrências pontuais ou registros parciais, declare isso explicitamente. Ausência de registro na API não é ausência geológica nem prova de inexistência do depósito.
3. Em seguida, em seção separada intitulada "Síntese geocientífica de referência", complemente objetivamente com o consenso geocientífico consolidado, deixando claro que essa parte NÃO veio dos registros da API. Para komatiitos mineralizados em Ni-Cu-EGP, cite os cinturões arqueanos clássicos: Cráton Yilgarn/Kambalda (Austrália Ocidental), Cinturão de Abitibi (Canadá), Cráton do Kaapvaal/Barberton (África do Sul) e Quadrilátero Ferrífero/Crixás (Brasil), quando pertinente à pergunta.
4. Diferencie sempre "registro recuperado da API" de "síntese geocientífica de referência". Não invente títulos, autores, anos, coordenadas ou links para a síntese; se citar literatura clássica, use apenas nomes de cinturões/províncias consagrados, sem link fictício.
5. Não substitua os achados da API pela síntese: a ordem é achados concretos primeiro, complemento de referência depois."""


def _instrucao_metalogenetica_global(pergunta, dados):
    """Instrução de síntese para consultas metalogenéticas globais.

    Só entra quando o grupo internacional está ativo na consulta e a
    pergunta combina escala global com foco mineral. Fora desse recorte,
    devolve string vazia para não poluir o prompt.
    """

    if "intl_geo" not in (dados or {}):
        return ""

    if not _pergunta_metalogenetica_global(pergunta):
        return ""

    return INSTRUCAO_SINTESE_METALOGENETICA_GLOBAL


def consultar_fonte(
    pergunta,
    fontes,
    limite=5,
    comunidade=None,
    modelo=None,
    usar_llm_termos=False,
    usar_ana=False,
    usar_web=False,
    web_apenas_tecnico=False,
    limite_web=WEB_LIMITE_PADRAO,
    usar_sgb=True,
    usar_openalex=False,
    usar_usgs=False,
    limite_externo=5,
    usar_intl_geo=False,
    regioes_intl_geo=None,
    usar_geosgb=False,
    limite_geosgb=GEOSGB_LIMITE_PADRAO,
    usar_anm=False,
    limite_anm=ANM_LIMITE_PADRAO,
    usar_macrostrat=False,
    limite_macrostrat=MACROSTRAT_LIMITE_PADRAO,
    usar_siagas=False,
    limite_siagas=SIAGAS_LIMITE_PADRAO,
    usar_geossit=False,
    limite_geossit=GEOSSIT_LIMITE_PADRAO,
    usgs_enabled=None,
    intl_geo_enabled=None,
    intl_geo_regioes=None
):
    """Coleta os dados das fontes que a pergunta exige.

    ``fontes`` é uma sequência com ``"sgb"`` e/ou ``"documentos"``. A
    assinatura antiga, que recebia um único rótulo como ``"multipla"``,
    ``"rag"`` ou ``"sgb"``, continua aceita para não quebrar chamadores
    existentes.

    ``limite`` e ``comunidade`` vêm dos controles da barra lateral e só
    afetam a consulta ao SGB: definem quantos artigos o RIGeo devolve e
    qual comunidade restringe a busca (``scope`` no DSpace).

    ``modelo`` é repassado à extração opcional de termos pelo Ollama
    (``usar_llm_termos=True``). O planejamento da busca é devolvido
    junto, em ``dados["busca"]``, para a interface mostrar qual termo
    foi efetivamente enviado ao RIGeo.

    ``usar_ana`` liga o conector do inventário público da ANA
    (HidroWeb). Ele é independente das demais fontes: acrescenta
    ``dados["ana"]`` e não interfere no roteamento do RIGeo. O conector
    consulta primeiro o cache local, depois os serviços abertos do
    SNIRH e, por fim, o WebService SOAP; uma falha online pode ser
    coberta pelo cache (mesmo expirado), e nesse caso
    ``dados["ana"]["fonte"]`` informa ``"ANA / HidroWeb (cache local)"``.
    Falhas sem cache viram lista vazia com ``aviso``, sem levantar
    exceção. Quem liga ou desliga o conector é o toggle
    ``ana_enabled`` da barra lateral, não a classificação de intenção.

    ``usar_web`` liga a pesquisa na Web aberta (DDGS, sem chave de
    API). Como a ANA, ela tem toggle próprio: roda em qualquer combinação
    de fontes e acrescenta ``dados["web"]`` com o contrato de
    ``consultar_web_detalhado``. ``web_apenas_tecnico`` restringe a busca
    a domínios técnicos e institucionais e ``limite_web`` controla
    quantas páginas voltam.

    ``usar_sgb=False`` retira ``"sgb"`` das fontes: é o toggle
    "SGB / RIGeo" da barra lateral. ``usar_openalex`` e ``usar_usgs``
    acrescentam as bases internacionais abertas, com ``limite_externo``
    registros cada uma. A consulta em inglês é planejada uma única vez,
    em ``dados["busca_externa"]``, e reaproveitada pelas bases.

    ``usar_intl_geo`` liga o grupo unificado de dez serviços geológicos
    internacionais. ``regioes_intl_geo`` é a lista de rótulos escolhida
    no multiselect da barra lateral; vazia ou com a opção global aciona
    todos os conectores. O resultado consolidado fica em
    ``dados["intl_geo"]``, com a origem de cada registro preservada em
    ``fonte``. O parâmetro legado ``usar_usgs`` continua aceito e, nesse
    caso, o orquestrador unificado executa apenas o ScienceBase; a chave
    ``dados["usgs"]`` é preenchida para chamadores antigos.

    ``usar_geosgb`` liga o conector do GeoSGB. A substância mineral e a
    UF saem da própria pergunta, dentro do conector, e ``limite_geosgb``
    limita as ocorrências devolvidas. Como as demais fontes adicionais,
    ele tem toggle próprio e nunca levanta exceção por falha de rede: o
    motivo fica em ``aviso``.

    ``usar_anm`` liga o conector do SIGMINE, o cadastro de processos
    minerários da ANM. A substância, o titular e a UF saem da pergunta,
    ``limite_anm`` limita os processos e o resultado fica em
    ``dados["anm"]``. É o par regulatório do GeoSGB, não um substituto:
    as duas bases podem ser ligadas na mesma consulta.

    ``usar_macrostrat``, ``usar_siagas`` e ``usar_geossit`` ligam os
    três conectores geológicos da última fase, também com toggles
    próprios. A Macrostrat usa as coordenadas da pergunta ou de
    um documento local recuperado nesta consulta (``dados`` já traz os
    trechos porque este bloco roda depois da busca local). Os limites de
    cada conector são validados por eles mesmos; um ``ValueError`` vira
    fonte vazia com o motivo em ``aviso``, nunca uma exceção na
    interface.
    """

    # Compatibilidade com chamadores antigos que usam os nomes das
    # chaves de sessão da interface (``usgs_enabled``) ou os nomes
    # equivalentes do grupo internacional.
    if usgs_enabled is not None:
        usar_usgs = usar_usgs or bool(usgs_enabled)

    if intl_geo_enabled is not None:
        usar_intl_geo = bool(intl_geo_enabled)

    if intl_geo_regioes is not None:
        regioes_intl_geo = list(intl_geo_regioes)

    if isinstance(fontes, str):
        if fontes == "multipla":
            fontes = fontes_relevantes(pergunta)
        elif fontes == "geral":
            fontes = set()
        else:
            fontes = {fontes}

    # "rag" é o nome histórico usado por ``fontes_relevantes``; o
    # dicionário de dados e o roteador usam "documentos".
    fontes = {
        "documentos" if fonte == "rag" else fonte
        for fonte in fontes
    }

    if not usar_sgb:
        fontes.discard("sgb")

    dados = {}

    if "sgb" in fontes:
        # A consulta é planejada aqui para que o termo efetivo esteja
        # pronto antes da chamada HTTP: é ele que a interface exibe no
        # st.status e é ele que ``consultar_sgb`` reaproveita.
        busca = extrair_termos(
            pergunta,
            usar_llm=usar_llm_termos,
            modelo=modelo
        )

        dados["sgb"] = consultar_sgb(
            pergunta,
            limite=limite,
            comunidade=comunidade,
            termos=busca
        )
        dados["busca"] = busca

    if "documentos" in fontes:
        # A busca local é bilíngue: a mesma pergunta é consultada em
        # português e em inglês antes de os trechos serem unidos. O
        # modelo escolhido na barra lateral também gera as queries.
        dados["documentos"] = consultar_documentos(
            pergunta,
            modelo=modelo
        )

    if usar_ana:
        # O conector é opcional e independente do roteamento: mesmo no
        # modo "Conhecimento geral" ele pode enriquecer a resposta com
        # estações. ``consultar_ana_estacoes`` nunca levanta exceção por
        # falha de rede; o motivo fica em ``aviso``.
        dados["ana"] = consultar_ana_estacoes(pergunta)

    if usar_web:
        # A Web é uma fonte adicional, não um modo: por isso roda em
        # qualquer seletor e depois das fontes oficiais, que continuam
        # tendo prioridade na resposta. A versão "detalhada" é usada
        # para que o aviso (sem pacote, sem internet, sem resultados)
        # chegue ao st.status da interface.
        dados["web"] = consultar_web_detalhado(
            pergunta,
            limite=limite_web,
            apenas_tecnico=web_apenas_tecnico
        )

    if usar_openalex or usar_usgs or usar_intl_geo:
        # A tradução PT→EN é feita uma única vez e reaproveitada pelas
        # bases abertas. Ela só usa a pergunta, então não há chamada de
        # rede nesta etapa.
        busca_externa = planejar_termo_ingles(pergunta)
        dados["busca_externa"] = busca_externa
        termo_en = busca_externa["termo_en"]

        if usar_openalex:
            try:
                dados["openalex"] = consultar_openalex_detalhado(
                    termo_en,
                    limite=limite_externo
                )
            except ValueError as erro:
                # Um parâmetro inválido não pode derrubar a resposta
                # inteira: a base fica vazia com o motivo no aviso.
                dados["openalex"] = _base_externa_indisponivel(
                    "OpenAlex", termo_en, limite_externo, erro
                )

        if usar_intl_geo or usar_usgs:
            # O USGS ScienceBase é um dos dez serviços do grupo
            # unificado. Chamadas legadas com ``usar_usgs=True`` são
            # atendidas pelo mesmo orquestrador, restritas ao serviço
            # norte-americano quando o grupo novo não estiver ligado.
            regioes = [
                str(regiao).strip()
                for regiao in (regioes_intl_geo or [])
                if str(regiao).strip()
            ]

            if usar_usgs and not usar_intl_geo:
                regioes = [OPCAO_USGS_INTERNACIONAL]
            elif (
                usar_usgs
                and OPCAO_USGS_INTERNACIONAL not in regioes
                and REGIAO_TODAS not in regioes
            ):
                regioes.append(OPCAO_USGS_INTERNACIONAL)

            if not regioes:
                regioes = [REGIAO_TODAS]

            latitude, longitude = _coordenadas_da_consulta(pergunta, dados)
            erro_intl = None

            try:
                registros_intl = consultar_servicos_geologicos_internacionais(
                    termo_en,
                    regioes_selecionadas=regioes,
                    lat=latitude,
                    lon=longitude,
                    limite_total=18,
                )
            except Exception as erro:
                # O orquestrador já contém falhas por conector; esta
                # proteção extra cobre um chamador substituto ou um
                # catálogo inválido sem derrubar a resposta.
                registros_intl = []
                erro_intl = str(erro)

            por_fonte = {}

            for registro in registros_intl:
                nome_fonte = str(registro.get("fonte") or "").strip()

                if nome_fonte:
                    por_fonte[nome_fonte] = por_fonte.get(nome_fonte, 0) + 1

            if usar_intl_geo:
                dados["intl_geo"] = {
                    "fonte": "Serviços Geológicos Internacionais",
                    "pergunta": pergunta,
                    "termo_busca": termo_en,
                    "regioes": regioes,
                    "limite": 18,
                    "total": len(registros_intl),
                    "registros": registros_intl,
                    "por_fonte": por_fonte,
                    "aviso": (
                        None
                        if registros_intl
                        else (
                            "Os serviços geológicos selecionados não "
                            "retornaram registros para o termo consultado. "
                            + (
                                f"Falha do orquestrador: {erro_intl}. "
                                if erro_intl
                                else "Cada portal respondeu em modo silencioso."
                            )
                        )
                    ),
                }

            if usar_usgs:
                # Compatibilidade com chamadas antigas que esperam a
                # chave ``usgs`` no dicionário de dados.
                registros_usgs = [
                    registro
                    for registro in registros_intl
                    if registro.get("fonte") == FONTE_USGS_INTERNACIONAL
                ]
                dados["usgs"] = {
                    "fonte": "USGS ScienceBase",
                    "pergunta": termo_en,
                    "termo_busca": termo_en,
                    "limite": len(registros_usgs),
                    "total": len(registros_usgs),
                    "registros": registros_usgs,
                    "aviso": (
                        None
                        if registros_usgs
                        else "Nenhum item do USGS ScienceBase foi "
                        "encontrado para o termo consultado."
                    ),
                }

    if usar_geosgb:
        # A extração de substância e UF acontece dentro do conector, a
        # partir da própria pergunta. Como nas bases internacionais, um
        # parâmetro inválido vira fonte vazia com o motivo no aviso.
        try:
            dados["geosgb"] = consultar_geosgb_ocorrencias(
                pergunta,
                limite=limite_geosgb
            )
        except ValueError as erro:
            dados["geosgb"] = _base_externa_indisponivel(
                "GeoSGB WFS", pergunta, limite_geosgb, erro
            )

    if usar_anm:
        # O recorte (substância, titular ou UF) é decidido dentro do
        # conector. A ANM oscila e apresenta cadeia de certificados
        # incompleta: o conector já devolve lista vazia com o motivo em
        # ``aviso`` em vez de levantar exceção de rede.
        try:
            dados["anm"] = consultar_anm_processos(
                pergunta,
                limite=limite_anm
            )
        except ValueError as erro:
            dados["anm"] = _base_externa_indisponivel(
                "ANM / SIGMINE", pergunta, limite_anm, erro
            )

    if usar_macrostrat:
        # As coordenadas saem da pergunta ou de um trecho de documento
        # local já recuperado acima. Sem coordenada, a consulta é por
        # nome de unidade litoestratigráfica — o conector decide.
        latitude, longitude = _coordenadas_da_consulta(pergunta, dados)

        try:
            dados["macrostrat"] = consultar_macrostrat(
                pergunta,
                lat=latitude,
                lon=longitude,
                limite=limite_macrostrat
            )
        except ValueError as erro:
            dados["macrostrat"] = _base_externa_indisponivel(
                "Macrostrat", pergunta, limite_macrostrat, erro
            )

    if usar_siagas:
        # O município e a UF são extraídos dentro do conector, sem
        # concatenar a frase inteira no filtro CQL do WFS.
        try:
            dados["siagas"] = consultar_siagas_pocos(
                pergunta,
                limite=limite_siagas
            )
        except ValueError as erro:
            dados["siagas"] = _base_externa_indisponivel(
                "SIAGAS / SGB", pergunta, limite_siagas, erro
            )

    if usar_geossit:
        # Como no SIAGAS, o recorte geográfico é definido pelo conector
        # a partir da pergunta.
        try:
            dados["geossit"] = consultar_geossit_inde(
                pergunta,
                limite=limite_geossit
            )
        except ValueError as erro:
            dados["geossit"] = _base_externa_indisponivel(
                "INDE / GEOSSIT", pergunta, limite_geossit, erro
            )

    return dados if dados else None


def responder(
    pergunta,
    modo=None,
    historico=None,
    limite=5,
    comunidade=None,
    modelo=None,
    texto_prompt=None,
    documentos=None,
    usar_llm_termos=False,
    usar_ana=False,
    usar_web=False,
    web_apenas_tecnico=False,
    limite_web=WEB_LIMITE_PADRAO,
    usar_sgb=True,
    usar_documentos=True,
    usar_openalex=False,
    usar_usgs=False,
    limite_externo=5,
    usar_intl_geo=False,
    regioes_intl_geo=None,
    usar_geosgb=False,
    limite_geosgb=GEOSGB_LIMITE_PADRAO,
    usar_anm=False,
    limite_anm=ANM_LIMITE_PADRAO,
    usar_macrostrat=False,
    limite_macrostrat=MACROSTRAT_LIMITE_PADRAO,
    usar_siagas=False,
    limite_siagas=SIAGAS_LIMITE_PADRAO,
    usar_geossit=False,
    limite_geossit=GEOSSIT_LIMITE_PADRAO,
    usgs_enabled=None,
    intl_geo_enabled=None,
    intl_geo_regioes=None,
    idioma: str = "pt"
):
    """Responde à pergunta combinando as fontes externas e o LLM local.

    O roteamento é **orientado aos toggles** da barra lateral: cada fonte
    com o toggle ligado entra na consulta, sem exceção. ``usar_sgb``
    governa o acervo RIGeo e ``usar_documentos`` a base documental
    local; ``usar_ana``, ``usar_web``, ``usar_openalex``, ``usar_usgs``,
    ``usar_geosgb``, ``usar_anm``, ``usar_macrostrat``, ``usar_siagas``
    e ``usar_geossit`` ligam os conectores correspondentes. A
    classificação de intenção continua rodando, mas só para registrar a
    justificativa e otimizar os filtros (município, UF, substância e
    rio), nunca para descartar uma fonte que o usuário ligou.

    ``modo`` é aceito apenas para compatibilidade com chamadores
    antigos: um modo manual (``"Geologia (SGB)"``, ``"Documentos (RAG)"``
    ou ``"Conhecimento geral"``) ainda restringe as fontes como antes.
    Sem ele — o fluxo atual da interface — as fontes vêm dos toggles.

    ``limite`` e ``comunidade`` são os filtros escolhidos na barra
    lateral e são repassados à consulta do SGB; os demais modos de
    fonte não são afetados por eles.

    ``modelo`` é o modelo do Ollama escolhido no seletor da barra
    lateral. Quando não é informado, ``gerar_resposta`` usa o padrão de
    ``config.py``. O roteador inteligente e a extração opcional de
    termos usam o mesmo modelo.

    ``texto_prompt`` é o texto atual da caixa "Editar System Prompt".
    Ele é repassado a ``montar_prompt_sistema`` e passa a valer já nesta
    pergunta, mesmo que a edição exista apenas na sessão e ainda não
    tenha sido gravada em ``prompts/system_base.txt``. Sem ele, o arquivo
    padrão é lido.

    ``documentos`` é a lista de documentos locais já carregada pela
    interface. Quando omitida, o roteador lê ``data/docs`` novamente.

    ``usar_llm_termos`` liga o refinamento opcional da consulta ao RIGeo
    pelo Ollama. Desligado (o padrão), a extração é 100% determinística.

    ``usar_ana`` liga o conector do inventário de estações da ANA
    (HidroWeb). O resultado fica em ``dados["ana"]`` e a interface o
    mostra no status e no expander de fontes. Quem liga ou desliga o
    conector é o toggle ``ana_enabled`` da barra lateral; a intenção da
    pergunta não liga uma fonte que o usuário deixou desligada.

    ``usar_web`` liga a pesquisa na Web aberta (DDGS). Como a ANA, é
    independente dos demais toggles. ``web_apenas_tecnico`` restringe a
    busca a domínios técnicos e institucionais e ``limite_web`` controla
    quantas páginas voltam. Os registros ficam em ``dados["web"]`` e a
    interface os lista nos cartões de "📚 Fontes e Metadados
    Consultados".

    ``usar_sgb`` e ``usar_documentos`` são os toggles do acervo
    RIGeo/GeoBusca e da base documental local. ``usar_openalex`` e
    ``usar_usgs`` ligam as bases internacionais abertas; a pergunta é
    traduzida para o inglês em ``dados["busca_externa"]`` e os registros
    ficam em ``dados["openalex"]`` e ``dados["usgs"]``.
    ``limite_externo`` controla quantos registros cada base devolve.

    ``usar_geosgb`` liga o conector das ocorrências minerais do GeoSGB:
    a substância e a UF são extraídas da pergunta, os registros ficam em
    ``dados["geosgb"]`` e ``limite_geosgb`` controla quantas ocorrências
    voltam. A tabela Markdown do contexto é montada em
    ``core.prompt_manager`` a partir desses registros.

    ``usar_intl_geo`` liga o grupo dos dez serviços geológicos
    internacionais e ``regioes_intl_geo`` restringe a busca às regiões
    escolhidas no multiselect. O termo é traduzido para o inglês e a
    tabela consolidada, com a coluna do serviço de origem, é injetada no
    contexto por ``core.prompt_manager``. ``usar_usgs`` permanece como
    compatibilidade: executa apenas o ScienceBase e preenche
    ``dados["usgs"]``. Os aliases ``intl_geo_enabled``,
    ``intl_geo_regioes`` e ``usgs_enabled`` reproduzem as chaves da
    interface para chamadores legados.

    ``usar_anm`` liga o conector dos processos minerários do SIGMINE: a
    substância, o titular e a UF saem da pergunta, os registros ficam em
    ``dados["anm"]`` e ``limite_anm`` controla quantos processos voltam.
    A tabela Markdown do contexto também é montada em
    ``core.prompt_manager``, separada da tabela do GeoSGB.

    ``usar_macrostrat``, ``usar_siagas`` e ``usar_geossit`` ligam os
    três conectores geológicos da última fase, com os limites em
    ``limite_macrostrat``, ``limite_siagas`` e ``limite_geossit``. Eles
    têm toggles próprios — como a Web, a ANA e as bases internacionais —
    e também nunca derrubam a resposta por falha de rede. Os registros
    ficam em ``dados["macrostrat"]``, ``dados["siagas"]`` e
    ``dados["geossit"]``, e as tabelas
    correspondentes são injetadas no contexto por
    ``core.prompt_manager``: estratigrafia (Macrostrat), poços e águas
    subterrâneas (SIAGAS/RIMAS) e patrimônio geológico (INDE/GEOSSIT).
    Quando a ANA e o SIAGAS devolvem dados na mesma consulta, o prompt
    pede explicitamente o cruzamento entre águas superficiais e
    subterrâneas.

    O retorno inclui ``busca_rigeo``: o termo efetivo, a origem da
    extração e a cadeia de consultas enviadas ao RIGeo (vazio quando a
    fonte SGB não foi consultada). É esse dicionário que a interface
    mostra no ``st.status``.

    ``idioma`` é o idioma escolhido nos botões de bandeira da barra
    lateral (``"pt"`` ou ``"en"``). Ele **não** interfere nas consultas:
    serve para injetar no system prompt a instrução explícita que exige
    a resposta técnica e as tabelas em Português do Brasil ou em inglês
    técnico, mantendo citações e nomes próprios originais das fontes.
    Idiomas desconhecidos caem no padrão ``"pt"``.
    """

    # Aliases de compatibilidade: a interface e chamadores antigos podem
    # informar as chaves de sessão diretamente, em vez dos parâmetros
    # ``usar_*``/``regioes_*``.
    if usgs_enabled is not None:
        usar_usgs = usar_usgs or bool(usgs_enabled)

    if intl_geo_enabled is not None:
        usar_intl_geo = bool(intl_geo_enabled)

    if intl_geo_regioes is not None:
        regioes_intl_geo = list(intl_geo_regioes)

    # 1. A classificação de intenção continua rodando para registrar a
    #    justificativa e o recorte da pergunta, mas não decide mais
    #    quais fontes consultar: isso é papel dos toggles da barra
    #    lateral. Um ``modo`` manual (compatibilidade) continua
    #    restringindo as fontes como antes.
    if modo and modo != "Automático":
        roteamento = _roteamento_manual(modo, documentos)
        fontes = list(FONTES_POR_MODO[modo])
    else:
        roteamento = decidir_roteamento(
            pergunta,
            documentos=documentos,
            modelo=modelo,
            historico=historico
        )

        fontes = []

        if usar_sgb:
            fontes.append("sgb")

        if usar_documentos:
            fontes.append("documentos")

    # 2. Filtros objetivos que a própria pergunta já revela. Eles são
    #    uma otimização sobre o mesmo recorte que os conectores aplicam
    #    internamente (município, UF, substância e rio) e ficam
    #    registrados no roteamento para a interface.
    filtros = extrair_filtros_consulta(pergunta)

    roteamento["filtros"] = filtros
    roteamento["fontes_efetivas"] = list(fontes)
    roteamento["usar_documentos"] = bool(
        "documentos" in fontes
    )
    roteamento["usar_ana"] = bool(usar_ana)
    roteamento["usar_intl_geo"] = bool(usar_intl_geo or usar_usgs)
    roteamento["regioes_intl_geo"] = list(regioes_intl_geo or [])
    roteamento["fontes_por_toggle"] = modo in (None, "Automático")
    roteamento["idioma"] = normalizar_idioma(idioma)

    dados = consultar_fonte(
        pergunta,
        fontes,
        limite=limite,
        comunidade=comunidade,
        modelo=modelo,
        usar_llm_termos=usar_llm_termos,
        usar_ana=usar_ana,
        usar_web=usar_web,
        web_apenas_tecnico=web_apenas_tecnico,
        limite_web=limite_web,
        usar_sgb=usar_sgb,
        usar_openalex=usar_openalex,
        usar_usgs=usar_usgs,
        limite_externo=limite_externo,
        usar_intl_geo=usar_intl_geo,
        regioes_intl_geo=regioes_intl_geo,
        usar_geosgb=usar_geosgb,
        limite_geosgb=limite_geosgb,
        usar_anm=usar_anm,
        limite_anm=limite_anm,
        usar_macrostrat=usar_macrostrat,
        limite_macrostrat=limite_macrostrat,
        usar_siagas=usar_siagas,
        limite_siagas=limite_siagas,
        usar_geossit=usar_geossit,
        limite_geossit=limite_geossit
    )

    # O system prompt é montado na camada de orquestração e reflete
    # apenas as fontes que realmente retornaram dados nesta consulta. A
    # pergunta vai junto para que a tabela de equivalência PT-BR ↔ EN
    # inclua os termos técnicos que ela mesma trouxe.
    prompt_sistema = montar_prompt_sistema(
        dados,
        texto_base=texto_prompt,
        pergunta=pergunta
    )

    # Instrução explícita de idioma: orienta o modelo a redigir toda a
    # resposta técnica (texto, tabelas, títulos e conclusões) no idioma
    # escolhido, sem traduzir citações e nomes próprios das fontes. Ela
    # é acrescentada ao final para prevalecer sobre instruções genéricas
    # do texto base.
    idioma_normalizado = normalizar_idioma(idioma)
    instrucao_sintese = _instrucao_metalogenetica_global(pergunta, dados)

    partes_prompt = [(prompt_sistema or "").rstrip()]

    if instrucao_sintese:
        partes_prompt.append(instrucao_sintese)

    partes_prompt.append(instrucao_idioma_resposta(idioma_normalizado))

    prompt_sistema = "\n\n".join(
        parte for parte in partes_prompt if parte
    )

    resposta = gerar_resposta(
        pergunta=pergunta,
        dados=dados,
        historico=historico,
        prompt_sistema=prompt_sistema,
        modelo=modelo
    )

    # O rótulo da fonte ANA acompanha a origem real do dado: quando o
    # conector devolveu do cache local, a interface, o histórico e o
    # prompt precisam mostrar "ANA / HidroWeb (cache local)".
    cache_ana = ((dados or {}).get("ana") or {}).get("cache") or {}
    fonte_ana = (
        "ANA / HidroWeb (cache local)"
        if cache_ana.get("usado")
        else "ANA / HidroWeb"
    )

    nomes = {
        "sgb": "SGB",
        "documentos": "Documentos locais",
        "ana": fonte_ana,
        "siagas": "SIAGAS / RIMAS",
        "macrostrat": "Macrostrat",
        "geossit": "INDE / GEOSSIT",
        "geosgb": "GeoSGB WFS",
        "anm": "ANM / SIGMINE",
        "openalex": "OpenAlex",
        "usgs": "USGS ScienceBase",
        "intl_geo": "Serviços Geológicos Internacionais",
        "web": "Web",
    }

    if dados:
        fonte_nome = " + ".join(
            nomes[chave]
            for chave in (
                "sgb",
                "documentos",
                "ana",
                "siagas",
                "macrostrat",
                "geossit",
                "geosgb",
                "anm",
                "openalex",
                "usgs",
                "intl_geo",
                "web"
            )
            if chave in dados
        )
    else:
        fonte_nome = "Ollama"

    return {
        "resposta": resposta,
        "fonte": fonte_nome,
        "dados": dados,
        "roteamento": roteamento,
        "busca_rigeo": (dados or {}).get("busca") or {}
    }
