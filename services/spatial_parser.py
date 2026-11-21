"""Geocodificação contextual e consolidação espacial leve.

Este módulo transforma tudo o que uma resposta do assistente já traz de
posição geográfica em uma única lista padronizada de pontos, pronta para
o mapa nativo do Streamlit (``st.map``). Não usa geopandas, GDAL, PROJ
nem qualquer serviço externo: apenas ``re``, ``math``, ``csv`` e
``pandas`` (já presente no projeto pela exploração de tabelas).

As três origens de posição são unificadas por
:func:`consolidar_pontos_mapa`:

1. **Metadados das APIs externas** — os registros de ANA, SIAGAS,
   GeoSGB, ANM/SIGMINE, INDE/GEOSSIT, Macrostrat e dos serviços
   geológicos internacionais já trazem ``lat``/``lon`` (a ANA publica
   ``latitude``/``longitude``, aceito do mesmo jeito);
2. **Tabelas extraídas** dos documentos locais
   (``services/table_extractor.py``), quando existe coluna de latitude e
   longitude — furos de sondagem, amostras, pontos de campo;
3. **Texto** da resposta e resumos das fontes, via
   :func:`extrair_feicoes_espaciais`, que reconhece pares de
   coordenadas em graus decimais, em graus/minutos/segundos e os
   códigos de folha da Carta Internacional ao Milionésimo (CIM).

Articulação sistemática (CIM) usada no cálculo das folhas
----------------------------------------------------------

A nomenclatura segue a articulação do mapeamento sistemático
brasileiro (IBGE/DSG), conferida com o exemplo clássico
``SF-22-Y-D-I-1`` (φ = 23°04' S, λ = 52°24' W):

- ``1:1.000.000`` — hemisfério (``S``/``N``) + banda de 4° em latitude
  (``A`` = 0°–4°, ``B`` = 4°–8°, …) + coluna de 6° em longitude
  (``1`` começa em 180° W), por exemplo ``SA.20``;
- ``1:500.000`` — quatro quadrantes ``V`` (NO), ``X`` (NE), ``Y`` (SO)
  e ``Z`` (SE), lidos da esquerda para a direita e de cima para baixo;
- ``1:250.000`` — quatro quadrantes ``A`` (NO), ``B`` (NE), ``C`` (SO)
  e ``D`` (SE);
- ``1:100.000`` — seis quadrantes ``I`` a ``VI`` em duas linhas de três;
- ``1:50.000`` — quatro quadrantes ``1`` a ``4`` em duas linhas de dois.

Os limites são calculados a partir do código, e o centróide é o centro
geométrico da folha. O código aceita ponto ou hífen depois da zona
(``SB.21`` e ``SB-21``) e hífen, travessão ou ponto entre as
subdivisões.

Limitações assumidas
--------------------

- A sigla de estado ``SC`` seguida de número **com separador**
  (``SC.22``) é lida como folha CIM; é a leitura correta em contexto
  geológico, mas o detector não distingue os dois usos.
- Coordenadas sem rótulo exigem pelo menos três casas decimais, para
  não confundir pares de números quaisquer (``1,5 2,5``) com posição.
- A conversão GMS usa o datum WGS84 e ignora segundos ausentes.
- Nada aqui corrige datum histórico (Córrego Alegre, SAD69): o texto
  citado é tratado como WGS84, como fazem as APIs consultadas.
"""

import csv
import io
import math
import re
import unicodedata

import pandas as pd

# ---------------------------------------------------------------------------
# Camadas e cores
# ---------------------------------------------------------------------------

# Cada camada reúne uma família de feições e uma cor fixa: a mesma cor
# aparece no mapa, na legenda do filtro e na tabela, o que permite
# comparar turnos diferentes sem depender da ordem de chegada.
CAMADAS = {
    "ana": ("Hidrologia (ANA)", "#1F6FEB"),
    "siagas": ("Hidrogeologia (SIAGAS)", "#00B4D8"),
    "geosgb": ("Ocorrências minerais (GeoSGB)", "#E0A100"),
    "anm": ("Processos minerários (ANM)", "#D93636"),
    "geossit": ("Geossítios (INDE/GEOSSIT)", "#1E8F4E"),
    "macrostrat": ("Estratigrafia (Macrostrat)", "#8D6E63"),
    "intl_geo": ("Serviços geológicos internacionais", "#0F766E"),
    "folhas_cim": ("Folhas CIM (SGB)", "#43A047"),
    "documentos": ("Pontos de documentos locais", "#8E44AD"),
}

# Ordem de exibição na tabela: fontes públicas primeiro, feições
# derivadas de texto por último.
ORDEM_CAMADAS = (
    "ana",
    "siagas",
    "geosgb",
    "anm",
    "geossit",
    "macrostrat",
    "intl_geo",
    "folhas_cim",
    "documentos",
)

CAMADA_PADRAO = "documentos"

# Teto de feições por turno. Uma resposta que cita dezenas de estações e
# ainda tabelas longas produziria centenas de pontos; acima disso o mapa
# fica ilegível e a tabela deixa de ser "compacta". O corte preserva as
# feições das APIs, que entram primeiro na consolidação.
LIMITE_FEICOES = 300

