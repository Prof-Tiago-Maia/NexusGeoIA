"""Testes offline dos scripts de empacotamento e do launcher.

Validam sintaxe e conteúdo de ``packaging/assistente.spec``,
``packaging/installer.iss``, ``packaging/*.ps1``, ``launcher_desktop.py``
e ``iniciar.bat`` sem executar PyInstaller, Inno Setup, Ollama ou o
Streamlit. A sintaxe do PowerShell é conferida pelo parser da própria
linguagem quando ``powershell``/``pwsh`` está disponível.
"""

import inspect
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import tomllib

import launcher_desktop
import setup_llm
from tests import _db_intocado

RAIZ = Path(__file__).resolve().parent.parent
PACKAGING = RAIZ / "packaging"

# Faixa de portas testada pelo launcher e pelo iniciar.bat.
PORTA_PREFERIDA = 8501
PORTA_MAXIMA = 8510

# Estado do diretório de dados durante a suíte (ver setUpModule).
_DIRETORIO_DADOS_ORIGINAL = None
_PASTA_DADOS_TESTE = None


def setUpModule():
    """Aponta o launcher para uma pasta descartável durante os testes.

    O log diagnóstico (<DATA_DIR>/launcher.log) e o registro de instância
    nunca podem tocar o perfil real do usuário quando a suíte executa
    abrir_navegador_url, abrir_navegador_quando_pronto ou main.
    """

    global _DIRETORIO_DADOS_ORIGINAL, _PASTA_DADOS_TESTE

    _DIRETORIO_DADOS_ORIGINAL = launcher_desktop.DIRETORIO_DADOS
    _PASTA_DADOS_TESTE = RAIZ / "build" / "_tmp_dados_launcher_testes"
    shutil.rmtree(_PASTA_DADOS_TESTE, ignore_errors=True)
    _PASTA_DADOS_TESTE.mkdir(parents=True, exist_ok=True)
    launcher_desktop.DIRETORIO_DADOS = _PASTA_DADOS_TESTE


def tearDownModule():
    """Restaura o diretório real e remove a pasta temporária."""

    if _DIRETORIO_DADOS_ORIGINAL is not None:
        launcher_desktop.DIRETORIO_DADOS = _DIRETORIO_DADOS_ORIGINAL

    if _PASTA_DADOS_TESTE is not None:
        shutil.rmtree(_PASTA_DADOS_TESTE, ignore_errors=True)


def ler(caminho):
    return Path(caminho).read_text(encoding="utf-8")


