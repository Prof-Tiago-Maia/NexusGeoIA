"""Extração, normalização e tipagem de tabelas dos documentos e das APIs.

O módulo é generalista de propósito: não conhece o assunto dos relatórios.
Ele reconhece blocos tabulares Markdown (``| coluna | coluna |``) e grades
separadas por tabulação ou por colunas alinhadas, preserva o título/seção
imediatamente anterior, o nome do documento e a página, e devolve cada
tabela em dois formatos:

- ``df_bruto``: os valores exatamente como aparecem no documento;
- ``df_limpo``: colunas tipadas (números, datas, coordenadas) para
  cálculo, filtragem e exportação para Excel, Pandas e SIG.

A inferência de tipos trata os casos comuns de relatórios técnicos:
separador de milhar, decimal com vírgula, valores abaixo/acima do limite
de detecção (``< 0,5``), dados ausentes (``ND``), intervalos e
coordenadas geográficas. Os qualificadores (``<``, ``>``, ``intervalo``,
``ND``) e as unidades ficam rastreáveis em colunas/metadados próprios, em
vez de serem descartados silenciosamente.

Também consolida os registros estruturados devolvidos pelos conectores
externos da sessão (ANA, SIAGAS, GeoSGB, Macrostrat, GEOSSIT, RIGeo,
OpenAlex, USGS e Web) em tabelas prontas para exploração.
"""

from __future__ import annotations

import io
import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from services import document_parser

# ---------------------------------------------------------------------------
# Limites de segurança
# ---------------------------------------------------------------------------

# Uma tabela maior que isso é truncada (com observação explícita): o
# painel do Streamlit e o Excel não precisam carregar dezenas de milhares
# de linhas de um relatório para a exploração rápida.
MAXIMO_LINHAS_TABELA = 20000

# Evita que um Markdown atípico (ou corrompido) gere milhares de tabelas
# minúsculas e trave a interface.
MAXIMO_TABELAS_DOCUMENTO = 200

# Quantas linhas acima do bloco são inspecionadas em busca de título/seção.
LIMITE_BUSCA_TITULO = 80

# ---------------------------------------------------------------------------
# Padrões de reconhecimento
# ---------------------------------------------------------------------------

PADRAO_CABECALHO_MD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
PADRAO_NEGRITO = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
PADRAO_SEPARADOR_CELULA = re.compile(r"^:?-{2,}:?$")
PADRAO_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
PADRAO_IMAGEM_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# Legendas comuns antes de uma tabela ("Tabela 1 – ...", "Quadro 2 ...").
PADRAO_LEGENDA = re.compile(
    r"^\s*(tabela|quadro|figura|gr[áa]fico|mapa|anexo|ap[êe]ndice)\b",
    re.IGNORECASE,
)

# Unidade entre parênteses ou colchetes no fim do cabeçalho:
# "Profundidade (m)", "Teor [%]", "Vazão (m³/h)".
PADRAO_UNIDADE_CABECALHO = re.compile(
    r"[\(\[]\s*([^\)\]]{1,24})\s*[\)\]]\s*$"
)

# Número "puro" usado como sinal de que uma grade alinhada é tabular.
PADRAO_CELULA_NUMERICA = re.compile(
    r"^\s*(?:[<>≤≥~≈±]\s*)?[-+]?\d+(?:[.,]\d+)?\s*(?:[^\d\s].{0,14})?$"
)

PADRAO_DATA = re.compile(
    r"^\s*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\s*$"
    r"|^\s*\d{4}-\d{2}-\d{2}(?:[T ].*)?\s*$"
)

PADRAO_VALOR_AUSENTE = re.compile(
    r"^(?:nd|n\.?\s?d\.?|n/d|na|n\.?a\.?|nr|n\.?r\.?|"
    r"sem\s+dados?|sem\s+informa[çc][ãa]o|n[ãa]o\s+informado|"
    r"n[ãa]o\s+dispon[íi]vel|[-—–]|\*+)$",
    re.IGNORECASE,
)

# Qualificadores numéricos: limite de detecção, aproximação e erro.
PADRAO_QUALIFICADOR = re.compile(
    r"^\s*(<=|>=|≤|≥|<|>|~|≈|±|aprox\.?|cerca\s+de)\s*",
    re.IGNORECASE,
)

# Intervalo com dois números: "1,2 - 3,4", "10 a 20", "5–9".
PADRAO_INTERVALO = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*"
    r"(?:-|–|—|\bà\b|\ba\b|\baté\b)\s*"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(.*)$",
    re.IGNORECASE,
)

PADRAO_NUMERO = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(.*)$"
)

# Cabeçalhos que nunca devem ser convertidos em número: códigos, nomes,
# classificações e textos. Sem isso, "Código 001" viraria 1 e perderia o
# zero à esquerda justamente na exportação para SIG.
PADRAO_COLUNA_TEXTO = re.compile(
    r"(?:^|\b)("
    r"codigo|código|code|id|identificador|cep|cpf|cnpj|telefone|fone|"
    r"processo|matricula|matrícula|sigla|uf|estado|municipio|município|"
    r"nome|rio|bacia|aquifero|aquífero|substancia|substância|status|"
    r"situacao|situação|tipo|categoria|relevancia|relevância|litologia|"
    r"ambiente|folha|unidade|formacao|formação|autor|autores|titulo|"
    r"título|resumo|link|doi|fonte|observacao|observação|descricao|"
    r"descrição|texto|serie|série|classe|grupo|zona|sistema|interesse|"
    r"pais|país|local|localidade|ponto|estação|estacao"
    r")(?:\b|$)",
    re.IGNORECASE,
)

PADRAO_COLUNA_COORDENADA = re.compile(
    r"coord|coordenad|geogr[áa]fic|lat\s*[/,;]?\s*lon|lon\s*[/,;]?\s*lat",
    re.IGNORECASE,
)

PADRAO_COLUNA_LATITUDE = re.compile(r"^\s*lat(?:itude)?\b", re.IGNORECASE)
PADRAO_COLUNA_LONGITUDE = re.compile(
    r"^\s*(?:lon(?:gitude)?|long)\b", re.IGNORECASE
)

# Cabeçalhos de grandeza: uma coluna vazia (ou com uma única linha) só é
# numérica quando o nome declara que o conteúdo é medida.
PADRAO_COLUNA_NUMERICA = re.compile(
    r"\b(lat|latitude|lon|longitude|altitude|profundidade|nivel|vazao|"
    r"area|valor|numero|populacao|quantidade|total|media|teor|idade_ma|"
    r"ano|peso|comprimento|largura|espessura|diametro|temperatura)\b",
    re.IGNORECASE,
)

