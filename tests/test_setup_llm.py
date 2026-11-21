"""Testes offline do assistente de modelos LLM (``setup_llm.py``).

Cobrem a matriz dos três modelos, a seleção múltipla, a fila de download
com o ``/api/pull`` simulado, a persistência em ``config_local.json`` e
a prioridade de leitura em ``config.py``. Nenhum teste abre janela,
acessa a rede, executa o Ollama ou usa navegador.
"""

import inspect
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock

import config
import setup_llm

RAIZ = Path(__file__).resolve().parent.parent


def novo_diretorio_temporario():
    """Pasta temporaria dentro de ``tests/`` (gravavel e sem rede).

    Evita o diretorio temporario do sistema, que em algumas politicas de
    execucao do Windows pode negar a limpeza.
    """

    base = Path(__file__).resolve().parent / "_tmp_setup_llm"
    base.mkdir(parents=True, exist_ok=True)

    pasta = base / uuid.uuid4().hex
    pasta.mkdir()

    return pasta


# ---------------------------------------------------------------------------
# Dublês HTTP
# ---------------------------------------------------------------------------

class RespostaFalsa:
    """Resposta mínima compatível com o que ``baixar_modelo`` consome."""

    def __init__(self, linhas, status_code=200, texto=""):
        self._linhas = list(linhas)
        self.status_code = status_code
        self.text = texto
        self.fechada = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self, decode_unicode=True):
        for linha in self._linhas:
            yield linha

    def close(self):
        self.fechada = True


class SessaoFalsa:
    """``requests.Session`` de mentira que registra as chamadas."""

    def __init__(
        self,
        linhas_por_modelo=None,
        erros=None,
        status=200,
        corpos=None,
    ):
        self.linhas_por_modelo = linhas_por_modelo or {}
        self.erros = erros or {}
        self.status = status
        self.corpos = corpos or {}
        self.chamadas = []
        self.respostas = []

    def post(self, url, json=None, stream=False, timeout=None):
        modelo = (json or {}).get("model", "")

        self.chamadas.append(
            {
                "url": url,
                "modelo": modelo,
                "stream": stream,
                "timeout": timeout,
            }
        )

        if modelo in self.erros:
            resposta = RespostaFalsa(
                [
                    json_dumps({"error": self.erros[modelo]}),
                ],
                status_code=self.status,
            )
        else:
            linhas = self.linhas_por_modelo.get(
                modelo,
                [
                    {"status": "pulling manifest"},
                    {"status": "downloading", "completed": 50, "total": 100},
                    {"status": "success"},
                ],
            )

            resposta = RespostaFalsa(
                [json_dumps(evento) for evento in linhas],
                status_code=self.status,
                texto=self.corpos.get(modelo, ""),
            )

        self.respostas.append(resposta)

        return resposta