def carregar_modulo_packaging(nome):
    """Importa um helper de packaging/ pelo caminho, sem depender do pacote.

    O diretório packaging/ não tem __init__.py e o nome "packaging" colide
    com a distribuição do PyPI; por isso a carga é feita por arquivo.
    """

    import importlib.util

    caminho = PACKAGING / f"{nome}.py"
    spec = importlib.util.spec_from_file_location(
        f"nexusgeo_packaging_{nome}",
        caminho,
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    return modulo


def validar_iss(conteudo):
    """Validação estrutural mínima de um script do Inno Setup.

    Devolve a lista de problemas encontrados (vazia quando o arquivo
    está bem formado). Não substitui o ISCC; cobre seções, diretivas
    obrigatórias, chaves ``#if``/``#endif`` e linhas de seção.
    """

    problemas = []

    secoes_obrigatorias = (
        "[Setup]",
        "[Languages]",
        "[Files]",
        "[Icons]",
        "[Run]",
    )

    for secao in secoes_obrigatorias:
        if secao not in conteudo:
            problemas.append(f"seção ausente: {secao}")

    if "#if" in conteudo:
        abertos = conteudo.count("#if ")
        fechados = conteudo.count("#endif")

        if abertos != fechados:
            problemas.append(
                f"#if/#endif desbalanceados: {abertos} x {fechados}"
            )

    secao_atual = ""
    em_code = False

    for numero, linha in enumerate(conteudo.splitlines(), start=1):
        limpa = linha.strip()

        if not limpa or limpa.startswith((";", "#")):
            continue

        if limpa.startswith("[") and limpa.endswith("]"):
            secao_atual = limpa
            em_code = secao_atual == "[Code]"
            continue

        if em_code or limpa == "#endif":
            continue

        # Diretivas usam ``Chave=Valor``; entradas das seções usam
        # ``Chave: valor``.
        if "=" not in limpa and ":" not in limpa:
            problemas.append(
                f"linha {numero} sem '=' nem ':' na seção "
                f"{secao_atual}: {limpa}"
            )

    return problemas


class TestArquivosEmpacotamento(unittest.TestCase):
    """Os quatro entregáveis do empacotamento existem."""

    def test_arquivos_existem(self):
        esperados = (
            "assistente.spec",
            "installer.iss",
            "build_portatil.ps1",
            "build_installer.ps1",
        )

        for nome in esperados:
            self.assertTrue(
                (PACKAGING / nome).is_file(),
                f"packaging/{nome} não existe",
            )

    def test_python_do_pacote_compila(self):
        for nome in (
            RAIZ / "config.py",
            RAIZ / "setup_llm.py",
            RAIZ / "launcher_desktop.py",
            PACKAGING / "assistente.spec",
        ):
            compile(ler(nome), str(nome), "exec")


class TestSpec(unittest.TestCase):
    """A especificação do PyInstaller cobre Streamlit e as pastas internas."""

    def setUp(self):
        self.spec = ler(PACKAGING / "assistente.spec")

    def test_collect_all_e_copy_metadata_de_streamlit(self):
        self.assertIn("collect_all(", self.spec)
        self.assertIn('"streamlit"', self.spec)
        self.assertIn("copy_metadata(", self.spec)

    def test_copy_metadata_do_streamlit_e_obrigatorio(self):
        # ``import streamlit`` chama ``importlib.metadata.version(...)``.
        # Sem o diretório streamlit-*.dist-info em _internal o executável
        # congelado falha com PackageNotFoundError antes de abrir a GUI.
        self.assertIn('datas += copy_metadata("streamlit")', self.spec)
        self.assertIn("PACOTES_METADADOS", self.spec)

        for distribuicao in (
            "streamlit",
            "altair",
            "pillow",
            "pydeck",
            "click",
            "packaging",
        ):
            self.assertIn(f'"{distribuicao}"', self.spec)

    def test_filtro_de_dados_nao_descarta_site_packages(self):
        # A origem de todo pacote coletado vive em .venv\Lib\site-packages.
        # Olhar a ORIGEM no filtro descartava Streamlit, RapidOCR,
        # python-docx e os .dist-info; a decisão precisa usar o DESTINO.
        trecho = self.spec[
            self.spec.index("def _destino_bloqueado"):
            self.spec.index("datas = _filtrar_entradas")
        ]

        self.assertIn("_destino_bloqueado", trecho)
        self.assertIn("origem.resolve().is_relative_to", trecho)
        self.assertIn("destino_arquivo", trecho)
        self.assertNotIn("_caminho_do_projeto", self.spec)

    def test_launcher_e_app_como_entrada_e_dado(self):
        self.assertIn("launcher_desktop.py", self.spec)
        self.assertIn('RAIZ / "app.py"', self.spec)
        self.assertIn(".streamlit", self.spec)
        self.assertIn("prompts", self.spec)

    def test_pacotes_internos_incluidos(self):
        for pacote in ("core", "services", "database", "utils"):
            self.assertIn(pacote, self.spec)

    def test_gera_pacote_onedir(self):
        # O empacotamento e --onedir: EXE(exclude_binaries=True) seguido
        # de COLLECT. O modo arquivo unico exigia criar _MEI... em %TEMP%
        # e falhava com "Could not create temporary directory!".
        self.assertIn("EXE(", self.spec)
        self.assertIn("exclude_binaries=True", self.spec)
        self.assertIn("COLLECT(", self.spec)
        self.assertIn('contents_directory="_internal"', self.spec)
        self.assertIn('name="NexusGeoIA"', self.spec)
        self.assertNotIn("exclude_binaries=False", self.spec)

    def test_exe_nao_embute_binarios_no_onedir(self):
        # No --onedir o EXE recebe apenas pyz/scripts; binarios, dados e
        # zipfiles vao para o COLLECT (pasta _internal).
        trecho_exe = self.spec[
            self.spec.index("exe = EXE("):
            self.spec.index("coll = COLLECT(")
        ]

        self.assertNotIn("a.binaries", trecho_exe)
        self.assertNotIn("a.datas", trecho_exe)

        trecho_collect = self.spec[self.spec.index("coll = COLLECT("):]

        for entrada in ("a.binaries", "a.zipfiles", "a.datas"):
            self.assertIn(entrada, trecho_collect)

    def test_spec_filtra_toc_final_do_analysis(self):
        # Os hooks do PyInstaller (pyarrow, pandas, ...) acrescentam
        # dados depois do filtro inicial; a TOC consolidada precisa da
        # mesma higiene antes do COLLECT.
        for trecho in (
            "def _filtrar_toc",
            "a.datas = _filtrar_toc(a.datas)",
            "a.binaries = _filtrar_toc(a.binaries)",
            "a.zipfiles = _filtrar_toc(a.zipfiles)",
            "certifi/cacert.pem",
            "So o caminho DESTINO",
        ):
            self.assertIn(trecho, self.spec)

    def test_spec_filtra_estado_local_e_segredos(self):
        # O bundle nunca deve carregar estado local, cache, testes ou
        # arquivos de ambiente/segredo, mesmo que uma coleta os traga.
        for trecho in (
            "PASTAS_LOCAIS_BLOQUEADAS",
            "ARQUIVOS_LOCAIS_BLOQUEADOS",
            "EXTENSOES_SEGREDAS",
            "_filtrar_entradas",
            ".dsh",
            ".git",
            ".ruff_cache",
            "__pycache__",
            "tests",
            "config_local.json",
            "secrets.toml",
        ):
            self.assertIn(trecho, self.spec)

    def test_spec_cobre_bibliotecas_de_exportacao(self):
        # report_generator (Word), table_extractor (Excel) e
        # document_parser (PDF) importam estas bibliotecas de forma
        # tardia; sem cobertura o .exe quebra só na exportação.
        for trecho in (
            "PACOTES_DOCUMENTO",
            "python-docx",
            "openpyxl",
            "pypdf",
            "PyMuPDF",
            "MODULOS_DOCUMENTO",
            "docx.opc.constants",
            "docx.oxml.ns",
            "docx.shared",
            "openpyxl.styles",
            "pandas.io.excel._openpyxl",
            "pymupdf",
            "fitz",
        ):
            self.assertIn(trecho, self.spec)

    def test_spec_coleta_dados_do_python_docx(self):
        # ``Document()`` sem argumento lê ``docx/templates/default.docx``
        # do disco; só o hiddenimport não basta no bundle empacotado.
        #
        # A coleta precisa usar o nome IMPORTADO (``docx``), não o da
        # distribuição (``python-docx``): com o nome errado o PyInstaller
        # apenas avisa "not a package" e segue sem os dados.
        self.assertIn('("docx", "python-docx")', self.spec)
        self.assertIn('("pymupdf", "PyMuPDF")', self.spec)
        self.assertIn("collect_data_files(", self.spec)
        self.assertIn("copy_metadata(distribuicao)", self.spec)
        self.assertIn('EXCLUSOES_DADOS.get(modulo', self.spec)
        self.assertIn("importlib.util.find_spec", self.spec)
        self.assertIn("_modulo_instalado", self.spec)

    def test_filtro_de_dados_preserva_o_diretorio_de_destino(self):
        # O destino de ``datas`` no PyInstaller e sempre um DIRETORIO.
        # Usar ``destino / relativo`` (com o nome do arquivo) duplicava o
        # ultimo componente no bundle:
        # ``prompts/system_base.txt/system_base.txt`` e
        # ``.streamlit/config.toml/config.toml``. O pai do caminho
        # relativo preserva a arvore correta.
        trecho = self.spec[
            self.spec.index("def _filtrar_entradas"):
            self.spec.index("datas = _filtrar_entradas")
        ]

        self.assertIn("relativo.parent", trecho)
        self.assertNotIn("Path(destino) / relativo)", trecho)

    def test_spec_tolera_biblioteca_ausente(self):
        # Cada coleta nova fica em try/except: o build não pode falhar
        # quando a biblioteca opcional não está instalada.
        trecho = self.spec[
            self.spec.index("for modulo, distribuicao in PACOTES_DOCUMENTO"):
            self.spec.index("MODULOS_DOCUMENTO = (")
        ]

        self.assertIn("try:", trecho)
        self.assertIn("except Exception:", trecho)


class TestArtefatoCompilado(unittest.TestCase):
    """O pacote --onedir compilado carrega os metadados lidos em runtime."""

    def test_internal_contem_metadados_do_streamlit(self):
        interna = RAIZ / "dist" / "NexusGeoIA" / "_internal"
        spec = PACKAGING / "assistente.spec"

        if not interna.is_dir():
            self.skipTest("dist\\NexusGeoIA\\_internal ainda não compilado")

        # A suíte roda antes do PyInstaller dentro do build. Um artefato
        # anterior à correção do .spec não serve de evidência para o
        # bundle novo; depois da recompilação o teste passa a valer.
        if interna.stat().st_mtime < spec.stat().st_mtime:
            self.skipTest(
                "artefato compilado antes da correção do .spec; "
                "recompile para validar"
            )

        dist_infos = sorted(
            caminho.name
            for caminho in interna.iterdir()
            if caminho.is_dir()
            and re.fullmatch(
                r"streamlit-.*\.dist-info",
                caminho.name,
                re.IGNORECASE,
            )
        )

        self.assertTrue(
            dist_infos,
            "dist\\NexusGeoIA\\_internal não contém streamlit-*.dist-info: "
            "o .exe congelado falharia com PackageNotFoundError",
        )

        metadados = interna / dist_infos[0] / "METADATA"

        self.assertTrue(
            metadados.is_file(),
            f"METADATA ausente em {dist_infos[0]}",
        )


class TestInstallerIss(unittest.TestCase):
    """O instalador cria atalhos, roda o setup e fala português."""

    def setUp(self):
        self.iss = ler(PACKAGING / "installer.iss")

    def test_estrutura_valida(self):
        self.assertEqual(validar_iss(self.iss), [])

    def test_nome_do_instalador(self):
        self.assertIn(
            "OutputBaseFilename=NexusGeoIA_v1.0.0_Setup",
            self.iss,
        )
        self.assertIn("AppName=NexusGeo IA", self.iss)
        self.assertIn("AppVersion=1.0.0", self.iss)
        self.assertIn('#define MyAppName "NexusGeo IA"', self.iss)
        self.assertIn('#define MyAppVersion "1.0.0"', self.iss)

    def test_idioma_portugues_brasil(self):
        self.assertIn("BrazilianPortuguese.isl", self.iss)
        self.assertIn('Name: "brazilianportuguese"', self.iss)

    def test_atalhos_area_de_trabalho_e_menu_iniciar(self):
        self.assertIn("{autodesktop}", self.iss)
        self.assertIn("{group}", self.iss)
        self.assertIn("Name: \"desktopicon\"", self.iss)

    def test_atalho_gerenciar_modelos(self):
        self.assertIn("Gerenciar Modelo Local", self.iss)
        self.assertGreaterEqual(self.iss.count("--setup-modelo"), 2)

    def test_assistente_roda_ao_final_da_instalacao(self):
        self.assertIn("postinstall", self.iss)
        self.assertIn("skipifsilent", self.iss)

    def test_empacota_o_pacote_onedir_do_pyinstaller(self):
        # O instalador copia dist\NexusGeoIA\* (o .exe e a pasta
        # _internal) recursivamente para {app}.
        self.assertIn(
            r'Source: "..\dist\NexusGeoIA\*"',
            self.iss,
        )
        self.assertIn("recursesubdirs", self.iss)
        self.assertIn("createallsubdirs", self.iss)
        self.assertIn("DestDir: \"{app}\"", self.iss)

    def test_instala_o_ollama_silenciosamente(self):
        self.assertIn("OllamaSetup.exe", self.iss)
        self.assertIn("CurStepChanged", self.iss)
        self.assertIn("ssPostInstall", self.iss)
        self.assertIn(
            "ExtractTemporaryFile('instalar_ollama.ps1')",
            self.iss,
        )
        self.assertIn("-File", self.iss)
        self.assertNotIn("-Command", self.iss)

        script = ler(PACKAGING / "instalar_ollama.ps1")

        self.assertIn("/VERYSILENT", script)
        self.assertIn("/NORESTART", script)
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertIn("Invoke-WebRequest", script)
        self.assertIn("SignerCertificate.Subject", script)

    def test_instala_sem_uac_por_padrao(self):
        # Sem prompt de Administrador em PCs academicos/laboratorios.
        self.assertIn("PrivilegesRequired=lowest", self.iss)
        self.assertIn(
            "PrivilegesRequiredOverridesAllowed=dialog",
            self.iss,
        )
        self.assertNotIn("PrivilegesRequired=admin", self.iss)

    def test_diretorio_padrao_compativel_com_instalacao_sem_uac(self):
        # {autopf} resolve para %LOCALAPPDATA%\Programs no modo lowest e
        # para Program Files apenas quando o usuario escolhe o override.
        self.assertIn("DefaultDirName={autopf}\\{#MyAppDirName}", self.iss)
        self.assertIn('#define MyAppDirName "NexusGeoIA"', self.iss)


class TestConfigStreamlit(unittest.TestCase):
    """A configuracao compartilhada abre o navegador em localhost:8501."""

    def setUp(self):
        caminho = RAIZ / ".streamlit" / "config.toml"

        with caminho.open("rb") as arquivo:
            self.config = tomllib.load(arquivo)

    def test_headless_desligado(self):
        self.assertIs(self.config["server"]["headless"], False)

    def test_endereco_do_aplicativo_sem_porta_fixa(self):
        # A porta e escolhida pelo launcher (8501..8510) e repassada em
        # --server.port. Fixa-la no TOML quebra a importacao do app no
        # bundle PyInstaller, onde o Streamlit infere developmentMode.
        self.assertEqual(self.config["server"]["address"], "localhost")
        self.assertNotIn("port", self.config["server"])

    def test_metricas_de_uso_desativadas(self):
        self.assertIs(self.config["browser"]["gatherUsageStats"], False)

    def test_limite_de_upload_configurado(self):
        self.assertEqual(self.config["server"]["maxUploadSize"], 100)


class TestLauncher(unittest.TestCase):
    """O launcher define o diretório de dados e inicia o Streamlit."""

    def setUp(self):
        self.codigo = ler(RAIZ / "launcher_desktop.py")

    def test_define_localappdata_antes_do_config(self):
        posicao_env = self.codigo.index("ASSISTENTE_DATA_DIR")
        posicao_import = self.codigo.index("import config")

        self.assertLess(posicao_env, posicao_import)

    def test_chama_setup_llm_e_streamlit(self):
        self.assertIn("setup_llm.main(", self.codigo)
        self.assertIn("streamlit.web import cli", self.codigo)
        self.assertIn("--global.developmentMode=false", self.codigo)

    def test_streamlit_headless_para_o_launcher_abrir_so_uma_aba(self):
        self.assertIn("--server.headless=true", self.codigo)
        self.assertIn("agendar_abertura_navegador(porta)", self.codigo)

    def test_abre_localhost_8501_apos_o_healthcheck(self):
        chamadas = []

        with mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=True,
        ):
            resultado = launcher_desktop.abrir_navegador_quando_pronto(
                tentativas=1,
                intervalo=0,
                abrir=chamadas.append,
            )

        self.assertTrue(resultado)
        self.assertEqual(chamadas, ["http://localhost:8501"])
        self.assertEqual(
            launcher_desktop.URL_APLICATIVO,
            "http://localhost:8501",
        )

    def test_nao_abre_navegador_sem_healthcheck(self):
        chamadas = []

        with mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=False,
        ):
            resultado = launcher_desktop.abrir_navegador_quando_pronto(
                tentativas=2,
                intervalo=0,
                abrir=chamadas.append,
            )

        self.assertFalse(resultado)
        self.assertEqual(chamadas, [])

    def test_healthcheck_consulta_a_porta_8501(self):
        class RespostaSaude:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def getcode(self):
                return 200

        with mock.patch.object(
            launcher_desktop.urllib.request,
            "urlopen",
            return_value=RespostaSaude(),
        ) as urlopen:
            self.assertTrue(launcher_desktop.aplicacao_respondendo())

        self.assertEqual(
            urlopen.call_args.args[0],
            "http://localhost:8501/_stcore/health",
        )

    def test_flags_do_atalho(self):
        self.assertIn('"--setup-modelo"', self.codigo)
        self.assertIn('"--forcar"', self.codigo)

    def test_inclui_ollama_no_path_da_sessao(self):
        self.assertIn("adicionar_ollama_ao_path", self.codigo)
        self.assertIn('"Programs" / "Ollama"', self.codigo)

    def test_preserva_pasta_portatil_quando_gravavel(self):
        base = RAIZ / "build" / "_tmp_fallback_dados"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)

        try:
            pacote = base / "pacote"
            pacote.mkdir()
            local = base / "localappdata"

            with mock.patch.object(
                launcher_desktop,
                "diretorio_localappdata",
                return_value=local,
            ), mock.patch.dict(
                os.environ,
                {"ASSISTENTE_DATA_DIR": str(pacote)},
            ):
                resultado = launcher_desktop.configurar_diretorio_dados()

                self.assertEqual(resultado, pacote)
                self.assertEqual(
                    os.environ["ASSISTENTE_DATA_DIR"],
                    str(pacote),
                )
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_cai_para_localappdata_quando_pasta_portatil_e_protegida(self):
        base = RAIZ / "build" / "_tmp_fallback_dados"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)

        try:
            pacote = base / "Program Files" / "NexusGeoIA"
            local = base / "localappdata"
            local.mkdir()

            def gravavel(caminho):
                return Path(caminho) == local

            with mock.patch.object(
                launcher_desktop,
                "diretorio_localappdata",
                return_value=local,
            ), mock.patch.object(
                launcher_desktop,
                "_diretorio_gravavel",
                side_effect=gravavel,
            ), mock.patch.dict(
                os.environ,
                {"ASSISTENTE_DATA_DIR": str(pacote)},
            ):
                resultado = launcher_desktop.configurar_diretorio_dados()

                self.assertEqual(resultado, local)
                self.assertEqual(
                    os.environ["ASSISTENTE_DATA_DIR"],
                    str(local),
                )
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestPortaDinamicaLauncher(unittest.TestCase):
    """O launcher escolhe a primeira porta livre e a repassa ao Streamlit."""

    @staticmethod
    def _ocupar(porta):
        """Reserva ``porta`` em 127.0.0.1; devolve o socket ocupado."""

        soquete = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            soquete.bind((launcher_desktop.ENDERECO_LOOPBACK, int(porta)))
        except OSError:
            soquete.close()
            raise

        soquete.listen(5)

        return soquete

    def test_assinatura_padrao(self):
        parametros = inspect.signature(
            launcher_desktop._encontrar_porta_livre
        ).parameters

        self.assertEqual(parametros["porta_inicial"].default, 8501)
        self.assertEqual(parametros["tentativas"].default, 10)

    def test_8501_livre_devolve_8501(self):
        if not launcher_desktop._porta_disponivel(8501):
            self.skipTest("8501 já está ocupada neste ambiente")

        self.assertEqual(launcher_desktop._encontrar_porta_livre(), 8501)

    def test_8501_ocupada_devolve_8502(self):
        try:
            ocupado = self._ocupar(8501)
        except OSError:
            self.skipTest("8501 já está ocupada por outro processo")

        self.addCleanup(ocupado.close)

        if not launcher_desktop._porta_disponivel(8502):
            self.skipTest("8502 também está ocupada neste ambiente")

        self.assertEqual(
            launcher_desktop._encontrar_porta_livre(8501, 10),
            8502,
        )

    def test_nao_devolve_porta_ocupada(self):
        try:
            ocupado = self._ocupar(8501)
        except OSError:
            self.skipTest("8501 já está ocupada por outro processo")

        self.addCleanup(ocupado.close)

        porta = launcher_desktop._encontrar_porta_livre(8501, 10)

        self.assertNotEqual(porta, 8501)
        self.assertTrue(launcher_desktop._porta_disponivel(porta))

    def test_faixa_esgotada_pede_porta_efemera(self):
        with mock.patch.object(
            launcher_desktop,
            "_porta_disponivel",
            return_value=False,
        ):
            porta = launcher_desktop._encontrar_porta_livre(8501, 10)

        self.assertFalse(8501 <= porta <= 8510, porta)
        self.assertGreater(porta, 0)
        self.assertTrue(launcher_desktop._porta_disponivel(porta))

    def test_url_da_porta_escolhida(self):
        self.assertEqual(
            launcher_desktop.url_aplicativo(8502),
            "http://localhost:8502",
        )
        self.assertEqual(
            launcher_desktop.URL_APLICATIVO,
            "http://localhost:8501",
        )

    def test_abre_a_url_da_porta_escolhida(self):
        chamadas = []

        with mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=True,
        ):
            resultado = launcher_desktop.abrir_navegador_quando_pronto(
                porta=8502,
                tentativas=1,
                intervalo=0,
                abrir=chamadas.append,
            )

        self.assertTrue(resultado)
        self.assertEqual(chamadas, ["http://localhost:8502"])

    def test_porta_do_argumento_aceita_as_duas_formas(self):
        self.assertEqual(
            launcher_desktop.porta_do_argumento(
                ["--servidor-streamlit", "--porta", "8504"]
            ),
            8504,
        )
        self.assertEqual(
            launcher_desktop.porta_do_argumento(["--porta=8506"]),
            8506,
        )
        self.assertEqual(
            launcher_desktop.porta_do_argumento(["--porta", "x"]),
            launcher_desktop.PORTA_PREFERIDA,
        )
        self.assertEqual(
            launcher_desktop.porta_do_argumento([]),
            launcher_desktop.PORTA_PREFERIDA,
        )

    def test_executar_servidor_streamlit_roda_o_cli_e_registra(self):
        lidos = {}
        argumentos_originais = list(sys.argv)
        self.addCleanup(
            lambda: sys.argv.__setitem__(slice(None), argumentos_originais)
        )

        def main_falso():
            lidos["argv"] = list(sys.argv)
            raise SystemExit(0)

        with mock.patch.object(
            launcher_desktop,
            "caminho_app",
            return_value=RAIZ / "app.py",
        ), mock.patch.object(
            launcher_desktop, "preparar_ambiente"
        ), mock.patch.object(
            launcher_desktop, "_gravar_registro_instancia"
        ) as gravar, mock.patch.object(
            launcher_desktop, "_remover_registro_instancia"
        ) as remover, mock.patch(
            "streamlit.web.cli.main",
            side_effect=main_falso,
        ):
            codigo = launcher_desktop.executar_servidor_streamlit(8504)

        self.assertEqual(codigo, 0)
        self.assertIn("--server.port=8504", lidos["argv"])
        self.assertIn("--server.headless=true", lidos["argv"])
        gravar.assert_called_once_with(8504)
        remover.assert_called_once_with()

    def test_monitor_de_sessao_e_agendado_antes_do_cli(self):
        """O monitor sobe imediatamente antes de ``cli.main()``."""

        ordem = []
        thread = mock.Mock()
        thread.name = "nexusgeo-monitor-sessao"
        thread.daemon = True
        thread.is_alive.return_value = True

        def agendar(porta):
            ordem.append(("agendar", porta))

            return thread

        def main_falso():
            ordem.append("main")
            raise SystemExit(0)

        argumentos_originais = list(sys.argv)
        self.addCleanup(
            lambda: sys.argv.__setitem__(slice(None), argumentos_originais)
        )

        with mock.patch.dict(
            os.environ, {launcher_desktop.ENV_MONITOR_SESSAO: "1"}
        ), mock.patch.object(
            launcher_desktop,
            "caminho_app",
            return_value=RAIZ / "app.py",
        ), mock.patch.object(
            launcher_desktop, "preparar_ambiente"
        ), mock.patch.object(
            launcher_desktop, "_gravar_registro_instancia"
        ), mock.patch.object(
            launcher_desktop, "_remover_registro_instancia"
        ), mock.patch.object(
            launcher_desktop,
            "agendar_monitor_sessao",
            side_effect=agendar,
        ) as agendou, mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ) as registrar, mock.patch(
            "streamlit.web.cli.main",
            side_effect=main_falso,
        ):
            codigo = launcher_desktop.executar_servidor_streamlit(8504)

        self.assertEqual(codigo, 0)
        self.assertEqual(ordem, [("agendar", 8504), "main"])
        agendou.assert_called_once_with(8504)
        registrar.assert_any_call(
            "monitor de sessões iniciado "
            "(janela=25.0s, inatividade=10.0s)"
        )

    def test_agendar_monitor_sessao_usa_thread_daemon(self):
        thread = mock.Mock()

        with mock.patch.object(
            launcher_desktop.threading,
            "Thread",
            return_value=thread,
        ) as criadora:
            retorno = launcher_desktop.agendar_monitor_sessao(8504)

        self.assertIs(retorno, thread)
        thread.start.assert_called_once_with()
        _, opcoes = criadora.call_args
        self.assertTrue(opcoes["daemon"])
        self.assertIs(opcoes["target"], launcher_desktop.monitorar_sessoes_ativas)
        self.assertEqual(opcoes["name"], "nexusgeo-monitor-sessao")
        self.assertEqual(opcoes["kwargs"], {"porta": 8504})

    def test_argumentos_do_streamlit_usam_a_porta_escolhida(self):
        argumentos = launcher_desktop.argumentos_streamlit(8502)

        self.assertIn("--server.port=8502", argumentos)
        self.assertNotIn("--server.port", argumentos)
        self.assertIn("--server.headless=true", argumentos)
        self.assertIn("--global.developmentMode=false", argumentos)
        self.assertIn(str(RAIZ / "app.py"), argumentos)

    def test_comando_do_servidor_reexecuta_o_launcher(self):
        comando = launcher_desktop.comando_servidor(8504)

        self.assertEqual(comando[0], str(sys.executable))
        self.assertIn(launcher_desktop.ARG_SERVIDOR, comando)
        self.assertEqual(
            comando[comando.index(launcher_desktop.ARG_PORTA) + 1],
            "8504",
        )

    def test_iniciar_streamlit_usa_subprocesso_e_job_object(self):
        class ProcessoFalso:
            """Subprocesso falso: registra a espera e devolve o código."""

            pid = 4242

            def __init__(self):
                self.aguardou = False

            def wait(self):
                self.aguardou = True

                return 0

            def poll(self):
                return 0

        processo = ProcessoFalso()
        job = mock.Mock()
        job.ativo = True
        job.criar.return_value = True
        job.associar.return_value = True

        with mock.patch.object(
            launcher_desktop,
            "caminho_app",
            return_value=RAIZ / "app.py",
        ), mock.patch.object(
            launcher_desktop, "preparar_ambiente"
        ), mock.patch.object(
            launcher_desktop, "registrar_limpeza_encerramento"
        ) as registrar, mock.patch.object(
            launcher_desktop,
            "JobObjectWindows",
            return_value=job,
        ), mock.patch.object(
            launcher_desktop, "subprocess"
        ) as modulo_subprocesso, mock.patch.object(
            launcher_desktop, "agendar_abertura_navegador"
        ) as navegador, mock.patch.object(
            launcher_desktop, "_limpar_servidor"
        ):
            modulo_subprocesso.Popen.return_value = processo

            codigo = launcher_desktop.iniciar_streamlit(8502)

        self.assertEqual(codigo, 0)
        self.assertTrue(processo.aguardou)

        comando = modulo_subprocesso.Popen.call_args.args[0]

        self.assertIn(launcher_desktop.ARG_SERVIDOR, comando)
        self.assertIn("8502", comando)

        registrar.assert_called_once()
        job.criar.assert_called_once()
        job.associar.assert_called_once_with(processo)
        navegador.assert_called_once_with(8502)


