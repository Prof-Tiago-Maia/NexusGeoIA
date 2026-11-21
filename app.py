"""Interface Streamlit do NexusGeo IA.

Esta camada é apenas de apresentação: o roteamento, a orquestração e o
system prompt continuam em ``core/``, os conectores de fontes em
``services/`` e a persistência em ``database/``. O fluxo de consulta
segue ``core.assistant.responder()``, com o conector opcional da
ANA/HidroWeb ao lado das fontes já existentes.

A interface aproveita o que já vem no retorno de ``responder()``:

- ``roteamento``: intenção (``LOCAL_ONLY``, ``RIGEO_ONLY``, ``HIBRIDO``,
  ``ANA_ONLY`` ou ``GERAL``), justificativa, origem da decisão, filtros
  reconhecidos na pergunta (município, UF, substância e rio), as fontes
  efetivamente consultadas e os documentos locais considerados;
- ``artigos_rigeo``: registros do RIGeo (título, autores, ano e links),
  guardados no histórico da sessão para os cartões de metadados;
- ``busca_rigeo``: o termo efetivamente enviado ao RIGeo, a origem da
  extração e a cadeia de consultas, exibidos no bloco de status para o
  usuário conferir o que foi pesquisado;
- ``estacoes_ana``: estações fluviométricas e pluviométricas do
  inventário público da ANA/HidroWeb, consultadas de forma opcional pela
  barra lateral e guardadas no histórico para o expander de fontes;
- ``openalex`` e ``usgs``: publicações das bases internacionais abertas
  (OpenAlex e USGS ScienceBase), ligadas de forma opcional na seção
  "Fontes de Dados Ativas" da barra lateral e exibidas no mesmo padrão
  visual do RIGeo;
- ``intl_geo``: grupo unificado dos serviços geológicos internacionais
  abertos (OneGeology, USGS, NRCan, EGDI, GA/GSQ, GSJ, GeoNet,
  CGS/Digital Earth Africa, NGD e GSI/Bhukosh), com filtro de regiões
  na barra lateral e origem preservada em cada registro;
- ``geosgb``: ocorrências minerais do Serviço Geológico do Brasil
  (GeoSGB WFS), com alvo, substância, status, município/UF, folha
  cartográfica e coordenadas, exibidas no status e nos cartões de fontes;
- ``anm``: processos minerários da Agência Nacional de Mineração
  (SIGMINE), com número do processo, ano, fase, titular, substância,
  área em hectares e UF, exibidos no status e nos cartões de fontes —
  o par regulatório do GeoSGB, em uma base independente;
- ``macrostrat``: unidades litoestratigráficas da base pública
  Macrostrat, com idade, litologia e ambiente deposicional, para
  contextualizar a geologia local;
- ``siagas``: poços tubulares do SIAGAS/RIMAS (SGB), com profundidade,
  níveis estático e dinâmico, vazão, aquífero e coordenadas;
- ``geossit``: geossítios e sítios da geodiversidade do INDE/GEOSSIT,
  com categoria, município/UF, relevância e coordenadas.

O system prompt combina o texto base editável com o bloco do perfil
analítico escolhido na barra lateral (``core.analytical_profiles``).

Todos são exibidos no bloco de status da consulta e no expander de
fontes, tanto na resposta nova quanto ao renderizar o histórico.
"""

import json
import os
import re
import threading
import urllib.parse
from importlib import import_module
from pathlib import Path

# ---------------------------------------------------------------------------
# Certificados TLS antes dos imports de terceiros, core e services
# ---------------------------------------------------------------------------
#
# BUG CORRIGIDO: no executável congelado o contexto SSL criado pelo
# ``ollama``/``httpx`` não encontrava o ``cacert.pem`` do ``certifi`` e o
# import de ``services.llm_service`` morria com ``FileNotFoundError``. A
# correção vive também no ``launcher_desktop.py``; repetir aqui cobre a
# execução direta (``streamlit run app.py`` em desenvolvimento) e a
# importação do ``app`` pelo smoke test do bundle.
#
# O caminho definido pelo usuário só é substituído quando está vazio ou
# aponta para um arquivo inexistente.
try:
    _certifi = import_module("certifi")
except Exception:  # noqa: BLE001 - ambiente sem certifi
    _certifi = None

_CAMINHO_CERTIFICADOS = ""

if _certifi is not None:
    try:
        _CAMINHO_CERTIFICADOS = str(_certifi.where())
    except Exception:  # noqa: BLE001 - certifi sem arquivo de CAs
        _CAMINHO_CERTIFICADOS = ""

if _CAMINHO_CERTIFICADOS and os.path.isfile(_CAMINHO_CERTIFICADOS):
    for _variavel_certificado in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        _valor_atual = os.environ.get(_variavel_certificado, "").strip()

        if not _valor_atual or not os.path.isfile(_valor_atual):
            os.environ[_variavel_certificado] = _CAMINHO_CERTIFICADOS

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from config import APP_NAME, APP_VERSION, OLLAMA_HOST, OLLAMA_MODEL
from core.analytical_profiles import (
    PERFIL_PADRAO,
    PERFIL_PERSONALIZADO,
    PERFIS_ANALITICOS,
    dados_do_perfil,
    detectar_perfil,
    montar_prompt_do_perfil,
    remover_blocos_de_perfil
)
from core.assistant import responder
from core.prompt_manager import (
    PromptBaseAusenteError,
    carregar_prompt_base,
    salvar_prompt_base
)
from services import document_parser
from services.external_api_service import (
    COMUNIDADE_TODAS,
    COMUNIDADES_RIGEO,
    OPCOES_REGIOES_INTERNACIONAIS,
    REGIAO_TODAS,
    montar_tabela_geossitios,
    montar_tabela_ocorrencias_geosgb,
    montar_tabela_pocos_siagas,
    montar_tabela_processos_anm,
    montar_tabela_servicos_geologicos,
    montar_tabela_unidades_macrostrat,
    web_disponivel
)
from services.glossario_bilingue import rotulo_idioma
from services.history_service import (
    HistoricoError,
    agora_iso,
    carregar_conversa,
    excluir_conversa,
    excluir_todas_conversas,
    gerar_titulo,
    listar_conversas,
    novo_session_id,
    salvar_conversa
)
from services.llm_service import (
    garantir_ollama_ativo,
    listar_modelos_locais
)
from services.rag_service import (
    DocumentoInvalidoError,
    avaliar_arquivo,
    descrever_extracoes,
    limpar_cache,
    listar_documentos,
    mensagem_arquivo_sem_texto,
    salvar_documento
)
from services.report_generator import (
    RelatorioError,
    gerar_parecer_docx,
    gerar_parecer_markdown,
    nome_arquivo_parecer
)
from services.spatial_parser import (
    consolidar_pontos_mapa,
    gerar_csv_pontos
)
from services.table_extractor import (
    chave_registro,
    consolidar_dados_sessao,
    extrair_tabelas_documento,
    gerar_csv,
    gerar_excel,
    nome_arquivo_tabela
)
from utils.i18n import (
    IDIOMA_PADRAO,
    NOMES_IDIOMA,
    ROTULOS_IDIOMA,
    descricao_perfil,
    perfil_do_rotulo,
    regiao_do_rotulo,
    rotulo_curto_perfil,
    rotulo_curto_regiao,
    rotulo_perfil,
    rotulo_regiao,
    t,
    tf
)

# Endereço do Ollama sem o esquema, apenas para o badge do cabeçalho.
HOST_OLLAMA_EXIBICAO = (
    OLLAMA_HOST
    .replace("https://", "")
    .replace("http://", "")
    .rstrip("/")
)

# Avatar do assistente: ícone de geociências em vez do avatar padrão.
AVATAR_ASSISTENTE = ":material/terrain:"

# Verificação de saúde do Ollama: tempo máximo de espera por tentativa e
# intervalo de atualização automática do badge (em segundos).
TEMPO_LIMITE_STATUS_OLLAMA = 1.5
INTERVALO_STATUS_OLLAMA = 20

# Classes de intenção devolvidas pelo roteador (``core.smart_router``).
INTENCAO_LOCAL = "LOCAL_ONLY"
INTENCAO_RIGEO = "RIGEO_ONLY"
INTENCAO_HIBRIDO = "HIBRIDO"
INTENCAO_ANA = "ANA_ONLY"
INTENCAO_GERAL = "GERAL"

# Apenas essas intenções consultam a base documental local.
INTENCOES_COM_DOCUMENTOS = (INTENCAO_LOCAL, INTENCAO_HIBRIDO)

CORES_INTENCAO = {
    INTENCAO_LOCAL: "blue",
    INTENCAO_RIGEO: "orange",
    INTENCAO_HIBRIDO: "violet",
    INTENCAO_ANA: "blue",
    INTENCAO_GERAL: "gray",
}

# Chave de i18n do rótulo de cada intenção. O valor exibido vem de
# ``utils.i18n.t``, então o mesmo mapa serve aos dois idiomas.
CHAVES_ROTULO_INTENCAO = {
    INTENCAO_LOCAL: "intencao_local",
    INTENCAO_RIGEO: "intencao_rigeo",
    INTENCAO_HIBRIDO: "intencao_hibrido",
    INTENCAO_ANA: "intencao_ana",
    INTENCAO_GERAL: "intencao_geral",
}

# Cor do badge de cada fonte ativa exibida no cabeçalho.
CORES_FONTE = {
    "Base local": "violet",
}

# Cor do badge do perfil analítico. Perfis especializados têm cor própria
# para o modo ativo ser reconhecido de relance no cabeçalho.
CORES_PERFIL = {
    PERFIL_PADRAO: "gray",
    "Geologia Regional & Mapeamento Geológico": "blue",
    "Exploração Mineral & Geoquímica": "orange",
    "Hidrogeologia & Recursos Hídricos": "blue",
    "Geotecnia & Geologia de Engenharia": "green",
    "Sensoriamento Remoto & Geofísica": "red",
    "Licenciamento & Risco Ambiental": "green",
    PERFIL_PERSONALIZADO: "violet",
}

# Conectores externos da seção "Fontes de Dados Ativas" da barra
# lateral. Cada item vira um ``st.toggle`` e a chave é a mesma de
# ``session_state`` lida pelo roteador e pelos badges do cabeçalho. O
# catálogo guarda o valor padrão e as chaves de i18n do rótulo e da
# ajuda (``utils.i18n``); a ordem e o agrupamento visual ficam em
# ``GRUPOS_CONECTORES``, que precisa listar cada chave daqui exatamente
# uma vez.
CONECTORES_EXTERNOS = (
    {
        "chave": "rigeo_enabled",
        "rotulo_i18n": "fonte_rigeo",
        "padrao": True,
        "ajuda_i18n": "ajuda_fonte_rigeo",
    },
    {
        "chave": "ana_enabled",
        "rotulo_i18n": "fonte_ana",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_ana",
    },
    {
        "chave": "web_search_enabled",
        "rotulo_i18n": "fonte_web",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_web",
    },
)

# Fase 2: bases internacionais disponíveis e os conectores geológicos,
# exibidos na mesma seção visível. Como no catálogo acima, os textos
# vêm de ``utils.i18n`` e o conector só guarda as chaves. Desligados por
# padrão: mantêm a resposta rápida e o aplicativo utilizável sem
# internet.
CONECTORES_FASE_2 = (
    {
        "chave": "openalex_enabled",
        "rotulo_i18n": "fonte_openalex",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_openalex",
    },
    {
        "chave": "intl_geo_enabled",
        "rotulo_i18n": "fonte_intl_geo",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_intl_geo",
    },
    {
        "chave": "geosgb_enabled",
        "rotulo_i18n": "fonte_geosgb",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_geosgb",
    },
    {
        "chave": "anm_enabled",
        "rotulo_i18n": "fonte_anm",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_anm",
    },
    {
        "chave": "macrostrat_enabled",
        "rotulo_i18n": "fonte_macrostrat",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_macrostrat",
    },
    {
        "chave": "siagas_enabled",
        "rotulo_i18n": "fonte_siagas",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_siagas",
    },
    {
        "chave": "geossit_enabled",
        "rotulo_i18n": "fonte_geossit",
        "padrao": False,
        "ajuda_i18n": "ajuda_fonte_geossit",
    },
)

# Ordem e agrupamento visual da seção "Fontes de Dados Ativas" da barra
# lateral. Cada grupo vira um título curto (chave de i18n) e mantém
# juntos os conectores da mesma família; a sequência desta tupla é a
# ordem em que os ``st.toggle`` aparecem e a mesma usada pelos badges do
# cabeçalho.
GRUPOS_CONECTORES = (
    {
        "titulo_i18n": "grupo_acervo_web",
        "chaves": ("rigeo_enabled", "web_search_enabled"),
    },
    {
        "titulo_i18n": "grupo_hidrologia",
        "chaves": ("ana_enabled", "siagas_enabled"),
    },
    {
        "titulo_i18n": "grupo_recursos_minerais",
        "chaves": ("geosgb_enabled", "anm_enabled", "geossit_enabled"),
    },
    {
        "titulo_i18n": "grupo_bases_cientificas",
        "chaves": (
            "macrostrat_enabled",
            "openalex_enabled",
            "intl_geo_enabled",
        ),
    },
)

# Índice por chave de ``session_state``. Os grupos guardam apenas a ordem;
# rótulo, valor padrão e ajuda continuam vindo dos catálogos acima.
CONECTORES_POR_CHAVE = {
    conector["chave"]: conector
    for conector in CONECTORES_EXTERNOS + CONECTORES_FASE_2
}

# O agrupamento precisa cobrir cada conector do catálogo exatamente uma
# vez: sem esta conferência, um conector novo no catálogo poderia sumir
# da barra lateral sem nenhum aviso.
_CHAVES_CATALOGO = set(CONECTORES_POR_CHAVE)
_CHAVES_AGRUPADAS = [
    chave
    for grupo in GRUPOS_CONECTORES
    for chave in grupo["chaves"]
]

if (
    len(_CHAVES_AGRUPADAS) != len(_CHAVES_CATALOGO)
    or set(_CHAVES_AGRUPADAS) != _CHAVES_CATALOGO
):
    raise RuntimeError(
        "GRUPOS_CONECTORES deve listar cada conector do catálogo uma "
        "única vez."
    )

# Guia rápido exibido apenas enquanto a conversa atual está vazia. Cada
# passo aponta para as chaves de título e texto em ``utils.i18n``; quatro
# passos em grade 2x2 mantêm o painel compacto, sem rolagem. O conteúdo
# acompanha o idioma ativo escolhido no topo da barra lateral.
GUIA_RAPIDO_PASSOS = (
    ("guia_passo_1_titulo", "guia_passo_1_texto"),
    ("guia_passo_2_titulo", "guia_passo_2_texto"),
    ("guia_passo_3_titulo", "guia_passo_3_texto"),
    ("guia_passo_4_titulo", "guia_passo_4_texto"),
)

# Dicas de combinação de fontes por tipo de consulta. O bloco é exibido
# logo abaixo dos quatro passos, no mesmo painel central, e aponta para
# as chaves bilíngues de ``utils.i18n``. Cada item é um par
# (título, texto).
GUIA_COMBINACAO_FONTES = (
    ("guia_combinacao_1_titulo", "guia_combinacao_1_texto"),
    ("guia_combinacao_2_titulo", "guia_combinacao_2_texto"),
    ("guia_combinacao_3_titulo", "guia_combinacao_3_texto"),
    ("guia_combinacao_4_titulo", "guia_combinacao_4_texto"),
)

# Quantidade de documentos listados na barra lateral antes de resumir.
LIMITE_DOCUMENTOS_VISIVEIS = 12


# ---------------------------------------------------------------------------
# Estilo e chrome da página
# ---------------------------------------------------------------------------

# Fundo temático: seção geológica/geofísica desenhada em SVG vetorial e
# aplicada como ``background-image`` no container principal. A arte é
# discreta e fica em opacidade baixa (0.035 a 0.06), para dar identidade
# visual sem competir com o texto.
SVG_FUNDO_GEO = """
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420" fill="none">
  <!-- Perfil Geofísico (Anomalia Magnetométrica/Gravimétrica) -->
  <path d="M0 65 Q 110 62, 180 48 T 310 22 T 430 58 T 640 64" stroke="#58a6ff" stroke-width="1.2" opacity="0.06"/>
  <path d="M0 78 L 640 78" stroke="#8b949e" stroke-width="0.6" stroke-dasharray="3 5" opacity="0.04"/>
  <!-- Camadas de Rocha (Dobra Geológica / Estratigrafia) -->
  <path d="M0 160 C 160 130, 320 190, 480 150 C 560 130, 600 145, 640 155" stroke="#8b949e" stroke-width="1" opacity="0.05"/>
  <path d="M0 245 C 160 215, 320 275, 480 235 C 560 215, 600 230, 640 240" stroke="#8b949e" stroke-width="1" opacity="0.05"/>
  <path d="M0 330 C 160 300, 320 360, 480 320 C 560 300, 600 315, 640 325" stroke="#8b949e" stroke-width="1" opacity="0.045"/>
  <!-- Hachuras de Embasamento Cristalino (+) -->
  <g stroke="#8b949e" stroke-width="0.9" opacity="0.045">
    <path d="M80 360v8M76 364h8M210 375v8M206 379h8M360 365v8M356 369h8M510 355v8M506 359h8"/>
  </g>
  <!-- Veio de Minério / Intrusão Mineralizada (Âmbar Metálico Sutil) -->
  <path d="M265 420 L 318 142 L 332 142 L 282 420 Z" fill="#e0a952" opacity="0.035"/>
  <path d="M265 420 L 318 142 M 332 142 L 282 420" stroke="#e0a952" stroke-width="1" opacity="0.06"/>
  <!-- Geoquímica (Rede Cristalina / Hexágono e Pontos de Amostra) -->
  <polygon points="520,95 538,105 538,125 520,135 502,125 502,105" stroke="#3fb950" stroke-width="0.9" opacity="0.05"/>
  <circle cx="325" cy="142" r="2.5" fill="#e0a952" opacity="0.07"/>
  <circle cx="145" cy="195" r="2" fill="#8b949e" opacity="0.05"/>
  <circle cx="465" cy="280" r="2" fill="#8b949e" opacity="0.05"/>
</svg>
"""

# O SVG é embutido como data URI (UTF-8 em percent-encoding, método do
# RFC 2397 que não depende da codificação da página). As cores ``#`` são
# escapadas por ``quote`` e as aspas simples em ``url()`` protegem a
# sequência ``data:image/svg+xml,...``.
IMAGEM_FUNDO_TEMATICO = (
    "data:image/svg+xml,"
    + urllib.parse.quote(SVG_FUNDO_GEO, safe="")
)