def json_dumps(dados):
    return json.dumps(dados, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Catálogo e seleção
# ---------------------------------------------------------------------------

class TestCatalogo(unittest.TestCase):
    """Os três modelos exatos, com perfil, RAM e comportamento."""

    def test_exatamente_tres_modelos_na_ordem_esperada(self):
        self.assertEqual(
            setup_llm.identificadores_modelos(),
            ["qwen3:4b", "qwen3:14b", "qwen2.5:3b"],
        )

    def test_ram_de_cada_modelo(self):
        self.assertEqual(setup_llm.obter_modelo("qwen3:4b").ram_gb, 2.6)
        self.assertEqual(setup_llm.obter_modelo("qwen3:14b").ram_gb, 9.0)
        self.assertEqual(setup_llm.obter_modelo("qwen2.5:3b").ram_gb, 1.9)

    def test_perfis_de_hardware_nos_dois_idiomas(self):
        quatro = setup_llm.obter_modelo("qwen3:4b")
        quatorze = setup_llm.obter_modelo("qwen3:14b")
        leve = setup_llm.obter_modelo("qwen2.5:3b")

        self.assertIn("16 GB", quatro.perfil("pt"))
        self.assertIn("Sem GPU dedicada", quatro.perfil("pt"))
        self.assertIn("Offline Installer Default", quatro.perfil("en"))

        self.assertIn("32+", quatorze.perfil("pt"))
        self.assertIn("8 GB VRAM", quatorze.perfil("pt"))

        self.assertIn("8 GB", leve.perfil("pt"))
        self.assertIn("Older laptops", leve.perfil("en"))

    def test_comportamentos_dos_dois_idiomas(self):
        for modelo in setup_llm.CATALOGO_MODELOS:
            self.assertTrue(modelo.comportamento("pt").strip())
            self.assertTrue(modelo.comportamento("en").strip())

    def test_formatar_ram_pt_e_en(self):
        self.assertEqual(setup_llm.formatar_ram(2.6, "pt"), "~2,6 GB")
        self.assertEqual(setup_llm.formatar_ram(2.6, "en"), "~2.6 GB")

    def test_ram_formatada_do_modelo(self):
        self.assertEqual(
            setup_llm.obter_modelo("qwen3:14b").ram_formatada("pt"),
            "~9,0 GB",
        )

    def test_modelo_desconhecido_devolve_none(self):
        self.assertIsNone(setup_llm.obter_modelo("llama3:8b"))

    def test_normalizar_modelos_descarta_invalidos_e_duplicados(self):
        self.assertEqual(
            setup_llm.normalizar_modelos(
                ["qwen3:4b", "llama3:8b", "qwen3:4b", " qwen2.5:3b "]
            ),
            ["qwen3:4b", "qwen2.5:3b"],
        )


class TestSelecao(unittest.TestCase):
    """Pré-seleção por RAM, RAM estimada e prioridade do modelo padrão."""

    def test_pre_selecao_por_ram(self):
        self.assertEqual(setup_llm.modelos_iniciais(8.0), ["qwen2.5:3b"])
        self.assertEqual(setup_llm.modelos_iniciais(16.0), ["qwen3:4b"])
        self.assertEqual(setup_llm.modelos_iniciais(31.7), ["qwen3:14b"])
        self.assertEqual(setup_llm.modelos_iniciais(64.0), ["qwen3:14b"])

    def test_ram_estimada_soma_os_marcados(self):
        self.assertEqual(
            setup_llm.estimar_ram_gb(["qwen3:4b", "qwen3:14b"]),
            11.6,
        )
        self.assertEqual(setup_llm.estimar_ram_gb(["qwen2.5:3b"]), 1.9)
        self.assertEqual(setup_llm.estimar_ram_gb([]), 0.0)

    def test_modelo_padrao_prioriza_14b(self):
        self.assertEqual(
            setup_llm.modelo_padrao(["qwen2.5:3b", "qwen3:14b", "qwen3:4b"]),
            "qwen3:14b",
        )
        self.assertEqual(
            setup_llm.modelo_padrao(["qwen2.5:3b", "qwen3:4b"]),
            "qwen3:4b",
        )
        self.assertEqual(
            setup_llm.modelo_padrao(["qwen2.5:3b"]),
            "qwen2.5:3b",
        )
        self.assertEqual(setup_llm.modelo_padrao([]), "")

    def test_texto_de_progresso(self):
        self.assertEqual(
            setup_llm.texto_de_progresso(1, 2, "qwen3:4b", "pt"),
            "Baixando 1/2: qwen3:4b...",
        )
        self.assertEqual(
            setup_llm.texto_de_progresso(2, 3, "qwen2.5:3b", "en"),
            "Downloading 2/3: qwen2.5:3b...",
        )

    def test_percentual_tolerante(self):
        self.assertEqual(setup_llm.calcular_percentual(50, 100), 50.0)
        self.assertEqual(setup_llm.calcular_percentual(0, 100), 0.0)
        self.assertEqual(setup_llm.calcular_percentual(100, 100), 100.0)
        self.assertIsNone(setup_llm.calcular_percentual(10, 0))
        self.assertIsNone(setup_llm.calcular_percentual(None, 100))
        self.assertIsNone(setup_llm.calcular_percentual("x", "y"))


# ---------------------------------------------------------------------------
# Serviço Ollama (sem rede)
# ---------------------------------------------------------------------------

class TestServicoOllama(unittest.TestCase):
    """Verificação do serviço e leitura de ``/api/tags`` com HTTP dublado."""

    def test_servico_ativo_quando_tags_responde(self):
        with mock.patch.object(
            setup_llm,
            "_http_json",
            return_value={"models": []},
        ):
            self.assertTrue(setup_llm.servico_ollama_ativo())

    def test_servico_inativo_quando_tags_falha(self):
        with mock.patch.object(setup_llm, "_http_json", return_value=None):
            self.assertFalse(setup_llm.servico_ollama_ativo())

    def test_healthcheck_usa_loopback_11434(self):
        with mock.patch.object(
            setup_llm,
            "_http_json",
            return_value={"models": []},
        ) as http_json:
            self.assertTrue(
                setup_llm.servico_ollama_ativo(
                    setup_llm.HOST_OLLAMA_LOCAL
                )
            )

        self.assertEqual(
            http_json.call_args.args[0],
            "http://127.0.0.1:11434/api/tags",
        )

    def test_modelos_instalados_extrai_nomes(self):
        with mock.patch.object(
            setup_llm,
            "_http_json",
            return_value={
                "models": [
                    {"name": "qwen3:4b"},
                    {"model": "qwen2.5:3b"},
                    {"name": ""},
                    "ignorado",
                ]
            },
        ):
            self.assertEqual(
                setup_llm.modelos_instalados(),
                ["qwen3:4b", "qwen2.5:3b"],
            )

    def test_modelos_instalados_sem_lista(self):
        with mock.patch.object(
            setup_llm,
            "_http_json",
            return_value={"models": "inesperado"},
        ):
            self.assertEqual(setup_llm.modelos_instalados(), [])


class TestEsperaOllama(unittest.TestCase):
    """Polling de arranque antes de qualquer aviso modal.

    O ``ollama serve`` iniciado pelo aplicativo leva alguns instantes
    para abrir a porta 11434; a interface precisa esperar 0,5 s por até
    5,0 s antes de exibir "Ollama indisponível".
    """

    def test_janela_padrao_de_meio_segundo_por_cinco_segundos(self):
        self.assertEqual(setup_llm.INTERVALO_ESPERA_UI_OLLAMA, 0.5)
        self.assertEqual(setup_llm.ESPERA_UI_OLLAMA_SEGUNDOS, 5.0)

        tentativas = (
            round(
                setup_llm.ESPERA_UI_OLLAMA_SEGUNDOS
                / setup_llm.INTERVALO_ESPERA_UI_OLLAMA
            )
            + 1
        )

        self.assertEqual(tentativas, 11)

    def test_nao_dispara_alerta_se_servico_responde_na_janela(self):
        respostas = [False, False, True]
        consultas = []
        pausas = []

        def verificador():
            consultas.append(True)

            return respostas.pop(0)

        self.assertTrue(
            setup_llm.aguardar_ollama(
                espera=1.0,
                intervalo=0.5,
                verificador=verificador,
                dormir=pausas.append,
            )
        )

        self.assertEqual(len(consultas), 3)
        self.assertEqual(pausas, [0.5, 0.5])

    def test_desiste_ao_esgotar_a_janela(self):
        consultas = []
        pausas = []

        def verificador():
            consultas.append(True)

            return False

        self.assertFalse(
            setup_llm.aguardar_ollama(
                espera=1.0,
                intervalo=0.5,
                verificador=verificador,
                dormir=pausas.append,
            )
        )

        # 1,0 s / 0,5 s = 3 consultas e 2 pausas: nunca fica em laço.
        self.assertEqual(len(consultas), 3)
        self.assertEqual(pausas, [0.5, 0.5])

    def test_consulta_api_tags_no_host_pedido(self):
        with mock.patch.object(
            setup_llm,
            "servico_ollama_ativo",
            side_effect=[False, True],
        ) as ativo:
            self.assertTrue(
                setup_llm.aguardar_ollama(
                    host=setup_llm.HOST_OLLAMA_LOCAL,
                    espera=0.5,
                    intervalo=0.5,
                    dormir=lambda _segundos: None,
                )
            )

        self.assertEqual(
            ativo.call_args.args[0],
            setup_llm.HOST_OLLAMA_LOCAL,
        )

    def test_iniciar_servidor_da_tolerancia_quando_o_processo_sai(self):
        # Outra instância do Ollama pode ter tomado a porta: o filho
        # recém-criado sai, mas o serviço ainda pode subir na sequência.
        processo = mock.Mock()
        processo.poll.return_value = 0

        with mock.patch.object(
            setup_llm,
            "servico_ollama_ativo",
            return_value=False,
        ), mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=r"C:\Ollama\ollama.exe",
        ), mock.patch.object(
            setup_llm.subprocess,
            "Popen",
            return_value=processo,
        ), mock.patch.object(
            setup_llm,
            "aguardar_ollama",
            return_value=True,
        ) as aguardar:
            self.assertTrue(setup_llm.iniciar_servidor_ollama())

        aguardar.assert_called_once_with(setup_llm.HOST_OLLAMA_PADRAO)


