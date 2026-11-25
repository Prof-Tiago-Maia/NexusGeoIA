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
- o ``certifi/cacert.pem`` (``collect_data_files('certifi')``) e os
  modulos da cadeia de boot ``ollama``/``httpx``/``pydantic``: sem o
  certificado o import de ``services.llm_service`` falha com
  ``FileNotFoundError`` antes de qualquer consulta ao modelo;
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
import json
import os
import sys
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

# O .spec roda no interpretador do PyInstaller, cujo sys.path não inclui
# necessariamente a raiz do projeto. Sem isto collect_submodules("core")
# e a descoberta do manifesto podem falhar no build.
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

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
    # Metadados das dependencias do boot (LLM local e HTTP). Algumas
    # bibliotecas consultam a propria versao por ``importlib.metadata``
    # e sem o ``.dist-info`` dentro de ``_internal`` o executavel
    # congelado aborta com ``PackageNotFoundError``.
    "certifi",
    "httpx",
    "httpcore",
    "ollama",
    "pydantic",
    "pydantic-core",
    "requests",
    "urllib3",
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
# Certificados TLS (certifi/cacert.pem)
# ---------------------------------------------------------------------------
#
# BUG CORRIGIDO: ``services.llm_service`` importa ``ollama`` e instancia
# ``ollama.Client(...)`` no topo do modulo. O cliente cria um contexto
# SSL do ``httpx``, que no Windows le o ``cacert.pem`` do ``certifi``. No
# bundle ``--onedir`` esse arquivo precisa estar em
# ``_internal/certifi/cacert.pem``; sem ele o import falha com::
#
#     FileNotFoundError: [Errno 2] No such file or directory
#     ... httpx/_config.py -> ssl.create_default_context
#
# ``collect_all("streamlit")`` nao traz o certifi e o filtro de higiene
# nao tem relacao com o problema: o arquivo simplesmente nunca era
# coletado. Como ``certifi`` e dependencia dura de ``requests`` e do
# ``httpx`` (usados no boot), a coleta aqui NAO fica em try/except: se o
# pacote nao existir no ambiente do build, o build falha agora em vez de
# gerar um .exe que so quebra na primeira consulta ao Ollama.
dados_certifi = collect_data_files("certifi")

if not any(
    str(origem).replace("\\", "/").endswith("certifi/cacert.pem")
    for origem, _ in dados_certifi
):
    raise RuntimeError(
        "collect_data_files('certifi') nao encontrou certifi/cacert.pem; "
        "o executavel congelado falharia no import de services.llm_service."
    )

datas += dados_certifi

# ---------------------------------------------------------------------------
# Dependencias do boot (imports que o modulegraph pode perder)
# ---------------------------------------------------------------------------
#
# A cadeia que quebrou na validacao real foi:
# ``app.py`` -> ``core.assistant`` -> ``core.smart_router`` ->
# ``services.llm_service`` -> ``ollama`` -> ``httpx``. ``streamlit``
# importa ``httpx``/``pydantic`` de forma dinamica e o ``ollama`` tem
# submodulos resolvidos por nome. A lista garante que todos entrem mesmo
# quando um coletor automatico mudar de comportamento; cada item so e
# adicionado quando o modulo existe no ambiente (nada de hidden import
# "not found" quando a biblioteca opcional nao esta instalada).
MODULOS_BOOT = (
    "certifi",
    "ssl",
    "httpx",
    "httpx._config",
    "httpx._client",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "idna",
    "requests",
    "urllib3",
    "charset_normalizer",
    "ollama",
    "ollama._client",
    "ollama._types",
    "pydantic",
    "pydantic_core",
    "pydantic.deprecated",
    "pydantic.v1",
    "pypdf",
    "docx",
    "services.llm_service",
    "core.smart_router",
    "core.assistant",
)


def _modulo_instalado_boot(nome):
    """Diz se ``nome`` pode ser importado no Python que roda o build."""

    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, AttributeError, ValueError):
        return False