# O CSS é reunido aqui para não espalhar regras pelo restante do roteiro.
#
# Três blocos:
#
# 0. Fundo temático — o container principal recebe a seção geológica em
#    SVG repetida (``640px 420px``) sobre o fundo do próprio tema, com um
#    ``radial-gradient`` escuro sutil no topo. O container do Streamlit
#    não tem cor de fundo própria, então o gradiente é translúcido e o
#    tema continua visível por baixo, preservando o contraste.
# 1. Chrome do Streamlit — esconde o menu e o botão "Deploy" e deixa a
#    barra superior (``header``) sem destaque: fundo do próprio tema,
#    altura compacta e sem capturar cliques. Ela não é removida da
#    árvore porque é ali que fica o botão de reabrir a barra lateral
#    depois de recolhida. A altura usada (2.875rem) é a mesma que o
#    próprio Streamlit aplica no modo tela cheia; o ``padding-top`` do
#    conteúdo é ajustado para essa medida, evitando que o conteúdo
#    passe por baixo da barra.
# 2. Barra lateral — compacta fontes e espaçamentos para que os
#    controles caibam sem rolagem excessiva, e estiliza a listagem de
#    documentos indexados e os cartões de fontes.
#
# Regras de blindagem contra sobreposição (bloco 2):
# - nenhum container de widget recebe margem negativa, altura fixa ou
#   recorte de overflow; todos ficam com altura automática e visível;
# - o espaçamento entre blocos vem do gap positivo do bloco vertical;
# - títulos têm margem inferior positiva (0.35rem) e entrelinha 1.35,
#   o que os afasta do caption seguinte;
# - captions e parágrafos mantêm overflow visível e entrelinha 1.35;
# - o contêiner de markdown do tema aplica margem negativa; ela é
#   zerada para o texto não escorregar para dentro do widget vizinho;
# - os divisores de seção (``st.divider()``) têm o contêiner interno
#   zerado e o ``<hr>`` com margem curta, para não abrirem vão vazio
#   entre os blocos da barra lateral.
CSS_INTERFACE = f"""
<style>
/* 0. Fundo temático ----------------------------------------------------- */

[data-testid="stAppViewContainer"] {{
    background-color: transparent;
    background-image:
        radial-gradient(
            ellipse 140% 70% at 50% -18%,
            rgba(0, 0, 0, 0.32) 0%,
            rgba(0, 0, 0, 0.12) 45%,
            rgba(0, 0, 0, 0) 78%
        ),
        url("{IMAGEM_FUNDO_TEMATICO}");
    background-size: 100% 100%, 640px 420px;
    background-repeat: no-repeat, repeat;
    background-position: center top, left top;
    background-attachment: scroll, scroll;
}}

/* 1. Chrome do Streamlit ------------------------------------------------ */

/* O botão de publicar (``Deploy``) é o ÚNICO item do chrome que sai da
   barra superior: o fluxo é local e não há deploy a fazer. Todo o resto
   (menu ``⋮``, botão ``Parar`` e ações nativas) permanece visível e
   clicável, e é traduzido por ``_traduzir_interface_streamlit()``. */
.stDeployButton,
[data-testid="stAppDeployButton"] {{
    display: none !important;
}}

/* Trava de visibilidade do chrome. O ``toolbarMode = "auto"`` do
   ``.streamlit/config.toml`` garante que o Streamlit renderize a barra;
   estas regras apenas impedem que qualquer estilo do tema (ou um
   ``data-testid`` reaproveitado por outra versão) recolha o menu
   principal, as ações da barra ou o botão ``Parar``. Nada aqui usa
   ``display: none`` nem ``visibility: hidden``. */
[data-testid="stToolbar"],
[data-testid="stToolbarActions"],
[data-testid="stMainMenu"],
#MainMenu {{
    visibility: visible !important;
    display: flex !important;
    align-items: center;
    opacity: 1 !important;
}}

/* A barra superior permanece na árvore (é ali que ficam o menu ``⋮``, o
   botão ``Parar`` e o botão de reabrir a barra lateral), mas perde altura
   e fica sem destaque: o fundo é transparente, então a arte de fundo
   continua visível atrás dela. A altura acompanha o padding-top do
   conteúdo abaixo. */
header[data-testid="stHeader"] {{
    height: 2.875rem;
    min-height: 2.875rem;
    background: transparent;
    box-shadow: none;
    border-bottom: 0;
    pointer-events: none;
    visibility: visible !important;
}}

/* Só a barra de ferramentas (onde ficam o menu ``⋮`` e o botão ``Parar``)
   continua clicável. */
[data-testid="stToolbar"] {{
    pointer-events: auto;
}}

/* Topo e base do conteúdo principal mais compactos. O topo é igual à
   altura da barra superior para o conteúdo não ficar por baixo dela. */
[data-testid="stMainBlockContainer"],
.block-container {{
    padding-top: 2.875rem !important;
    padding-bottom: 2.5rem !important;
}}

/* Cabeçalho horizontal: título compacto na mesma linha dos badges.
   O container recebe key="cabecalho", que gera a classe abaixo. */
.st-key-cabecalho h4 {{
    font-size: 1.35rem;
    line-height: 1.25;
    margin: 0;
    padding: 0;
}}

.st-key-cabecalho {{
    margin-bottom: 0.15rem;
}}

/* 2. Barra lateral ------------------------------------------------------ */

/* Respiro interno da barra lateral: 0.75rem no topo e na base substituem
   o padding folgado do tema. O ``stSidebarContent`` é o contêiner rolável
   (fica com padding zerado) e o ``stSidebarUserContent`` é quem envolve
   os widgets, por isso o respiro fica só nele — assim ele não é somado
   duas vezes. */
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{
    padding-top: 0.75rem !important;
    padding-bottom: 0.75rem !important;
}}

/* Espaçamento vertical entre os blocos da sidebar: compacto (0.35rem),
   mas ainda positivo, para cada título não encostar no parágrafo
   explicativo seguinte. */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    gap: 0.35rem !important;
}}

/* O tema aplica margem negativa nos contêineres de markdown, o que
   puxava legendas para debaixo dos títulos. Zerar a margem elimina a
   causa da sobreposição sem recorrer a valores negativos. */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{
    margin: 0 !important;
}}

[data-testid="stSidebar"] h1 {{
    font-size: 1.1rem;
    line-height: 1.35 !important;
    margin: 0 0 0.35rem 0 !important;
    padding: 0;
}}

/* Títulos de seção: margem inferior curta (0.2rem) e um fio de margem
   superior (0.1rem) separam o título do caption seguinte sem abrir um
   vão entre as seções. */
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] [data-testid="stHeading"] {{
    font-size: 1.0rem;
    line-height: 1.35 !important;
    margin: 0.1rem 0 0.2rem 0 !important;
    padding: 0;
}}

/* Parágrafos e rótulos na mesma escala dos captions (0.82rem). */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {{
    font-size: 0.82rem;
    line-height: 1.35 !important;
    margin-top: 0.1rem !important;
    margin-bottom: 0.2rem !important;
}}

[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{
    margin-bottom: 0.2rem !important;
}}

/* Captions e parágrafos: overflow visível para a legenda não ser
   recortada e margem superior mínima que a afasta do título. */
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] p {{
    overflow: visible !important;
    line-height: 1.35 !important;
    margin-top: 0.1rem !important;
}}

[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
    font-size: 0.82rem;
}}

/* Containers dos widgets: somente margens positivas, altura automática
   e overflow visível. Nenhum deles usa margem negativa, altura fixa ou
   recorte, que eram as causas das caixas sobrepostas. */
[data-testid="stSidebar"] [data-testid="stSelectbox"],
[data-testid="stSidebar"] [data-testid="stSlider"],
[data-testid="stSidebar"] [data-testid="stFileUploader"],
[data-testid="stSidebar"] [data-testid="stTextArea"],
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    margin: 0 0 0.15rem 0 !important;
    padding: 0 !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
}}

[data-testid="stSidebar"] [data-testid="stTooltipIcon"] {{
    transform: scale(0.85);
}}

/* Divisores de seção: o ``st.divider()`` é um elemento Markdown, e o
   container interno do Streamlit mantém a margem padrão larga em cima e
   embaixo, o que abria um vão vazio entre os blocos da barra lateral.
   Os dois seletores abaixo alcançam o contêiner externo do elemento e o
   contêiner de markdown que envolve o ``<hr>``; ``min-height: 0`` evita
   que a altura mínima do elemento devolva o espaço zerado. */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(hr),
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(hr) {{
    margin-top: 0.15rem !important;
    margin-bottom: 0.15rem !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    min-height: 0 !important;
}}

/* O ``<hr>`` traz margem vertical de 2em do tema; 0.25rem basta para o
   fio não encostar no texto acima nem no título abaixo. A cor de borda é
   um cinza-azulado translúcido que fica visível e harmônico tanto sobre o
   fundo escuro quanto sobre o claro, sem depender do tema ativo. */
[data-testid="stSidebar"] hr {{
    margin: 0.25rem 0 !important;
    border-color: rgba(139, 148, 158, 0.30) !important;
}}

/* Títulos imediatamente após um divisor: sem o respiro superior largo
   do tema, para o cabeçalho da seção não descolar da linha. Fica depois
   das regras de tipografia acima para vencer a margem em cascata. */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 {{
    margin-top: 0.15rem !important;
    padding-top: 0 !important;
}}

/* Toggles e caixas de seleção: cada linha fica rente à anterior, com
   padding vertical mínimo para o clique continuar confortável. */
[data-testid="stSidebar"] [data-testid="stToggle"],
[data-testid="stSidebar"] [data-testid="stCheckbox"] {{
    margin: 0 !important;
    padding: 0.05rem 0 !important;
}}

[data-testid="stSidebar"] [data-testid="stToggle"] label,
[data-testid="stSidebar"] [data-testid="stCheckbox"] label {{
    margin: 0 !important;
    min-height: 1.6rem;
}}

/* Botões da barra lateral: altura compacta (mas acima do mínimo de
   toque) e sem margem própria, para ficarem próximos entre si. As
   regras específicas de cada lista continuam mandando por terem
   seletor mais específico. */
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] {{
    margin: 0 !important;
    min-height: 2.1rem;
    padding-top: 0.15rem !important;
    padding-bottom: 0.15rem !important;
}}

[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    font-size: 0.82rem;
    line-height: 1.35 !important;
    padding: 0.35rem 0 !important;
}}

[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
    padding-top: 0.35rem !important;
}}

/* Documentos indexados: cada arquivo em uma linha com ícone, nome, selo
   de status e botão discreto de exclusão. O bloco é gerado por
   ``_renderizar_documentos_sidebar``; a chave do container de cada item
   gera a classe ``st-key-documento_item_*``. */
[class*="st-key-documento_item_"] {{
    gap: 0.3rem !important;
    margin: 0;
    padding: 0.2rem 0.45rem;
    border: 1px solid rgba(139, 148, 158, 0.3);
    border-radius: 0.5rem;
    background-color: rgba(139, 148, 158, 0.1);
}}

/* O nome do arquivo fica com o espaço livre da linha e corta com
   reticências, em vez de empurrar o selo e o botão para fora. */
[class*="st-key-documento_item_"] > [data-testid="stElementContainer"]:first-child {{
    flex: 1 1 auto;
    min-width: 0;
}}

[class*="st-key-documento_item_"] [data-testid="stMarkdownContainer"] p {{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin: 0 !important;
    font-size: 0.78rem;
    line-height: 1.35;
}}

/* Selo de status nativo (``st.badge``) no tamanho compacto da lista. */
[class*="st-key-documento_item_"] .stMarkdownBadge {{
    flex: none;
    font-size: 0.66rem;
    line-height: 1.2;
    letter-spacing: 0.02em;
    padding: 0.1rem 0.4rem;
}}

/* Botão de exclusão: discreto e sem aumentar a altura da linha. */
[class*="st-key-documento_item_"] [data-testid="stBaseButton-tertiary"] {{
    flex: none;
    padding: 0 0.3rem;
    min-height: 1.4rem;
}}

/* 3. Fontes consultadas (conversa) -------------------------------------- */

/* Cartão de metadados de um artigo do RIGeo: o container recebe uma
   chave ``st-key-cartao_rigeo_*``, que gera a classe abaixo. Os cartões
   das bases internacionais (``cartao_publicacao_*``) usam o mesmo
   acabamento, para o expander de fontes ter um padrão único. */
[class*="st-key-cartao_rigeo_"],
[class*="st-key-cartao_publicacao_"] {{
    padding: 0.75rem 0.9rem;
}}

[class*="st-key-cartao_rigeo_"] [data-testid="stCaptionContainer"],
[class*="st-key-cartao_publicacao_"] [data-testid="stCaptionContainer"] {{
    margin-top: 0.15rem;
}}

/* Os link buttons de cada cartão ficam menores que os do restante da
   página (testid verificado na versão instalada do Streamlit). */
[class*="st-key-cartao_rigeo_"] [data-testid="stLinkButton"],
[class*="st-key-cartao_publicacao_"] [data-testid="stLinkButton"] {{
    font-size: 0.8rem;
}}

/* 4. Histórico de conversas (barra lateral) ----------------------------- */

/* A barra lateral é estreita: quando falta largura, o Streamlit empilha
   as colunas de um bloco horizontal, e a lixeira cai para a linha de
   baixo do título. ``nowrap`` mantém toda linha horizontal da sidebar em
   uma única linha e o alinhamento central iguala as alturas. */
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap !important;
    align-items: center !important;
}}

/* Cada conversa é uma linha com o botão de abrir (coluna de 84%) e o
   botão discreto de exclusão (coluna de 16%). O container recebe a chave
   ``st-key-historico_item_<session_id>``. */
[class*="st-key-historico_item_"] {{
    margin: 0;
}}

[class*="st-key-historico_item_"] [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0.25rem !important;
}}

/* A coluna do título pode encolher; a da lixeira fica com a largura do
   próprio ícone, sem espremer nem empurrar o título para outra linha. */
[class*="st-key-historico_item_"] [data-testid="stHorizontalBlock"] > div {{
    min-width: 0;
}}

[class*="st-key-historico_item_"]
[data-testid="stHorizontalBlock"] > div:last-child {{
    flex: 0 0 auto;
}}

/* Botão que abre a conversa: alinhado à esquerda, largura inteira da
   coluna e texto em uma linha com reticências. Vale para o botão
   secundário (conversa inativa) e para o primário (conversa ativa). */
[class*="st-key-historico_item_"] [data-testid="stBaseButton-secondary"],
[class*="st-key-historico_item_"] [data-testid="stBaseButton-primary"] {{
    justify-content: flex-start;
    font-size: 0.8rem;
    line-height: 1.35;
    padding: 0.25rem 0.5rem;
    text-align: left;
    min-width: 0;
    overflow: hidden;
}}

/* O rótulo do botão nunca quebra: o texto que passar da largura ganha
   reticências em vez de empurrar a lixeira para baixo. */
[class*="st-key-historico_item_"] [data-testid="stBaseButton-secondary"] p,
[class*="st-key-historico_item_"] [data-testid="stBaseButton-primary"] p {{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin: 0 !important;
}}

/* Conversa ativa no momento: mantém a cor de destaque do tema, com
   fundo translúcido e borda, para diferenciá-la do restante da lista sem
   quebrar a paleta escura. */
[class*="st-key-historico_item_"] [data-testid="stBaseButton-secondary"][aria-current="true"],
[class*="st-key-historico_item_"] [data-testid="stBaseButton-secondary"][data-active="true"],
[class*="st-key-historico_item_"] [data-testid="stBaseButton-primary"] {{
    border-color: var(--primary-color);
    background-color: rgba(88, 166, 255, 0.14);
    color: var(--primary-color);
}}

/* Botão de exclusão (``type="tertiary"``): discreto, sem borda e com
   altura de uma linha, para não competir visualmente com o título. */
[class*="st-key-historico_excluir_"] [data-testid="stBaseButton-tertiary"] {{
    padding: 0.2rem 0.3rem;
    min-height: 1.6rem;
    border-color: transparent;
    background-color: transparent;
    white-space: nowrap;
}}

[class*="st-key-historico_excluir_"]
[data-testid="stBaseButton-tertiary"]:hover {{
    border-color: rgba(248, 81, 73, 0.5);
    background-color: rgba(248, 81, 73, 0.14);
}}

/* Caixa rolável da lista de conversas: o Streamlit aplica a chave do
   container como classe, então o limite de altura e a rolagem ficam só
   na seção do histórico, sem estourar a barra lateral. */
.st-key-historico_lista [data-testid="stVerticalBlock"] {{
    gap: 0.25rem !important;
}}

.st-key-historico_lista {{
    max-height: 15rem;
    overflow-y: auto;
    padding-right: 0.15rem;
}}

/* 5. Rodapé fixo da área principal (Novo Chat + campo de mensagem) ------ */

/* O ``st.bottom`` já entrega o conteúdo preso à base da área principal
   como parte do layout do Streamlit — por isso não há ``position:
   fixed`` aqui: um bloco fixo de verdade cobriria as mensagens do chat.
   O que o CSS garante é que o botão compacto e o campo de mensagem
   fiquem na mesma linha, com alturas alinhadas. */
.st-key-rodape_chat {{
    padding: 0.25rem 0 0.35rem 0;
}}

.st-key-rodape_chat [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0.5rem !important;
}}

/* As duas colunas podem encolher; o botão nunca quebra o rótulo. */
.st-key-rodape_chat [data-testid="stHorizontalBlock"] > div {{
    min-width: 0;
}}

.st-key-rodape_chat [data-testid="stBaseButton-secondary"] {{
    min-height: 2.75rem;
    height: 100%;
    white-space: nowrap;
    font-size: 0.85rem;
    padding: 0.35rem 0.5rem;
}}

/* O campo de mensagem ocupa a coluna restante, sem margem que desaline
   a linha do botão. */
.st-key-rodape_chat [data-testid="stChatInput"] {{
    margin: 0 !important;
}}

[data-testid="stBottom"] [data-testid="stBottomBlockContainer"] {{
    padding-bottom: 0.75rem !important;
}}

/* 6. Guia rápido do estado vazio ---------------------------------------- */

/* O cartão recebe key="guia_rapido", que gera a classe abaixo. O realce
   é discreto — fundo azulado translúcido e um fio de destaque à
   esquerda — para integrar o painel ao tema escuro sem competir com o
   campo de mensagem. */
.st-key-guia_rapido {{
    padding: 1rem 1.1rem 0.85rem 1.1rem;
    background-color: rgba(88, 166, 255, 0.055);
    border-left: 3px solid rgba(88, 166, 255, 0.5);
}}

/* Título do painel um pouco menor que o h4 padrão da página. */
.st-key-guia_rapido h4 {{
    font-size: 1.05rem;
    line-height: 1.3;
    margin: 0 0 0.35rem 0;
}}

/* Espaçamento curto entre parágrafos e legendas: os quatro passos cabem
   na primeira tela, sem rolagem. */
.st-key-guia_rapido [data-testid="stMarkdownContainer"] p {{
    margin-bottom: 0.15rem;
}}

.st-key-guia_rapido [data-testid="stCaptionContainer"] {{
    line-height: 1.4;
}}
</style>
"""

# Script injetado na barra superior para traduzir os rótulos nativos do
# Streamlit. Roda dentro de um iframe de altura zero e observa apenas a
# barra superior, o menu principal, o widget de status (barra de execução e
# aviso de arquivo alterado) e os popovers desse menu, sem tocar no conteúdo
# das mensagens do chat nem nas tabelas técnicas.
SCRIPT_TRADUCAO_INTERFACE = """
<script>
(function () {
  "use strict";

  var pai;
  try {
    pai = window.parent;
    if (!pai || !pai.document || !pai.document.body) { return; }
  } catch (erro) {
    return;
  }

  var doc = pai.document;

  var MAPA = {
    "Stop": "Parar",
    "Deploy": "Publicar",
    "System": "Sistema",
    "Light": "Claro",
    "Dark": "Escuro",
    "Rerun": "Recarregar",
    "Auto rerun": "Recarregar automaticamente",
    "Always rerun": "Sempre recarregar",
    "Clear cache": "Limpar cache",
    "Print": "Imprimir",
    "Record screen": "Gravar tela",
    "File change.": "Arquivo alterado.",
    "Source file changed.": "Arquivo-fonte alterado.",
    "Running...": "Executando...",
    "Connecting...": "Conectando...",
    "Please wait...": "Aguarde..."
  };
  var CREDITO_ORIGINAL = "Made with Streamlit";
  var CREDITO_TRADUZIDO = "__CREDITO_APLICATIVO__";

  // Escopo observado pelo MutationObserver: barra superior, barra de
  // ferramentas, menu principal, lista do menu e o widget de status, onde
  // aparecem "File change." / "Always rerun" / "Running..." / "Connecting..."
  // / "Please wait...".
  var SELETOR_RAIZ = [
    '[data-testid="stHeader"]',
    '[data-testid="stToolbar"]',
    '[data-testid="stMainMenu"]',
    '[data-testid="stMainMenuList"]',
    '[data-testid="stStatusWidget"]'
  ].join(",");

  var SELETOR_POPOVER = '[data-baseweb="popover"]';
  var SELETOR_ITEM_MENU = '[data-testid="stMainMenuList"], ' +
    '[data-testid^="stMainMenuItem"], [data-testid="stThemeSwitcher"]';

  var SELETOR_PROTEGIDO = [
    '[data-testid="stChatMessage"]',
    '[data-testid="stChatMessageContent"]',
    '[data-testid="stChatInput"]',
    '[data-testid="stDataFrame"]',
    '[data-testid="stTable"]',
    '[data-testid="stCode"]',
    "table",
    "pre",
    "code"
  ].join(",");

  function traduzir(valor) {
    if (!valor) { return null; }
    var limpo = valor.trim();
    if (!limpo) { return null; }
    if (Object.prototype.hasOwnProperty.call(MAPA, limpo)) {
      return MAPA[limpo];
    }
    if (limpo.indexOf(CREDITO_ORIGINAL) === 0) {
      return CREDITO_TRADUZIDO + limpo.slice(CREDITO_ORIGINAL.length);
    }
    return null;
  }

  function traduzirNoTexto(no) {
    var elemento = no.parentElement;
    if (!elemento || elemento.closest(SELETOR_PROTEGIDO)) { return; }
    var original = no.nodeValue;
    if (!original) { return; }
    var limpo = original.trim();
    if (!limpo || limpo.length > 48) { return; }
    var novo = traduzir(limpo);
    if (!novo) { return; }
    var inicio = original.indexOf(limpo);
    no.nodeValue = original.slice(0, inicio) + novo +
      original.slice(inicio + limpo.length);
  }

  function traduzirAtributos(elemento) {
    if (!elemento || elemento.nodeType !== 1) { return; }
    ["aria-label", "title"].forEach(function (atributo) {
      if (!elemento.hasAttribute(atributo)) { return; }
      var novo = traduzir(elemento.getAttribute(atributo));
      if (novo) { elemento.setAttribute(atributo, novo); }
    });
  }

  function traduzirRaiz(raiz) {
    if (!raiz) { return; }
    traduzirAtributos(raiz);
    var caminhante = doc.createTreeWalker(raiz, 4, null);
    var texto;
    while ((texto = caminhante.nextNode())) {
      traduzirNoTexto(texto);
    }
    var comRotulo = raiz.querySelectorAll("[aria-label], [title]");
    for (var i = 0; i < comRotulo.length; i++) {
      traduzirAtributos(comRotulo[i]);
    }
  }

  function aplicarTudo() {
    var raizes = doc.querySelectorAll(SELETOR_RAIZ);
    for (var i = 0; i < raizes.length; i++) {
      traduzirRaiz(raizes[i]);
    }
    var popovers = doc.querySelectorAll(SELETOR_POPOVER);
    for (var j = 0; j < popovers.length; j++) {
      if (popovers[j].querySelector(SELETOR_ITEM_MENU) &&
          !popovers[j].closest(SELETOR_RAIZ)) {
        traduzirRaiz(popovers[j]);
      }
    }
  }

  function relevante(no) {
    if (!no) { return false; }
    var elemento = no.nodeType === 1 ? no : no.parentElement;
    if (!elemento || !elemento.closest) { return false; }
    return !!(elemento.closest(SELETOR_RAIZ) ||
      elemento.closest(SELETOR_POPOVER));
  }

  var agendado = false;
  function agendar() {
    if (agendado) { return; }
    agendado = true;
    var executar = function () {
      agendado = false;
      aplicarTudo();
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(executar);
    } else {
      window.setTimeout(executar, 60);
    }
  }

  var observador = new MutationObserver(function (mutacoes) {
    for (var i = 0; i < mutacoes.length; i++) {
      var mutacao = mutacoes[i];
      if (relevante(mutacao.target)) { agendar(); return; }
      var adicionados = mutacao.addedNodes;
      for (var j = 0; j < adicionados.length; j++) {
        if (relevante(adicionados[j])) { agendar(); return; }
      }
    }
  });

  try {
    if (pai.__traduzInterfaceStreamlit) {
      pai.__traduzInterfaceStreamlit.disconnect();
    }
    pai.__traduzInterfaceStreamlit = observador;
  } catch (erro) {
    // Sem acesso ao objeto global do pai: segue apenas com a observação.
  }

  observador.observe(doc.body, {
    childList: true,
    subtree: true,
    characterData: true
  });

  aplicarTudo();
  window.setTimeout(aplicarTudo, 300);
  window.setTimeout(aplicarTudo, 1500);
})();
</script>
"""

# O crédito exibido no menu nativo do Streamlit usa as constantes
# oficiais de ``config.py`` (valor final: "NexusGeo IA v0.9.0"); o
# placeholder evita quebrar as chaves das expressões JavaScript dentro
# da string.
SCRIPT_TRADUCAO_INTERFACE = SCRIPT_TRADUCAO_INTERFACE.replace(
    "__CREDITO_APLICATIVO__",
    f"{APP_NAME} v{APP_VERSION}",
)


