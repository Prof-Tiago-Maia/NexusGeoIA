"""Perfis analíticos (modos de análise) do system prompt.

Cada perfil é um bloco de instruções geocientíficas que a interface
acrescenta ao texto base de ``prompts/system_base.txt``. A escolha fica
na barra lateral (``app.py``) e o texto resultante é repassado como
``texto_prompt=`` para ``montar_prompt_sistema(...)``.

O perfil ``Personalizado`` não tem bloco próprio: as instruções são as
que o usuário escrever na caixa de edição.

Os blocos são autocontidos e terminam com um texto fixo; é por esse
texto que :func:`remover_blocos_de_perfil` retira o bloco de um perfil
anterior ao trocar de modo, sem duplicar instruções no prompt ativo.
"""

PERFIL_PADRAO = "Geociências Geral (Padrão)"
PERFIL_PERSONALIZADO = "Personalizado"

# Ordem em que os modos aparecem no seletor da barra lateral. Cada modo
# tem um bloco autocontido; o perfil geral usa o próprio texto base e o
# personalizado usa a instrução livre escrita na caixa de edição.
PERFIS_ANALITICOS = {
    PERFIL_PADRAO: {
        "rotulo_curto": "Geral",
        "descricao": (
            "Síntese técnica equilibrada, com rigor bibliográfico e "
            "citação de todas as fontes."
        ),
        # O texto de prompts/system_base.txt já é o perfil geral: não há
        # bloco extra a acrescentar.
        "instrucoes": "",
    },
    "Geologia Regional & Mapeamento Geológico": {
        "rotulo_curto": "Geologia regional",
        "descricao": (
            "Litoestratigrafia, províncias estruturais, geocronologia, "
            "evolução tectônica, contatos e folhas cartográficas "
            "(1:100.000 / 1:250.000)."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — GEOLOGIA REGIONAL & MAPEAMENTO "
            "GEOLÓGICO\n"
            "Priorize, em todas as respostas:\n"
            "- litoestratigrafia: unidades e sua hierarquia (grupo, "
            "formação, membro), litotipos, espessuras e relações de "
            "contato (concordante, discordante, tectônico);\n"
            "- províncias estruturais e domínios tectônicos, com as "
            "fases de deformação, dobramento e falhamento reconhecidas;\n"
            "- geocronologia: método (U-Pb, Rb-Sr, Sm-Nd, Ar-Ar, K-Ar), "
            "material datado, idade, incerteza analítica e a diferença "
            "entre idade de cristalização, metamorfismo e resfriamento;\n"
            "- evolução tectônica e contexto geodinâmico (crátons, "
            "orógenos, arcos, bacias), com a escala temporal em Ma;\n"
            "- contatos geológicos, falhas, zonas de cisalhamento e "
            "lineamentos, com atitude (rumo/mergulho) quando a fonte "
            "informar;\n"
            "- folhas cartográficas, articulação e escala do mapeamento "
            "(1:100.000, 1:250.000 ou outra), com a nomenclatura oficial "
            "da folha quando disponível;\n"
            "- correlação regional entre áreas e unidades equivalentes, "
            "separando correlação proposta de contato observado.\n"
            "Informe sempre a escala do estudo e a fonte cartográfica. "
            "Não extrapole contatos, idades ou correlações para além da "
            "área mapeada e não atribua idade a uma unidade que as "
            "fontes não dataram."
        ),
    },
    "Exploração Mineral & Geoquímica": {
        "rotulo_curto": "Exploração mineral",
        "descricao": (
            "Teores, controles litológicos/estruturais e paragênese, "
            "com foco em recursos, reservas e anomalias."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — EXPLORAÇÃO MINERAL & GEOQUÍMICA\n"
            "Priorize, em todas as respostas:\n"
            "- teores e unidades (%, ppm, ppb, g/t), limite de detecção, "
            "método analítico e QA/QC;\n"
            "- controles estruturais (falhas, dobras, zonas de "
            "cisalhamento) e litológicos (rochas hospedeiras e alteração "
            "hidrotermal);\n"
            "- paragênese, sucessão mineral e assembleias de minério e "
            "ganga;\n"
            "- classificação de recursos e reservas (JORC, NI 43-101, "
            "SAMREC ou o código informado na fonte) e o teor de corte "
            "correspondente;\n"
            "- anomalias geoquímicas, background, threshold e dispersão "
            "primária e secundária;\n"
            "- modelo metalogenético e ambiente geotectônico "
            "compatíveis.\n"
            "Separe sempre dado medido de interpretação, informe a "
            "escala do estudo e não extrapole teores, tonelagens ou "
            "recursos a partir de descrição qualitativa. Quando um valor "
            "não constar das fontes, declare a lacuna."
        ),
    },
    "Hidrogeologia & Recursos Hídricos": {
        "rotulo_curto": "Hidrogeologia",
        "descricao": (
            "Balanço hídrico, aquíferos, níveis, vazões, bacias e "
            "monitoramento ANA/SIAGAS."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — HIDROGEOLOGIA & RECURSOS HÍDRICOS\n"
            "Priorize, em todas as respostas:\n"
            "- balanço hídrico (precipitação, evapotranspiração, "
            "escoamento, recarga e variação de reserva) e a base de "
            "dados de cada termo;\n"
            "- aquíferos e sua condição (livre, confinado, "
            "semiconfinado), porosidade, permeabilidade, "
            "transmissividade, condutividade hidráulica e coeficiente de "
            "armazenamento;\n"
            "- níveis estático e dinâmico, profundidade do poço e "
            "rebaixamento, com a data da medição quando a fonte "
            "informar;\n"
            "- vazões (m³/s, L/s), curvas de permanência, mínimas Q7,10 "
            "e Q95 e séries históricas;\n"
            "- bacias e sub-bacias hidrográficas, áreas de contribuição "
            "e divisores;\n"
            "- monitoramento: estações fluviométricas e pluviométricas "
            "da ANA (código, tipo, rio, município/UF e coordenadas) e "
            "poços do SIAGAS/RIMAS (código do ponto, aquífero captado e "
            "níveis), quando esses conectores estiverem ativos.\n"
            "Não deduza vazões, cotas ou séries históricas a partir do "
            "inventário de estações nem de médias regionais: informe a "
            "ausência do dado."
        ),
    },
    "Geotecnia & Geologia de Engenharia": {
        "rotulo_curto": "Geotecnia",
        "descricao": (
            "Maciços rochosos e solos, intemperismo, estabilidade de "
            "taludes, fundações, permeabilidade e riscos geológicos."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — GEOTECNIA & GEOLOGIA DE ENGENHARIA\n"
            "Priorize, em todas as respostas:\n"
            "- maciços rochosos: litologia, grau de alteração e "
            "fraturamento, RQD, RMR, Q de Barton, resistência à "
            "compressão e descontinuidades (atitude, persistência, "
            "abertura e preenchimento);\n"
            "- solos: classificação (granulometria, plasticidade, "
            "SUCS), espessura, compacidade/consistência, expansividade "
            "e colapsividade;\n"
            "- intemperismo e perfil de alteração, com a zona de "
            "transição rocha-solo;\n"
            "- estabilidade de taludes: geometria, ruptura planar, em "
            "cunha, por tombamento e circular, nível d'água e medidas "
            "de contenção;\n"
            "- fundações: capacidade de carga, recalque, investigação "
            "(SPT, CPT, sondagem rotativa) e condicionantes do "
            "substrato;\n"
            "- permeabilidade, condutividade hidráulica, ensaios e "
            "drenagem;\n"
            "- riscos geológicos: escorregamentos, erosão, "
            "subsidência, sismicidade e enchentes.\n"
            "Diferencie parâmetro medido de estimativa e informe o "
            "ensaio e a norma aplicada (ABNT NBR, ISRM). Não converta "
            "descrição litológica em parâmetros geotécnicos numéricos "
            "sem o ensaio correspondente."
        ),
    },
    "Sensoriamento Remoto & Geofísica": {
        "rotulo_curto": "Sensoriamento remoto",
        "descricao": (
            "Assinaturas espectrais, magnetometria, "
            "gamaespectrometria, gravimetria, lineamentos e alvos "
            "geofísicos."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — SENSORIAMENTO REMOTO & GEOFÍSICA\n"
            "Priorize, em todas as respostas:\n"
            "- assinaturas espectrais: faixas (VNIR, SWIR, TIR), "
            "minerais e alterações diagnósticas (argilas, óxidos de "
            "ferro, carbonatos, silicatos), índices e sensores (ASTER, "
            "Sentinel-2, Landsat 8/9);\n"
            "- magnetometria: anomalias e domínios, intensidade, "
            "redução ao polo, derivadas e lineamentos, com a "
            "interpretação das fontes;\n"
            "- gamaespectrometria: canais K, eTh e eU, razões e "
            "anomalias;\n"
            "- gravimetria: anomalias Bouguer, separação "
            "regional/residual, modelagem e contraste de densidade;\n"
            "- lineamentos estruturais, trends regionais e sua relação "
            "com a geologia mapeada;\n"
            "- alvos geofísicos e de sensoriamento remoto, com o "
            "critério que sustenta cada alvo e o nível de confiança.\n"
            "Informe sensor, banda, resolução e datum das coordenadas. "
            "Uma anomalia geofísica ou espectral é indicativa: não a "
            "converta em teor, reserva ou minério sem verificação de "
            "campo e análise química."
        ),
    },
    "Licenciamento & Risco Ambiental": {
        "rotulo_curto": "Licenciamento",
        "descricao": (
            "Passivos, condicionantes, impactos hídricos/edáficos e "
            "conformidade regulatória (ANM/IBAMA)."
        ),
        "instrucoes": (
            "PERFIL ANALÍTICO — LICENCIAMENTO & RISCO AMBIENTAL\n"
            "Priorize, em todas as respostas:\n"
            "- passivos ambientais em solo, sedimento, água superficial "
            "e subterrânea, com as evidências analíticas disponíveis;\n"
            "- condicionantes, medidas mitigadoras e compensatórias de "
            "EIA/RIMA, PCA, PRAD, plano de recuperação e plano de "
            "fechamento de mina;\n"
            "- impactos hídricos (rebaixamento do nível d'água, "
            "captação, lançamento de efluentes, assoreamento) e edáficos "
            "(compactação, erosão, perda de horizonte orgânico);\n"
            "- conformidade regulatória: ANM (título minerário, plano de "
            "lavra, CFEM), IBAMA e CONAMA, órgãos estaduais e "
            "municipais, unidades de conservação e terras indígenas;\n"
            "- risco: probabilidade, severidade, medidas de controle e "
            "monitoramento proposto.\n"
            "Não afirme conformidade legal nem emita parecer jurídico: "
            "descreva o que as fontes sustentam e indique a verificação "
            "documental e a consultoria especializada necessárias."
        ),
    },
    PERFIL_PERSONALIZADO: {
        "rotulo_curto": "Personalizado",
        "descricao": (
            "Instrução livre: o texto da caixa de edição vale como "
            "está, sem bloco automático."
        ),
        "instrucoes": "",
    },
}


