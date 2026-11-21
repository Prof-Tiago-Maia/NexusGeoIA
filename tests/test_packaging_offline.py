"""Testes offline dos scripts de empacotamento e do launcher.

Validam sintaxe e conteúdo de ``packaging/assistente.spec``,
``packaging/installer.iss``, ``packaging/*.ps1``, ``launcher_desktop.py``
e ``iniciar.bat`` sem executar PyInstaller, Inno Setup, Ollama ou o
Streamlit. A sintaxe do PowerShell é conferida pelo parser da própria
linguagem quando ``powershell``/``pwsh`` está disponível.
"""

import io
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import launcher_desktop
import setup_llm

RAIZ = Path(__file__).resolve().parent.parent
PACKAGING = RAIZ / "packaging"

# Faixa de portas testada pelo launcher e pelo iniciar.bat.
PORTA_PREFERIDA = 8501
PORTA_MAXIMA = 8510


def ler(caminho):
    return Path(caminho).read_text(encoding="utf-8")


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

        if not limpa or limpa.startswith(";") or limpa.startswith("#"):
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
            "OutputBaseFilename=NexusGeoIA_v0.9.0_Setup",
            self.iss,
        )
        self.assertIn("AppName=NexusGeo IA", self.iss)
        self.assertIn("AppVersion=0.9.0", self.iss)
        self.assertIn('#define MyAppName "NexusGeo IA"', self.iss)
        self.assertIn('#define MyAppVersion "0.9.0"', self.iss)

    def test_idioma_portugues_brasil(self):
        self.assertIn("BrazilianPortuguese.isl", self.iss)
        self.assertIn('Name: "brazilianportuguese"', self.iss)

    def test_atalhos_area_de_trabalho_e_menu_iniciar(self):
        self.assertIn("{autodesktop}", self.iss)
        self.assertIn("{group}", self.iss)
        self.assertIn("Name: \"desktopicon\"", self.iss)

    def test_atalho_gerenciar_modelos(self):
        self.assertIn("Gerenciar Modelos LLM", self.iss)
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
        self.assertIn("/VERYSILENT", self.iss)
        self.assertIn("/NORESTART", self.iss)
        self.assertIn("CurStepChanged", self.iss)
        self.assertIn("ssPostInstall", self.iss)

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

    def test_porta_e_endereco_do_aplicativo(self):
        self.assertEqual(self.config["server"]["port"], 8501)
        self.assertEqual(self.config["server"]["address"], "localhost")

    def test_metricas_de_uso_desativadas(self):
        self.assertIs(self.config["browser"]["gatherUsageStats"], False)


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

    def test_iniciar_streamlit_repassa_server_port(self):
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
            launcher_desktop, "agendar_abertura_navegador"
        ) as navegador, mock.patch(
            "streamlit.web.cli.main",
            side_effect=main_falso,
        ):
            codigo = launcher_desktop.iniciar_streamlit(8502)

        self.assertEqual(codigo, 0)
        self.assertIn("--server.port=8502", lidos["argv"])
        self.assertNotIn("--server.port", lidos["argv"])
        self.assertIn("--server.headless=true", lidos["argv"])
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
        # O autoteste precisa sair antes do assistente de modelos e do
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

    def test_build_portatil_nao_executa_o_exe_por_padrao(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O aplicativo e desktop: sobe o Streamlit e nao termina sozinho.
        # Executar o binario no build e opt-in (-SmokeExe); o padrao monta
        # o pacote sem abrir o .exe.
        self.assertIn("[switch]$SmokeExe", codigo)
        self.assertIn("if (-not $SmokeExe)", codigo)
        self.assertIn("Smoke test do executavel: ignorado (use -SmokeExe)", codigo)

        smoke = codigo.index("if (-not $SmokeExe)")
        zip_final = codigo.index("Gerando $ZipFinal")

        self.assertLess(
            smoke,
            zip_final,
            "o bloco do autoteste deve ficar antes da geracao do .zip",
        )
        self.assertIn("--autoteste", codigo)
        self.assertIn("ASSISTENTE_SMOKE_REPORT", codigo)

    def test_build_portatil_inclui_o_protocolo_de_pesquisa(self):
        codigo = ler(PACKAGING / "build_portatil.ps1")

        # O protocolo viaja no .zip, e o build falha se ele sumir.
        self.assertIn('Join-Path $Raiz "PROTOCOLO_PESQUISA.md"', codigo)
        self.assertIn('"PROTOCOLO_PESQUISA.md",', codigo)

        conteudo = ler(RAIZ / "PROTOCOLO_PESQUISA.md")

        self.assertIn("NexusGeo IA", conteudo)
        self.assertGreater(len(conteudo), 2000)


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
                "NexusGeoIA_v0.9.0_Portatil/NexusGeoIA.exe",
                "NexusGeoIA_v0.9.0_Portatil/iniciar.bat",
                "NexusGeoIA_v0.9.0_Portatil/.dsh/estado.json",
                "NexusGeoIA_v0.9.0_Portatil/tests/test_x.py",
                "NexusGeoIA_v0.9.0_Portatil/__pycache__/app.cpython-314.pyc",
                "NexusGeoIA_v0.9.0_Portatil/.env",
                "NexusGeoIA_v0.9.0_Portatil/secrets.toml",
                "NexusGeoIA_v0.9.0_Portatil/estrutura.txt",
                "NexusGeoIA_v0.9.0_Portatil/tmpabc/lixo.txt",
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

        staging = pasta / "NexusGeoIA_v0.9.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v0.9.0_Portatil.zip"

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
                        f"NexusGeoIA_v0.9.0_Portatil/{nome}", b"x"
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

        staging = pasta / "NexusGeoIA_v0.9.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v0.9.0_Portatil.zip"

        try:
            import zipfile

            with zipfile.ZipFile(zip_final, "w") as arquivo:
                for nome in ("NexusGeoIA.exe", "iniciar.bat", "LEIA-ME.txt"):
                    arquivo.writestr(
                        f"NexusGeoIA_v0.9.0_Portatil/{nome}", b"x"
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
                resultado = modulo.verificar_pacote_onedir(pacote, falhas)

            self.assertEqual(falhas, [])
            self.assertIsNotNone(resultado)
            self.assertIsNotNone(resultado["internal_mb"])
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

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

        staging = pasta / "NexusGeoIA_v0.9.0_Portatil"
        zip_final = pasta / "NexusGeoIA_v0.9.0_Portatil.zip"

        try:
            import zipfile

            with zipfile.ZipFile(zip_final, "w") as arquivo:
                arquivo.writestr(
                    "NexusGeoIA_v0.9.0_Portatil/NexusGeoIA.exe", b"x"
                )
                arquivo.writestr(
                    "NexusGeoIA_v0.9.0_Portatil/.git/config", b"x"
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
            "NexusGeoIA_v0.9.0_Portatil",
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
            "NexusGeoIA_v0.9.0_Setup.exe",
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

        self.assertIn("--server.headless=false", codigo)
        self.assertIn("--server.port=%PORTA%", codigo)
        self.assertIn("http://localhost:%PORTA%", codigo)

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


class EntradaFalsa:
    """Substitui o ``input()`` do seletor de terminal nos testes."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)

        if not self.respostas:
            raise EOFError

        return self.respostas.pop(0)


class TestFallbackCliSetupLlm(unittest.TestCase):
    """O ``setup_llm.py`` configura o modelo sem Tkinter (entrada 1, 2, 3)."""

    def test_interpretar_escolha_enter_usa_recomendacao(self):
        self.assertEqual(
            setup_llm.interpretar_escolha_cli("", ["qwen3:4b"]),
            ["qwen3:4b"],
        )

    def test_interpretar_escolha_aceita_varias_opcoes(self):
        self.assertEqual(
            setup_llm.interpretar_escolha_cli("1,3"),
            ["qwen3:4b", "qwen2.5:3b"],
        )
        self.assertEqual(
            setup_llm.interpretar_escolha_cli("2 3"),
            ["qwen3:14b", "qwen2.5:3b"],
        )
        self.assertEqual(
            setup_llm.interpretar_escolha_cli("1;1"),
            ["qwen3:4b"],
        )

    def test_interpretar_escolha_recusa_entrada_invalida(self):
        for valor in ("0", "4", "x", "1,x", "-1"):
            with self.subTest(valor=valor):
                self.assertIsNone(
                    setup_llm.interpretar_escolha_cli(valor)
                )

    def _executar(self, respostas, ram=16.0, servico_ativo=True):
        entrada = EntradaFalsa(respostas)
        saida = io.StringIO()
        chamadas = {"download": [], "persistencia": []}

        def baixar(selecionados, ao_progresso=None, idioma=None):
            chamadas["download"].append(list(selecionados))
            return {
                "tipo": "fim",
                "instalados": list(selecionados),
                "falhas": {},
                "modelo_padrao": setup_llm.modelo_padrao(selecionados),
            }

        def persistir(instalados, caminho=None):
            chamadas["persistencia"].append(list(instalados))
            return {"modelo_padrao": setup_llm.modelo_padrao(instalados)}

        with mock.patch.object(
            setup_llm, "memoria_total_gb", return_value=ram
        ), mock.patch.object(
            setup_llm,
            "garantir_servico_ollama",
            return_value={"ativo": servico_ativo},
        ), mock.patch.object(
            setup_llm, "baixar_modelos", side_effect=baixar
        ), mock.patch.object(
            setup_llm, "persistir_selecao", side_effect=persistir
        ), redirect_stdout(saida):
            codigo = setup_llm.executar_seletor_cli(
                entrada=entrada,
                idioma="pt",
            )

        return codigo, entrada, saida.getvalue(), chamadas

    def test_enter_baixa_o_recomendado_por_ram(self):
        codigo, entrada, saida, chamadas = self._executar([""], ram=8.0)

        self.assertEqual(codigo, 0)
        self.assertEqual(chamadas["download"], [["qwen2.5:3b"]])
        self.assertEqual(chamadas["persistencia"], [["qwen2.5:3b"]])
        self.assertEqual(len(entrada.prompts), 1)
        self.assertIn("ENTER", entrada.prompts[0])

        # A tabela numerada com as tres opcoes foi exibida.
        for numero in ("1)", "2)", "3)"):
            self.assertIn(numero, saida)

        self.assertIn("Configuração gravada", saida)

    def test_opcao_invalida_repete_e_aceita_escolha(self):
        codigo, _, saida, chamadas = self._executar(["9", "1,3"])

        self.assertEqual(codigo, 0)
        self.assertIn("Opção inválida", saida)
        self.assertEqual(
            chamadas["download"],
            [["qwen3:4b", "qwen2.5:3b"]],
        )

    def test_ollama_inativo_nao_baixa(self):
        codigo, _, saida, chamadas = self._executar(
            ["1"],
            servico_ativo=False,
        )

        self.assertEqual(codigo, 1)
        self.assertEqual(chamadas["download"], [])
        self.assertIn("Ollama não está acessível", saida)

    def test_entrada_cancelada_nao_grava(self):
        codigo, _, _, chamadas = self._executar([])

        self.assertEqual(codigo, 1)
        self.assertEqual(chamadas["download"], [])
        self.assertEqual(chamadas["persistencia"], [])

    def test_principal_cai_para_cli_sem_tkinter(self):
        with mock.patch.object(
            setup_llm, "precisa_configurar", return_value=True
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=False
        ), mock.patch.object(
            setup_llm, "executar_seletor_cli", return_value=0
        ) as cli, mock.patch.object(
            setup_llm, "abrir_interface"
        ) as gui:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with()
        gui.assert_not_called()

    def test_principal_cai_para_cli_quando_import_falha(self):
        with mock.patch.object(
            setup_llm, "precisa_configurar", return_value=True
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=ImportError("No module named 'tkinter'"),
        ), mock.patch.object(
            setup_llm, "executar_seletor_cli", return_value=0
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with()

    def test_principal_cai_para_cli_quando_tcl_falha(self):
        if not setup_llm.tkinter_disponivel():
            self.skipTest("tkinter não disponível para montar o TclError")

        import tkinter

        with mock.patch.object(
            setup_llm, "precisa_configurar", return_value=True
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=tkinter.TclError("no display"),
        ), mock.patch.object(
            setup_llm, "executar_seletor_cli", return_value=0
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with()

    def test_principal_mantem_erro_generico_sem_cli(self):
        with mock.patch.object(
            setup_llm, "precisa_configurar", return_value=True
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=RuntimeError("sem display"),
        ), mock.patch.object(
            setup_llm, "executar_seletor_cli"
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 1)

        cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