def _traduzir_interface_streamlit():
    """Traduz a barra superior, o status e o menu do Streamlit.

    Injeta um iframe de altura zero com um ``MutationObserver`` leve que
    atua somente na barra superior (``stHeader``/``stToolbar``/
    ``stMainMenu``/``stMainMenuList``), no widget de status
    (``stStatusWidget``) e nos popovers do menu principal. Os textos
    nativos tratados são "Stop", "Deploy", "System", "Light", "Dark",
    "Rerun", "Auto rerun", "Always rerun", "Clear cache", "Print",
    "Record screen", "File change.", "Source file changed.",
    "Running...", "Connecting...", "Please wait..." e o crédito
    "Made with Streamlit". O conteúdo do chat e as tabelas técnicas ficam
    fora do escopo do script.

    Só é chamada no idioma Português do Brasil: em inglês os rótulos
    nativos do Streamlit já estão no idioma correto ("Stop", "Rerun",
    "File change.", "System", "Light", "Dark"...), e traduzi-los de volta
    seria um efeito colateral indesejado.
    """

    components.html(SCRIPT_TRADUCAO_INTERFACE, height=0)


# Idioma da interface: "pt" (Português do Brasil, padrão) ou "en"
# (Inglês). A troca é feita pelos botões de bandeira no topo da barra
# lateral e sobrevive a todos os reruns da sessão.
st.session_state.setdefault("idioma", IDIOMA_PADRAO)

st.set_page_config(
    page_title=APP_NAME,
    page_icon="⛏️",
    layout="wide"
)

st.html(CSS_INTERFACE)

# A tradução DOM do chrome nativo do Streamlit é aplicada apenas em
# português; em inglês a interface nativa já usa os rótulos em inglês.
if st.session_state.get("idioma") == "pt":
    _traduzir_interface_streamlit()

# ---------------------------------------------------------------------------
# Estado da sessão e helpers de apresentação
# ---------------------------------------------------------------------------

# Estado inicial da aplicação.
#
# ``session_id`` identifica a conversa em andamento: é o nome do arquivo
# em ``data/historico`` e o prefixo das chaves dos widgets de cada
# mensagem. ``criado_em`` guarda a data de criação da conversa para que o
# primeiro autosave não a reescreva, e ``conversa_ativa_salva`` registra
# se a sessão atual já tem arquivo no disco (pastilha do histórico).
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

st.session_state.setdefault("session_id", novo_session_id())
st.session_state.setdefault("criado_em", agora_iso())
st.session_state.setdefault("conversa_ativa_salva", False)

# Aviso pendente das ações do histórico (salvar, abrir, excluir), exibido
# uma única vez no bloco de histórico da barra lateral.
st.session_state.setdefault("historico_aviso", None)

# Confirmação em duas etapas do histórico ("Apagar Todo o Histórico"): a
# primeira execução só liga esta chave; a exclusão em si acontece no
# clique seguinte. Fica no estado da sessão para sobreviver ao rerun.
st.session_state.setdefault("confirmar_apagar_tudo", False)

# Aviso pendente das ações sobre os documentos locais (excluir um arquivo
# ou limpar a base), exibido uma única vez na listagem da barra lateral.
st.session_state.setdefault("documentos_aviso", None)

# Contador auxiliar da conversa: posição da última mensagem montada.
# As chaves dos widgets das mensagens são calculadas pela posição na
# lista ``mensagens`` (ver ``_chave_widget``), não por este contador.
st.session_state.setdefault("sequencia_resposta", 0)

# Texto base do system prompt: carregado do arquivo para iniciar a caixa
# de edição e mantido no estado da sessão, para preservar alterações que
# ainda não foram gravadas no disco.
try:
    prompt_base_padrao = carregar_prompt_base()
    erro_prompt_base = None
except PromptBaseAusenteError as erro:
    prompt_base_padrao = ""
    erro_prompt_base = str(erro)

st.session_state.setdefault(
    "prompt_sistema_editado",
    prompt_base_padrao
)

# Modo de análise ativo. Quando o arquivo salvo já termina com o bloco
# de um perfil, o seletor começa nele, para o prompt ativo e o modo
# exibido no cabeçalho continuarem coerentes entre sessões.
if "perfil_analitico" not in st.session_state:
    st.session_state["perfil_analitico"] = (
        detectar_perfil(prompt_base_padrao) or PERFIL_PADRAO
    )

# Compatibilidade com a versão anterior da barra lateral, que guardava os
# mesmos conectores em ``consultar_sgb``, ``consultar_ana``,
# ``consultar_openalex`` e ``consultar_usgs``. Uma sessão antiga mantém a
# escolha em vez de voltar ao valor padrão.
for _chave_nova, _chave_antiga in (
    ("rigeo_enabled", "consultar_sgb"),
    ("ana_enabled", "consultar_ana"),
    ("openalex_enabled", "consultar_openalex"),
):
    if (
        _chave_nova not in st.session_state
        and _chave_antiga in st.session_state
    ):
        st.session_state[_chave_nova] = st.session_state[_chave_antiga]
        del st.session_state[_chave_antiga]

# O antigo toggle exclusivo do USGS ScienceBase foi absorvido pelo grupo
# internacional. Sessões que o tinham ligado passam a abrir o grupo com
# a região dos EUA já selecionada; as chaves antigas são descartadas.
_usgs_legado = bool(
    st.session_state.get("usgs_enabled")
    or st.session_state.get("consultar_usgs")
)

if _usgs_legado:
    st.session_state["intl_geo_enabled"] = True
    _regioes_migradas = list(
        st.session_state.get("intl_geo_regioes") or []
    )

    if (
        OPCOES_REGIOES_INTERNACIONAIS[2] not in _regioes_migradas
        and REGIAO_TODAS not in _regioes_migradas
    ):
        _regioes_migradas.append(OPCOES_REGIOES_INTERNACIONAIS[2])

    st.session_state["intl_geo_regioes_padrao"] = (
        _regioes_migradas or [REGIAO_TODAS]
    )

st.session_state.pop("usgs_enabled", None)
st.session_state.pop("consultar_usgs", None)


def _salvar_prompt_padrao():
    """Grava no arquivo o texto atual da caixa de edição."""

    try:
        salvar_prompt_base(
            st.session_state.get("prompt_sistema_editado", "")
        )
    except OSError as erro:
        st.session_state["prompt_sistema_aviso"] = (
            "erro",
            tf("aviso_prompt_erro", erro=erro)
        )
    else:
        st.session_state["prompt_sistema_aviso"] = (
            "sucesso",
            t("aviso_prompt_salvo")
        )


def _restaurar_prompt_original():
    """Recarrega do arquivo o texto, reaplicando o perfil ativo.

    O arquivo guarda o texto base; quando um modo de análise está
    selecionado, o bloco dele volta a ser acrescentado ao final.
    """

    perfil = perfil_do_rotulo(
        st.session_state.get("perfil_analitico", PERFIL_PADRAO)
    ) or PERFIL_PADRAO

    try:
        texto_base = remover_blocos_de_perfil(carregar_prompt_base())
    except PromptBaseAusenteError as erro:
        st.session_state["prompt_sistema_aviso"] = ("erro", str(erro))
    else:
        st.session_state["prompt_sistema_editado"] = (
            texto_base
            if perfil == PERFIL_PERSONALIZADO
            else montar_prompt_do_perfil(perfil, texto_base)
        )
        st.session_state["prompt_sistema_aviso"] = (
            "sucesso",
            t("aviso_prompt_restaurado")
        )


def _aplicar_perfil_analitico():
    """Preenche o editor com o texto base + bloco do perfil escolhido.

    É o callback do seletor "Modo de análise": roda antes de o script
    ser redesenhado, então o ``st.text_area`` já aparece com o texto
    novo. O bloco do perfil anterior é retirado antes de acrescentar o
    novo, para não duplicar instruções.

    No modo ``Personalizado`` o texto atual é mantido como ponto de
    partida da instrução livre e o editor é aberto.
    """

    perfil = perfil_do_rotulo(
        st.session_state.get("perfil_analitico", PERFIL_PADRAO)
    ) or PERFIL_PADRAO

    texto_atual = st.session_state.get("prompt_sistema_editado", "")

    if perfil == PERFIL_PERSONALIZADO:
        st.session_state["editor_prompt_aberto"] = True
        return

    st.session_state["prompt_sistema_editado"] = montar_prompt_do_perfil(
        perfil,
        remover_blocos_de_perfil(texto_atual),
    )


def _legenda_fonte(fonte, roteamento=None):
    """Monta a legenda de fonte já usada pelo chat.

    No modo "Automático", acrescenta a classe decidida pelo roteador
    (``LOCAL_ONLY``, ``RIGEO_ONLY`` ou ``HIBRIDO``) à mesma linha de
    legenda existente.
    """

    legenda = tf("fonte_legenda", fonte=fonte)

    if (
        (roteamento or {}).get("modo") == "automatico"
        and roteamento.get("intencao")
    ):
        legenda += tf(
            "roteamento_legenda",
            intencao=roteamento["intencao"],
        )

    return legenda


def _cor_intencao(intencao):
    """Cor do badge de roteamento para a intenção informada."""

    return CORES_INTENCAO.get(intencao, "gray")


def _escapar_markdown(texto):
    """Neutraliza caracteres de marcação em títulos vindos de fontes.

    Os metadados do RIGeo são conteúdo externo e podem conter ``*``,
    ``_``, colchetes ou crases, que o Markdown interpretaria como
    formatação ou link.
    """

    for caractere in ("\\", "*", "_", "[", "]", "`", "#", ">"):
        texto = texto.replace(caractere, f"\\{caractere}")

    return texto


def _texto_curto(valor):
    """Normaliza um valor de metadado em uma linha única de texto."""

    return " ".join(str(valor or "").split())


def _url_web(valor):
    """Devolve o endereço normalizado apenas se for ``http`` ou ``https``.

    Metadados do RIGeo vêm de fonte externa; qualquer outro esquema
    (ou texto vazio) devolve ``""`` e o botão de link correspondente
    simplesmente não é exibido.
    """

    url = _texto_curto(valor)

    if url.lower().startswith(("http://", "https://")):
        return url

    return ""


def _exibir_aviso_prompt():
    """Mostra e descarta o aviso pendente do editor de system prompt."""

    aviso_prompt = st.session_state.pop("prompt_sistema_aviso", None)

    if not aviso_prompt:
        return

    tipo_aviso, mensagem_aviso = aviso_prompt

    if tipo_aviso == "sucesso":
        st.success(mensagem_aviso)
    else:
        st.error(mensagem_aviso)


# ---------------------------------------------------------------------------
# Histórico de conversas (barra lateral)
# ---------------------------------------------------------------------------

def _chave_widget(mensagem):
    """Prefixo das chaves dos widgets gerados pela mensagem.

    Junta o ``session_id`` à posição da mensagem na conversa: a primeira
    resposta fica com ``<session_id>_1`` (contando da primeira pergunta),
    a segunda com ``<session_id>_3`` e assim por diante. Trocar de
    conversa ou criar uma nova muda o prefixo, então expanders, cartões e
    link buttons nunca repetem chave (``StreamlitDuplicateElementKey``)
    ao alternar entre sessões salvas.
    """

    return (
        f"{st.session_state.session_id}_"
        f"{mensagem.get('chave', 0)}"
    )


def _chave_resposta_atual():
    """Chave única para a resposta em exibição logo após a consulta.

    Também funciona como índice provisório dessa mensagem (contando da
    primeira pergunta), então os widgets da exibição imediata e os do
    redesenho seguinte usam a mesma chave — o estado dos expanders não é
    recriado à toa.
    """

    total = len(st.session_state.mensagens)

    return (
        f"{st.session_state.session_id}_"
        f"{max(total - 1, 0)}"
    )


def _salvar_conversa_atual():
    """Grava a conversa da sessão em ``data/historico``.

    Chamada silenciosa (autosave e "Novo Chat"): a conversa só é gravada
    quando já existe mensagem, e o resultado não gera aviso de sucesso —
    só falhas de disco viram aviso, para que a perda não passe
    despercebida.
    """

    mensagens = st.session_state.get("mensagens") or []

    if not mensagens:
        return

    try:
        salvo = salvar_conversa(
            st.session_state.session_id,
            st.session_state.get("titulo_conversa"),
            mensagens
        )
    except HistoricoError as erro:
        st.session_state["historico_aviso"] = ("erro", str(erro))
        return

    if salvo:
        st.session_state["conversa_ativa_salva"] = True


def _nova_mensagem(papel, conteudo, **metadados):
    """Monta a mensagem com a chave de widgets e a data de criação.

    A chave é a posição da mensagem na conversa (contando da primeira
    pergunta), calculada depois de acrescentá-la à lista.
    """

    st.session_state.sequencia_resposta = len(st.session_state.mensagens)

    mensagem = {
        "role": papel,
        "content": conteudo,
        "chave": st.session_state.sequencia_resposta,
        "criado_em": agora_iso(),
    }
    mensagem.update(metadados)

    return mensagem


def _abrir_conversa(session_id):
    """Carrega uma conversa salva no ``st.session_state``.

    É usada como ``on_click`` do item do histórico: o callback roda antes
    do redesenho da página, então a conversa já aparece na primeira
    execução, sem precisar de ``st.rerun``.
    """

    conversa = carregar_conversa(session_id)

    if conversa is None:
        st.session_state["historico_aviso"] = (
            "erro",
            t("aviso_abrir_erro")
        )
        return

    # A chave de widgets de cada mensagem é a posição dela na conversa;
    # ela é recalculada aqui para que um arquivo de outra versão (ou
    # editado à mão) não quebre as chaves.
    mensagens = []

    for indice, mensagem in enumerate(conversa["mensagens"]):
        mensagem = dict(mensagem)
        mensagem["chave"] = indice
        mensagens.append(mensagem)

    st.session_state.mensagens = mensagens
    st.session_state.session_id = conversa["id"]
    st.session_state.titulo_conversa = conversa["titulo"]
    st.session_state.criado_em = conversa["criado_em"]
    st.session_state.conversa_ativa_salva = True
    st.session_state.sequencia_resposta = len(mensagens)


def _nova_conversa():
    """Inicia uma conversa em branco, mantendo os documentos indexados.

    A conversa anterior é gravada antes; o ``session_id``, o título e a
    data de criação passam a ser novos, e a lista de mensagens fica
    vazia — a tela inicial (Empty State) volta a aparecer, sem tocar em
    ``data/docs``. As confirmações pendentes (exclusão total do
    histórico) são desarmadas, para um clique no rodapé não apagar nada
    por engano depois de trocar de conversa.
    """

    _salvar_conversa_atual()

    st.session_state.session_id = novo_session_id()
    st.session_state.criado_em = agora_iso()
    st.session_state.titulo_conversa = ""
    st.session_state.mensagens = []
    st.session_state.conversa_ativa_salva = False
    st.session_state.sequencia_resposta = 0
    st.session_state["confirmar_apagar_tudo"] = False


def _excluir_conversa(session_id):
    """Apaga uma conversa do histórico.

    Se ela for a conversa aberta no momento, a tela volta ao Empty State
    com um novo ``session_id``; caso contrário, a conversa atual
    permanece intacta.
    """

    try:
        excluida = excluir_conversa(session_id)
    except HistoricoError as erro:
        st.session_state["historico_aviso"] = ("erro", str(erro))
        return

    if session_id == st.session_state.session_id:
        st.session_state.session_id = novo_session_id()
        st.session_state.criado_em = agora_iso()
        st.session_state.titulo_conversa = ""
        st.session_state.mensagens = []
        st.session_state.conversa_ativa_salva = False
        st.session_state.sequencia_resposta = 0

    if excluida:
        st.session_state["historico_aviso"] = (
            "sucesso",
            t("aviso_conversa_excluida")
        )


def _apagar_todo_historico():
    """Apaga todas as conversas salvas e reinicia a conversa da sessão.

    Chamada somente depois da confirmação em duas etapas do rodapé. A
    exclusão em massa atinge apenas ``data/historico``: os documentos
    indexados em ``data/docs`` continuam intactos.

    A tela volta ao Empty State com um ``session_id`` novo, porque o
    anterior era o nome de um arquivo que acabou de ser apagado — sem a
    troca, o próximo autosave recriaria a conversa recém-excluída.
    """

    try:
        apagadas = excluir_todas_conversas()
    except HistoricoError as erro:
        st.session_state["historico_aviso"] = ("erro", str(erro))
        st.session_state["confirmar_apagar_tudo"] = False
        return

    st.session_state.mensagens = []
    st.session_state.titulo_conversa = ""
    st.session_state.conversa_ativa_salva = False
    st.session_state.sequencia_resposta = 0
    st.session_state.session_id = novo_session_id()
    st.session_state.criado_em = agora_iso()
    st.session_state["confirmar_apagar_tudo"] = False

    if apagadas:
        st.session_state["historico_aviso"] = (
            "sucesso",
            tf("aviso_historico_apagado", n=apagadas)
        )
    else:
        st.session_state["historico_aviso"] = (
            "sucesso",
            t("aviso_sem_conversas")
        )


def _cancelar_apagar_tudo():
    """Desarma a confirmação de exclusão total sem apagar nada."""

    st.session_state["confirmar_apagar_tudo"] = False


def _rotulo_conversa(conversa):
    """Rótulo do item do histórico: ícone (ou data) e título curto."""

    titulo = _texto_curto(conversa.get("titulo")) or t("nova_conversa")

    if st.session_state.session_id == conversa["id"]:
        return f":material/chat: {titulo}"

    return f":material/forum: {titulo}"


def _renderizar_historico():
    """Lista as conversas salvas na barra lateral, da mais nova à mais antiga.

    Cada linha tem o botão que abre a conversa e um botão discreto de
    exclusão. A conversa aberta no momento aparece em destaque (botão
    primário, ícone de bate-papo preenchido e desabilitado para não
    recarregar a conversa que já está na tela).

    Título e lixeira ficam em ``st.columns`` com 84%/16% da largura e
    alinhamento vertical central, e o CSS da seção 4 mantém as duas
    colunas na mesma linha (``flex-wrap: nowrap``) mesmo na barra
    lateral estreita. Devolve a quantidade de conversas salvas, usada
    pelo botão "Apagar Todo o Histórico" logo abaixo da lista.
    """

    conversas = listar_conversas()

    st.subheader(t("secao_historico"))

    if not conversas:
        st.caption(t("historico_vazio"))
        return 0

    st.caption(tf("historico_contagem", n=len(conversas)))

    with st.container(key="historico_lista"):
        for conversa in conversas:
            session_id = conversa["id"]
            ativa = st.session_state.session_id == session_id

            # A chave do container gera a classe ``st-key-historico_item_*``
            # usada pelas regras de CSS da lista.
            with st.container(key=f"historico_item_{session_id}"):
                col_titulo, col_del = st.columns(
                    [0.84, 0.16],
                    gap="small",
                    vertical_alignment="center"
                )

                with col_titulo:
                    st.button(
                        _rotulo_conversa(conversa),
                        key=f"abrir_{session_id}",
                        width="stretch",
                        type="primary" if ativa else "secondary",
                        disabled=ativa,
                        help=(
                            t("historico_aberta")
                            if ativa
                            else tf(
                                "historico_abrir",
                                data=_texto_curto(
                                    conversa["atualizado_em"]
                                ),
                            )
                        ),
                        on_click=_abrir_conversa,
                        args=(session_id,)
                    )

                with col_del:
                    st.button(
                        "",
                        key=f"historico_excluir_{session_id}",
                        icon=":material/delete:",
                        type="tertiary",
                        help=tf(
                            "historico_excluir",
                            titulo=conversa["titulo"],
                        ),
                        on_click=_excluir_conversa,
                        args=(session_id,)
                    )

        # A conversa aberta pode ainda não ter arquivo (nenhuma resposta
        # concluída): ela entra na lista em memória para não sumir de
        # vista enquanto o usuário consulta.
        if (
            not st.session_state.conversa_ativa_salva
            and st.session_state.mensagens
        ):
            st.caption(t("historico_nao_salva"))

    return len(conversas)


def _gerar_titulo_conversa():
    """Define o título da conversa aberta a partir da primeira pergunta.

    Roda uma única vez por conversa: assim que a primeira pergunta é
    enviada, o título aparece na barra lateral e passa a ser gravado em
    todos os autosaves. Títulos já existentes (de conversas carregadas)
    são preservados.
    """

    if st.session_state.get("titulo_conversa"):
        return

    for mensagem in st.session_state.mensagens:
        if mensagem.get("role") == "user":
            st.session_state.titulo_conversa = gerar_titulo(
                mensagem.get("content")
            )
            return


def _exibir_aviso_historico():
    """Mostra e descarta o aviso pendente das ações do histórico."""

    aviso = st.session_state.pop("historico_aviso", None)

    if not aviso:
        return

    tipo_aviso, mensagem_aviso = aviso

    if tipo_aviso == "sucesso":
        st.success(mensagem_aviso, icon=":material/check_circle:")
    else:
        st.error(mensagem_aviso, icon=":material/error:")


@st.cache_resource(show_spinner=t("spinner_ollama"))
def _iniciar_ollama():
    """Sobe o Ollama uma única vez, quando o app é carregado.

    O ``st.cache_resource`` mantém o resultado entre reruns e sessões,
    então a verificação (e o eventual ``ollama serve``) acontece só no
    primeiro carregamento do servidor. O retorno é o booleano devolvido
    por ``garantir_ollama_ativo`` e não é usado diretamente: o badge
    abaixo continua consultando o estado real do serviço.

    O texto do spinner é resolvido por ``t("spinner_ollama")`` no
    decorador, que é reavaliado a cada execução do script — depois do
    ``setdefault`` do idioma —, então ele já sai no idioma ativo.
    """

    return garantir_ollama_ativo()


# Executado no topo do script, antes de qualquer elemento da página, para
# que o serviço esteja disponível quando o badge e a lista de modelos o
# consultarem.
ollama_iniciado = _iniciar_ollama()


@st.cache_data(ttl=10, show_spinner=False)
def _verificar_conexao_ollama(host):
    """Consulta ``/api/version`` e devolve (online, detalhe).

    O resultado fica em cache por poucos segundos para que o badge do
    cabeçalho possa se atualizar sozinho sem gerar uma requisição a cada
    interação da página. Qualquer falha de rede vira ``online = False``,
    sem interromper a aplicação.
    """

    url = f"{host.rstrip('/')}/api/version"

    try:
        resposta = requests.get(
            url,
            timeout=TEMPO_LIMITE_STATUS_OLLAMA
        )
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError) as erro:
        return False, f"Sem resposta de {url}: {type(erro).__name__}."

    versao = dados.get("version") if isinstance(dados, dict) else None

    return True, f"{url} respondeu (versão {versao or 'não informada'})."