class TestDiagnosticoPermissao(unittest.TestCase):
    """Diagnóstico NTFS do download de modelos (``Acesso negado``)."""

    def test_reconhece_variantes_de_acesso_negado(self):
        for mensagem in (
            (
                r"open C:\Users\ana\.ollama\models\manifests-v2\x:"
                " Access is denied."
            ),
            r"open C:\Users\ana\.ollama\models\x: Acesso negado.",
            "Permission denied",
            "[WinError 5] Access is denied",
        ):
            with self.subTest(mensagem=mensagem):
                self.assertTrue(setup_llm.erro_de_permissao(mensagem))

    def test_nao_confunde_erros_comuns(self):
        for mensagem in (
            "model not found",
            "connection refused",
            "HTTP 500",
            "",
            None,
        ):
            with self.subTest(mensagem=mensagem):
                self.assertFalse(setup_llm.erro_de_permissao(mensagem))

    def test_orientacao_traz_icacls_e_ollama_models_nos_dois_idiomas(self):
        pasta = r"C:\Users\ana\.ollama\models"

        portugues = setup_llm.orientacao_permissao(
            "Acesso negado",
            "pt",
            pasta=pasta,
        )
        ingles = setup_llm.orientacao_permissao(
            "Access is denied",
            "en",
            pasta=pasta,
        )

        for orientacao in (portugues, ingles):
            self.assertIn("icacls", orientacao)
            self.assertIn("OLLAMA_MODELS", orientacao)
            self.assertIn("setx", orientacao)
            self.assertIn(pasta, orientacao)

        self.assertIn("Administrador", portugues)
        self.assertIn("Acesso negado", portugues)
        self.assertIn("Administrator", ingles)
        self.assertIn("Access is denied", ingles)

    def test_pasta_modelos_respeita_ollama_models(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_MODELS": r"D:\ollama_models"},
            clear=False,
        ):
            self.assertEqual(
                str(setup_llm.pasta_modelos_ollama()),
                r"D:\ollama_models",
            )

    def test_baixar_modelos_anexa_orientacao_a_falha(self):
        sessao = SessaoFalsa(
            erros={
                "qwen3:4b": (
                    r"open C:\Users\ana\.ollama\models\manifests-v2"
                    r"\registry.ollama.ai\library\qwen3\4b\manifest-abc:"
                    " Access is denied."
                )
            },
        )
        eventos = []

        resultado = setup_llm.baixar_modelos(
            ["qwen3:4b", "qwen3:14b"],
            sessao=sessao,
            ao_progresso=eventos.append,
            idioma="pt",
        )

        # O segundo modelo continua baixando normalmente.
        self.assertEqual(resultado["instalados"], ["qwen3:14b"])

        falha = resultado["falhas"]["qwen3:4b"]

        self.assertIn("icacls", falha)
        self.assertIn("OLLAMA_MODELS", falha)
        self.assertIn("Administrador", falha)

        erro = next(
            evento for evento in eventos if evento["tipo"] == "erro"
        )
        self.assertIn("icacls", erro["mensagem"])

    def test_baixar_modelos_usa_idioma_ingles_na_orientacao(self):
        sessao = SessaoFalsa(
            erros={"qwen3:4b": "Access is denied"},
        )

        resultado = setup_llm.baixar_modelos(
            ["qwen3:4b"],
            sessao=sessao,
            idioma="en",
        )

        falha = resultado["falhas"]["qwen3:4b"]

        self.assertIn("Administrator", falha)
        self.assertIn("OLLAMA_MODELS", falha)

    def test_http_de_erro_com_corpo_de_acesso_negado_e_diagnosticado(self):
        sessao = SessaoFalsa(
            status=500,
            corpos={
                "qwen3:4b": (
                    r'{"error":"open C:\Users\ana\.ollama\models\x: '
                    r'Access is denied."}'
                )
            },
        )

        resultado = setup_llm.baixar_modelos(
            ["qwen3:4b"],
            sessao=sessao,
        )

        falha = resultado["falhas"]["qwen3:4b"]

        self.assertIn("HTTP 500", falha)
        self.assertIn("Access is denied", falha)
        self.assertIn("icacls", falha)


class TestInterfaceSemFalsoAlerta(unittest.TestCase):
    """A janela só alerta "Ollama indisponível" depois da espera."""

    def test_aviso_modal_vem_depois_do_polling(self):
        codigo = inspect.getsource(setup_llm.abrir_interface)

        posicao_espera = codigo.index("aguardar_ollama")
        posicao_aviso = codigo.index("sem_ollama_titulo")

        self.assertLess(posicao_espera, posicao_aviso)

    def test_confirmar_fica_bloqueado_durante_a_verificacao(self):
        codigo = inspect.getsource(setup_llm.abrir_interface)

        self.assertIn('estado["verificando"] or estado["baixando"]', codigo)


# ---------------------------------------------------------------------------
# Detecção, download e instalação automática do Ollama
# ---------------------------------------------------------------------------

class RespostaDownloadFalsa:
    """Resposta binária mínima compatível com o download do instalador."""

    def __init__(self, blocos, content_length=None):
        self._blocos = list(blocos)
        self.headers = {}

        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

        self.fechada = False

    def read(self, tamanho=-1):
        if not self._blocos:
            return b""

        return self._blocos.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.fechada = True