class TestResolucaoEmModoCongelado(unittest.TestCase):
    """Recursos lidos por caminho vêm de ``sys._MEIPASS`` no executável.

    Em ``Program Files`` a pasta de instalação é somente leitura e não
    guarda ``app.py``, ``prompts`` nem ``.streamlit``: tudo precisa ser
    resolvido do bundle extraído pelo PyInstaller.
    """

    def test_config_resolve_recursos_do_meipass(self):
        import config

        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(
                    sys, "_MEIPASS", r"C:\Temp\_MEI123", create=True
                ):
            self.assertEqual(
                config.diretorio_do_projeto(),
                Path(r"C:\Temp\_MEI123").resolve(),
            )

    def test_config_cai_para_a_pasta_do_executavel(self):
        import config

        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\App\NexusGeoIA.exe"):
            if hasattr(sys, "_MEIPASS"):
                self.skipTest("a sessão define _MEIPASS; cenário inválido")

            self.assertEqual(
                config.diretorio_do_projeto(),
                Path(r"C:\App").resolve(),
            )

    def test_config_fora_do_executavel_usa_a_raiz_do_projeto(self):
        import config

        self.assertEqual(
            config.diretorio_do_projeto(),
            RAIZ.resolve(),
        )

    def test_config_grava_dados_fora_do_program_files(self):
        import config

        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(
                    os.environ,
                    {"LOCALAPPDATA": r"C:\Users\teste\AppData\Local"},
                ):
            self.assertEqual(
                config.diretorio_padrao_dados(),
                Path(r"C:\Users\teste\AppData\Local") / config.NOME_APLICATIVO,
            )

    def test_launcher_resolve_app_do_meipass(self):
        with mock.patch.object(sys, "_MEIPASS", r"C:\Temp\_MEI123", create=True):
            self.assertEqual(
                launcher_desktop.diretorio_recursos(),
                Path(r"C:\Temp\_MEI123").resolve(),
            )
            self.assertEqual(
                launcher_desktop.caminho_app(),
                Path(r"C:\Temp\_MEI123").resolve() / "app.py",
            )

    def test_prompt_manager_usa_a_raiz_do_config(self):
        # ``prompts/system_base.txt`` é lido por caminho: a raiz precisa
        # vir do config.py, que é a fonte única da verdade para
        # desenvolvimento x congelado.
        import config
        from core import prompt_manager

        self.assertEqual(
            prompt_manager.DIRETORIO_PROMPTS,
            config.diretorio_do_projeto() / "prompts",
        )
        self.assertEqual(
            prompt_manager.ARQUIVO_PROMPT_BASE,
            prompt_manager.DIRETORIO_PROMPTS / "system_base.txt",
        )

    def test_prompt_manager_le_o_arquivo_empacotado(self):
        from core import prompt_manager

        self.assertTrue(prompt_manager.arquivo_prompt_base().is_file())
        self.assertTrue(prompt_manager.carregar_prompt_base().strip())

    def test_launcher_verifica_recursos_do_bundle(self):
        with mock.patch.object(
            launcher_desktop,
            "diretorio_recursos",
            return_value=RAIZ,
        ):
            self.assertEqual(launcher_desktop.recursos_ausentes(), [])
            self.assertEqual(
                launcher_desktop.verificar_recursos(),
                RAIZ,
            )

    def test_launcher_aponta_recurso_ausente(self):
        with mock.patch.object(
            launcher_desktop,
            "diretorio_recursos",
            return_value=RAIZ / "packaging",
        ):
            ausentes = launcher_desktop.recursos_ausentes()
            nomes = [caminho for caminho, _ in ausentes]

            self.assertEqual(len(ausentes), 3)
            self.assertTrue(any(n.endswith("app.py") for n in nomes))

            with self.assertRaises(FileNotFoundError) as contexto:
                launcher_desktop.verificar_recursos()

            self.assertIn("app.py", str(contexto.exception))