def dados_do_perfil(nome):
    """Dados do perfil; devolve o padrão quando o nome é desconhecido."""

    return PERFIS_ANALITICOS.get(nome) or PERFIS_ANALITICOS[PERFIL_PADRAO]


def bloco_do_perfil(nome):
    """Bloco de instruções do perfil, sem espaços nas extremidades.

    Perfis sem bloco próprio (``Geociências Geral`` e ``Personalizado``)
    devolvem string vazia.
    """

    return (dados_do_perfil(nome).get("instrucoes") or "").strip()


def montar_prompt_do_perfil(nome, texto_base):
    """Acrescenta o bloco do perfil ao texto base informado.

    O texto base é o conteúdo editável de ``prompts/system_base.txt``.
    O bloco entra sempre no fim, separado por uma linha em branco, para
    que :func:`remover_blocos_de_perfil` o reconheça e possa retirá-lo
    quando o usuário trocar de modo.
    """

    base = (texto_base or "").strip()
    bloco = bloco_do_perfil(nome)

    if not bloco:
        return base

    if not base:
        return bloco

    return f"{base}\n\n{bloco}"


def detectar_perfil(texto):
    """Perfil cujo bloco termina o texto informado.

    Devolve ``None`` quando nenhum bloco conhecido está no fim do texto,
    o que inclui o texto base sem perfil. É o inverso de
    :func:`montar_prompt_do_perfil` e mantém o seletor coerente com um
    prompt que já foi salvo em disco.
    """

    texto = (texto or "").rstrip()

    for nome, dados in PERFIS_ANALITICOS.items():
        bloco = (dados.get("instrucoes") or "").strip()

        if bloco and texto.endswith(bloco):
            return nome

    return None


def remover_blocos_de_perfil(texto):
    """Retira do fim do texto os blocos de perfil conhecidos.

    A remoção compara o texto exato dos blocos, então edições do usuário
    não são descartadas: se o bloco foi alterado, ele permanece. Serve
    para trocar de perfil sem duplicar instruções, inclusive quando o
    prompt salvo em disco já contém o bloco de um modo anterior.
    """

    texto = (texto or "").rstrip()
    removeu = True

    while removeu:
        removeu = False

        for dados in PERFIS_ANALITICOS.values():
            bloco = (dados.get("instrucoes") or "").strip()

            if bloco and texto.endswith(bloco):
                texto = texto[: -len(bloco)].rstrip()
                removeu = True
                break

    return texto
