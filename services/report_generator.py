"""Geração do Parecer Técnico Geocientífico em ``.docx`` e ``.md``.

O módulo converte uma resposta em Markdown do assistente em dois
artefatos prontos para entrega profissional:

- ``gerar_parecer_docx``: documento Word montado inteiramente em memória
  (``io.BytesIO``), com cabeçalho institucional, metadados de emissão,
  escopo, análise técnica, síntese espacial condicional, referências no
  padrão ABNT NBR 6023 e rodapé com numeração de página e nota de
  rastreabilidade;
- ``gerar_parecer_markdown``: a mesma estrutura em Markdown, com o
  conteúdo do assistente rebaixado um nível de título para não competir
  com as seções numeradas do parecer.

Dependências: apenas a biblioteca padrão e ``python-docx`` (leve, sem
binários externos). Se ``python-docx`` não estiver instalada, a geração
em Markdown continua funcionando e a geração em Word levanta
:class:`RelatorioError` com a instrução de instalação.

O texto do assistente é tratado como dado: nenhuma marcação Markdown é
executada, apenas convertida em elementos nativos do Word.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime
from hashlib import sha256

from config import APP_NAME, APP_VERSION

try:  # pragma: no cover - depende do ambiente de execução
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    DOCX_DISPONIVEL = True
except ImportError:  # pragma: no cover - ambiente sem python-docx
    DOCX_DISPONIVEL = False


__all__ = [
    "DOCX_DISPONIVEL",
    "RelatorioError",
    "carimbo_data_hora",
    "formatar_referencia_abnt",
    "gerar_parecer_docx",
    "gerar_parecer_markdown",
    "nome_arquivo_parecer",
    "normalizar_metadados_fontes",
    "titulo_tecnico",
]


# ---------------------------------------------------------------------------
# Constantes de apresentação
# ---------------------------------------------------------------------------

COR_AZUL_ESCURO = "1F3864"
COR_AZUL_MEDIO = "2E5C8A"
COR_CINZA_TEXTO = "44546A"
COR_CINZA_CLARO = "F2F5FA"
COR_CINZA_BORDA = "BFBFBF"

FONTE_CORPO = "Calibri"
FONTE_TECNICA = "Consolas"

TAMANHO_MAXIMO_TITULO = 110
MAXIMO_LINHAS_TABELA = 100
MAXIMO_LINHAS_TABELA_EXTRAIDA = 40
MAXIMO_COLUNAS_TABELA = 8

MESES_ABREVIADOS = (
    "jan.",
    "fev.",
    "mar.",
    "abr.",
    "mai.",
    "jun.",
    "jul.",
    "ago.",
    "set.",
    "out.",
    "nov.",
    "dez.",
)

# Rótulos legíveis para as chaves internas dos conectores.
ROTULOS_FONTE = {
    "ana": "ANA / HidroWeb",
    "sgb": "RIGeo / SGB",
    "rigeo": "RIGeo / SGB",
    "web": "Pesquisa na Web",
    "openalex": "OpenAlex",
    "usgs": "USGS ScienceBase",
    "geosgb": "GeoSGB / SGB",
    "anm": "ANM / SIGMINE",
    "macrostrat": "Macrostrat",
    "siagas": "SIAGAS / RIMAS",
    "geossit": "INDE / GEOSSIT",
    "intl_geo": "Serviços Geológicos Internacionais",
    "local": "Acervo documental local",
    "documentos": "Acervo documental local",
}

# Expressões que caracterizam autoria institucional.
PALAVRAS_INSTITUICAO = (
    "universidade",
    "university",
    "instituto",
    "institute",
    "serviço",
    "servico",
    "agência",
    "agencia",
    "agency",
    "ministério",
    "ministerio",
    "companhia",
    "empresa",
    "centro",
    "fundação",
    "fundacao",
    "departamento",
    "secretaria",
    "conselho",
    "associação",
    "associacao",
    "sociedade",
    "laboratório",
    "laboratorio",
    "observatório",
    "observatorio",
    "survey",
    "geological",
)

# Siglas que identificam órgãos ou bases; exigem caixa alta no original
# para não confundir um nome próprio ("Ana") com a sigla "ANA".
SIGLAS_INSTITUICAO = (
    "usgs",
    "cprm",
    "sgb",
    "ana",
    "anm",
    "ibge",
    "inde",
    "openalex",
    "siagas",
    "rimas",
    "macrostrat",
    "geosgb",
    "geossit",
    "sigmine",
    "hidroweb",
    "rigeo",
    "onegeology",
    "nrcan",
    "egdi",
    "eurogeosurveys",
    "gsq",
    "gsj",
    "aist",
    "geonet",
    "gns",
    "ngd",
    "gsi",
    "bhukosh",
)

PARTICULAS_NOME = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "del",
    "della",
    "van",
    "von",
    "der",
    "di",
    "du",
    "la",
    "le",
}


class RelatorioError(RuntimeError):
    """Falha controlada na geração do parecer técnico."""


# ---------------------------------------------------------------------------
# Utilidades de data, texto e rastreabilidade
# ---------------------------------------------------------------------------

def _agora_local() -> datetime:
    """Data e hora atuais com fuso local, quando disponível."""

    try:
        return datetime.now().astimezone()
    except (OSError, ValueError):  # pragma: no cover - ambiente exótico
        return datetime.now()


def carimbo_data_hora(agora: datetime | None = None) -> str:
    """Data e hora de emissão no formato ``17/11/2026 às 21:10``."""

    momento = agora or _agora_local()

    return momento.strftime("%d/%m/%Y às %H:%M")


def nome_arquivo_parecer(extensao: str = "docx", agora: datetime | None = None) -> str:
    """Nome do arquivo no padrão ``parecer_tecnico_YYYYMMDD_HHMM.ext``."""

    momento = agora or _agora_local()
    extensao = (extensao or "docx").lstrip(".")

    return f"parecer_tecnico_{momento.strftime('%Y%m%d_%H%M')}.{extensao}"


def _data_abnt(agora: datetime) -> str:
    """Data de acesso no padrão ABNT: ``17 nov. 2026``."""

    return f"{agora.day:02d} {MESES_ABREVIADOS[agora.month - 1]} {agora.year}"


def _limpar_espacos(texto) -> str:
    """Colapsa espaços, quebras e tabulações em um único espaço."""

    return re.sub(r"\s+", " ", str(texto or "")).strip()


def _sem_acentos(texto) -> str:
    """Versão sem diacríticos, usada apenas para ordenação e busca."""

    decomposto = unicodedata.normalize("NFKD", str(texto or ""))

    return "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    )


def _registro_rastreabilidade(pergunta: str, resposta: str, fontes: list[dict]) -> str:
    """Hash curto que liga o documento à consulta que o originou.

    Não é assinatura digital: serve para localizar a conversa de origem
    em auditoria interna, já que o Parecer é gerado fora do histórico.
    """

    base = "\n".join(
        (
            _limpar_espacos(pergunta),
            _limpar_espacos(resposta),
            "|".join(sorted(_sem_acentos(item.get("titulo", "")) for item in fontes)),
        )
    )

    return sha256(base.encode("utf-8")).hexdigest()[:16].upper()


def titulo_tecnico(pergunta: str, perfil_analitico: str = "") -> str:
    """Deriva um título técnico curto a partir da pergunta.

    Remove comandos conversacionais e cópulas do início (``qual``,
    ``liste``, ``são``, ``explique``...), preservando siglas e nomes
    próprios. Quando a pergunta é vazia, o título usa o perfil analítico
    como assunto.
    """

    texto = _limpar_espacos(pergunta)
    texto = re.sub(r"^(por favor[,]?\s*)", "", texto, flags=re.IGNORECASE)
    comando = re.compile(
        r"^(qual|quais|quanto|quantos|quantas|como|onde|quando|por que|"
        r"porque|liste|listar|mostre|mostrar|explique|explicar|descreva|"
        r"descrever|compare|comparar|faça|faca|elabore|resuma|resumir|"
        r"analise|analisar|informe|informar|diga|me diga|me mostre|"
        r"gostaria de saber|preciso de|quero|são|sao|é|É|estão|estao|"
        r"foram|será|sera|há|ha|existe|existem)\b[\s,:;\-]*",
        re.IGNORECASE,
    )

    for _ in range(3):
        sem_comando = comando.sub("", texto, count=1)

        if sem_comando == texto:
            break

        texto = sem_comando.strip(" ?.;:!-")

        if not texto:
            break

    texto = _limpar_espacos(texto)

    if not texto:
        perfil = _limpar_espacos(perfil_analitico)

        return (
            f"Análise técnica em {perfil}"
            if perfil and perfil.lower().startswith(("geologia", "hidro", "explora"))
            else "Análise Geocientífica Integrada"
        )

    if len(texto) > TAMANHO_MAXIMO_TITULO:
        corte = texto[:TAMANHO_MAXIMO_TITULO].rsplit(" ", 1)[0]

        return f"{corte}…"

    return texto[0].upper() + texto[1:]


# ---------------------------------------------------------------------------
# Normalização dos metadados de fontes
# ---------------------------------------------------------------------------

def _rotulo_da_fonte(chave) -> str:
    """Traduz a chave interna do conector para o rótulo exibido."""

    texto = _limpar_espacos(chave)

    if not texto:
        return "Fonte não identificada"

    return ROTULOS_FONTE.get(texto.lower(), texto)


def _titulo_limpo(valor) -> str:
    """Remove marcação Markdown e pontuação final do título."""

    titulo = str(valor or "")
    titulo = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", titulo)
    titulo = titulo.replace("**", "").replace("__", "").replace("`", "")
    titulo = re.sub(
        r"\.(pdf|docx?|xlsx?|pptx?|md|txt|csv|odt|rtf)$",
        "",
        _limpar_espacos(titulo),
        flags=re.IGNORECASE,
    )
    titulo = _limpar_espacos(titulo)

    return titulo.strip(" .;:")


def _extrair_ano(valor) -> str:
    """Extrai um ano de quatro dígitos de valores variados.

    Os conectores usam ``ano`` tanto para o ano de publicação quanto para
    o status de uma estação (``"Em operação"``); neste último caso não há
    ano e a referência fica como ``s.d.``.
    """

    texto = _limpar_espacos(valor)

    if not texto:
        return ""

    encontrado = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", texto)

    return encontrado.group(1) if encontrado else ""


def _parece_instituicao(nome: str) -> bool:
    """Decide se a autoria é institucional (órgão, empresa, base de dados).

    Nomes pessoais compostos podem conter palavras parecidas com siglas
    (``Ana`` x ``ANA``); por isso as siglas só contam quando aparecem em
    caixa alta no nome original.
    """

    if "/" in nome:
        return True

    minusculo = _sem_acentos(nome).lower()

    if any(palavra in minusculo for palavra in PALAVRAS_INSTITUICAO):
        return True

    for palavra in re.findall(r"[A-Za-zÀ-ÿ]+", nome):
        if palavra.isupper() and _sem_acentos(palavra).lower() in SIGLAS_INSTITUICAO:
            return True

    return False


def _formatar_autores_abnt(autores) -> str:
    """Formata a autoria conforme a NBR 6023.

    - ``Nome Sobrenome`` vira ``SOBRENOME, Nome``;
    - ``Sobrenome, Nome`` tem o sobrenome apenas convertido para caixa
      alta;
    - instituições (``ANA / HidroWeb``, ``USGS ScienceBase``) ficam
      inteiras em caixa alta;
    - a partir de quatro autores, usa-se ``et al.`` depois do primeiro.
    """

    if isinstance(autores, (list, tuple)):
        brutos = [str(item) for item in autores if _limpar_espacos(item)]
    else:
        brutos = [
            parte
            for parte in re.split(r"\s*;\s*", str(autores or ""))
            if _limpar_espacos(parte)
        ]

    if not brutos:
        return ""

    formatados = []

    for bruto in brutos:
        nome = _limpar_espacos(bruto).strip(" .;:,")

        if not nome:
            continue

        if _parece_instituicao(nome):
            formatados.append(nome.upper())
            continue

        if "," in nome:
            sobrenome, complemento = nome.split(",", 1)
            formatados.append(
                f"{_limpar_espacos(sobrenome).upper()}, "
                f"{_limpar_espacos(complemento)}"
            )
            continue

        partes = nome.split()

        if len(partes) == 1:
            formatados.append(nome.upper())
            continue

        if partes[-1].lower() in PARTICULAS_NOME:
            formatados.append(nome)
            continue

        sobrenome = partes[-1].upper()
        prenome = " ".join(partes[:-1])
        formatados.append(f"{sobrenome}, {prenome}")

    if not formatados:
        return ""

    if len(formatados) > 3:
        return f"{formatados[0]} et al."

    return "; ".join(formatados)


def _normalizar_registro(registro: dict, rotulo_grupo: str = "") -> dict:
    """Extrai apenas os campos bibliográficos relevantes de um registro."""

    def primeiro(*chaves):
        for chave in chaves:
            valor = registro.get(chave)

            if _limpar_espacos(valor):
                return valor

        return ""

    fonte = _rotulo_da_fonte(
        primeiro("fonte", "base", "repositorio", "veiculo") or rotulo_grupo
    )

    return {
        "titulo": _titulo_limpo(primeiro("titulo", "title", "nome")),
        "autores": primeiro(
            "autores",
            "autor",
            "authors",
            "autoria",
            "instituicao",
        ),
        "ano": _extrair_ano(primeiro("ano", "year", "publication_year", "data")),
        "fonte": fonte,
        "veiculo": _limpar_espacos(
            primeiro("periodico", "revista", "veiculo", "publicacao")
        ),
        "local": _limpar_espacos(primeiro("local", "cidade", "localidade")),
        "editora": _limpar_espacos(
            primeiro("editora", "publisher", "instituicao_publicadora")
        ),
        "volume": _limpar_espacos(primeiro("volume", "vol")),
        "numero": _limpar_espacos(primeiro("numero", "number", "issue", "fasciculo")),
        "paginas": _limpar_espacos(primeiro("paginas", "pages", "p")),
        "link": primeiro("link", "url", "link_pdf", "permalink", "html_url"),
        "doi": _limpar_espacos(primeiro("doi", "DOI")),
        "tipo": _limpar_espacos(primeiro("tipo", "type", "categoria")),
    }


def normalizar_metadados_fontes(metadados_fontes) -> list[dict]:
    """Achata, higieniza e deduplica os metadados das fontes.

    Aceita tanto grupos no formato usado pelo mapa espacial
    (``{"fonte": "ana", "registros": [...]}``) quanto registros soltos.
    Entradas sem título são descartadas — não há como referenciá-las sem
    placeholder genérico — e a deduplicação usa título e ano, mantendo a
    primeira ocorrência.
    """

    registros: list[dict] = []
    vistos: set[tuple[str, str]] = set()

    for entrada in metadados_fontes or []:
        if not isinstance(entrada, dict):
            continue

        rotulo_grupo = _rotulo_da_fonte(
            entrada.get("fonte") or entrada.get("rotulo") or ""
        )
        filhos = entrada.get("registros")

        if isinstance(filhos, list):
            pares = [
                (filho, rotulo_grupo)
                for filho in filhos
                if isinstance(filho, dict)
            ]
        else:
            pares = [(entrada, rotulo_grupo)]

        for bruto, rotulo in pares:
            item = _normalizar_registro(bruto, rotulo)

            if not item["titulo"]:
                continue

            assinatura = (item["titulo"].lower(), item["ano"])

            if assinatura in vistos:
                continue

            vistos.add(assinatura)
            registros.append(item)

    return registros


def formatar_referencia_abnt(item: dict) -> str:
    """Formata um registro como referência ABNT NBR 6023.

    A ordem dos elementos segue a norma: autoria, título, veículo/local,
    volume, número, páginas, ano e, para documentos online, ``Disponível
    em`` com a data de acesso. ``DOI`` tem precedência sobre a URL.
    """

    autores = _formatar_autores_abnt(item.get("autores")).strip(" .")
    titulo = _titulo_limpo(item.get("titulo"))
    ano = item.get("ano") or _extrair_ano(item.get("ano"))
    veiculo = _limpar_espacos(
        item.get("veiculo") or item.get("fonte")
    ) or "Fonte não identificada"
    local = _limpar_espacos(item.get("local"))
    editora = _limpar_espacos(item.get("editora"))
    volume = _limpar_espacos(item.get("volume"))
    numero = _limpar_espacos(item.get("numero"))
    paginas = _limpar_espacos(item.get("paginas"))
    link = _limpar_espacos(item.get("link"))
    doi = _limpar_espacos(item.get("doi"))

    partes: list[str] = []

    # Autoria igual ao veículo (ex.: "SIAGAS / RIMAS") não precisa repetir.
    if autores and veiculo and _sem_acentos(autores).lower() == _sem_acentos(
        veiculo
    ).lower():
        autores = ""

    if autores:
        partes.append(f"{autores}.")

    if titulo:
        partes.append(f"{titulo}.")

    detalhes = [veiculo]

    if local:
        detalhes.append(local)

    if editora and editora.lower() not in veiculo.lower():
        detalhes.append(editora)

    if volume:
        detalhes.append(f"v. {volume}")

    if numero:
        detalhes.append(f"n. {numero}")

    if paginas:
        detalhes.append(f"p. {paginas}")

    detalhes.append(ano or "s.d.")

    descricao = ", ".join(detalhes).rstrip(".")
    partes.append(f"{descricao}.")

    if doi:
        identificador = doi

        if identificador.lower().startswith("10."):
            identificador = f"https://doi.org/{identificador}"

        partes.append(f"Disponível em: {identificador}.")
    elif link.lower().startswith(("http://", "https://")):
        partes.append(f"Disponível em: {link}.")

    referencia = " ".join(parte.strip() for parte in partes if parte.strip())
    referencia = re.sub(r"\s+", " ", referencia).strip()
    # "s.d." e afins já terminam em ponto: evita o ponto duplicado.
    referencia = re.sub(r"\.{2,}", ".", referencia)

    if doi or link.lower().startswith(("http://", "https://")):
        referencia += f" Acesso em: {_data_abnt(_agora_local())}."

    return referencia


def _ordenar_referencias(referencias: list[str]) -> list[str]:
    """Ordena alfabeticamente, ignorando acentos e caixa."""

    return sorted(referencias, key=lambda item: _sem_acentos(item).lower())


# ---------------------------------------------------------------------------
# Conversão de Markdown em elementos do Word
# ---------------------------------------------------------------------------

_RE_TITULO = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_RE_REGUA = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_RE_SEPARADOR_TABELA = re.compile(
    r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$"
)
_RE_ITEM_BULLET = re.compile(r"^(\s*)[-*+•]\s+(.*)$")
_RE_ITEM_NUMERO = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_RE_CITACAO = re.compile(r"^\s*>\s?(.*)$")
_RE_CODIGO = re.compile(r"^\s*```")
_RE_URL = re.compile(r"(https?://[^\s<>()\[\]]+[^\s<>()\[\].,;:!?])")

_RE_INLINE = re.compile(
    r"(?P<negrito>\*\*(?P<negrito_txt>.+?)\*\*)"
    r"|(?P<italico>(?<![\*\w])\*(?!\*)(?P<italico_txt>.+?)(?<!\*)\*(?!\*))"
    r"|(?P<riscado>~~(?P<riscado_txt>.+?)~~)"
    r"|(?P<codigo>`(?P<codigo_txt>[^`]+)`)"
    r"|(?P<link>\[(?P<link_txt>[^\]]+)\]\((?P<link_url>[^)\s]+)"
    r"(?:\s+\"[^\"]*\")?\))"
)


def _dividir_linha_tabela(linha: str) -> list[str]:
    """Divide uma linha de tabela Markdown em células."""

    texto = linha.strip()
    texto = texto.removeprefix("|")

    if texto.endswith("|") and not texto.endswith("\\|"):
        texto = texto[:-1]

    celulas = re.split(r"(?<!\\)\|", texto)

    return [
        celula.replace("\\|", "|").strip()
        for celula in celulas
    ]


def _inicio_de_bloco(linha: str) -> bool:
    """Indica se a linha abre um bloco próprio dentro do Markdown."""

    texto = linha.strip()

    return bool(
        not texto
        or _RE_TITULO.match(linha)
        or _RE_REGUA.match(texto)
        or _RE_ITEM_BULLET.match(linha)
        or _RE_ITEM_NUMERO.match(linha)
        or _RE_CITACAO.match(linha)
        or _RE_CODIGO.match(linha)
    )


def _blocos_markdown(texto: str):
    """Percorre o Markdown e devolve blocos tipados.

    Tipos: ``titulo``, ``paragrafo``, ``item``, ``numero``, ``citacao``,
    ``codigo``, ``tabela`` e ``regua``. A leitura é tolerante: uma
    construção que não seja reconhecida vira parágrafo comum.
    """

    linhas = (
        str(texto or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )
    indice = 0
    total = len(linhas)

    while indice < total:
        linha = linhas[indice]
        sem = linha.strip()

        if not sem:
            indice += 1
            continue

        if _RE_CODIGO.match(linha):
            indice += 1
            corpo: list[str] = []

            while indice < total and not _RE_CODIGO.match(linhas[indice]):
                corpo.append(linhas[indice])
                indice += 1

            indice += 1
            yield ("codigo", "\n".join(corpo))
            continue

        achado = _RE_TITULO.match(sem)

        if achado:
            yield ("titulo", len(achado.group(1)), achado.group(2).strip())
            indice += 1
            continue

        if _RE_REGUA.match(sem):
            yield ("regua",)
            indice += 1
            continue

        if (
            "|" in sem
            and indice + 1 < total
            and _RE_SEPARADOR_TABELA.match(linhas[indice + 1])
        ):
            cabecalhos = _dividir_linha_tabela(sem)
            indice += 2
            linhas_dados: list[list[str]] = []

            while (
                indice < total
                and linhas[indice].strip()
                and "|" in linhas[indice]
            ):
                linhas_dados.append(_dividir_linha_tabela(linhas[indice]))
                indice += 1

            yield ("tabela", cabecalhos, linhas_dados)
            continue

        if _RE_CITACAO.match(linha):
            citacao: list[str] = []

            while indice < total and linhas[indice].strip().startswith(">"):
                citacao.append(_RE_CITACAO.match(linhas[indice]).group(1).strip())
                indice += 1

            yield ("citacao", _limpar_espacos(" ".join(citacao)))
            continue

        achado = _RE_ITEM_BULLET.match(linha)

        if achado:
            recuo = len(achado.group(1).replace("\t", "    "))
            yield ("item", 2 if recuo >= 2 else 1, achado.group(2).strip())
            indice += 1
            continue

        achado = _RE_ITEM_NUMERO.match(linha)

        if achado:
            recuo = len(achado.group(1).replace("\t", "    "))
            yield (
                "numero",
                2 if recuo >= 2 else 1,
                achado.group(2),
                achado.group(3).strip(),
            )
            indice += 1
            continue

        paragrafo = [sem]
        indice += 1

        while indice < total and not _inicio_de_bloco(linhas[indice]):
            # Uma tabela colada no parágrafo (sem linha em branco) ainda
            # precisa ser reconhecida como tabela.
            if (
                "|" in linhas[indice]
                and indice + 1 < total
                and _RE_SEPARADOR_TABELA.match(linhas[indice + 1])
            ):
                break

            paragrafo.append(linhas[indice].strip())
            indice += 1

        yield ("paragrafo", " ".join(paragrafo))


def _configurar_fonte_run(run, negrito=False, italico=False, codigo=False,
                          tamanho=None, cor=None, riscado=False):
    """Aplica a formatação tipográfica a um trecho de texto."""

    run.bold = bool(negrito)
    run.italic = bool(italico)
    run.font.name = FONTE_TECNICA if codigo else FONTE_CORPO

    if tamanho is not None:
        run.font.size = Pt(tamanho)

    if cor is not None:
        run.font.color.rgb = RGBColor.from_string(cor)

    if riscado:
        run.font.strike = True


def _adicionar_hyperlink(paragrafo, url: str, texto: str, tamanho=None):
    """Insere um hyperlink externo em um parágrafo do Word."""

    try:
        identificador = paragrafo.part.relate_to(url, RT.HYPERLINK, is_external=True)
    except Exception:  # pragma: no cover - URL inválida em documento
        run = paragrafo.add_run(texto)
        _configurar_fonte_run(run, tamanho=tamanho)
        return

    hiperlink = OxmlElement("w:hyperlink")
    hiperlink.set(qn("r:id"), identificador)

    run = OxmlElement("w:r")
    propriedades = OxmlElement("w:rPr")

    cor = OxmlElement("w:color")
    cor.set(qn("w:val"), "0563C1")
    propriedades.append(cor)

    sublinhado = OxmlElement("w:u")
    sublinhado.set(qn("w:val"), "single")
    propriedades.append(sublinhado)

    if tamanho is not None:
        metade = str(int(tamanho * 2))
        tamanho_xml = OxmlElement("w:sz")
        tamanho_xml.set(qn("w:val"), metade)
        propriedades.append(tamanho_xml)

    run.append(propriedades)

    trecho = OxmlElement("w:t")
    trecho.set(qn("xml:space"), "preserve")
    trecho.text = texto
    run.append(trecho)
    hiperlink.append(run)
    paragrafo._p.append(hiperlink)


def _escrever_trecho_plano(paragrafo, texto: str, **formato):
    """Escreve texto puro, transformando URLs soltas em links."""

    if not texto:
        return

    ultimo = 0

    for achado in _RE_URL.finditer(texto):
        antes = texto[ultimo:achado.start()]

        if antes:
            run = paragrafo.add_run(antes)
            _configurar_fonte_run(run, **formato)

        _adicionar_hyperlink(
            paragrafo,
            achado.group(1),
            achado.group(1),
            tamanho=formato.get("tamanho"),
        )
        ultimo = achado.end()

    restante = texto[ultimo:]

    if restante:
        run = paragrafo.add_run(restante)
        _configurar_fonte_run(run, **formato)


def _escrever_inline(paragrafo, texto: str, negrito=False, italico=False,
                     tamanho=None, cor=None):
    """Escreve Markdown inline (negrito, itálico, código e links).

    O parser é deliberadamente simples e linear: cada marcação encontrada
    gera um trecho formatado, e o restante continua como texto comum.
    """

    restante = str(texto or "")
    posicao = 0

    while posicao < len(restante):
        achado = _RE_INLINE.search(restante, posicao)

        if not achado:
            _escrever_trecho_plano(
                paragrafo,
                restante[posicao:],
                negrito=negrito,
                italico=italico,
                tamanho=tamanho,
                cor=cor,
            )
            break

        if achado.start() > posicao:
            _escrever_trecho_plano(
                paragrafo,
                restante[posicao:achado.start()],
                negrito=negrito,
                italico=italico,
                tamanho=tamanho,
                cor=cor,
            )

        if achado.group("negrito"):
            _escrever_inline(
                paragrafo,
                achado.group("negrito_txt"),
                negrito=True,
                italico=italico,
                tamanho=tamanho,
                cor=cor,
            )
        elif achado.group("italico"):
            _escrever_inline(
                paragrafo,
                achado.group("italico_txt"),
                negrito=negrito,
                italico=True,
                tamanho=tamanho,
                cor=cor,
            )
        elif achado.group("codigo"):
            run = paragrafo.add_run(achado.group("codigo_txt"))
            _configurar_fonte_run(
                run,
                negrito=negrito,
                italico=italico,
                codigo=True,
                tamanho=(tamanho or 10.5) - 1,
                cor=cor,
            )
        elif achado.group("riscado"):
            run = paragrafo.add_run(achado.group("riscado_txt"))
            _configurar_fonte_run(
                run,
                negrito=negrito,
                italico=italico,
                tamanho=tamanho,
                cor=cor,
                riscado=True,
            )
        elif achado.group("link"):
            _adicionar_hyperlink(
                paragrafo,
                achado.group("link_url"),
                achado.group("link_txt"),
                tamanho=tamanho,
            )

        posicao = achado.end()


# ---------------------------------------------------------------------------
# Blocos nativos do Word: tabelas, títulos, listas e realces
# ---------------------------------------------------------------------------

def _definir_idioma(documento):
    """Marca o documento como português do Brasil para revisão ortográfica."""

    try:
        idioma = OxmlElement("w:lang")
        idioma.set(qn("w:val"), "pt-BR")
        idioma.set(qn("w:eastAsia"), "pt-BR")
        idioma.set(qn("w:bidi"), "ar-SA")
        documento.styles["Normal"].element.get_or_add_rPr().append(idioma)
    except Exception:  # pragma: no cover - estilo ausente no template
        pass


def _sombra_celula(celula, cor: str):
    """Aplica preenchimento de fundo a uma célula."""

    propriedades = celula._tc.get_or_add_tcPr()
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:val"), "clear")
    sombra.set(qn("w:color"), "auto")
    sombra.set(qn("w:fill"), cor)
    propriedades.insert_element_before(
        sombra,
        "w:noWrap",
        "w:tcMar",
        "w:textDirection",
        "w:tcFitText",
        "w:vAlign",
        "w:hideMark",
    )


def _margens_tabela(tabela, topo=40, baixo=40, esquerda=80, direita=80):
    """Ajusta as margens internas da tabela (em twips)."""

    propriedades = tabela._tbl.tblPr
    margens = OxmlElement("w:tblCellMar")

    for lado, valor in (
        ("top", topo),
        ("left", esquerda),
        ("bottom", baixo),
        ("right", direita),
    ):
        elemento = OxmlElement(f"w:{lado}")
        elemento.set(qn("w:w"), str(valor))
        elemento.set(qn("w:type"), "dxa")
        margens.append(elemento)

    propriedades.insert_element_before(
        margens,
        "w:tblLook",
        "w:tblCaption",
        "w:tblDescription",
    )


def _repetir_cabecalho(linha):
    """Marca a linha de cabeçalho para repetir em cada página."""

    propriedades = linha._tr.get_or_add_trPr()
    cabecalho = OxmlElement("w:tblHeader")
    cabecalho.set(qn("w:val"), "true")
    propriedades.append(cabecalho)


def _borda_paragrafo(paragrafo, lado: str = "bottom",
                     cor: str = COR_CINZA_BORDA, tamanho: int = 6,
                     espaco: str = "4"):
    """Desenha uma borda no parágrafo, na posição indicada.

    A posição importa: o rodapé usa ``top`` (linha acima da nota) e o
    cabeçalho usa ``bottom`` (linha abaixo da identificação).
    """

    propriedades = paragrafo._p.get_or_add_pPr()
    bordas = OxmlElement("w:pBdr")
    elemento = OxmlElement(f"w:{lado}")
    elemento.set(qn("w:val"), "single")
    elemento.set(qn("w:sz"), str(tamanho))
    elemento.set(qn("w:space"), espaco)
    elemento.set(qn("w:color"), cor)
    bordas.append(elemento)
    propriedades.insert_element_before(
        bordas,
        "w:shd",
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def _borda_inferior(paragrafo, cor: str = COR_CINZA_BORDA, tamanho: int = 6):
    """Atalho para a borda inferior usada como régua."""

    _borda_paragrafo(paragrafo, "bottom", cor=cor, tamanho=tamanho)


def _borda_esquerda(paragrafo, cor: str = COR_AZUL_MEDIO, tamanho: int = 18):
    """Atalho para a barra vertical de citação."""

    _borda_paragrafo(
        paragrafo, "left", cor=cor, tamanho=tamanho, espaco="8"
    )


def _sombra_paragrafo(paragrafo, cor: str):
    """Aplica fundo claro a um parágrafo (blocos de código)."""

    propriedades = paragrafo._p.get_or_add_pPr()
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:val"), "clear")
    sombra.set(qn("w:color"), "auto")
    sombra.set(qn("w:fill"), cor)
    propriedades.insert_element_before(
        sombra,
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def _formatar_celula(valor) -> str:
    """Converte qualquer valor tabular em texto legível."""

    if valor is None:
        return ""

    try:
        if valor != valor:  # NaN
            return ""
    except Exception:  # pragma: no cover - tipo exótico
        pass

    if isinstance(valor, float):
        if valor.is_integer():
            return str(int(valor))

        return f"{valor:.5f}".rstrip("0").rstrip(".")

    return _limpar_espacos(valor)


def _feicoes_validas(feicoes) -> list[dict]:
    """Filtra feições com coordenadas numéricas dentro dos limites WGS84.

    O parecer pode ser gerado a partir de um histórico JSON editado ou
    antigo; uma coordenada textual não pode derrubar a exportação.
    """

    validas = []

    for feicao in feicoes or []:
        if not isinstance(feicao, dict):
            continue

        try:
            latitude = float(feicao.get("lat"))
            longitude = float(feicao.get("lon"))
        except (TypeError, ValueError):
            continue

        if not (-90.0 <= latitude <= 90.0):
            continue

        if not (-180.0 <= longitude <= 180.0):
            continue

        item = dict(feicao)
        item["lat"] = latitude
        item["lon"] = longitude
        validas.append(item)

    return validas


def _coluna_numerica(cabecalho: str, valores: list[str]) -> bool:
    """Heurística para alinhar à direita colunas de coordenadas e números."""

    titulo = _sem_acentos(cabecalho).lower()
    amostra = [valor for valor in valores if valor][:5]

    if not amostra:
        return False

    if any(chave in titulo for chave in ("lat", "lon", "ano", "valor", "área", "area")):
        return True

    return all(
        re.fullmatch(r"-?\d+(?:[.,]\d+)?", valor) for valor in amostra
    )


def _adicionar_tabela(documento, cabecalhos, linhas, larguras=None,
                      fonte_pt=9.0):
    """Insere uma tabela nativa estilizada e devolve o objeto criado.

    ``larguras`` é uma lista de pesos relativos (ex.: ``[3, 2, 1]``); sem
    ela, as colunas recebem a mesma largura. Células aceitam Markdown
    inline (negrito, itálico e links).
    """

    if not cabecalhos:
        return None

    colunas = min(len(cabecalhos), MAXIMO_COLUNAS_TABELA)
    cabecalhos = [
        _formatar_celula(cabecalho) for cabecalho in cabecalhos[:colunas]
    ]
    linhas = [list(linha)[:colunas] for linha in linhas or []]

    tabela = documento.add_table(rows=1, cols=colunas)
    tabela.style = "Table Grid"
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabela.autofit = False
    _margens_tabela(tabela)

    pesos = list(larguras or [1] * colunas)[:colunas]
    total_pesos = float(sum(pesos) or colunas)
    largura_util = 16.0  # cm úteis entre margens de 2,5 e 2,0 cm

    if len(pesos) < colunas:
        pesos += [1] * (colunas - len(pesos))
        total_pesos = float(sum(pesos))

    larguras_cm = [
        max(1.4, largura_util * peso / total_pesos) for peso in pesos
    ]

    linha_cabecalho = tabela.rows[0]
    _repetir_cabecalho(linha_cabecalho)

    # Alinhamento calculado uma única vez por coluna, a partir dos valores
    # já formatados; é o mesmo no cabeçalho e nas células de dados.
    linhas_formatadas = [
        (
            [_formatar_celula(valor) for valor in linha]
            + [""] * max(colunas - len(linha), 0)
        )[:colunas]
        for linha in linhas
    ]
    alinhamentos = [
        _coluna_numerica(
            cabecalhos[indice],
            [linha[indice] for linha in linhas_formatadas],
        )
        for indice in range(colunas)
    ]

    for indice, texto in enumerate(cabecalhos):
        celula = linha_cabecalho.cells[indice]
        celula.width = Cm(larguras_cm[indice])
        _sombra_celula(celula, COR_AZUL_ESCURO)
        paragrafo = celula.paragraphs[0]
        paragrafo.paragraph_format.space_after = Pt(0)

        if alinhamentos[indice]:
            paragrafo.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        _escrever_inline(
            paragrafo,
            texto,
            negrito=True,
            tamanho=fonte_pt,
            cor="FFFFFF",
        )

    for posicao, valores in enumerate(linhas_formatadas):
        celulas = tabela.add_row().cells
        preenchimento = COR_CINZA_CLARO if posicao % 2 else "FFFFFF"

        for indice in range(colunas):
            celula = celulas[indice]
            celula.width = Cm(larguras_cm[indice])
            _sombra_celula(celula, preenchimento)
            paragrafo = celula.paragraphs[0]
            paragrafo.paragraph_format.space_after = Pt(0)
            paragrafo.paragraph_format.line_spacing = 1.0

            if alinhamentos[indice]:
                paragrafo.alignment = WD_ALIGN_PARAGRAPH.RIGHT

            _escrever_inline(paragrafo, valores[indice], tamanho=fonte_pt)

    return tabela


def _adicionar_titulo(documento, texto: str, nivel: int = 1):
    """Cria um título numerado das seções do parecer."""

    paragrafo = documento.add_heading(level=nivel)

    if nivel == 1:
        run = paragrafo.add_run(texto)
        _configurar_fonte_run(
            run, negrito=True, tamanho=14, cor=COR_AZUL_ESCURO
        )
    else:
        run = paragrafo.add_run(texto)
        _configurar_fonte_run(
            run,
            negrito=True,
            tamanho=12 if nivel == 2 else 11,
            cor=COR_AZUL_MEDIO if nivel == 2 else COR_CINZA_TEXTO,
        )

    paragrafo.paragraph_format.space_before = Pt(14 if nivel == 1 else 10)
    paragrafo.paragraph_format.space_after = Pt(6)
    paragrafo.paragraph_format.keep_with_next = True

    return paragrafo


def _renderizar_markdown(documento, texto: str):
    """Converte o Markdown do assistente em conteúdo nativo do Word."""

    for bloco in _blocos_markdown(texto):
        tipo = bloco[0]

        if tipo == "titulo":
            _nivel, nivel_markdown, conteudo = bloco
            nivel_word = min(2 + nivel_markdown, 5)
            _adicionar_titulo(documento, conteudo, nivel=nivel_word)

        elif tipo == "paragrafo":
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.space_after = Pt(6)
            paragrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _escrever_inline(paragrafo, bloco[1])

        elif tipo == "item":
            _tipo, nivel, conteudo = bloco
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.left_indent = Cm(0.75 * nivel)
            paragrafo.paragraph_format.first_line_indent = Cm(-0.4)
            paragrafo.paragraph_format.space_after = Pt(3)
            marcador = "•" if nivel == 1 else "–"
            run = paragrafo.add_run(f"{marcador} ")
            _configurar_fonte_run(run, cor=COR_AZUL_MEDIO)
            _escrever_inline(paragrafo, conteudo)

        elif tipo == "numero":
            _tipo, nivel, numero, conteudo = bloco
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.left_indent = Cm(0.75 * nivel + 0.4)
            paragrafo.paragraph_format.first_line_indent = Cm(-0.7)
            paragrafo.paragraph_format.space_after = Pt(3)
            run = paragrafo.add_run(f"{numero}. ")
            _configurar_fonte_run(run, negrito=True, cor=COR_AZUL_MEDIO)
            _escrever_inline(paragrafo, conteudo)

        elif tipo == "citacao":
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.left_indent = Cm(0.8)
            paragrafo.paragraph_format.space_before = Pt(4)
            paragrafo.paragraph_format.space_after = Pt(8)
            _borda_esquerda(paragrafo)
            _escrever_inline(paragrafo, bloco[1], italico=True)

        elif tipo == "codigo":
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.left_indent = Cm(0.4)
            paragrafo.paragraph_format.space_before = Pt(4)
            paragrafo.paragraph_format.space_after = Pt(8)
            _sombra_paragrafo(paragrafo, COR_CINZA_CLARO)
            run = paragrafo.add_run(bloco[1])
            _configurar_fonte_run(
                run, codigo=True, tamanho=8.5, cor=COR_CINZA_TEXTO
            )

        elif tipo == "regua":
            paragrafo = documento.add_paragraph()
            paragrafo.paragraph_format.space_before = Pt(2)
            paragrafo.paragraph_format.space_after = Pt(8)
            _borda_inferior(paragrafo)

        elif tipo == "tabela":
            _tipo, cabecalhos, linhas = bloco

            if len(linhas) > MAXIMO_LINHAS_TABELA:
                linhas = linhas[:MAXIMO_LINHAS_TABELA]
                aviso = documento.add_paragraph()
                run = aviso.add_run(
                    "Tabela truncada em "
                    f"{MAXIMO_LINHAS_TABELA} linhas para caber no parecer."
                )
                _configurar_fonte_run(
                    run, italico=True, tamanho=8, cor=COR_CINZA_TEXTO
                )

            _adicionar_tabela(documento, cabecalhos, linhas)

            legenda = documento.add_paragraph()
            legenda.paragraph_format.space_before = Pt(2)
            legenda.paragraph_format.space_after = Pt(10)


# ---------------------------------------------------------------------------
# Estrutura do documento Word
# ---------------------------------------------------------------------------

def _novo_documento(agora: datetime, titulo: str):
    """Cria o documento A4 com estilos, margens e idioma."""

    documento = Document()
    secao = documento.sections[0]
    secao.page_width = Cm(21.0)
    secao.page_height = Cm(29.7)
    secao.top_margin = Cm(2.5)
    secao.bottom_margin = Cm(2.0)
    secao.left_margin = Cm(2.5)
    secao.right_margin = Cm(2.0)
    secao.header_distance = Cm(1.25)
    secao.footer_distance = Cm(1.0)

    normal = documento.styles["Normal"]
    normal.font.name = FONTE_CORPO
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string("262626")
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    _definir_idioma(documento)

    propriedades = documento.core_properties
    propriedades.title = titulo
    propriedades.author = f"{APP_NAME} v{APP_VERSION}"
    propriedades.subject = "Parecer Técnico Geocientífico"
    propriedades.keywords = "geociências; parecer técnico; ABNT NBR 6023"
    propriedades.comments = (
        f"Documento gerado automaticamente pelo {APP_NAME} "
        f"v{APP_VERSION} em {carimbo_data_hora(agora)}."
    )

    return documento


def _cabecalho_pagina(documento, perfil_analitico: str):
    """Cabeçalho institucional repetido em todas as páginas."""

    cabecalho = documento.sections[0].header
    paragrafo = cabecalho.paragraphs[0]
    paragrafo.paragraph_format.tab_stops.add_tab_stop(
        Cm(16.5), WD_TAB_ALIGNMENT.RIGHT
    )
    run = paragrafo.add_run(
        f"{APP_NAME.upper()} v{APP_VERSION} · PARECER TÉCNICO"
    )
    _configurar_fonte_run(run, negrito=True, tamanho=8, cor=COR_AZUL_ESCURO)
    run = paragrafo.add_run("\t" + _limpar_espacos(perfil_analitico))
    _configurar_fonte_run(run, tamanho=8, cor=COR_CINZA_TEXTO)
    _borda_inferior(paragrafo, cor=COR_AZUL_MEDIO, tamanho=4)


def _rodape_pagina(documento, agora: datetime, rastreio: str):
    """Rodapé com numeração de página e nota de rastreabilidade."""

    rodape = documento.sections[0].footer
    primeiro = rodape.paragraphs[0]
    primeiro.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = primeiro.add_run("Página ")
    _configurar_fonte_run(run, tamanho=8, cor=COR_CINZA_TEXTO)
    _campo_word(primeiro, "PAGE")
    run = primeiro.add_run(" de ")
    _configurar_fonte_run(run, tamanho=8, cor=COR_CINZA_TEXTO)
    _campo_word(primeiro, "NUMPAGES")

    nota = rodape.add_paragraph()
    nota.alignment = WD_ALIGN_PARAGRAPH.CENTER
    nota.paragraph_format.space_before = Pt(4)
    _borda_paragrafo(nota, "top", cor=COR_CINZA_BORDA, tamanho=4)
    run = nota.add_run(
        f"Documento gerado pelo {APP_NAME} v{APP_VERSION} · "
        f"{carimbo_data_hora(agora)} · Rastreabilidade {rastreio}"
    )
    _configurar_fonte_run(run, tamanho=7, cor=COR_CINZA_TEXTO)


def _campo_word(paragrafo, instrucao: str):
    """Insere um campo do Word (``PAGE``/``NUMPAGES``) no parágrafo."""

    run = paragrafo.add_run()

    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")

    texto_instrucao = OxmlElement("w:instrText")
    texto_instrucao.set(qn("xml:space"), "preserve")
    texto_instrucao.text = f" {instrucao} "

    separador = OxmlElement("w:fldChar")
    separador.set(qn("w:fldCharType"), "separate")

    valor = OxmlElement("w:t")
    valor.text = "1"

    fim = OxmlElement("w:fldChar")
    fim.set(qn("w:fldCharType"), "end")

    for elemento in (inicio, texto_instrucao, separador, valor, fim):
        run._r.append(elemento)

    _configurar_fonte_run(run, tamanho=8, cor=COR_CINZA_TEXTO)


def _bloco_metadados(documento, perfil_analitico: str, bases: str,
                     rastreio: str, agora: datetime):
    """Tabela de identificação do documento, sem bordas aparentes."""

    linhas = (
        ("Emissão", carimbo_data_hora(agora)),
        ("Perfil analítico", _limpar_espacos(perfil_analitico) or "Não informado"),
        ("Bases consultadas", bases),
        ("Registro de rastreabilidade", rastreio),
    )

    tabela = documento.add_table(rows=0, cols=2)
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabela.autofit = False
    _margens_tabela(tabela, topo=60, baixo=60, esquerda=100, direita=100)

    for rotulo, valor in linhas:
        celulas = tabela.add_row().cells
        celulas[0].width = Cm(4.4)
        celulas[1].width = Cm(11.4)
        _sombra_celula(celulas[0], "E8EDF5")
        _sombra_celula(celulas[1], "FFFFFF")

        paragrafo = celulas[0].paragraphs[0]
        paragrafo.paragraph_format.space_after = Pt(0)
        run = paragrafo.add_run(rotulo)
        _configurar_fonte_run(run, negrito=True, tamanho=9, cor=COR_AZUL_ESCURO)

        paragrafo = celulas[1].paragraphs[0]
        paragrafo.paragraph_format.space_after = Pt(0)
        run = paragrafo.add_run(valor)
        _configurar_fonte_run(run, tamanho=9, cor="262626")

    return tabela


def _cabecalho_institucional(documento, titulo: str, perfil_analitico: str,
                             bases: str, rastreio: str, agora: datetime):
    """Título técnico, subtítulo e bloco de metadados de emissão."""

    paragrafo = documento.add_paragraph()
    paragrafo.paragraph_format.space_before = Pt(6)
    paragrafo.paragraph_format.space_after = Pt(2)
    run = paragrafo.add_run("PARECER TÉCNICO GEOCIENTÍFICO")
    _configurar_fonte_run(
        run, negrito=True, tamanho=20, cor=COR_AZUL_ESCURO
    )

    subtitulo = documento.add_paragraph()
    subtitulo.paragraph_format.space_after = Pt(4)
    run = subtitulo.add_run(titulo)
    _configurar_fonte_run(
        run, negrito=True, tamanho=12.5, cor=COR_AZUL_MEDIO
    )

    regua = documento.add_paragraph()
    regua.paragraph_format.space_after = Pt(10)
    _borda_inferior(regua, cor=COR_AZUL_MEDIO, tamanho=10)

    _bloco_metadados(documento, perfil_analitico, bases, rastreio, agora)

    documento.add_paragraph().paragraph_format.space_after = Pt(2)


def _secao_escopo(documento, pergunta: str):
    """Seção 1: pergunta analisada, em caixa de citação."""

    _adicionar_titulo(documento, "1. Escopo / Consulta Técnica", nivel=1)

    tabela = documento.add_table(rows=1, cols=1)
    tabela.autofit = False
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    _margens_tabela(tabela, topo=90, baixo=90, esquerda=140, direita=140)
    celula = tabela.rows[0].cells[0]
    celula.width = Cm(16.0)
    _sombra_celula(celula, "F4F7FB")

    paragrafo = celula.paragraphs[0]
    paragrafo.paragraph_format.space_after = Pt(0)
    paragrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = paragrafo.add_run("Consulta: ")
    _configurar_fonte_run(run, negrito=True, tamanho=10, cor=COR_AZUL_ESCURO)
    texto = _limpar_espacos(pergunta) or "Consulta não informada."
    _escrever_inline(paragrafo, texto, italico=True, tamanho=10)

    nota = documento.add_paragraph()
    nota.paragraph_format.space_before = Pt(6)
    run = nota.add_run(
        "A análise a seguir responde à consulta acima com base nas fontes "
        "listadas no item 4; interpretações e lacunas são indicadas no "
        "próprio texto."
    )
    _configurar_fonte_run(run, italico=True, tamanho=8.5, cor=COR_CINZA_TEXTO)


def _adicionar_tabelas_extraidas(documento, tabelas_extraidas):
    """Anexa à seção 2 as tabelas extraídas dos documentos locais."""

    if not tabelas_extraidas:
        return

    _adicionar_titulo(
        documento, "2.1. Tabelas extraídas dos documentos", nivel=2
    )

    incluidas = 0

    for tabela in tabelas_extraidas:
        if not isinstance(tabela, dict):
            continue

        dados = tabela.get("df_limpo")

        if dados is None:
            dados = tabela.get("df_bruto")

        colunas_brutas = getattr(dados, "columns", None)
        colunas = list(colunas_brutas) if colunas_brutas is not None else []

        if not colunas:
            continue

        legenda = documento.add_paragraph()
        legenda.paragraph_format.space_before = Pt(6)
        legenda.paragraph_format.space_after = Pt(3)
        legenda.paragraph_format.keep_with_next = True
        run = legenda.add_run(
            f"Tabela {incluidas + 1} — "
            f"{_titulo_limpo(tabela.get('titulo')) or 'Tabela extraída'}"
        )
        _configurar_fonte_run(run, negrito=True, tamanho=9, cor=COR_AZUL_MEDIO)

        origem = _limpar_espacos(
            f"{tabela.get('caminho') or tabela.get('origem') or ''}"
        )

        if tabela.get("pagina"):
            origem = f"{origem} (p. {tabela['pagina']})"

        if origem:
            nota = documento.add_paragraph()
            nota.paragraph_format.space_after = Pt(3)
            run = nota.add_run(f"Origem: {origem}")
            _configurar_fonte_run(run, italico=True, tamanho=8, cor=COR_CINZA_TEXTO)

        try:
            linhas = [
                list(linha)
                for linha in dados.itertuples(index=False, name=None)
            ]
        except Exception:  # pragma: no cover - dataframe exótico
            continue

        if len(linhas) > MAXIMO_LINHAS_TABELA_EXTRAIDA:
            linhas = linhas[:MAXIMO_LINHAS_TABELA_EXTRAIDA]

        _adicionar_tabela(
            documento,
            [str(coluna) for coluna in colunas],
            linhas,
            fonte_pt=8.5,
        )
        incluidas += 1

        espaco = documento.add_paragraph()
        espaco.paragraph_format.space_after = Pt(6)


def _secao_analise(documento, resposta_md: str, tabelas_extraidas):
    """Seção 2: conversão do Markdown do assistente."""

    _adicionar_titulo(documento, "2. Análise Técnica e Interpretação", nivel=1)

    if _limpar_espacos(resposta_md):
        _renderizar_markdown(documento, resposta_md)
    else:
        paragrafo = documento.add_paragraph()
        run = paragrafo.add_run(
            "Não há conteúdo de análise registrado para esta consulta."
        )
        _configurar_fonte_run(run, italico=True)

    _adicionar_tabelas_extraidas(documento, tabelas_extraidas)


def _secao_espacial(documento, feicoes_espaciais):
    """Seção 3 (condicional): síntese espacial em WGS84."""

    feicoes = _feicoes_validas(feicoes_espaciais)

    if not feicoes:
        return

    _adicionar_titulo(documento, "3. Síntese Espacial", nivel=1)

    paragrafo = documento.add_paragraph()
    paragrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = paragrafo.add_run(
        "As coordenadas abaixo estão no sistema geodésico WGS84 "
        "(graus decimais, cinco casas ≈ 1 m), conforme as camadas e as "
        "folhas CIM citadas na análise. A tabela serve de referência para "
        "conferência em SIG e não substitui o levantamento de campo."
    )
    _configurar_fonte_run(run, tamanho=9.5)

    linhas = []

    for feicao in feicoes:
        linhas.append([
            _limpar_espacos(feicao.get("nome")) or "Sem identificação",
            _limpar_espacos(feicao.get("camada")) or "Outras fontes",
            f"{float(feicao['lat']):.5f}",
            f"{float(feicao['lon']):.5f}",
            _limpar_espacos(feicao.get("folha_cim")),
            _limpar_espacos(feicao.get("limites")),
        ])

    if len(linhas) > MAXIMO_LINHAS_TABELA:
        linhas = linhas[:MAXIMO_LINHAS_TABELA]

    _adicionar_tabela(
        documento,
        [
            "Identificação",
            "Camada / fonte",
            "Latitude",
            "Longitude",
            "Folha CIM",
            "Limites",
        ],
        linhas,
        larguras=[4.2, 3.2, 1.9, 1.9, 2.2, 2.6],
        fonte_pt=8.5,
    )

    legenda = documento.add_paragraph()
    legenda.paragraph_format.space_before = Pt(3)
    camadas = sorted({
        _limpar_espacos(feicao.get("camada")) or "Outras fontes"
        for feicao in feicoes
    })
    run = legenda.add_run(
        f"{len(feicoes)} feição(ões) espacial(is) em "
        f"{len(camadas)} camada(s): {', '.join(camadas)}."
    )
    _configurar_fonte_run(run, italico=True, tamanho=8, cor=COR_CINZA_TEXTO)


def _secao_referencias(documento, referencias: list[str]):
    """Seção 4: referências consultadas no padrão ABNT."""

    _adicionar_titulo(
        documento, "4. Referências Consultadas (ABNT NBR 6023)", nivel=1
    )

    if not referencias:
        paragrafo = documento.add_paragraph()
        run = paragrafo.add_run(
            "Nenhuma fonte externa foi registrada nesta consulta; a "
            "análise é baseada no conhecimento do modelo e na base "
            "documental local, quando indicada no escopo."
        )
        _configurar_fonte_run(run, italico=True, tamanho=9.5)
        return

    for referencia in referencias:
        paragrafo = documento.add_paragraph()
        paragrafo.paragraph_format.left_indent = Cm(0.8)
        paragrafo.paragraph_format.first_line_indent = Cm(-0.8)
        paragrafo.paragraph_format.space_after = Pt(6)
        paragrafo.paragraph_format.line_spacing = 1.0
        paragrafo.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _escrever_inline(paragrafo, referencia, tamanho=9.5)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def _resumo_das_bases(fontes: list[dict]) -> str:
    """Lista, sem repetição, os rótulos das bases que trouxeram registros."""

    rotulos = []

    for item in fontes:
        rotulo = _limpar_espacos(item.get("fonte"))

        if rotulo and rotulo not in rotulos:
            rotulos.append(rotulo)

    return " · ".join(rotulos) if rotulos else "Nenhuma fonte externa registrada"


def gerar_parecer_docx(
    pergunta: str,
    resposta_md: str,
    metadados_fontes: list[dict],
    perfil_analitico: str,
    feicoes_espaciais: list[dict] | None = None,
    tabelas_extraidas: list[dict] | None = None,
) -> bytes:
    """Gera o Parecer Técnico Geocientífico em ``.docx`` (bytes).

    O documento é montado inteiramente em memória e devolvido como
    ``bytes``, pronto para ``st.download_button``. Levanta
    :class:`RelatorioError` apenas quando ``python-docx`` não está
    instalado; conteúdo vazio não impede a geração.
    """

    if not DOCX_DISPONIVEL:
        raise RelatorioError(
            "O pacote python-docx não está instalado neste ambiente. "
            "Instale com '.venv\\Scripts\\python.exe -m pip install "
            "python-docx' e tente novamente."
        )

    pergunta = _limpar_espacos(pergunta)
    resposta_md = str(resposta_md or "")
    fontes = normalizar_metadados_fontes(metadados_fontes)
    agora = _agora_local()
    titulo = titulo_tecnico(pergunta, perfil_analitico)
    rastreio = _registro_rastreabilidade(pergunta, resposta_md, fontes)
    bases = _resumo_das_bases(fontes)

    documento = _novo_documento(agora, titulo)
    _cabecalho_pagina(documento, perfil_analitico)
    _rodape_pagina(documento, agora, rastreio)
    _cabecalho_institucional(
        documento, titulo, perfil_analitico, bases, rastreio, agora
    )
    _secao_escopo(documento, pergunta)
    _secao_analise(documento, resposta_md, tabelas_extraidas)
    _secao_espacial(documento, feicoes_espaciais)

    referencias = _ordenar_referencias([
        formatar_referencia_abnt(item) for item in fontes
    ])
    _secao_referencias(documento, referencias)

    buffer = io.BytesIO()
    documento.save(buffer)

    return buffer.getvalue()


def _rebaixar_titulos_markdown(texto: str) -> str:
    """Aprofunda dois níveis os títulos do assistente.

    Assim, um ``# Título`` da resposta vira ``### Título`` dentro do item
    2, sem competir com as seções numeradas do próprio parecer. Títulos
    já no nível máximo são mantidos em ``######``.
    """

    linhas = str(texto or "").split("\n")
    dentro_de_codigo = False
    resultado = []

    for linha in linhas:
        if _RE_CODIGO.match(linha):
            dentro_de_codigo = not dentro_de_codigo
            resultado.append(linha)
            continue

        achado = None if dentro_de_codigo else re.match(r"^(#{1,6})\s+(.*)$", linha)

        if achado:
            nivel = min(len(achado.group(1)) + 2, 6)
            resultado.append(f"{'#' * nivel} {achado.group(2)}")
        else:
            resultado.append(linha)

    return "\n".join(resultado)


def _citar_markdown(valor) -> str:
    """Escapa um valor para uso em célula de tabela Markdown."""

    return _limpar_espacos(valor).replace("|", "\\|")


def gerar_parecer_markdown(
    pergunta: str,
    resposta_md: str,
    metadados_fontes: list[dict],
    perfil_analitico: str,
    feicoes_espaciais: list[dict] | None = None,
    tabelas_extraidas: list[dict] | None = None,
) -> str:
    """Gera o Parecer Técnico Geocientífico em Markdown estruturado.

    A estrutura é a mesma do Word: cabeçalho de metadados, seções
    numeradas, síntese espacial condicional, referências ABNT e nota de
    rastreabilidade no rodapé.
    """

    pergunta = _limpar_espacos(pergunta)
    resposta_md = str(resposta_md or "")
    fontes = normalizar_metadados_fontes(metadados_fontes)
    agora = _agora_local()
    titulo = titulo_tecnico(pergunta, perfil_analitico)
    rastreio = _registro_rastreabilidade(pergunta, resposta_md, fontes)
    bases = _resumo_das_bases(fontes)

    linhas = [
        "# PARECER TÉCNICO GEOCIENTÍFICO",
        "",
        f"## {titulo}",
        "",
        "| Campo | Conteúdo |",
        "| --- | --- |",
        f"| Emissão | {_citar_markdown(carimbo_data_hora(agora))} |",
        (
            f"| Perfil analítico | "
            f"{_citar_markdown(_limpar_espacos(perfil_analitico) or 'Não informado')} |"
        ),
        f"| Bases consultadas | {_citar_markdown(bases)} |",
        f"| Registro de rastreabilidade | {rastreio} |",
        "",
        "## 1. Escopo / Consulta Técnica",
        "",
        f"> {pergunta or 'Consulta não informada.'}",
        "",
        (
            "A análise a seguir responde à consulta acima com base nas fontes "
            "listadas no item 4; interpretações e lacunas são indicadas no "
            "próprio texto."
        ),
        "",
        "## 2. Análise Técnica e Interpretação",
        "",
        _rebaixar_titulos_markdown(resposta_md).strip()
        or "Não há conteúdo de análise registrado para esta consulta.",
        "",
    ]

    feicoes = _feicoes_validas(feicoes_espaciais)

    if feicoes:
        linhas.extend([
            "## 3. Síntese Espacial",
            "",
            (
                "Coordenadas no sistema geodésico WGS84 (graus decimais, cinco "
                "casas ≈ 1 m), conforme as camadas e as folhas CIM citadas na "
                "análise."
            ),
            "",
            (
                "| Identificação | Camada / fonte | Latitude | Longitude | "
                "Folha CIM | Limites |"
            ),
            "| --- | --- | ---: | ---: | --- | --- |",
        ])

        for feicao in feicoes[:MAXIMO_LINHAS_TABELA]:
            linhas.append(
                "| "
                + " | ".join([
                    _citar_markdown(feicao.get("nome")) or "Sem identificação",
                    _citar_markdown(feicao.get("camada")) or "Outras fontes",
                    f"{float(feicao['lat']):.5f}",
                    f"{float(feicao['lon']):.5f}",
                    _citar_markdown(feicao.get("folha_cim")),
                    _citar_markdown(feicao.get("limites")),
                ])
                + " |"
            )

        linhas.extend([
            "",
            f"*{len(feicoes)} feição(ões) espacial(is) citada(s) na análise.*",
            "",
        ])

    if tabelas_extraidas:
        referencias_tabelas = []

        for tabela in tabelas_extraidas:
            if not isinstance(tabela, dict):
                continue

            rotulo = _titulo_limpo(tabela.get("titulo")) or "Tabela extraída"
            origem = _limpar_espacos(
                tabela.get("caminho") or tabela.get("origem") or ""
            )
            complemento = f" — {origem}" if origem else ""
            referencias_tabelas.append(f"- {rotulo}{complemento}")

        if referencias_tabelas:
            linhas.extend([
                "### 2.1. Tabelas extraídas dos documentos",
                "",
                *referencias_tabelas,
                "",
                "*As tabelas completas estão no arquivo Word do parecer.*",
                "",
            ])

    referencias = _ordenar_referencias([
        formatar_referencia_abnt(item) for item in fontes
    ])

    linhas.extend([
        "## 4. Referências Consultadas (ABNT NBR 6023)",
        "",
    ])

    if referencias:
        linhas.extend(
            f"{indice}. {referencia}"
            for indice, referencia in enumerate(referencias, start=1)
        )
    else:
        linhas.append(
            "Nenhuma fonte externa foi registrada nesta consulta; a "
            "análise é baseada no conhecimento do modelo e na base "
            "documental local, quando indicada no escopo."
        )

    linhas.extend([
        "",
        "---",
        "",
        (
            f"*Documento gerado pelo {APP_NAME} v{APP_VERSION} · "
            f"{carimbo_data_hora(agora)} · Rastreabilidade {rastreio}*"
        ),
        "",
    ])

    return "\n".join(linhas)
