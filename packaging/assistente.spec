# -*- mode: python ; coding: utf-8 -*-
"""Especificacao do PyInstaller do NexusGeo IA.

Gera o pacote no modo ``--onedir`` em ``dist/NexusGeoIA/``:

- ``dist/NexusGeoIA/NexusGeoIA.exe`` (alvo: ``launcher_desktop.py``), o
  carregador enxuto que nao extrai ``_MEI...`` em tempo de execucao;
- ``dist/NexusGeoIA/_internal/``, com ``app.py``, ``.streamlit``,
  ``prompts``, as bibliotecas e os demais dados. No PyInstaller 6 o
  ``sys._MEIPASS`` do modo ``--onedir`` aponta justamente para essa
  pasta ``_internal``, entao o launcher e o ``config.py`` continuam
  resolvendo os recursos por caminho sem nenhuma mudanca.
- Essa montagem elimina o erro ``Could not create temporary directory!``
  do bootloader ``--onefile`` (que dependia de criar ``_MEI`` em
  ``%TEMP%``), abre mais rapido porque nao descompacta o bundle a cada
  inicializacao e reduz falsos positivos de antivirus;
- ``streamlit`` completo (``collect_all``) e os metadados que ele le em
  tempo de execucao (``copy_metadata``);
- os dados do RapidOCR (``.yaml`` de configuracao e modelos ONNX), que
  ele resolve por caminho dentro do pacote;
- as bibliotecas opcionais de exportacao/leitura de documentos
  (``python-docx``, ``openpyxl``, ``pypdf`` e ``PyMuPDF``), com
  ``hiddenimports``, ``collect_data_files`` e ``copy_metadata`` em
  ``try/except`` para nao falhar quando alguma nao esta instalada;
- os pacotes internos ``core``, ``services``, ``database`` e ``utils``.

O instalador do Inno Setup (``packaging/installer.iss``) empacota
recursivamente a pasta ``dist/NexusGeoIA/`` inteira (``.exe`` +
``_internal/``) e o build portatil copia o mesmo conteudo para o
staging do ``.zip``.
"""

import importlib.util
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# ``SPECPATH`` e definido pelo PyInstaller e aponta para packaging/.
RAIZ = Path(SPECPATH).resolve().parent

datas = []
binaries = []
hiddenimports = []

# ---------------------------------------------------------------------------
# Streamlit e dependencias de runtime que ele importa dinamicamente
# ---------------------------------------------------------------------------

for pacote in ("streamlit", "altair"):
    dados_pacote, binarios_pacote, ocultos_pacote = collect_all(pacote)
    datas += dados_pacote
    binaries += binarios_pacote
    hiddenimports += ocultos_pacote

# ``copy_metadata`` e obrigatorio: no import o Streamlit consulta a
# versao do proprio pacote com ``importlib.metadata.version("streamlit")``
# e, sem o diretorio ``streamlit-*.dist-info`` dentro de ``_internal``, o
# executavel congelado aborta com ``PackageNotFoundError``. Como o
# Streamlit e dependencia dura do aplicativo, a coleta dele nao fica em
# try/except: se os metadados nao existirem no ambiente do build, o build
# falha aqui em vez de gerar um .exe quebrado.
datas += copy_metadata("streamlit")

# Metadados das distribuicoes que o Streamlit e o pandas consultam por
# ``importlib.metadata.version(...)`` em tempo de execucao. As opcionais
# seguem tolerantes a ausencia para nao quebrar ambientes minimos.
PACOTES_METADADOS = (
    "streamlit",
    "altair",
    "pillow",
    "pydeck",
    "click",
    "packaging",
    "pandas",
    "pyarrow",
    "plotly",
)

for pacote in PACOTES_METADADOS:
    if pacote == "streamlit":
        continue

    try:
        datas += copy_metadata(pacote)
    except PackageNotFoundError:
        # Distribuicao opcional ausente neste ambiente: o Streamlit
        # funciona sem ela e o PyInstaller nao precisa falhar por isso.
        continue

# ---------------------------------------------------------------------------
# RapidOCR (OCR opcional dos PDFs escaneados)
# ---------------------------------------------------------------------------
#
# O RapidOCR guarda ``config.yaml``, ``default_models.yaml`` e os modelos
# ONNX dentro da propria pasta do pacote e os resolve por caminho em tempo
# de execucao. No pacote --onedir esses arquivos precisam ir para
# ``_internal``; sem eles o Omegaconf levanta FileNotFoundError ao ler a
# configuracao e o app cai. Como o import e tardio e dinamico
# (``importlib.import_module`` em ``services.document_parser``), os
# submodulos tambem entram explicitamente.
#
# Equivale a ``--collect-data rapidocr`` na linha de comando. A flag nao e
# usada em ``build_installer.ps1`` porque o PyInstaller proibe opcoes de
# "makespec" quando um ``.spec`` e fornecido.