# Casas decimais usadas na deduplicação. Cinco casas equivalem a cerca de
# 1 m em latitude: dois registros com a mesma posição arredondada são a
# mesma feição para efeito de mapa.
CASAS_DEDUPLICACAO = 5

# Tolerância para considerar que um ponto citado no texto repete um ponto
# estruturado (resumo de fonte com "Coord: ..."): mesma origem, mesmo
# lugar, um único marcador no mapa.
CASAS_REPETICAO_TEXTO = 4

# Rótulos usados no CSV e na tabela da interface.
CABECALHO_CSV = (
    "nome",
    "camada",
    "lat",
    "lon",
    "folha_cim",
    "lat_min",
    "lat_max",
    "lon_min",
    "lon_max",
    "detalhe",
)

# ---------------------------------------------------------------------------
# Utilidades de texto e número
# ---------------------------------------------------------------------------

def _sem_acento(texto):
    """Remove acentos sem alterar o restante do texto."""

    decomposto = unicodedata.normalize("NFKD", str(texto or ""))

    return "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    )


def _texto_limpo(valor):
    """Texto de uma célula: uma linha, sem espaços sobrando."""

    if valor is None:
        return ""

    if isinstance(valor, float) and math.isnan(valor):
        return ""

    return " ".join(str(valor).split())


def _numero(valor):
    """Converte célula em ``float`` aceitando vírgula decimal."""

    if isinstance(valor, bool) or valor is None:
        return None

    if isinstance(valor, (int, float)):
        numero = float(valor)
        return numero if math.isfinite(numero) else None

    texto = _texto_limpo(valor).replace(" ", "").replace(",", ".")

    if not texto:
        return None

    try:
        numero = float(texto)
    except ValueError:
        return None

    return numero if math.isfinite(numero) else None


def coordenada_valida(lat, lon):
    """Diz se o par está dentro dos limites geográficos."""

    if lat is None or lon is None:
        return False

    if not (-90.0 <= lat <= 90.0):
        return False

    if not (-180.0 <= lon <= 180.0):
        return False

    return True


# ---------------------------------------------------------------------------
# Carta Internacional ao Milionésimo (CIM)
# ---------------------------------------------------------------------------

# Bandas de latitude da CIM: A (0°–4°) até I (32°–36°). O Brasil vai de
# 5° N a 34° S, então A–I cobre todo o território com folga.
_BANDAS_LATITUDE = "ABCDEFGHI"

# Quadrantes de 1:500.000 (V, X, Y, Z) e de 1:250.000 (A, B, C, D):
# (linha, coluna) com linha 0 ao norte e coluna 0 a oeste.
_QUADRANTES = {
    "V": (0, 0),
    "X": (0, 1),
    "Y": (1, 0),
    "Z": (1, 1),
    "A": (0, 0),
    "B": (0, 1),
    "C": (1, 0),
    "D": (1, 1),
}

# Numeração romana dos seis quadrantes de 1:100.000.
_ROMANOS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
}

# A zona aceita ponto ou hífen (SB.21 / SB-21) e as subdivisões aceitam
# ponto, hífen ou travessão, com espaços opcionais.
_SEPARADOR = r"\s*[.\-\u2013\u2014]\s*"

_PADRAO_CIM = re.compile(
    r"\b(?P<hemisferio>[SN])(?P<banda>[A-H])"
    + _SEPARADOR
    + r"(?P<coluna>\d{1,2})"
    + r"(?:" + _SEPARADOR + r"(?P<q500>[VXYZ]))?"
    + r"(?:" + _SEPARADOR + r"(?P<q250>[A-D]))?"
    + r"(?:" + _SEPARADOR + r"(?P<q100>VI|IV|V|III|II|I))?"
    + r"(?:" + _SEPARADOR + r"(?P<q50>[1-4]))?",
    re.IGNORECASE,
)

_ESCALAS_CIM = (
    "1:1.000.000",
    "1:500.000",
    "1:250.000",
    "1:100.000",
    "1:50.000",
)

def _subdividir(caixa, linhas, colunas, linha, coluna):
    """Recorta uma sub-área da caixa ``(lat_max, lat_min, lon_min, lon_max)``."""

    lat_max, lat_min, lon_min, lon_max = caixa
    altura = (lat_max - lat_min) / linhas
    largura = (lon_max - lon_min) / colunas

    return (
        lat_max - altura * linha,
        lat_max - altura * (linha + 1),
        lon_min + largura * coluna,
        lon_min + largura * (coluna + 1),
    )


def _centro(caixa):
    """Centróide geográfico (média dos cantos) de uma caixa CIM."""

    lat_max, lat_min, lon_min, lon_max = caixa

    return (
        round((lat_max + lat_min) / 2, 6),
        round((lon_max + lon_min) / 2, 6),
    )


def _formatar_limites(caixa):
    """Texto curto dos limites, para a coluna da tabela."""

    lat_max, lat_min, lon_min, lon_max = caixa

    return (
        f"lat {lat_min:.4f} a {lat_max:.4f} · "
        f"lon {lon_min:.4f} a {lon_max:.4f}"
    )