class TestDeteccaoOllama(unittest.TestCase):
    """``shutil.which`` e os caminhos padrão do Windows."""

    def test_localizar_usa_which(self):
        with mock.patch.object(
            setup_llm.shutil,
            "which",
            return_value=r"C:\Ferramentas\ollama.exe",
        ):
            self.assertEqual(
                setup_llm.localizar_ollama(),
                r"C:\Ferramentas\ollama.exe",
            )

    def test_localizar_usa_caminho_padrao_sem_which(self):
        pasta = novo_diretorio_temporario()

        try:
            ollama = pasta / "Programs" / "Ollama" / "ollama.exe"
            ollama.parent.mkdir(parents=True)
            ollama.write_bytes(b"fake")

            with mock.patch.object(
                setup_llm.shutil,
                "which",
                return_value=None,
            ), mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(pasta)},
                clear=False,
            ):
                self.assertEqual(
                    setup_llm.localizar_ollama(),
                    str(ollama),
                )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_adicionar_ollama_ao_path_e_idempotente(self):
        pasta = novo_diretorio_temporario()

        try:
            pasta_ollama = pasta / "Programs" / "Ollama"
            pasta_ollama.mkdir(parents=True)

            with mock.patch.dict(
                os.environ,
                {"PATH": "C:\\Windows", "LOCALAPPDATA": str(pasta)},
                clear=False,
            ):
                primeiro = setup_llm.adicionar_ollama_ao_path()
                segundo = setup_llm.adicionar_ollama_ao_path()
                path_final = os.environ["PATH"]

            self.assertEqual(primeiro, str(pasta_ollama))
            self.assertEqual(segundo, str(pasta_ollama))
            self.assertEqual(path_final.count(str(pasta_ollama)), 1)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


class TestDownloadInstaladorOllama(unittest.TestCase):
    """Download HTTP do ``OllamaSetup.exe`` com progresso, sem rede."""

    def setUp(self):
        self.pasta = novo_diretorio_temporario()
        self.destino = self.pasta / "OllamaSetup.exe"

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_baixa_reportando_mb_e_percentual(self):
        resposta = RespostaDownloadFalsa(
            [b"a" * 512, b"b" * 512],
            content_length=1024,
        )
        eventos = []

        with mock.patch.object(
            setup_llm,
            "_abrir_url",
            return_value=resposta,
        ) as abrir:
            caminho = setup_llm.baixar_instalador_ollama(
                destino=self.destino,
                callback_progresso=eventos.append,
            )

        self.assertEqual(caminho, str(self.destino))
        self.assertEqual(
            self.destino.read_bytes(),
            b"a" * 512 + b"b" * 512,
        )
        self.assertEqual(
            abrir.call_args.args[0],
            setup_llm.URL_INSTALADOR_OLLAMA,
        )
        self.assertTrue(resposta.fechada)

        percentuais = [
            evento["percentual"]
            for evento in eventos
            if evento.get("percentual") is not None
        ]

        self.assertIn(50.0, percentuais)
        self.assertEqual(percentuais[-1], 100.0)
        self.assertEqual(eventos[-1]["etapa"], "baixando")
        self.assertEqual(
            setup_llm.formatar_mb(1048576, "pt"),
            "1,0 MB",
        )

    def test_url_padrao_do_instalador_oficial(self):
        self.assertEqual(
            setup_llm.URL_INSTALADOR_OLLAMA,
            "https://ollama.com/download/OllamaSetup.exe",
        )

    def test_falha_de_rede_remove_arquivo_parcial(self):
        with mock.patch.object(
            setup_llm,
            "_abrir_url",
            side_effect=OSError("sem rede"),
        ):
            with self.assertRaises(setup_llm.ErroInstalacaoOllama):
                setup_llm.baixar_instalador_ollama(
                    destino=self.destino,
                )

        self.assertFalse(self.destino.exists())

    def test_falha_antes_da_execucao_remove_pasta_temporaria(self):
        """A2/Baixo 1: mkdtemp não pode vazar em falha de download.

        Sem destino explícito, o instalador vai para uma pasta única. Se o
        download falhar antes de executar, tanto o arquivo parcial quanto
        a pasta precisam desaparecer.
        """

        base = RAIZ / "build" / "_tmp_ollama_falha"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)

        try:
            with mock.patch.object(
                setup_llm.tempfile,
                "mkdtemp",
                return_value=str(base),
            ), mock.patch.object(
                setup_llm,
                "_abrir_url",
                side_effect=OSError("TLS indisponível"),
            ):
                with self.assertRaises(setup_llm.ErroInstalacaoOllama):
                    setup_llm.baixar_instalador_ollama()

            self.assertFalse(base.exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_resumo_do_stderr_nao_despeja_texto_longo(self):
        stderr = "\n".join(
            ["Categoria: erro muito longo " * 20, "Assinatura invalida: NotSigned"]
        )

        self.assertEqual(
            setup_llm._resumir_stderr_assinatura(stderr),
            "Assinatura invalida: NotSigned",
        )

        resumo = setup_llm._resumir_stderr_assinatura("x" * 1000)

        self.assertLessEqual(len(resumo), 161)
        self.assertTrue(resumo.endswith("…"))


@unittest.skipUnless(os.name == "nt", "assinatura Authenticode é do Windows")
class TestAssinaturaInstaladorOllama(unittest.TestCase):
    """A2: o instalador só executa com assinatura Authenticode válida."""

    def test_assinatura_valida_retorna_true(self):
        resultado = mock.Mock(returncode=0, stderr="")

        with mock.patch.object(
            setup_llm.subprocess,
            "run",
            return_value=resultado,
        ) as executar:
            self.assertTrue(
                setup_llm._verificar_assinatura_instalador(
                    r"C:\Temp\OllamaSetup.exe"
                )
            )

        argumentos = executar.call_args.args[0]
        self.assertIn("Get-AuthenticodeSignature", " ".join(argumentos))
        self.assertEqual(
            executar.call_args.kwargs["env"]["NEXUSGEO_INSTALADOR"],
            r"C:\Temp\OllamaSetup.exe",
        )

    def test_assinatura_invalida_reprova(self):
        resultado = mock.Mock(returncode=1, stderr="Assinatura invalida")

        with mock.patch.object(
            setup_llm.subprocess,
            "run",
            return_value=resultado,
        ):
            with self.assertRaises(setup_llm.ErroInstalacaoOllama):
                setup_llm._verificar_assinatura_instalador(
                    r"C:\Temp\OllamaSetup.exe"
                )

    def test_instalador_nao_executa_sem_assinatura(self):
        with mock.patch.object(
            setup_llm,
            "_verificar_assinatura_instalador",
            side_effect=setup_llm.ErroInstalacaoOllama("sem assinatura"),
        ), mock.patch.object(
            setup_llm.subprocess,
            "run",
        ) as executar:
            with self.assertRaises(setup_llm.ErroInstalacaoOllama):
                setup_llm.executar_instalador_ollama(
                    r"C:\Temp\OllamaSetup.exe"
                )

        executar.assert_not_called()

    def test_destino_padrao_usa_pasta_unica(self):
        resposta = RespostaDownloadFalsa([b"a"], content_length=1)
        base = RAIZ / "build" / "nexusgeo_ollama_teste"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)

        with mock.patch.object(
            setup_llm,
            "_abrir_url",
            return_value=resposta,
        ), mock.patch.object(
            setup_llm.tempfile,
            "mkdtemp",
            return_value=str(base),
        ):
            caminho = setup_llm.baixar_instalador_ollama()

        alvo = Path(caminho)

        try:
            self.assertTrue(
                alvo.parent.name.startswith("nexusgeo_ollama_")
            )
            self.assertTrue(alvo.is_file())
        finally:
            setup_llm._remover_instalador_temporario(caminho)

        self.assertFalse(alvo.parent.exists())