for modulo in MODULOS_BOOT:
    if _modulo_instalado_boot(modulo) and modulo not in hiddenimports:
        hiddenimports.append(modulo)

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
# Pacotes internos do projeto (v1.0.0)
# ---------------------------------------------------------------------------
#
# Todo pacote interno entra com ``collect_submodules`` e
# ``collect_data_files``, o equivalente no .spec às flags
# ``--collect-submodules`` e ``--collect-data`` do PyInstaller. A
# cobertura é redundante de propósito:
#
# 1. ``collect_submodules`` descobre o que o modulegraph perderia;
# 2. ``collect_data_files`` traz arquivos não-Python lidos por caminho;
# 3. o manifesto gerado por ``packaging/coleta_interna.py`` acrescenta
#    um hiddenimport explícito para CADA .py real de core, services, ui,
#    adapters e utils (mais config e setup_llm);
# 4. a checagem ``_faltantes_do_manifesto`` reprova o build se algum
#    .py do projeto ficar de fora.
#
# O pacote ``ui`` não existia na primeira versão do .spec e por isso o
# executável quebrava ao importar ``ui.*``; ``adapters`` segue o mesmo
# caminho (antes só ``core``, ``services``, ``database`` e ``utils``).
PACOTES_INTERNOS = ("core", "services", "ui", "adapters", "utils")

# database/ é o serviço legado de atendimentos, fora do fluxo principal,
# mas continua no bundle por compatibilidade.
PACOTES_LEGADOS = ("database",)

for pacote in PACOTES_INTERNOS + PACOTES_LEGADOS:
    if not _modulo_instalado(pacote):
        continue

    hiddenimports += collect_submodules(pacote)
    datas += collect_data_files(pacote)

# Módulos soltos na raiz que o launcher e o setup importam por nome.
MODULOS_RAIZ_INTERNOS = ("config", "setup_llm", "launcher_desktop")

for modulo in MODULOS_RAIZ_INTERNOS:
    if modulo not in hiddenimports:
        hiddenimports.append(modulo)


def _modulos_do_manifesto():
    """Lê a lista explícita gerada pelo build_portatil.ps1.

    O caminho vem de ``NEXUSGEO_MODULOS_MANIFEST``; sem a variável (por
    exemplo, ao rodar o PyInstaller à mão), cai para
    ``build/modulos_internos.json``. Lista vazia significa que o .spec
    usará apenas ``collect_submodules``, sem falhar.
    """

    caminho = os.environ.get("NEXUSGEO_MODULOS_MANIFEST", "").strip()
    candidatos = [Path(caminho)] if caminho else []
    candidatos.append(RAIZ / "build" / "modulos_internos.json")

    for arquivo in candidatos:
        try:
            if not arquivo.is_file():
                continue

            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        return [
            str(modulo)
            for modulo in dados.get("modulos") or []
            if str(modulo).strip()
        ]

    return []


for modulo in _modulos_do_manifesto():
    if modulo not in hiddenimports:
        hiddenimports.append(modulo)


def _faltantes_do_manifesto():
    """Módulos .py dos pacotes internos que não entraram no bundle."""

    esperados = set()

    for pacote in PACOTES_INTERNOS:
        pasta = RAIZ / pacote

        if not pasta.is_dir():
            continue

        for arquivo in pasta.rglob("*.py"):
            if "__pycache__" in arquivo.parts:
                continue

            partes = list(arquivo.relative_to(RAIZ).with_suffix("").parts)

            if partes and partes[-1] == "__init__":
                partes.pop()

            if partes:
                esperados.add(".".join(partes))

    return sorted(esperados - set(hiddenimports))


_faltando_no_bundle = _faltantes_do_manifesto()

if _faltando_no_bundle:
    raise RuntimeError(
        "Pacotes internos incompletos no PyInstaller: "
        + ", ".join(_faltando_no_bundle)
    )

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
    (str(RAIZ / "launcher_desktop.py"), "."),
    (str(RAIZ / "prompts"), "prompts"),
    (str(RAIZ / ".streamlit"), ".streamlit"),
    # ui/ e os Modelfile também viajam em _internal: o launcher faz
    # chdir para _MEIPASS e o setup_llm.resolve caminho pelo
    # config.diretorio_do_projeto(), que no bundle aponta para _internal.
    (str(RAIZ / "ui"), "ui"),
]

# finetuning/ é grande (datasets, adaptadores, relatórios). Só os
# templates Modelfile.* são recursos de runtime; o restante não entra no
# bundle nem no pacote portátil.
for _modelfile in sorted((RAIZ / "finetuning").glob("Modelfile.*")):
    datas.append((str(_modelfile), "finetuning"))

# O manifesto de módulos gerado pelo build também viaja em _internal:
# o --self-test do executável o usa para importar TODO módulo do projeto
# mesmo quando o pacote não tem a árvore .py de core/services/adapters.
_manifesto_modulos = RAIZ / "build" / "modulos_internos.json"

if _manifesto_modulos.is_file():
    datas.append((str(_manifesto_modulos), "."))

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