# Campos técnicos redundantes nos conectores: o registro traz o mesmo
# conteúdo em ``resumo``/``titulo`` e em colunas específicas. Para não
# duplicar a tabela, eles só aparecem nos esquemas de publicações.
CAMPOS_REDUNDANTES = {"titulo", "autores", "resumo", "link_pdf", "ano"}


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def _texto_limpo(valor: Any) -> str:
    """Converte um valor em texto de uma linha, sem espaços extras."""

    if valor is None:
        return ""

    if isinstance(valor, float) and math.isnan(valor):
        return ""

    texto = str(valor)
    texto = (
        texto.replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\u2212", "-")
        .replace("−", "-")
    )

    return re.sub(r"\s+", " ", texto).strip()


def _remover_formatacao_markdown(texto: str) -> str:
    """Remove negrito, código e links de um texto de cabeçalho."""

    texto = _texto_limpo(texto)
    texto = PADRAO_IMAGEM_MD.sub("", texto)
    texto = PADRAO_LINK_MD.sub(r"\1", texto)
    texto = texto.replace("**", "").replace("__", "").replace("`", "")
    return texto.strip(" :|")


def _chave_comparacao(texto: str) -> str:
    """Chave sem acento e em minúsculas, para comparar cabeçalhos."""

    base = unicodedata.normalize("NFKD", _texto_limpo(texto))
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", " ", base.lower()).strip()
    return re.sub(r"\s+", " ", base)


def _limpar_cabecalhos(cabecalhos: Sequence[Any]) -> list[str]:
    """Limpa cabeçalhos vazios, duplicados e com formatação Markdown.

    Cabeçalho vazio vira ``Coluna N``; nomes repetidos ganham sufixo
    ``(2)``, ``(3)``... para que a tabela tipada e a exportação não
    colapsem duas colunas distintas do documento.
    """

    limpos: list[str] = []
    vistos: dict[str, int] = {}

    for indice, cabecalho in enumerate(cabecalhos, start=1):
        nome = _remover_formatacao_markdown(cabecalho)

        if not nome or set(nome) <= {"-", ":", " "}:
            nome = f"Coluna {indice}"

        chave = _chave_comparacao(nome)
        vistos[chave] = vistos.get(chave, 0) + 1

        if vistos[chave] > 1:
            nome = f"{nome} ({vistos[chave]})"

        limpos.append(nome)

    return limpos


def _unidade_do_cabecalho(cabecalho: str) -> str:
    """Extrai a unidade declarada no cabeçalho, quando existir."""

    achado = PADRAO_UNIDADE_CABECALHO.search(_texto_limpo(cabecalho))

    if not achado:
        return ""

    unidade = achado.group(1).strip()

    # Evita tratar "(2023)" ou "(estimado)" como unidade.
    if not re.search(r"[a-zA-Z%°µμ]", unidade):
        return ""

    return unidade


# ---------------------------------------------------------------------------
# Normalização e leitura de números
# ---------------------------------------------------------------------------

def _normalizar_numero_texto(texto: str, modo: str = "ptbr") -> str:
    """Padroniza separadores decimais/milhar em um texto numérico.

    ``modo="ptbr"`` aplica a convenção dos relatórios brasileiros: ponto
    apenas como milhar quando seguido de exatamente três dígitos
    (``1.234`` -> ``1234``) e vírgula como decimal. ``modo="decimal"``
    preserva o ponto como decimal, usado em coordenadas e em colunas
    lat/lon, onde ``-3.456`` é um valor geográfico e não 3456.
    """

    texto = _texto_limpo(texto)

    if not texto:
        return ""

    # Separador de milhar por espaço: "1 234,56".
    texto = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", texto)

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
        return texto

    if "," in texto:
        partes = texto.split(",")

        if len(partes) > 2 and all(len(parte) == 3 for parte in partes[1:]):
            return texto.replace(",", "")

        return texto.replace(",", ".")

    if "." in texto:
        if modo == "decimal":
            return texto

        partes = texto.split(".")

        if len(partes) > 2 and all(len(parte) == 3 for parte in partes[1:]):
            return texto.replace(".", "")

        if (
            len(partes) == 2
            and len(partes[1]) == 3
            and len(partes[0]) <= 3
            and partes[0].lstrip("+-").isdigit()
        ):
            return texto.replace(".", "")

    return texto


def _ler_numero(
    valor: Any,
    *,
    modo_decimal: bool = False,
) -> tuple[float | None, str, str]:
    """Interpreta um valor numérico e devolve (número, qualificador, unidade).

    - ``ND`` e afins: ``(None, "ND", "")``;
    - ``< 0,5``: ``(0.5, "<", "")`` — o valor é o limite declarado;
    - ``1,2 - 3,4``: ``(2.3, "intervalo 1,2–3,4", "")``;
    - ``12,5 mg/L``: ``(12.5, "", "mg/L")``;
    - texto não numérico: ``(None, "não numérico", "")``.
    """

    texto = _texto_limpo(valor)

    if not texto:
        return None, "", ""

    if PADRAO_VALOR_AUSENTE.match(texto):
        return None, "ND", ""

    qualificador = ""
    achado_qualificador = PADRAO_QUALIFICADOR.match(texto)

    if achado_qualificador:
        qualificador = achado_qualificador.group(1).strip()
        texto = texto[achado_qualificador.end():].strip()

    modo = "decimal" if modo_decimal else "ptbr"
    texto_normalizado = _normalizar_numero_texto(texto, modo=modo)

    # Intervalo: usa o ponto médio e guarda os extremos no qualificador.
    achado_intervalo = PADRAO_INTERVALO.match(texto_normalizado)

    if achado_intervalo:
        inicio = float(achado_intervalo.group(1))
        fim = float(achado_intervalo.group(2))
        unidade = _unidade_do_sufixo(achado_intervalo.group(3))
        rotulo = f"intervalo {_formatar_numero_pt(inicio)}–{_formatar_numero_pt(fim)}"

        return (inicio + fim) / 2, rotulo, unidade

    achado_numero = PADRAO_NUMERO.match(texto_normalizado)

    if not achado_numero:
        return None, "não numérico", ""

    try:
        numero = float(achado_numero.group(1))
    except ValueError:
        return None, "não numérico", ""

    unidade = _unidade_do_sufixo(achado_numero.group(2))

    return numero, qualificador, unidade


def _unidade_do_sufixo(sufixo: str) -> str:
    """Reconhece a unidade que acompanha um número (``12,5 mg/L``)."""

    sufixo = _texto_limpo(sufixo).strip("()[] ")

    if not sufixo:
        return ""

    # Unidades curtas e com letra/símbolo; descrições longas não são
    # unidade e ficam de fora para não poluir os metadados.
    if len(sufixo) <= 16 and re.search(r"[a-zA-Z%°µμ]", sufixo):
        return sufixo

    return ""