@unittest.skipUnless(os.name == "nt", "instalação silenciosa é do Windows")
class TestInstalacaoSilenciosaOllama(unittest.TestCase):
    """Instalação ``/VERYSILENT /NORESTART`` e PATH da sessão."""

    def setUp(self):
        self.pasta = novo_diretorio_temporario()
        self.pasta_ollama = self.pasta / "Programs" / "Ollama"
        self.pasta_ollama.mkdir(parents=True)
        self.ollama = self.pasta_ollama / "ollama.exe"
        self.ollama.write_bytes(b"fake")
        self.instalador = self.pasta / "OllamaSetup.exe"

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_garantir_instalado_usa_which(self):
        eventos = []

        with mock.patch.dict(
            os.environ,
            {"PATH": "C:\\Windows"},
            clear=False,
        ), mock.patch.object(
            setup_llm.shutil,
            "which",
            return_value=str(self.ollama),
        ), mock.patch.object(
            setup_llm,
            "iniciar_servidor_ollama",
            return_value=True,
        ) as iniciar:
            caminho = setup_llm.garantir_ollama_instalado(
                callback_progresso=eventos.append,
            )
            path_final = os.environ["PATH"]

        self.assertEqual(caminho, str(self.ollama))
        iniciar.assert_called_once_with(setup_llm.HOST_OLLAMA_LOCAL)
        self.assertIn(
            str(self.pasta_ollama).casefold(),
            path_final.casefold(),
        )
        self.assertIn(
            "detectado",
            [evento.get("etapa") for evento in eventos],
        )
        self.assertEqual(eventos[-1]["etapa"], "pronto")

    def test_sem_ollama_baixa_e_instala_em_silencio(self):
        eventos = []

        with mock.patch.dict(
            os.environ,
            {"PATH": "C:\\Windows", "LOCALAPPDATA": str(self.pasta)},
            clear=False,
        ), mock.patch.object(
            setup_llm.shutil,
            "which",
            return_value=None,
        ), mock.patch.object(
            setup_llm,
            "localizar_ollama",
            side_effect=[None, str(self.ollama)],
        ), mock.patch.object(
            setup_llm,
            "baixar_instalador_ollama",
            return_value=str(self.instalador),
        ) as baixar, mock.patch.object(
            setup_llm,
            "_verificar_assinatura_instalador",
            return_value=True,
        ), mock.patch.object(
            setup_llm.subprocess,
            "run",
        ) as executar, mock.patch.object(
            setup_llm,
            "iniciar_servidor_ollama",
            return_value=True,
        ):
            caminho = setup_llm.garantir_ollama_instalado(
                callback_progresso=eventos.append,
            )
            path_final = os.environ["PATH"]

        self.assertEqual(caminho, str(self.ollama))
        baixar.assert_called_once()

        executar.assert_called_once()
        comando = executar.call_args.args[0]

        self.assertEqual(comando[0], str(self.instalador))
        self.assertEqual(comando[1:], ["/VERYSILENT", "/NORESTART"])
        self.assertTrue(executar.call_args.kwargs["check"])

        self.assertIn(
            str(self.pasta_ollama).casefold(),
            path_final.casefold(),
        )
        etapas = [evento.get("etapa") for evento in eventos]
        self.assertIn("instalando", etapas)
        self.assertIn("instalado", etapas)
        self.assertEqual(etapas[-1], "pronto")

    def test_falha_do_instalador_vira_erro(self):
        with mock.patch.object(
            setup_llm.shutil,
            "which",
            return_value=None,
        ), mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=None,
        ), mock.patch.object(
            setup_llm,
            "baixar_instalador_ollama",
            return_value=str(self.instalador),
        ), mock.patch.object(
            setup_llm,
            "_verificar_assinatura_instalador",
            return_value=True,
        ), mock.patch.object(
            setup_llm.subprocess,
            "run",
            side_effect=OSError("acesso negado"),
        ):
            with self.assertRaises(setup_llm.ErroInstalacaoOllama):
                setup_llm.garantir_ollama_instalado()


class TestGarantirServicoComInstalacao(unittest.TestCase):
    """A verificação do serviço instala o Ollama ausente e usa o loopback."""

    def test_instala_quando_ausente_e_verifica_loopback(self):
        eventos = []

        with mock.patch.object(
            setup_llm,
            "servico_ollama_ativo",
            side_effect=[False, True],
        ) as ativo, mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=None,
        ), mock.patch.object(
            setup_llm,
            "garantir_ollama_instalado",
            return_value=r"C:\Ollama\ollama.exe",
        ) as instalar:
            resultado = setup_llm.garantir_servico_ollama(
                callback_progresso=eventos.append,
            )

        self.assertTrue(resultado["ativo"])
        self.assertTrue(resultado["instalado"])
        instalar.assert_called_once()
        self.assertEqual(
            instalar.call_args.kwargs["callback_progresso"],
            eventos.append,
        )
        self.assertEqual(
            ativo.call_args.args[0],
            setup_llm.HOST_OLLAMA_PADRAO,
        )


# ---------------------------------------------------------------------------
# Fila de download
# ---------------------------------------------------------------------------