def decodificar_folha_cim(codigo):
    """Interpreta um código CIM e devolve limite, centro e escala.

    Aceita as leituras de 1:1.000.000 até 1:50.000 (``SA.20``,
    ``SB.21-X-B``, ``SC.22-Z-D-IV``, ``SD.23-Y-C-IV-3``). Devolve
    ``None`` quando o código não é uma folha válida: hemisfério fora de
    ``S``/``N``, banda fora de ``A``–``H`` ou coluna fora de 1–60.

    A chave ``codigo`` sai normalizada (maiúsculas, ponto depois da zona
    e hífen entre as subdivisões), independentemente de como o texto
    original a escreveu.
    """

    if not isinstance(codigo, str):
        return None

    encontrado = _PADRAO_CIM.fullmatch(codigo.strip())

    if encontrado is None:
        return None

    hemisferio = encontrado.group("hemisferio").upper()
    banda = encontrado.group("banda").upper()

    try:
        coluna = int(encontrado.group("coluna"))
    except (TypeError, ValueError):
        return None

    if banda not in _BANDAS_LATITUDE or not 1 <= coluna <= 60:
        return None

    indice_banda = _BANDAS_LATITUDE.index(banda)

    if hemisferio == "S":
        # Somar 0.0 evita o "-0.0" na folha que encosta no equador.
        lat_max = -4.0 * indice_banda + 0.0
        lat_min = -4.0 * (indice_banda + 1)
    else:
        lat_min = 4.0 * indice_banda + 0.0
        lat_max = 4.0 * (indice_banda + 1)

    lon_min = -180.0 + 6.0 * (coluna - 1)
    lon_max = lon_min + 6.0

    caixa = (lat_max, lat_min, lon_min, lon_max)
    partes = [f"{hemisferio}{banda}.{coluna:02d}"]

    q500 = (encontrado.group("q500") or "").upper()
    q250 = (encontrado.group("q250") or "").upper()
    q100 = (encontrado.group("q100") or "").upper()
    q50 = encontrado.group("q50") or ""

    if q500:
        if q500 not in _QUADRANTES:
            return None

        partes.append(q500)
        caixa = _subdividir(caixa, 2, 2, *_QUADRANTES[q500])

    if q250:
        if q250 not in _QUADRANTES:
            return None

        partes.append(q250)
        caixa = _subdividir(caixa, 2, 2, *_QUADRANTES[q250])

    if q100:
        numero = _ROMANOS.get(q100)

        if numero is None:
            return None

        partes.append(q100)
        caixa = _subdividir(caixa, 2, 3, (numero - 1) // 3, (numero - 1) % 3)

    if q50:
        numero = int(q50)

        if numero not in (1, 2, 3, 4):
            return None

        partes.append(q50)
        caixa = _subdividir(caixa, 2, 2, (numero - 1) // 2, (numero - 1) % 2)

    lat, lon = _centro(caixa)

    return {
        "codigo": "-".join(partes),
        "escala": _ESCALAS_CIM[len(partes) - 1],
        "lat": lat,
        "lon": lon,
        "lat_min": round(caixa[1], 6),
        "lat_max": round(caixa[0], 6),
        "lon_min": round(caixa[2], 6),
        "lon_max": round(caixa[3], 6),
        "limites": _formatar_limites(caixa),
    }


def codigo_folha_cim(lat, lon):
    """Código CIM 1:1.000.000 que contém o ponto (``None`` se inválido)."""

    if not coordenada_valida(lat, lon):
        return None

    # No equador a convenção brasileira é a folha do hemisfério sul.
    hemisferio = "N" if lat > 0 else "S"
    indice = min(int(abs(lat) // 4), len(_BANDAS_LATITUDE) - 1)
    coluna = int(math.floor((lon + 180.0) / 6.0)) + 1
    coluna = min(max(coluna, 1), 60)

    return f"{hemisferio}{_BANDAS_LATITUDE[indice]}.{coluna:02d}"


# ---------------------------------------------------------------------------
# Detecção textual: graus decimais e GMS
# ---------------------------------------------------------------------------

# Números decimais de coordenada. A vírgula decimal é aceita porque
# relatórios em português a usam; a validação de faixa só acontece
# depois da conversão.
_DECIMAL = r"[-+]?\d{1,3}[.,]\d{1,6}"

# Par rotulado: "Lat: -7.21 / Lon: -59.88", "latitude -3,1234
# longitude -60,0123".
_PADRAO_DECIMAL_ROTULADO = re.compile(
    r"\blat(?:itude)?\b\s*(?:em)?\s*[:=]?\s*(?P<lat>" + _DECIMAL + r")"
    r"(?:\s*°)?\s*[,;/|]?\s*"
    r"(?:lon(?:gitude)?|long)\b\s*(?:em)?\s*[:=]?\s*(?P<lon>" + _DECIMAL + r")",
    re.IGNORECASE,
)

# Par precedido de "coordenadas", aceitando parênteses e duas casas
# decimais ("Coordenadas: (-3.12, -60.01)").
_PADRAO_DECIMAL_COORDENADAS = re.compile(
    r"\bcoordenadas?\b(?:\s+aproximadas?)?\s*[:=]?\s*\(?\s*"
    r"(?P<lat>" + _DECIMAL + r")\s*[,;/|]\s*(?P<lon>" + _DECIMAL + r")",
    re.IGNORECASE,
)

# Par solto: exige três casas decimais em pelo menos um dos números, o
# que descarta pares de medidas comuns ("1,5 2,5") sem perder
# coordenadas de relatório.
_PADRAO_DECIMAL_PAR = re.compile(
    r"(?<![\d.,])(?P<lat>[-+]?\d{1,3}[.,]\d{3,6})\s*(?:[,;/|]|\s{1,3})\s*"
    r"(?P<lon>[-+]?\d{1,3}[.,]\d{2,6})(?![\d.,])",
)

# Graus, minutos e segundos. Os segundos podem faltar, o símbolo de grau
# é obrigatório (é o que separa GMS de um par qualquer) e o hemisfério
# fecha a leitura.
_GRAU = r"[°ºᵒ]"
_MINUTO = r"['′’]"
_SEGUNDO = r"[\"″”“]{1,2}"

_PADRAO_GMS_PAR = re.compile(
    r"(?P<lat_g>\d{1,3})\s*" + _GRAU + r"\s*"
    r"(?:(?P<lat_m>\d{1,2})\s*" + _MINUTO + r"\s*)?"
    r"(?:(?P<lat_s>\d{1,2}(?:[.,]\d+)?)\s*" + _SEGUNDO + r"\s*)?"
    r"(?P<lat_h>[NSns])\s*[,;/|]?\s*"
    r"(?P<lon_g>\d{1,3})\s*" + _GRAU + r"\s*"
    r"(?:(?P<lon_m>\d{1,2})\s*" + _MINUTO + r"\s*)?"
    r"(?:(?P<lon_s>\d{1,2}(?:[.,]\d+)?)\s*" + _SEGUNDO + r"\s*)?"
    r"(?P<lon_h>[EWOewo])"
)

# A mesma leitura com a longitude primeiro (comum em textos de campo).
_PADRAO_GMS_PAR_INVERTIDO = re.compile(
    r"(?P<lon_g>\d{1,3})\s*" + _GRAU + r"\s*"
    r"(?:(?P<lon_m>\d{1,2})\s*" + _MINUTO + r"\s*)?"
    r"(?:(?P<lon_s>\d{1,2}(?:[.,]\d+)?)\s*" + _SEGUNDO + r"\s*)?"
    r"(?P<lon_h>[EWOewo])\s*[,;/|]?\s*"
    r"(?P<lat_g>\d{1,3})\s*" + _GRAU + r"\s*"
    r"(?:(?P<lat_m>\d{1,2})\s*" + _MINUTO + r"\s*)?"
    r"(?:(?P<lat_s>\d{1,2}(?:[.,]\d+)?)\s*" + _SEGUNDO + r"\s*)?"
    r"(?P<lat_h>[NSns])"
)


def gms_para_decimal(graus, minutos, segundos, hemisferio):
    """Converte graus/minutos/segundos em grau decimal com sinal.

    ``S`` e ``W``/``O`` produzem valor negativo. Devolve ``None`` quando
    algum componente está fora da faixa esperada.
    """

    try:
        graus = float(str(graus).replace(",", "."))
        minutos = float(str(minutos).replace(",", ".")) if minutos else 0.0
        segundos = (
            float(str(segundos).replace(",", ".")) if segundos else 0.0
        )
    except (TypeError, ValueError):
        return None

    if not (0.0 <= graus <= 180.0):
        return None

    if not (0.0 <= minutos < 60.0):
        return None

    if not (0.0 <= segundos < 60.0):
        return None

    decimal = graus + minutos / 60.0 + segundos / 3600.0

    if str(hemisferio).upper() in {"S", "W", "O"}:
        decimal = -decimal

    return decimal


def _trecho_contexto(texto, inicio, fim, margem=48):
    """Trecho ao redor do achado, usado como detalhe legível."""

    inicial = max(0, inicio - margem)
    final = min(len(texto), fim + margem)
    trecho = " ".join(texto[inicial:final].split())

    if inicial > 0:
        trecho = "… " + trecho

    if final < len(texto):
        trecho = trecho + " …"

    return trecho[:220]


def _montar_feicao(
    camada,
    nome,
    lat,
    lon,
    detalhe="",
    origem="texto",
    folha=None,
    **extras
):
    """Monta um ponto no contrato usado pela interface e pelo CSV."""

    if not coordenada_valida(lat, lon):
        return None

    rotulo, cor = CAMADAS.get(camada, CAMADAS[CAMADA_PADRAO])

    feicao = {
        "nome": _texto_limpo(nome)[:160] or "Ponto sem nome",
        "camada": rotulo,
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "detalhe": _texto_limpo(detalhe)[:400],
        "cor_hex": cor,
        "origem": origem,
        # A folha de 1:1.000.000 que contém o ponto é sempre conhecida e
        # ajuda a localizar o registro em bases do SGB/RIGeo.
        "folha_cim": folha or codigo_folha_cim(lat, lon),
        "lat_min": None,
        "lat_max": None,
        "lon_min": None,
        "lon_max": None,
        "limites": "",
    }

    feicao.update(extras)

    return feicao


def _extrair_folhas_cim(texto):
    """Feições das folhas CIM citadas, com centróide e limites."""

    feicoes = []

    for encontrado in _PADRAO_CIM.finditer(texto):
        folha = decodificar_folha_cim(encontrado.group(0))

        if folha is None:
            continue

        feicoes.append(_montar_feicao(
            "folhas_cim",
            f"Folha {folha['codigo']}",
            folha["lat"],
            folha["lon"],
            detalhe=(
                f"Folha CIM {folha['codigo']} · escala {folha['escala']} · "
                f"{folha['limites']}"
            ),
            origem="texto",
            folha=folha["codigo"],
            escala=folha["escala"],
            lat_min=folha["lat_min"],
            lat_max=folha["lat_max"],
            lon_min=folha["lon_min"],
            lon_max=folha["lon_max"],
            limites=folha["limites"],
        ))

    return [feicao for feicao in feicoes if feicao is not None]


def _extrair_gms(texto):
    """Pontos escritos em graus, minutos e segundos."""

    feicoes = []
    ocupados = []

    for padrao in (_PADRAO_GMS_PAR, _PADRAO_GMS_PAR_INVERTIDO):
        for encontrado in padrao.finditer(texto):
            inicio, fim = encontrado.span()

            if any(inicio < final and inicial < fim for inicial, final in ocupados):
                continue

            ocupados.append((inicio, fim))

            lat = gms_para_decimal(
                encontrado.group("lat_g"),
                encontrado.group("lat_m"),
                encontrado.group("lat_s"),
                encontrado.group("lat_h"),
            )
            lon = gms_para_decimal(
                encontrado.group("lon_g"),
                encontrado.group("lon_m"),
                encontrado.group("lon_s"),
                encontrado.group("lon_h"),
            )

            if lat is None or lon is None:
                continue

            citacao = " ".join(encontrado.group(0).split())

            feicoes.append(_montar_feicao(
                CAMADA_PADRAO,
                f"Ponto {citacao}",
                lat,
                lon,
                detalhe=_trecho_contexto(texto, inicio, fim),
            ))

    return [feicao for feicao in feicoes if feicao is not None]


def _adicionar_decimal(feicoes, encontrado, texto, permitir_inversao=True):
    """Acrescenta o par decimal de um ``match`` já validado.

    ``permitir_inversao`` fica ligado apenas para pares sem rótulo. Em
    ``Lat: ... / Lon: ...`` e ``Coordenadas: lat, lon`` a ordem é
    explícita: trocar os eixos para "fazer caber" transformaria uma
    coordenada inválida (lat 95) em um ponto falso no oceano.
    """

    lat = _numero(encontrado.group("lat"))
    lon = _numero(encontrado.group("lon"))

    if lat is None or lon is None:
        return

    # Par invertido (lon, lat) é comum em planilhas e relatórios sem
    # rótulo: aceito quando a leitura direta não fecha geograficamente.
    if not coordenada_valida(lat, lon):
        if permitir_inversao and coordenada_valida(lon, lat):
            lat, lon = lon, lat
        else:
            return

    inicio, fim = encontrado.span()

    feicao = _montar_feicao(
        CAMADA_PADRAO,
        f"Ponto citado ({lat:.5f}, {lon:.5f})",
        lat,
        lon,
        detalhe=_trecho_contexto(texto, inicio, fim),
    )

    if feicao is not None:
        feicoes.append(feicao)


def _extrair_decimais(texto):
    """Pares de coordenadas em graus decimais, rotulados ou soltos."""

    feicoes = []

    for padrao in (
        _PADRAO_DECIMAL_ROTULADO,
        _PADRAO_DECIMAL_COORDENADAS,
        _PADRAO_DECIMAL_PAR,
    ):
        # Só o par solto aceita inversão: os padrões rotulados já dizem
        # qual número é latitude e qual é longitude.
        permitir_inversao = padrao is _PADRAO_DECIMAL_PAR

        for encontrado in padrao.finditer(texto):
            _adicionar_decimal(
                feicoes,
                encontrado,
                texto,
                permitir_inversao=permitir_inversao,
            )

    return feicoes


def extrair_feicoes_espaciais(texto):
    """Detecta coordenadas e folhas CIM citadas em um texto.

    Devolve uma lista de dicionários no mesmo contrato de
    :func:`consolidar_pontos_mapa` (``nome``, ``camada``, ``lat``,
    ``lon``, ``detalhe``, ``cor_hex``), já sem repetições. Pontos fora
    dos limites geográficos são descartados; folhas CIM viram o
    centróide da área, com limites e escala.

    O texto é truncado em 20 mil caracteres para manter o custo das
    expressões regulares previsível em respostas muito longas.
    """

    if not isinstance(texto, str):
        return []

    recorte = texto[:20000]

    if not recorte.strip():
        return []

    feicoes = []
    feicoes.extend(_extrair_folhas_cim(recorte))
    feicoes.extend(_extrair_gms(recorte))
    feicoes.extend(_extrair_decimais(recorte))

    return _deduplicar(feicoes)


# ---------------------------------------------------------------------------
# Consolidação multi-fonte
# ---------------------------------------------------------------------------

# Correspondência entre o identificador da fonte (como aparece nos
# metadados ou no texto) e a camada do mapa. A busca é por trecho, sem
# acento e em minúsculas, o que absorve "ANA / HidroWeb (cache local)" e
# "SGB / GeoSGB WFS".
_APELIDOS_FONTES = (
    ("ana", ("ana", "hidroweb")),
    ("siagas", ("siagas", "rimas")),
    ("geosgb", ("geosgb",)),
    ("anm", ("anm", "sigmine")),
    ("geossit", ("geossit", "inde")),
    ("macrostrat", ("macrostrat",)),
    # Serviços geológicos internacionais: a entrada do grupo chega com a
    # chave ``intl_geo``; os apelidos cobrem registros individuais quando
    # a interface os passar soltos.
    (
        "intl_geo",
        (
            "intl_geo",
            "serviços geológicos internacionais",
            "servicos geologicos internacionais",
            "serviço geológico internacional",
            "onegeology",
            "sciencebase",
            "nrcan",
            "geoscan",
            "egdi",
            "eurogeosurveys",
            "geoscience australia",
            "gsq",
            "gsj",
            "aist",
            "geonet",
            "gns science",
            "digital earth africa",
            "council for geoscience",
            "ngd",
            "bhukosh",
            "gsi /",
        ),
    ),
    # Artigos do acervo SGB/RIGeo só entram no mapa quando trazem
    # coordenada explícita; ficam na camada de documentos locais.
    ("documentos", ("sgb", "rigeo", "geobusca")),
)

_TITULOS_REGISTRO = (
    "nome",
    "nome_ponto",
    "nome_alvo",
    "titulo",
    "processo",
    "codigo",
    "estacao",
    "poco",
    "furo",
    "amostra",
    "ponto",
    "id",
)


def _camada_da_fonte(nome):
    """Traduz o nome de uma fonte para a chave de camada do mapa."""

    chave = _sem_acento(nome).lower()

    if not chave:
        return ""

    # A camada internacional é avaliada primeiro: "Canadá" contém a
    # sequência "ana" e seria confundido com a camada da ANA.
    for camada, apelidos in _APELIDOS_FONTES:
        if camada != "intl_geo":
            continue

        if any(apelido in chave for apelido in apelidos):
            return camada

    for camada, apelidos in _APELIDOS_FONTES:
        if camada == "intl_geo":
            continue

        if any(apelido in chave for apelido in apelidos):
            return camada

    return ""


def _registros_da_entrada(entrada):
    """Lista de registros de uma entrada de metadados."""

    if not isinstance(entrada, dict):
        return []

    candidatos = (
        entrada.get("registros")
        or entrada.get("dados")
        or entrada.get("itens")
        or []
    )

    if isinstance(candidatos, dict):
        candidatos = candidatos.get("registros") or []

    if not isinstance(candidatos, (list, tuple)):
        return []

    return [item for item in candidatos if isinstance(item, dict)]


def _coordenadas_registro(registro):
    """Extrai ``(lat, lon)`` de um registro de API, em qualquer grafia.

    A ANA publica ``latitude``/``longitude``; as demais fontes usam
    ``lat``/``lon``; o GEOSSIT grava ``long``. A função tenta as três
    grafias antes de desistir do registro.
    """

    lat = None
    lon = None

    for campo in ("lat", "latitude"):
        lat = _numero(registro.get(campo))

        if lat is not None:
            break

    for campo in ("lon", "longitude", "lng", "long"):
        lon = _numero(registro.get(campo))

        if lon is not None:
            break

    if lat is None or lon is None:
        # Última tentativa: um campo de coordenadas em texto
        # ("lat, lon" ou "−3,12 / −60,01").
        for campo in ("coordenadas", "coordenada", "coord", "geometry"):
            valor = registro.get(campo)

            if isinstance(valor, str):
                par = _ler_par_coordenadas(valor)

                if par is not None:
                    return par

        return None

    if coordenada_valida(lat, lon):
        return (lat, lon)

    if coordenada_valida(lon, lat):
        return (lon, lat)

    return None


def _ler_par_coordenadas(texto):
    """Lê ``"lat, lon"`` de um texto e valida os limites."""

    if not isinstance(texto, str):
        return None

    numeros = re.findall(r"[-+]?\d+(?:[.,]\d+)?", texto)

    if len(numeros) != 2:
        return None

    primeiro = _numero(numeros[0])
    segundo = _numero(numeros[1])

    if primeiro is None or segundo is None:
        return None

    if coordenada_valida(primeiro, segundo):
        return (primeiro, segundo)

    if coordenada_valida(segundo, primeiro):
        return (segundo, primeiro)

    return None


def _nome_registro(registro, posicao):
    """Melhor rótulo disponível para um registro tabular."""

    for campo in _TITULOS_REGISTRO:
        valor = _texto_limpo(registro.get(campo))

        if valor:
            return valor

    return f"Registro {posicao + 1}"


def _detalhe_registro(registro, rotulo_fonte):
    """Detalhe curto do registro: resumo, localização e fonte."""

    resumo = _texto_limpo(registro.get("resumo"))
    partes = []

    if rotulo_fonte:
        partes.append(rotulo_fonte)

    local = "/".join(
        valor
        for valor in (
            _texto_limpo(registro.get("municipio")),
            _texto_limpo(registro.get("uf")),
        )
        if valor
    )

    if local:
        partes.append(local)

    if resumo:
        return " · ".join(partes + [resumo]) if partes else resumo

    if registro.get("tipo"):
        partes.append(_texto_limpo(registro.get("tipo")))

    return " · ".join(partes)


def _feicoes_das_fontes(metadados_fontes):
    """Pontos dos registros que já trazem latitude e longitude."""

    feicoes = []

    for entrada in metadados_fontes or []:
        if not isinstance(entrada, dict):
            continue

        camada = _camada_da_fonte(entrada.get("fonte") or entrada.get("origem"))
        registros = _registros_da_entrada(entrada)

        if not camada or not registros:
            continue

        rotulo_fonte = (
            _texto_limpo(entrada.get("titulo"))
            or CAMADAS.get(camada, CAMADAS[CAMADA_PADRAO])[0]
        )

        for posicao, registro in enumerate(registros):
            par = _coordenadas_registro(registro)

            if par is None:
                continue

            lat, lon = par
            feicao = _montar_feicao(
                camada,
                _nome_registro(registro, posicao),
                lat,
                lon,
                detalhe=_detalhe_registro(registro, rotulo_fonte),
                origem="api",
            )

            if feicao is not None:
                feicoes.append(feicao)

    return feicoes


def _resumos_das_fontes(metadados_fontes):
    """Textos das fontes usados na busca por coordenadas citadas."""

    resumos = []

    for entrada in metadados_fontes or []:
        if not isinstance(entrada, dict):
            continue

        # Texto de nível da fonte (quando existir) e o resumo de cada
        # registro: é ali que aparecem "Folha SD.23" e "Coord: ...".
        for campo in ("resumo", "texto", "descricao", "comentario"):
            valor = _texto_limpo(entrada.get(campo))

            if valor:
                resumos.append(valor)

        for registro in _registros_da_entrada(entrada):
            for campo in ("resumo", "descricao", "observacao"):
                valor = _texto_limpo(registro.get(campo))

                if valor:
                    resumos.append(valor)

    return resumos


def _classificar_cabecalho(cabecalho):
    """Diz se a coluna é latitude, longitude ou par de coordenadas."""

    chave = _sem_acento(cabecalho).strip().lower()
    chave = re.sub(r"[^a-z0-9]+", " ", chave).strip()

    if not chave:
        return ""

    tem_lat = "lat" in chave.split() or "latitude" in chave
    tem_lon = (
        "lon" in chave.split()
        or "long" in chave.split()
        or "longitude" in chave
    )

    if "coordenada" in chave or "coord" in chave:
        return "par"

    if tem_lat and tem_lon:
        return "par"

    if tem_lat:
        return "lat"

    if tem_lon:
        return "lon"

    return ""


def _dataframe_da_tabela(tabela):
    """DataFrame já tipado e DataFrame bruto de uma tabela extraída."""

    if not isinstance(tabela, dict):
        return None

    for chave in ("df_limpo", "df_bruto"):
        valor = tabela.get(chave)

        if isinstance(valor, pd.DataFrame) and not valor.empty:
            return valor

    return None


def _feicoes_das_tabelas(tabelas_extraidas):
    """Pontos das tabelas que possuem colunas de latitude e longitude."""

    feicoes = []

    for tabela in tabelas_extraidas or []:
        df = _dataframe_da_tabela(tabela)

        if df is None:
            continue

        colunas = list(df.columns)
        coluna_lat = ""
        coluna_lon = ""
        coluna_par = ""

        for coluna in colunas:
            classificacao = _classificar_cabecalho(coluna)

            if classificacao == "par" and not coluna_par:
                coluna_par = coluna
            elif classificacao == "lat" and not coluna_lat:
                coluna_lat = coluna
            elif classificacao == "lon" and not coluna_lon:
                coluna_lon = coluna

        if coluna_par:
            coluna_lat = coluna_lon = ""

        if not coluna_par and not (coluna_lat and coluna_lon):
            continue

        # Coluna de nome: a primeira que identificar o registro.
        coluna_nome = ""

        for coluna in colunas:
            chave = _sem_acento(coluna).strip().lower()

            if chave in {
                "nome",
                "furo",
                "furos",
                "amostra",
                "amostras",
                "ponto",
                "pontos",
                "id",
                "codigo",
                "estacao",
                "poco",
            } or chave.startswith(("furo ", "amostra ", "ponto ")):
                coluna_nome = coluna
                break

        titulo = _texto_limpo(tabela.get("titulo")) or "Tabela"
        origem = _texto_limpo(tabela.get("origem"))
        pagina = tabela.get("pagina")
        base_detalhe = " · ".join(
            parte
            for parte in (
                origem,
                f"p. {pagina}" if pagina else "",
            )
            if parte
        )

        for posicao, (_, linha) in enumerate(df.iterrows()):
            if coluna_par:
                par = _ler_par_coordenadas(_texto_limpo(linha.get(coluna_par)))
            else:
                lat = _numero(linha.get(coluna_lat))
                lon = _numero(linha.get(coluna_lon))

                if lat is None or lon is None:
                    par = None
                elif coordenada_valida(lat, lon):
                    par = (lat, lon)
                elif coordenada_valida(lon, lat):
                    par = (lon, lat)
                else:
                    par = None

            if par is None:
                continue

            lat, lon = par

            nome = (
                _texto_limpo(linha.get(coluna_nome))
                if coluna_nome
                else ""
            ) or f"{titulo} (linha {posicao + 1})"

            detalhe = titulo

            if base_detalhe:
                detalhe = f"{titulo} · {base_detalhe}"

            feicao = _montar_feicao(
                CAMADA_PADRAO,
                nome,
                lat,
                lon,
                detalhe=detalhe,
                origem="tabela",
            )

            if feicao is not None:
                feicoes.append(feicao)

    return feicoes


def _chave_deduplicacao(feicao):
    """Identidade de um ponto: camada mais posição arredondada."""

    return (
        feicao["camada"],
        round(feicao["lat"], CASAS_DEDUPLICACAO),
        round(feicao["lon"], CASAS_DEDUPLICACAO),
    )


def _deduplicar(feicoes):
    """Remove pontos idênticos, preservando a primeira ocorrência."""

    vistos = set()
    resultado = []

    for feicao in feicoes or []:
        if not isinstance(feicao, dict):
            continue

        chave = _chave_deduplicacao(feicao)

        if chave in vistos:
            continue

        vistos.add(chave)
        resultado.append(feicao)

    return resultado


def _remover_pontos_textuais_repetidos(feicoes):
    """Descarta citações no texto que repetem um ponto estruturado.

    Os resumos das APIs trazem a coordenada como texto ("Coord: -3,12,
    -60,01"); sem este filtro o mesmo lugar apareceria duas vezes, em
    duas camadas. A comparação usa quatro casas decimais (~11 m), o que
    cobre arredondamentos de fonte sem juntar pontos vizinhos.
    """

    estruturados = {
        (
            round(feicao["lat"], CASAS_REPETICAO_TEXTO),
            round(feicao["lon"], CASAS_REPETICAO_TEXTO),
        )
        for feicao in feicoes
        if feicao.get("origem") != "texto"
    }

    resultado = []

    for feicao in feicoes:
        if feicao.get("origem") == "texto":
            chave = (
                round(feicao["lat"], CASAS_REPETICAO_TEXTO),
                round(feicao["lon"], CASAS_REPETICAO_TEXTO),
            )

            if chave in estruturados:
                continue

        resultado.append(feicao)

    return resultado


def _ordenar(feicoes):
    """Ordena por camada (na ordem fixa) e depois por nome."""

    pesos = {
        CAMADAS[chave][0]: indice
        for indice, chave in enumerate(ORDEM_CAMADAS)
    }

    return sorted(
        feicoes,
        key=lambda feicao: (
            pesos.get(feicao["camada"], len(pesos)),
            feicao["nome"].lower(),
        ),
    )


def consolidar_pontos_mapa(
    texto_resposta,
    metadados_fontes,
    tabelas_extraidas=None,
):
    """Unifica em uma lista os pontos espaciais de uma interação.

    ``metadados_fontes`` é a lista de entradas das fontes consultadas,
    no formato aceito por ``services.table_extractor``::

        {"fonte": "ana", "registros": [ ... ], "titulo": "opcional"}

    ``tabelas_extraidas`` são as tabelas de
    ``services.table_extractor.extrair_tabelas_documento`` /
    ``consolidar_dados_sessao`` (usa ``df_limpo`` ou ``df_bruto``).

    Cada item devolvido traz ``nome``, ``camada``, ``lat``, ``lon``,
    ``detalhe`` e ``cor_hex``, mais a folha CIM que contém o ponto e,
    para folhas citadas como tal, os limites e a escala. A ordem de
    entrada é a das fontes (API, tabelas e, por último, texto), o que
    garante prioridade aos dados estruturados quando o limite de
    feições é aplicado.
    """

    feicoes = []
    feicoes.extend(_feicoes_das_fontes(metadados_fontes))
    feicoes.extend(_feicoes_das_tabelas(tabelas_extraidas))

    # O texto da resposta vem antes dos resumos: se a mesma coordenada
    # for citada nos dois, o detalhe exibido é o da resposta.
    for texto in [texto_resposta, *_resumos_das_fontes(metadados_fontes)]:
        feicoes.extend(extrair_feicoes_espaciais(texto))

    feicoes = _deduplicar(feicoes)
    feicoes = _remover_pontos_textuais_repetidos(feicoes)
    feicoes = _deduplicar(feicoes)

    if len(feicoes) > LIMITE_FEICOES:
        feicoes = feicoes[:LIMITE_FEICOES]

    return _ordenar(feicoes)


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def _formatar_valor_coordenada(valor):
    """Representação numérica estável no CSV (ponto decimal)."""

    if valor is None:
        return ""

    return f"{float(valor):.6f}"


def gerar_csv_pontos(feicoes):
    """CSV UTF-8 (com BOM), separador ``;``, pronto para QGIS.

    O ponto decimal é mantido nas coordenadas de propósito: é o formato
    que o QGIS interpreta como campo numérico sem depender da
    configuração regional, e o BOM garante os acentos no Excel.
    """

    buffer = io.StringIO()
    escritor = csv.writer(
        buffer,
        delimiter=";",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    escritor.writerow(CABECALHO_CSV)

    for feicao in feicoes or []:
        escritor.writerow([
            feicao.get("nome") or "",
            feicao.get("camada") or "",
            _formatar_valor_coordenada(feicao.get("lat")),
            _formatar_valor_coordenada(feicao.get("lon")),
            feicao.get("folha_cim") or "",
            _formatar_valor_coordenada(feicao.get("lat_min")),
            _formatar_valor_coordenada(feicao.get("lat_max")),
            _formatar_valor_coordenada(feicao.get("lon_min")),
            _formatar_valor_coordenada(feicao.get("lon_max")),
            feicao.get("detalhe") or "",
        ])

    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