def _formatar_numero_pt(numero: float) -> str:
    """Formata um número com vírgula decimal, para exibição em pt-BR."""

    if numero == int(numero):
        return str(int(numero))

    return f"{numero:g}".replace(".", ",")


def _coluna_e_texto(cabecalho: str) -> bool:
    """Diz se o cabeçalho obriga a coluna a permanecer textual."""

    return bool(PADRAO_COLUNA_TEXTO.search(_chave_comparacao(cabecalho)))


def _coluna_e_coordenada(cabecalho: str) -> bool:
    """Diz se o cabeçalho representa um par de coordenadas."""

    return bool(
        PADRAO_COLUNA_COORDENADA.search(cabecalho)
        and not PADRAO_COLUNA_LATITUDE.match(cabecalho)
        and not PADRAO_COLUNA_LONGITUDE.match(cabecalho)
    )


def _modo_decimal_da_coluna(cabecalho: str) -> bool:
    """Coordenadas usam ponto decimal; as demais colunas, convenção PT-BR."""

    return bool(
        PADRAO_COLUNA_COORDENADA.search(cabecalho)
        or PADRAO_COLUNA_LATITUDE.match(cabecalho)
        or PADRAO_COLUNA_LONGITUDE.match(cabecalho)
    )


def _coluna_parece_numerica(cabecalho: str) -> bool:
    """Diz se o cabeçalho declara uma grandeza numérica."""

    chave = _chave_comparacao(cabecalho)

    return bool(
        PADRAO_UNIDADE_CABECALHO.search(cabecalho)
        or PADRAO_COLUNA_NUMERICA.search(chave)
    )


def _ler_par_coordenadas(valor: Any) -> tuple[float, float] | None:
    """Lê ``"lat, lon"``/``"-3,45 -60,12"`` e valida os limites geográficos."""

    texto = _texto_limpo(valor)

    if not texto:
        return None

    # Números com vírgula ou ponto decimal, isolados de pontuação.
    numeros = re.findall(r"[-+]?\d+(?:[.,]\d+)?", texto)

    if len(numeros) != 2:
        return None

    try:
        primeiro = float(numeros[0].replace(",", "."))
        segundo = float(numeros[1].replace(",", "."))
    except ValueError:
        return None

    if -90 <= primeiro <= 90 and -180 <= segundo <= 180:
        return primeiro, segundo

    if -90 <= segundo <= 90 and -180 <= primeiro <= 180:
        # Ordem invertida (lon, lat) é comum em planilhas.
        return segundo, primeiro

    return None


# ---------------------------------------------------------------------------
# Tipagem de um DataFrame bruto
# ---------------------------------------------------------------------------

def _serie_texto(df: pd.DataFrame, coluna: str) -> pd.Series:
    """Série textual da coluna, sem nulos e sem quebras de linha."""

    serie = df[coluna]

    return serie.map(_texto_limpo)


def _detectar_coluna_numerica(cabecalho: str, valores: Sequence[str]) -> bool:
    """Decide se a coluna deve ser numérica na tabela tipada."""

    if _coluna_e_texto(cabecalho):
        return False

    # O par "lat, lon" não é um número único: a coluna original continua
    # textual e a expansão em Latitude/Longitude acontece depois.
    if _coluna_e_coordenada(cabecalho):
        return False

    nao_vazios = [valor for valor in valores if valor]
    modo_decimal = _modo_decimal_da_coluna(cabecalho)

    if not nao_vazios:
        # Coluna inteira vazia: se o nome declara uma grandeza, ela nasce
        # numérica (NaN) para manter o mesmo tipo nas exportações.
        return _coluna_parece_numerica(cabecalho)

    # Colunas de data ("12/03/2023") não podem virar o número 12.
    datas = sum(1 for valor in nao_vazios if PADRAO_DATA.match(valor))

    if datas / len(nao_vazios) >= 0.7:
        return False

    numeros = 0
    ausentes = 0

    for valor in nao_vazios:
        numero, qualificador, _ = _ler_numero(
            valor, modo_decimal=modo_decimal
        )

        if numero is not None:
            numeros += 1
        elif qualificador == "ND":
            ausentes += 1

    if numeros == 0:
        return False

    proporcao = (numeros + ausentes) / len(nao_vazios)

    # Uma única linha só vira número quando o valor é numérico e o
    # cabeçalho não é de código/nome, ou quando o nome declara grandeza.
    if len(nao_vazios) == 1:
        return proporcao >= 1.0 and (
            _coluna_parece_numerica(cabecalho)
            or not _coluna_e_texto(cabecalho)
        )

    return proporcao >= 0.6


def _detectar_coluna_data(cabecalho: str, valores: Sequence[str]) -> bool:
    """Decide se a coluna deve ser convertida em data/hora."""

    if _coluna_e_texto(cabecalho):
        return False

    nao_vazios = [valor for valor in valores if valor]

    if len(nao_vazios) < 2:
        return False

    datas = sum(1 for valor in nao_vazios if PADRAO_DATA.match(valor))

    return datas / len(nao_vazios) >= 0.7


def _converter_numerico(series: pd.Series, modo_decimal: bool) -> pd.Series:
    """Converte textos em números, preservando ausentes e qualificadores."""

    valores: list[float | None] = []

    for valor in series:
        numero, _, _ = _ler_numero(valor, modo_decimal=modo_decimal)
        valores.append(numero)

    convertido = pd.to_numeric(pd.Series(valores, index=series.index), errors="coerce")

    # Colunas só com inteiros ficam como Int64: evita "2019.0" no Excel e
    # mantém valores ausentes representáveis.
    validos = convertido.dropna()

    if not validos.empty and (validos % 1 == 0).all() and validos.abs().max() < 1e15:
        return convertido.astype("Int64")

    return convertido.astype(float)