try:
    datas += collect_data_files("rapidocr")
    hiddenimports += collect_submodules("rapidocr")
except Exception:
    # Pacote opcional ausente: no Python < 3.13 o nome instalado e o
    # legado rapidocr_onnxruntime.
    pass

try:
    datas += collect_data_files("rapidocr_onnxruntime")
    hiddenimports += collect_submodules("rapidocr_onnxruntime")
except Exception:
    # Pacote opcional ausente: no Python >= 3.13 o nome instalado e
    # rapidocr.
    pass

# ---------------------------------------------------------------------------
# Bibliotecas opcionais de exportacao e leitura de documentos
# ---------------------------------------------------------------------------
#
# As tres bibliotecas abaixo sao importadas de forma tardia (dentro de
# funcoes) ou por nome, e por isso o PyInstaller pode nao descobri-las:
#
# - ``services/report_generator.py`` monta o Parecer Tecnico em Word com
#   ``from docx import ...`` dentro de ``_importar_docx()``. Alem do
#   codigo, o ``python-docx`` carrega ``docx/templates/default.docx`` do
#   disco quando ``Document()`` e chamado sem argumento; sem esse modelo
#   em ``_MEI...`` a geracao do Word falha em tempo de execucao.
# - ``services/table_extractor.py`` exporta Excel com
#   ``pandas.ExcelWriter(engine="openpyxl")``; o pandas resolve o motor
#   por nome com ``importlib`` e ``openpyxl.styles`` e importado dentro da
#   funcao de estilos.
# - ``services/document_parser.py`` le PDF com ``pymupdf`` e cai para o
#   alias legado ``fitz``.
#
# NAO ha dependencia dura: cada pacote entra em try/except e a ausencia
# apenas remove aquele recurso do bundle (o aplicativo continua abrindo).
# Sem estes blocos o build passa, mas o .exe quebra silenciosamente so na
# hora de exportar o parecer, o Excel ou ler um PDF.

# Distribuicoes (nomes do PyPI) com dados ou metadados proprios.
#
# A primeira coluna e o nome IMPORTADO (o que ``collect_data_files``
# aceita); a segunda e o nome da DISTRIBUICAO no PyPI (o que
# ``copy_metadata`` aceita). Os dois nao coincidem em python-docx/PyMuPDF:
# usar o nome da distribuicao em ``collect_data_files`` faz o PyInstaller
# apenas avisar "not a package" e seguir sem os dados - foi assim que o
# ``docx/templates/default.docx`` deixou de entrar no bundle.
PACOTES_DOCUMENTO = (
    ("docx", "python-docx"),
    ("openpyxl", "openpyxl"),
    ("pypdf", "pypdf"),
    ("pymupdf", "PyMuPDF"),
)

# Dados que nao sao usados em runtime e so aumentariam o executavel.
EXCLUSOES_DADOS = {
    # Cabecalhos C e fontes do MuPDF: o runtime usa apenas a DLL.
    "pymupdf": ["mupdf-devel/**"],
}

for modulo, distribuicao in PACOTES_DOCUMENTO:
    try:
        datas += collect_data_files(
            modulo,
            excludes=EXCLUSOES_DADOS.get(modulo, []),
        )
    except Exception:
        # Modulo ausente no ambiente do PyInstaller: o recurso
        # correspondente simplesmente nao entra no bundle.
        pass

    try:
        datas += copy_metadata(distribuicao)
    except Exception:
        pass

# Modulos internos que o modulegraph nao garante em import tardio/por
# nome. A checagem usa ``find_spec`` para nao gerar "hidden import not
# found" quando a biblioteca nao esta instalada.
MODULOS_DOCUMENTO = (
    # python-docx (servicos/report_generator.py)
    "docx",
    "docx.enum",
    "docx.enum.table",
    "docx.enum.text",
    "docx.opc",
    "docx.opc.constants",
    "docx.oxml",
    "docx.oxml.ns",
    "docx.shared",
    # openpyxl (servicos/table_extractor.py e motor do pandas)
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.workbook",
    "pandas.io.excel._openpyxl",
    # Leitura de PDF (servicos/document_parser.py)
    "pypdf",
    "pymupdf",
    "fitz",
)