class TestDownload(unittest.TestCase):
    """Download sequencial em streaming com o ``/api/pull`` dublado."""

    def test_baixa_dois_modelos_em_sequencia(self):
        sessao = SessaoFalsa()
        eventos = []

        resultado = setup_llm.baixar_modelos(
            ["qwen3:4b", "qwen3:14b"],
            sessao=sessao,
            ao_progresso=eventos.append,
        )

        self.assertEqual(
            resultado["instalados"],
            ["qwen3:4b", "qwen3:14b"],
        )
        self.assertEqual(resultado["falhas"], {})
        self.assertEqual(resultado["modelo_padrao"], "qwen3:14b")

        self.assertEqual(
            [chamada["modelo"] for chamada in sessao.chamadas],
            ["qwen3:4b", "qwen3:14b"],
        )

        for chamada in sessao.chamadas:
            self.assertTrue(chamada["url"].endswith("/api/pull"))
            self.assertTrue(chamada["stream"])

        inicios = [evento for evento in eventos if evento["tipo"] == "inicio"]

        self.assertEqual(len(inicios), 2)
        self.assertEqual(inicios[0]["texto"], "Baixando 1/2: qwen3:4b...")
        self.assertEqual(inicios[1]["texto"], "Baixando 2/2: qwen3:14b...")

        progressos = [
            evento for evento in eventos if evento["tipo"] == "progresso"
        ]

        self.assertTrue(
            any(evento["percentual"] == 50.0 for evento in progressos)
        )
        self.assertEqual(eventos[-1]["tipo"], "fim")

    def test_selecao_multipla_com_os_tres(self):
        sessao = SessaoFalsa()
        eventos = []

        resultado = setup_llm.baixar_modelos(
            list(setup_llm.identificadores_modelos()),
            sessao=sessao,
            ao_progresso=eventos.append,
        )

        self.assertEqual(len(resultado["instalados"]), 3)
        self.assertEqual(len(sessao.chamadas), 3)
        self.assertEqual(
            len([evento for evento in eventos if evento["tipo"] == "inicio"]),
            3,
        )
        self.assertEqual(resultado["modelo_padrao"], "qwen3:14b")

    def test_um_modelo_so(self):
        sessao = SessaoFalsa()

        resultado = setup_llm.baixar_modelos(
            ["qwen2.5:3b"],
            sessao=sessao,
        )

        self.assertEqual(resultado["instalados"], ["qwen2.5:3b"])
        self.assertEqual(resultado["modelo_padrao"], "qwen2.5:3b")
        self.assertEqual(len(sessao.chamadas), 1)
        self.assertTrue(sessao.respostas[0].fechada)

    def test_falha_de_um_modelo_nao_interrompe_o_seguinte(self):
        sessao = SessaoFalsa(
            erros={"qwen3:4b": "model not found"},
        )
        eventos = []

        resultado = setup_llm.baixar_modelos(
            ["qwen3:4b", "qwen3:14b"],
            sessao=sessao,
            ao_progresso=eventos.append,
        )

        self.assertEqual(resultado["instalados"], ["qwen3:14b"])
        self.assertIn("qwen3:4b", resultado["falhas"])
        self.assertIn("model not found", resultado["falhas"]["qwen3:4b"])

        erros = [evento for evento in eventos if evento["tipo"] == "erro"]

        self.assertEqual(len(erros), 1)
        self.assertEqual(erros[0]["modelo"], "qwen3:4b")

    def test_http_de_erro_vira_erro_download(self):
        sessao = SessaoFalsa(status=500)

        with self.assertRaises(setup_llm.ErroDownload):
            setup_llm.baixar_modelo("qwen3:4b", sessao=sessao)

    def test_fila_vazia_recusa(self):
        with self.assertRaises(ValueError):
            setup_llm.baixar_modelos([])

    def test_modelo_fora_do_catalogo_recusa(self):
        with self.assertRaises(ValueError):
            setup_llm.baixar_modelos(["llama3:8b"])

    def test_sessao_e_fechada_mesmo_com_erro(self):
        sessao = SessaoFalsa(erros={"qwen3:4b": "boom"})

        with self.assertRaises(setup_llm.ErroDownload):
            setup_llm.baixar_modelo("qwen3:4b", sessao=sessao)

        self.assertTrue(sessao.respostas[0].fechada)


# ---------------------------------------------------------------------------
# Persistência e prioridade no config.py
# ---------------------------------------------------------------------------

class TestPersistencia(unittest.TestCase):
    """Gravação do config_local.json e leitura pelo config.py."""

    def setUp(self):
        self._pasta = novo_diretorio_temporario()
        self.caminho = self._pasta / "config_local.json"

    def tearDown(self):
        shutil.rmtree(self._pasta, ignore_errors=True)

    def _ler(self):
        return json.loads(self.caminho.read_text(encoding="utf-8"))

    def test_precisa_configurar_sem_arquivo(self):
        self.assertTrue(setup_llm.precisa_configurar(self.caminho))

    def test_persistir_grava_lista_e_padrao(self):
        dados = setup_llm.persistir_selecao(
            ["qwen2.5:3b", "qwen3:4b"],
            caminho=self.caminho,
        )

        self.assertTrue(self.caminho.is_file())
        self.assertEqual(
            dados["modelos_instalados"],
            ["qwen2.5:3b", "qwen3:4b"],
        )
        self.assertEqual(dados["modelo_padrao"], "qwen3:4b")

        lido = self._ler()

        self.assertEqual(lido["modelo_padrao"], "qwen3:4b")
        self.assertEqual(lido["versao_config"], config.VERSAO_CONFIG_LOCAL)
        self.assertIn("atualizado_em", lido)

    def test_persistir_acumula_com_forcar(self):
        setup_llm.persistir_selecao(["qwen3:4b"], caminho=self.caminho)
        dados = setup_llm.persistir_selecao(
            ["qwen3:14b"],
            caminho=self.caminho,
        )

        self.assertEqual(
            dados["modelos_instalados"],
            ["qwen3:4b", "qwen3:14b"],
        )
        self.assertEqual(dados["modelo_padrao"], "qwen3:14b")
        self.assertFalse(setup_llm.precisa_configurar(self.caminho))

    def test_persistir_sem_modelo_valido_recusa(self):
        with self.assertRaises(ValueError):
            setup_llm.persistir_selecao([], caminho=self.caminho)

        with self.assertRaises(ValueError):
            setup_llm.persistir_selecao(["llama3:8b"], caminho=self.caminho)

        self.assertFalse(self.caminho.exists())

    def test_modelos_ja_instalados(self):
        setup_llm.persistir_selecao(
            ["qwen2.5:3b"],
            caminho=self.caminho,
        )

        self.assertEqual(
            setup_llm.modelos_ja_instalados(self.caminho),
            ["qwen2.5:3b"],
        )

    def test_config_local_corrompido_nao_quebra(self):
        self.caminho.write_text("{invalido", encoding="utf-8")

        self.assertEqual(config.carregar_config_local(self.caminho), {})
        self.assertTrue(setup_llm.precisa_configurar(self.caminho))

    def test_config_local_com_bom_do_notepad(self):
        conteudo = json.dumps(
            {
                "modelos_instalados": ["qwen3:14b"],
                "modelo_padrao": "qwen3:14b",
            }
        )
        self.caminho.write_bytes(b"\xef\xbb\xbf" + conteudo.encode("utf-8"))

        self.assertEqual(
            config.carregar_config_local(self.caminho)["modelo_padrao"],
            "qwen3:14b",
        )
        self.assertFalse(setup_llm.precisa_configurar(self.caminho))


