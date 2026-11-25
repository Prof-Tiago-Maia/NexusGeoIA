"""Neutralização de fórmulas e exportações seguras (Fase D2).

Dados de APIs públicas, documentos enviados pelo usuário e respostas do
LLM são não confiáveis. Uma célula que começa com "=", "+", "-", "@",
tabulação, retorno de carro ou quebra de linha pode ser interpretada como
fórmula ao abrir o arquivo no Excel, no LibreOffice ou em outro consumidor
de planilhas.

Este módulo concentra a decisão em um único lugar:

* :func:`valor_perigoso` reconhece os prefixos;
* :func:`neutralizar_formula` devolve o valor com apóstrofo de proteção,
  usado nas exportações textuais (CSV e propriedades GeoJSON/QGIS);
* :func:`neutralizar_dataframe` aplica a proteção a colunas e células;
* :func:`gerar_csv_seguro` gera CSV em memória;
* :func:`gerar_geojson_qgis` gera uma camada vetorial GeoJSON pronta para
  arrastar no QGIS;
* :func:`forcar_texto_openpyxl` mantém células perigosas como texto no
  XLSX, sem alterar o valor original.

Nada aqui grava arquivos temporários, abre rede ou depende de
Streamlit. "pandas" já é dependência do projeto; "openpyxl" só é
importado dentro da função que o utiliza.
"""

from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime, timezone

import pandas as pd

# Prefixos que disparam a neutralização. A ordem não importa para o
# startswith, mas documenta exatamente o conjunto exigido pelo Gate D2.
PREFIXOS_FORMULA = ("=", "+", "-", "@", "\t", "\r", "\n")

# Um valor textual que é apenas um número (inclusive negativo, como
# "-3.100000") não pode receber apóstrofo: no CSV/Excel ele precisa ser
# lido como coordenada numérica, não como texto. A expressão aceita os
# formatos que as fontes e o parser de coordenadas produzem: sinal
# opcional, parte inteira ou fracionária, vírgula ou ponto decimal e
# expoente científico.
_NUMERO_TEXTUAL = re.compile(
    r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$"
)

# Marcador visual usado nas exportações textuais. O apóstrofo é o caractere
# que o Excel e o LibreOffice reconhecem como "texto literal" sem alterar a
# leitura do restante da célula.
PREFIXO_NEUTRALIZACAO = "'"

NOME_COLECAO_GEOJSON = "NexusGeoIA_feicoes"
VERSAO_SCHEMA_GEOJSON = 1


def valor_numerico(valor):
    """Diz se o texto representa um número, e não uma fórmula.

    ``-3.100000`` e ``+60.000000`` começam com ``-``/``+``, mas são
    coordenadas válidas. O Excel, o LibreOffice e o QGIS os leem como
    números; prefixar apóstrofo corromperia a coordenada e impediria a
    importação numérica.
    """

    if not isinstance(valor, str):
        return False

    texto = valor.strip()

    if not texto:
        return False

    return _NUMERO_TEXTUAL.fullmatch(texto) is not None


def valor_perigoso(valor):
    """Diz se o valor começa com um prefixo interpretável como fórmula.

    Números textuais ficam de fora: preservar o sinal negativo de uma
    coordenada é requisito da exportação para QGIS e Excel.
    """

    return (
        isinstance(valor, str)
        and valor.startswith(PREFIXOS_FORMULA)
        and not valor_numerico(valor)
    )


def neutralizar_formula(valor):
    """Prefixa apóstrofo quando o texto pode virar fórmula.

    Valores que não são texto (números, None, datas) passam intactos:
    a planilha precisa continuar tratando coordenadas e medidas como
    números.
    """

    if valor_perigoso(valor):
        return PREFIXO_NEUTRALIZACAO + valor

    return valor


def neutralizar_texto(valor):
    """Alias explícito para neutralizar um único valor textual."""

    return neutralizar_formula(valor)


def neutralizar_dataframe(df):
    """Copia o DataFrame e neutraliza colunas e células perigosas."""

    if df is None:
        return df

    copia = df.copy()
    copia.columns = [
        neutralizar_formula(str(coluna)) for coluna in copia.columns
    ]

    return copia.map(neutralizar_formula)


def neutralizar_registros(registros):
    """Neutraliza as chaves e os valores de uma lista de dicionários."""

    saida = []

    for registro in registros or []:
        if not isinstance(registro, dict):
            continue

        item = {}

        for chave, valor in registro.items():
            chave_segura = neutralizar_formula(str(chave))
            item[chave_segura] = neutralizar_formula(valor)

        saida.append(item)

    return saida