def _modulo_instalado(nome):
    """Diz se ``nome`` pode ser importado no Python que roda o build."""

    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, AttributeError, ValueError):
        return False


for modulo in MODULOS_DOCUMENTO:
    if _modulo_instalado(modulo) and modulo not in hiddenimports:
        hiddenimports.append(modulo)

# ---------------------------------------------------------------------------
# Pacotes internos do projeto
# ---------------------------------------------------------------------------

for pacote in ("core", "services", "database", "utils"):
    hiddenimports += collect_submodules(pacote)

# Lista explícita: os pacotes internos são namespace packages (não têm
# ``__init__.py``) e a listagem explícita garante que todos entrem no
# bundle, mesmo se um coletor automático mudar de comportamento.
hiddenimports += [
    "core.analytical_profiles",
    "core.assistant",
    "core.prompt_manager",
    "core.smart_router",
    "core.source_router",
    "services.database_service",
    "services.document_parser",
    "services.external_api_service",
    "services.geocoding_service",
    "services.glossario_bilingue",
    "services.history_service",
    "services.llm_service",
    "services.rag_service",
    "services.report_generator",
    "services.spatial_parser",
    "services.table_extractor",
    "services.weather_service",
    "database.connection",
    "database.init_db",
    "utils.i18n",
]

hiddenimports += [
    "config",
    "setup_llm",
    "launcher_desktop",
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "database.init_db",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.runtime.scriptrunner.script_runner",
    "streamlit.runtime.scriptrunner.script_cache",
]

# ---------------------------------------------------------------------------
# Dados do projeto (lidos por caminho, nao por import)
# ---------------------------------------------------------------------------

datas += [
    (str(RAIZ / "app.py"), "."),
    (str(RAIZ / "setup_llm.py"), "."),
    (str(RAIZ / "config.py"), "."),
    (str(RAIZ / "prompts"), "prompts"),
    (str(RAIZ / ".streamlit"), ".streamlit"),
]

icone = RAIZ / "packaging" / "icone.ico"
icone_arg = str(icone) if icone.is_file() else None

# ---------------------------------------------------------------------------
# Higiene do bundle: estado local nunca entra no executavel
# ---------------------------------------------------------------------------
#
# O .spec nao copia a raiz inteira do projeto, mas ``collect_all`` e
# ``collect_data_files`` podem trazer pastas de testes/cache de dentro de
# dependencias. Este filtro e uma segunda barreira: remove qualquer dado ou
# binario cujo caminho contenha as pastas de estado local ou cujo nome seja
# um arquivo de ambiente/segredo. Assim o pacote nao infla nem vaza
# ``.dsh``, ``.git``, ``.ruff_cache``, ``__pycache__``, ``tests``, ``.env``
# ou ``estrutura.txt``.

PASTAS_LOCAIS_BLOQUEADAS = {
    ".dsh",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "tests",
}

ARQUIVOS_LOCAIS_BLOQUEADOS = {
    ".env",
    "config_local.json",
    "estrutura.txt",
    "secrets.toml",
}

EXTENSOES_SEGREDAS = {
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
}


def _destino_bloqueado(caminho, checar_extensoes=True):
    """Diz se um caminho DESTINO (relativo ao bundle) deve ser descartado.

    A checagem precisa usar o caminho de destino, nunca o de origem: todo
    pacote coletado de ``site-packages`` vive sob ``.venv`` e o filtro
    antigo, ao olhar a origem, descartava Streamlit, RapidOCR, python-docx
    e todos os ``.dist-info``. Sem esses dados o .exe congelado quebra no
    import do Streamlit com ``PackageNotFoundError``.
    """

    if not caminho:
        return False

    destino = Path(str(caminho).replace("\\", "/"))
    nomes = {destino.name} - {""}

    if any(parte in PASTAS_LOCAIS_BLOQUEADAS for parte in destino.parts):
        return True

    if nomes & ARQUIVOS_LOCAIS_BLOQUEADOS:
        return True

    if any(
        nome == ".env" or nome.startswith(".env.") or nome.endswith(".env")
        for nome in nomes
    ):
        return True

    return (
        bool(checar_extensoes)
        and destino.suffix.lower() in EXTENSOES_SEGREDAS
    )