class TestEntradaPrincipal(unittest.TestCase):
    """``--forcar`` controla a abertura da janela."""

    def test_sem_forcar_e_configurado_nao_abre_interface(self):
        with mock.patch.object(
            setup_llm,
            "precisa_configurar",
            return_value=False,
        ), mock.patch.object(setup_llm, "abrir_interface") as abrir:
            self.assertEqual(setup_llm.principal([]), 0)
            abrir.assert_not_called()

    def test_sem_configuracao_abre_interface(self):
        with mock.patch.object(
            setup_llm,
            "precisa_configurar",
            return_value=True,
        ), mock.patch.object(setup_llm, "abrir_interface") as abrir:
            self.assertEqual(setup_llm.principal([]), 0)
            abrir.assert_called_once_with(forcar=False)

    def test_forcar_abre_interface_mesmo_configurado(self):
        with mock.patch.object(
            setup_llm,
            "precisa_configurar",
            return_value=False,
        ), mock.patch.object(setup_llm, "abrir_interface") as abrir:
            self.assertEqual(setup_llm.principal(["--forcar"]), 0)
            abrir.assert_called_once_with(forcar=True)

    def test_falha_da_interface_retorna_codigo_de_erro(self):
        with mock.patch.object(
            setup_llm,
            "precisa_configurar",
            return_value=True,
        ), mock.patch.object(
            setup_llm,
            "abrir_interface",
            side_effect=RuntimeError("sem display"),
        ):
            self.assertEqual(setup_llm.principal([]), 1)


class TestConfigPrioridade(unittest.TestCase):
    """Prioridade config local > ambiente > fallback, sem tocar no disco."""

    def test_config_local_vence_o_ambiente(self):
        self.assertEqual(
            config.resolver_modelo_inicial(
                {"modelo_padrao": "qwen3:14b"},
                {"OLLAMA_MODEL": "qwen2.5:3b"},
            ),
            "qwen3:14b",
        )

    def test_ambiente_vence_o_fallback(self):
        self.assertEqual(
            config.resolver_modelo_inicial({}, {"OLLAMA_MODEL": "qwen2.5:3b"}),
            "qwen2.5:3b",
        )

    def test_fallback_qwen3_4b(self):
        self.assertEqual(
            config.resolver_modelo_inicial({}, {}),
            config.MODELO_FALLBACK,
        )
        self.assertEqual(config.MODELO_FALLBACK, "qwen3:4b")

    def test_prioridade_por_lista_sem_padrao(self):
        self.assertEqual(
            config.modelo_padrao_do_config(
                {"modelos_instalados": ["qwen2.5:3b", "qwen3:14b"]}
            ),
            "qwen3:14b",
        )

    def test_config_local_do_ambiente_de_teste(self):
        pasta = novo_diretorio_temporario()

        try:
            caminho = pasta / "config_local.json"

            config.salvar_config_local(
                {
                    "modelos_instalados": ["qwen3:4b"],
                    "modelo_padrao": "qwen3:4b",
                },
                caminho,
            )

            self.assertEqual(
                config.carregar_config_local(caminho)["modelo_padrao"],
                "qwen3:4b",
            )
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_normalizar_lista_modelos(self):
        self.assertEqual(
            config.normalizar_lista_modelos(
                [" qwen3:4b ", "", "qwen3:4b", None]
            ),
            ["qwen3:4b"],
        )
        self.assertEqual(config.normalizar_lista_modelos("qwen3:4b"), ["qwen3:4b"])
        self.assertEqual(config.normalizar_lista_modelos(None), [])


# ---------------------------------------------------------------------------
# Interface Tkinter: grade de 4 colunas e janela oculta
# ---------------------------------------------------------------------------

def _tkinter_disponivel():
    """Diz se a janela Tk pode ser criada neste ambiente."""

    try:
        import tkinter as tk

        raiz = tk.Tk()
        raiz.withdraw()
        raiz.destroy()
    except Exception:
        return False

    return True


def _filhos_recursivos(widget):
    """Percorre a árvore de widgets (Tk não expõe isso pronto)."""

    for filho in widget.winfo_children():
        yield filho

        yield from _filhos_recursivos(filho)