@st.fragment(run_every=INTERVALO_STATUS_OLLAMA)
def _badge_status_ollama():
    """Badge com o estado atual da conexão com o Ollama local.

    O fragmento é reexecutado no intervalo configurado, então o badge
    reflete o estado do servidor sem exigir recarregar a página.
    """

    online, detalhe = _verificar_conexao_ollama(OLLAMA_HOST)

    if online:
        st.badge(
            tf("ollama_online", host=HOST_OLLAMA_EXIBICAO),
            icon=":material/check_circle:",
            color="green",
            help=detalhe
        )
    else:
        st.badge(
            tf("ollama_offline", host=HOST_OLLAMA_EXIBICAO),
            icon=":material/error:",
            color="red",
            help=detalhe
        )


def _renderizar_guia_rapido():
    """Guia rápido de uso exibido no estado vazio da conversa.

    O painel é puramente informativo: não cria chave de widget nem guarda
    estado, então não sobra nada a limpar além do placeholder que o
    contém. Ele desaparece assim que a primeira pergunta é enviada.
    """

    with st.container(border=True, key="guia_rapido"):
        st.markdown(t("guia_titulo"))
        st.markdown(t("guia_intro"))

        # Grade 2x2: os passos ímpares vão para a coluna da esquerda e os
        # pares para a da direita, formando duas linhas. Cada passo traz
        # as chaves de i18n do título e do texto.
        coluna_esquerda, coluna_direita = st.columns(2, gap="medium")

        for indice, (chave_titulo, chave_texto) in enumerate(
            GUIA_RAPIDO_PASSOS
        ):
            coluna = coluna_esquerda if indice % 2 == 0 else coluna_direita

            with coluna:
                st.markdown(f"**{t(chave_titulo)}**")
                st.caption(t(chave_texto))

        # Dicas de combinação de fontes por tipo de consulta. O bloco
        # usa as mesmas duas colunas para manter o painel compacto e
        # orientar o usuário sobre quais toggles ligar em cada cenário.
        st.space("small")
        st.markdown(f"**{t('guia_combinacao_titulo')}**")
        st.caption(t("guia_combinacao_intro"))

        coluna_esquerda, coluna_direita = st.columns(2, gap="medium")

        for indice, (chave_titulo, chave_texto) in enumerate(
            GUIA_COMBINACAO_FONTES
        ):
            coluna = coluna_esquerda if indice % 2 == 0 else coluna_direita

            with coluna:
                st.markdown(f"**{t(chave_titulo)}**")
                st.caption(t(chave_texto))

        st.space("small")
        st.caption(f"💡 {t('guia_dica')}")


@st.cache_data(show_spinner=False, ttl="30m", max_entries=200)
def _avaliacao_cacheada(caminho, mtime_ns, tamanho):
    """Avaliação do documento em cache, por assinatura do arquivo.

    A conversão de um PDF pode custar segundos (OCR por página). Como a
    barra lateral é reconstruída a cada rerun, o resultado fica em cache
    enquanto o arquivo não muda — a chave inclui ``mtime`` e tamanho.
    """

    return avaliar_arquivo(Path(caminho))


def _avaliar_documento(caminho):
    """Avalia um documento de ``data/docs`` com cache e sem derrubar a UI."""

    try:
        informacao = caminho.stat()
    except OSError:
        return {
            "valido": False,
            "motivo": "falha_leitura",
            "caracteres_uteis": 0,
            "paginas": 0,
            "paginas_com_texto": 0,
            "previa": "",
        }

    try:
        return _avaliacao_cacheada(
            str(caminho),
            informacao.st_mtime_ns,
            informacao.st_size,
        )
    except DocumentoInvalidoError as erro:
        return {
            "valido": False,
            "motivo": "falha_leitura",
            "mensagem": str(erro),
            "caracteres_uteis": 0,
            "paginas": 0,
            "paginas_com_texto": 0,
            "previa": "",
        }


def _atualizar_indice_documentos():
    """Descarta o índice em memória depois de mudar ``data/docs``.

    ``limpar_cache`` esvazia os trechos já divididos e as consultas em
    cache do ``services.rag_service``: a próxima pergunta relê
    ``data/docs`` do zero, sem depender de reiniciar o app. O
    ``_avaliacao_cacheada`` também é limpo para que a barra lateral não
    reaproveite a avaliação de um arquivo que saiu do disco.
    """

    limpar_cache()
    _avaliacao_cacheada.clear()


def _excluir_documento(caminho):
    """Remove um documento de ``data/docs`` e o cache do seu Markdown.

    Roda como callback do botão ``:material/delete:`` de cada linha da
    listagem. O Streamlit refaz o script em seguida, então a lista, a
    contagem de ``Documentos indexados`` e o índice vetorial já
    aparecem atualizados sem nenhuma ação extra do usuário.
    """

    caminho = Path(caminho)

    # O ``.md``/``.json`` é apagado antes do original: ``remover_cache``
    # resolve o caminho do cache a partir do arquivo de origem.
    try:
        document_parser.remover_cache(caminho)
        caminho.unlink(missing_ok=True)
    except OSError as erro:
        st.session_state["documentos_aviso"] = (
            "erro",
            tf(
                "aviso_excluir_documento_erro",
                nome=caminho.name,
                erro=erro,
            )
        )
        return

    _atualizar_indice_documentos()

    st.session_state["documentos_aviso"] = (
        "sucesso",
        tf("aviso_documento_excluido", nome=caminho.name)
    )


def _limpar_base_documentos():
    """Remove todos os documentos locais e os caches correspondentes.

    Os arquivos são apagados um a um para que uma falha de permissão em
    um deles não impeça a remoção dos demais. No fim, o índice em
    memória é recarregado e o resumo da operação fica em
    ``documentos_aviso``, exibido no próximo rerun.
    """

    documentos = listar_documentos()
    removidos = 0
    falhas = []

    for caminho in documentos:
        try:
            document_parser.remover_cache(caminho)
            caminho.unlink(missing_ok=True)
        except OSError:
            falhas.append(caminho.name)
        else:
            removidos += 1

    _atualizar_indice_documentos()

    if falhas:
        st.session_state["documentos_aviso"] = (
            "erro",
            tf("aviso_limpar_falhas", falhas=", ".join(falhas))
        )
        return

    st.session_state["documentos_aviso"] = (
        "sucesso",
        tf("aviso_limpeza_sucesso", n=removidos)
    )


def _exibir_aviso_documentos():
    """Mostra e descarta o aviso pendente das ações sobre documentos."""

    aviso = st.session_state.pop("documentos_aviso", None)

    if not aviso:
        return

    tipo_aviso, mensagem_aviso = aviso

    if tipo_aviso == "sucesso":
        st.success(mensagem_aviso, icon=":material/check_circle:")
    else:
        st.error(mensagem_aviso, icon=":material/error:")


def _renderizar_documentos_sidebar(documentos, avaliacoes=None):
    """Lista os arquivos com ícone, selo de status e exclusão.

    O selo reflete o resultado real da extração, e não a mera existência
    do arquivo em ``data/docs``:

    - ``Indexado`` (verde): há texto selecionável suficiente;
    - ``Sem texto`` (vermelho): o arquivo não tem texto útil (PDF
      escaneado, por exemplo) e **não** entra na busca.

    Arquivos sem texto aparecem listados porque estão no disco, mas o
    usuário precisa saber que não serão usados na resposta — e pode
    excluí-los pelo botão discreto de cada linha.
    """

    avaliacoes = avaliacoes or {}

    with st.container(key="documentos_lista"):
        for indice, documento in enumerate(documentos):
            avaliacao = (
                avaliacoes.get(documento) or _avaliar_documento(documento)
            )

            if avaliacao.get("valido"):
                paginas_ocr = avaliacao.get("paginas_ocr") or 0
                paginas = avaliacao.get("paginas") or 0

                if paginas_ocr:
                    selo = t("selo_indexado_ocr")
                    titulo = tf(
                        "ajuda_doc_ocr",
                        ocr=paginas_ocr,
                        total=paginas or paginas_ocr,
                    )
                else:
                    selo = t("selo_indexado")
                    titulo = t("ajuda_doc_nativo")

                cor = "green"
            else:
                selo = t("selo_sem_texto")
                cor = "red"
                titulo = avaliacao.get("mensagem") or (
                    mensagem_arquivo_sem_texto(
                        documento.name,
                        avaliacao
                    ) if avaliacao.get("motivo") in {
                        "sem_texto_selecionavel",
                        "vazio",
                    } else t("ajuda_doc_sem_texto")
                )

            with st.container(
                key=f"documento_item_{indice}",
                horizontal=True,
                vertical_alignment="center",
                gap="small"
            ):
                # O nome vem de um arquivo do disco: o escape evita que
                # ``*``, ``_`` ou colchetes no nome virem formatação.
                st.markdown(
                    f":material/description: "
                    f"{_escapar_markdown(documento.name)}",
                    width="stretch",
                    help=f"{documento.name} · {titulo}"
                )

                st.badge(selo, color=cor)

                st.button(
                    "",
                    key=f"documento_excluir_{indice}",
                    icon=":material/delete:",
                    type="tertiary",
                    help=tf(
                        "ajuda_excluir_documento",
                        nome=documento.name,
                    ),
                    on_click=_excluir_documento,
                    args=(documento,)
                )


def _celula_tabela_ana(valor):
    """Prepara um valor da ANA para uma célula Markdown."""

    texto = _escapar_markdown(_texto_curto(valor)).replace("|", "\\|")

    return texto or "—"