def _filtrar_entradas(entradas):
    """Remove estado local de pares (origem, destino).

    Quando a origem e uma pasta (por exemplo ``.streamlit`` ou uma pasta
    de dados de dependencia), a arvore e expandida arquivo a arquivo
    antes do filtro. Assim um ``secrets.toml`` ou ``__pycache__`` dentro
    da pasta nao escapa da checagem feita apenas no caminho do diretorio.

    O filtro olha o DESTINO efetivo (destino + nome relativo). A origem
    so e consultada para saber se o arquivo pertence ao projeto: extensoes
    de certificado, como o ``cacert.pem`` do ``certifi``, sao legitimas em
    dependencias e nao podem ser tratadas como segredo local.
    """

    filtradas = []
    raiz_resolvida = RAIZ.resolve()

    for entrada in entradas:
        origem = Path(str(entrada[0]))
        destino = str(entrada[1])
        extras = tuple(entrada[2:])

        try:
            origem_local = origem.resolve().is_relative_to(raiz_resolvida)
        except (OSError, ValueError):
            origem_local = False

        if origem.is_dir():
            for arquivo in sorted(origem.rglob("*")):
                if not arquivo.is_file():
                    continue

                relativo = arquivo.relative_to(origem)
                destino_arquivo = Path(destino) / relativo

                if _destino_bloqueado(
                    destino_arquivo,
                    checar_extensoes=origem_local,
                ):
                    continue

                # O destino do PyInstaller e sempre um DIRETORIO: ele
                # acrescenta o nome do arquivo ao extrair. Usar
                # ``destino / relativo`` (com o nome do arquivo)
                # duplicava o ultimo componente no bundle, criando
                # ``prompts/system_base.txt/system_base.txt`` e
                # ``.streamlit/config.toml/config.toml``. O diretorio
                # correto e o pai do caminho relativo.
                novo_destino = str(Path(destino) / relativo.parent)
                filtradas.append((str(arquivo), novo_destino) + extras)
            continue

        if origem.is_file():
            destino_arquivo = Path(destino) / origem.name

            if _destino_bloqueado(
                destino_arquivo,
                checar_extensoes=origem_local,
            ):
                continue

            filtradas.append(entrada)

    return filtradas


datas = _filtrar_entradas(datas)
binaries = _filtrar_entradas(binaries)


def _filtrar_toc(entradas):
    """Segunda barreira: filtra a TOC final montada pelo ``Analysis``.

    Os hooks do PyInstaller acrescentam dados e binarios depois do
    filtro inicial de ``datas``/``binaries`` (por exemplo
    ``pyarrow/tests`` e ``pandas/tests``). Sem esta passagem eles vazam
    para ``_internal`` e o build portatil reprova na validacao do .zip.
    A checagem usa os componentes do caminho DESTINO e nomes exatos.
    Extensoes de certificado ficam de fora porque ``certifi/cacert.pem``
    e uma CA publica necessaria ao HTTPS, nao um segredo local.
    """

    filtradas = []

    for entrada in entradas:
        # So o caminho DESTINO e relativo ao bundle. A origem vive em
        # ``.venv/Lib/site-packages`` e contem ``.venv`` em todos os
        # itens: usa-la aqui descartaria o pacote inteiro.
        if _destino_bloqueado(entrada[0], checar_extensoes=False):
            continue

        filtradas.append(entrada)

    return filtradas

# ---------------------------------------------------------------------------
# Analise e montagem (--onedir: dist/NexusGeoIA/ + _internal/)
# ---------------------------------------------------------------------------

a = Analysis(
    [str(RAIZ / "launcher_desktop.py")],
    pathex=[str(RAIZ)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Playwright nao e usado pelo executavel e pesa centenas de MB.
    excludes=[
        "playwright",
        "tkinter.test",
        "unittest.test",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)

# Os hooks rodam dentro do ``Analysis`` e podem trazer pastas de teste
# das dependencias. Filtra a TOC consolidada antes de montar PYZ/EXE e
# COLLECT, para que o pacote --onedir respeite a mesma higiene do .zip.
a.datas = _filtrar_toc(a.datas)
a.binaries = _filtrar_toc(a.binaries)
a.zipfiles = _filtrar_toc(a.zipfiles)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    # --onedir: o .exe carrega as bibliotecas e os dados do diretorio
    # _internal ao lado dele, em vez de descompactar um _MEI... em %TEMP%.
    # Sem ``exclude_binaries=True`` o PyInstaller voltaria ao arquivo unico.
    exclude_binaries=True,
    name="NexusGeoIA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icone_arg,
)

# ``COLLECT`` fecha o modo --onedir: grava
# ``dist/NexusGeoIA/NexusGeoIA.exe`` + ``dist/NexusGeoIA/_internal/``.
# A opcao ``contents_directory="_internal"`` e o padrao do PyInstaller 6 e
# esta explicita para deixar claro de onde vem o ``sys._MEIPASS``.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NexusGeoIA",
    contents_directory="_internal",
)