class TestAutotesteExecutavel(unittest.TestCase):
    """O ``--autoteste`` valida bundle, imports, Word e Excel."""

    def test_argumentos_reconhecidos(self):
        self.assertEqual(launcher_desktop.ARG_AUTOTESTE, "--autoteste")
        self.assertIn(
            launcher_desktop.ARG_AUTOTESTE,
            (Path(RAIZ) / "launcher_desktop.py").read_text(encoding="utf-8"),
        )

    def test_autoteste_aprova_o_projeto(self):
        pasta = RAIZ / "build" / "_tmp_autoteste"
        pasta.mkdir(parents=True, exist_ok=True)

        relatorio = pasta / "smoke.json"

        if relatorio.is_file():
            relatorio.unlink()

        try:
            resultado = launcher_desktop.autoteste(relatorio=str(relatorio))

            self.assertTrue(resultado["ok"], resultado["falhas"])
            self.assertTrue(relatorio.is_file())

            dados = json.loads(relatorio.read_text(encoding="utf-8"))

            self.assertTrue(dados["ok"])
            self.assertFalse(dados["congelado"])

            nomes = [
                verificacao["nome"]
                for verificacao in dados["verificacoes"]
            ]

            self.assertIn("recursos", nomes)
            self.assertIn("system_prompt", nomes)
            self.assertIn("imports_criticos", nomes)
            self.assertIn("parecer_docx", nomes)
            self.assertIn("excel_openpyxl", nomes)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_autoteste_nao_abre_servidor_nem_setup(self):
        # O autoteste precisa sair antes do configurador do modelo local e do
        # Streamlit: sem isso o smoke test do build travaria esperando
        # interação de janela.
        with mock.patch.object(
            launcher_desktop,
            "autoteste",
            return_value={"ok": True, "verificacoes": [], "falhas": []},
        ) as teste, mock.patch.object(
            launcher_desktop, "configuracao_pendente"
        ) as pendente, mock.patch.object(
            launcher_desktop, "iniciar_streamlit"
        ) as streamlit:
            codigo = launcher_desktop.main(["--autoteste"])

        self.assertEqual(codigo, 0)
        teste.assert_called_once()
        pendente.assert_not_called()
        streamlit.assert_not_called()

    def test_autoteste_reprovado_devolve_codigo_1(self):
        with mock.patch.object(
            launcher_desktop,
            "autoteste",
            return_value={
                "ok": False,
                "verificacoes": [
                    {"nome": "parecer_docx", "ok": False, "erro": "x"}
                ],
                "falhas": ["parecer_docx: x"],
            },
        ):
            codigo = launcher_desktop.main(["--autoteste"])

        self.assertEqual(codigo, 1)

    def test_build_portatil_executa_o_self_test_obrigatorio(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O build so conclui quando o .exe compilado passa no --self-test.
        # O smoke test deixou de ser opt-in: nao existe mais -SmokeExe.
        self.assertIn("smoke_exe.py", codigo)
        self.assertIn("--self-test", codigo)
        self.assertIn("Self-test obrigatorio do executavel", codigo)
        self.assertNotIn("if (-not $SmokeExe)", codigo)
        self.assertNotIn("[switch]$SmokeExe", codigo)

        smoke = codigo.index("Self-test obrigatorio do executavel")
        zip_final = codigo.index("Gerando $ZipFinal")

        self.assertLess(
            smoke,
            zip_final,
            "o self-test deve rodar antes da geracao do .zip",
        )
        self.assertIn("ASSISTENTE_SELFTEST_REPORT", codigo)
        self.assertIn("self_test.json", codigo)

    def test_build_portatil_inclui_o_protocolo_de_pesquisa(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O protocolo viaja no .zip, e o build falha se ele sumir.
        self.assertIn('Join-Path $Raiz "PROTOCOLO_PESQUISA.md"', codigo)
        self.assertIn('"PROTOCOLO_PESQUISA.md",', codigo)

        conteudo = ler(RAIZ / "PROTOCOLO_PESQUISA.md")

        self.assertIn("NexusGeo IA", conteudo)
        self.assertGreater(len(conteudo), 2000)


class TestCoberturaModulosPyInstaller(unittest.TestCase):
    """A v1.0.0 inteira precisa entrar no bundle do PyInstaller.

    Varre os .py reais de core, services, ui, adapters e utils e garante
    que o manifesto gerado pelo build cobre cada um. Também confere que o
    .spec coleta submodules/dados dos cinco pacotes — o equivalente a
    --collect-submodules e --collect-data.
    """

    def setUp(self):
        self.coleta = carregar_modulo_packaging("coleta_interna")
        self.build = ler(PACKAGING / "build_portatil.ps1")
        self.spec = ler(PACKAGING / "assistente.spec")

    def test_manifesto_cobre_todos_os_py_reais(self):
        manifesto = self.coleta.montar_manifesto(RAIZ)

        self.assertEqual(
            manifesto["pacotes"],
            ["core", "services", "ui", "adapters", "utils"],
        )
        self.assertEqual(
            manifesto["modulos_raiz"],
            ["config", "setup_llm"],
        )

        esperados = set()

        for pacote in ("core", "services", "ui", "adapters", "utils"):
            for arquivo in (RAIZ / pacote).rglob("*.py"):
                if "__pycache__" in arquivo.parts:
                    continue

                partes = list(
                    arquivo.relative_to(RAIZ).with_suffix("").parts
                )

                if partes and partes[-1] == "__init__":
                    partes.pop()

                if partes:
                    esperados.add(".".join(partes))

        esperados.update({"config", "setup_llm"})

        self.assertEqual(set(manifesto["modulos"]), esperados)
        self.assertEqual(
            self.coleta.validar_manifesto(manifesto, RAIZ),
            [],
        )

        for modulo in (
            "core.governance",
            "core.context_builder",
            "services.db_service",
            "services.history_db",
            "services.sondagem",
            "services.exportacao_segura",
            "ui.workstation_layout",
            "adapters.spatial_cim",
            "utils.i18n",
            "config",
            "setup_llm",
        ):
            self.assertIn(modulo, manifesto["modulos"])

    def test_build_descreve_a_coleta_dinamica(self):
        for trecho in (
            "coleta_interna.py",
            '"modulos_internos.json"',
            "NEXUSGEO_MODULOS_MANIFEST",
            "--collect-submodules",
            "--collect-data",
            '@("core", "services", "ui", "adapters", "utils")',
        ):
            self.assertIn(trecho, self.build)

        self.assertIn(
            "$env:NEXUSGEO_MODULOS_MANIFEST = $ManifestoModulos",
            self.build,
        )
        self.assertIn(
            "& $PythonExe $ColetaInterna --raiz $Raiz --saida $ManifestoModulos",
            self.build,
        )

    def test_spec_coleta_submodulos_e_dados_dos_cinco_pacotes(self):
        for trecho in (
            'PACOTES_INTERNOS = ("core", "services", "ui", "adapters", "utils")',
            "collect_submodules(pacote)",
            "collect_data_files(pacote)",
            "NEXUSGEO_MODULOS_MANIFEST",
            "_faltantes_do_manifesto",
            '_manifesto_modulos = RAIZ / "build" / "modulos_internos.json"',
            '(str(_manifesto_modulos), ".")',
            '(str(RAIZ / "ui"), "ui")',
            'glob("Modelfile.*")',
        ):
            self.assertIn(trecho, self.spec)

    def test_build_confere_ui_e_finetuning_no_internal(self):
        for trecho in (
            r'"ui\workstation_layout.py"',
            r'"finetuning\Modelfile.nexusgeo-qwen3-4b-v2"',
            '"modulos_internos.json"',
        ):
            self.assertIn(trecho, self.build)

    def test_build_instala_self_test_antes_do_zip(self):
        self.assertIn("smoke_exe.py", self.build)
        self.assertIn("--self-test", self.build)
        self.assertIn("Self-test obrigatorio do executavel", self.build)

        self_test = self.build.index("Self-test obrigatorio do executavel")
        zip_final = self.build.index("Gerando $ZipFinal")

        self.assertLess(self_test, zip_final)


class TestSelfTestExecutavel(unittest.TestCase):
    """O --self-test valida a cadeia inteira sem abrir navegador."""

    def test_argumentos_e_relatorio(self):
        self.assertEqual(launcher_desktop.ARG_SELFTEST, "--self-test")
        self.assertEqual(
            launcher_desktop.ENV_RELATORIO_SELFTEST,
            "ASSISTENTE_SELFTEST_REPORT",
        )

        fonte = ler(RAIZ / "launcher_desktop.py")

        self.assertIn("--self-test", fonte)
        self.assertIn("autodiagnostico", fonte)
        self.assertIn("verificar_modulos_internos", fonte)
        self.assertIn("verificar_banco_sqlite_wal", fonte)
        self.assertIn("verificar_modelo_oficial", fonte)
        self.assertIn("verificar_app_py_dry_run", fonte)

    def test_modulos_internos_do_projeto_inclui_todos_os_pacotes(self):
        nomes = launcher_desktop.modulos_internos_do_projeto(RAIZ)

        for prefixo in ("core.", "services.", "ui.", "adapters.", "utils."):
            self.assertTrue(
                any(nome.startswith(prefixo) for nome in nomes),
                f"nenhum módulo {prefixo}* descoberto",
            )

        self.assertIn("config", nomes)
        self.assertIn("setup_llm", nomes)
        self.assertIn("core.governance", nomes)
        self.assertIn("services.history_db", nomes)

    def test_autodiagnostico_aprova_o_projeto(self):
        pasta = RAIZ / "build" / "_tmp_selftest"
        pasta.mkdir(parents=True, exist_ok=True)

        relatorio = pasta / "self_test.json"

        if relatorio.is_file():
            relatorio.unlink()

        try:
            resultado = launcher_desktop.autodiagnostico(
                relatorio=str(relatorio)
            )

            self.assertTrue(resultado["ok"], resultado["falhas"])
            self.assertTrue(relatorio.is_file())

            dados = json.loads(relatorio.read_text(encoding="utf-8"))

            self.assertTrue(dados["ok"])
            self.assertFalse(dados["congelado"])

            nomes = [
                verificacao["nome"]
                for verificacao in dados["verificacoes"]
            ]

            for nome in (
                "recursos_runtime",
                "modulos_internos",
                "banco_sqlite_wal",
                "modelo_oficial",
                "app_py_dry_run",
                "certificados",
            ):
                self.assertIn(nome, nomes)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_autodiagnostico_nao_altera_o_banco_real(self):
        antes = _db_intocado.capturar()
        resultado = launcher_desktop.autodiagnostico()
        depois = _db_intocado.capturar()

        self.assertTrue(resultado["ok"], resultado["falhas"])
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )

    def test_main_self_test_nao_abre_servidor_nem_setup(self):
        with mock.patch.object(
            launcher_desktop,
            "autodiagnostico",
            return_value={"ok": True, "verificacoes": [], "falhas": []},
        ) as teste, mock.patch.object(
            launcher_desktop, "configuracao_pendente"
        ) as pendente, mock.patch.object(
            launcher_desktop, "iniciar_streamlit"
        ) as streamlit:
            codigo = launcher_desktop.main(["--self-test"])

        self.assertEqual(codigo, 0)
        teste.assert_called_once()
        pendente.assert_not_called()
        streamlit.assert_not_called()

    def test_autodiagnostico_reprovado_devolve_codigo_1(self):
        with mock.patch.object(
            launcher_desktop,
            "autodiagnostico",
            return_value={
                "ok": False,
                "verificacoes": [
                    {"nome": "modulos_internos", "ok": False, "erro": "x"}
                ],
                "falhas": ["modulos_internos: x"],
            },
        ):
            codigo = launcher_desktop.main(["--self-test"])

        self.assertEqual(codigo, 1)

    def test_smoke_exe_valida_relatorio(self):
        modulo = carregar_modulo_packaging("smoke_exe")

        dados = {
            "ok": True,
            "concluido": True,
            "falhas": [],
            "verificacoes": [
                {"nome": nome, "ok": True}
                for nome in (
                    modulo.VERIFICACOES_OBRIGATORIAS
                    + modulo.VERIFICACOES_RECOMENDADAS
                )
            ],
        }

        self.assertEqual(modulo.validar_relatorio(dados), [])

        dados["ok"] = False
        dados["falhas"] = ["core.governance ausente"]

        problemas = modulo.validar_relatorio(dados)

        self.assertTrue(any("ok" in item for item in problemas))
        self.assertTrue(any("core.governance" in item for item in problemas))

    def test_smoke_exe_compila_e_aceita_argumentos(self):
        caminho = PACKAGING / "smoke_exe.py"

        self.assertTrue(caminho.is_file())
        compile(ler(caminho), str(caminho), "exec")

        fonte = ler(caminho)

        for trecho in ("--exe", "--relatorio", "--timeout", "--self-test"):
            self.assertIn(trecho, fonte)


class TestDBIntocado(unittest.TestCase):
    """Guarda real de ``data/nexusgeoia.db`` durante a suíte (D2 -> D3)."""

    def test_ambiente_do_autoteste_e_temporario_e_restaurado(self):
        anterior = os.environ.get("NEXUSGEO_DB_PATH")

        with launcher_desktop.ambiente_autoteste_isolado() as pasta:
            banco = Path(os.environ["NEXUSGEO_DB_PATH"])
            self.assertNotEqual(banco.resolve(), _db_intocado.BANCO_REAL)
            self.assertTrue(str(banco).startswith(str(pasta)))
            self.assertEqual(os.environ["ASSISTENTE_DATA_DIR"], str(pasta))
            self.assertEqual(os.environ["NEXUSGEO_TEST_MODE"], "1")

        self.assertEqual(os.environ.get("NEXUSGEO_DB_PATH"), anterior)

    def test_ambiente_do_modulo_app_restaura_sys_modules(self):
        """O isolamento de ``app`` devolve o estado exato de sys.modules."""

        sentinela = types.ModuleType("app")
        sentinela_sub = types.ModuleType("app.sub")
        anteriores = {
            nome: sys.modules[nome]
            for nome in list(sys.modules)
            if nome == "app" or nome.startswith("app.")
        }

        try:
            # Caso do autoteste em processo limpo (--onedir): nada em
            # sys.modules antes e nada depois.
            with launcher_desktop.ambiente_modulo_app_isolado():
                self.assertNotIn("app", sys.modules)
                sys.modules["app"] = types.ModuleType("app")
                sys.modules["app.sub"] = types.ModuleType("app.sub")

            self.assertNotIn("app", sys.modules)
            self.assertNotIn("app.sub", sys.modules)

            # Caso em que a suíte já importou ``app``: a identidade
            # original é restaurada, sem sobrar o módulo temporário.
            sys.modules["app"] = sentinela
            sys.modules["app.sub"] = sentinela_sub

            with launcher_desktop.ambiente_modulo_app_isolado():
                self.assertNotIn("app", sys.modules)
                self.assertNotIn("app.sub", sys.modules)

            self.assertIs(sys.modules.get("app"), sentinela)
            self.assertIs(sys.modules.get("app.sub"), sentinela_sub)
        finally:
            for nome in [
                nome
                for nome in list(sys.modules)
                if nome == "app" or nome.startswith("app.")
            ]:
                sys.modules.pop(nome, None)

            sys.modules.update(anteriores)

    def test_comparacao_detecta_alteracao_de_hash_e_tamanho(self):
        pasta = RAIZ / "build" / "_tmp_db_intocado"
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / "banco.db"

        try:
            arquivo.write_bytes(b"conteudo-inicial")
            antes = _db_intocado.capturar(arquivo)
            depois = _db_intocado.capturar(arquivo)
            self.assertTrue(
                _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
            )

            arquivo.write_bytes(b"conteudo-alterado")
            alterado = _db_intocado.capturar(arquivo)
            verificacao = _db_intocado.comparar(antes, alterado)
            self.assertFalse(verificacao["intocado"])
            self.assertFalse(verificacao["mesmo_sha256"])
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_guarda_reprova_sem_encerrar_o_processo(self):
        """A falha vira relatório/veredito; o processo termina normalmente."""

        pasta = RAIZ / "build" / "_tmp_db_guard_teste"
        arquivo = pasta / "relatorio.json"
        inicial = _db_intocado._IMPRESSAO_INICIAL
        resultado_anterior = _db_intocado._RESULTADO_FINAL
        pasta.mkdir(parents=True, exist_ok=True)

        try:
            _db_intocado._IMPRESSAO_INICIAL = {
                "caminho": "banco",
                "existe": True,
                "tamanho": 10,
                "sha256": "antes",
            }

            with mock.patch.object(
                _db_intocado,
                "capturar",
                return_value={
                    "caminho": "banco",
                    "existe": True,
                    "tamanho": 11,
                    "sha256": "depois",
                },
            ), mock.patch.object(
                _db_intocado, "PASTA_RELATORIOS", pasta
            ), mock.patch.object(
                _db_intocado, "ARQUIVO_RELATORIO", arquivo
            ), redirect_stdout(io.StringIO()) as saida:
                resultado = _db_intocado.finalizar_guarda(origem="teste")

            self.assertFalse(resultado["intocado"])
            self.assertFalse(resultado["DB_INTOCADO"])
            self.assertTrue(_db_intocado.falha_de_integridade())
            self.assertIn("DB_INTOCADO=False", saida.getvalue())
            self.assertTrue(arquivo.is_file())

            relatorio = json.loads(arquivo.read_text(encoding="utf-8"))
            self.assertFalse(relatorio["intocado"])
            self.assertEqual(relatorio["origem"], "teste")
        finally:
            _db_intocado._IMPRESSAO_INICIAL = inicial
            _db_intocado._RESULTADO_FINAL = resultado_anterior
            shutil.rmtree(pasta, ignore_errors=True)

    def test_guarda_nao_usa_os_exit(self):
        """A finalização da guarda não pode matar o processo à força."""

        codigo = ler(RAIZ / "tests" / "_db_intocado.py")

        self.assertNotIn("os._exit", codigo)
        self.assertIn("atexit.register", codigo)
        self.assertIn("falha_de_integridade", codigo)

    def test_autoteste_nao_altera_o_banco_real(self):
        modulos_app = {
            nome: sys.modules[nome]
            for nome in list(sys.modules)
            if nome == "app" or nome.startswith("app.")
        }
        antes = _db_intocado.capturar()
        resultado = launcher_desktop.autoteste()
        depois = _db_intocado.capturar()

        self.assertTrue(resultado["ok"], resultado["falhas"])
        verificacao = _db_intocado.comparar(antes, depois)
        self.assertTrue(
            verificacao["DB_INTOCADO"],
            verificacao,
        )

        # O import de ``app`` do autoteste não pode deixar módulo
        # residual: o estado de sys.modules precisa ser o mesmo.
        self.assertEqual(
            set(modulos_app),
            {
                nome
                for nome in sys.modules
                if nome == "app" or nome.startswith("app.")
            },
        )

        for nome, modulo in modulos_app.items():
            self.assertIs(sys.modules[nome], modulo)


class TestSmokeTestArtefatos(unittest.TestCase):
    """O smoke test dos artefatos finais cobre zip, exe e instalador."""

    @staticmethod
    def _modulo():
        import importlib.util

        caminho = PACKAGING / "smoke_test_artefatos.py"
        spec = importlib.util.spec_from_file_location(
            "smoke_test_artefatos", caminho
        )
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)

        return modulo

    def test_script_existe_e_compila(self):
        caminho = PACKAGING / "smoke_test_artefatos.py"

        self.assertTrue(caminho.is_file())
        compile(ler(caminho), str(caminho), "exec")

    def test_reconhece_entradas_proibidas(self):
        modulo = self._modulo()

        proibidas = modulo._entradas_proibidas(
            [
                "NexusGeoIA_v1.0.0_Portatil/NexusGeoIA.exe",
                "NexusGeoIA_v1.0.0_Portatil/iniciar.bat",
                "NexusGeoIA_v1.0.0_Portatil/.dsh/estado.json",
                "NexusGeoIA_v1.0.0_Portatil/tests/test_x.py",
                "NexusGeoIA_v1.0.0_Portatil/__pycache__/app.cpython-314.pyc",
                "NexusGeoIA_v1.0.0_Portatil/.env",
                "NexusGeoIA_v1.0.0_Portatil/secrets.toml",
                "NexusGeoIA_v1.0.0_Portatil/estrutura.txt",
                "NexusGeoIA_v1.0.0_Portatil/tmpabc/lixo.txt",
            ]
        )

        # .dsh, tests, __pycache__, .env, secrets.toml, estrutura.txt, tmp*
        self.assertEqual(len(proibidas), 7)

        for entrada in proibidas:
            self.assertNotIn("NexusGeoIA.exe", entrada)

    def test_aprova_zip_limpo(self):
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_zip"
        pasta.mkdir(parents=True, exist_ok=True)

        staging = pasta / "NexusGeoIA_v1.0.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v1.0.0_Portatil.zip"

        try:
            import zipfile

            with zipfile.ZipFile(zip_final, "w") as arquivo:
                for nome in (
                    "NexusGeoIA.exe",
                    "iniciar.bat",
                    "LEIA-ME.txt",
                    "_internal/app.py",
                ):
                    arquivo.writestr(
                        f"NexusGeoIA_v1.0.0_Portatil/{nome}", b"x"
                    )

            falhas = []
            avisos = []
            resultado = modulo.verificar_zip(
                zip_final, staging, falhas, avisos
            )

            self.assertEqual(falhas, [])
            self.assertEqual(resultado["entradas"], 4)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_reprova_zip_sem_a_pasta_internal(self):
        # Sem _internal o NexusGeoIA.exe nao abre: o .zip precisa levar a
        # pasta inteira do pacote --onedir.
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_zip_sem_internal"
        pasta.mkdir(parents=True, exist_ok=True)

        staging = pasta / "NexusGeoIA_v1.0.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v1.0.0_Portatil.zip"

        try:
            import zipfile

            with zipfile.ZipFile(zip_final, "w") as arquivo:
                for nome in ("NexusGeoIA.exe", "iniciar.bat", "LEIA-ME.txt"):
                    arquivo.writestr(
                        f"NexusGeoIA_v1.0.0_Portatil/{nome}", b"x"
                    )

            falhas = []
            avisos = []
            modulo.verificar_zip(zip_final, staging, falhas, avisos)

            self.assertTrue(
                any("_internal" in falha for falha in falhas),
                falhas,
            )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_verifica_o_pacote_onedir(self):
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_onedir"
        pacote = pasta / "NexusGeoIA"
        interna = pacote / "_internal"

        (interna / "prompts").mkdir(parents=True, exist_ok=True)
        (interna / ".streamlit").mkdir(parents=True, exist_ok=True)
        (interna / "certifi").mkdir(parents=True, exist_ok=True)

        try:
            (pacote / "NexusGeoIA.exe").write_bytes(b"MZ" + b"0" * 64)
            (interna / "app.py").write_text("", encoding="utf-8")
            (interna / "prompts" / "system_base.txt").write_text(
                "", encoding="utf-8"
            )
            (interna / ".streamlit" / "config.toml").write_text(
                "", encoding="utf-8"
            )
            (interna / "certifi" / "cacert.pem").write_text(
                "-----BEGIN CERTIFICATE-----",
                encoding="utf-8",
            )

            falhas = []

            with mock.patch.object(modulo, "TAMANHO_MINIMO_MB", 0):
                resultado = modulo.verificar_pacote_onedir(pacote, falhas)

            self.assertEqual(falhas, [])
            self.assertIsNotNone(resultado)
            self.assertIsNotNone(resultado["internal_mb"])
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_reprova_pacote_onedir_sem_cacert_pem(self):
        # Bug 1: sem _internal/certifi/cacert.pem o import de
        # services.llm_service quebra no bundle congelado.
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_onedir_sem_certifi"
        pacote = pasta / "NexusGeoIA"
        interna = pacote / "_internal"

        (interna / "prompts").mkdir(parents=True, exist_ok=True)
        (interna / ".streamlit").mkdir(parents=True, exist_ok=True)

        try:
            (pacote / "NexusGeoIA.exe").write_bytes(b"MZ" + b"0" * 64)
            (interna / "app.py").write_text("", encoding="utf-8")
            (interna / "prompts" / "system_base.txt").write_text(
                "", encoding="utf-8"
            )
            (interna / ".streamlit" / "config.toml").write_text(
                "", encoding="utf-8"
            )

            falhas = []

            with mock.patch.object(modulo, "TAMANHO_MINIMO_MB", 0):
                modulo.verificar_pacote_onedir(pacote, falhas)

            self.assertTrue(
                any("cacert.pem" in falha for falha in falhas),
                falhas,
            )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_ambiente_sem_venv_remove_o_ambiente_do_build(self):
        modulo = self._modulo()

        ambiente = modulo._ambiente_sem_venv(
            {
                "PATH": r"C:\Windows;C:\proj\.venv\Scripts;C:\py\Lib\site-packages",
                "PYTHONPATH": "x",
                "PYTHONHOME": "y",
                "VIRTUAL_ENV": "z",
            }
        )

        self.assertEqual(ambiente["PATH"], r"C:\Windows")

        for chave in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            self.assertNotIn(chave, ambiente)

    def test_smoke_executa_imports_congelados(self):
        codigo = ler(PACKAGING / "smoke_test_artefatos.py")

        for trecho in (
            "--verificar-imports",
            "ASSISTENTE_IMPORTS_REPORT",
            "verificar_imports_congelados",
            "_ambiente_sem_venv",
            "services_llm_service",
            "certifi/cacert.pem",
        ):
            self.assertIn(trecho, codigo)

    def test_reprova_pacote_onedir_sem_internal(self):
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_onedir_incompleto"
        pacote = pasta / "NexusGeoIA"
        pacote.mkdir(parents=True, exist_ok=True)

        try:
            (pacote / "NexusGeoIA.exe").write_bytes(b"MZ" + b"0" * 64)

            falhas = []

            with mock.patch.object(modulo, "TAMANHO_MINIMO_MB", 0):
                modulo.verificar_pacote_onedir(pacote, falhas)

            self.assertTrue(
                any("_internal" in falha for falha in falhas),
                falhas,
            )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_reprova_zip_com_estado_local(self):
        modulo = self._modulo()
        pasta = RAIZ / "build" / "_tmp_smoke_zip_sujo"
        pasta.mkdir(parents=True, exist_ok=True)

        staging = pasta / "NexusGeoIA_v1.0.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v1.0.0_Portatil.zip"

        try:
            import zipfile

            with zipfile.ZipFile(zip_final, "w") as arquivo:
                arquivo.writestr(
                    "NexusGeoIA_v1.0.0_Portatil/NexusGeoIA.exe", b"x"
                )
                arquivo.writestr(
                    "NexusGeoIA_v1.0.0_Portatil/.git/config", b"x"
                )

            falhas = []
            avisos = []
            modulo.verificar_zip(zip_final, staging, falhas, avisos)

            self.assertTrue(falhas)
            self.assertTrue(
                any("proibida" in falha for falha in falhas),
                falhas,
            )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_build_installer_roda_o_smoke_test(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        for trecho in (
            "smoke_test_artefatos.py",
            "Smoke test dos artefatos finais",
            "--dist",
            "-SemSmoke",
            "build\\smoke_artefatos",
        ):
            self.assertIn(trecho, codigo)


class TestScriptsPowerShell(unittest.TestCase):
    """Os dois scripts .ps1 passam pelo parser do PowerShell."""

    @staticmethod
    def _powershell():
        for nome in ("pwsh", "powershell"):
            caminho = shutil.which(nome)

            if caminho:
                return caminho

        return None

    def test_sintaxe_dos_scripts(self):
        interpretador = self._powershell()

        if not interpretador:
            self.skipTest("PowerShell não disponível para validar sintaxe")

        for nome in ("build_portatil.ps1", "build_installer.ps1"):
            caminho = PACKAGING / nome

            comando = (
                "$erros = $null; $tokens = $null; "
                f"[System.Management.Automation.Language.Parser]::ParseFile("
                f"'{caminho}', [ref]$tokens, [ref]$erros) | Out-Null; "
                "if ($erros.Count -gt 0) { "
                "$erros | ForEach-Object { Write-Error $_.Message }; "
                "exit 1 } else { exit 0 }"
            )

            resultado = subprocess.run(
                [
                    interpretador,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    comando,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            self.assertEqual(
                resultado.returncode,
                0,
                f"{nome} tem erro de sintaxe: {resultado.stderr}",
            )

    def test_build_portatil_monta_o_pacote_onedir(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O staging recebe todo o conteudo de dist\NexusGeoIA\
        # (NexusGeoIA.exe + _internal) ao lado de iniciar.bat.
        for trecho in (
            '$PastaApp = Join-Path $Dist $NomeApp',
            '$ExeApp = Join-Path $PastaApp "$NomeApp.exe"',
            '$PastaInterna = Join-Path $PastaApp "_internal"',
            '$StagingInterna = Join-Path $Staging "_internal"',
            "Copy-PastaPublicavel $PastaApp $Staging",
            '"$NomeApp.exe",',
            '"_internal",',
        ):
            self.assertIn(trecho, codigo)

        # O exe legado do modo arquivo unico e removido na limpeza para
        # nao sobrar um binario obsoleto em dist\.
        self.assertIn("$ExeLegado = Join-Path $Dist", codigo)

    def test_build_portatil_valida_recursos_do_internal(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        self.assertIn('"prompts\\system_base.txt"', codigo)
        self.assertIn('".streamlit\\config.toml"', codigo)
        self.assertIn("exclude_binaries", codigo)
        self.assertIn("COLLECT(", codigo)
        self.assertIn('contents_directory', codigo)

    def test_build_portatil_exige_certifi_no_internal(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # Bug 1: o build falha se o cacert.pem do certifi nao chegar ao
        # bundle, em vez de gerar um .exe que so quebra no primeiro uso.
        self.assertIn("collect_data_files", codigo)
        self.assertIn("certifi\\cacert.pem", codigo)
        self.assertGreaterEqual(
            codigo.count('"certifi\\cacert.pem"'),
            2,
            "o certificado deve ser conferido em _internal e no staging",
        )

    def test_build_portatil_preserva_certificado_na_copia_do_internal(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O robocopy excluia "*.pem" e o pacote portatil ficava sem o
        # cacert.pem mesmo com dist\NexusGeoIA\_internal correto.
        self.assertIn("[switch]$ManterCertificados", codigo)
        self.assertIn('$exclusoesArquivo += "*.pem"', codigo)
        self.assertIn(
            "Copy-PastaPublicavel $PastaApp $Staging -ManterCertificados",
            codigo,
        )

    def test_build_portatil_exclui_certificados_do_internal_da_varredura(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # _internal traz CA publicas (certifi\cacert.pem); a varredura de
        # segredos vale para o que publicamos fora dele.
        self.assertIn("$prefixoInterno", codigo)
        self.assertIn("StartsWith(", codigo)
        self.assertIn("cacert.pem", codigo)

    def test_build_portatil_cobre_o_fluxo(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        for trecho in (
            "unittest",
            "tests/test_packaging_offline.py",
            "pyinstaller.exe",
            "--clean",
            "--noconfirm",
            "assistente.spec",
            "launcher_desktop.py",
            "iniciar.bat",
            "setup_llm.py",
            "prompts",
            ".streamlit",
            "Compress-Archive",
            '$ProgressPreference = "SilentlyContinue"',
            "__pycache__",
            "tests",
            ".dsh",
            ".git",
            ".ruff_cache",
            "secrets.toml",
            "estrutura.txt",
            "tmp*",
            "NexusGeoIA_v1.0.0_Portatil",
        ):
            self.assertIn(trecho, codigo)

    def test_build_portatil_valida_max_path(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # Caminho base acima de 100 caracteres dispara aviso: o
        # PyInstaller e a extracao do .zip consomem a margem do MAX_PATH.
        self.assertIn("$LIMITE_CAMINHO_BASE = 100", codigo)
        self.assertIn("$Raiz.Length -gt $LIMITE_CAMINHO_BASE", codigo)
        self.assertIn("MAX_PATH", codigo)
        self.assertIn("Write-Warning", codigo)

    def test_build_portatil_roda_testes_antes_do_pyinstaller(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        testes = codigo.index('"tests/test_packaging_offline.py"')
        pyinstaller = codigo.index('"packaging\\assistente.spec"')

        self.assertLess(
            testes,
            pyinstaller,
            "a suite de empacotamento deve rodar antes do PyInstaller",
        )
        self.assertIn("$SemTestes", codigo)
        self.assertIn("throw", codigo[testes:pyinstaller])

    def test_build_portatil_limpa_temporarios_antes_de_compilar(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        limpeza = codigo.index("Limpando temporarios de builds anteriores")
        compilacao = codigo.index("Compilando o executavel com PyInstaller")

        self.assertLess(
            limpeza,
            compilacao,
            "a limpeza do build anterior deve vir antes do PyInstaller",
        )
        self.assertIn("Remove-PastaSegura", codigo)
        self.assertIn("$WorkPath", codigo)
        self.assertIn("$Staging", codigo)
        self.assertIn("Assert-DentroDoProjeto", codigo)

    def test_build_portatil_le_o_tamanho_do_zip_gerado(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O tamanho da pasta é lido antes da compactação; o do .zip vem
        # sempre do arquivo gerado, depois dela.
        antes = codigo.index("$tamanhoStagingMb =")
        compactacao = codigo.index("$motorZip = Invoke-CompactacaoZip")
        depois = codigo.index("$zipMb = [math]::Round")

        self.assertLess(antes, compactacao)
        self.assertLess(compactacao, depois)
        self.assertIn(
            "(Get-Item -LiteralPath $ZipFinal).Length",
            codigo,
        )

    def test_build_portatil_prefere_tar_com_fallback(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # tar.exe (bsdtar) compacta árvores grandes muito mais rápido que
        # o Compress-Archive do PowerShell 5.1; este último continua
        # disponível como fallback.
        self.assertIn("Get-Command \"tar.exe\"", codigo)
        self.assertIn("-a -c -f", codigo)
        self.assertIn("Compress-Archive -LiteralPath", codigo)

        funcao = codigo[
            codigo.index("function Invoke-CompactacaoZip"):
            codigo.index("$LIMITE_CAMINHO_BASE")
        ]

        self.assertLess(
            funcao.index("Get-Command \"tar.exe\""),
            funcao.index("Compress-Archive -LiteralPath"),
            "o tar.exe deve ser tentado antes do Compress-Archive",
        )

    def test_build_portatil_valida_conteudo_do_zip(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # A extração pelo Explorer precisa da pasta raiz, e nenhum item
        # proibido (estado local, segredos, temporários) pode viajar.
        self.assertIn("ZipFile]::OpenRead", codigo)
        self.assertIn("raizZip", codigo)
        self.assertIn("padroesProibidosZip", codigo)
        self.assertIn("assinaturaZip", codigo)

    def test_leia_me_e_bilingue(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O mesmo .zip serve aos dois idiomas da interface: o LEIA-ME.txt
        # traz o bloco PT-BR e o bloco EN.
        self.assertIn("pacote portatil", codigo)
        self.assertIn("portable package (English)", codigo)
        self.assertIn("Run iniciar.bat.", codigo)

        posicao_pt = codigo.index("pacote portatil")
        posicao_en = codigo.index("portable package (English)")

        self.assertLess(
            posicao_pt,
            posicao_en,
            "a versão em inglês vem logo abaixo da portuguesa",
        )

    def test_build_portatil_valida_iniciar_bat(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O build falha se o iniciar.bat perder o executavel portatil, a
        # pasta de dados ou o caminho de desenvolvimento (navegador e
        # porta dinamica).
        self.assertIn("NexusGeoIA\\.exe", codigo)
        self.assertIn("ASSISTENTE_DATA_DIR", codigo)
        self.assertIn("--server\\.headless=false", codigo)
        self.assertIn("--server\\.port=%PORTA%", codigo)

    def test_build_installer_cobre_o_fluxo(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        for trecho in (
            "PyInstaller",
            "build_portatil.ps1",
            "assistente.spec",
            "installer.iss",
            "Find-Iscc",
            "NexusGeoIA_v1.0.0_Setup.exe",
            "NexusGeoIA.exe",
            "SemPortatil",
            "ExigirInno",
        ):
            self.assertIn(trecho, codigo)

    def test_build_installer_repassa_parametros_por_hashtable(self):
        # No PowerShell 5.1 o splat de ARRAY entrega os elementos como
        # argumentos posicionais: "-Limpar" virava o valor de -PythonExe e
        # o build portatil abortava com "Python nao encontrado".
        codigo = ler(PACKAGING / "build_installer.ps1")
        trecho = codigo[
            codigo.index("$parametrosPortatil = @{"):
            codigo.index("& $BuildPortatil")
        ]

        self.assertIn('$parametrosPortatil["PythonExe"]', trecho)
        self.assertIn('$parametrosPortatil["Limpar"]', trecho)
        self.assertNotIn("@argumentosPortatil", codigo)

    def test_build_installer_empacota_o_pacote_onedir(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        for trecho in (
            '$PastaApp = Join-Path $Dist $NomeApp',
            '$ExeApp = Join-Path $PastaApp "$NomeApp.exe"',
            "recursesubdirs",
            "createallsubdirs",
            "_internal",
        ):
            self.assertIn(trecho, codigo)

    def test_build_installer_confere_versao_e_caminhos(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        # A versao do config.py precisa bater com o installer.iss e o
        # executavel embutido precisa ser o mesmo publicado pelo build
        # portatil; o script falha antes de rodar o ISCC quando nao bate.
        self.assertIn("$ConteudoIss.Contains('#define MyAppVersion", codigo)
        self.assertIn("OutputBaseFilename=", codigo)
        self.assertIn('Source: "..\\dist\\', codigo)

    def test_build_installer_exige_instalacao_sem_uac(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        # O script recusa o .iss com PrivilegesRequired=admin e exige
        # lowest + override por dialogo + DefaultDirName em autopf.
        self.assertIn(
            "PrivilegesRequired\\s*=\\s*admin",
            codigo,
        )
        self.assertIn(
            "PrivilegesRequired\\s*=\\s*lowest",
            codigo,
        )
        self.assertIn(
            "PrivilegesRequiredOverridesAllowed\\s*=\\s*dialog",
            codigo,
        )
        self.assertIn("DefaultDirName\\s*=", codigo)

    def test_build_installer_instala_por_usuario_sem_uac(self):
        codigo = ler(PACKAGING / "build_installer.ps1")

        # Mensagem de erro e regex precisam citar as duas diretivas.
        self.assertIn("PrivilegesRequired=lowest", codigo)
        self.assertIn("PrivilegesRequiredOverridesAllowed=dialog", codigo)

    def test_build_portatil_confere_dados_do_rapidocr(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O script precisa documentar e conferir os dados do RapidOCR: o
        # requisito original pede --collect-data rapidocr. A flag nao viaja
        # na linha de comando porque o PyInstaller rejeita opcoes de
        # "makespec" quando um .spec e fornecido; a coleta efetiva fica no
        # assistente.spec (verificado abaixo).
        self.assertIn("--collect-data rapidocr", codigo)
        self.assertIn("rapidocr_onnxruntime", codigo)
        self.assertIn("collect_data_files", codigo)

        spec = ler(PACKAGING / "assistente.spec")
        self.assertIn('collect_data_files("rapidocr")', spec)
        self.assertIn('collect_data_files("rapidocr_onnxruntime")', spec)

    def test_iniciar_bat_usa_python_embarcado_e_setup(self):
        codigo = ler(RAIZ / "iniciar.bat")

        self.assertIn(r"python\python.exe", codigo)
        self.assertIn(r".venv\Scripts\python.exe", codigo)
        self.assertIn("setup_llm.py", codigo)
        self.assertIn("-m streamlit run", codigo)
        self.assertIn("--forcar", codigo)

    def test_iniciar_bat_abre_o_navegador_na_porta_escolhida(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # Caminho de desenvolvimento (sem NexusGeoIA.exe): quem abre a
        # aba e o proprio Streamlit, na porta dinamica escolhida.
        self.assertIn("--server.headless=false", codigo)
        self.assertIn("--server.port=%PORTA%", codigo)
        self.assertIn("http://localhost:%PORTA%", codigo)

    def test_iniciar_bat_abre_o_navegador_do_executavel_portatil(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # O executavel e compilado com console=False: no processo sem
        # console o Shell do Windows ignora os.startfile() em silencio e
        # a aba nunca abre. Quem abre a aba, no pacote portatil, e o
        # iniciar.bat (console visivel), lendo instancia_ativa.json.
        self.assertIn(
            'set "REGISTRO_INSTANCIA=%~dp0instancia_ativa.json"',
            codigo,
        )
        self.assertIn(":aguardar_registro", codigo)
        self.assertIn("if %TENTATIVAS_REGISTRO% GEQ 30", codigo)
        self.assertIn("ConvertFrom-Json", codigo)
        self.assertIn(".porta", codigo)
        self.assertIn('set "PORTA=8501"', codigo)
        self.assertIn('start "" "http://localhost:%PORTA%"', codigo)

        # O registro e gravado antes do import do Streamlit: o .bat so
        # abre a URL quando o socket da porta responde, e nunca antes de
        # o registro aparecer.
        self.assertIn(":aguardar_porta", codigo)
        self.assertIn("ConnectAsync", codigo)

        posicao_registro = codigo.index(
            'if exist "%REGISTRO_INSTANCIA%" goto :abrir_navegador'
        )
        posicao_start = codigo.index('start "" "http://localhost:%PORTA%"')

        self.assertLess(posicao_registro, posicao_start)

    def test_iniciar_bat_remove_registro_obsoleto_antes_de_iniciar(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # O registro so e apagado quando nenhum NexusGeoIA.exe esta
        # ativo: com instancia viva o arquivo e a fonte da porta dela.
        self.assertIn(":existe_executavel_ativo", codigo)
        self.assertIn("tasklist", codigo)
        self.assertIn('del /q "%REGISTRO_INSTANCIA%"', codigo)

        posicao_checagem = codigo.index("call :existe_executavel_ativo")
        posicao_start = codigo.index('start "" /B "%EXE_PATH%" %*')

        self.assertLess(posicao_checagem, posicao_start)

    def test_iniciar_bat_acompanha_o_servidor_ate_encerrar(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # Depois de abrir a aba, o .bat espera o servidor terminar
        # (registro removido ou processo morto) e encerra limpo, sem
        # deixar a janela do console aberta.
        self.assertIn(":aguardar_servidor", codigo)
        self.assertIn(
            'if not exist "%REGISTRO_INSTANCIA%" goto :executavel_encerrado',
            codigo,
        )
        self.assertIn(":executavel_encerrado", codigo)

    def test_iniciar_bat_nao_abre_navegador_nos_modos_diagnosticos(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # --self-test (usado pelo smoke_exe.py) e os demais modos de
        # diagnostico nao sobem servidor: rodam de forma sincrona, sem
        # esperar registro e sem abrir navegador.
        self.assertIn(
            'if /I "%~1"=="--self-test" goto :executavel_sincrono',
            codigo,
        )
        self.assertIn(":executavel_sincrono", codigo)

        posicao_self_test = codigo.index('"%~1"=="--self-test"')
        posicao_start = codigo.index('start "" /B "%EXE_PATH%" %*')
        posicao_navegador = codigo.index('start "" "http://localhost:%PORTA%"')

        self.assertLess(posicao_self_test, posicao_start)
        self.assertLess(posicao_self_test, posicao_navegador)

    def test_iniciar_bat_escolhe_a_primeira_porta_livre(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # Porta preferida e faixa de busca (8501..8510) declaradas.
        self.assertIn('set "PORTA=8501"', codigo)
        self.assertIn("range(8501,8511)", codigo)
        self.assertIn("127.0.0.1", codigo)
        self.assertIn("socket", codigo)

    def test_iniciar_bat_nao_usa_mais_porta_fixa(self):
        codigo = ler(RAIZ / "iniciar.bat")

        self.assertNotIn("--server.port=8501", codigo)

    def test_iniciar_bat_inclui_ollama_no_path(self):
        codigo = ler(RAIZ / "iniciar.bat")

        self.assertIn(
            r"%LOCALAPPDATA%\Programs\Ollama",
            codigo,
        )
        self.assertIn(
            r"%ProgramFiles%\Ollama",
            codigo,
        )

    def test_iniciar_bat_abre_o_executavel_portatil(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # O pacote portatil traz o carregador onedir (NexusGeoIA.exe +
        # _internal) ao lado do .bat: quando o .exe esta presente, ele
        # tem prioridade sobre python\ e .venv, e os dados ficam na
        # propria pasta do pacote.
        self.assertIn('if exist "%~dp0NexusGeoIA.exe"', codigo)
        self.assertIn("goto :iniciar_executavel", codigo)
        self.assertIn(":iniciar_executavel", codigo)
        self.assertIn("ASSISTENTE_DATA_DIR", codigo)

        posicao_exe = codigo.index('if exist "%~dp0NexusGeoIA.exe"')
        posicao_python = codigo.index('set "PYTHON="')

        self.assertLess(
            posicao_exe,
            posicao_python,
            "o executavel portatil deve ser testado antes do Python",
        )

        # O desvio por goto evita ler %ERRORLEVEL% na leitura do bloco.
        posicao_label = codigo.index("\n:iniciar_executavel")
        posicao_erro = codigo.index("set \"CODIGO_SAIDA=%ERRORLEVEL%\"", posicao_label)

        self.assertLess(posicao_label, posicao_erro)


class TestModulosDaReleaseNoPacote(unittest.TestCase):
    r"""Gate 3: .streamlit, ui\ e finetuning\Modelfile.* viajam na release.

    O porte da v1.0.0 passou a publicar .streamlit\config.toml (tema
    escuro), os modulos de apresentacao (ui\, inclusive
    workstation_layout.py) e os templates do modelo proprio
    (finetuning\Modelfile.*). O pacote --onedir e a fonte unica: o
    staging do portatil herda a pasta publicada e o instalador embute
    dist\NexusGeoIA\* recursivamente.
    """

    def setUp(self):
        self.portatil = ler(PACKAGING / "build_portatil.ps1")
        self.installer = ler(PACKAGING / "build_installer.ps1")

    def test_arquivos_da_release_existem_no_repositorio(self):
        for relativo in (
            ".streamlit/config.toml",
            "ui/__init__.py",
            "ui/workstation_layout.py",
            "finetuning/Modelfile.nexusgeo-qwen3-4b-v2",
        ):
            self.assertTrue((RAIZ / relativo).is_file(), relativo)

        # ui/ e finetuning/Modelfile.* sao copiados por inteiro (o
        # Modelfile -q4 e opcional, mas existe nesta release).
        self.assertGreaterEqual(len(list((RAIZ / "ui").glob("*.py"))), 6)
        self.assertTrue(
            (RAIZ / "finetuning" / "Modelfile.nexusgeo-qwen3-4b-v2-q4").is_file()
        )

    def test_build_portatil_copia_os_modulos_para_o_pacote(self):
        for trecho in (
            "function Copy-ModulosDeDistribuicao",
            'Copy-PastaPublicavel (Join-Path $Raiz "ui")',
            '(Join-Path $Destino "ui")',
            'Join-Path "finetuning" $modelfile',
            '"Modelfile.nexusgeo-qwen3-4b-v2"',
            '"Modelfile.nexusgeo-qwen3-4b-v2-q4"',
            "Copy-ModulosDeDistribuicao $PastaApp",
        ):
            self.assertIn(trecho, self.portatil)

        # A copia precisa acontecer antes do staging herdar a pasta
        # publicada; senao ui\ e finetuning\ ficariam de fora do .zip.
        copia = self.portatil.index("Copy-ModulosDeDistribuicao $PastaApp")
        staging = self.portatil.index("Copy-PastaPublicavel $PastaApp $Staging")

        self.assertLess(
            copia,
            staging,
            "os modulos devem ser copiados antes do staging do portatil",
        )

    def test_build_portatil_valida_os_modulos_na_montagem(self):
        trecho = self.portatil[
            self.portatil.index("$conteudoEsperado = @("):
            self.portatil.index("foreach ($item in $conteudoEsperado)")
        ]

        for item in ('"ui",', '"finetuning"', '".streamlit",'):
            self.assertIn(item, trecho)

        # models\ so entra na montagem quando o GGUF foi embutido.
        self.assertIn('$conteudoEsperado += "models"', self.portatil)

        for validacao in (
            'Join-Path "ui" "workstation_layout.py"',
            'Join-Path "ui" "__init__.py"',
            'Join-Path ".streamlit" "config.toml"',
            "$ModelfilesNexusGeo",
        ):
            self.assertIn(validacao, self.portatil)

    def test_build_portatil_exige_os_arquivos_antes_de_compilar(self):
        # Sem .streamlit\config.toml, ui\workstation_layout.py ou o
        # Modelfile principal o build para antes do PyInstaller.
        for trecho in (
            'Assert-Arquivo (Join-Path $Raiz ".streamlit\\config.toml")',
            'Assert-Arquivo (Join-Path $Raiz "ui\\workstation_layout.py")',
            'Assert-Arquivo (Join-Path $Raiz "finetuning\\$ModelfilePrincipal")',
        ):
            self.assertIn(trecho, self.portatil)

    def test_build_installer_inclui_e_confere_os_modulos(self):
        for trecho in (
            "function Copy-ModuloPublicavel",
            'Copy-ModuloPublicavel (Join-Path $Raiz "ui")',
            '"Modelfile.nexusgeo-qwen3-4b-v2"',
            '"Modelfile.nexusgeo-qwen3-4b-v2-q4"',
            'Join-Path "ui" "workstation_layout.py"',
            "_internal\\.streamlit\\config.toml",
            "recursesubdirs",
            "Conferindo .streamlit, ui e finetuning no pacote onedir",
        ):
            self.assertIn(trecho, self.installer)


class TestFlagIncludeCustomGGUF(unittest.TestCase):
    """-IncludeCustomGGUF e opt-in e o pacote padrao continua leve.

    Os testes de comportamento extraem as funcoes de GGUF do proprio
    build_portatil.ps1 e as executam sobre um arquivo mock leve (~1 KB):
    nenhum GGUF real de ~2,5 GB e copiado.
    """

    NOME = "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
    CACHE = r"D:\hf_cache"

    def setUp(self):
        self.codigo = ler(PACKAGING / "build_portatil.ps1")

    @staticmethod
    def _powershell():
        for nome in ("pwsh", "powershell"):
            caminho = shutil.which(nome)

            if caminho:
                return caminho

        return None

    @staticmethod
    def _extrair_funcoes(codigo):
        partes = []

        for nome in ("Resolve-GgufCustom", "Copy-GgufCustomParaPacote"):
            inicio = codigo.index(f"function {nome}")
            fim = codigo.index("\n}\n", inicio) + 3
            partes.append(codigo[inicio:fim])

        return "\n".join(partes)

    def _executar_copia(self, interpretador, raiz, cache, pacote):
        script = raiz / "copia_gguf.ps1"
        script.write_text(
            self._extrair_funcoes(self.codigo)
            + "\n$destino = Copy-GgufCustomParaPacote"
            + f" -RaizProjeto '{raiz}'"
            + f" -CacheAlternativo '{cache}'"
            + f" -NomeArquivo '{self.NOME}'"
            + f" -Pacote '{pacote}'\n"
            + "Write-Output $destino\n",
            encoding="utf-8",
        )

        return subprocess.run(
            [
                interpretador,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_parametro_switch_documentado(self):
        parametros = self.codigo[
            self.codigo.index("param("):
            self.codigo.index("$ErrorActionPreference")
        ]

        self.assertIn("[switch]$IncludeCustomGGUF", parametros)
        self.assertIn(".PARAMETER IncludeCustomGGUF", self.codigo)

    def test_procura_no_projeto_e_no_cache_hf(self):
        self.assertIn(self.NOME, self.codigo)
        self.assertIn(self.CACHE, self.codigo)
        self.assertIn(
            'Join-Path (Join-Path $RaizProjeto "models") $NomeArquivo',
            self.codigo,
        )
        self.assertIn(
            "Join-Path $CacheAlternativo $NomeArquivo",
            self.codigo,
        )

    def test_sem_a_flag_o_pacote_continua_leve(self):
        marcador = "if ($IncludeCustomGGUF) {"
        self.assertIn(marcador, self.codigo)

        bloco = self.codigo[self.codigo.index(marcador):]
        bloco = bloco[:bloco.index("\nelse {")]

        # A copia so existe dentro do bloco da flag; o caminho padrao
        # apenas informa que o GGUF nao foi embutido.
        chamada = "$ggufDestino = Copy-GgufCustomParaPacote"

        self.assertIn(chamada, bloco)
        self.assertNotIn(
            chamada,
            self.codigo[:self.codigo.index(marcador)],
        )
        self.assertIn("nao embutido", self.codigo)
        self.assertIn("-IncludeCustomGGUF", self.codigo)

    def test_copia_arquivo_mock_leve_do_projeto(self):
        interpretador = self._powershell()

        if not interpretador:
            self.skipTest("PowerShell nao disponivel para executar a copia")

        pasta = RAIZ / "build" / "_tmp_gguf_portatil"
        projeto = pasta / "projeto"
        cache = pasta / "hf_cache"
        pacote = pasta / "pacote"

        try:
            (projeto / "models").mkdir(parents=True, exist_ok=True)
            cache.mkdir(parents=True, exist_ok=True)
            pacote.mkdir(parents=True, exist_ok=True)

            origem = projeto / "models" / self.NOME
            origem.write_bytes(b"GGUF" + b"\0" * 1021)

            resultado = self._executar_copia(
                interpretador, projeto, cache, pacote
            )

            self.assertEqual(resultado.returncode, 0, resultado.stderr)

            destino = pacote / "models" / self.NOME

            self.assertTrue(destino.is_file())
            self.assertEqual(destino.read_bytes(), origem.read_bytes())
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_cai_para_o_cache_quando_o_projeto_nao_tem_o_gguf(self):
        interpretador = self._powershell()

        if not interpretador:
            self.skipTest("PowerShell nao disponivel para executar a copia")

        pasta = RAIZ / "build" / "_tmp_gguf_cache"
        projeto = pasta / "projeto"
        cache = pasta / "hf_cache"
        pacote = pasta / "pacote"

        try:
            (projeto / "models").mkdir(parents=True, exist_ok=True)
            cache.mkdir(parents=True, exist_ok=True)
            pacote.mkdir(parents=True, exist_ok=True)

            origem = cache / self.NOME
            origem.write_bytes(b"GGUF" + b"\0" * 1021)

            resultado = self._executar_copia(
                interpretador, projeto, cache, pacote
            )

            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertTrue((pacote / "models" / self.NOME).is_file())
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_interrompe_sem_o_gguf_com_mensagem_clara(self):
        interpretador = self._powershell()

        if not interpretador:
            self.skipTest("PowerShell nao disponivel para executar a copia")

        pasta = RAIZ / "build" / "_tmp_gguf_ausente"
        projeto = pasta / "projeto"
        cache = pasta / "hf_cache"
        pacote = pasta / "pacote"

        try:
            (projeto / "models").mkdir(parents=True, exist_ok=True)
            cache.mkdir(parents=True, exist_ok=True)
            pacote.mkdir(parents=True, exist_ok=True)

            resultado = self._executar_copia(
                interpretador, projeto, cache, pacote
            )

            self.assertNotEqual(resultado.returncode, 0)
            self.assertIn("GGUF", resultado.stderr)
            self.assertIn("-IncludeCustomGGUF", resultado.stderr)
            self.assertFalse((pacote / "models" / self.NOME).exists())
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


class TestCertificadosTls(unittest.TestCase):
    """Bug 1: o ``certifi/cacert.pem`` precisa existir e ser usado.

    A cadeia do erro real foi ``app`` -> ``core.assistant`` ->
    ``core.smart_router`` -> ``services.llm_service`` -> ``ollama`` ->
    ``httpx`` -> ``ssl.create_default_context``. O bundle não levava o
    ``cacert.pem`` e o ``.exe`` quebrava no boot com FileNotFoundError.
    """

    def setUp(self):
        self.spec = ler(PACKAGING / "assistente.spec")
        self.launcher = ler(RAIZ / "launcher_desktop.py")
        self.app = ler(RAIZ / "app.py")

    def test_spec_coleta_o_certifi_com_collect_data_files(self):
        self.assertIn("collect_data_files('certifi')", self.spec)
        self.assertIn("collect_data_files(\"certifi\")", self.spec)
        self.assertIn("dados_certifi", self.spec)
        self.assertIn("datas += dados_certifi", self.spec)
        self.assertIn("certifi/cacert.pem", self.spec)

    def test_spec_inclui_a_cadeia_de_boot_do_llm(self):
        for modulo in (
            "ollama",
            "httpx",
            "httpcore",
            "pydantic",
            "pydantic_core",
            "pypdf",
            "docx",
            "services.llm_service",
            "core.smart_router",
            "core.assistant",
        ):
            self.assertIn(f'"{modulo}"', self.spec, modulo)

    def test_launcher_configura_ssl_cert_file_antes_do_config(self):
        for trecho in (
            "configurar_certificados",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "VARIAVEIS_CERTIFICADO",
            "certifi.where()",
        ):
            self.assertIn(trecho, self.launcher)

        posicao_certificado = self.launcher.index(
            "CAMINHO_CERTIFICADOS = configurar_certificados()"
        )
        posicao_config = self.launcher.index("\nimport config\n")

        self.assertLess(
            posicao_certificado,
            posicao_config,
            "o certificado precisa ser configurado antes de import config",
        )

    def test_app_configura_ssl_cert_file_antes_de_core_e_services(self):
        for trecho in (
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "_CAMINHO_CERTIFICADOS",
            'import_module("certifi")',
        ):
            self.assertIn(trecho, self.app)

        posicao_certificado = self.app.index("_CAMINHO_CERTIFICADOS = str(")
        posicao_config = self.app.index("from config import APP_NAME")
        posicao_llm = self.app.index("from services.llm_service import")

        self.assertLess(posicao_certificado, posicao_config)
        self.assertLess(posicao_certificado, posicao_llm)

    def test_configurar_certificados_corrige_caminho_invalido(self):
        import certifi

        esperado = str(certifi.where())

        with mock.patch.dict(
            os.environ,
            {
                "SSL_CERT_FILE": r"C:\inexistente\cacert.pem",
                "REQUESTS_CA_BUNDLE": "",
            },
            clear=False,
        ):
            caminho = launcher_desktop.configurar_certificados()

            self.assertEqual(caminho, esperado)
            self.assertEqual(os.environ["SSL_CERT_FILE"], esperado)
            self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], esperado)

    def test_configurar_certificados_preserva_caminho_valido(self):
        pasta = RAIZ / "build" / "_tmp_certificado"
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / "ca.pem"

        try:
            arquivo.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "SSL_CERT_FILE": str(arquivo),
                    "REQUESTS_CA_BUNDLE": str(arquivo),
                },
                clear=False,
            ):
                launcher_desktop.configurar_certificados()

                self.assertEqual(os.environ["SSL_CERT_FILE"], str(arquivo))
                self.assertEqual(
                    os.environ["REQUESTS_CA_BUNDLE"],
                    str(arquivo),
                )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_verificar_certificados_abre_o_contexto_ssl(self):
        resultado = launcher_desktop.verificar_certificados()

        self.assertTrue(Path(resultado["certifi"]).is_file())
        self.assertTrue(
            Path(resultado["ssl_cert_file"]).is_file()
        )
        self.assertTrue(
            Path(resultado["requests_ca_bundle"]).is_file()
        )


class TestJobObjectEEncerramento(unittest.TestCase):
    """Bug 2: o servidor não pode ficar órfão ao fechar o launcher."""

    def setUp(self):
        self.codigo = ler(RAIZ / "launcher_desktop.py")

    def test_job_object_usa_kill_on_job_close(self):
        for trecho in (
            "JobObjectWindows",
            "CreateJobObjectW",
            "SetInformationJobObject",
            "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
            "AssignProcessToJobObject",
            "class _ExtendedLimitInformation",
        ):
            self.assertIn(trecho, self.codigo)

    def test_registra_handlers_de_encerramento(self):
        for trecho in (
            "SetConsoleCtrlHandler",
            "AttachConsole",
            "anexar_console_pai",
            "atexit.register",
            "taskkill",
            "/F",
            "/T",
            "/PID",
            "encerrar_arvore_processos",
            "_limpar_servidor",
        ):
            self.assertIn(trecho, self.codigo)

    def test_anexa_ao_console_do_iniciar_bat(self):
        if os.name != "nt":
            self.skipTest("AttachConsole é específico do Windows")

        with mock.patch.object(
            launcher_desktop.ctypes, "windll", create=True
        ) as windll:
            windll.kernel32.GetConsoleWindow.return_value = 0
            windll.kernel32.AttachConsole.return_value = 1

            self.assertTrue(launcher_desktop.anexar_console_pai())

        windll.kernel32.AttachConsole.assert_called_once_with(-1)

    def test_anexar_console_sem_pai_nao_levanta(self):
        if os.name != "nt":
            self.skipTest("AttachConsole é específico do Windows")

        with mock.patch.object(
            launcher_desktop.ctypes, "windll", create=True
        ) as windll:
            windll.kernel32.GetConsoleWindow.return_value = 0
            windll.kernel32.AttachConsole.return_value = 0

            self.assertFalse(launcher_desktop.anexar_console_pai())

    def test_job_object_real_pode_ser_criado_e_fechado(self):
        if os.name != "nt":
            self.skipTest("Job Object é específico do Windows")

        job = launcher_desktop.JobObjectWindows()

        self.assertTrue(job.criar(), job.motivo)
        self.assertTrue(job.ativo)

        job.fechar()

        self.assertFalse(job.ativo)

    def test_encerrar_arvore_usa_taskkill_no_windows(self):
        class ProcessoFalso:
            pid = 1234

            def poll(self):
                return 0

        with mock.patch.object(
            launcher_desktop.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as executar:
            resultado = launcher_desktop.encerrar_arvore_processos(
                pid=1234,
                processo=ProcessoFalso(),
            )

        self.assertTrue(resultado)

        if os.name == "nt":
            comando = executar.call_args.args[0]

            self.assertEqual(
                comando[:4],
                ["taskkill", "/F", "/T", "/PID"],
            )
            self.assertIn("check", executar.call_args.kwargs)

    def test_limpar_servidor_e_idempotente(self):
        processo = mock.Mock()
        processo.pid = 4242
        job = mock.Mock()

        launcher_desktop._SERVIDOR["processo"] = processo
        launcher_desktop._SERVIDOR["job"] = job

        try:
            with mock.patch.object(
                launcher_desktop, "encerrar_arvore_processos"
            ) as encerrar, mock.patch.object(
                launcher_desktop, "_remover_registro_instancia"
            ) as remover:
                launcher_desktop._limpar_servidor()
                launcher_desktop._limpar_servidor()
        finally:
            launcher_desktop._SERVIDOR["processo"] = None
            launcher_desktop._SERVIDOR["job"] = None

        encerrar.assert_any_call(4242, processo)
        self.assertEqual(encerrar.call_count, 2)
        job.fechar.assert_called_once_with()
        remover.assert_called()

    def test_registrar_limpeza_instala_atexit_e_console_handler(self):
        with mock.patch.object(
            launcher_desktop.atexit, "register"
        ) as registrar, mock.patch.object(
            launcher_desktop.ctypes, "windll", create=True
        ) as windll:
            launcher_desktop._ENCERRAMENTO_REGISTRADO = False
            launcher_desktop._HANDLER_CONSOLE = None

            try:
                launcher_desktop.registrar_limpeza_encerramento()
            finally:
                launcher_desktop._ENCERRAMENTO_REGISTRADO = True

        registrar.assert_called_once_with(launcher_desktop._limpar_servidor)

        if os.name == "nt":
            windll.kernel32.SetConsoleCtrlHandler.assert_called_once()


class TestInstanciaUnica(unittest.TestCase):
    """Uma segunda abertura reaproveita a instância saudável."""

    def setUp(self):
        self.codigo = ler(RAIZ / "launcher_desktop.py")

    def test_detecta_instancia_por_registro(self):
        with mock.patch.object(
            launcher_desktop,
            "_ler_registro_instancia",
            return_value=8504,
        ), mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=True,
        ), mock.patch.object(
            launcher_desktop,
            "pagina_do_aplicativo",
            return_value=True,
        ):
            self.assertEqual(launcher_desktop.instancia_ativa(), 8504)

    def test_detecta_instancia_na_faixa_de_portas(self):
        with mock.patch.object(
            launcher_desktop,
            "_ler_registro_instancia",
            return_value=None,
        ), mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            side_effect=lambda porta, *_: porta == 8503,
        ), mock.patch.object(
            launcher_desktop,
            "pagina_do_aplicativo",
            return_value=True,
        ):
            self.assertEqual(launcher_desktop.instancia_ativa(), 8503)

    def test_sem_instancia_devolve_none(self):
        with mock.patch.object(
            launcher_desktop,
            "_ler_registro_instancia",
            return_value=None,
        ), mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=False,
        ):
            self.assertIsNone(launcher_desktop.instancia_ativa())

    def test_ignora_healthcheck_que_nao_e_streamlit(self):
        with mock.patch.object(
            launcher_desktop,
            "_ler_registro_instancia",
            return_value=8504,
        ), mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=True,
        ), mock.patch.object(
            launcher_desktop,
            "pagina_do_aplicativo",
            return_value=False,
        ):
            self.assertIsNone(launcher_desktop.instancia_ativa())

    def test_registro_da_instancia_em_disco(self):
        pasta = RAIZ / "build" / "_tmp_registro_instancia"
        pasta.mkdir(parents=True, exist_ok=True)

        try:
            with mock.patch.object(
                launcher_desktop,
                "DIRETORIO_DADOS",
                pasta,
            ):
                self.assertTrue(
                    launcher_desktop._gravar_registro_instancia(8504)
                )
                self.assertEqual(
                    launcher_desktop._ler_registro_instancia(),
                    8504,
                )

                launcher_desktop._remover_registro_instancia()

                self.assertIsNone(
                    launcher_desktop._ler_registro_instancia()
                )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_segunda_abertura_nao_sobe_servidor(self):
        with mock.patch.object(
            launcher_desktop, "instancia_ativa", return_value=8504
        ), mock.patch.object(
            launcher_desktop, "abrir_instancia_existente"
        ) as abrir, mock.patch.object(
            launcher_desktop, "iniciar_streamlit"
        ) as servidor, mock.patch.object(
            launcher_desktop, "executar_setup"
        ) as setup:
            codigo = launcher_desktop.main([])

        self.assertEqual(codigo, 0)
        abrir.assert_called_once_with(8504)
        servidor.assert_not_called()
        setup.assert_not_called()

    def test_nova_instancia_ignora_a_existente(self):
        with mock.patch.object(
            launcher_desktop, "instancia_ativa", return_value=8504
        ) as ativa, mock.patch.object(
            launcher_desktop, "configuracao_pendente", return_value=False
        ), mock.patch.object(
            launcher_desktop, "_encontrar_porta_livre", return_value=8501
        ), mock.patch.object(
            launcher_desktop, "iniciar_streamlit", return_value=0
        ) as servidor:
            codigo = launcher_desktop.main(["--nova-instancia"])

        self.assertEqual(codigo, 0)
        ativa.assert_not_called()
        servidor.assert_called_once_with(8501)

    def test_codigo_mostra_o_fluxo_de_instancia_unica(self):
        for trecho in (
            "instancia_ativa(",
            "abrir_instancia_existente(",
            "ARG_NOVA_INSTANCIA",
            "NOME_ARQUIVO_INSTANCIA",
            "instancia_ativa.json",
        ):
            self.assertIn(trecho, self.codigo)


class TestBotaoEncerrarServidor(unittest.TestCase):
    """Ação discreta na barra lateral para fechar tudo pela página web."""

    def setUp(self):
        self.app = ler(RAIZ / "app.py")
        # A D1 moveu a ação para ui/sidebar.py; o app.py apenas delega.
        self.sidebar = ler(RAIZ / "ui" / "sidebar.py")
        self.i18n = ler(RAIZ / "utils" / "i18n.py")

    def test_app_tem_acao_de_encerrar(self):
        self.assertIn(
            "ui_sidebar.renderizar_botao_encerramento()",
            self.app,
        )

        for trecho in (
            't("encerrar_servidor")',
            't("ajuda_encerrar_servidor")',
            't("aviso_encerrando_servidor")',
            "st.stop()",
        ):
            self.assertIn(trecho, self.sidebar)

        # O botão fica dentro da barra lateral, depois do rodapé.
        posicao_sidebar = self.app.index("with st.sidebar:")
        posicao_botao = self.app.index(
            "ui_sidebar.renderizar_botao_encerramento()"
        )

        self.assertLess(posicao_sidebar, posicao_botao)

    def test_textos_existem_nos_dois_idiomas(self):
        from utils.i18n import TEXTOS_I18N, t

        for chave in (
            "encerrar_servidor",
            "ajuda_encerrar_servidor",
            "aviso_encerrando_servidor",
        ):
            self.assertIn(chave, TEXTOS_I18N["pt"])
            self.assertIn(chave, TEXTOS_I18N["en"])
            self.assertNotEqual(t(chave, "pt"), t(chave, "en"))

    def test_encerrar_streamlit_usa_a_api_do_runtime(self):
        # A função vive em ui/sidebar.py, então o contrato é verificado
        # pelo texto: finaliza os subprocessos iniciados pelo app, usa a
        # API pública do Runtime e tem rede de segurança Timer + os._exit.
        self.assertIn("Runtime.instance().stop()", self.sidebar)
        self.assertIn("encerrar_processos_iniciados", self.sidebar)
        self.assertIn("threading.Timer", self.sidebar)
        self.assertIn("os._exit(0)", self.sidebar)


class TestCicloDeVidaDesktop(unittest.TestCase):
    """Bug: navegador garantido, auto-shutdown e --encerrar."""

    def test_url_nunca_usa_o_endereco_de_escuta(self):
        for porta in (8501, 8502, 9999):
            with self.subTest(porta=porta):
                self.assertNotIn(
                    "0.0.0.0",
                    launcher_desktop.url_aplicativo(porta),
                )

        self.assertEqual(
            launcher_desktop.normalizar_url_navegador(
                "http://0.0.0.0:8501"
            ),
            "http://localhost:8501",
        )
        self.assertEqual(
            launcher_desktop.normalizar_url_navegador(
                "http://0.0.0.0:8502/rota?x=1#topo"
            ),
            "http://localhost:8502/rota?x=1#topo",
        )
        self.assertEqual(
            launcher_desktop.normalizar_url_navegador("http://[::]:8503"),
            "http://localhost:8503",
        )

        # URLs já navegáveis (ou relativas) não são reescritas.
        self.assertEqual(
            launcher_desktop.normalizar_url_navegador(
                "http://127.0.0.1:8501"
            ),
            "http://127.0.0.1:8501",
        )
        self.assertEqual(
            launcher_desktop.normalizar_url_navegador("sem/host"),
            "sem/host",
        )

    def test_us_startfile_recebe_url_normalizada_com_com(self):
        with mock.patch.object(
            launcher_desktop.os, "name", "nt"
        ), mock.patch.object(
            launcher_desktop.os, "startfile", create=True
        ) as startfile, mock.patch.object(
            launcher_desktop.ctypes, "windll", create=True
        ) as windll, mock.patch.object(
            launcher_desktop.subprocess, "Popen"
        ) as popen, mock.patch.object(
            launcher_desktop.webbrowser, "open"
        ) as navegador, mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ) as log:
            self.assertTrue(
                launcher_desktop.abrir_navegador_url(
                    "http://0.0.0.0:8501"
                )
            )

        startfile.assert_called_once_with("http://localhost:8501")
        windll.ole32.CoInitialize.assert_called_once_with(None)
        windll.ole32.CoUninitialize.assert_called_once()
        popen.assert_not_called()
        navegador.assert_not_called()
        self.assertTrue(
            any("os.startfile" in str(chamada)
                for chamada in log.call_args_list)
        )

    def test_abrir_navegador_url_cai_para_cmd_start(self):
        with mock.patch.object(
            launcher_desktop.os, "name", "nt"
        ), mock.patch.object(
            launcher_desktop.os,
            "startfile",
            create=True,
            side_effect=OSError("sem shell"),
        ), mock.patch.object(
            launcher_desktop.ctypes, "windll", create=True
        ) as windll, mock.patch.object(
            launcher_desktop.subprocess, "Popen"
        ) as popen, mock.patch.object(
            launcher_desktop.webbrowser, "open"
        ) as navegador, mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ):
            windll.ole32.CoInitialize.side_effect = OSError("sem COM")

            self.assertTrue(
                launcher_desktop.abrir_navegador_url(
                    "http://localhost:8501"
                )
            )

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            ["cmd.exe", "/c", "start", "", "http://localhost:8501"],
        )
        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        navegador.assert_not_called()

    def test_abrir_navegador_url_cai_para_webbrowser(self):
        with mock.patch.object(
            launcher_desktop.os, "name", "nt"
        ), mock.patch.object(
            launcher_desktop.os,
            "startfile",
            create=True,
            side_effect=OSError("sem shell"),
        ), mock.patch.object(
            launcher_desktop.subprocess,
            "Popen",
            side_effect=OSError("sem cmd"),
        ), mock.patch.object(
            launcher_desktop.webbrowser, "open", return_value=True
        ) as navegador, mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ):
            self.assertTrue(
                launcher_desktop.abrir_navegador_url(
                    "http://localhost:8501"
                )
            )

        navegador.assert_called_once_with(
            "http://localhost:8501",
            new=2,
        )

    def test_abrir_navegador_url_sem_metodo_devolve_false(self):
        with mock.patch.object(
            launcher_desktop.os, "name", "nt"
        ), mock.patch.object(
            launcher_desktop.os,
            "startfile",
            create=True,
            side_effect=OSError("sem shell"),
        ), mock.patch.object(
            launcher_desktop.subprocess,
            "Popen",
            side_effect=OSError("sem cmd"),
        ), mock.patch.object(
            launcher_desktop.webbrowser, "open", return_value=False
        ), mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ) as log:
            self.assertFalse(
                launcher_desktop.abrir_navegador_url(
                    "http://localhost:8501"
                )
            )

        self.assertTrue(
            any("nenhum método abriu" in str(chamada)
                for chamada in log.call_args_list)
        )

    def test_abrir_navegador_url_ignora_url_vazia(self):
        with mock.patch.object(
            launcher_desktop, "registrar_log_launcher"
        ):
            self.assertFalse(launcher_desktop.abrir_navegador_url(""))

    def test_log_do_launcher_registra_healthcheck_e_encerramento(self):
        pasta = RAIZ / "build" / "_tmp_log_launcher"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)

        try:
            with mock.patch.object(
                launcher_desktop, "DIRETORIO_DADOS", pasta
            ), mock.patch.object(
                launcher_desktop,
                "aplicacao_respondendo",
                return_value=True,
            ), mock.patch.object(
                launcher_desktop,
                "abrir_navegador_url",
                return_value=True,
            ):
                self.assertTrue(
                    launcher_desktop.abrir_navegador_quando_pronto(
                        tentativas=1,
                        intervalo=0,
                    )
                )
                launcher_desktop.encerrar_por_inatividade(
                    "inatividade de teste",
                    sair=mock.Mock(),
                )

                caminho = launcher_desktop.caminho_log_launcher()

            self.assertEqual(caminho, pasta / "launcher.log")

            conteudo = caminho.read_text(encoding="utf-8")

            self.assertIn("healthcheck", conteudo)
            self.assertIn("http://localhost:8501", conteudo)
            self.assertIn("inatividade de teste", conteudo)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_abertura_apos_healthcheck_usa_o_abridor_do_windows(self):
        with mock.patch.object(
            launcher_desktop,
            "aplicacao_respondendo",
            return_value=True,
        ), mock.patch.object(
            launcher_desktop,
            "abrir_navegador_url",
            return_value=True,
        ) as abrir:
            resultado = launcher_desktop.abrir_navegador_quando_pronto(
                tentativas=1,
                intervalo=0,
            )

        self.assertTrue(resultado)
        abrir.assert_called_once_with("http://localhost:8501")

    def test_instancia_existente_usa_o_mesmo_abridor(self):
        with mock.patch.object(
            launcher_desktop,
            "abrir_navegador_url",
            return_value=True,
        ) as abrir:
            self.assertTrue(
                launcher_desktop.abrir_instancia_existente(8504)
            )

        abrir.assert_called_once_with("http://localhost:8504")

    def test_contagem_nativa_le_as_sessoes_do_runtime(self):
        """A contagem vem de Runtime.instance()._session_mgr."""

        runtime = mock.Mock()
        runtime._session_mgr.list_active_sessions.return_value = [
            mock.Mock(),
            mock.Mock(),
        ]

        with mock.patch(
            "streamlit.runtime.Runtime.instance", return_value=runtime
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                2,
            )

        # Aba fechada: o gerenciador de sessões devolve lista vazia.
        runtime._session_mgr.list_active_sessions.return_value = []

        with mock.patch(
            "streamlit.runtime.Runtime.instance", return_value=runtime
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                0,
            )

        # A porta é aceita por compatibilidade, mas a contagem é nativa:
        # o gerenciador de sessões é consultado uma única vez por ciclo.
        self.assertEqual(
            runtime._session_mgr.list_active_sessions.call_count, 2
        )

    def test_contagem_nativa_prefere_num_active_sessions(self):
        """O método nativo moderno é a primeira opção de contagem."""

        runtime = mock.Mock()
        runtime._session_mgr.num_active_sessions.return_value = 3

        with mock.patch(
            "streamlit.runtime.Runtime.instance", return_value=runtime
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                3,
            )

        runtime._session_mgr.num_active_sessions.assert_called_once_with()
        runtime._session_mgr.list_active_sessions.assert_not_called()

    def test_contagem_nativa_cai_para_list_active_sessions(self):
        """Sem ``num_active_sessions``, usa ``len(list_active_sessions())``."""

        runtime = mock.Mock()
        runtime._session_mgr.num_active_sessions.side_effect = (
            AttributeError("método ausente neste Streamlit")
        )
        runtime._session_mgr.list_active_sessions.return_value = [
            mock.Mock(),
            mock.Mock(),
        ]

        with mock.patch(
            "streamlit.runtime.Runtime.instance", return_value=runtime
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                2,
            )

        runtime._session_mgr.list_active_sessions.assert_called_once_with()

    def test_contagem_nativa_tolera_runtime_indisponivel(self):
        """Runtime ausente, import quebrado ou falha devolvem 0."""

        with mock.patch(
            "streamlit.runtime.Runtime.instance",
            side_effect=RuntimeError("Runtime hasn't been created!"),
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                0,
            )

        # Runtime inicializando, sem gerenciador de sessões: o fallback
        # get_client sem sessão registrada também devolve 0.
        runtime_sem_gerenciador = mock.Mock(spec=["get_client"])
        runtime_sem_gerenciador.get_client.return_value = None

        with mock.patch(
            "streamlit.runtime.Runtime.instance",
            return_value=runtime_sem_gerenciador,
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                0,
            )

        runtime_com_falha = mock.Mock()
        runtime_com_falha._session_mgr.list_active_sessions.side_effect = (
            RuntimeError("runtime em transição")
        )

        with mock.patch(
            "streamlit.runtime.Runtime.instance",
            return_value=runtime_com_falha,
        ):
            self.assertEqual(
                launcher_desktop.contar_sessoes_ativas_streamlit(8501),
                0,
            )

    def test_monitor_encerra_apos_10s_sem_sessoes(self):
        estado = launcher_desktop.novo_estado_monitor(
            0.0,
            janela_inicial=0.0,
        )

        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 0.0, 1
            )
        )
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 1.0, 0
            )
        )
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 10.9, 0
            )
        )
        self.assertTrue(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 11.0, 0
            )
        )

    def test_monitor_respeita_a_janela_inicial_de_25s(self):
        self.assertEqual(launcher_desktop.JANELA_INICIAL_SESSAO, 25.0)

        estado = launcher_desktop.novo_estado_monitor(0.0)
        self.assertEqual(estado["janela_inicial"], 25.0)

        # Sem sessões e antes dos 25 s: a sessão ainda não começou.
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 12.0, 0
            )
        )
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 24.9, 0
            )
        )
        # Aos 25 s a janela expira: começa a contagem de inatividade.
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 25.0, 0
            )
        )
        self.assertFalse(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 34.9, 0
            )
        )
        self.assertTrue(
            launcher_desktop.avaliar_monitor_sessao(
                estado, 35.0, 0
            )
        )

    def test_loop_do_monitor_encerra_quando_as_sessoes_zeram(self):
        pasta = RAIZ / "build" / "_tmp_monitor_sessoes"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)

        try:
            with mock.patch.object(
                launcher_desktop, "DIRETORIO_DADOS", pasta
            ), mock.patch.object(
                launcher_desktop, "_limpar_servidor"
            ) as limpar:
                registro = pasta / launcher_desktop.NOME_ARQUIVO_INSTANCIA
                registro.write_text(
                    json.dumps({"porta": 8501, "pid": 4321}),
                    encoding="utf-8",
                )

                # Uma aba conectada e, em seguida, o WebSocket cai.
                leituras = iter([1] + [0] * 20)
                tempos = iter(
                    [0.0] + [float(indice) for indice in range(1, 40)]
                )
                sair = mock.Mock()
                registros = []

                launcher_desktop.monitorar_sessoes_ativas(
                    porta=8501,
                    intervalo=0,
                    janela_inicial=launcher_desktop.JANELA_INICIAL_SESSAO,
                    limite_inatividade=(
                        launcher_desktop.LIMITE_INATIVIDADE_SESSAO
                    ),
                    contador=lambda porta: next(leituras),
                    encerrar=lambda: launcher_desktop.encerrar_por_inatividade(
                        sair=sair
                    ),
                    dormir=lambda _: None,
                    relogio=lambda: next(tempos),
                    registrar=registros.append,
                )

                self.assertFalse(registro.exists())
                self.assertEqual(
                    registros,
                    [
                        "primeira sessão ativa detectada",
                        "0 sessões ativas; iniciando contagem de inatividade",
                    ],
                )

            limpar.assert_called_once_with()
            sair.assert_called_once_with(0)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
    def test_encerrar_por_inatividade_limpa_e_sai(self):
        with mock.patch.object(
            launcher_desktop, "_limpar_servidor"
        ) as limpar, mock.patch.object(
            launcher_desktop, "_remover_registro_instancia"
        ) as remover:
            sair = mock.Mock()
            launcher_desktop.encerrar_por_inatividade(sair=sair)

        limpar.assert_called_once_with()
        remover.assert_called_once_with()
        sair.assert_called_once_with(0)

    def test_flag_encerrar_e_reconhecida(self):
        self.assertEqual(
            launcher_desktop.ARG_ENCERRAR,
            "--encerrar",
        )

        with mock.patch.object(
            launcher_desktop,
            "encerrar_instancia_ativa",
            return_value=True,
        ) as encerrar:
            codigo = launcher_desktop.main(["--encerrar"])

        self.assertEqual(codigo, 0)
        encerrar.assert_called_once_with()

    def test_encerrar_instancia_mata_o_pid_e_remove_o_registro(self):
        with mock.patch.object(
            launcher_desktop,
            "_ler_dados_registro_instancia",
            return_value={"porta": 8501, "pid": 4321},
        ), mock.patch.object(
            launcher_desktop,
            "encerrar_arvore_processos",
            return_value=True,
        ) as matar, mock.patch.object(
            launcher_desktop, "_remover_registro_instancia"
        ) as remover:
            self.assertTrue(
                launcher_desktop.encerrar_instancia_ativa()
            )

        matar.assert_called_once_with(pid=4321)
        remover.assert_called_once_with()

    def test_encerrar_bat_acompanha_o_build(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")
        self.assertIn("encerrar.bat", codigo)
        self.assertIn("--encerrar", codigo)

        encerrar = ler(RAIZ / "encerrar.bat")
        self.assertIn("iniciar.bat", encerrar)
        self.assertIn("--encerrar", encerrar)

    def test_iniciar_bat_mantem_o_vinculo_com_o_console(self):
        codigo = ler(RAIZ / "iniciar.bat")

        # O executavel roda em paralelo (start /B), mas no MESMO console:
        # sem janela separada, ele herda o console e recebe
        # CTRL_CLOSE_EVENT quando a janela do CMD e fechada. O start sem
        # /B (que abriria uma janela nova) continua proibido.
        self.assertIn('start "" /B "%EXE_PATH%" %*', codigo)
        self.assertNotIn('start "" /MIN', codigo)
        self.assertNotIn('start "" "%~dp0NexusGeoIA.exe"', codigo)

        # Os modos de diagnostico continuam sincronos e devolvem o
        # codigo de saida do executavel.
        self.assertIn('"%~dp0NexusGeoIA.exe" %*', codigo)
        self.assertIn(":executavel_sincrono", codigo)
        self.assertIn('set "CODIGO_SAIDA=%ERRORLEVEL%"', codigo)

        self.assertIn(":encerrar", codigo)
        self.assertIn("--encerrar", codigo)


class TestFluxoUnicoSetupLlm(unittest.TestCase):
    """O setup_llm.py da v1.0.0 configura um único modelo oficial."""

    def test_modulo_nao_tem_catalogo_antigo(self):
        for atributo in (
            "CATALOGO_MODELOS",
            "modelos_iniciais",
            "interpretar_escolha_cli",
            "executar_seletor_cli",
            "persistir_selecao",
        ):
            with self.subTest(atributo=atributo):
                self.assertFalse(hasattr(setup_llm, atributo))

        codigo = inspect.getsource(setup_llm)

        for proibido in (
            "qwen3:14b",
            "qwen2.5:3b",
            "três modelos",
            "Checkbutton",
            "Perfil de Hardware",
        ):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, codigo)

        self.assertIn(setup_llm.NOME_MODELO_LOCAL, codigo)
        self.assertEqual(setup_llm.MODELO_TECNICO_FALLBACK, "qwen3:4b")

    def test_cli_grava_modelo_oficial(self):
        saida = io.StringIO()

        with mock.patch.object(
            setup_llm,
            "garantir_modelo_oficial",
            return_value={
                "modelo": setup_llm.NOME_MODELO_LOCAL,
                "origem": "registrado",
                "caminho_config": "C:\\dados\\config_local.json",
            },
        ) as garantir, redirect_stdout(saida):
            codigo = setup_llm.executar_fluxo_cli(idioma="pt")

        self.assertEqual(codigo, 0)
        garantir.assert_called_once_with(
            forcar=False,
            idioma="pt",
            ao_progresso=mock.ANY,
        )
        self.assertIn("config_local.json", saida.getvalue())
        self.assertIn(setup_llm.NOME_MODELO_LOCAL, saida.getvalue())

    def test_cli_falha_retorna_1(self):
        saida = io.StringIO()

        with mock.patch.object(
            setup_llm,
            "garantir_modelo_oficial",
            side_effect=setup_llm.ErroDownload("sem rede"),
        ), redirect_stdout(saida):
            codigo = setup_llm.executar_fluxo_cli()

        self.assertEqual(codigo, 1)
        self.assertIn("sem rede", saida.getvalue())

    def test_principal_sem_tkinter_cai_para_cli(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=False
        ), mock.patch.object(
            setup_llm, "executar_fluxo_cli", return_value=0
        ) as cli, mock.patch.object(
            setup_llm, "abrir_interface"
        ) as gui:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with(forcar=False)
        gui.assert_not_called()

    def test_principal_cai_para_cli_quando_import_falha(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=ImportError("No module named 'tkinter'"),
        ), mock.patch.object(
            setup_llm, "executar_fluxo_cli", return_value=0
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with(forcar=False)

    def test_principal_cai_para_cli_quando_tcl_falha(self):
        if not setup_llm.tkinter_disponivel():
            self.skipTest("tkinter não disponível para montar o TclError")

        import tkinter

        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=tkinter.TclError("no display"),
        ), mock.patch.object(
            setup_llm, "executar_fluxo_cli", return_value=0
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with(forcar=False)

    def test_principal_mantem_erro_generico_sem_cli(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=RuntimeError("sem display"),
        ), mock.patch.object(
            setup_llm, "executar_fluxo_cli"
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 1)

        cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