def _tipar_dataframe(
    df_bruto: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Gera a tabela tipada e os metadados de tipagem de ``df_bruto``.

    Cada coluna numérica ganha, quando necessário, uma coluna vizinha
    ``<nome> (qualificador)`` com ``<``, ``>``, ``ND``, ``intervalo...``
    ou ``não numérico``. As unidades ficam em ``unidades`` e também no
    próprio cabeçalho original.
    """

    dados_limpos: dict[str, pd.Series] = {}
    unidades: dict[str, str] = {}
    colunas_numericas: list[str] = []
    colunas_data: list[str] = []
    qualificadores_usados: list[str] = []

    for coluna in df_bruto.columns:
        valores = _serie_texto(df_bruto, coluna).tolist()
        unidade = _unidade_do_cabecalho(coluna)

        if unidade:
            unidades[coluna] = unidade

        if _detectar_coluna_data(coluna, valores):
            serie = pd.to_datetime(
                pd.Series(valores, index=df_bruto.index),
                dayfirst=True,
                errors="coerce",
                format="mixed",
            )

            if serie.notna().any():
                dados_limpos[coluna] = serie
                colunas_data.append(coluna)
                continue

        if _detectar_coluna_numerica(coluna, valores):
            modo_decimal = _modo_decimal_da_coluna(coluna)
            coluna_limpa = coluna
            contador = 1

            while coluna_limpa in dados_limpos:
                contador += 1
                coluna_limpa = f"{coluna} ({contador})"

            dados_limpos[coluna_limpa] = _converter_numerico(
                pd.Series(valores, index=df_bruto.index),
                modo_decimal=modo_decimal,
            )
            colunas_numericas.append(coluna_limpa)

            qualificadores = []
            unidades_detectadas = [
                _ler_numero(valor, modo_decimal=modo_decimal)[2]
                for valor in valores
            ]

            for valor in valores:
                numero, qualificador, _ = _ler_numero(
                    valor, modo_decimal=modo_decimal
                )

                if numero is None and qualificador:
                    qualificadores.append(qualificador)
                elif numero is not None and qualificador:
                    qualificadores.append(qualificador)
                elif valor:
                    qualificadores.append("")
                else:
                    qualificadores.append("")

            if any(qualificadores):
                nome_qualificador = f"{coluna_limpa} (qualificador)"
                dados_limpos[nome_qualificador] = pd.Series(
                    qualificadores, index=df_bruto.index, dtype=object
                )
                qualificadores_usados.append(nome_qualificador)

            # Unidade inferida dos valores quando o cabeçalho não declara.
            if not unidade:
                detectadas = [
                    item for item in unidades_detectadas if item
                ]

                if detectadas:
                    unidades[coluna_limpa] = max(
                        set(detectadas), key=detectadas.count
                    )

            continue

        if _detectar_coluna_data(coluna, valores):
            serie = pd.to_datetime(
                pd.Series(valores, index=df_bruto.index),
                dayfirst=True,
                errors="coerce",
                format="mixed",
            )

            if serie.notna().any():
                dados_limpos[coluna] = serie
                colunas_data.append(coluna)
                continue

        texto = pd.Series(
            [valor if valor else None for valor in valores],
            index=df_bruto.index,
            dtype=object,
        )
        dados_limpos[coluna] = texto

    df_limpo = pd.DataFrame(dados_limpos, index=df_bruto.index)

    # Pares de coordenadas: além da coluna textual original, cria
    # Latitude/Longitude numéricas, prontas para o QGIS.
    for coluna in list(df_bruto.columns):
        if not _coluna_e_coordenada(coluna):
            continue

        pares = [_ler_par_coordenadas(valor) for valor in df_bruto[coluna]]

        validos = [par for par in pares if par is not None]

        if len(validos) < max(1, math.ceil(0.7 * len(pares))):
            continue

        nome_lat = "Latitude"
        nome_lon = "Longitude"
        contador = 1

        while nome_lat in df_limpo.columns or nome_lon in df_limpo.columns:
            contador += 1
            nome_lat = f"Latitude ({contador})"
            nome_lon = f"Longitude ({contador})"

        df_limpo[nome_lat] = pd.Series(
            [par[0] if par else None for par in pares],
            index=df_bruto.index,
            dtype=float,
        )
        df_limpo[nome_lon] = pd.Series(
            [par[1] if par else None for par in pares],
            index=df_bruto.index,
            dtype=float,
        )
        colunas_numericas.extend([nome_lat, nome_lon])

    metadados = {
        "unidades": unidades,
        "colunas_numericas": colunas_numericas,
        "colunas_data": colunas_data,
        "qualificadores": qualificadores_usados,
    }

    df_limpo.attrs["unidades"] = dict(unidades)
    df_limpo.attrs["colunas_numericas"] = list(colunas_numericas)

    return df_limpo, metadados


def normalizar_dataframe(
    df_bruto: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Expõe a tipagem para quem já tem um DataFrame bruto em mãos."""

    return _tipar_dataframe(df_bruto)


# ---------------------------------------------------------------------------
# Reconhecimento de blocos tabulares
# ---------------------------------------------------------------------------

def _e_linha_markdown(linha: str) -> bool:
    """Diz se a linha pertence a uma tabela Markdown com barras."""

    texto = linha.strip()

    if not texto.startswith("|"):
        return False

    return len(re.findall(r"(?<!\\)\|", texto)) >= 2


def _dividir_linha_markdown(linha: str) -> list[str]:
    r"""Divide uma linha Markdown em células, respeitando ``\|`` escapado."""

    texto = linha.strip()

    if texto.startswith("|"):
        texto = texto[1:]

    if texto.endswith("|") and not texto.endswith("\\|"):
        texto = texto[:-1]

    celulas = re.split(r"(?<!\\)\|", texto)
    return [
        celula.replace("\\|", "|").strip()
        for celula in celulas
    ]


def _e_linha_separadora(celulas: Sequence[str]) -> bool:
    """Diz se a linha é apenas o separador ``| --- | :---: |``."""

    if not celulas:
        return False

    return all(
        PADRAO_SEPARADOR_CELULA.match(celula.strip()) for celula in celulas
    )


def _ajustar_linha(celulas: Sequence[str], quantidade: int) -> list[str]:
    """Padroniza a quantidade de células de uma linha."""

    ajustada = list(celulas[:quantidade])

    if len(ajustada) < quantidade:
        ajustada.extend([""] * (quantidade - len(ajustada)))

    return ajustada


def _e_linha_grade_candidata(linha: str) -> bool:
    """Diz se a linha pode pertencer a uma grade alinhada/tabulada."""

    texto = linha.strip()

    if not texto or _e_linha_markdown(linha):
        return False

    if texto.startswith(("#", "-", "*", ">", "!", "<!--")):
        return False

    if PADRAO_CABECALHO_MD.match(texto):
        return False

    if "\t" in linha:
        return len([c for c in linha.split("\t") if c.strip()]) >= 2

    return len([c for c in re.split(r"\s{2,}", texto) if c]) >= 2


def _dividir_linha_grade(linha: str) -> list[str]:
    """Divide uma grade por tabulação ou por duas ou mais colunas de espaço."""

    if "\t" in linha:
        celulas = linha.split("\t")
    else:
        celulas = re.split(r"\s{2,}", linha.strip())

    celulas = [celula.strip() for celula in celulas]

    # Remove células vazias nas pontas criadas pela indentação.
    while celulas and not celulas[0]:
        celulas.pop(0)

    while celulas and not celulas[-1]:
        celulas.pop()

    return celulas


def _ler_grade(
    linhas: Sequence[str],
    inicio: int,
) -> tuple[list[str], list[list[str]], int] | None:
    """Lê uma grade alinhada a partir de ``inicio``.

    Devolve ``(cabecalho, linhas, proximo_indice)`` ou ``None``. A grade
    só é aceita com pelo menos três linhas, colunas consistentes e sinal
    numérico em metade das linhas — o que evita transformar parágrafos
    alinhados em tabela.
    """

    primeira = _dividir_linha_grade(linhas[inicio])
    quantidade = len(primeira)

    if quantidade < 2:
        return None

    blocos: list[list[str]] = [primeira]
    indice = inicio + 1

    while indice < len(linhas) and _e_linha_grade_candidata(linhas[indice]):
        celulas = _dividir_linha_grade(linhas[indice])

        if len(celulas) != quantidade:
            break

        blocos.append(celulas)
        indice += 1

    if len(blocos) < 3:
        return None

    linhas_com_numero = sum(
        1
        for bloco in blocos
        if any(PADRAO_CELULA_NUMERICA.match(celula) for celula in bloco if celula)
    )

    if linhas_com_numero < math.ceil(len(blocos) / 2):
        return None

    # A primeira linha é o cabeçalho quando as demais têm predominância
    # de números; sem isso, todas as linhas entram como dados.
    primeira_e_cabecalho = not all(
        PADRAO_CELULA_NUMERICA.match(celula)
        for celula in primeira
        if celula
    )

    if primeira_e_cabecalho:
        return primeira, blocos[1:], indice

    return [f"Coluna {posicao}" for posicao in range(1, quantidade + 1)], blocos, indice


def _parece_legenda(texto: str) -> bool:
    """Diz se um texto anterior tem cara de legenda de tabela/figura."""

    texto = _texto_limpo(texto)

    if not texto:
        return False

    if PADRAO_LEGENDA.match(texto):
        return True

    # Linha curta, sem ponto final: título de seção ou descrição breve.
    return (
        len(texto) <= 90
        and len(texto.split()) <= 14
        and not re.search(r"[.!?]$", texto)
    )


def _procurar_titulo(
    linhas: Sequence[str],
    indice: int,
) -> tuple[str, str]:
    """Busca o título/seção imediatamente anterior ao bloco.

    Devolve ``(titulo, secao)``. A legenda imediatamente acima
    ("Tabela 3 – ...") tem prioridade; sem ela, usa o último cabeçalho da
    página e evita transformar o parágrafo de abertura da seção no
    título da tabela.
    """

    proximo_texto = ""
    secao = ""
    nao_vazias = 0

    limite = max(-1, indice - LIMITE_BUSCA_TITULO)

    for posicao in range(indice - 1, limite, -1):
        linha = linhas[posicao].strip()

        if not linha:
            continue

        if _e_linha_markdown(linha):
            continue

        nao_vazias += 1
        achado_cabecalho = PADRAO_CABECALHO_MD.match(linha)

        if achado_cabecalho:
            texto = _remover_formatacao_markdown(achado_cabecalho.group(2))

            if texto:
                secao = secao or texto

            # A legenda encontrada logo acima tem prioridade sobre o
            # título da seção a que a tabela pertence.
            return (proximo_texto or secao or ""), secao

        achado_negrito = PADRAO_NEGRITO.match(linha)

        if achado_negrito and nao_vazias <= 3:
            texto = _remover_formatacao_markdown(achado_negrito.group(1))

            if texto:
                return texto, secao or texto

        if not proximo_texto and nao_vazias <= 3 and _parece_legenda(linha):
            proximo_texto = _remover_formatacao_markdown(linha)

    return proximo_texto, secao


def _titulo_padrao(nome_documento: str, pagina: int | None) -> str:
    """Título de reserva quando o bloco não tem texto anterior."""

    local = f"página {pagina}" if pagina else "documento sem paginação"

    return f"{nome_documento} — {local}"


# ---------------------------------------------------------------------------
# Extração de um documento
# ---------------------------------------------------------------------------

def _montar_tabela(
    *,
    titulo: str,
    secao: str,
    origem: str,
    caminho: str,
    pagina: int | None,
    formato: str,
    cabecalho: Sequence[str],
    linhas: Sequence[Sequence[str]],
    indice: int,
) -> dict[str, Any] | None:
    """Monta o dicionário público de uma tabela extraída."""

    cabecalhos = _limpar_cabecalhos(cabecalho)
    quantidade = len(cabecalhos)

    if quantidade < 2:
        return None

    linhas_ajustadas = [
        _ajustar_linha(linha, quantidade)
        for linha in linhas
        if any(_texto_limpo(celula) for celula in linha)
    ]

    observacoes: list[str] = []

    if len(linhas_ajustadas) > MAXIMO_LINHAS_TABELA:
        observacoes.append(
            f"Tabela truncada em {MAXIMO_LINHAS_TABELA} linhas."
        )
        linhas_ajustadas = linhas_ajustadas[:MAXIMO_LINHAS_TABELA]

    if not linhas_ajustadas:
        return None

    df_bruto = pd.DataFrame(linhas_ajustadas, columns=cabecalhos)
    df_limpo, metadados_tipagem = _tipar_dataframe(df_bruto)

    return {
        "id": f"{Path(caminho).name}:{pagina or 0}:{indice}",
        "titulo": titulo or _titulo_padrao(Path(caminho).name, pagina),
        "secao": secao,
        "origem": origem,
        "caminho": caminho,
        "pagina": pagina,
        "formato": formato,
        "df_bruto": df_bruto,
        "df_limpo": df_limpo,
        "unidades": metadados_tipagem["unidades"],
        "colunas_numericas": metadados_tipagem["colunas_numericas"],
        "colunas_data": metadados_tipagem["colunas_data"],
        "qualificadores": metadados_tipagem["qualificadores"],
        "observacoes": observacoes,
    }


def extrair_tabelas_documento(caminho_md: str) -> list[dict]:
    """Extrai todas as tabelas de um Markdown higienizado.

    O arquivo é lido como o Markdown que já está em ``data/cache_md`` (a
    conversão de PDFs acontece em :mod:`services.document_parser`). Cada
    bloco reconhecido devolve ``titulo``, ``origem``, ``pagina``,
    ``df_bruto`` e ``df_limpo``, além de metadados de tipagem.

    São reconhecidos:

    - tabelas Markdown com barras (com ou sem a linha ``| --- |``);
    - grades separadas por tabulação;
    - grades com colunas alinhadas por dois ou mais espaços.

    A página vem dos marcadores ``<!-- Página X -->`` gerados na
    conversão; um Markdown sem marcadores devolve ``pagina=None``.
    """

    caminho = Path(caminho_md)

    if not caminho.is_file():
        raise FileNotFoundError(
            f"Markdown não encontrado para extração de tabelas: {caminho}"
        )

    texto = caminho.read_text(encoding="utf-8", errors="replace")
    blocos = document_parser.extrair_blocos_markdown(texto)

    tabelas: list[dict] = []
    indice_tabela = 0

    for conteudo, pagina in blocos:
        linhas = conteudo.splitlines()
        posicao = 0

        while posicao < len(linhas) and len(tabelas) < MAXIMO_TABELAS_DOCUMENTO:
            linha = linhas[posicao]

            if _e_linha_markdown(linha):
                inicio_bloco = posicao
                bloco: list[list[str]] = []

                while posicao < len(linhas) and _e_linha_markdown(linhas[posicao]):
                    bloco.append(_dividir_linha_markdown(linhas[posicao]))
                    posicao += 1

                if len(bloco) < 2 or _e_linha_separadora(bloco[0]):
                    continue

                if _e_linha_separadora(bloco[1]):
                    cabecalho = bloco[0]
                    corpo = bloco[2:]
                elif all(
                    PADRAO_CELULA_NUMERICA.match(celula)
                    for celula in bloco[0]
                    if celula
                ):
                    # Tabela sem cabeçalho: a primeira linha já é dado.
                    cabecalho = [
                        f"Coluna {posicao}"
                        for posicao in range(1, len(bloco[0]) + 1)
                    ]
                    corpo = bloco
                else:
                    cabecalho = bloco[0]
                    corpo = bloco[1:]

                if not corpo:
                    continue

                titulo, secao = _procurar_titulo(linhas, inicio_bloco)
                indice_tabela += 1

                tabela = _montar_tabela(
                    titulo=titulo,
                    secao=secao,
                    origem=caminho.name,
                    caminho=str(caminho),
                    pagina=pagina,
                    formato="markdown",
                    cabecalho=cabecalho,
                    linhas=corpo,
                    indice=indice_tabela,
                )

                if tabela:
                    tabelas.append(tabela)

                continue

            if _e_linha_grade_candidata(linha):
                leitura = _ler_grade(linhas, posicao)

                if leitura:
                    cabecalho, corpo, proximo = leitura
                    titulo, secao = _procurar_titulo(linhas, posicao)
                    indice_tabela += 1

                    tabela = _montar_tabela(
                        titulo=titulo,
                        secao=secao,
                        origem=caminho.name,
                        caminho=str(caminho),
                        pagina=pagina,
                        formato="grade",
                        cabecalho=cabecalho,
                        linhas=corpo,
                        indice=indice_tabela,
                    )

                    if tabela:
                        tabelas.append(tabela)
                        posicao = proximo
                        continue

            posicao += 1

    return tabelas


# ---------------------------------------------------------------------------
# Consolidação das fontes externas da sessão
# ---------------------------------------------------------------------------

# Rótulos amigáveis e ordem preferencial das colunas por conector. Campos
# que não estão aqui são acrescentados no fim, com o cabeçalho limpo: uma
# API nova continua funcionando sem alterar este módulo.
ESQUEMAS_FONTES: dict[str, dict[str, Any]] = {
    "ana": {
        "rotulo": "ANA / HidroWeb",
        "colunas": {
            "codigo": "Código",
            "nome": "Estação",
            "tipo": "Tipo",
            "rio": "Rio",
            "municipio": "Município",
            "uf": "UF",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "status": "Status",
            "fonte": "Fonte",
            "link": "Link",
        },
    },
    "siagas": {
        "rotulo": "SIAGAS / RIMAS",
        "colunas": {
            "codigo": "Código",
            "nome_ponto": "Nome do ponto",
            "municipio": "Município",
            "uf": "UF",
            "profundidade": "Profundidade (m)",
            "ne": "Nível estático (m)",
            "nd": "Nível dinâmico (m)",
            "vazao": "Vazão",
            "vazao_unidade": "Unidade da vazão",
            "vazao_especifica": "Vazão específica",
            "aquifero": "Aquífero",
            "natureza": "Natureza",
            "uso_agua": "Uso da água",
            "situacao": "Situação",
            "bacia": "Bacia",
            "lat": "Latitude",
            "lon": "Longitude",
            "link_detalhe": "Detalhe",
        },
    },
    "geosgb": {
        "rotulo": "GeoSGB / Ocorrências Minerais",
        "colunas": {
            "nome_alvo": "Alvo",
            "substancia": "Substância",
            "status": "Status",
            "municipio": "Município",
            "uf": "UF",
            "folha": "Folha",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "id_ocorrencia": "ID da ocorrência",
            "link": "Link",
        },
    },
    "macrostrat": {
        "rotulo": "Macrostrat",
        "colunas": {
            "unidade": "Unidade",
            "idade": "Idade",
            "idade_ma": "Idade (Ma)",
            "litologia": "Litologia",
            "ambiente": "Ambiente",
            "bacia": "Bacia",
            "lat": "Latitude",
            "lon": "Longitude",
        },
    },
    "geossit": {
        "rotulo": "INDE / GEOSSIT",
        "colunas": {
            "nome": "Geossítio",
            "categoria": "Interesse",
            "municipio": "Município",
            "uf": "UF",
            "relevancia": "Relevância",
            "lat": "Latitude",
            "lon": "Longitude",
        },
    },
    "sgb": {
        "rotulo": "Acervo SGB / RIGeo",
        "colunas": {
            "titulo": "Título",
            "autores": "Autores",
            "ano": "Ano",
            "resumo": "Resumo",
            "link": "Link",
            "link_pdf": "PDF",
            "fonte": "Fonte",
        },
    },
    "openalex": {
        "rotulo": "OpenAlex",
        "colunas": {
            "titulo": "Título",
            "autores": "Autores",
            "ano": "Ano",
            "resumo": "Resumo",
            "link": "Link",
            "link_pdf": "PDF",
            "fonte": "Fonte",
        },
    },
    "usgs": {
        "rotulo": "USGS ScienceBase",
        "colunas": {
            "titulo": "Título",
            "autores": "Autores",
            "ano": "Ano",
            "resumo": "Resumo",
            "link": "Link",
            "link_pdf": "PDF",
            "fonte": "Fonte",
        },
    },
    "web": {
        "rotulo": "Pesquisa na Web",
        "colunas": {
            "titulo": "Título",
            "autores": "Domínio",
            "ano": "Ano",
            "resumo": "Resumo",
            "link": "Link",
            "link_pdf": "PDF",
            "fonte": "Fonte",
        },
    },
}

# Apelidos aceitos para a chave da fonte (``fonte`` dos metadados).
APELIDOS_FONTES = {
    "ana": "ana",
    "hidroweb": "ana",
    "ana / hidroweb": "ana",
    "siagas": "siagas",
    "rimas": "siagas",
    "geosgb": "geosgb",
    "macrostrat": "macrostrat",
    "geossit": "geossit",
    "inde": "geossit",
    "sgb": "sgb",
    "rigeo": "sgb",
    "openalex": "openalex",
    "usgs": "usgs",
    "sciencebase": "usgs",
    "web": "web",
}


def chave_registro(registro: dict) -> str:
    """Chave estável para deduplicar registros de diferentes respostas.

    Combina os campos que identificam o registro (código, DOI, alvo,
    unidade, título, link) com as coordenadas. Vários campos entram
    juntos porque alguns conectores repetem o mesmo link institucional em
    todos os registros: usar só o link colapsaria todas as estações da
    ANA ou todos os poços do SIAGAS em uma única linha.
    """

    if not isinstance(registro, dict):
        return json.dumps(registro, ensure_ascii=False, sort_keys=True, default=str)

    identidade = []

    for campo in (
        "codigo",
        "id_ocorrencia",
        "doi",
        "link_detalhe",
        "nome_alvo",
        "unidade",
        "titulo",
        "nome",
        "link",
        "link_pdf",
    ):
        valor = _texto_limpo(registro.get(campo))

        if valor:
            identidade.append(f"{campo}={valor}")

    latitude = _texto_limpo(registro.get("lat"))
    longitude = _texto_limpo(registro.get("lon"))

    if identidade or latitude or longitude:
        identidade.append(f"lat={latitude}")
        identidade.append(f"lon={longitude}")
        return "|".join(identidade)

    return json.dumps(registro, ensure_ascii=False, sort_keys=True, default=str)


def _resolver_fonte(nome: Any) -> str:
    """Resolve ``fonte``/``origem`` para uma chave de esquema conhecida."""

    chave = _chave_comparacao(nome)

    if chave in APELIDOS_FONTES:
        return APELIDOS_FONTES[chave]

    for apelido, destino in APELIDOS_FONTES.items():
        if apelido and apelido in chave:
            return destino

    return ""


def _registros_da_entrada(entrada: dict) -> list[dict]:
    """Obtém a lista de registros de uma entrada de metadados."""

    candidatos: Iterable[Any] = (
        entrada.get("registros")
        or entrada.get("dados")
        or entrada.get("itens")
        or []
    )

    if isinstance(candidatos, dict):
        candidatos = candidatos.get("registros") or []

    registros: list[dict] = []

    for item in candidatos:
        if isinstance(item, dict):
            registros.append(item)
        elif item is not None:
            registros.append({"valor": item})

    return registros


def _dataframe_da_fonte(
    registros: Sequence[dict],
    chave_fonte: str,
) -> pd.DataFrame:
    """Monta o DataFrame bruto de uma fonte, na ordem do esquema."""

    esquema = ESQUEMAS_FONTES.get(chave_fonte, {})
    colunas_mapeadas: dict[str, str] = dict(esquema.get("colunas") or {})

    # Ordem de primeira aparição como reserva para fontes desconhecidas.
    chaves_originais: list[str] = []

    for registro in registros:
        for campo in registro:
            if campo not in chaves_originais:
                chaves_originais.append(campo)

    definidas = [campo for campo in colunas_mapeadas if campo in chaves_originais]
    restantes = [campo for campo in chaves_originais if campo not in colunas_mapeadas]

    if esquema and chave_fonte not in {"sgb", "openalex", "usgs", "web"}:
        restantes = [campo for campo in restantes if campo not in CAMPOS_REDUNDANTES]

    ordem = definidas + restantes

    if not ordem:
        return pd.DataFrame()

    cabecalhos = [
        colunas_mapeadas.get(campo, _remover_formatacao_markdown(campo) or campo)
        for campo in ordem
    ]
    cabecalhos = _limpar_cabecalhos(cabecalhos)

    linhas = [
        [_texto_celula(registro.get(campo)) for campo in ordem]
        for registro in registros
    ]

    return pd.DataFrame(linhas, columns=cabecalhos)


def _texto_celula(valor: Any) -> str:
    """Representação textual de um valor de registro, para ``df_bruto``."""

    if valor is None:
        return ""

    # Listas e dicionários (tags, autores, geometrias) viram JSON: a
    # célula continua legível e, ao contrário de "1; 2", não é confundida
    # com um único número na inferência de tipos.
    if isinstance(valor, (list, tuple, dict)):
        return json.dumps(valor, ensure_ascii=False, default=str)

    if isinstance(valor, bool):
        return "Sim" if valor else "Não"

    if isinstance(valor, float):
        if math.isnan(valor):
            return ""
        return f"{valor:g}" if valor != int(valor) else str(int(valor))

    return _texto_limpo(valor)


def consolidar_dados_sessao(metadados_fontes: list[dict]) -> list[dict]:
    """Converte os registros das APIs da sessão em tabelas exploráveis.

    ``metadados_fontes`` é uma lista de entradas, uma por fonte, no
    formato::

        {
            "fonte": "ana" | "siagas" | "geosgb" | "macrostrat" |
                     "geossit" | "sgb" | "openalex" | "usgs" | "web",
            "registros": [ {...}, {...} ],
            "titulo": "opcional",
            "pagina": None,
            "origem": "opcional",
        }

    As chaves conhecidas são renomeadas e ordenadas pelo esquema do
    conector; fontes novas são aceitas com as colunas na ordem em que
    aparecem. Cada tabela devolve o mesmo contrato da extração de
    documentos (``titulo``, ``origem``, ``pagina``, ``df_bruto``,
    ``df_limpo``) e é deduplicada por :func:`chave_registro`.
    """

    if isinstance(metadados_fontes, dict):
        metadados_fontes = [metadados_fontes]

    tabelas: list[dict] = []

    for indice_entrada, entrada in enumerate(metadados_fontes or [], start=1):
        if not isinstance(entrada, dict):
            continue

        registros = _registros_da_entrada(entrada)

        if not registros:
            continue

        # Deduplica preservando a ordem de chegada.
        vistos: set[str] = set()
        unicos: list[dict] = []

        for registro in registros:
            chave = chave_registro(registro)

            if chave in vistos:
                continue

            vistos.add(chave)
            unicos.append(registro)

        chave_fonte = _resolver_fonte(
            entrada.get("fonte") or entrada.get("origem") or ""
        )
        rotulo = (
            ESQUEMAS_FONTES.get(chave_fonte, {}).get("rotulo")
            or _texto_limpo(entrada.get("rotulo"))
            or _texto_limpo(entrada.get("fonte"))
            or f"Fonte {indice_entrada}"
        )

        df_bruto = _dataframe_da_fonte(unicos, chave_fonte)

        if df_bruto.empty:
            continue

        df_limpo, metadados_tipagem = _tipar_dataframe(df_bruto)
        titulo = (
            _texto_limpo(entrada.get("titulo"))
            or f"{rotulo} ({len(df_bruto)} registro(s))"
        )

        tabelas.append(
            {
                "id": f"sessao:{chave_fonte or 'generico'}:{indice_entrada}",
                "titulo": titulo,
                "secao": rotulo,
                "origem": _texto_limpo(entrada.get("origem"))
                or f"Sessão · {rotulo}",
                "caminho": "",
                "pagina": entrada.get("pagina"),
                "formato": "api",
                "df_bruto": df_bruto,
                "df_limpo": df_limpo,
                "unidades": metadados_tipagem["unidades"],
                "colunas_numericas": metadados_tipagem["colunas_numericas"],
                "colunas_data": metadados_tipagem["colunas_data"],
                "qualificadores": metadados_tipagem["qualificadores"],
                "observacoes": [
                    f"{len(registros) - len(unicos)} registro(s) duplicado(s) removido(s)."
                ]
                if len(registros) > len(unicos)
                else [],
            }
        )

    return tabelas


# ---------------------------------------------------------------------------
# Exportação (sempre em memória)
# ---------------------------------------------------------------------------

def _sanitizar_nome_arquivo(texto: str, limite: int = 80) -> str:
    """Transforma título/origem em nome de arquivo seguro."""

    base = unicodedata.normalize("NFKD", _texto_limpo(texto))
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")

    return (base or "tabela")[:limite]


def nome_arquivo_tabela(tabela: dict, extensao: str) -> str:
    """Nome de download estável para a tabela, sem acentos."""

    extensao = extensao.lstrip(".")
    origem = Path(_texto_limpo(tabela.get("origem"))).stem or "tabela"
    titulo = _texto_limpo(tabela.get("titulo")) or "tabela"
    secao = _texto_limpo(tabela.get("secao"))
    pagina = tabela.get("pagina")

    # Dados de API não têm documento: o nome curto identifica só a fonte.
    if tabela.get("formato") == "api":
        partes = [_sanitizar_nome_arquivo(secao or origem, 60)]
    else:
        partes = [
            _sanitizar_nome_arquivo(origem, 40),
            _sanitizar_nome_arquivo(titulo, 60),
        ]

    if pagina:
        partes.append(f"pagina_{pagina}")

    return "_".join(parte for parte in partes if parte) + f".{extensao}"


def gerar_csv(tabela: dict) -> bytes:
    """CSV UTF-8 (com BOM), separador ``;`` e decimal com vírgula.

    É o formato que o Excel em português abre com duplo clique e que o
    QGIS importa diretamente como camada de texto delimitado.
    """

    df = tabela.get("df_limpo")

    if df is None:
        df = tabela.get("df_bruto")

    if df is None:
        return b""

    return df.to_csv(
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        lineterminator="\r\n",
    ).encode("utf-8-sig")


def _formatar_aba_excel(aba, df: pd.DataFrame) -> None:
    """Aplica cabeçalho formatado, filtro, painéis e larguras na aba."""

    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    if df.empty and not len(df.columns):
        return

    largura_maxima = len(df.columns)
    aba.freeze_panes = "A2"

    if largura_maxima:
        ultima_letra = aba.cell(row=1, column=largura_maxima).column_letter
        ultima_linha = max(1, len(df) + 1)
        aba.auto_filter.ref = f"A1:{ultima_letra}{ultima_linha}"

    preenchimento = PatternFill("solid", fgColor="1F4E78")
    fonte = Font(color="FFFFFF", bold=True)
    borda = Border(
        bottom=Side(style="thin", color="BFBFBF")
    )

    for indice, coluna in enumerate(df.columns, start=1):
        celula = aba.cell(row=1, column=indice)
        celula.fill = preenchimento
        celula.font = fonte
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celula.border = borda

        valores = [str(coluna)] + [
            "" if valor is None else str(valor)
            for valor in df[coluna].head(200).tolist()
        ]
        largura = min(60, max(10, max(len(valor) for valor in valores) + 2))

        aba.column_dimensions[aba.cell(row=1, column=indice).column_letter].width = (
            largura
        )

    aba.row_dimensions[1].height = 24


def gerar_excel(tabela: dict) -> bytes:
    """Gera um ``.xlsx`` em memória com dados, brutos e metadados.

    Usa ``openpyxl`` através de ``pandas.ExcelWriter`` e um ``BytesIO``:
    nenhum arquivo temporário é gravado no disco.
    """

    try:
        import openpyxl  # noqa: F401
    except ImportError as erro:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "A exportação Excel exige o pacote openpyxl. "
            "Instale com: pip install openpyxl"
        ) from erro

    df_limpo = tabela.get("df_limpo")
    df_bruto = tabela.get("df_bruto")

    if df_limpo is None or df_bruto is None:
        raise ValueError("Tabela sem dados para exportação.")

    unidades = tabela.get("unidades") or {}
    observacoes = tabela.get("observacoes") or []

    metadados = pd.DataFrame(
        [
            ("Título", tabela.get("titulo") or ""),
            ("Seção", tabela.get("secao") or ""),
            ("Origem", tabela.get("origem") or ""),
            ("Página", tabela.get("pagina") if tabela.get("pagina") else "—"),
            ("Formato", tabela.get("formato") or ""),
            ("Linhas", len(df_bruto)),
            ("Colunas", len(df_bruto.columns)),
            (
                "Colunas numéricas",
                ", ".join(tabela.get("colunas_numericas") or []) or "—",
            ),
            (
                "Unidades",
                "; ".join(f"{coluna}: {unidade}" for coluna, unidade in unidades.items())
                or "—",
            ),
            (
                "Observações",
                " | ".join(observacoes) if observacoes else "—",
            ),
            ("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ],
        columns=["Campo", "Valor"],
    )

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        df_limpo.to_excel(escritor, sheet_name="Dados", index=False)
        df_bruto.to_excel(escritor, sheet_name="Dados brutos", index=False)
        metadados.to_excel(escritor, sheet_name="Metadados", index=False)

        _formatar_aba_excel(escritor.sheets["Dados"], df_limpo)
        _formatar_aba_excel(escritor.sheets["Dados brutos"], df_bruto)
        _formatar_aba_excel(escritor.sheets["Metadados"], metadados)

        escritor.sheets["Dados"].sheet_properties.tabColor = "1F4E78"
        escritor.sheets["Dados brutos"].sheet_properties.tabColor = "7F7F7F"
        escritor.sheets["Metadados"].sheet_properties.tabColor = "548235"

    return buffer.getvalue()
