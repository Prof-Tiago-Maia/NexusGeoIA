"""Sondagem e litologia: grade De-Ate, validacao e exportacao (D3b).

Este modulo concentra o contrato de dados da Fase D3b:

* parser de cabecalhos em Portugues do Brasil e English, cobrindo
  "De"/"Até", "Prof. de"/"Prof. até", "Intervalo", "From", "To",
  "Hole"/"Furo" e "Lithology"/"Litologia", inclusive com a unidade
  entre parenteses ("Prof. de (cm)", "Intervalo (m)");
* normalizacao de profundidades com virgula ou ponto decimal e unidade
  explicita na celula, na coluna Unidade ou no cabecalho (m ou cm
  convertidos para metros);
* validacao de de >= 0 e ate > de, mantendo os intervalos validos mesmo
  quando outra linha falha;
* deteccao de sobreposicoes e lacunas por furo, com ordenacao estavel
  por furo e profundidade;
* exportacao sanitizada em CSV/XLSX, reutilizando
  services.exportacao_segura para neutralizar formulas perigosas sem
  corromper numeros negativos validos.

O modulo nao importa Streamlit, nao grava arquivos e nao acessa rede.
A interface consome o dicionario devolvido por analisar_sondagem e
traduz os codigos estaveis (situacao e motivo) com utils.i18n.

Idempotencia e referencias leves: a analise e pura e deterministica, e
duas execucoes da mesma tabela produzem a mesma assinatura
(assinatura_resultado). A interface guarda apenas essa assinatura e o
hash do texto (hash_texto) para decidir se precisa reanalisar, em vez
de comparar ou copiar a grade inteira.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from itertools import chain

import pandas as pd

from services import progress_service
from services.exportacao_segura import gerar_csv_seguro, gerar_xlsx_seguro

# Tolerancia usada nas comparacoes de profundidade (em metros). Ela evita
# que arredondamentos binarios transformem um contato exato em lacuna ou
# sobreposicao de 1e-16 m.
TOLERANCIA_M = 1e-9

UNIDADE_PADRAO = "m"

# Prazo padrao de uma analise interativa. O parser e O(n) e puro; o
# limite existe para que uma tabela patologica nao prenda a interface
# sem mensagem. Chamadores de lote podem passar prazo_s=None (sem
# limite); a aba de sondagem usa este valor explicitamente.
TEMPO_LIMITE_PADRAO_S = 30.0

# Codigo estavel de erro quando o prazo da etapa expira. A interface
# traduz o codigo com utils.i18n, como os demais erros de contrato.
CODIGO_TEMPO_EXCEDIDO = "tempo_excedido"

# Campos canonicos do modelo de furo/intervalo.
CAMPOS = (
    "furo",
    "de",
    "ate",
    "intervalo",
    "litologia",
    "amostra",
    "observacao",
    "unidade",
)

CAMPOS_OBRIGATORIOS = ("furo",)

# Sinonimos aceitos depois de remover acentos, pontuacao e caixa. A
# normalizacao de mapear_cabecalhos transforma "Prof. de (m)" em
# "prof de m", por exemplo.
ALIASES = {
    "furo": frozenset({
        "furo",
        "furo de sondagem",
        "furo sondagem",
        "numero do furo",
        "numero furo",
        "no furo",
        "id furo",
        "furo id",
        "sondagem",
        "sondagem id",
        "hole",
        "hole id",
        "borehole",
        "borehole id",
        "drillhole",
        "drillhole id",
        "dh",
        "bh",
    }),
    "de": frozenset({
        "de",
        "de m",
        "prof de",
        "prof de m",
        "profundidade de",
        "profundidade de m",
        "profundidade inicial",
        "profundidade inicial m",
        "inicio",
        "inicio m",
        "from",
        "from m",
        "from depth",
        "from depth m",
        "depth from",
        "depth from m",
        "top",
        "top m",
        "start",
        "start m",
    }),
    "ate": frozenset({
        "ate",
        "ate m",
        "prof ate",
        "prof ate m",
        "profundidade ate",
        "profundidade ate m",
        "profundidade final",
        "profundidade final m",
        "fim",
        "fim m",
        "final",
        "final m",
        "to",
        "to m",
        "to depth",
        "to depth m",
        "depth to",
        "depth to m",
        "bottom",
        "bottom m",
        "end",
        "end m",
    }),
    "intervalo": frozenset({
        "intervalo",
        "intervalo de profundidade",
        "intervalo profundidade",
        "depth interval",
        "depth range",
        "interval",
    }),
    "litologia": frozenset({
        "litologia",
        "litologias",
        "lit",
        "lito",
        "rocha",
        "tipo de rocha",
        "tipo litologico",
        "unidade litologica",
        "lithology",
        "lithologies",
        "lith",
        "rock",
        "rock type",
        "lithotype",
    }),
    "amostra": frozenset({
        "amostra",
        "amostra id",
        "numero da amostra",
        "numero amostra",
        "no amostra",
        "sample",
        "sample id",
        "sample no",
        "sample number",
    }),
    "observacao": frozenset({
        "observacao",
        "observacoes",
        "obs",
        "observation",
        "observations",
        "remark",
        "remarks",
        "comentario",
        "comentarios",
        "note",
        "notes",
        "descricao",
        "description",
    }),
    "unidade": frozenset({
        "unidade",
        "unidade de profundidade",
        "unidade de medida",
        "unidade profundidade",
        "unit",
        "units",
        "depth unit",
        "measure unit",
    }),
}

# Fatores de conversao para metros. A chave ja esta normalizada.
FATORES_UNIDADE = {
    "m": 1.0,
    "metro": 1.0,
    "metros": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "cm": 0.01,
    "centimetro": 0.01,
    "centimetros": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
}

# Conjuntos normalizados usados para reconhecer a unidade no fim de um
# cabecalho, como em "Prof. de (cm)" ou "From (m)".
UNIDADES_M = frozenset({"m", "metro", "metros", "meter", "meters"})
UNIDADES_CM = frozenset({
    "cm",
    "centimetro",
    "centimetros",
    "centimeter",
    "centimeters",
})
UNIDADES_CABECALHO = UNIDADES_M | UNIDADES_CM

SITUACAO_VALIDO = "valido"
SITUACAO_SOBREPOSICAO = "sobreposicao"
SITUACAO_LACUNA = "lacuna"
SITUACAO_SOBREPOSICAO_LACUNA = "sobreposicao_lacuna"
SITUACAO_INVALIDO = "invalido"

SITUACOES = (
    SITUACAO_VALIDO,
    SITUACAO_SOBREPOSICAO,
    SITUACAO_LACUNA,
    SITUACAO_SOBREPOSICAO_LACUNA,
    SITUACAO_INVALIDO,
)

# Codigos estaveis de motivo. A interface traduz cada um; o export usa o
# proprio codigo para nao depender do idioma ativo.
MOTIVO_FURO_AUSENTE = "furo_ausente"
MOTIVO_DE_AUSENTE = "de_ausente"
MOTIVO_ATE_AUSENTE = "ate_ausente"
MOTIVO_DE_INVALIDO = "de_invalido"
MOTIVO_ATE_INVALIDO = "ate_invalido"
MOTIVO_INTERVALO_INVALIDO = "intervalo_invalido"
MOTIVO_DE_NEGATIVO = "de_negativo"
MOTIVO_ATE_NAO_MAIOR = "ate_nao_maior_que_de"
MOTIVO_UNIDADE_INVALIDA = "unidade_invalida"

MOTIVOS = (
    MOTIVO_FURO_AUSENTE,
    MOTIVO_DE_AUSENTE,
    MOTIVO_ATE_AUSENTE,
    MOTIVO_DE_INVALIDO,
    MOTIVO_ATE_INVALIDO,
    MOTIVO_INTERVALO_INVALIDO,
    MOTIVO_DE_NEGATIVO,
    MOTIVO_ATE_NAO_MAIOR,
    MOTIVO_UNIDADE_INVALIDA,
)

# Colunas estaveis da grade exportada. A interface pode renomea-las com
# rotulos para respeitar o idioma ativo.
COLUNAS_EXPORTACAO = (
    "linha",
    "furo",
    "de_original",
    "ate_original",
    "unidade",
    "de_m",
    "ate_m",
    "espessura_m",
    "litologia",
    "amostra",
    "observacao",
    "situacao",
    "motivo",
)

_NUMERO_RE = re.compile(
    r"^[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)$"
)
_VALOR_COM_UNIDADE_RE = re.compile(
    r"^\s*([+-]?(?:\d[\d.,]*|[.,]\d+))\s*([^\W\d_]+)?\s*$"
)
# "ate" e "até" (com acento) sao ambos aceitos, assim como o
# conector "a" e o dash em suas variantes tipograficas.
_INTERVALO_RE = re.compile(
    r"^\s*(.+?)\s*(?:–|—|-|\ba\b|\bat[ée]\b|\bto\b)\s*(.+?)\s*$",
    re.IGNORECASE,
)


class SondagemError(ValueError):
    """Erro de contrato do parser de sondagem.

    codigo e estavel e traduzivel pela interface; detalhe traz o
    complemento tecnico (campos ausentes, valor recusado etc.).
    """

    def __init__(self, codigo: str, detalhe: str = ""):
        self.codigo = codigo
        self.detalhe = detalhe
        super().__init__(
            f"{codigo}: {detalhe}" if detalhe else codigo
        )


def _texto(valor) -> str:
    """Converte uma celula em texto limpo, tratando None/NaN."""

    if valor is None:
        return ""

    if isinstance(valor, str):
        return valor.strip()

    if isinstance(valor, float) and math.isnan(valor):
        return ""

    if valor is pd.NA:
        return ""

    return str(valor).strip()


def normalizar_cabecalho(texto) -> str:
    """Normaliza um cabecalho para comparacao sem acento ou pontuacao."""

    base = unicodedata.normalize("NFKD", _texto(texto))
    base = "".join(
        caractere
        for caractere in base
        if not unicodedata.combining(caractere)
    )
    base = base.lower().replace("º", "").replace("°", "")
    base = re.sub(r"[^a-z0-9]+", " ", base)

    return re.sub(r"\s+", " ", base).strip()


def _buscar_campo(normalizado: str) -> str | None:
    """Procura o campo canonico de um cabecalho ja normalizado."""

    for campo, aliases in ALIASES.items():
        if normalizado in aliases:
            return campo

    return None


def _campo_do_cabecalho(cabecalho) -> str | None:
    """Devolve o campo canonico de um cabecalho reconhecido.

    A unidade entre parenteses e removida antes da comparacao: assim
    "Prof. de (cm)", "Prof. até (cm)", "Intervalo (cm)", "From (m)" e
    "Depth To (cm)" continuam sendo reconhecidos como De/Até/Intervalo.
    """

    normalizado = normalizar_cabecalho(cabecalho)
    campo = _buscar_campo(normalizado)

    if campo is not None:
        return campo

    tokens = normalizado.split()

    if len(tokens) > 1 and tokens[-1] in UNIDADES_CABECALHO:
        return _buscar_campo(" ".join(tokens[:-1]))

    return None


def unidade_do_cabecalho(cabecalho) -> str | None:
    """Unidade declarada no fim do cabecalho ("Prof. de (cm)" -> cm)."""

    tokens = normalizar_cabecalho(cabecalho).split()

    if not tokens:
        return None

    ultimo = tokens[-1]

    if ultimo in UNIDADES_M:
        return "m"

    if ultimo in UNIDADES_CM:
        return "cm"

    return None


def unidades_de_cabecalho(cabecalhos) -> dict[str, str]:
    """Unidades declaradas nos cabecalhos de profundidade.

    O primeiro cabecalho reconhecido de cada campo vence, mantendo a
    mesma regra de mapear_cabecalhos. Somente De, Até e Intervalo
    carregam unidade; a coluna Unidade continua tendo precedencia por
    ser um dado explicito da linha.
    """

    unidades: dict[str, str] = {}

    for cabecalho in cabecalhos or []:
        campo = _campo_do_cabecalho(cabecalho)
        unidade = unidade_do_cabecalho(cabecalho)

        if (
            campo in ("de", "ate", "intervalo")
            and unidade
            and campo not in unidades
        ):
            unidades[campo] = unidade

    return unidades


def mapear_cabecalhos(cabecalhos) -> dict[str, int]:
    """Mapeia campo canonico para a posicao do cabecalho na tabela.

    O primeiro sinonimo reconhecido vence; cabecalhos duplicados do mesmo
    campo nao sobrescrevem a primeira coluna. Cabecalhos desconhecidos
    sao ignorados.
    """

    mapa: dict[str, int] = {}

    for indice, cabecalho in enumerate(cabecalhos or []):
        campo = _campo_do_cabecalho(cabecalho)

        if campo is not None and campo not in mapa:
            mapa[campo] = indice

    return mapa


def _normalizar_numero(texto: str) -> float:
    """Converte um numero com virgula ou ponto decimal em float."""

    limpo = _texto(texto).replace("\u00a0", "").replace(" ", "")
    limpo = limpo.replace("\u2212", "-")

    if not limpo or not _NUMERO_RE.fullmatch(limpo):
        raise SondagemError("numero_invalido", _texto(texto))

    if "," in limpo and "." in limpo:
        if limpo.rfind(",") > limpo.rfind("."):
            # Formato pt-BR: 1.234,56 -> 1234.56
            if limpo.count(",") != 1:
                raise SondagemError("numero_invalido", _texto(texto))
            limpo = limpo.replace(".", "").replace(",", ".")
        else:
            # Formato en: 1,234.56 -> 1234.56
            if limpo.count(".") != 1:
                raise SondagemError("numero_invalido", _texto(texto))
            limpo = limpo.replace(",", "")
    elif "," in limpo:
        if limpo.count(",") != 1:
            raise SondagemError("numero_invalido", _texto(texto))
        limpo = limpo.replace(",", ".")
    elif "." in limpo and limpo.count(".") != 1:
        raise SondagemError("numero_invalido", _texto(texto))

    try:
        numero = float(limpo)
    except (TypeError, ValueError) as erro:
        raise SondagemError("numero_invalido", _texto(texto)) from erro

    if not math.isfinite(numero):
        raise SondagemError("numero_invalido", _texto(texto))

    return numero


def _normalizar_unidade(unidade: str) -> str:
    """Reconhece a unidade e devolve m ou cm."""

    normalizada = normalizar_cabecalho(unidade)

    if normalizada in UNIDADES_M:
        return "m"

    if normalizada in UNIDADES_CM:
        return "cm"

    raise SondagemError(MOTIVO_UNIDADE_INVALIDA, _texto(unidade))


def _unidade_do_texto(valor) -> str:
    """Unidade escrita na propria celula, ou string vazia.

    Diferente de converter_profundidade, nao valida o numero: serve para
    descobrir a unidade de um intervalo antes de converter os limites.
    """

    if isinstance(valor, (int, float)):
        return ""

    encontrado = _VALOR_COM_UNIDADE_RE.fullmatch(_texto(valor))

    if not encontrado:
        return ""

    unidade = encontrado.group(2) or ""

    if not unidade:
        return ""

    try:
        return _normalizar_unidade(unidade)
    except SondagemError:
        return ""


def converter_profundidade(
    valor,
    unidade=None,
    origem_unidade=None,
) -> tuple[float, str, str]:
    """Converte uma profundidade para metros.

    Devolve (metros, unidade_origem, origem_da_unidade), em que
    origem_da_unidade e "celula", "coluna" ou "padrao". A unidade escrita
    na propria celula (150 cm) tem precedencia sobre a unidade da coluna
    Unidade; sem nenhuma das duas, vale metro. origem_unidade permite
    declarar que a unidade padrao veio de outra celula da mesma linha
    (por exemplo, o limite superior de "0 - 1,5 m").
    """

    if isinstance(valor, bool):
        raise SondagemError("numero_invalido", _texto(valor))

    if isinstance(valor, (int, float)):
        numero = float(valor)

        if not math.isfinite(numero):
            raise SondagemError("numero_invalido", _texto(valor))

        unidade_celula = ""
    else:
        texto = _texto(valor)
        encontrado = _VALOR_COM_UNIDADE_RE.fullmatch(texto)

        if not encontrado:
            raise SondagemError("numero_invalido", texto)

        numero = _normalizar_numero(encontrado.group(1))
        unidade_celula = encontrado.group(2) or ""

    if unidade_celula:
        unidade_final = _normalizar_unidade(unidade_celula)
        origem = "celula"
    elif _texto(unidade):
        unidade_final = _normalizar_unidade(unidade)
        origem = origem_unidade or "coluna"
    else:
        unidade_final = UNIDADE_PADRAO
        origem = "padrao"

    metros = round(numero * FATORES_UNIDADE[unidade_final], 6)

    return (
        _sem_zero_negativo(metros),
        unidade_final,
        origem,
    )


def _separar_intervalo(texto: str) -> tuple[str, str]:
    """Separa 0,0 - 2,5 ou 0 a 2,5 m em duas profundidades."""

    encontrado = _INTERVALO_RE.fullmatch(_texto(texto))

    if not encontrado:
        raise SondagemError(MOTIVO_INTERVALO_INVALIDO, _texto(texto))

    return encontrado.group(1).strip(), encontrado.group(2).strip()


def _largura_util(registro) -> int:
    """Numero de campos de um registro, incluindo celulas vazias.

    A celula vazia no fim de "a;b;c;" corresponde a uma coluna real do
    cabecalho e por isso conta na largura. Descartar esses campos
    esconderia justamente o desalinhamento que a validacao precisa
    detectar.
    """

    return len(registro)


def _avaliar_delimitador(linhas, candidato: str) -> tuple:
    """Pontua um delimitador pela consistencia da largura das linhas."""

    try:
        registros = list(csv.reader(linhas, delimiter=candidato))
    except csv.Error:
        return (False, False, False, 0, 0, 0)

    larguras = [_largura_util(registro) for registro in registros]

    if not larguras:
        return (False, False, False, 0, 0, 0)

    largura_cabecalho = larguras[0]
    consistente = len(set(larguras)) == 1
    tem_colunas = largura_cabecalho > 1
    linhas_uteis = sum(1 for largura in larguras if largura > 1)

    # Ordem de prioridade:
    # 1. delimitador que produz >= 2 colunas em todas as linhas;
    # 2. delimitador que produz >= 2 colunas no cabecalho (mesmo que
    #    alguma linha esteja desalinhada, para que o erro correto seja
    #    "tabela_desalinhada" e nao "cabecalhos_obrigatorios");
    # 3. consistencia e largura do cabecalho, como desempate.
    return (
        bool(consistente and tem_colunas),
        tem_colunas,
        consistente,
        largura_cabecalho,
        linhas_uteis,
        0,
    )


def _detectar_delimitador(linhas) -> str:
    """Escolhe o delimitador mais provavel pela tabela inteira.

    Avaliar apenas o cabecalho confundia a virgula decimal com um
    separador extra. A pontuacao usa a consistencia da largura de todas
    as linhas e so prefere um candidato ambiguo quando ele ainda produz
    colunas suficientes para diagnosticar o desalinhamento.
    """

    if isinstance(linhas, str):
        linhas = [linhas]

    linhas = list(linhas or [""])
    candidatos = (";", "\t", ",", "|")
    preferencia = {
        candidato: indice
        for indice, candidato in enumerate(candidatos)
    }
    melhor = None
    melhor_pontuacao = None

    for candidato in candidatos:
        pontuacao = _avaliar_delimitador(linhas, candidato)
        chave = (pontuacao, -preferencia[candidato])

        if melhor_pontuacao is None or chave > melhor_pontuacao:
            melhor = candidato
            melhor_pontuacao = chave

    return melhor or ";"


def _validar_largura_linhas(
    cabecalhos: Sequence[str],
    linhas_dados: Sequence[Sequence[str]],
    deslocamento: int = 1,
) -> None:
    """Recusa tabelas em que alguma linha nao casa com o cabecalho.

    A validacao roda depois da leitura, quando o delimitador ja foi
    escolhido. Ela impede que uma virgula decimal ou uma coluna extra
    seja aceita silenciosamente como um campo a mais.
    """

    largura_cabecalho = _largura_util(cabecalhos)
    desalinhadas = [
        indice + deslocamento + 1
        for indice, linha in enumerate(linhas_dados)
        if _largura_util(linha) != largura_cabecalho
    ]

    if desalinhadas:
        raise SondagemError(
            "tabela_desalinhada",
            ", ".join(str(numero) for numero in desalinhadas[:10]),
        )


def ler_tabela_texto(
    texto: str,
    delimitador: str | None = None,
) -> tuple[list[str], list[list[str]], int]:
    """Le uma tabela colada ou um CSV em memoria.

    Devolve (cabecalhos, linhas, deslocamento). deslocamento e 1 quando ha
    linha de cabecalho, para que o relatorio de linhas invalidas use o
    numero da linha como aparece no texto original.
    """

    conteudo = _texto(texto).replace("\ufeff", "")

    if not conteudo:
        raise SondagemError("tabela_vazia")

    linhas = [
        linha
        for linha in conteudo.splitlines()
        if linha.strip() and not linha.lstrip().startswith("#")
    ]

    if not linhas:
        raise SondagemError("tabela_vazia")

    separador = delimitador or _detectar_delimitador(linhas)

    try:
        registros = list(csv.reader(linhas, delimiter=separador))
    except csv.Error as erro:
        raise SondagemError("tabela_invalida", str(erro)) from erro

    if not registros:
        raise SondagemError("tabela_vazia")

    cabecalhos = [_texto(celula) for celula in registros[0]]
    linhas_dados = [
        linha
        for linha in registros[1:]
        if any(_texto(celula) for celula in linha)
    ]

    if not linhas_dados:
        raise SondagemError("sem_linhas")

    _validar_largura_linhas(cabecalhos, linhas_dados)

    return cabecalhos, linhas_dados, 1


def _valor_celula(
    registro,
    cabecalhos: Sequence[str],
    mapa: Mapping[str, int],
    campo: str,
) -> str:
    """Valor bruto de um campo em uma linha de lista ou dicionario."""

    posicao = mapa.get(campo)

    if posicao is None:
        return ""

    if isinstance(registro, Mapping):
        if posicao >= len(cabecalhos):
            return ""
        return _texto(registro.get(cabecalhos[posicao]))

    if posicao >= len(registro):
        return ""

    return _texto(registro[posicao])


def _adicionar_motivo(motivos: list[str], codigo: str) -> None:
    if codigo and codigo not in motivos:
        motivos.append(codigo)


def _sem_zero_negativo(valor):
    """Normaliza -0.0 para 0.0 preservando None e os demais numeros."""

    if valor is None:
        return None

    if valor == 0:
        return 0.0

    return valor


def _processar_linha(
    registro,
    cabecalhos: Sequence[str],
    mapa: Mapping[str, int],
    linha: int,
    unidades_cabecalho: Mapping[str, str] | None = None,
) -> dict:
    """Valida uma linha e devolve o intervalo canonico ou invalido.

    A unidade e resolvida na ordem: celula (incluindo o intervalo
    "0 - 2,5 m") > coluna Unidade > unidade do cabecalho ("Prof. de
    (cm)") > unidade emprestada do outro limite > metro.
    """

    unidades = unidades_cabecalho or {}
    unidade_cabecalho_de = unidades.get("de", "")
    unidade_cabecalho_ate = unidades.get("ate", "")
    unidade_cabecalho_intervalo = unidades.get("intervalo", "")

    furo = _texto(_valor_celula(registro, cabecalhos, mapa, "furo"))
    de_texto = _valor_celula(registro, cabecalhos, mapa, "de")
    ate_texto = _valor_celula(registro, cabecalhos, mapa, "ate")
    intervalo_texto = _valor_celula(
        registro, cabecalhos, mapa, "intervalo"
    )
    unidade_coluna = _valor_celula(
        registro, cabecalhos, mapa, "unidade"
    )
    litologia = _valor_celula(
        registro, cabecalhos, mapa, "litologia"
    )
    amostra = _valor_celula(registro, cabecalhos, mapa, "amostra")
    observacao = _valor_celula(
        registro, cabecalhos, mapa, "observacao"
    )

    motivos: list[str] = []
    de_m = None
    ate_m = None
    unidade_de = ""
    unidade_ate = ""
    origem_unidade_de = ""
    origem_unidade_ate = ""
    unidade_intervalo = ""

    # O cabecalho "Intervalo" e uma alternativa aos pares De/Ate: nesse
    # caso a propria celula carrega os dois limites. A unidade escrita
    # em qualquer um dos lados vale para o intervalo inteiro, cobrindo
    # "0 - 150 cm" e "0 até 2,5 m".
    if not de_texto and not ate_texto and intervalo_texto:
        try:
            de_texto, ate_texto = _separar_intervalo(intervalo_texto)
            unidade_intervalo = (
                _unidade_do_texto(ate_texto)
                or _unidade_do_texto(de_texto)
            )
        except SondagemError:
            _adicionar_motivo(motivos, MOTIVO_INTERVALO_INVALIDO)

    if not furo:
        _adicionar_motivo(motivos, MOTIVO_FURO_AUSENTE)

    padrao_de = (
        unidade_intervalo
        or unidade_coluna
        or unidade_cabecalho_de
        or unidade_cabecalho_intervalo
    )
    origem_padrao_de = (
        "celula"
        if unidade_intervalo
        else ("coluna" if padrao_de else None)
    )

    if not de_texto:
        _adicionar_motivo(motivos, MOTIVO_DE_AUSENTE)
    else:
        try:
            de_m, unidade_de, origem_unidade_de = (
                converter_profundidade(
                    de_texto,
                    padrao_de,
                    origem_padrao_de,
                )
            )
        except SondagemError as erro:
            _adicionar_motivo(
                motivos,
                (
                    MOTIVO_UNIDADE_INVALIDA
                    if erro.codigo == MOTIVO_UNIDADE_INVALIDA
                    else MOTIVO_DE_INVALIDO
                ),
            )

    # A unidade de De so e emprestada para Ate quando veio de uma
    # celula; se veio do padrao (metro), Ate tambem deve registrar
    # origem "padrao" em vez de fingir uma unidade de celula.
    unidade_emprestada = (
        unidade_de if origem_unidade_de == "celula" else ""
    )
    padrao_ate = (
        unidade_intervalo
        or unidade_coluna
        or unidade_cabecalho_ate
        or unidade_cabecalho_intervalo
        or unidade_emprestada
    )

    if unidade_intervalo:
        origem_padrao_ate = "celula"
    elif unidade_coluna or unidade_cabecalho_ate or unidade_cabecalho_intervalo:
        origem_padrao_ate = "coluna"
    elif unidade_emprestada:
        origem_padrao_ate = "celula"
    else:
        origem_padrao_ate = None

    if not ate_texto:
        _adicionar_motivo(motivos, MOTIVO_ATE_AUSENTE)
    else:
        try:
            ate_m, unidade_ate, origem_unidade_ate = (
                converter_profundidade(
                    ate_texto,
                    padrao_ate,
                    origem_padrao_ate,
                )
            )
        except SondagemError as erro:
            _adicionar_motivo(
                motivos,
                (
                    MOTIVO_UNIDADE_INVALIDA
                    if erro.codigo == MOTIVO_UNIDADE_INVALIDA
                    else MOTIVO_ATE_INVALIDO
                ),
            )

    if de_m is not None:
        if de_m < 0:
            _adicionar_motivo(motivos, MOTIVO_DE_NEGATIVO)
        else:
            # "-0" e aceito pela validacao de nao negativo, mas a grade
            # nao deve exibir "-0,0".
            de_m = _sem_zero_negativo(de_m)

    if ate_m is not None:
        ate_m = _sem_zero_negativo(ate_m)

    if (
        de_m is not None
        and ate_m is not None
        and ate_m <= de_m + TOLERANCIA_M
    ):
        _adicionar_motivo(motivos, MOTIVO_ATE_NAO_MAIOR)

    espessura = None

    if (
        de_m is not None
        and ate_m is not None
        and ate_m > de_m + TOLERANCIA_M
    ):
        espessura = _sem_zero_negativo(round(ate_m - de_m, 6))

    unidade_exibicao = ""

    if unidade_de and unidade_ate and unidade_de != unidade_ate:
        unidade_exibicao = f"{unidade_de}/{unidade_ate}"
    else:
        unidade_exibicao = unidade_de or unidade_ate or ""

    return {
        "linha": linha,
        "furo": furo,
        "de_original": de_texto,
        "ate_original": ate_texto,
        "intervalo_original": intervalo_texto,
        "de_m": de_m,
        "ate_m": ate_m,
        "espessura_m": espessura,
        "litologia": litologia,
        "amostra": amostra,
        "observacao": observacao,
        "unidade": unidade_exibicao,
        "unidade_de": unidade_de,
        "unidade_ate": unidade_ate,
        "origem_unidade_de": origem_unidade_de,
        "origem_unidade_ate": origem_unidade_ate,
        "situacao": SITUACAO_INVALIDO if motivos else SITUACAO_VALIDO,
        "motivos": motivos,
        "motivo": "; ".join(motivos),
        "sobreposicao_m": None,
        "lacuna_antes_m": None,
    }


def _unir_cobertura(
    cobertura: list[tuple[float, float]],
    inicio: float,
    fim: float,
) -> list[tuple[float, float]]:
    """Acrescenta um intervalo a uniao de faixas cobertas.

    A uniao mantem os segmentos ordenados e fundidos, de modo que um
    intervalo aninhado nao seja contado duas vezes na espessura total.
    """

    segmentos = [*cobertura, (inicio, fim)]
    segmentos.sort()
    unidos: list[tuple[float, float]] = []

    for inicio_segmento, fim_segmento in segmentos:
        if (
            unidos
            and inicio_segmento
            <= unidos[-1][1] + TOLERANCIA_M
        ):
            if fim_segmento > unidos[-1][1]:
                unidos[-1] = (unidos[-1][0], fim_segmento)
        else:
            unidos.append((inicio_segmento, fim_segmento))

    return unidos


def _sobreposicao_com_cobertura(
    de_m: float,
    ate_m: float,
    cobertura: list[tuple[float, float]],
) -> float:
    """Comprimento da interseccao do intervalo com a uniao ja coberta."""

    total = 0.0

    for inicio, fim in cobertura:
        inicio_interseccao = max(de_m, inicio)
        fim_interseccao = min(ate_m, fim)

        if fim_interseccao - inicio_interseccao > TOLERANCIA_M:
            total += fim_interseccao - inicio_interseccao

    return _sem_zero_negativo(round(total, 6))


def _detectar_sobreposicoes_e_lacunas(intervalos: list[dict]) -> tuple:
    """Detecta conflitos por furo e devolve sobreposicoes, lacunas, resumo.

    A cobertura e tratada como uniao de faixas. Assim, em intervalos
    aninhados (0-10 e 2-4), a sobreposicao e 2 m -- e nao os 8 m que a
    distancia ate o fim do intervalo anterior sugeriria -- e a
    espessura_total_m nao soma duas vezes a mesma profundidade.
    """

    grupos: OrderedDict[str, list[dict]] = OrderedDict()

    for intervalo in intervalos:
        grupos.setdefault(intervalo["furo"], []).append(intervalo)

    sobreposicoes: list[dict] = []
    lacunas: list[dict] = []
    por_furo: OrderedDict[str, dict] = OrderedDict()

    for furo, itens in grupos.items():
        lista = sorted(
            itens,
            key=lambda item: (
                item["de_m"],
                item["ate_m"],
                item["linha"],
            ),
        )
        cobertura: list[tuple[float, float]] = []
        cobertura_ate = None
        referencia = None

        for item in lista:
            item["situacao"] = SITUACAO_VALIDO
            item["sobreposicao_m"] = None
            item["lacuna_antes_m"] = None

            if referencia is not None:
                sobreposicao = _sobreposicao_com_cobertura(
                    item["de_m"],
                    item["ate_m"],
                    cobertura,
                )

                if sobreposicao > TOLERANCIA_M:
                    item["sobreposicao_m"] = sobreposicao
                    item["situacao"] = SITUACAO_SOBREPOSICAO
                    sobreposicoes.append(
                        {
                            "furo": furo,
                            "linha": item["linha"],
                            "de_m": item["de_m"],
                            "ate_m": item["ate_m"],
                            "anterior_linha": referencia["linha"],
                            "anterior_de_m": referencia["de_m"],
                            "anterior_ate_m": referencia["ate_m"],
                            "sobreposicao_m": sobreposicao,
                        }
                    )
                elif item["de_m"] > cobertura_ate + TOLERANCIA_M:
                    lacuna = _sem_zero_negativo(
                        round(item["de_m"] - cobertura_ate, 6)
                    )
                    item["lacuna_antes_m"] = lacuna
                    item["situacao"] = SITUACAO_LACUNA

                    lacunas.append(
                        {
                            "furo": furo,
                            "linha": item["linha"],
                            "de_m": item["de_m"],
                            "ate_m": item["ate_m"],
                            "anterior_linha": referencia["linha"],
                            "anterior_de_m": referencia["de_m"],
                            "anterior_ate_m": referencia["ate_m"],
                            "lacuna_m": lacuna,
                        }
                    )

            cobertura = _unir_cobertura(
                cobertura,
                item["de_m"],
                item["ate_m"],
            )

            if cobertura_ate is None or item["ate_m"] > cobertura_ate:
                cobertura_ate = item["ate_m"]
                referencia = item

        de_min = _sem_zero_negativo(
            round(min(item["de_m"] for item in lista), 6)
        )
        ate_max = _sem_zero_negativo(
            round(max(item["ate_m"] for item in lista), 6)
        )
        espessura_total = _sem_zero_negativo(
            round(
                sum(fim - inicio for inicio, fim in cobertura),
                6,
            )
        )
        litologias = []

        for item in lista:
            if item["litologia"] and item["litologia"] not in litologias:
                litologias.append(item["litologia"])

        por_furo[furo] = {
            "furo": furo,
            "total_intervalos": len(lista),
            "de_m": de_min,
            "ate_m": ate_max,
            "espessura_total_m": espessura_total,
            "litologias": litologias,
            "sobreposicoes": sum(
                1
                for item in lista
                if item["sobreposicao_m"] is not None
            ),
            "lacunas": sum(
                1
                for item in lista
                if item["lacuna_antes_m"] is not None
            ),
        }

    return sobreposicoes, lacunas, por_furo


# Campos que entram na assinatura estavel da grade. Inclui o codigo do
# motivo (e nao so o texto juntado) para que a assinatura continue
# valida em qualquer idioma da interface.
_CAMPOS_ASSINATURA = (
    "linha",
    "furo",
    "de_original",
    "ate_original",
    "intervalo_original",
    "de_m",
    "ate_m",
    "espessura_m",
    "unidade",
    "unidade_de",
    "unidade_ate",
    "origem_unidade_de",
    "origem_unidade_ate",
    "litologia",
    "amostra",
    "observacao",
    "situacao",
    "motivos",
    "sobreposicao_m",
    "lacuna_antes_m",
)


def normalizar_texto_tabela(texto) -> str:
    """Forma canonica e idempotente do texto colado.

    Remove BOM, unifica fim de linha, descarta espacos a direita e as
    linhas vazias das extremidades. E a base de :func:`hash_texto` e nao
    altera o conteudo usado pelo parser (que ja tolera essas variacoes).
    """

    conteudo = (
        _texto(texto)
        .replace("\ufeff", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    linhas = [linha.rstrip() for linha in conteudo.split("\n")]

    while linhas and not linhas[0].strip():
        linhas.pop(0)

    while linhas and not linhas[-1].strip():
        linhas.pop()

    return "\n".join(linhas)


def hash_texto(texto) -> str:
    """SHA-256 do texto canonico: referencia leve da entrada.

    A interface guarda so este hash (64 caracteres) para decidir se a
    mesma tabela ja foi analisada, em vez de manter uma copia do texto
    ou comparar a grade inteira a cada rerun.
    """

    return hashlib.sha256(
        normalizar_texto_tabela(texto).encode("utf-8")
    ).hexdigest()


def assinatura_resultado(
    resultado: Mapping,
    incluir_invalidos: bool = True,
) -> str:
    """Hash estavel da grade devolvida por :func:`analisar_sondagem`.

    Duas execucoes da mesma tabela produzem a mesma assinatura, o que
    torna a reexecucao da etapa verificavel e idempotente. A funcao nao
    modifica o resultado e serializa apenas campos canonicos, sem
    depender do idioma ativo, da ordem de insercao ou do DataFrame de
    exportacao.
    """

    itens = list((resultado or {}).get("intervalos") or [])

    if incluir_invalidos:
        itens.extend(list((resultado or {}).get("invalidos") or []))

    registros = []

    for item in sorted(
        itens,
        key=lambda entrada: (
            str((entrada or {}).get("furo") or "").casefold(),
            (entrada or {}).get("linha") or 0,
        ),
    ):
        registros.append(
            {
                campo: (item or {}).get(campo)
                for campo in _CAMPOS_ASSINATURA
            }
        )

    payload = json.dumps(
        registros,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preparar_registros(
    linhas,
    cabecalhos: Sequence[str] | None,
) -> tuple[list[str], Iterable, int]:
    """Normaliza a entrada aceita por analisar_sondagem."""

    if isinstance(linhas, str):
        cabecalhos_texto, registros, deslocamento = ler_tabela_texto(
            linhas
        )
        return cabecalhos_texto, registros, deslocamento

    if isinstance(linhas, pd.DataFrame):
        cabecalhos_tabela = [
            _texto(coluna) for coluna in linhas.columns
        ]
        registros = [
            [_texto(valor) for valor in linha]
            for linha in linhas.itertuples(index=False, name=None)
        ]
        return cabecalhos_tabela, registros, 0

    if isinstance(linhas, Mapping):
        linhas = [linhas]

    iterador = iter(linhas)

    try:
        primeiro = next(iterador)
    except StopIteration as erro:
        raise SondagemError("sem_linhas") from erro

    if isinstance(primeiro, Mapping):
        registros = [primeiro]
        registros.extend(iterador)
        cabecalhos_tabela = list(cabecalhos or [])

        if not cabecalhos_tabela:
            for registro in registros:
                if not isinstance(registro, Mapping):
                    continue

                for chave in registro:
                    if chave not in cabecalhos_tabela:
                        cabecalhos_tabela.append(chave)

        return cabecalhos_tabela, registros, 0

    if not cabecalhos:
        raise SondagemError("cabecalhos_ausentes")

    # chain preserva o consumo preguicoso: um gerador lento continua
    # verificando o cancelamento linha a linha dentro de analisar_sondagem.
    return list(cabecalhos), chain([primeiro], iterador), 0


def analisar_sondagem(
    linhas,
    cabecalhos: Sequence[str] | None = None,
    cancelamento=None,
    prazo_s: float | None = None,
) -> dict:
    """Analisa uma tabela de sondagem e devolve a grade validada.

    linhas aceita texto delimitado (CSV/TSV colado), DataFrame, sequencia
    de dicionarios ou sequencia de listas (com cabecalhos). cancelamento
    e um threading.Event (ou progress_service.EventoCancelamento)
    verificado a cada linha; quando setado, levanta
    progress_service.CancelamentoSolicitado.

    prazo_s e o tempo maximo, em segundos, para consumir as linhas. None
    mantem o comportamento historico (sem limite de tempo) e e o valor
    usado por chamadores de lote; a interface passa
    TEMPO_LIMITE_PADRAO_S. Quando o prazo expira, levanta SondagemError
    com codigo CODIGO_TEMPO_EXCEDIDO e nao devolve grade parcial.
    """

    cabecalhos_tabela, registros, deslocamento = _preparar_registros(
        linhas,
        cabecalhos,
    )
    mapa = mapear_cabecalhos(cabecalhos_tabela)
    unidades_cabecalho = unidades_de_cabecalho(cabecalhos_tabela)

    if "furo" not in mapa:
        raise SondagemError(
            "cabecalhos_obrigatorios",
            "furo",
        )

    tem_de_ate = "de" in mapa and "ate" in mapa
    tem_intervalo = "intervalo" in mapa

    if not tem_de_ate and not tem_intervalo:
        faltantes = [
            campo
            for campo in ("de", "ate")
            if campo not in mapa
        ]
        raise SondagemError(
            "cabecalhos_obrigatorios",
            ", ".join(faltantes),
        )

    intervalos: list[dict] = []
    invalidos: list[dict] = []
    total = len(registros) if hasattr(registros, "__len__") else None
    limite = None if prazo_s is None else max(0.0, float(prazo_s))
    inicio = time.monotonic()

    for posicao, registro in enumerate(registros, start=1):
        # O cancelamento tem precedencia sobre o prazo: um pedido do
        # usuario precisa encerrar a etapa como cancelamento, nao como
        # erro de tempo.
        progress_service.verificar_cancelamento(
            cancelamento,
            "sondagem",
        )

        if limite is not None:
            decorrido = time.monotonic() - inicio

            if decorrido > limite:
                raise SondagemError(
                    CODIGO_TEMPO_EXCEDIDO,
                    f"{decorrido:.1f}s",
                )

        linha = posicao + deslocamento

        # A leitura de texto ja valida a largura; listas e geradores
        # tambem precisam recusar colunas a mais/menos em vez de
        # descartar o excedente em silencio.
        if (
            not isinstance(registro, Mapping)
            and len(registro) != len(cabecalhos_tabela)
        ):
            raise SondagemError("tabela_desalinhada", str(linha))

        item = _processar_linha(
            registro,
            cabecalhos_tabela,
            mapa,
            linha,
            unidades_cabecalho,
        )

        if item["situacao"] == SITUACAO_INVALIDO:
            invalidos.append(item)
        else:
            intervalos.append(item)

    # Ordenacao estavel por furo e profundidade; linha desempata
    # intervalos identicos sem perder a origem.
    intervalos.sort(
        key=lambda item: (
            item["furo"].casefold(),
            item["de_m"],
            item["ate_m"],
            item["linha"],
        )
    )

    sobreposicoes, lacunas, por_furo = (
        _detectar_sobreposicoes_e_lacunas(intervalos)
    )

    colunas = {
        campo: cabecalhos_tabela[posicao]
        for campo, posicao in mapa.items()
        if posicao < len(cabecalhos_tabela)
    }

    resultado = {
        "ok": bool(
            intervalos
            and not invalidos
            and not sobreposicoes
            and not lacunas
        ),
        "total_linhas": len(intervalos) + len(invalidos),
        "total_validos": len(intervalos),
        "total_invalidos": len(invalidos),
        "total_sobreposicoes": len(sobreposicoes),
        "total_lacunas": len(lacunas),
        "total_furos": len(por_furo),
        "intervalos": intervalos,
        "invalidos": invalidos,
        "sobreposicoes": sobreposicoes,
        "lacunas": lacunas,
        "por_furo": por_furo,
        "colunas": colunas,
        "total_previsto": total,
    }

    # A assinatura viaja com a grade: a interface e o cache de exportacao
    # passam a reutilizar essa referencia leve (64 caracteres) em vez de
    # comparar ou copiar os intervalos a cada rerun.
    resultado["assinatura"] = assinatura_resultado(resultado)

    return resultado


def montar_dataframe(
    resultado: Mapping,
    rotulos: Mapping[str, str] | None = None,
    incluir_invalidos: bool = False,
) -> pd.DataFrame:
    """Monta a grade tabular, opcionalmente com as linhas invalidas."""

    registros: list[dict] = []
    itens = list((resultado or {}).get("intervalos") or [])

    if incluir_invalidos:
        itens.extend(
            list((resultado or {}).get("invalidos") or [])
        )

    itens.sort(key=lambda item: (item.get("linha") or 0))

    for item in itens:
        registros.append(
            {
                "linha": item.get("linha"),
                "furo": item.get("furo") or "",
                "de_original": item.get("de_original") or "",
                "ate_original": item.get("ate_original") or "",
                "unidade": item.get("unidade") or "",
                "de_m": item.get("de_m"),
                "ate_m": item.get("ate_m"),
                "espessura_m": item.get("espessura_m"),
                "litologia": item.get("litologia") or "",
                "amostra": item.get("amostra") or "",
                "observacao": item.get("observacao") or "",
                "situacao": item.get("situacao") or "",
                "motivo": item.get("motivo") or "",
            }
        )

    tabela = pd.DataFrame(registros, columns=COLUNAS_EXPORTACAO)

    if rotulos:
        tabela = tabela.rename(
            columns={
                campo: rotulos.get(campo, campo)
                for campo in COLUNAS_EXPORTACAO
            }
        )

    return tabela


def gerar_csv_sondagem(
    resultado: Mapping,
    rotulos: Mapping[str, str] | None = None,
) -> bytes:
    """CSV sanitizado (UTF-8 com BOM, separador ; e virgula decimal)."""

    tabela = montar_dataframe(
        resultado,
        rotulos=rotulos,
        incluir_invalidos=True,
    )

    return gerar_csv_seguro(
        tabela,
        separador=";",
        decimal=",",
        codificacao="utf-8-sig",
        terminador="\r\n",
    )


def gerar_xlsx_sondagem(
    resultado: Mapping,
    rotulos: Mapping[str, str] | None = None,
) -> bytes:
    """XLSX sanitizado em memoria, com as linhas validas e invalidas."""

    tabela = montar_dataframe(
        resultado,
        rotulos=rotulos,
        incluir_invalidos=True,
    )

    return gerar_xlsx_seguro(tabela, nome_aba="Sondagem")


def nome_arquivo_sondagem(extensao: str) -> str:
    """Nome estavel para o download da grade."""

    extensao = extensao.lstrip(".")
    return f"grade_sondagem.{extensao}"