def _tabela_estacoes_ana(estacoes):
    """Tabela compacta das estações da ANA para o bloco de status."""

    linhas = [
        "| Código | Estação | Tipo | Rio | Município/UF | Coordenadas |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for estacao in estacoes:
        latitude = _celula_tabela_ana(estacao.get("latitude"))
        longitude = _celula_tabela_ana(estacao.get("longitude"))
        coordenadas = (
            f"{latitude}, {longitude}"
            if latitude != "—" and longitude != "—"
            else "—"
        )

        linhas.append(
            "| {codigo} | {nome} | {tipo} | {rio} | {municipio}/{uf} | "
            "{coordenadas} |".format(
                codigo=_celula_tabela_ana(estacao.get("codigo")),
                nome=_celula_tabela_ana(estacao.get("nome")),
                tipo=_celula_tabela_ana(estacao.get("tipo")),
                rio=_celula_tabela_ana(estacao.get("rio")),
                municipio=_celula_tabela_ana(estacao.get("municipio")),
                uf=_celula_tabela_ana(estacao.get("uf")),
                coordenadas=coordenadas,
            )
        )

    return "\n".join(linhas)


def _renderizar_cartao_estacao_ana(estacao, chave):
    """Cartão de uma estação da ANA no expander de fontes."""

    titulo = _escapar_markdown(
        _texto_curto(estacao.get("titulo"))
        or _texto_curto(estacao.get("nome"))
        or "Estação sem nome"
    )
    tipo = _texto_curto(estacao.get("tipo")) or "Tipo não informado"
    rio = _texto_curto(estacao.get("rio")) or "Rio não informado"
    municipio = _texto_curto(estacao.get("municipio"))
    uf = _texto_curto(estacao.get("uf"))
    status = _texto_curto(estacao.get("status")) or _texto_curto(
        estacao.get("ano")
    )
    latitude = _texto_curto(estacao.get("latitude"))
    longitude = _texto_curto(estacao.get("longitude"))
    coordenadas = (
        f"{latitude}, {longitude}"
        if latitude and longitude
        else "não informadas"
    )
    url_series = _url_web(estacao.get("link"))

    with st.container(border=True, key=f"cartao_ana_{chave}"):
        st.markdown(f"**{titulo}**")

        local = "/".join(
            parte for parte in (municipio, uf) if parte
        ) or "Município não informado"

        st.caption(f"{tipo} · {rio} · {local}")

        st.caption(
            f"Coord: {coordenadas}"
            + (f" · {status}" if status else "")
        )

        if url_series:
            st.link_button(
                t("link_series_historicas"),
                url_series,
                key=f"ana_series_{chave}"
            )


def _renderizar_cartao_rigeo(artigo, chave):
    """Cartão de metadados de um artigo do RIGeo."""

    titulo = _escapar_markdown(
        _texto_curto(artigo.get("titulo")) or "Título não informado"
    )
    # O schema padrão publica ``autores`` como texto; conversas antigas
    # gravadas antes da padronização ainda podem trazer uma lista.
    autores_brutos = artigo.get("autores") or []

    if isinstance(autores_brutos, str):
        autores_brutos = [autores_brutos]

    autores = [
        _escapar_markdown(_texto_curto(autor))
        for autor in autores_brutos
        if _texto_curto(autor)
    ]
    ano = _texto_curto(artigo.get("ano"))
    link = _texto_curto(artigo.get("link"))
    link_pdf = _texto_curto(artigo.get("link_pdf"))

    # Endereços vindos de fonte externa: só ``http``/``https`` viram
    # botão de link, para que um registro malformado não injete outro
    # esquema (``javascript:``, por exemplo) na página.
    url_pdf = _url_web(link_pdf)
    url_ficha = _url_web(link)

    with st.container(border=True, key=f"cartao_rigeo_{chave}"):
        st.markdown(f"**{titulo}**")

        # Autores e ano na mesma legenda; "Base" fica abaixo, já que a
        # fonte do cartão de RIGeo é sempre o próprio acervo.
        metadados = [
            "Autores: " + "; ".join(autores)
            if autores
            else "Autores não informados"
        ]

        if ano:
            metadados.append(ano)

        st.caption(" · ".join(metadados))

        if url_pdf or url_ficha:
            # Botões lado a lado: PDF direto e ficha no RIGeo.
            with st.container(horizontal=True, gap="small"):
                if url_pdf:
                    st.link_button(
                        t("link_abrir_pdf"),
                        url_pdf,
                        key=f"pdf_{chave}"
                    )

                if url_ficha:
                    st.link_button(
                        t("link_ficha_rigeo"),
                        url_ficha,
                        key=f"ficha_{chave}"
                    )


def _renderizar_cartao_web(pagina, chave):
    """Cartão clicável de uma página encontrada na Web aberta.

    ``chave`` é única por resposta (``session_id`` + mensagem + índice),
    então os botões de link não repetem chave entre sessões nem entre
    respostas. O domínio aparece em destaque porque é ele que o modelo
    cita como origem da informação (``autores`` no schema padrão).
    """

    titulo = (
        _escapar_markdown(_texto_curto(pagina.get("titulo")))
        or "Página sem título"
    )
    dominio = _texto_curto(pagina.get("autores"))
    resumo = _escapar_markdown(_texto_curto(pagina.get("resumo")))

    # Só ``http``/``https`` viram link: o endereço vem de fonte externa.
    url = _url_web(pagina.get("link"))

    with st.container(border=True, key=f"cartao_web_{chave}"):
        st.markdown(f"**{titulo}**")

        metadados = [
            f"Domínio: {dominio}" if dominio else "Domínio não informado",
            "Web aberta",
        ]
        st.caption(" · ".join(metadados))

        if resumo:
            st.caption(resumo)

        if url:
            st.link_button(
                t("link_abrir_pagina"),
                url,
                key=f"pagina_web_{chave}"
            )


def _renderizar_cartao_publicacao(registro, chave, rotulo_link):
    """Cartão clicável de uma publicação de base internacional.

    O schema é o mesmo das demais fontes externas: título, autores, ano,
    resumo, link e ``link_pdf``. ``rotulo_link`` identifica a base no
    botão (OpenAlex ou ScienceBase) e a origem também aparece na
    legenda, para o usuário não confundir com o acervo RIGeo.
    """

    titulo = _escapar_markdown(
        _texto_curto(registro.get("titulo")) or "Registro sem título"
    )
    autores = _escapar_markdown(_texto_curto(registro.get("autores")))
    ano = _texto_curto(registro.get("ano"))
    resumo = _escapar_markdown(_texto_curto(registro.get("resumo")))
    fonte = _texto_curto(registro.get("fonte"))
    url_pdf = _url_web(registro.get("link_pdf"))
    url_ficha = _url_web(registro.get("link"))

    with st.container(border=True, key=f"cartao_publicacao_{chave}"):
        st.markdown(f"**{titulo}**")

        metadados = [
            f"Fonte: {fonte}" if fonte else "Fonte não informada",
        ]

        if ano:
            metadados.append(ano)

        metadados.append(
            "Autores: " + autores if autores else "Autores não informados"
        )

        st.caption(" · ".join(metadados))

        if resumo:
            st.caption(resumo)

        if url_pdf or url_ficha:
            with st.container(horizontal=True, gap="small"):
                if url_pdf:
                    st.link_button(
                        t("link_abrir_pdf"),
                        url_pdf,
                        key=f"pdf_{chave}"
                    )

                if url_ficha:
                    st.link_button(
                        rotulo_link,
                        url_ficha,
                        key=f"ficha_{chave}"
                    )


def _renderizar_cartao_geosgb(ocorrencia, chave):
    """Cartão de uma ocorrência mineral do GeoSGB.

    ``chave`` é única por resposta (``session_id`` + mensagem + índice),
    então os botões de link não repetem chave entre sessões nem entre
    respostas. O status (garimpo, mina, depósito ou ocorrência) aparece
    na legenda, porque é ele que qualifica o ponto cadastrado; as
    coordenadas vêm no formato usado no schema padrão.
    """

    titulo = _escapar_markdown(
        _texto_curto(ocorrencia.get("titulo"))
        or "Ocorrência sem nome"
    )
    status = _texto_curto(ocorrencia.get("status"))
    substancia = _texto_curto(ocorrencia.get("substancia"))
    municipio = _texto_curto(ocorrencia.get("municipio"))
    uf = _texto_curto(ocorrencia.get("uf"))
    folha = _texto_curto(ocorrencia.get("folha"))
    latitude = ocorrencia.get("latitude")
    longitude = ocorrencia.get("longitude")
    coordenadas = (
        f"{latitude:.5f}, {longitude:.5f}"
        if isinstance(latitude, (int, float))
        and isinstance(longitude, (int, float))
        else "não informadas"
    )
    url_geosgb = _url_web(ocorrencia.get("link"))

    with st.container(border=True, key=f"cartao_geosgb_{chave}"):
        st.markdown(f"**{titulo}**")

        local = "/".join(
            parte for parte in (municipio, uf) if parte
        ) or "Município não informado"

        st.caption(
            " · ".join(
                parte
                for parte in (
                    substancia or "Substância não informada",
                    status or "Status não informado",
                    local,
                )
                if parte
            )
        )

        st.caption(
            f"Coord: {coordenadas}"
            + (f" · Folha: {folha}" if folha else "")
        )

        if url_geosgb:
            st.link_button(
                t("link_abrir_geosgb"),
                url_geosgb,
                key=f"geosgb_link_{chave}"
            )


def _renderizar_cartao_anm(processo, chave):
    """Cartão de um processo minerário da ANM / SIGMINE.

    O cadastro da ANM não publica autores: o que qualifica o registro é o
    titular, a fase atual e a área titulada. O cartão mostra esses campos
    no lugar dos metadados bibliográficos usados pelo RIGeo, mantendo o
    mesmo formato dos demais cartões de fontes. ``chave`` é única por
    resposta (``session_id`` + mensagem + índice), então os botões de link
    não repetem chave entre sessões nem entre respostas.
    """

    titulo = _escapar_markdown(
        _texto_curto(processo.get("titulo"))
        or "Processo sem número"
    )
    fase = _texto_curto(processo.get("fase"))
    titular = _texto_curto(processo.get("titular"))
    substancia = _texto_curto(processo.get("substancia"))
    uf = _texto_curto(processo.get("uf"))
    municipio = _texto_curto(processo.get("municipio"))
    ultimo_evento = _texto_curto(processo.get("ultimo_evento"))
    area = processo.get("area_ha")
    area_texto = (
        f"{area:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if isinstance(area, (int, float))
        else "não informada"
    )
    url_sigmine = _url_web(processo.get("link"))

    with st.container(border=True, key=f"cartao_anm_{chave}"):
        st.markdown(f"**{titulo}**")

        local = "/".join(
            parte for parte in (municipio, uf) if parte
        ) or "UF não informada"

        st.caption(
            " · ".join(
                parte
                for parte in (
                    f"Fase: {fase}" if fase else "Fase não informada",
                    f"Área: {area_texto} ha",
                    local,
                )
                if parte
            )
        )

        st.caption(
            "Titular: " + (titular or "não informado")
            + (f" · Substância: {substancia}" if substancia else "")
        )

        if ultimo_evento:
            st.caption(
                tf("ultimo_evento", evento=ultimo_evento)
            )

        if url_sigmine:
            st.link_button(
                t("link_abrir_sigmine"),
                url_sigmine,
                key=f"anm_link_{chave}"
            )


def _renderizar_cartao_geologico(registro, chave, rotulo_link, rotulo_detalhe):
    """Cartão clicável de um registro das fontes geológicas abertas.

    Macrostrat, SIAGAS/RIMAS e INDE/GEOSSIT usam o mesmo schema padrão
    (título, autores, ano, resumo, link, ``link_pdf``), com um endereço
    específico do registro em ``link_detalhe`` quando a base publica
    uma ficha própria (a página do poço no SIAGAS, o geossítio no
    GEOSSIT). ``chave`` é única por resposta (``session_id`` + mensagem
    + índice), então os botões não repetem chave entre sessões.
    """

    titulo = _escapar_markdown(
        _texto_curto(registro.get("titulo")) or "Registro sem título"
    )
    autores = _escapar_markdown(_texto_curto(registro.get("autores")))
    ano = _texto_curto(registro.get("ano"))
    resumo = _escapar_markdown(_texto_curto(registro.get("resumo")))
    fonte = _texto_curto(registro.get("fonte"))
    url_ficha = _url_web(registro.get("link"))
    url_detalhe = _url_web(registro.get("link_detalhe"))

    with st.container(border=True, key=f"cartao_geologico_{chave}"):
        st.markdown(f"**{titulo}**")

        metadados = [
            f"Fonte: {fonte}" if fonte else "Fonte não informada",
        ]

        if ano:
            metadados.append(ano)

        metadados.append(
            "Autores: " + autores if autores else "Autores não informados"
        )

        st.caption(" · ".join(metadados))

        if resumo:
            st.caption(resumo)

        if url_detalhe or url_ficha:
            with st.container(horizontal=True, gap="small"):
                if url_detalhe:
                    st.link_button(
                        rotulo_detalhe,
                        url_detalhe,
                        key=f"detalhe_{chave}"
                    )

                if url_ficha:
                    st.link_button(
                        rotulo_link,
                        url_ficha,
                        key=f"ficha_{chave}"
                    )


def _renderizar_fontes(
    roteamento,
    artigos_rigeo,
    chave,
    busca_rigeo=None,
    estacoes_ana=None,
    web=None,
    openalex=None,
    usgs=None,
    intl_geo=None,
    geosgb=None,
    anm=None,
    macrostrat=None,
    siagas=None,
    geossit=None
):
    """Expander com as fontes e os metadados usados na resposta.

    Usa apenas o que já foi guardado no histórico da sessão
    (``roteamento``, ``artigos_rigeo``, ``busca_rigeo``,
    ``estacoes_ana``, ``web``, ``openalex``, ``usgs``, ``intl_geo``,
    ``geosgb``, ``anm``, ``macrostrat``, ``siagas`` e ``geossit``), sem
    refazer nenhuma consulta. ``chave`` é o prefixo único (``session_id``
    + mensagem) do expander e dos cartões, definido por
    ``_chave_widget`` ou por ``_chave_resposta_atual``.
    """

    roteamento = roteamento or {}
    artigos_rigeo = artigos_rigeo or []
    busca_rigeo = busca_rigeo or {}
    estacoes_ana = estacoes_ana or []
    web = web or {}
    openalex = openalex or {}
    usgs = usgs or {}
    intl_geo = intl_geo or {}
    geosgb = geosgb or {}
    anm = anm or {}
    macrostrat = macrostrat or {}
    siagas = siagas or {}
    geossit = geossit or {}
    registros_web = web.get("registros") or []
    registros_openalex = openalex.get("registros") or []
    registros_usgs = usgs.get("registros") or []
    registros_intl = intl_geo.get("registros") or []
    registros_geosgb = geosgb.get("registros") or []
    registros_anm = anm.get("registros") or []
    registros_macrostrat = macrostrat.get("registros") or []
    registros_siagas = siagas.get("registros") or []
    registros_geossit = geossit.get("registros") or []

    intencao = roteamento.get("intencao")
    documentos_locais = roteamento.get("documentos_locais") or []

    # Conversas antigas não guardam a marca de roteamento por toggle;
    # nelas a intenção continua decidindo a exibição dos documentos.
    if "usar_documentos" in roteamento:
        mostrar_documentos = bool(
            roteamento["usar_documentos"] and documentos_locais
        )
    else:
        mostrar_documentos = bool(
            intencao in INTENCOES_COM_DOCUMENTOS and documentos_locais
        )

    with st.expander(
        t("fontes_expander"),
        expanded=False,
        key=f"fontes_{chave}"
    ):
        if intencao:
            chave_intencao = CHAVES_ROTULO_INTENCAO.get(intencao)
            rotulo_intencao = (
                t(chave_intencao) if chave_intencao else ""
            )

            st.caption(
                tf("roteamento_caption", intencao=intencao)
                + (f" · {rotulo_intencao}" if rotulo_intencao else "")
            )

        if busca_rigeo.get("termo"):
            st.caption(
                tf(
                    "termo_rigeo",
                    termo=_texto_curto(busca_rigeo["termo"]),
                )
            )

        if web.get("termo_busca"):
            st.caption(
                tf(
                    "termo_web",
                    termo=_texto_curto(web["termo_busca"]),
                )
            )

        # O planejamento é único para as duas bases internacionais: o
        # mesmo termo em inglês alimenta OpenAlex e ScienceBase.
        termo_internacional = _texto_curto(
            openalex.get("termo_busca")
            or usgs.get("termo_busca")
            or intl_geo.get("termo_busca")
        )

        if termo_internacional:
            bases = [
                nome
                for nome, dados_base in (
                    ("OpenAlex", openalex),
                    ("USGS ScienceBase", usgs),
                    ("Serviços Geológicos Internacionais", intl_geo),
                )
                if dados_base
            ]
            separador = " e " if st.session_state.get(
                "idioma"
            ) != "en" else " and "

            st.caption(
                tf(
                    "termo_internacional",
                    bases=separador.join(bases),
                    termo=termo_internacional,
                )
            )

        if (
            not artigos_rigeo
            and not mostrar_documentos
            and not estacoes_ana
            and not registros_web
            and not registros_openalex
            and not registros_usgs
            and not registros_intl
            and not registros_geosgb
            and not registros_anm
            and not registros_macrostrat
            and not registros_siagas
            and not registros_geossit
            and not openalex
            and not usgs
            and not intl_geo
            and not geosgb
            and not anm
            and not macrostrat
            and not siagas
            and not geossit
        ):
            st.caption(t("sem_fontes"))
            return

        if artigos_rigeo:
            st.markdown(
                tf("artigos_rigeo", n=len(artigos_rigeo))
            )

            for indice, artigo in enumerate(artigos_rigeo):
                _renderizar_cartao_rigeo(
                    artigo,
                    f"{chave}_rigeo_{indice}"
                )

        if estacoes_ana:
            rotulo_ana = _texto_curto(
                estacoes_ana[0].get("fonte")
            ) or "ANA / HidroWeb"
            st.markdown(
                tf(
                    "estacoes_ana",
                    fonte=rotulo_ana,
                    n=len(estacoes_ana),
                )
            )

            for indice, estacao in enumerate(estacoes_ana):
                _renderizar_cartao_estacao_ana(
                    estacao,
                    f"{chave}_ana_{indice}"
                )

        if registros_geosgb:
            st.markdown(
                tf("ocorrencias_geosgb", n=len(registros_geosgb))
            )

            for indice, ocorrencia in enumerate(registros_geosgb):
                _renderizar_cartao_geosgb(
                    ocorrencia,
                    f"{chave}_geosgb_{indice}"
                )
        elif geosgb:
            st.caption(
                tf(
                    "vazio_geosgb",
                    motivo=(
                        _texto_curto(geosgb.get("aviso"))
                        or t("motivo_geosgb")
                    ),
                )
            )

        if registros_anm:
            st.markdown(
                tf("processos_anm", n=len(registros_anm))
            )

            for indice, processo in enumerate(registros_anm):
                _renderizar_cartao_anm(
                    processo,
                    f"{chave}_anm_{indice}"
                )
        elif anm:
            st.caption(
                tf(
                    "vazio_anm",
                    motivo=(
                        _texto_curto(anm.get("aviso"))
                        or t("motivo_anm")
                    ),
                )
            )

        if registros_macrostrat:
            st.markdown(
                tf("unidades_macrostrat", n=len(registros_macrostrat))
            )

            for indice, unidade in enumerate(registros_macrostrat):
                _renderizar_cartao_geologico(
                    unidade,
                    f"{chave}_macrostrat_{indice}",
                    t("link_abrir_macrostrat"),
                    t("link_ficha_unidade")
                )
        elif macrostrat:
            st.caption(
                tf(
                    "vazio_macrostrat",
                    motivo=(
                        _texto_curto(macrostrat.get("aviso"))
                        or t("motivo_macrostrat")
                    ),
                )
            )

        if registros_siagas:
            st.markdown(
                tf("pocos_siagas", n=len(registros_siagas))
            )

            for indice, poco in enumerate(registros_siagas):
                _renderizar_cartao_geologico(
                    poco,
                    f"{chave}_siagas_{indice}",
                    t("link_abrir_siagas"),
                    t("link_ficha_poco")
                )
        elif siagas:
            st.caption(
                tf(
                    "vazio_siagas",
                    motivo=(
                        _texto_curto(siagas.get("aviso"))
                        or t("motivo_siagas")
                    ),
                )
            )

        if registros_geossit:
            st.markdown(
                tf("geossitios_inde", n=len(registros_geossit))
            )

            for indice, sitio in enumerate(registros_geossit):
                _renderizar_cartao_geologico(
                    sitio,
                    f"{chave}_geossit_{indice}",
                    t("link_abrir_geossit"),
                    t("link_ficha_geossitio")
                )
        elif geossit:
            st.caption(
                tf(
                    "vazio_geossit",
                    motivo=(
                        _texto_curto(geossit.get("aviso"))
                        or t("motivo_geossit")
                    ),
                )
            )

        if registros_web:
            st.markdown(
                tf("paginas_web", n=len(registros_web))
            )

            for indice, pagina in enumerate(registros_web):
                _renderizar_cartao_web(
                    pagina,
                    f"{chave}_web_{indice}"
                )
        elif web:
            st.caption(
                tf(
                    "vazio_web",
                    motivo=(
                        _texto_curto(web.get("aviso"))
                        or t("motivo_web")
                    ),
                )
            )

        if registros_openalex:
            st.markdown(
                tf("openalex_titulo", n=len(registros_openalex))
            )

            for indice, publicacao in enumerate(registros_openalex):
                _renderizar_cartao_publicacao(
                    publicacao,
                    f"{chave}_openalex_{indice}",
                    t("link_abrir_openalex")
                )
        elif openalex:
            st.caption(
                tf(
                    "vazio_openalex",
                    motivo=(
                        _texto_curto(openalex.get("aviso"))
                        or t("motivo_openalex")
                    ),
                )
            )

        if registros_intl:
            st.markdown(
                tf("servicos_intl", n=len(registros_intl))
            )

            if intl_geo.get("termo_busca"):
                st.caption(
                    tf(
                        "termo_intl_consultado",
                        termo=_texto_curto(intl_geo["termo_busca"]),
                    )
                )

            agrupados = {}
            for publicacao in registros_intl:
                nome_servico = (
                    _texto_curto(publicacao.get("fonte"))
                    or t("servico_generico")
                )
                agrupados.setdefault(nome_servico, []).append(publicacao)

            indice_global = 0

            for nome_servico, publicacoes in agrupados.items():
                st.caption(f"**{nome_servico}**")

                for publicacao in publicacoes:
                    _renderizar_cartao_publicacao(
                        publicacao,
                        f"{chave}_intl_{indice_global}",
                        t("link_abrir_servico")
                    )
                    indice_global += 1
        elif intl_geo:
            st.caption(
                tf(
                    "vazio_intl",
                    motivo=(
                        _texto_curto(intl_geo.get("aviso"))
                        or t("motivo_intl")
                    ),
                )
            )

        if registros_usgs:
            st.markdown(
                tf("usgs_sciencebase", n=len(registros_usgs))
            )

            for indice, publicacao in enumerate(registros_usgs):
                _renderizar_cartao_publicacao(
                    publicacao,
                    f"{chave}_usgs_{indice}",
                    t("link_ficha_sciencebase")
                )
        elif usgs:
            st.caption(
                tf(
                    "vazio_usgs",
                    motivo=(
                        _texto_curto(usgs.get("aviso"))
                        or t("motivo_usgs")
                    ),
                )
            )

        if mostrar_documentos:
            st.markdown(
                tf(
                    "documentos_locais_consultados",
                    n=len(documentos_locais),
                )
            )
            st.markdown(
                "\n".join(
                    f"- `{_texto_curto(nome)}`"
                    for nome in documentos_locais
                    if _texto_curto(nome)
                )
            )


def _renderizar_mapa_espacial(feicoes, chave):
    """Expander com filtro por camada, mapa nativo, tabela e CSV.

    ``feicoes`` é a lista devolvida por
    ``services.spatial_parser.consolidar_pontos_mapa`` e ``chave`` é o
    prefixo único dos widgets (``session_id`` + mensagem). O mapa usa
    ``st.map`` — nativo, instantâneo e sem dependência externa — com a
    cor de cada categoria vinda da própria feição.

    Nada é recalculado aqui: ao reabrir uma conversa do histórico, a
    lista gravada na mensagem alimenta o mapa diretamente, sem repetir
    as expressões regulares nem as consultas às APIs.
    """

    feicoes = [
        feicao
        for feicao in (feicoes or [])
        if isinstance(feicao, dict) and feicao.get("lat") is not None
        and feicao.get("lon") is not None
    ]

    if not feicoes:
        return

    total = len(feicoes)

    camada_padrao = t("outras_fontes")

    with st.expander(
        tf("mapa_expander", n=total),
        expanded=False,
        key=f"mapa_{chave}",
    ):
        camadas = list(dict.fromkeys(
            feicao.get("camada") or camada_padrao
            for feicao in feicoes
        ))

        selecionadas = st.multiselect(
            t("mapa_camadas"),
            camadas,
            default=camadas,
            key=f"mapa_camadas_{chave}",
            help=t("ajuda_mapa_camadas"),
        )

        filtradas = [
            feicao
            for feicao in feicoes
            if (feicao.get("camada") or camada_padrao) in selecionadas
        ]

        if not filtradas:
            st.caption(t("mapa_sem_feicoes"))
            return

        df_mapa = pd.DataFrame({
            "nome": [feicao.get("nome") or "" for feicao in filtradas],
            "camada": [
                feicao.get("camada") or camada_padrao
                for feicao in filtradas
            ],
            "lat": [feicao["lat"] for feicao in filtradas],
            "lon": [feicao["lon"] for feicao in filtradas],
            "cor_hex": [
                feicao.get("cor_hex") or "#1F6FEB"
                for feicao in filtradas
            ],
        })

        st.map(
            df_mapa,
            latitude="lat",
            longitude="lon",
            color="cor_hex",
            size=60,
            height=420,
            alt=tf("mapa_alt", n=len(filtradas)),
        )

        # Tabela compacta: posição em cinco casas (~1 m), folha CIM e,
        # quando a feição é a própria folha, os limites da área.
        coluna_nome = t("col_nome")
        coluna_camada = t("col_camada")
        coluna_latitude = t("col_latitude")
        coluna_longitude = t("col_longitude")
        coluna_folha = t("col_folha_cim")
        coluna_limites = t("col_limites")
        coluna_detalhe = t("col_detalhe")

        df_exibicao = pd.DataFrame({
            coluna_nome: [
                feicao.get("nome") or "" for feicao in filtradas
            ],
            coluna_camada: [
                feicao.get("camada") or camada_padrao
                for feicao in filtradas
            ],
            coluna_latitude: [
                round(feicao["lat"], 5) for feicao in filtradas
            ],
            coluna_longitude: [
                round(feicao["lon"], 5) for feicao in filtradas
            ],
            coluna_folha: [
                feicao.get("folha_cim") or "" for feicao in filtradas
            ],
            coluna_limites: [
                feicao.get("limites") or "" for feicao in filtradas
            ],
            coluna_detalhe: [
                feicao.get("detalhe") or "" for feicao in filtradas
            ],
        })

        st.dataframe(
            df_exibicao,
            width="stretch",
            hide_index=True,
            column_config={
                coluna_latitude: st.column_config.NumberColumn(
                    coluna_latitude, format="%.5f"
                ),
                coluna_longitude: st.column_config.NumberColumn(
                    coluna_longitude, format="%.5f"
                ),
            },
            alt=t("mapa_tabela_alt"),
        )

        st.download_button(
            t("baixar_pontos"),
            data=gerar_csv_pontos(filtradas),
            file_name=f"pontos_espaciais_{_chave_widget_dados(chave)}.csv",
            mime="text/csv",
            key=f"mapa_csv_{chave}",
            help=t("ajuda_baixar_pontos"),
        )

        st.caption(
            tf(
                "mapa_rodape",
                exibidas=len(filtradas),
                total=total,
                camadas_ativas=len(selecionadas),
                camadas=len(camadas),
            )
        )


def _detalhar_busca_rigeo(busca):
    """Mostra no status qual termo foi efetivamente enviado ao RIGeo.

    ``busca`` é o plano de ``services.external_api_service.extrair_termos``
    (repassado por ``responder()``). O termo aparece destacado, porque é
    ele — não a pergunta inteira — que o DSpace recebeu: é a informação
    que explica por que certos artigos voltaram (ou não).
    """

    if not busca:
        return

    termo = _texto_curto(busca.get("termo"))
    origem = _texto_curto(busca.get("origem"))
    consultas = [
        _texto_curto(consulta)
        for consulta in busca.get("consultas") or []
        if _texto_curto(consulta)
    ]

    if termo:
        legenda = t("termo_rigeo").format(
            termo=_escapar_markdown(termo)
        )
    else:
        legenda = t("status_termo_rigeo_vazio")

    if origem == "llm":
        legenda += t("status_termos_ollama")

    st.markdown(f"**{legenda}**")

    if len(consultas) > 1:
        st.caption(
            tf(
                "status_plano_rigeo",
                plano=" → ".join(
                    f'"{consulta}"' for consulta in consultas
                ),
            )
        )


def _detalhar_recuperacao(dados):
    """Mostra como a busca local (RAG bilíngue) foi executada.

    O usuário vê as duas queries (PT e EN) que consultaram o índice, de
    onde veio a tradução (Ollama ou fallback determinístico) e se houve
    amostragem representativa — a informação que explica por que
    apareceram trechos de um arquivo em inglês para uma pergunta em
    português.
    """

    documentos = (dados or {}).get("documentos") or {}
    trechos = documentos.get("trechos") or []

    if not trechos:
        return

    queries = documentos.get("queries") or {}
    idioma = documentos.get("idioma_pergunta")
    amostragem = bool(documentos.get("amostragem"))

    st.markdown(t("status_busca_bilingue"))

    rotulos_origem = {
        "llm": t("status_origem_llm"),
        "fallback": t("status_origem_fallback"),
        "identica": t("status_origem_identica"),
    }

    legenda = (
        tf("status_idioma_detectado", idioma=rotulo_idioma(idioma))
        if idioma
        else t("status_idioma_nao_identificado")
    )
    origem = rotulos_origem.get(queries.get("origem"), "")
    legenda += f" · {origem}" if origem else ""

    st.caption(legenda)

    for lingua, chave in (("PT", "pt"), ("EN", "en")):
        texto = _texto_curto(queries.get(chave))

        if texto:
            st.markdown(
                tf(
                    "status_query",
                    lingua=lingua,
                    texto=_escapar_markdown(texto),
                )
            )

    if amostragem:
        st.caption(t("status_amostragem"))

    recuperados = sum(
        1
        for trecho in trechos
        if trecho.get("origem_trecho") == "busca"
    )
    amostrados = len(trechos) - recuperados

    if recuperados or amostrados:
        st.caption(
            tf(
                "status_trechos",
                recuperados=recuperados,
                amostrados=amostrados,
            )
        )


def _detalhar_consulta(roteamento, artigos_rigeo, dados):
    """Mostra o roteamento e as fontes recuperadas dentro do status."""

    intencao = roteamento.get("intencao")
    justificativa = _texto_curto(roteamento.get("justificativa"))
    origem = _texto_curto(roteamento.get("origem"))
    aviso = _texto_curto(roteamento.get("aviso"))

    st.badge(
        tf(
            "status_intencao",
            intencao=intencao or t("status_intencao_padrao"),
        ),
        icon=":material/route:",
        color=_cor_intencao(intencao)
    )

    if justificativa:
        st.markdown(f"*{_escapar_markdown(justificativa)}*")

    if origem:
        st.caption(tf("status_decisao", origem=origem))

    if aviso:
        st.caption(f"⚠️ {aviso}")

    _detalhar_busca_rigeo((dados or {}).get("busca"))

    if artigos_rigeo:
        st.markdown(
            tf("status_artigos_rigeo", n=len(artigos_rigeo))
        )

        linhas = []

        for artigo in artigos_rigeo:
            titulo = _escapar_markdown(
                _texto_curto(artigo.get("titulo"))
                or t("status_titulo_nao_informado")
            )
            ano = _texto_curto(artigo.get("ano"))

            linhas.append(
                f"- {titulo}" + (f" ({ano})" if ano else "")
            )

        st.markdown("\n".join(linhas))

    documentos_locais = roteamento.get("documentos_locais") or []

    # O mesmo critério do expander de fontes: a base local só é listada
    # quando o toggle estava ligado (ou, em conversas antigas, quando a
    # intenção incluía documentos).
    if "usar_documentos" in roteamento:
        documentos_consultados = bool(roteamento["usar_documentos"])
    else:
        documentos_consultados = intencao in INTENCOES_COM_DOCUMENTOS

    if documentos_consultados and documentos_locais:
        st.markdown(
            tf(
                "documentos_locais_consultados",
                n=len(documentos_locais),
            )
        )
        st.markdown(
            "\n".join(
                f"- `{_texto_curto(nome)}`"
                for nome in documentos_locais
                if _texto_curto(nome)
            )
        )

    trechos = ((dados or {}).get("documentos") or {}).get("trechos") or []

    if trechos:
        st.caption(
            tf("status_trechos_documentos", n=len(trechos))
        )
        _detalhar_recuperacao(dados)

    aviso_sgb = _texto_curto(
        ((dados or {}).get("sgb") or {}).get("aviso")
    )

    if aviso_sgb:
        st.caption(f"RIGeo: {aviso_sgb}")

    ana = (dados or {}).get("ana") or {}
    estacoes_ana = ana.get("registros") or []
    aviso_ana = _texto_curto(ana.get("aviso"))
    rotulo_ana = _texto_curto(ana.get("fonte")) or "ANA / HidroWeb"

    if estacoes_ana:
        st.markdown(
            tf(
                "status_estacoes_recuperadas",
                fonte=rotulo_ana,
                n=len(estacoes_ana),
            )
        )
        st.markdown(_tabela_estacoes_ana(estacoes_ana))
    elif ana and not aviso_ana:
        recorte = []

        if ana.get("uf"):
            recorte.append(f"UF {ana['uf']}")

        if ana.get("termo_busca"):
            recorte.append(f'termo "{_texto_curto(ana["termo_busca"])}"')

        st.caption(
            tf(
                "status_ana_vazio",
                fonte=rotulo_ana,
                recorte=" · ".join(recorte) or "—",
            )
        )

    if aviso_ana:
        st.caption(f"{rotulo_ana}: {aviso_ana}")

    # Ocorrências minerais do GeoSGB: a tabela compacta já é a mesma
    # usada no contexto do LLM, o que mantém interface e resposta
    # coerentes sobre quais alvos foram considerados.
    geosgb = (dados or {}).get("geosgb") or {}
    ocorrencias_geosgb = geosgb.get("registros") or []
    aviso_geosgb = _texto_curto(geosgb.get("aviso"))

    if ocorrencias_geosgb:
        st.markdown(
            tf("ocorrencias_geosgb", n=len(ocorrencias_geosgb))
        )
        st.markdown(montar_tabela_ocorrencias_geosgb(ocorrencias_geosgb))

        if aviso_geosgb:
            st.caption(f"GeoSGB: {aviso_geosgb}")
    elif geosgb:
        st.caption(
            tf(
                "vazio_geosgb",
                motivo=aviso_geosgb or t("motivo_geosgb"),
            )
        )

    # Macrostrat, SIAGAS/RIMAS, INDE/GEOSSIT e ANM/SIGMINE: as tabelas
    # compactas são as mesmas usadas no contexto do LLM, o que mantém o
    # status e a resposta coerentes sobre quais registros foram
    # considerados.
    for chave_fonte, chave_rotulo, tabela, aviso_prefixo in (
        (
            "anm",
            "status_anm_recuperados",
            montar_tabela_processos_anm,
            "ANM / SIGMINE",
        ),
        (
            "macrostrat",
            "status_macrostrat_recuperadas",
            montar_tabela_unidades_macrostrat,
            "Macrostrat",
        ),
        (
            "siagas",
            "status_siagas_recuperados",
            montar_tabela_pocos_siagas,
            "SIAGAS / RIMAS",
        ),
        (
            "geossit",
            "status_geossit_recuperados",
            montar_tabela_geossitios,
            "INDE / GEOSSIT",
        ),
    ):
        fonte = (dados or {}).get(chave_fonte) or {}
        registros = fonte.get("registros") or []
        aviso_fonte = _texto_curto(fonte.get("aviso"))

        if registros:
            st.markdown(
                f"**{t(chave_rotulo)} ({len(registros)})**"
            )
            st.markdown(tabela(registros))

            if aviso_fonte:
                st.caption(f"{aviso_prefixo}: {aviso_fonte}")
        elif fonte:
            st.caption(
                f"{aviso_prefixo}: "
                + (aviso_fonte or t("status_vazio_registro"))
            )

    web = (dados or {}).get("web") or {}
    registros_web = web.get("registros") or []
    aviso_web = _texto_curto(web.get("aviso"))

    if registros_web:
        st.markdown(
            tf("status_paginas_web", n=len(registros_web))
        )

        linhas = []

        for pagina in registros_web:
            titulo = _escapar_markdown(
                _texto_curto(pagina.get("titulo"))
                or t("status_pagina_sem_titulo")
            )
            dominio = _texto_curto(pagina.get("autores"))
            url = _url_web(pagina.get("link"))
            complemento = f" · {dominio}" if dominio else ""

            if url:
                linhas.append(f"- [{titulo}]({url}){complemento}")
            else:
                linhas.append(f"- {titulo}{complemento}")

        st.markdown("\n".join(linhas))

    if aviso_web:
        st.caption(f"Web: {aviso_web}")

    # Bases internacionais abertas. O termo em inglês é exibido antes
    # da lista: ele é a consulta realmente enviada às APIs.
    for chave, rotulo in (
        ("openalex", "OpenAlex"),
        ("usgs", "USGS ScienceBase"),
    ):
        base = (dados or {}).get(chave) or {}
        registros = base.get("registros") or []
        aviso_base = _texto_curto(base.get("aviso"))
        termo_base = _texto_curto(base.get("termo_busca"))

        if not base:
            continue

        if termo_base:
            st.caption(
                tf(
                    "status_termo_ingles",
                    base=rotulo,
                    termo=termo_base,
                )
            )

        if registros:
            st.markdown(
                tf(
                    "status_publicacoes",
                    base=rotulo,
                    n=len(registros),
                )
            )

            linhas = []

            for publicacao in registros:
                titulo = _escapar_markdown(
                    _texto_curto(publicacao.get("titulo"))
                    or t("status_registro_sem_titulo")
                )
                ano = _texto_curto(publicacao.get("ano"))
                url = _url_web(publicacao.get("link"))
                complemento = f" · {ano}" if ano else ""

                if url:
                    linhas.append(f"- [{titulo}]({url}){complemento}")
                else:
                    linhas.append(f"- {titulo}{complemento}")

            st.markdown("\n".join(linhas))
        else:
            st.caption(
                f"{rotulo}: "
                + (aviso_base or t("status_vazio_registro"))
            )

    # Serviços geológicos internacionais: a tabela consolidada identifica
    # o provedor de cada registro e é a mesma usada no contexto do LLM.
    intl_geo = (dados or {}).get("intl_geo") or {}
    registros_intl = intl_geo.get("registros") or []
    aviso_intl = _texto_curto(intl_geo.get("aviso"))

    if registros_intl:
        st.markdown(
            tf("status_intl_recuperados", n=len(registros_intl))
        )
        st.markdown(
            montar_tabela_servicos_geologicos(registros_intl)
        )

        if aviso_intl:
            st.caption(
                tf("aviso_servicos_intl", aviso=aviso_intl)
            )
    elif intl_geo:
        st.caption(
            tf(
                "vazio_intl",
                motivo=aviso_intl or t("motivo_intl"),
            )
        )


# ---------------------------------------------------------------------------
# Exportação do Parecer Técnico (.docx e .md)
# ---------------------------------------------------------------------------

# Cada conector guarda os registros em um campo próprio da mensagem. A
# segunda posição é o campo no histórico e a terceira, o rótulo usado na
# referência ABNT e no bloco de metadados do parecer.
FONTES_METADADOS_PARECER = (
    ("ana", "estacoes_ana", "ANA / HidroWeb"),
    ("sgb", "artigos_rigeo", "RIGeo / SGB"),
    ("web", "web", "Pesquisa na Web"),
    ("openalex", "openalex", "OpenAlex"),
    ("usgs", "usgs", "USGS ScienceBase"),
    ("intl_geo", "intl_geo", "Serviços Geológicos Internacionais"),
    ("geosgb", "geosgb", "GeoSGB / SGB"),
    ("anm", "anm", "ANM / SIGMINE"),
    ("macrostrat", "macrostrat", "Macrostrat"),
    ("siagas", "siagas", "SIAGAS / RIMAS"),
    ("geossit", "geossit", "INDE / GEOSSIT"),
)


def _metadados_fontes_mensagem(mensagem):
    """Consolida as fontes gravadas na mensagem para o parecer.

    O gerador aceita grupos no formato ``{"fonte", "registros"}``, o
    mesmo do mapa espacial. Cada registro leva autoria, ano, link e DOI
    já guardados no histórico — nenhuma consulta é refeita. Os
    documentos locais entram como um grupo próprio, com o nome do
    arquivo como título.
    """

    fontes = []

    for _chave, campo, rotulo in FONTES_METADADOS_PARECER:
        registros = _registros_da_mensagem(mensagem.get(campo))

        if not registros:
            continue

        itens = []

        for registro in registros:
            item = dict(registro)

            if not _texto_curto(item.get("fonte")):
                item["fonte"] = rotulo

            itens.append(item)

        fontes.append({
            "fonte": rotulo,
            "registros": itens,
        })

    documentos = (
        (mensagem.get("roteamento") or {}).get("documentos_locais") or []
    )
    itens_locais = []

    for documento in documentos:
        titulo = _texto_curto(documento)

        if not titulo:
            continue

        itens_locais.append({
            "titulo": titulo,
            "autores": "Acervo documental local",
            "fonte": "Acervo documental local",
        })

    if itens_locais:
        fontes.append({
            "fonte": "local",
            "registros": itens_locais,
        })

    return fontes


def _perfil_da_mensagem(mensagem):
    """Perfil analítico vigente na mensagem (ou o atual da sessão).

    Conversas gravadas antes deste recurso não têm o campo; nesse caso o
    parecer usa o perfil selecionado no momento da exportação.
    """

    perfil = _texto_curto(mensagem.get("perfil_analitico"))

    if perfil:
        return perfil

    return (
        st.session_state.get("perfil_analitico")
        or PERFIL_PADRAO
    )


@st.cache_data(show_spinner=False, max_entries=64)
def _parecer_docx_cache(
    pergunta,
    resposta,
    metadados_json,
    perfil_analitico,
    feicoes_json
):
    """Gera o .docx uma única vez por conteúdo e o reutiliza nos reruns.

    A chave do cache é o próprio texto do parecer: reabrir a conversa ou
    redesenhar a página não remonta o documento, e o botão de download
    recebe os mesmos bytes.
    """

    metadados = json.loads(metadados_json) if metadados_json else []
    feicoes = json.loads(feicoes_json) if feicoes_json else []

    return gerar_parecer_docx(
        pergunta,
        resposta,
        metadados,
        perfil_analitico,
        feicoes or None,
        None
    )


def _renderizar_exportacao_parecer(mensagem, pergunta, chave):
    """Expander discreto com os dois downloads do parecer técnico.

    ``chave`` é o prefixo único (``session_id`` + mensagem), o mesmo dos
    demais widgets da resposta. O corpo do expander só é executado
    quando ele está aberto (``on_change="rerun"`` + ``.open``), então
    conversas longas não pagam a geração do Word em todo rerun.
    """

    resposta = str(mensagem.get("content") or "")

    if not resposta.strip():
        return

    painel = st.expander(
        t("parecer_expander"),
        expanded=False,
        key=f"parecer_{chave}",
        icon=":material/description:",
        on_change="rerun"
    )

    if not painel.open:
        return

    perfil = _perfil_da_mensagem(mensagem)
    metadados = _metadados_fontes_mensagem(mensagem)
    feicoes = [
        feicao
        for feicao in (mensagem.get("feicoes_espaciais") or [])
        if isinstance(feicao, dict)
    ]
    pergunta = _texto_curto(pergunta) or t("consulta_historico")

    st.caption(t("parecer_texto"))

    coluna_docx, coluna_md = st.columns(2, gap="small")

    with coluna_docx:
        try:
            conteudo_docx = _parecer_docx_cache(
                pergunta,
                resposta,
                json.dumps(
                    metadados,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str
                ),
                perfil,
                json.dumps(
                    feicoes,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str
                )
            )
        except RelatorioError as erro:
            st.warning(str(erro), title=t("word_indisponivel"))
        except Exception as erro:
            print("Falha ao gerar o parecer .docx:", repr(erro))
            st.error(t("parecer_erro_word"))
        else:
            st.download_button(
                t("baixar_parecer_docx"),
                data=conteudo_docx,
                file_name=nome_arquivo_parecer("docx"),
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                key=f"parecer_docx_{chave}",
                width="stretch",
                help=t("ajuda_parecer_docx")
            )

    with coluna_md:
        try:
            conteudo_md = gerar_parecer_markdown(
                pergunta,
                resposta,
                metadados,
                perfil,
                feicoes or None,
                None
            )
        except Exception as erro:
            print("Falha ao gerar o parecer .md:", repr(erro))
            st.error(t("parecer_erro_md"))
        else:
            st.download_button(
                t("baixar_relatorio_md"),
                data=conteudo_md,
                file_name=nome_arquivo_parecer("md"),
                mime="text/markdown",
                key=f"parecer_md_{chave}",
                width="stretch",
                help=t("ajuda_relatorio_md")
            )

    st.caption(
        tf(
            "parecer_rodape",
            perfil=rotulo_perfil(perfil),
            grupos=len(metadados),
            feicoes=len(feicoes),
        )
    )


def _renderizar_mensagem(mensagem, pergunta=""):
    """Renderiza uma mensagem do histórico, com fontes quando assistente.

    As chaves dos widgets derivam do ``session_id`` da conversa e da
    chave própria da mensagem (``_chave_widget``), portanto alternar
    entre conversas do histórico nunca repete uma chave. ``pergunta`` é
    o texto do usuário que originou a resposta, usado no cabeçalho do
    Parecer Técnico.
    """

    papel = mensagem.get("role", "assistant")

    with st.chat_message(
        papel,
        avatar=AVATAR_ASSISTENTE if papel == "assistant" else None
    ):
        st.markdown(mensagem.get("content", ""))

        if papel != "assistant":
            return

        if mensagem.get("fonte"):
            st.caption(
                _legenda_fonte(
                    mensagem["fonte"],
                    mensagem.get("roteamento")
                )
            )

        _renderizar_fontes(
            mensagem.get("roteamento") or {},
            mensagem.get("artigos_rigeo") or [],
            chave=_chave_widget(mensagem),
            busca_rigeo=mensagem.get("busca_rigeo") or {},
            estacoes_ana=mensagem.get("estacoes_ana") or [],
            web=mensagem.get("web") or {},
            openalex=mensagem.get("openalex") or {},
            usgs=mensagem.get("usgs") or {},
            intl_geo=mensagem.get("intl_geo") or {},
            geosgb=mensagem.get("geosgb") or {},
            anm=mensagem.get("anm") or {},
            macrostrat=mensagem.get("macrostrat") or {},
            siagas=mensagem.get("siagas") or {},
            geossit=mensagem.get("geossit") or {}
        )

        _renderizar_mapa_espacial(
            mensagem.get("feicoes_espaciais") or [],
            _chave_widget(mensagem)
        )

        _renderizar_exportacao_parecer(
            mensagem,
            pergunta,
            _chave_widget(mensagem)
        )


# ---------------------------------------------------------------------------
# Extração e exploração de dados tabulares
# ---------------------------------------------------------------------------

# Fontes cujos registros ficam guardados no histórico da conversa. A
# segunda posição é a chave da mensagem; a terceira, o rótulo exibido no
# seletor de tabelas. A ordem é a mesma usada no restante da interface.
FONTES_TABELAS_SESSAO = (
    ("ana", "estacoes_ana", "Estações ANA/HidroWeb"),
    ("sgb", "artigos_rigeo", "Acervo SGB/RIGeo"),
    ("web", "web", "Pesquisa na Web"),
    ("openalex", "openalex", "OpenAlex"),
    ("usgs", "usgs", "USGS ScienceBase"),
    ("intl_geo", "intl_geo", "Serviços Geológicos Internacionais"),
    ("geosgb", "geosgb", "GeoSGB"),
    ("anm", "anm", "ANM/SIGMINE"),
    ("macrostrat", "macrostrat", "Macrostrat"),
    ("siagas", "siagas", "SIAGAS/RIMAS"),
    ("geossit", "geossit", "INDE/GEOSSIT"),
)


def _chave_widget_dados(texto):
    """Gera uma chave de widget estável e sem acentos para o painel."""

    base = re.sub(r"[^A-Za-z0-9_]+", "_", str(texto or "")).strip("_").lower()

    return base or "tabela"


def _registros_da_mensagem(valor):
    """Obtém a lista de registros de um campo do histórico da conversa."""

    if isinstance(valor, list):
        return [item for item in valor if isinstance(item, dict)]

    if isinstance(valor, dict):
        return [
            item
            for item in (valor.get("registros") or [])
            if isinstance(item, dict)
        ]

    return []


def _metadados_tabelas_sessao(mensagens):
    """Consolida os registros tabulares guardados nas respostas da sessão.

    Percorre as mensagens do assistente (as únicas que guardam fontes) e
    devolve uma entrada por conector, já sem registros repetidos entre
    respostas. Nenhuma consulta é refeita: os dados vêm do histórico em
    ``st.session_state.mensagens``.
    """

    coletados = {
        chave: {
            "fonte": chave,
            "rotulo": rotulo,
            "registros": [],
            "vistos": set(),
        }
        for chave, _campo, rotulo in FONTES_TABELAS_SESSAO
    }

    for mensagem in mensagens or []:
        if mensagem.get("role") != "assistant":
            continue

        for chave, campo, _rotulo in FONTES_TABELAS_SESSAO:
            for registro in _registros_da_mensagem(mensagem.get(campo)):
                assinatura = chave_registro(registro)

                if assinatura in coletados[chave]["vistos"]:
                    continue

                coletados[chave]["vistos"].add(assinatura)
                coletados[chave]["registros"].append(registro)

    return [
        {
            "fonte": item["fonte"],
            "titulo": f"{item['rotulo']} (conversa atual)",
            "registros": item["registros"],
        }
        for item in coletados.values()
        if item["registros"]
    ]


@st.cache_data(show_spinner=False, ttl="30m", max_entries=100)
def _tabelas_markdown_cache(caminho, mtime_ns, tamanho):
    """Extrai as tabelas de um Markdown, por assinatura do arquivo."""

    return extrair_tabelas_documento(caminho)


def _extrair_tabelas_documentos(documentos):
    """Extrai as tabelas de todos os documentos indexados.

    Devolve ``(tabelas, falhas)``. A conversão para Markdown é a mesma
    do RAG (cache em ``data/cache_md``), então abrir o painel não
    reconverte um PDF que já foi indexado.
    """

    tabelas = []
    falhas = 0

    for documento in documentos or []:
        try:
            resultado = document_parser.converter_arquivo(Path(documento))
            caminho_md = resultado.caminho_md

            if not caminho_md:
                continue

            caminho_md = Path(caminho_md)

            if not caminho_md.is_file():
                continue

            assinatura = caminho_md.stat()
            tabelas.extend(
                _tabelas_markdown_cache(
                    str(caminho_md),
                    assinatura.st_mtime_ns,
                    assinatura.st_size,
                )
            )
        except Exception as erro:
            # Um documento problemático não pode esconder as tabelas dos
            # demais: a falha fica no console e é contada no painel.
            falhas += 1
            print("Falha ao extrair tabelas de", documento, repr(erro))

    return tabelas, falhas


def _metadados_espaciais(dados):
    """Entradas de fontes que podem render pontos no mapa do turno.

    Percorre o contrato de ``responder`` (``dados["ana"]``,
    ``dados["siagas"]`` etc.) e mantém apenas as fontes com registros;
    a chave vira o identificador de camada em
    ``services.spatial_parser``.
    """

    entradas = []

    for chave, valor in (dados or {}).items():
        if not isinstance(valor, dict):
            continue

        registros = valor.get("registros") or []

        if not registros:
            continue

        entradas.append({
            "fonte": chave,
            "titulo": valor.get("fonte") or chave,
            "registros": registros,
        })

    return entradas


@st.cache_data(show_spinner=False, ttl="30m", max_entries=20)
def _tabelas_espaciais_cache(assinaturas):
    """Extrai (uma vez por assinatura) as tabelas dos documentos locais."""

    caminhos = [Path(caminho) for caminho, _mtime, _tamanho in assinaturas]
    tabelas, _falhas = _extrair_tabelas_documentos(caminhos)

    return tabelas


def _tabelas_espaciais_documentos(documentos):
    """Tabelas dos documentos indexados, para o mapa espacial.

    A extração é a mesma do painel de dados e fica em cache pela
    assinatura de cada arquivo (mtime + tamanho): a primeira pergunta
    paga a conversão uma vez e as seguintes reaproveitam o resultado.
    Falha de leitura não pode esconder a resposta, então o mapa segue
    apenas com as fontes externas e o texto.
    """

    assinaturas = []

    for documento in documentos or []:
        caminho = Path(documento)

        try:
            informacao = caminho.stat()
        except OSError:
            continue

        assinaturas.append(
            (str(caminho), informacao.st_mtime_ns, informacao.st_size)
        )

    if not assinaturas:
        return []

    try:
        return _tabelas_espaciais_cache(tuple(assinaturas))
    except Exception as erro:
        print("Falha ao extrair tabelas para o mapa:", repr(erro))
        return []


def _consolidar_feicoes_turno(resposta, dados, documentos):
    """Lista de feições espaciais de uma resposta recém-gerada.

    Reúne metadados das APIs, tabelas dos documentos locais e o próprio
    texto da resposta. Qualquer falha no módulo espacial é contida aqui:
    a resposta ao usuário nunca é perdida por causa do mapa.
    """

    try:
        return consolidar_pontos_mapa(
            resposta,
            _metadados_espaciais(dados),
            _tabelas_espaciais_documentos(documentos),
        )
    except Exception as erro:
        print("Falha ao consolidar os pontos do mapa:", repr(erro))
        return []


def _rotulo_tabela_dados(tabelas, indice):
    """Rótulo do seletor: título, origem, página e dimensões."""

    tabela = tabelas[indice]
    pagina = (
        f"p. {tabela['pagina']}" if tabela.get("pagina") else "sem página"
    )
    df_bruto = tabela["df_bruto"]

    return (
        f"{indice + 1}. {tabela['titulo']} · {tabela['origem']} · "
        f"{pagina} · {len(df_bruto)} linha(s) × "
        f"{len(df_bruto.columns)} coluna(s)"
    )


def _renderizar_resumo_estatistico(df_limpo, df_bruto):
    """Resumo rápido: estatística das colunas numéricas, nulos e únicos."""

    numericas = df_limpo.select_dtypes(include="number")

    if not numericas.empty:
        descricao = numericas.describe().transpose()
        descricao.index.name = t("resumo_coluna")
        descricao = descricao.rename(
            columns={
                "count": t("resumo_contagem"),
                "mean": t("resumo_media"),
                "std": t("resumo_desvio"),
                "min": t("resumo_minimo"),
                "25%": "25%",
                "50%": t("resumo_mediana"),
                "75%": "75%",
                "max": t("resumo_maximo"),
            }
        )

        st.dataframe(
            descricao,
            width="stretch",
            alt=t("resumo_numerico_alt"),
        )
    else:
        st.caption(t("dados_sem_coluna_numerica"))

    resumo = pd.DataFrame(
        {
            t("resumo_tipo"): df_limpo.dtypes.astype(str).to_numpy(),
            t("resumo_nulos"): df_limpo.isna().sum().to_numpy(),
            t("resumo_unicos"): df_limpo.nunique(dropna=True).to_numpy(),
        },
        index=df_limpo.columns,
    )
    resumo.index.name = t("resumo_coluna")

    st.caption(
        tf(
            "resumo_linhas_colunas",
            linhas=len(df_bruto),
            colunas=len(df_limpo.columns),
        )
    )
    st.dataframe(
        resumo,
        width="stretch",
        alt=t("resumo_colunas_alt"),
    )


def _renderizar_exportacao_dados(tabela, df_limpo, df_bruto, indice):
    """Botões de exportação em memória: CSV PT-BR e Excel com metadados."""

    tabela_exportavel = dict(tabela)
    tabela_exportavel["df_limpo"] = df_limpo
    tabela_exportavel["df_bruto"] = df_bruto
    chave = _chave_widget_dados(tabela.get("id") or indice)

    st.caption(t("exportacao_caption"))

    colunas = st.columns(2)

    with colunas[0]:
        st.download_button(
            t("baixar_csv"),
            data=gerar_csv(tabela_exportavel),
            file_name=nome_arquivo_tabela(tabela_exportavel, "csv"),
            mime="text/csv",
            icon=":material/download:",
            width="stretch",
            key=f"dados_csv_{chave}",
            help=t("ajuda_csv_dados"),
        )

    with colunas[1]:
        try:
            conteudo_excel = gerar_excel(tabela_exportavel)
        except Exception as erro:
            st.warning(
                str(erro),
                title=t("excel_indisponivel"),
                icon=":material/error:",
            )
        else:
            st.download_button(
                t("baixar_excel"),
                data=conteudo_excel,
                file_name=nome_arquivo_tabela(tabela_exportavel, "xlsx"),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                icon=":material/download:",
                width="stretch",
                key=f"dados_excel_{chave}",
                help=t("ajuda_excel"),
            )


def _renderizar_painel_dados(documentos):
    """Painel de extração, exploração e exportação de tabelas.

    Aparece quando há documentos indexados ou registros tabulares nas
    respostas da conversa. O conteúdo só é calculado quando o expander
    está aberto; ``on_change="rerun"`` mantém ``.open`` atualizado sem
    extrair tabelas em toda pergunta.
    """

    metadados_sessao = _metadados_tabelas_sessao(
        st.session_state.get("mensagens")
    )

    if not documentos and not metadados_sessao:
        return

    painel = st.expander(
        t("dados_expander"),
        expanded=False,
        key="dados_painel",
        on_change="rerun",
    )

    if not painel.open:
        return

    with painel:
        st.caption(t("dados_caption"))

        tabelas_documentos = []
        falhas_documentos = 0

        if documentos:
            with st.spinner(t("dados_spinner")):
                tabelas_documentos, falhas_documentos = (
                    _extrair_tabelas_documentos(documentos)
                )

        tabelas_sessao = consolidar_dados_sessao(metadados_sessao)
        tabelas = tabelas_documentos + tabelas_sessao

        if falhas_documentos:
            st.caption(
                tf("dados_falhas_leitura", n=falhas_documentos)
            )

        if not tabelas:
            st.info(
                t("dados_sem_tabelas"),
                icon=":material/table_off:",
            )
            return

        st.caption(
            tf(
                "dados_contagem",
                documentos=len(tabelas_documentos),
                sessao=len(tabelas_sessao),
            )
        )

        opcoes = list(range(len(tabelas)))

        if st.session_state.get("dados_tabela_indice") not in opcoes:
            st.session_state["dados_tabela_indice"] = 0

        indice = st.selectbox(
            t("dados_tabela_rotulo"),
            opcoes,
            format_func=lambda posicao: _rotulo_tabela_dados(tabelas, posicao),
            key="dados_tabela_indice",
        )

        tabela = tabelas[indice]
        df_bruto = tabela["df_bruto"]
        df_limpo = tabela["df_limpo"]

        st.caption(
            tf(
                "dados_origem",
                titulo=tabela["titulo"],
                origem=tabela["origem"],
                pagina=tabela.get("pagina") or "—",
                linhas=len(df_bruto),
                colunas=len(df_bruto.columns),
            )
        )

        if tabela.get("unidades"):
            st.caption(
                tf(
                    "dados_unidades",
                    unidades=" · ".join(
                        f"{coluna}: {unidade}"
                        for coluna, unidade
                        in tabela["unidades"].items()
                    ),
                )
            )

        for observacao in tabela.get("observacoes") or []:
            st.caption(observacao)

        rotulo_tipados = t("dados_tipados")
        rotulo_brutos = t("dados_brutos")
        rotulo_sem_busca = t("dados_sem_busca")

        modo_visualizacao = st.segmented_control(
            t("dados_visualizacao"),
            [rotulo_tipados, rotulo_brutos],
            default=rotulo_tipados,
            key="dados_modo_visualizacao",
        ) or rotulo_tipados

        df_visual = (
            df_limpo
            if modo_visualizacao == rotulo_tipados
            else df_bruto
        )

        colunas_busca = [
            rotulo_sem_busca,
            *[str(c) for c in df_visual.columns],
        ]

        if st.session_state.get("dados_coluna_busca") not in colunas_busca:
            st.session_state["dados_coluna_busca"] = rotulo_sem_busca

        colunas_filtro = st.columns(2)

        with colunas_filtro[0]:
            coluna_busca = st.selectbox(
                t("dados_busca_coluna"),
                colunas_busca,
                key="dados_coluna_busca",
            )

        termo_busca = ""

        if coluna_busca != rotulo_sem_busca:
            with colunas_filtro[1]:
                termo_busca = st.text_input(
                    t("dados_texto_procurado"),
                    key="dados_termo_busca",
                    placeholder=t("dados_placeholder_busca"),
                )

        colunas_numericas = [
            str(coluna)
            for coluna in df_limpo.columns
            if pd.api.types.is_numeric_dtype(df_limpo[coluna])
        ]

        usar_faixa = st.toggle(
            t("dados_filtrar_faixa"),
            key="dados_faixa_ativa",
            disabled=not colunas_numericas,
            help=t("dados_ajuda_faixa"),
        )

        coluna_numerica = None
        faixa = None
        valor_unico = None

        if usar_faixa and colunas_numericas:
            if st.session_state.get("dados_coluna_numerica") not in colunas_numericas:
                st.session_state["dados_coluna_numerica"] = colunas_numericas[0]

            coluna_numerica = st.selectbox(
                t("dados_coluna_numerica"),
                colunas_numericas,
                key="dados_coluna_numerica",
            )

            serie_numerica = pd.to_numeric(
                df_limpo[coluna_numerica], errors="coerce"
            ).dropna()

            if serie_numerica.empty:
                st.caption(t("dados_sem_numericos"))
                coluna_numerica = None
            else:
                minimo = float(serie_numerica.min())
                maximo = float(serie_numerica.max())

                if minimo == maximo:
                    valor_unico = minimo
                    st.caption(
                        tf("dados_valor_unico", valor=f"{minimo:g}")
                    )
                else:
                    passo = max((maximo - minimo) / 100, 1e-9)
                    chave_faixa = (
                        f"dados_faixa_{indice}_"
                        f"{_chave_widget_dados(coluna_numerica)}_"
                        f"{colunas_numericas.index(coluna_numerica)}"
                    )
                    faixa = st.slider(
                        t("dados_faixa"),
                        min_value=minimo,
                        max_value=maximo,
                        value=(minimo, maximo),
                        step=passo,
                        key=chave_faixa,
                    )

        mascara = pd.Series(True, index=df_limpo.index)

        if coluna_numerica is not None:
            if faixa is not None:
                mascara &= (
                    df_limpo[coluna_numerica]
                    .between(faixa[0], faixa[1])
                    .fillna(False)
                )
            elif valor_unico is not None:
                mascara &= (
                    (df_limpo[coluna_numerica] == valor_unico)
                    .fillna(False)
                )

        if coluna_busca != rotulo_sem_busca and termo_busca.strip():
            filtro_texto = (
                df_visual[coluna_busca]
                .astype("string")
                .str.contains(
                    termo_busca.strip(),
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            mascara &= filtro_texto.reindex(
                df_limpo.index, fill_value=False
            )

        df_filtrado_visual = df_visual.loc[mascara]
        df_filtrado_limpo = df_limpo.loc[mascara]
        df_filtrado_bruto = df_bruto.loc[mascara]

        configuracao_colunas = {}

        for coluna_data in tabela.get("colunas_data") or []:
            if coluna_data in df_filtrado_visual.columns:
                configuracao_colunas[coluna_data] = (
                    st.column_config.DatetimeColumn(
                        coluna_data, format="DD/MM/YYYY"
                    )
                )

        st.dataframe(
            df_filtrado_visual,
            width="stretch",
            hide_index=True,
            column_config=configuracao_colunas or None,
            alt=f"Tabela extraída: {tabela['titulo']}",
        )

        st.caption(
            f"{len(df_filtrado_visual)} de {len(df_visual)} linha(s) "
            f"exibida(s) · {len(df_filtrado_visual.columns)} coluna(s)."
        )

        with st.expander(
            t("resumo_rapido_expander"),
            expanded=False,
        ):
            _renderizar_resumo_estatistico(
                df_filtrado_limpo, df_filtrado_bruto
            )

        _renderizar_exportacao_dados(
            tabela,
            df_filtrado_limpo,
            df_filtrado_bruto,
            indice,
        )


# ---------------------------------------------------------------------------
# Modelos do Ollama
# ---------------------------------------------------------------------------

# Lista os modelos instalados no Ollama. Se o serviço estiver offline, a
# função devolve apenas o modelo padrão e a interface continua abrindo.
modelos_disponiveis = listar_modelos_locais()

# Uma escolha antiga pode não existir mais na lista (modelo removido do
# Ollama). Nesse caso o estado é limpo antes de criar o widget.
if (
    "modelo_ollama" in st.session_state
    and st.session_state.modelo_ollama not in modelos_disponiveis
):
    del st.session_state["modelo_ollama"]

indice_modelo_padrao = (
    modelos_disponiveis.index(OLLAMA_MODEL)
    if OLLAMA_MODEL in modelos_disponiveis
    else 0
)


# ---------------------------------------------------------------------------
# Barra lateral: base documental, histórico, fontes e ajustes
# ---------------------------------------------------------------------------

def _encerrar_servidor_streamlit():
    """Encerra o servidor a pedido do usuário (botão da barra lateral).

    Usa ``Runtime.instance().stop()``, seguro a partir da thread do
    script, para desligar o servidor de forma ordenada: o processo do
    servidor termina e o launcher (que o espera) encerra em seguida,
    fechando o Job Object no Windows. Um ``Timer`` de segurança garante
    a saída do processo caso a API interna do Streamlit mude.
    """

    parou = False

    try:
        from streamlit.runtime import Runtime

        Runtime.instance().stop()
        parou = True
    except Exception:  # noqa: BLE001 - API interna indisponível
        parou = False

    def _sair_a_forca():
        """Sai do processo do servidor depois de desenhar o aviso."""

        os._exit(0)

    if parou:
        # Rede de segurança: se o runtime não concluir o desligamento, o
        # processo termina de qualquer forma (sem deixar órfãos). O timer
        # é daemon para não atrasar o encerramento normal.
        segundos = 5.0
    else:
        segundos = 0.5

    timer = threading.Timer(segundos, _sair_a_forca)
    timer.daemon = True
    timer.start()

    return parou


with st.sidebar:
    # -- 0. Seletor de idioma (topo absoluto da barra lateral) -----------
    # Duas colunas iguais com os botões de bandeira. O botão do idioma
    # ativo fica primário; o clique troca a chave ``idioma`` e força um
    # rerun, que redesenha a interface inteira no idioma escolhido.
    idioma = st.session_state.get("idioma", IDIOMA_PADRAO)

    col_pt, col_en = st.sidebar.columns(2)

    with col_pt:
        if st.button(
            ROTULOS_IDIOMA["pt"],
            key="idioma_pt",
            type="primary" if idioma == "pt" else "secondary",
            width="stretch",
            help=NOMES_IDIOMA["pt"],
        ):
            st.session_state["idioma"] = "pt"
            st.rerun()

    with col_en:
        if st.button(
            ROTULOS_IDIOMA["en"],
            key="idioma_en",
            type="primary" if idioma == "en" else "secondary",
            width="stretch",
            help=NOMES_IDIOMA["en"],
        ):
            st.session_state["idioma"] = "en"
            st.rerun()

    st.divider()

    # -- 1. Base de documentos (Upload) ----------------------------------
    # A seção começa logo após o seletor de idioma: o antigo cabeçalho
    # "Conversa atual: ..." saiu, porque repetia a conversa aberta
    # (destacada na lista de histórico) e consumia a primeira linha da
    # barra lateral. O botão "Novo Chat" vive no rodapé da área
    # principal, ao lado do campo de mensagem.
    st.subheader(t("secao_documentos"))
    st.caption(t("texto_documentos"))

    if not document_parser.ocr_disponivel():
        st.caption(t("ocr_indisponivel"))

    arquivos_enviados = st.file_uploader(
        t("rotulo_upload"),
        type=["txt", "md", "pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if arquivos_enviados and st.button(
        t("botao_salvar_documentos"),
        width="stretch"
    ):
        salvos = []
        # Arquivos recusados por falta de texto útil (PDF escaneado sem
        # imagem legível, arquivo vazio): cada um vira um aviso explícito,
        # para o usuário não achar que um arquivo sem texto foi indexado.
        sem_texto = []
        # Falhas que não são de conteúdo (dependência ausente, nome
        # inválido): aparecem como erro, fora do status de progresso.
        sem_conversao = []
        total_arquivos = len(arquivos_enviados)

        with st.status(
            t("status_convertendo"),
            expanded=True
        ) as status:
            barra = st.progress(
                0.0,
                text=tf(
                    "progresso_convertidos",
                    feitos=0,
                    total=total_arquivos,
                )
            )

            for indice, arquivo in enumerate(arquivos_enviados, start=1):
                st.write(f"**{arquivo.name}**")

                def ao_progredir(
                    fracao,
                    texto,
                    indice=indice,
                    nome=arquivo.name,
                ):
                    """Atualiza a barra enquanto as páginas são lidas."""

                    progresso = (
                        (indice - 1) + max(0.0, min(1.0, fracao))
                    ) / total_arquivos

                    barra.progress(
                        min(1.0, progresso),
                        text=f"{nome} · {texto}",
                    )

                try:
                    documento = salvar_documento(
                        arquivo.name,
                        arquivo.getvalue(),
                        ao_progredir=ao_progredir,
                    )
                except DocumentoInvalidoError as erro:
                    avaliacao = getattr(erro, "avaliacao", None)

                    if avaliacao and not avaliacao.get("valido"):
                        sem_texto.append({
                            "documento": arquivo.name,
                            "mensagem": str(erro),
                        })
                    else:
                        sem_conversao.append({
                            "documento": arquivo.name,
                            "mensagem": str(erro),
                        })
                    continue

                salvos.append(documento)

                detalhe = tf(
                    "detalhe_paginas",
                    paginas=documento.paginas,
                )

                if documento.paginas_ocr:
                    detalhe += tf(
                        "detalhe_ocr",
                        paginas=documento.paginas_ocr,
                    )

                if documento.do_cache:
                    detalhe += t("detalhe_cache")

                st.caption(f"{detalhe}.")

            barra.progress(
                1.0,
                text=tf(
                    "progresso_processados",
                    total=total_arquivos,
                )
            )

        # ``status.update`` fica fora do bloco: dentro do ``with`` o
        # Streamlit força o estado "complete" ao sair.
        status.update(
            label=tf(
                "status_convertidos_resumo",
                salvos=len(salvos),
                total=total_arquivos,
            ),
            state="complete" if len(salvos) == total_arquivos else "error",
            expanded=False,
        )

        if salvos:
            limpar_cache()
            _avaliacao_cacheada.clear()

            total_ocr = sum(item.paginas_ocr for item in salvos)
            total_paginas = sum(item.paginas for item in salvos)
            reaproveitados = sum(1 for item in salvos if item.do_cache)

            st.success(
                tf("sucesso_indexados", n=len(salvos))
            )

            if total_ocr:
                st.caption(
                    tf(
                        "ocr_aplicado",
                        ocr=total_ocr,
                        total=total_paginas,
                    )
                )
            else:
                st.caption(tf("sem_ocr", total=total_paginas))

            if reaproveitados:
                st.caption(
                    tf("cache_reaproveitado", n=reaproveitados)
                )

        for item in sem_conversao:
            st.error(
                item["mensagem"],
                title=t("titulo_arquivo_nao_indexado"),
                icon=":material/error:"
            )

        for item in sem_texto:
            st.warning(
                item["mensagem"],
                title=t("titulo_arquivo_nao_indexado"),
                icon=":material/scan_delete:"
            )

    documentos = listar_documentos()

    # Avaliação única por arquivo: a lista e os avisos abaixo usam o
    # mesmo resultado, sem converter o mesmo PDF duas vezes no rerun.
    avaliacoes = {
        documento: _avaliar_documento(documento)
        for documento in documentos
    }

    # Lista o que está realmente indexado em ``data/docs``: cada arquivo
    # com ícone e selo de status, em linha compacta.
    if documentos:
        st.caption(
            tf("documentos_contagem", n=len(documentos))
        )
        _renderizar_documentos_sidebar(
            documentos[:LIMITE_DOCUMENTOS_VISIVEIS],
            avaliacoes,
        )

        excedente = len(documentos) - LIMITE_DOCUMENTOS_VISIVEIS

        if excedente > 0:
            st.caption(tf("documentos_excedente", n=excedente))

        # Exclusão em massa: remove todos os arquivos locais e os caches
        # de uma vez. O ``st.rerun()`` refaz a listagem e o rodapé, que
        # passa a exibir ``Documentos indexados: 0``.
        if st.button(
            t("botao_limpar_base"),
            key="limpar_base_documentos",
            type="secondary",
            width="stretch",
            help=t("ajuda_limpar_base"),
        ):
            _limpar_base_documentos()
            st.rerun()

        # Blindagem também para o que já está no disco: um PDF escaneado
        # gravado manualmente em data/docs não pode ser tratado como
        # indexado silenciosamente.
        for aviso in descrever_extracoes(documentos, avaliacoes):
            st.warning(
                aviso["mensagem"],
                title=t("titulo_arquivo_sem_texto"),
                icon=":material/scan_delete:"
            )
    else:
        st.caption(t("documentos_vazio"))

    _exibir_aviso_documentos()

    # -- 2. Histórico de conversas + exclusão em lote --------------------
    # Um único divisor compacto separa a base documental do histórico: o
    # CSS da barra lateral zera o miolo do contêiner e fixa a margem do
    # ``<hr>`` em 0.25rem, sem linha em branco extra entre as duas seções.
    st.divider()
    total_conversas = _renderizar_historico()
    _exibir_aviso_historico()

    # A exclusão em lote fica imediatamente abaixo da lista que ela
    # apaga, e não no rodapé da barra lateral. O primeiro clique só arma
    # a confirmação (chave no estado da sessão) e a exclusão de fato
    # acontece no segundo clique; assim um clique acidental não apaga o
    # histórico. Os documentos de data/docs nunca são tocados.
    if st.session_state.get("confirmar_apagar_tudo"):
        st.warning(
            t("confirmar_apagar_texto"),
            title=t("confirmar_apagar_titulo")
        )

        if st.button(
            t("botao_apagar_confirmado"),
            key="apagar_todo_historico_confirmado",
            type="primary",
            width="stretch",
            help=t("ajuda_apagar_confirmado"),
            on_click=_apagar_todo_historico
        ):
            st.rerun()

        if st.button(
            t("botao_cancelar"),
            key="cancelar_apagar_tudo",
            width="stretch",
            help=t("ajuda_cancelar"),
            on_click=_cancelar_apagar_tudo
        ):
            st.rerun()
    elif st.button(
        t("botao_apagar_tudo"),
        key="apagar_todo_historico",
        type="secondary",
        width="stretch",
        disabled=not total_conversas,
        help=t("ajuda_apagar_tudo")
    ):
        st.session_state["confirmar_apagar_tudo"] = True
        st.rerun()

    st.divider()

    # -- 3. Fontes de dados ativas ---------------------------------------
    # Um toggle por fonte, agrupados por domínio. O roteador consulta
    # exatamente o que estiver ligado aqui: a classificação de intenção
    # só otimiza os filtros (município, UF, substância e rio).
    st.subheader(t("secao_fontes"))
    st.caption(t("texto_fontes"))

    local_docs_enabled = st.toggle(
        t("toggle_local_docs"),
        value=True,
        key="local_docs_enabled",
        help=t("ajuda_local_docs")
    )

    # Opção da Web: fica logo abaixo do interruptor que a habilita.
    web_apenas_tecnico = False
    conectores_ativos = {}
    intl_geo_regioes = [REGIAO_TODAS]

    for grupo in GRUPOS_CONECTORES:
        st.caption(f"**{t(grupo['titulo_i18n'])}**")

        for chave in grupo["chaves"]:
            conector = CONECTORES_POR_CHAVE[chave]

            conectores_ativos[chave] = st.toggle(
                t(conector["rotulo_i18n"]),
                value=conector["padrao"],
                key=chave,
                help=t(conector["ajuda_i18n"]),
            )

            if not conectores_ativos[chave]:
                continue

            # Dica ou opção condicional de cada conector, logo abaixo do
            # interruptor correspondente.
            if chave == "web_search_enabled":
                web_apenas_tecnico = st.checkbox(
                    t("web_tecnicos"),
                    value=False,
                    key="web_apenas_tecnico",
                    help=t("ajuda_web_tecnicos")
                )

                disponivel_web, motivo_web = web_disponivel()

                if not disponivel_web:
                    st.caption(motivo_web)
            elif chave == "siagas_enabled":
                st.caption(t("dica_siagas"))
            elif chave == "geosgb_enabled":
                st.caption(t("dica_geosgb"))
            elif chave == "anm_enabled":
                st.caption(t("dica_anm"))
            elif chave == "macrostrat_enabled":
                st.caption(t("dica_macrostrat"))
            elif chave == "geossit_enabled":
                st.caption(t("dica_geossit"))
            elif chave == "intl_geo_enabled":
                # Exibição condicional: o seletor só existe enquanto o
                # grupo unificado estiver ligado, mantendo a barra
                # lateral compacta quando ele está desligado.
                #
                # As opções exibidas são os rótulos do idioma ativo, mas
                # a lista devolvida ao backend é sempre convertida de
                # volta para a opção canônica em português — é ela que
                # os conectores comparam. O bloco abaixo também normaliza
                # o estado da sessão ao trocar de idioma, para a seleção
                # anterior continuar válida.
                opcoes_regioes = [
                    rotulo_regiao(regiao)
                    for regiao in OPCOES_REGIOES_INTERNACIONAIS
                ]

                selecao_atual = st.session_state.get(
                    "intl_geo_regioes"
                )

                if selecao_atual is None:
                    selecao_atual = st.session_state.get(
                        "intl_geo_regioes_padrao",
                        [REGIAO_TODAS],
                    )

                selecao_canonica = [
                    regiao_do_rotulo(item) or item
                    for item in selecao_atual
                ]

                st.session_state["intl_geo_regioes"] = [
                    rotulo_regiao(regiao)
                    for regiao in selecao_canonica
                    if regiao in OPCOES_REGIOES_INTERNACIONAIS
                ] or [rotulo_regiao(REGIAO_TODAS)]

                selecionadas_exibidas = st.multiselect(
                    t("onde_buscar"),
                    opcoes_regioes,
                    key="intl_geo_regioes",
                    placeholder=t("placeholder_regioes"),
                    help=t("ajuda_regioes"),
                )

                intl_geo_regioes = [
                    regiao_do_rotulo(item) or item
                    for item in selecionadas_exibidas
                ]

    # Os nomes abaixo são os mesmos usados pelo roteador, pelos badges e
    # por ``responder(...)``.
    rigeo_enabled = conectores_ativos["rigeo_enabled"]
    ana_enabled = conectores_ativos["ana_enabled"]
    web_search_enabled = conectores_ativos["web_search_enabled"]
    siagas_enabled = conectores_ativos["siagas_enabled"]
    geosgb_enabled = conectores_ativos["geosgb_enabled"]
    anm_enabled = conectores_ativos["anm_enabled"]
    macrostrat_enabled = conectores_ativos["macrostrat_enabled"]
    geossit_enabled = conectores_ativos["geossit_enabled"]
    openalex_enabled = conectores_ativos["openalex_enabled"]
    intl_ativo = conectores_ativos["intl_geo_enabled"]
    intl_geo_enabled = intl_ativo

    # -- 4. Perfil analítico e system prompt: também fora dos ajustes ----
    # O modo de análise preenche o texto base com o bloco do perfil; o
    # editor continua livre e o texto ativo aparece na prévia abaixo.
    st.divider()
    st.subheader(t("secao_perfil"))

    if erro_prompt_base:
        st.error(erro_prompt_base)

    # O seletor exibe os nomes traduzidos, mas a chave de sessão guarda
    # sempre o nome canônico em português (é o valor usado no prompt). O
    # bloco normaliza a chave ao trocar de idioma e restaura o padrão se
    # uma sessão antiga trouxer um modo que não existe mais.
    perfis_disponiveis = list(PERFIS_ANALITICOS)

    perfil_sessao = st.session_state.get(
        "perfil_analitico",
        PERFIL_PADRAO,
    )

    if perfil_sessao in PERFIS_ANALITICOS:
        perfil_canonico = perfil_sessao
    else:
        perfil_canonico = (
            perfil_do_rotulo(perfil_sessao) or PERFIL_PADRAO
        )

    if perfil_canonico not in PERFIS_ANALITICOS:
        perfil_canonico = PERFIL_PADRAO

    st.session_state["perfil_analitico"] = rotulo_perfil(perfil_canonico)

    perfil_selecionado = st.selectbox(
        t("modo_analise"),
        [rotulo_perfil(perfil) for perfil in perfis_disponiveis],
        key="perfil_analitico",
        on_change=_aplicar_perfil_analitico,
        help=t("ajuda_modo_analise")
    )

    perfil_analitico = (
        perfil_do_rotulo(perfil_selecionado) or PERFIL_PADRAO
    )

    # A descrição acompanha o idioma ativo; o valor salvo do perfil
    # continua sendo o nome canônico em português.
    descricao_perfil_ativo = descricao_perfil(
        perfil_analitico,
        padrao=dados_do_perfil(perfil_analitico)["descricao"],
    )

    st.caption(descricao_perfil_ativo)

    if perfil_analitico == PERFIL_PERSONALIZADO:
        st.caption(t("perfil_personalizado_texto"))

    editar_prompt = st.toggle(
        t("editar_prompt"),
        key="editor_prompt_aberto",
        help=t("ajuda_editar_prompt")
    )

    if editar_prompt:
        st.caption(t("texto_edicao"))

        # ``persist_state="session"`` é essencial aqui: sem ele, fechar o
        # editor descartaria o texto digitado, e o perfil selecionado
        # também perderia o bloco aplicado.
        st.text_area(
            t("rotulo_prompt_ativo"),
            key="prompt_sistema_editado",
            height=200,
            persist_state="session",
            help=t("ajuda_prompt_ativo")
        )

        st.button(
            t("botao_salvar_padrao"),
            key="salvar_prompt_padrao",
            width="stretch",
            on_click=_salvar_prompt_padrao
        )

        st.button(
            t("botao_restaurar"),
            key="restaurar_prompt_original",
            width="stretch",
            on_click=_restaurar_prompt_original
        )

    else:
        # Com o editor fechado, a prévia mantém o prompt ativo acessível
        # sem ocupar a altura de uma caixa de edição.
        prompt_ativo = st.session_state.get(
            "prompt_sistema_editado",
            ""
        )

        if prompt_ativo:
            with st.expander(t("expander_ver_prompt"), expanded=False):
                st.caption(
                    tf("texto_ver_prompt", n=len(prompt_ativo))
                )
                st.code(prompt_ativo, language=None, height=240)

    _exibir_aviso_prompt()

    st.divider()

    # -- 5. Configurações avançadas e rodapé -----------------------------
    # Só infraestrutura e busca: fontes e system prompt ficam nas seções
    # visíveis acima.
    with st.expander(t("config_avancadas"), expanded=False):
        modelo_ollama = st.selectbox(
            t("modelo_ollama"),
            modelos_disponiveis,
            index=indice_modelo_padrao,
            key="modelo_ollama",
            help=t("ajuda_modelo_ollama")
        )

        limite_rigeo = st.slider(
            t("limite_rigeo"),
            min_value=3,
            max_value=10,
            value=5,
            step=1,
            help=t("ajuda_limite_rigeo")
        )

        comunidade_rigeo = st.selectbox(
            t("comunidade_rigeo"),
            [COMUNIDADE_TODAS, *COMUNIDADES_RIGEO],
            help=t("ajuda_comunidade_rigeo")
        )

        # Extração opcional dos termos de busca pelo Ollama. Desligada, a
        # remoção de stopwords e palavras conversacionais (a via rápida e
        # determinística) é a única usada.
        termos_via_ollama = st.toggle(
            t("refinar_termos"),
            value=False,
            key="termos_via_ollama",
            help=t("ajuda_refinar_termos")
        )

    # Rodapé apenas informativo: sem botões duplicados, só o estado do
    # modelo e da base documental. As duas informações cabem em uma única
    # linha, o que encurta a barra lateral e dispensa um segundo caption.
    st.divider()
    st.caption(
        tf(
            "rodape_modelo",
            modelo=modelo_ollama,
            documentos=len(documentos),
        )
    )

    # Ação discreta de encerramento: libera a porta e fecha o servidor
    # (e o launcher, que o espera). O histórico já salvo é preservado.
    if st.button(
        t("encerrar_servidor"),
        key="encerrar_servidor",
        width="stretch",
        help=t("ajuda_encerrar_servidor"),
    ):
        _encerrar_servidor_streamlit()
        st.info(t("aviso_encerrando_servidor"))
        st.stop()


# Texto atual da caixa de edição, mesmo que o editor esteja fechado.
prompt_editado = st.session_state.get("prompt_sistema_editado", "")

# O prompt está "editado" quando o texto ativo difere do que o modo de
# análise produziria a partir do arquivo base. O bloco de perfil já
# gravado no arquivo é retirado antes da comparação, para que salvar um
# perfil especializado não apareça como edição manual. Serve para o badge
# do cabeçalho indicar prompt customizado.
prompt_alterado = (
    bool(prompt_editado.strip())
    and prompt_editado.strip()
    != montar_prompt_do_perfil(
        perfil_analitico,
        remover_blocos_de_perfil(prompt_base_padrao)
    ).strip()
)

perfil_ativo = dados_do_perfil(perfil_analitico)

# Rótulos compactos das regiões internacionais para o badge do cabeçalho.
# O seletor usa os rótulos longos; aqui só cabe a versão curta. Em inglês,
# ``utils.i18n.rotulo_curto_regiao`` devolve a forma curta traduzida.
ROTULOS_CURTOS_REGIOES = {
    REGIAO_TODAS: "Todas",
    OPCOES_REGIOES_INTERNACIONAIS[1]: "OneGeology",
    OPCOES_REGIOES_INTERNACIONAIS[2]: "EUA",
    OPCOES_REGIOES_INTERNACIONAIS[3]: "Canadá",
    OPCOES_REGIOES_INTERNACIONAIS[4]: "UE",
    OPCOES_REGIOES_INTERNACIONAIS[5]: "Austrália",
    OPCOES_REGIOES_INTERNACIONAIS[6]: "Japão",
    OPCOES_REGIOES_INTERNACIONAIS[7]: "Nova Zelândia",
    OPCOES_REGIOES_INTERNACIONAIS[8]: "África",
    OPCOES_REGIOES_INTERNACIONAIS[9]: "Arábia Saudita",
    OPCOES_REGIOES_INTERNACIONAIS[10]: "Índia",
}


def _rotulo_curto_regiao(regiao):
    """Rótulo curto da região no idioma ativo.

    Em português usa o mapa compacto acima; em inglês delega a
    ``utils.i18n``, que mantém um mapa equivalente.
    """

    if st.session_state.get("idioma") == "en":
        return rotulo_curto_regiao(regiao)

    return ROTULOS_CURTOS_REGIOES.get(regiao, regiao)


# ---------------------------------------------------------------------------
# Cabeçalho compacto com badges de fontes, perfil analítico e Ollama
# ---------------------------------------------------------------------------

with st.container(
    key="cabecalho",
    horizontal=True,
    vertical_alignment="center",
    gap="small"
):
    st.markdown(f"#### ⛏️ {t('titulo')}")

    # Base documental local: reflete o toggle "📄 Base Documental Local"
    # da barra lateral, que substituiu o antigo seletor "Fonte de
    # informação".
    st.badge(
        t("badge_base_local")
        if local_docs_enabled
        else t("badge_base_local_off"),
        color=CORES_FONTE["Base local"] if local_docs_enabled else "gray",
        help=(
            t("ajuda_base_local")
            if local_docs_enabled
            else t("ajuda_base_local_off")
        )
    )

    # APIs externas ativas: a badge confirma o que a seção "Fontes de
    # Dados Ativas" deixou ligado, sem precisar abrir a barra lateral.
    # A sequência é a mesma dos GRUPOS_CONECTORES da barra lateral.
    if rigeo_enabled:
        st.badge(
            "🏛️ RIGeo",
            color="orange",
            help=t("ajuda_rigeo")
        )
    else:
        st.badge(
            t("badge_rigeo_off"),
            icon=":material/database:",
            color="gray",
            help=t("ajuda_rigeo_off")
        )

    if web_search_enabled:
        st.badge(
            "🌐 Web",
            color="blue",
            help=(
                t("ajuda_web_tecnico")
                if web_apenas_tecnico
                else t("ajuda_web_aberta")
            )
        )

    if ana_enabled:
        st.badge(
            "💧 ANA",
            color="blue",
            help=t("ajuda_ana")
        )

    if siagas_enabled:
        st.badge(
            "🚰 SIAGAS",
            color="blue",
            help=t("ajuda_siagas")
        )

    if geosgb_enabled:
        st.badge(
            "🗺️ GeoSGB",
            color="red",
            help=t("ajuda_geosgb")
        )

    if anm_enabled:
        st.badge(
            "⛏️ ANM / SIGMINE",
            color="orange",
            help=t("ajuda_anm")
        )

    if geossit_enabled:
        st.badge(
            "🏞️ GEOSSIT",
            color="green",
            help=t("ajuda_geossit")
        )

    if macrostrat_enabled:
        st.badge(
            "🧱 Macrostrat",
            color="orange",
            help=t("ajuda_macrostrat")
        )

    if openalex_enabled:
        st.badge(
            "📚 OpenAlex",
            color="green",
            help=t("ajuda_openalex")
        )

    if intl_geo_enabled:
        regioes_ativas = (
            []
            if REGIAO_TODAS in intl_geo_regioes
            else [
                regiao
                for regiao in intl_geo_regioes
                if regiao != REGIAO_TODAS
            ]
        )

        if regioes_ativas:
            nomes_regioes = [
                _rotulo_curto_regiao(regiao)
                for regiao in regioes_ativas
            ]
            resumo_regioes = ", ".join(nomes_regioes[:3])

            if len(nomes_regioes) > 3:
                resumo_regioes += f" +{len(nomes_regioes) - 3}"

            st.badge(
                tf("badge_intl_geo_regioes", regioes=resumo_regioes),
                color="blue",
                help=tf(
                    "ajuda_intl_geo_regioes",
                    regioes=" · ".join(
                        rotulo_regiao(regiao)
                        for regiao in regioes_ativas
                    ),
                )
            )
        else:
            st.badge(
                "🌐 Geo Internacional"
                if st.session_state.get("idioma") != "en"
                else "🌐 International Geo",
                color="blue",
                help=t("ajuda_intl_geo_todas")
            )

    # Perfil analítico selecionado, com o rótulo curto para caber na
    # linha do cabeçalho.
    st.badge(
        f"🧠 {rotulo_curto_perfil(perfil_analitico)}",
        color=CORES_PERFIL.get(perfil_analitico, "gray"),
        help=tf(
            "ajuda_perfil",
            perfil=rotulo_perfil(perfil_analitico),
            descricao=descricao_perfil(
                perfil_analitico,
                padrao=perfil_ativo["descricao"],
            ),
        )
    )

    if prompt_alterado and perfil_analitico != PERFIL_PERSONALIZADO:
        st.badge(
            t("badge_prompt_editado"),
            color="violet",
            help=t("ajuda_prompt_editado")
        )

    _badge_status_ollama()

st.caption(t("subtitulo"))
st.divider()


# ---------------------------------------------------------------------------
# Extração, exploração e exportação de dados tabulares
# ---------------------------------------------------------------------------

_renderizar_painel_dados(documentos)


# ---------------------------------------------------------------------------
# Conversa
# ---------------------------------------------------------------------------

# Empty state: o guia rápido desaparece assim que a primeira pergunta é
# enviada. O placeholder permite limpar o bloco antes de renderizar a
# resposta seguinte.
espaco_guia = st.empty()

if not st.session_state.mensagens:
    with espaco_guia.container():
        _renderizar_guia_rapido()

# Histórico da conversa (inclui as fontes de cada resposta). A pergunta
# anterior acompanha cada resposta para o cabeçalho do Parecer Técnico.
pergunta_do_turno = ""

for mensagem in st.session_state.mensagens:
    if mensagem.get("role") == "user":
        pergunta_do_turno = mensagem.get("content", "")

    _renderizar_mensagem(mensagem, pergunta=pergunta_do_turno)

# Entrada do usuário no rodapé da área principal: o botão "Novo Chat"
# compacto fica ao lado esquerdo do campo de mensagem, na mesma linha.
# ``st.bottom`` mantém os dois presos à base da área principal, sem
# cobrir as mensagens já renderizadas (o container é parte do layout,
# não um elemento flutuante sobre o histórico).
with st.bottom, st.container(key="rodape_chat"):
    col_novo_chat, col_pergunta = st.columns(
        [0.15, 0.85],
        gap="small",
        vertical_alignment="center"
    )

    with col_novo_chat:
        if st.button(
            t("novo_chat"),
            key="novo_chat",
            type="secondary",
            width="stretch",
            help=t("ajuda_novo_chat")
        ):
            _nova_conversa()
            st.rerun()

    with col_pergunta:
        pergunta = st.chat_input(t("chat_placeholder"))

if pergunta:
    # O guia rápido some assim que uma pergunta é enviada.
    espaco_guia.empty()

    # Exibir pergunta.
    with st.chat_message("user"):
        st.markdown(pergunta)

    # Preparar histórico anterior.
    historico = [
        {
            "role": item["role"],
            "content": item["content"]
        }
        for item in st.session_state.mensagens
    ]

    # Cada mensagem carrega a própria chave de widgets (posição na
    # conversa); a pergunta e a resposta recebem chaves novas a cada
    # consulta.
    mensagem_usuario = _nova_mensagem("user", pergunta)
    st.session_state.mensagens.append(mensagem_usuario)

    # O título da conversa nasce da primeira pergunta e aparece na barra
    # lateral nesta mesma execução.
    _gerar_titulo_conversa()

    artigos_rigeo = []
    busca_rigeo = {}
    estacoes_ana = []
    web_dados = {}
    openalex_dados = {}
    intl_geo_dados = {}
    geosgb_dados = {}
    anm_dados = {}
    macrostrat_dados = {}
    siagas_dados = {}
    geossit_dados = {}
    erro_consulta = False

    # Feições espaciais do turno (mapa): preenchidas após a resposta e
    # guardadas na mensagem para o mapa reaparecer no histórico.
    feicoes_espaciais = []

    # Fontes ligadas na barra lateral: entram no rótulo do status para o
    # usuário saber, antes de a resposta chegar, o que está sendo
    # consultado. A ordem acompanha os GRUPOS_CONECTORES, com a base
    # documental local logo no início.
    fontes_adicionais = [
        rotulo
        for ativo, rotulo in (
            (local_docs_enabled, "Base local"),
            (rigeo_enabled, "RIGeo"),
            (web_search_enabled, "Web"),
            (ana_enabled, "ANA"),
            (siagas_enabled, "SIAGAS"),
            (geosgb_enabled, "GeoSGB"),
            (anm_enabled, "ANM/SIGMINE"),
            (geossit_enabled, "GEOSSIT"),
            (macrostrat_enabled, "Macrostrat"),
            (openalex_enabled, "OpenAlex"),
            (intl_geo_enabled, "Serviços Geológicos Internacionais"),
        )
        if ativo
    ]

    rotulo_status = t("status_analisando")

    if fontes_adicionais:
        rotulo_status += tf(
            "status_fontes",
            fontes=", ".join(fontes_adicionais),
        )

    rotulo_status += "..."

    # Consultar fonte e LLM. O status acompanha a execução e, antes da
    # resposta, mostra a intenção, a justificativa, o termo efetivamente
    # pesquisado no RIGeo e o que foi recuperado.
    with st.chat_message("assistant", avatar=AVATAR_ASSISTENTE):
        with st.status(
            rotulo_status,
            expanded=True
        ) as estado:
            try:
                resultado = responder(
                    pergunta=pergunta,
                    historico=historico,
                    limite=limite_rigeo,
                    comunidade=comunidade_rigeo,
                    modelo=modelo_ollama,
                    texto_prompt=prompt_editado,
                    documentos=documentos,
                    usar_llm_termos=termos_via_ollama,
                    usar_ana=ana_enabled,
                    usar_web=web_search_enabled,
                    web_apenas_tecnico=web_apenas_tecnico,
                    usar_sgb=rigeo_enabled,
                    usar_documentos=local_docs_enabled,
                    usar_openalex=openalex_enabled,
                    intl_geo_enabled=intl_geo_enabled,
                    intl_geo_regioes=intl_geo_regioes,
                    usar_geosgb=geosgb_enabled,
                    usar_anm=anm_enabled,
                    usar_macrostrat=macrostrat_enabled,
                    usar_siagas=siagas_enabled,
                    usar_geossit=geossit_enabled,
                    idioma=st.session_state.get("idioma", IDIOMA_PADRAO)
                )

                resposta = resultado["resposta"]
                fonte = resultado["fonte"]
                roteamento = resultado.get("roteamento") or {}
                dados = resultado.get("dados") or {}
                busca_rigeo = resultado.get("busca_rigeo") or {}

                # Os metadados completos do RIGeo são guardados na
                # mensagem para os cartões de fontes.
                artigos_rigeo = (
                    (dados.get("sgb") or {}).get("registros") or []
                )
                estacoes_ana = (
                    (dados.get("ana") or {}).get("registros") or []
                )
                web_dados = dados.get("web") or {}
                openalex_dados = dados.get("openalex") or {}
                intl_geo_dados = dados.get("intl_geo") or {}
                geosgb_dados = dados.get("geosgb") or {}
                anm_dados = dados.get("anm") or {}
                macrostrat_dados = dados.get("macrostrat") or {}
                siagas_dados = dados.get("siagas") or {}
                geossit_dados = dados.get("geossit") or {}

                _detalhar_consulta(roteamento, artigos_rigeo, dados)

                estado.update(
                    label=tf(
                        "status_concluida",
                        intencao=(
                            roteamento.get("intencao") or fonte or "—"
                        ),
                    ),
                    state="complete",
                    expanded=True
                )

            except Exception as erro:
                # Detalhes técnicos não são exibidos na interface
                # destinada ao usuário.
                print("Erro de integração:", repr(erro))

                erro_consulta = True
                resposta = t("erro_consulta")
                fonte = None
                roteamento = {}

                estado.update(
                    label=t("status_erro"),
                    state="error",
                    expanded=True
                )
                st.error(resposta)

        if not erro_consulta:
            st.markdown(resposta)
            st.caption(_legenda_fonte(fonte, roteamento))
            _renderizar_fontes(
                roteamento,
                artigos_rigeo,
                chave=_chave_resposta_atual(),
                busca_rigeo=busca_rigeo,
                estacoes_ana=estacoes_ana,
                web=web_dados,
                openalex=openalex_dados,
                intl_geo=intl_geo_dados,
                geosgb=geosgb_dados,
                anm=anm_dados,
                macrostrat=macrostrat_dados,
                siagas=siagas_dados,
                geossit=geossit_dados
            )

            # Mapa espacial logo abaixo das fontes: coordenadas das
            # APIs, tabelas dos documentos locais e citações no texto.
            feicoes_espaciais = _consolidar_feicoes_turno(
                resposta,
                dados,
                documentos
            )
            _renderizar_mapa_espacial(
                feicoes_espaciais,
                _chave_resposta_atual()
            )

    # Registrar resposta no histórico. ``roteamento``, ``artigos_rigeo``
    # e ``busca_rigeo`` alimentam o expander de fontes nos próximos
    # reruns.
    st.session_state.mensagens.append(_nova_mensagem(
        "assistant",
        resposta,
        fonte=fonte,
        roteamento=roteamento,
        artigos_rigeo=artigos_rigeo,
        busca_rigeo=busca_rigeo,
        estacoes_ana=estacoes_ana,
        web=web_dados,
        openalex=openalex_dados,
        intl_geo=intl_geo_dados,
        geosgb=geosgb_dados,
        anm=anm_dados,
        macrostrat=macrostrat_dados,
        siagas=siagas_dados,
        geossit=geossit_dados,
        feicoes_espaciais=feicoes_espaciais,
        perfil_analitico=perfil_analitico
    ))

    # Autosave transparente: a conversa é gravada assim que a resposta
    # fica pronta, então fechar a aba ou reiniciar o aplicativo não
    # perde a consulta. Uma nova pergunta atualiza o arquivo existente.
    _salvar_conversa_atual()

    # A página é redesenhada já com a resposta em ``mensagens``. Assim o
    # expander de fontes da resposta é recriado uma única vez por
    # execução (e não duas: na exibição imediata e no redesenho), a
    # barra lateral já mostra a conversa no histórico com o estado
    # atualizado, e um F5 não repete a consulta.
    st.rerun()
