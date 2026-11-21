"""Conversão de documentos locais em Markdown limpo e estruturado.

Esta camada fica entre o upload e a indexação: **todo** arquivo enviado
(.txt, .md ou .pdf) vira Markdown antes de entrar na busca do RAG. O
resultado é gravado em ``data/cache_md/<arquivo>.md`` e reaproveitado
enquanto o original não mudar (hash SHA-256 + ``mtime``/tamanho).

Para PDFs o fluxo é híbrido e roda 100% em CPU:

1. cada página é extraída com ``pymupdf4llm`` (layout em Markdown);
2. se a página tiver menos de ``MINIMO_CARACTERES_PAGINA`` caracteres
   úteis, ela é renderizada em imagem (~200 DPI) e o texto é lido com
   ``RapidOCR`` (ONNX Runtime embutido, sem Tesseract externo);
3. páginas que passaram pelo OCR ganham o marcador
   ``<!-- Página X (OCR) -->``, preservando a rastreabilidade da página.

Depois da extração o texto passa por uma higienização conservadora:
quebras de linha hifenizadas, espaços redundantes, linhas de número de
página e cabeçalhos/rodapés repetidos são removidos para economizar
tokens sem alterar o conteúdo técnico.

O módulo não depende de Streamlit: a interface apenas informa um
callback de progresso (:data:`Progresso`) e lê o resultado.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import logging
import os
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from config import DATA_DIR

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Caminhos e limites
# ---------------------------------------------------------------------------

# A raiz dos dados vem de ``config``: pasta do projeto em desenvolvimento
# e na distribuição portátil, ``%LOCALAPPDATA%`` no executável instalado.
DIRETORIO_DOCS = DATA_DIR / "docs"
DIRETORIO_CACHE = DATA_DIR / "cache_md"

EXTENSOES_SUPORTADAS = {".txt", ".md", ".pdf"}
EXTENSOES_TEXTO = {".txt", ".md"}

# Muda quando a limpeza/extração muda de comportamento: invalida o cache
# antigo em vez de servir um Markdown gerado por regras antigas.
VERSAO_PARSER = 1

# Renderização das páginas escaneadas: ~200 DPI é o ponto de equilíbrio
# entre qualidade do OCR e custo em um notebook.
DPI_OCR = 200

# Abaixo disso a página é considerada "sem camada de texto" e vai para o
# OCR. O mesmo piso é usado para dizer se o arquivo inteiro é útil.
MINIMO_CARACTERES_PAGINA = 40
MINIMO_CARACTERES_UTEIS = 40

# Linhas curtas repetidas em pelo menos 60% das páginas são tratadas como
# cabeçalho/rodapé do modelo e removidas a partir da segunda ocorrência.
PROPORCAO_LINHAS_REPETIDAS = 0.6
MINIMO_PAGINAS_REPETICAO = 3
TAMANHO_MAXIMO_LINHA_REPETIDA = 120

# Assinatura do tipo de callback de progresso: fração de 0.0 a 1.0 e um
# texto curto para a interface (ex.: "página 4/27 · OCR").
Progresso = Callable[[float, str], None]

PADRAO_MARCADOR_PAGINA = re.compile(
    r"<!--\s*P[áa]gina\s+(\d+)\s*(\(OCR\))?\s*-->",
    re.IGNORECASE,
)

# Linhas que são apenas numeração de página: não têm valor de conteúdo.
PADRAO_NUMERO_PAGINA = re.compile(
    r"^\s*(?:p[áa]gina|page|p\.)\s*\d+\s*(?:(?:de|of|/)\s*\d+)?\s*$",
    re.IGNORECASE,
)
PADRAO_NUMERO_PAGINA_FRACAO = re.compile(r"^\s*\d{1,3}\s*/\s*\d{1,3}\s*$")

# Uma linha que é só um número curto, na borda da página, é numeração.
PADRAO_SO_NUMERO = re.compile(r"^\d{1,4}$")

# Quantas linhas no topo e no rodapé são consideradas "borda" para
# detectar cabeçalhos/rodapés repetidos e numeração de página.
LIMITE_LINHAS_BORDA = 3

# Hífen no fim da linha (inclusive os tipográficos) seguido de minúscula:
# sinal clássico de palavra quebrada pela largura da coluna.
PADRAO_HIFENIZACAO = re.compile(r"(\w)[-\u2010\u2011]\s*\n\s*([a-zà-ÿ])")


class ErroConversao(RuntimeError):
    """Falha ao converter um documento em Markdown.

    ``avaliacao`` é preenchida quando existe uma medição que explica a
    falha (arquivo vazio, sem texto etc.), para que a interface possa
    montar o ``st.warning`` sem inventar números.
    """

    def __init__(self, mensagem: str, avaliacao: dict | None = None):
        super().__init__(mensagem)
        self.avaliacao = avaliacao or {}


class DependenciaAusenteError(ErroConversao):
    """Dependência opcional ausente: o usuário precisa rodar o pip."""


@dataclass
class ResultadoMarkdown:
    """Resultado da conversão de um documento para Markdown."""

    origem: Path
    caminho_md: Path | None
    markdown: str
    paginas: int
    paginas_ocr: int
    caracteres_uteis: int
    do_cache: bool = False
    avisos: list[str] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        """Indica se há texto útil suficiente para indexar."""

        return self.caracteres_uteis >= MINIMO_CARACTERES_UTEIS


# ---------------------------------------------------------------------------
# Utilidades de arquivo
# ---------------------------------------------------------------------------

def garantir_diretorios() -> None:
    """Cria ``data/docs`` e ``data/cache_md`` quando necessário."""

    DIRETORIO_DOCS.mkdir(parents=True, exist_ok=True)
    DIRETORIO_CACHE.mkdir(parents=True, exist_ok=True)


def contar_caracteres_uteis(texto: str) -> int:
    """Conta letras e dígitos (espaços e pontuação não contam)."""

    return sum(1 for caractere in str(texto or "") if caractere.isalnum())


def _sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)

    return digest.hexdigest()


def _assinatura(caminho: Path) -> dict:
    """Hash, tamanho e ``mtime`` do original: a chave do cache em disco."""

    informacao = caminho.stat()

    return {
        "sha256": _sha256_arquivo(caminho),
        "tamanho": informacao.st_size,
        "mtime_ns": informacao.st_mtime_ns,
    }


def _ler_json(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gravar_texto_atomico(caminho: Path, texto: str) -> None:
    """Grava o texto por arquivo temporário e troca atômica.

    Evita que uma queda no meio da gravação deixe um ``.md`` truncado
    sendo servido como cache válido.
    """

    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp-{os.getpid()}")

    try:
        temporario.write_text(texto, encoding="utf-8", newline="\n")
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)


def _gravar_json_atomico(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp-{os.getpid()}")

    try:
        temporario.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cache em disco: data/cache_md/<arquivo>.md (+ .json ao lado)
# ---------------------------------------------------------------------------

def caminho_markdown(caminho_origem: Path | str) -> Path:
    """Devolve o ``.md`` correspondente a um original em ``data/docs``.

    Arquivos já em Markdown usam o próprio arquivo (não há cópia: o
    original **é** o Markdown). Para os demais, o nome é o "stem" do
    original (``relatorio.pdf`` -> ``relatorio.md``). Se o mesmo nome já
    estiver associado a outro original, o nome completo entra no cache
    (``relatorio.txt.md``) para não misturar dois documentos.
    """

    caminho_origem = Path(caminho_origem)

    if caminho_origem.suffix.lower() == ".md":
        return caminho_origem

    DIRETORIO_CACHE.mkdir(parents=True, exist_ok=True)
    candidato = DIRETORIO_CACHE / f"{caminho_origem.stem}.md"
    metadados = _ler_json(_caminho_meta(candidato))

    origem_esperada = str(caminho_origem.resolve())

    if metadados is not None and metadados.get("origem") != origem_esperada:
        candidato = DIRETORIO_CACHE / f"{caminho_origem.name}.md"
    elif metadados is None and candidato.exists():
        # Cache de uma execução anterior (ou de outro documento com o
        # mesmo stem): usa o nome completo para não sobrescrever.
        candidato = DIRETORIO_CACHE / f"{caminho_origem.name}.md"

    return candidato


def _caminho_meta(caminho_md: Path) -> Path:
    return caminho_md.with_suffix(".json")


def cache_atualizado(
    caminho_origem: Path | str,
    *,
    assinatura: dict | None = None,
) -> bool:
    """Diz se o ``.md`` em cache corresponde ao original atual.

    A comparação usa o hash do conteúdo **e** o ``mtime``/tamanho: um
    arquivo regravado com o mesmo conteúdo (caso comum ao baixar o mesmo
    PDF de novo) não força nova conversão, e um arquivo alterado sem
    mudança de tamanho ainda é detectado pelo hash.
    """

    caminho_origem = Path(caminho_origem)

    if caminho_origem.suffix.lower() == ".md":
        return caminho_origem.is_file()

    caminho_md = caminho_markdown(caminho_origem)
    metadados = _ler_json(_caminho_meta(caminho_md))

    if metadados is None or not caminho_md.is_file():
        return False

    if metadados.get("versao") != VERSAO_PARSER:
        return False

    assinatura = assinatura or _assinatura(caminho_origem)

    return (
        metadados.get("sha256") == assinatura["sha256"]
        and metadados.get("mtime_ns") == assinatura["mtime_ns"]
        and metadados.get("tamanho") == assinatura["tamanho"]
    )


def remover_cache(caminho_origem: Path | str) -> None:
    """Apaga o ``.md`` e os metadados de cache de um original."""

    caminho_md = caminho_markdown(caminho_origem)

    if caminho_origem.suffix.lower() == ".md":
        return

    caminho_md.unlink(missing_ok=True)
    _caminho_meta(caminho_md).unlink(missing_ok=True)


def ler_markdown(
    caminho_origem: Path | str,
    *,
    assinatura: dict | None = None,
) -> str | None:
    """Lê o Markdown em cache, ou ``None`` quando ele não está atualizado."""

    caminho_origem = Path(caminho_origem)

    if not cache_atualizado(caminho_origem, assinatura=assinatura):
        return None

    caminho_md = caminho_markdown(caminho_origem)

    try:
        return caminho_md.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Carregamento tardio das dependências (o app abre mesmo sem elas)
# ---------------------------------------------------------------------------

def _importar_pymupdf():
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError as erro:
            raise DependenciaAusenteError(
                "A conversão de PDF exige o PyMuPDF. "
                "Execute: pip install -r requirements.txt"
            ) from erro

    return pymupdf


def _importar_pymupdf4llm():
    try:
        # O pymupdf4llm 0.3 imprime um aviso sobre o pacote opcional
        # ``pymupdf_layout`` ao ser importado; ele não é necessário aqui e
        # poluiria o console do Streamlit.
        with contextlib.redirect_stdout(io.StringIO()):
            import pymupdf4llm
    except ImportError:
        return None

    return pymupdf4llm


_MOTOR_OCR = None
_ERRO_MOTOR_OCR: str | None = None
_LOCK_OCR = threading.Lock()


def _carregar_classe_ocr():
    """Importa a classe ``RapidOCR`` sem instanciar o motor.

    Devolve ``None`` quando nenhum dos pacotes do RapidOCR está
    disponível **ou** quando o import falha por qualquer outro motivo.
    Essa tolerância é essencial no executável empacotado: o RapidOCR
    resolve os próprios ``.yaml`` e modelos ONNX dentro de ``_MEI...`` e,
    se os arquivos de dados não foram empacotados, o Omegaconf levanta
    ``FileNotFoundError``/``OSError`` ao ler a configuração. Capturar
    apenas ``ImportError`` deixaria essa exceção subir até o Streamlit e
    derrubar a interface inteira. O OCR é opcional: registramos o aviso
    e o PDF continua sendo extraído pela camada de texto.
    """

    for nome_modulo in ("rapidocr_onnxruntime", "rapidocr"):
        try:
            modulo = importlib.import_module(nome_modulo)
        except Exception as erro:  # noqa: BLE001 - OCR nunca derruba a UI
            LOGGER.debug(
                "RapidOCR indisponível via %s (%s: %s)",
                nome_modulo,
                type(erro).__name__,
                erro,
            )
            continue

        classe_ocr = getattr(modulo, "RapidOCR", None)

        if classe_ocr is not None:
            return classe_ocr

        LOGGER.debug(
            "O pacote %s não expõe a classe RapidOCR", nome_modulo
        )

    LOGGER.warning(
        "RapidOCR não pôde ser carregado; o OCR de páginas escaneadas "
        "fica desativado. Instale rapidocr (ou rapidocr_onnxruntime) ou "
        "recompile o executável com --collect-data rapidocr."
    )
    return None


def obter_motor_ocr():
    """Devolve o motor de OCR (carregado uma única vez por processo)."""

    global _MOTOR_OCR, _ERRO_MOTOR_OCR

    if _MOTOR_OCR is not None:
        return _MOTOR_OCR

    with _LOCK_OCR:
        if _MOTOR_OCR is not None:
            return _MOTOR_OCR

        if _ERRO_MOTOR_OCR is not None:
            raise DependenciaAusenteError(_ERRO_MOTOR_OCR)

        classe = _carregar_classe_ocr()

        if classe is None:
            _ERRO_MOTOR_OCR = (
                "O OCR de páginas escaneadas exige o RapidOCR. "
                "Execute: pip install -r requirements.txt"
            )
            raise DependenciaAusenteError(_ERRO_MOTOR_OCR)

        # O RapidOCR registra cada modelo carregado em nível INFO. Isso
        # polui o console do Streamlit sem ajudar o usuário final. O
        # nível é passado na criação (senão o construtor o redefine) e
        # reforçado abaixo para as versões antigas do pacote.
        try:
            try:
                _MOTOR_OCR = classe(params={"Global.log_level": "error"})
            except TypeError:
                _MOTOR_OCR = classe()
        except Exception as erro:  # pragma: no cover - depende do ambiente
            _ERRO_MOTOR_OCR = (
                "Não foi possível iniciar o RapidOCR "
                f"({type(erro).__name__}: {erro}). "
                "Execute: pip install -r requirements.txt"
            )
            raise DependenciaAusenteError(_ERRO_MOTOR_OCR) from erro

        for nome_logger in ("RapidOCR", "rapidocr"):
            logger_ocr = logging.getLogger(nome_logger)
            logger_ocr.setLevel(logging.ERROR)

            for manipulador in logger_ocr.handlers:
                manipulador.setLevel(logging.ERROR)

    return _MOTOR_OCR


def ocr_disponivel() -> bool:
    """Verifica, sem carregar modelos, se o RapidOCR pode ser usado.

    Nunca lança exceção: qualquer falha ao importar o pacote (inclusive
    dados ``.yaml``/``.onnx`` ausentes no executável empacotado) vira
    ``False``, mantendo a interface do Streamlit de pé.
    """

    try:
        return _carregar_classe_ocr() is not None
    except Exception as erro:  # noqa: BLE001 - OCR nunca derruba a UI
        LOGGER.debug(
            "Falha inesperada ao verificar o RapidOCR (%s: %s)",
            type(erro).__name__,
            erro,
        )
        return False


def pymupdf_disponivel() -> bool:
    """Verifica, sem abrir arquivos, se o PyMuPDF está instalado."""

    try:
        _importar_pymupdf()
        return True
    except ErroConversao:
        return False


# ---------------------------------------------------------------------------
# OCR de uma página
# ---------------------------------------------------------------------------

def _textos_do_ocr(saida) -> list[str]:
    """Normaliza a saída das duas gerações da API do RapidOCR.

    - ``rapidocr`` >= 3 devolve um objeto com ``.txts``;
    - ``rapidocr-onnxruntime`` 1.x devolve ``(resultado, tempos)``, com
      ``resultado`` sendo ``[[caixa, texto, confiança], ...]``.
    """

    if (
        isinstance(saida, tuple)
        and len(saida) == 2
        and not hasattr(saida[0], "txts")
    ):
        saida = saida[0]

    textos = getattr(saida, "txts", None)

    if textos is not None:
        return [str(item).strip() for item in textos if str(item or "").strip()]

    if isinstance(saida, (list, tuple)):
        linhas = []

        for item in saida:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                valor = item[1]
                if isinstance(valor, str) and valor.strip():
                    linhas.append(valor.strip())

        return linhas

    return []


def ocr_pagina(pagina) -> str:
    """Renderiza a página em imagem (~200 DPI) e lê o texto com OCR."""

    motor = obter_motor_ocr()

    imagem = pagina.get_pixmap(dpi=DPI_OCR)

    if not imagem.width or not imagem.height:
        return ""

    saida = motor(imagem.tobytes("png"))

    return "\n".join(_textos_do_ocr(saida))


# ---------------------------------------------------------------------------
# Extração e higienização
# ---------------------------------------------------------------------------

def _decodificar(dados: bytes) -> str:
    """Decodifica texto tolerando arquivos antigos (Windows/cp1252)."""

    for codificacao in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue

    return dados.decode("utf-8", errors="replace")


def deshifenizar(texto: str) -> str:
    """Junta palavras quebradas por hífen no fim da linha."""

    return PADRAO_HIFENIZACAO.sub(r"\1\2", texto)


def _limpar_linha(linha: str) -> str:
    """Remove espaços redundantes preservando recuo de listas/citações."""

    linha = linha.replace("\t", " ").replace("\u00a0", " ")
    linha = linha.replace("\u200b", "").rstrip()

    if not linha.strip():
        return ""

    recuo = len(linha) - len(linha.lstrip(" "))

    if recuo > 4:
        recuo = 0

    prefixo = linha[:recuo]
    corpo = re.sub(r" {2,}", " ", linha[recuo:]).strip()

    return f"{prefixo}{corpo}" if corpo else ""


def _chave_repeticao(linha: str) -> str:
    """Chave de comparação para cabeçalhos, tolerante ao número de página.

    Normaliza apenas números que são claramente numeração de página
    ("Página 3", "RELATÓRIO | 12"), nunca números que fazem parte do
    texto ("Seção 1" continua diferente de "Seção 2").
    """

    chave = unicodedata.normalize("NFKC", linha).strip().lower()
    chave = re.sub(r"\s+", " ", chave)
    chave = re.sub(
        r"\b(?:p[áa]gina|page|p\.)\s*\d+",
        "página #",
        chave,
    )
    chave = re.sub(r"\s*[-–—|/.]\s*\d{1,4}\s*$", " #", chave)

    return chave[:TAMANHO_MAXIMO_LINHA_REPETIDA]


def _indices_bordas(
    linhas: Sequence[str],
    janela: int = LIMITE_LINHAS_BORDA,
) -> list[int]:
    """Índices das linhas no topo/rodapé da página (onde ficam cabeçalhos)."""

    indices = [indice for indice, linha in enumerate(linhas) if linha.strip()]

    if not indices:
        return []

    if len(indices) <= janela * 2:
        # Página curta: só a primeira e a última linha são "borda", para
        # não tratar o corpo inteiro como cabeçalho.
        return indices if len(indices) <= 2 else indices[:1] + indices[-1:]

    return indices[:janela] + indices[-janela:]


def _remover_numeracao_de_pagina(
    paginas: Sequence[Sequence[str]],
) -> list[list[str]]:
    """Remove números de página isolados no topo ou no rodapé.

    Só é aplicado a documentos com mais de uma página e apenas nas
    bordas: um número solto no meio do texto pode ser dado técnico.
    """

    if len(paginas) < 2:
        return [list(pagina) for pagina in paginas]

    resultado = []

    for linhas in paginas:
        linhas = list(linhas)

        for indice in _indices_bordas(linhas):
            if PADRAO_SO_NUMERO.match(linhas[indice].strip()):
                linhas[indice] = ""

        resultado.append(linhas)

    return resultado


def _linha_eh_numeracao(linha: str) -> bool:
    return bool(
        PADRAO_NUMERO_PAGINA.match(linha)
        or PADRAO_NUMERO_PAGINA_FRACAO.match(linha)
    )


def _pagina_em_linhas(texto: str) -> list[str]:
    """Higieniza uma página e devolve suas linhas não vazias.

    O conteúdo entre cercas de código (```) é preservado literalmente,
    porque ali espaços fazem parte do significado.
    """

    linhas = []
    dentro_de_codigo = False

    for linha_bruta in deshifenizar(str(texto or "")).split("\n"):
        if linha_bruta.strip().startswith("```"):
            dentro_de_codigo = not dentro_de_codigo
            linhas.append(linha_bruta.rstrip())
            continue

        if dentro_de_codigo:
            linhas.append(linha_bruta.rstrip())
            continue

        linha = _limpar_linha(linha_bruta)

        if _linha_eh_numeracao(linha):
            continue

        linhas.append(linha)

    return linhas


def _remover_cabecalhos_repetidos(
    paginas: Sequence[Sequence[str]],
) -> tuple[list[list[str]], int]:
    """Remove cabeçalhos/rodapés repetidos, mantendo a 1ª ocorrência."""

    if len(paginas) < MINIMO_PAGINAS_REPETICAO:
        return [list(pagina) for pagina in paginas], 0

    contagem = Counter()

    for linhas in paginas:
        chaves = {
            _chave_repeticao(linhas[indice])
            for indice in _indices_bordas(linhas)
        }
        chaves.discard("")
        contagem.update(chaves)

    limite = max(
        MINIMO_PAGINAS_REPETICAO,
        int(len(paginas) * PROPORCAO_LINHAS_REPETIDAS + 0.999),
    )
    repetidas = {
        chave
        for chave, ocorrencias in contagem.items()
        if ocorrencias >= limite
    }

    if not repetidas:
        return [list(pagina) for pagina in paginas], 0

    resultado = []
    ja_mantidas: set[str] = set()
    removidas = 0

    for linhas in paginas:
        bordas = set(_indices_bordas(linhas))
        nova = []

        for indice, linha in enumerate(linhas):
            chave = _chave_repeticao(linha)

            if indice in bordas and chave in repetidas:
                if chave in ja_mantidas:
                    removidas += 1
                    continue

                ja_mantidas.add(chave)

            nova.append(linha)

        resultado.append(nova)

    return resultado, removidas


def _colapsar_linhas_em_branco(linhas: Sequence[str]) -> list[str]:
    """Mantém no máximo uma linha em branco entre blocos."""

    saida = []
    vazias = 0

    for linha in linhas:
        if linha.strip():
            vazias = 0
            saida.append(linha)
            continue

        vazias += 1

        if vazias == 1:
            saida.append("")

    while saida and saida[-1] == "":
        saida.pop()

    return saida


def _titulo_do_arquivo(caminho: Path) -> str:
    """Título legível a partir do nome do arquivo."""

    titulo = re.sub(r"[_\-]+", " ", caminho.stem).strip()

    return titulo or caminho.stem or "Documento"


def _finalizar_markdown(texto: str) -> str:
    """Ajustes finais válidos para qualquer origem (texto ou PDF)."""

    texto = deshifenizar(texto)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = "\n".join(linha.rstrip() for linha in texto.split("\n"))
    texto = texto.strip()

    return f"{texto}\n" if texto else ""


def _montar_markdown_paginas(
    titulo: str,
    paginas: Sequence[tuple[list[str], bool]],
) -> str:
    """Monta o Markdown final com os marcadores de página."""

    partes = [f"# {titulo}"]

    for numero, (linhas, usou_ocr) in enumerate(paginas, start=1):
        marcador = (
            f"<!-- Página {numero} (OCR) -->"
            if usou_ocr
            else f"<!-- Página {numero} -->"
        )
        corpo = "\n".join(_colapsar_linhas_em_branco(linhas)).strip()

        partes.append(f"{marcador}\n\n{corpo}" if corpo else marcador)

    return _finalizar_markdown("\n\n".join(partes))


def higienizar_markdown(texto: str, *, titulo: str | None = None) -> str:
    """Higieniza texto livre (``.txt``/``.md``) para Markdown econômico."""

    linhas = _pagina_em_linhas(texto)
    corpo = "\n".join(_colapsar_linhas_em_branco(linhas)).strip()

    if not corpo:
        return ""

    if titulo and not re.match(r"^\s*#\s+", corpo):
        corpo = f"# {titulo}\n\n{corpo}"

    return _finalizar_markdown(corpo)


# ---------------------------------------------------------------------------
# PDF página a página (texto nativo + OCR)
# ---------------------------------------------------------------------------

def _extrair_pagina_pdf(
    documento,
    pymupdf4llm,
    indice: int,
) -> tuple[str, bool, list[str]]:
    """Extrai uma página; devolve ``(texto, usou_ocr, avisos)``."""

    avisos = []
    texto = ""

    if pymupdf4llm is not None:
        try:
            partes = pymupdf4llm.to_markdown(
                documento,
                pages=[indice],
                page_chunks=True,
                show_progress=False,
                ignore_images=True,
                ignore_graphics=True,
            )
            if partes:
                texto = partes[0].get("text") or ""
        except Exception as erro:
            avisos.append(
                "pymupdf4llm falhou nesta página "
                f"({type(erro).__name__}); usando o texto do PyMuPDF."
            )
            texto = ""
    else:
        avisos.append(
            "pymupdf4llm indisponível; a página foi lida só com o texto "
            "nativo do PyMuPDF."
        )

    if contar_caracteres_uteis(texto) < MINIMO_CARACTERES_PAGINA:
        try:
            nativo = documento[indice].get_text("text") or ""
        except Exception:
            nativo = ""

        if contar_caracteres_uteis(nativo) > contar_caracteres_uteis(texto):
            texto = nativo

    if contar_caracteres_uteis(texto) >= MINIMO_CARACTERES_PAGINA:
        return texto, False, avisos

    # Página sem camada de texto (varredura): renderiza e aplica OCR.
    try:
        texto_ocr = ocr_pagina(documento[indice])
    except ErroConversao:
        raise
    except Exception as erro:
        avisos.append(
            "O OCR falhou nesta página "
            f"({type(erro).__name__}); a página ficou sem texto."
        )
        return texto, False, avisos

    if contar_caracteres_uteis(texto_ocr) > contar_caracteres_uteis(texto):
        return texto_ocr, True, avisos

    return texto, False, avisos


def _converter_pdf(
    caminho: Path,
    progresso: Progresso | None,
) -> tuple[str, int, int, list[str]]:
    """Converte o PDF inteiro; devolve ``(markdown, páginas, OCR, avisos)``."""

    pymupdf = _importar_pymupdf()
    pymupdf4llm = _importar_pymupdf4llm()

    try:
        documento = pymupdf.open(caminho)
    except Exception as erro:
        raise ErroConversao(
            f"O PDF {caminho.name} não pôde ser aberto "
            f"({type(erro).__name__})."
        ) from erro

    try:
        if getattr(documento, "needs_pass", False):
            raise ErroConversao(
                f"O PDF {caminho.name} é protegido por senha."
            )

        total = documento.page_count

        if total <= 0:
            return "", 0, 0, ["O PDF não possui páginas."]

        paginas = []
        avisos: list[str] = []
        total_ocr = 0

        for indice in range(total):
            _reportar_progresso(
                progresso,
                (indice + 1) / total,
                f"página {indice + 1}/{total}",
            )

            texto, usou_ocr, avisos_pagina = _extrair_pagina_pdf(
                documento,
                pymupdf4llm,
                indice,
            )

            if usou_ocr:
                total_ocr += 1
                _reportar_progresso(
                    progresso,
                    (indice + 1) / total,
                    f"página {indice + 1}/{total} · OCR",
                )

            for aviso in avisos_pagina:
                if aviso not in avisos:
                    avisos.append(aviso)

            paginas.append((_pagina_em_linhas(texto), usou_ocr))

    finally:
        documento.close()

    linhas_paginas = [linhas for linhas, _ in paginas]
    marcas_ocr = [usou for _, usou in paginas]

    linhas_paginas = _remover_numeracao_de_pagina(linhas_paginas)
    linhas_paginas, removidas = _remover_cabecalhos_repetidos(linhas_paginas)

    if removidas:
        avisos.append(
            f"{removidas} linha(s) de cabeçalho/rodapé repetido(s) "
            "foram removidas."
        )

    markdown = _montar_markdown_paginas(
        _titulo_do_arquivo(caminho),
        list(zip(linhas_paginas, marcas_ocr)),
    )

    return markdown, total, total_ocr, avisos


def _reportar_progresso(
    progresso: Progresso | None,
    fracao: float,
    texto: str,
) -> None:
    """Chama o callback de progresso sem deixar a UI derrubar a conversão."""

    if progresso is None:
        return

    try:
        progresso(max(0.0, min(1.0, fracao)), texto)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def _caracteres_do_conteudo(markdown: str, titulo: str) -> int:
    """Conta caracteres úteis **sem** o título sintético do documento.

    O título é gerado a partir do nome do arquivo. Contá-lo faria um PDF
    totalmente em branco parecer "com texto" só porque o nome do arquivo
    é longo — e ele acabaria marcado como indexado.
    """

    prefixo = f"# {titulo}\n"

    if markdown.startswith(prefixo):
        markdown = markdown[len(prefixo):]

    # Os marcadores ``<!-- Página N -->`` são andaimes de citação, não
    # conteúdo: sem removê-los, um PDF de várias páginas em branco
    # somaria caracteres suficientes para parecer "com texto".
    markdown = PADRAO_MARCADOR_PAGINA.sub(" ", markdown)

    return contar_caracteres_uteis(markdown)


def _converter_texto(caminho: Path) -> tuple[str, int, int, list[str]]:
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ErroConversao(
            f"O arquivo {caminho.name} não pôde ser lido.",
        ) from erro

    texto = higienizar_markdown(
        _decodificar(dados),
        titulo=_titulo_do_arquivo(caminho),
    )

    return texto, 1, 0, []


def converter_arquivo(
    caminho_origem: Path | str,
    *,
    forcar: bool = False,
    progresso: Progresso | None = None,
) -> ResultadoMarkdown:
    """Converte um documento em Markdown, reaproveitando o cache em disco.

    ``forcar=True`` ignora o cache e reconverte (útil depois de mudar
    regras de limpeza). ``progresso`` recebe ``(fração, texto)`` — para
    PDFs, a cada página; para arquivos de texto, uma única chamada.
    """

    caminho_origem = Path(caminho_origem)

    if not caminho_origem.is_file():
        raise ErroConversao(f"O arquivo {caminho_origem.name} não existe.")

    sufixo = caminho_origem.suffix.lower()

    if sufixo not in EXTENSOES_SUPORTADAS:
        raise ErroConversao(
            "Formato não suportado para conversão. "
            "Envie arquivos .txt, .md ou .pdf."
        )

    # Markdown já é o formato final: o próprio original é a fonte, sem
    # cópia de cache (e sem reescrever o arquivo do usuário).
    if sufixo == ".md":
        markdown, paginas, paginas_ocr, avisos = _converter_texto(caminho_origem)
        titulo = _titulo_do_arquivo(caminho_origem)

        return ResultadoMarkdown(
            origem=caminho_origem,
            caminho_md=caminho_origem,
            markdown=markdown,
            paginas=paginas,
            paginas_ocr=paginas_ocr,
            caracteres_uteis=_caracteres_do_conteudo(markdown, titulo),
            do_cache=False,
            avisos=avisos,
        )

    assinatura = _assinatura(caminho_origem)

    if not forcar and cache_atualizado(caminho_origem, assinatura=assinatura):
        resultado = _carregar_do_cache(caminho_origem)

        if resultado is not None:
            return resultado

    _reportar_progresso(progresso, 0.0, "preparando")

    if sufixo == ".pdf":
        markdown, paginas, paginas_ocr, avisos = _converter_pdf(
            caminho_origem,
            progresso,
        )
    else:
        markdown, paginas, paginas_ocr, avisos = _converter_texto(caminho_origem)
        _reportar_progresso(progresso, 1.0, "texto convertido")

    caracteres = _caracteres_do_conteudo(
        markdown,
        _titulo_do_arquivo(caminho_origem),
    )
    caminho_md = caminho_markdown(caminho_origem)

    # O cache é gravado mesmo quando o resultado é inválido: assim a
    # listagem da barra lateral não repete OCR de um arquivo já avaliado.
    _gravar_texto_atomico(caminho_md, markdown)
    _gravar_json_atomico(
        _caminho_meta(caminho_md),
        {
            "versao": VERSAO_PARSER,
            "origem": str(caminho_origem.resolve()),
            "sha256": assinatura["sha256"],
            "mtime_ns": assinatura["mtime_ns"],
            "tamanho": assinatura["tamanho"],
            "paginas": paginas,
            "paginas_ocr": paginas_ocr,
            "caracteres_uteis": caracteres,
            "avisos": avisos,
            "gerado_em": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ResultadoMarkdown(
        origem=caminho_origem,
        caminho_md=caminho_md,
        markdown=markdown,
        paginas=paginas,
        paginas_ocr=paginas_ocr,
        caracteres_uteis=caracteres,
        do_cache=False,
        avisos=avisos,
    )


def _carregar_do_cache(
    caminho_origem: Path,
) -> ResultadoMarkdown | None:
    caminho_md = caminho_markdown(caminho_origem)

    try:
        markdown = caminho_md.read_text(encoding="utf-8")
    except OSError:
        return None

    metadados = _ler_json(_caminho_meta(caminho_md)) or {}

    return ResultadoMarkdown(
        origem=caminho_origem,
        caminho_md=caminho_md,
        markdown=markdown,
        paginas=int(metadados.get("paginas") or 0),
        paginas_ocr=int(metadados.get("paginas_ocr") or 0),
        caracteres_uteis=int(
            metadados.get("caracteres_uteis")
            or contar_caracteres_uteis(markdown)
        ),
        do_cache=True,
        avisos=list(metadados.get("avisos") or []),
    )


def extrair_blocos_markdown(texto: str) -> list[tuple[str, int | None]]:
    """Divide o Markdown nos blocos de página, para citação na busca.

    Devolve pares ``(texto, número da página)``. O cabeçalho do
    documento (antes do primeiro marcador) fica como bloco sem página.
    Texto sem marcadores vira um único bloco com ``None``.
    """

    texto = str(texto or "")
    marcadores = list(PADRAO_MARCADOR_PAGINA.finditer(texto))

    if not marcadores:
        return [(texto, None)]

    blocos: list[tuple[str, int | None]] = []
    inicial = texto[: marcadores[0].start()].strip()

    if inicial:
        blocos.append((inicial, None))

    for posicao, marcador in enumerate(marcadores):
        fim = (
            marcadores[posicao + 1].start()
            if posicao + 1 < len(marcadores)
            else len(texto)
        )
        conteudo = texto[marcador.end():fim].strip()

        if conteudo:
            blocos.append((conteudo, int(marcador.group(1))))

    return blocos or [(texto, None)]