def gerar_csv_seguro(
    df,
    *,
    separador=";",
    decimal=",",
    codificacao="utf-8-sig",
    terminador="\r\n",
):
    """Gera CSV em memória aplicando a neutralização antes da escrita."""

    if df is None:
        return b""

    seguro = neutralizar_dataframe(df)
    texto = seguro.to_csv(
        index=False,
        sep=separador,
        decimal=decimal,
        lineterminator=terminador,
    )

    return (codificacao and texto.encode(codificacao)) or texto.encode()


def gerar_xlsx_seguro(df, nome_aba="Feicoes"):
    """Gera um XLSX em memória com células perigosas como texto.

    O valor original é preservado; a neutralização acontece no tipo da
    célula (string em vez de fórmula). Nenhum arquivo temporário é
    gravado.
    """

    import io

    if df is None:
        return b""

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        df.to_excel(escritor, sheet_name=nome_aba[:31], index=False)
        for aba in escritor.book.worksheets:
            forcar_texto_openpyxl(aba)

    return buffer.getvalue()


def _numero_geojson(valor):
    """Converte coordenada em float finito ou devolve None."""

    if isinstance(valor, bool) or valor is None:
        return None

    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None

    return numero if math.isfinite(numero) else None


def _bbox_das_feicoes(feicoes):
    """Bounding box [oeste, sul, leste, norte] das feições válidas."""

    longitudes = [item["lon"] for item in feicoes]
    latitudes = [item["lat"] for item in feicoes]

    if not latitudes or not longitudes:
        return None

    return [
        min(longitudes),
        min(latitudes),
        max(longitudes),
        max(latitudes),
    ]


def gerar_geojson_qgis(feicoes, nome=None):
    """Gera uma camada GeoJSON (WGS84) pronta para o QGIS.

    As propriedades passam por neutralizar_formula; os valores são
    escapados como texto pelo json.dumps, portanto um nome de feição não
    injeta HTML nem fórmula na tabela de atributos. Feições sem
    latitude/longitude válidas são ignoradas.
    """

    features = []

    for feicao in feicoes or []:
        if not isinstance(feicao, dict):
            continue

        lat = _numero_geojson(feicao.get("lat"))
        lon = _numero_geojson(feicao.get("lon"))

        if lat is None or lon is None:
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        propriedades = {
            "nome": feicao.get("nome") or "",
            "camada": feicao.get("camada") or "",
            "folha_cim": feicao.get("folha_cim") or "",
            "detalhe": feicao.get("detalhe") or "",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "cor_hex": feicao.get("cor_hex") or "",
        }

        for chave in ("fonte", "escala", "limites", "origem"):
            if feicao.get(chave) not in (None, ""):
                propriedades[chave] = feicao.get(chave)

        propriedades = {
            neutralizar_formula(str(chave)): neutralizar_formula(valor)
            for chave, valor in propriedades.items()
        }

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 6), round(lat, 6)],
            },
            "properties": propriedades,
        }

        try:
            lat_min = float(feicao.get("lat_min"))
            lat_max = float(feicao.get("lat_max"))
            lon_min = float(feicao.get("lon_min"))
            lon_max = float(feicao.get("lon_max"))
        except (TypeError, ValueError):
            bbox = None
        else:
            if all(
                math.isfinite(valor)
                for valor in (lat_min, lat_max, lon_min, lon_max)
            ):
                bbox = [lon_min, lat_min, lon_max, lat_max]
            else:
                bbox = None

        if bbox is not None:
            feature["bbox"] = bbox

        features.append(feature)

    documento = {
        "type": "FeatureCollection",
        "name": nome or NOME_COLECAO_GEOJSON,
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "metadata": {
            "schema_version": VERSAO_SCHEMA_GEOJSON,
            "gerado_em": datetime.now(timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds"),
            "total_feicoes": len(features),
        },
        "features": features,
    }

    bbox = _bbox_das_feicoes(
        [
            {
                "lat": feature["geometry"]["coordinates"][1],
                "lon": feature["geometry"]["coordinates"][0],
            }
            for feature in features
        ]
    )

    if bbox is not None:
        documento["bbox"] = bbox

    return json.dumps(
        documento,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def forcar_texto_openpyxl(aba):
    """Mantém células perigosas como texto em uma planilha openpyxl.

    O valor original é preservado; o que muda é o data_type, que deixa de
    ser "f" (fórmula) e passa a "s" (string). É a neutralização adequada
    para XLSX, onde o apóstrofo apareceria literalmente para o usuário.
    """

    for linha in aba.iter_rows():
        for celula in linha:
            if valor_perigoso(celula.value):
                celula.data_type = "s"


def descricao_neutralizacao():
    """Texto curto reutilizável em avisos e testes de documentação."""

    return (
        "Células iniciadas por =, +, -, @, tabulação, CR ou LF são "
        "neutralizadas antes da exportação."
    )


def escapar_tooltip(texto):
    """Escapa texto não confiável usado em tooltip do mapa."""

    return html.escape(str(texto or ""))