@unittest.skipUnless(
    _tkinter_disponivel(),
    "Tkinter/display indisponível para montar a janela oculta",
)
class TestGradeTabelaModelos(unittest.TestCase):
    """Cabeçalho e linhas compartilham minsize, padx e alinhamento."""

    def setUp(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.raiz = tk.Tk()
        self.raiz.withdraw()

        estilo = ttk.Style(master=self.raiz)
        estilo.configure("Cabecalho.TLabel", font=("Segoe UI", 10, "bold"))

        self.interior = ttk.Frame(self.raiz)
        self.interior.pack()

        self.variaveis = {
            identificador: tk.BooleanVar(master=self.raiz, value=False)
            for identificador in setup_llm.identificadores_modelos()
        }

        self.linhas = setup_llm.montar_tabela_modelos(
            self.interior,
            idioma="pt",
            variaveis=self.variaveis,
            recomendados=["qwen3:4b"],
        )

    def tearDown(self):
        try:
            self.raiz.destroy()
        except Exception:
            pass

    def test_minsize_e_peso_das_quatro_colunas(self):
        esperado = (135, 250, 105, 390)

        for indice, largura in enumerate(esperado):
            with self.subTest(coluna=indice):
                self.assertEqual(
                    int(
                        self.interior.grid_columnconfigure(
                            indice, "minsize"
                        )
                    ),
                    largura,
                )

        self.assertEqual(
            int(self.interior.grid_columnconfigure(3, "weight")),
            1,
        )
        self.assertEqual(
            int(self.interior.grid_columnconfigure(2, "weight")),
            0,
        )

    def test_cabecalho_e_linhas_usam_o_mesmo_padx(self):
        cabecalhos = [
            widget
            for widget in self.interior.winfo_children()
            if int(widget.grid_info().get("row", -1)) == 0
        ]

        self.assertEqual(len(cabecalhos), 4)
        self.assertEqual(
            [int(widget.grid_info()["column"]) for widget in cabecalhos],
            [0, 1, 2, 3],
        )

        for widget in cabecalhos:
            self.assertEqual(int(widget.grid_info()["padx"]), 8)

        for linha in self.linhas:
            check, perfil, ram, comportamento = linha
            caixa = check.master

            self.assertEqual(int(caixa.grid_info()["column"]), 0)
            self.assertEqual(int(caixa.grid_info()["padx"]), 8)

            for widget, coluna in (
                (perfil, 1),
                (ram, 2),
                (comportamento, 3),
            ):
                with self.subTest(coluna=coluna):
                    self.assertEqual(
                        int(widget.grid_info()["column"]), coluna
                    )
                    self.assertEqual(
                        int(widget.grid_info()["padx"]), 8
                    )
                    self.assertEqual(
                        widget.grid_info()["sticky"], "nw"
                    )

    def test_ram_alinhada_sob_o_titulo_e_sem_largura_fixa(self):
        self.assertEqual(
            [ram.cget("text") for _, _, ram, _ in self.linhas],
            ["~2,6 GB", "~9,0 GB", "~1,9 GB"],
        )

        for _, _, ram, _ in self.linhas:
            self.assertNotEqual(int(ram.cget("width") or 0), 12)
            self.assertEqual(str(ram.cget("anchor")), "w")

    def test_perfil_e_comportamento_com_wraplength(self):
        for _, perfil, _, comportamento in self.linhas:
            self.assertEqual(int(perfil.cget("wraplength")), 235)
            self.assertEqual(str(perfil.cget("justify")), "left")
            self.assertEqual(str(perfil.cget("anchor")), "w")

            self.assertEqual(
                int(comportamento.cget("wraplength")), 375
            )
            self.assertEqual(
                str(comportamento.cget("justify")), "left"
            )
            self.assertEqual(
                str(comportamento.cget("anchor")), "w"
            )

    def test_tag_recomendado_apenas_no_modelo_previsto(self):
        self.assertEqual(
            setup_llm.texto_tag_recomendado("pt"),
            "[Recomendado]",
        )
        self.assertEqual(
            setup_llm.texto_tag_recomendado("en"),
            "[Recommended]",
        )

        encontrados = {}

        for (check, *_), identificador in zip(
            self.linhas, setup_llm.identificadores_modelos()
        ):
            textos = [
                str(filho.cget("text"))
                for filho in check.master.winfo_children()
                if hasattr(filho, "cget")
            ]
            encontrados[identificador] = "[Recomendado]" in textos

        self.assertTrue(encontrados["qwen3:4b"])
        self.assertFalse(encontrados["qwen3:14b"])
        self.assertFalse(encontrados["qwen2.5:3b"])

    def test_remontagem_troca_o_idioma_da_tag(self):
        self.linhas = setup_llm.montar_tabela_modelos(
            self.interior,
            idioma="en",
            variaveis=self.variaveis,
            recomendados=["qwen2.5:3b"],
        )

        textos = [
            str(filho.cget("text"))
            for filho in self.linhas[2][0].master.winfo_children()
            if hasattr(filho, "cget")
        ]

        self.assertIn("[Recommended]", textos)
        self.assertNotIn("[Recomendado]", textos)


@unittest.skipUnless(
    _tkinter_disponivel(),
    "Tkinter/display indisponível para o smoke test da janela",
)
class TestJanelaOcultaSetupLlm(unittest.TestCase):
    """``abrir_interface(oculta=True)`` monta a janela sem exibi-la."""

    def test_abre_e_fecha_com_tabela_na_grade(self):
        import tkinter as tk
        from tkinter import ttk

        capturado = {}

        def mainloop_imediato(raiz_tk):
            try:
                raiz_tk.update_idletasks()

                canvas = next(
                    widget
                    for widget in _filhos_recursivos(raiz_tk)
                    if isinstance(widget, tk.Canvas)
                )
                capturado["altura_canvas"] = int(canvas.cget("height"))

                janelas = canvas.find_all()
                interior = raiz_tk.nametowidget(
                    canvas.itemcget(janelas[0], "window")
                )
                capturado["minsizes"] = [
                    int(interior.grid_columnconfigure(i, "minsize"))
                    for i in range(4)
                ]
                capturado["peso_coluna_3"] = int(
                    interior.grid_columnconfigure(3, "weight")
                )
                capturado["rotulos"] = [
                    str(widget.cget("text"))
                    for widget in _filhos_recursivos(interior)
                    if isinstance(widget, ttk.Label)
                ]
            finally:
                raiz_tk.destroy()

        with mock.patch.object(
            setup_llm, "memoria_total_gb", return_value=16.0
        ), mock.patch.object(
            setup_llm, "modelos_ja_instalados", return_value=[]
        ), mock.patch.object(
            tk.Tk, "mainloop", mainloop_imediato
        ):
            setup_llm.abrir_interface(oculta=True)

        self.assertEqual(capturado["altura_canvas"], 260)
        self.assertEqual(
            capturado["minsizes"], [135, 250, 105, 390]
        )
        self.assertEqual(capturado["peso_coluna_3"], 1)
        self.assertIn("[Recomendado]", capturado["rotulos"])
        self.assertIn("qwen3:4b", capturado["rotulos"])


if __name__ == "__main__":
    unittest.main()
