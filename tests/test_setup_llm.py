"""Testes offline do configurador do modelo local (``setup_llm.py``).

Cobrem o fluxo único do modelo oficial da v1.0.0, o download atômico do
GGUF, o fallback técnico ``qwen3:4b``, a persistência em
``config_local.json`` e a prioridade de leitura em ``config.py``.
Nenhum teste abre janela, acessa a rede, executa o Ollama ou usa
navegador.
"""

import inspect
import io
import json
import os
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
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
# Fluxo único do modelo oficial (v1.0.0)
# ---------------------------------------------------------------------------

class TestModeloUnico(unittest.TestCase):
    """Não existe catálogo: só o modelo oficial e o fallback técnico."""

    def test_modelo_oficial_e_fallback_tecnico(self):
        self.assertEqual(
            setup_llm.NOME_MODELO_LOCAL,
            "nexusgeo-qwen3-4b-v2-q4",
        )
        self.assertEqual(setup_llm.ARQUIVO_GGUF_LOCAL, "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf")
        self.assertEqual(setup_llm.MODELO_TECNICO_FALLBACK, "qwen3:4b")

    def test_catalogo_antigo_nao_existe_mais(self):
        for atributo in (
            "CATALOGO_MODELOS",
            "ModeloLLM",
            "identificadores_modelos",
            "obter_modelo",
            "normalizar_modelos",
            "modelos_iniciais",
            "estimar_ram_gb",
            "modelo_padrao",
            "interpretar_escolha_cli",
            "executar_seletor_cli",
            "montar_tabela_modelos",
            "memoria_total_gb",
            "formatar_ram",
        ):
            with self.subTest(atributo=atributo):
                self.assertFalse(hasattr(setup_llm, atributo))

    def test_url_oficial_do_gguf(self):
        self.assertTrue(
            setup_llm.URL_GGUF_OFICIAL.startswith(
                "https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases/"
            )
        )
        self.assertTrue(
            setup_llm.URL_GGUF_OFICIAL.endswith(
                "/v1.0.0/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
            )
        )

    def test_formatar_mb_pt_e_en(self):
        self.assertEqual(setup_llm.formatar_mb(1024 * 1024, "pt"), "1,0 MB")
        self.assertEqual(setup_llm.formatar_mb(1024 * 1024, "en"), "1.0 MB")
        self.assertEqual(setup_llm.formatar_mb(None, "pt"), "—")

    def test_nome_base_modelo(self):
        self.assertEqual(
            setup_llm.nome_base_modelo("nexusgeo-qwen3-4b-v2-q4:latest"),
            "nexusgeo-qwen3-4b-v2-q4",
        )
        self.assertEqual(
            setup_llm.nome_base_modelo("qwen3:4b"),
            "qwen3",
        )
        self.assertEqual(setup_llm.nome_base_modelo(None), "")

    def test_textos_pt_e_en_paridade(self):
        self.assertEqual(
            set(setup_llm.TEXTOS["pt"]),
            set(setup_llm.TEXTOS["en"]),
        )

        for idioma in ("pt", "en"):
            with self.subTest(idioma=idioma):
                self.assertIn(
                    "nexusgeo-qwen3-4b-v2-q4",
                    setup_llm.texto("subtitulo", idioma),
                )
                self.assertNotIn(
                    "três modelos",
                    setup_llm.texto("subtitulo", idioma).lower(),
                )

    def test_modelo_local_registrado(self):
        with mock.patch.object(
            setup_llm,
            "modelos_instalados",
            return_value=["qwen3:4b"],
        ):
            self.assertFalse(setup_llm.modelo_local_registrado())

        with mock.patch.object(
            setup_llm,
            "modelos_instalados",
            return_value=["nexusgeo-qwen3-4b-v2-q4:latest"],
        ):
            self.assertTrue(setup_llm.modelo_local_registrado())

        with mock.patch.object(
            setup_llm,
            "modelos_instalados",
            return_value=["nexusgeo-qwen3-4b-v2-q4", "qwen3:4b"],
        ):
            self.assertTrue(setup_llm.modelo_local_registrado())

        with mock.patch.object(
            setup_llm,
            "modelos_instalados",
            side_effect=OSError("offline"),
        ):
            self.assertFalse(setup_llm.modelo_local_registrado())


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
                    {"model": "nexusgeo-qwen3-4b-v2-q4"},
                    {"name": ""},
                    "ignorado",
                ]
            },
        ):
            self.assertEqual(
                setup_llm.modelos_instalados(),
                ["qwen3:4b", "nexusgeo-qwen3-4b-v2-q4"],
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
            ["qwen3:4b", "nexusgeo-qwen3-4b-v2-q4"],
            sessao=sessao,
            ao_progresso=eventos.append,
            idioma="pt",
        )

        # O segundo modelo continua baixando normalmente.
        self.assertEqual(
            resultado["instalados"],
            ["nexusgeo-qwen3-4b-v2-q4"],
        )

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


class TestInterfaceSemCatalogo(unittest.TestCase):
    """A janela v1.0.0 não tem checkboxes, tabela nem sugestão por RAM."""

    def test_janela_nao_tem_checkbox_nem_catalogo(self):
        codigo = inspect.getsource(setup_llm.abrir_interface)

        for proibido in (
            "Checkbutton",
            "CATALOGO_MODELOS",
            "modelos_iniciais",
            "memoria_total_gb",
            "estimar_ram_gb",
        ):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, codigo)

        self.assertIn("Progressbar", codigo)
        self.assertIn("garantir_modelo_oficial", codigo)

    def test_interface_tem_apenas_fluxo_unico(self):
        codigo = inspect.getsource(setup_llm.principal)

        self.assertIn("modelo_local_registrado", codigo)
        self.assertIn("caminho_gguf_local", codigo)
        self.assertIn("abrir_interface", codigo)
        self.assertNotIn("seletor", codigo)


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

# ---------------------------------------------------------------------------
# Download do GGUF oficial e persistência do modelo único
# ---------------------------------------------------------------------------

class RespostaGgufFalsa:
    """Resposta binária mínima compatível com ``baixar_gguf_oficial``."""

    def __init__(self, blocos, total=None, falhar_em=None):
        self._blocos = list(blocos)
        self._falhar_em = falhar_em
        self.headers = {}
        if total is not None:
            self.headers["Content-Length"] = str(total)
        self.fechada = False
        self.lido = 0

    def read(self, tamanho=None):
        self.lido += 1

        if self._falhar_em is not None and self.lido >= self._falhar_em:
            raise OSError("conexão interrompida")

        if not self._blocos:
            return b""

        return self._blocos.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.fechada = True
        return False


def _abrir_com(resposta):
    return lambda _url: resposta


class TestDownloadGgufOficial(unittest.TestCase):
    """Download atômico do GGUF com progresso e limpeza do parcial."""

    def setUp(self):
        self._pasta = novo_diretorio_temporario()
        self.destino = self._pasta / "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"

    def tearDown(self):
        shutil.rmtree(self._pasta, ignore_errors=True)

    def test_baixa_e_reporta_progresso(self):
        blocos = [b"a" * 1024, b"b" * 1024, b""]
        resposta = RespostaGgufFalsa(blocos, total=2048)
        eventos = []

        caminho = setup_llm.baixar_gguf_oficial(
            destino=self.destino,
            ao_progresso=eventos.append,
            abrir=_abrir_com(resposta),
        )

        self.assertEqual(caminho, self.destino)
        self.assertEqual(self.destino.read_bytes(), b"a" * 1024 + b"b" * 1024)
        self.assertFalse(
            (self._pasta / (self.destino.name + ".part")).exists()
        )
        self.assertGreaterEqual(len(eventos), 2)
        self.assertEqual(eventos[-1]["baixado_bytes"], 2048)
        self.assertEqual(eventos[-1]["percentual"], 100.0)

    def test_falha_de_rede_remove_o_parcial(self):
        resposta = RespostaGgufFalsa(
            [b"a" * 512],
            total=2048,
            falhar_em=2,
        )

        with self.assertRaises(setup_llm.ErroDownload):
            setup_llm.baixar_gguf_oficial(
                destino=self.destino,
                abrir=_abrir_com(resposta),
            )

        self.assertFalse(self.destino.exists())
        self.assertFalse(
            (self._pasta / (self.destino.name + ".part")).exists()
        )

    def test_download_vazio_falha(self):
        with self.assertRaises(setup_llm.ErroDownload):
            setup_llm.baixar_gguf_oficial(
                destino=self.destino,
                abrir=_abrir_com(RespostaGgufFalsa([])),
            )

        self.assertFalse(self.destino.exists())


class TestPersistenciaModeloUnico(unittest.TestCase):
    """O config_local.json grava o modelo único e o ``modelo_ollama``."""

    def setUp(self):
        self._pasta = novo_diretorio_temporario()
        self.caminho = self._pasta / "config_local.json"

    def tearDown(self):
        shutil.rmtree(self._pasta, ignore_errors=True)

    def _ler(self):
        return json.loads(self.caminho.read_text(encoding="utf-8"))

    def test_persistir_modelo_oficial(self):
        dados = setup_llm.persistir_modelo(caminho=self.caminho)

        self.assertEqual(dados["modelo_ollama"], setup_llm.NOME_MODELO_LOCAL)
        self.assertEqual(dados["modelo_padrao"], setup_llm.NOME_MODELO_LOCAL)
        self.assertEqual(
            dados["modelos_instalados"],
            [setup_llm.NOME_MODELO_LOCAL],
        )
        self.assertEqual(dados["versao_config"], config.VERSAO_CONFIG_LOCAL)
        self.assertIn("atualizado_em", dados)

    def test_persistir_fallback_tecnico(self):
        dados = setup_llm.persistir_modelo(
            setup_llm.MODELO_TECNICO_FALLBACK,
            caminho=self.caminho,
        )

        self.assertEqual(dados["modelo_ollama"], "qwen3:4b")
        self.assertEqual(dados["modelo_padrao"], "qwen3:4b")

    def test_persistir_acumula_sem_duplicar(self):
        setup_llm.persistir_modelo(caminho=self.caminho)
        dados = setup_llm.persistir_modelo(
            setup_llm.MODELO_TECNICO_FALLBACK,
            caminho=self.caminho,
        )

        self.assertEqual(
            dados["modelos_instalados"],
            [setup_llm.MODELO_TECNICO_FALLBACK, setup_llm.NOME_MODELO_LOCAL],
        )
        self.assertEqual(dados["modelo_padrao"], setup_llm.MODELO_TECNICO_FALLBACK)

    def test_persistir_rejeita_modelo_vazio(self):
        with self.assertRaises(ValueError):
            setup_llm.persistir_modelo("", caminho=self.caminho)

        self.assertFalse(self.caminho.exists())

    def test_precisa_configurar(self):
        self.assertTrue(setup_llm.precisa_configurar(self.caminho))

        setup_llm.persistir_modelo(caminho=self.caminho)

        self.assertFalse(setup_llm.precisa_configurar(self.caminho))
        self.assertEqual(
            setup_llm.modelos_ja_instalados(self.caminho),
            [setup_llm.NOME_MODELO_LOCAL],
        )

    def test_modelo_ollama_alimenta_o_config(self):
        self.caminho.write_text(
            json.dumps({"modelo_ollama": "qwen3:4b"}),
            encoding="utf-8",
        )

        self.assertEqual(
            config.modelo_padrao_do_config(
                config.carregar_config_local(self.caminho)
            ),
            "qwen3:4b",
        )


class TestFluxoModeloOficial(unittest.TestCase):
    """Ordem registrado -> GGUF local -> download -> fallback técnico."""

    def setUp(self):
        self._pasta = novo_diretorio_temporario()
        self.gguf = self._pasta / setup_llm.ARQUIVO_GGUF_LOCAL
        self.eventos = []

    def tearDown(self):
        shutil.rmtree(self._pasta, ignore_errors=True)

    def _fluxo(self, servico=None):
        with mock.patch.object(
            setup_llm,
            "garantir_servico_ollama",
            return_value=servico or {"ativo": True},
        ):
            return setup_llm.garantir_modelo_oficial(
                ao_progresso=self.eventos.append,
            )

    def test_modelo_ja_registrado_nao_baixa(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=True
        ), mock.patch.object(
            setup_llm, "persistir_modelo", return_value={"modelo_padrao": setup_llm.NOME_MODELO_LOCAL}
        ) as persistir, mock.patch.object(
            setup_llm, "baixar_gguf_oficial"
        ) as baixar, mock.patch.object(
            setup_llm, "registrar_modelo_local"
        ) as registrar:
            resultado = self._fluxo()

        self.assertEqual(resultado["origem"], "registrado")
        self.assertEqual(resultado["modelo"], setup_llm.NOME_MODELO_LOCAL)
        persistir.assert_called_once_with(setup_llm.NOME_MODELO_LOCAL)
        baixar.assert_not_called()
        registrar.assert_not_called()
        self.assertEqual(self.eventos[-1]["tipo"], "finalizado")

    def test_gguf_local_e_registrado(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=self.gguf
        ), mock.patch.object(
            setup_llm, "registrar_modelo_local", return_value=setup_llm.NOME_MODELO_LOCAL
        ) as registrar, mock.patch.object(
            setup_llm, "persistir_modelo", return_value={}
        ), mock.patch.object(
            setup_llm, "baixar_gguf_oficial"
        ) as baixar:
            resultado = self._fluxo()

        self.assertEqual(resultado["origem"], "gguf")
        registrar.assert_called_once()
        self.assertEqual(registrar.call_args.kwargs["gguf"], self.gguf)
        baixar.assert_not_called()

    def test_gguf_ausente_baixa_e_registra(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "baixar_gguf_oficial", return_value=self.gguf
        ) as baixar, mock.patch.object(
            setup_llm, "registrar_modelo_local", return_value=setup_llm.NOME_MODELO_LOCAL
        ), mock.patch.object(
            setup_llm, "persistir_modelo", return_value={}
        ):
            resultado = self._fluxo()

        self.assertEqual(resultado["origem"], "gguf")
        baixar.assert_called_once()

    def test_falha_de_download_usa_fallback_tecnico(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "baixar_gguf_oficial", side_effect=setup_llm.ErroDownload("sem rede")
        ), mock.patch.object(
            setup_llm, "baixar_modelo"
        ) as baixar_modelo, mock.patch.object(
            setup_llm, "persistir_modelo", return_value={}
        ) as persistir:
            resultado = self._fluxo()

        self.assertEqual(resultado["origem"], "fallback")
        self.assertEqual(resultado["modelo"], "qwen3:4b")
        baixar_modelo.assert_called_once()
        self.assertEqual(baixar_modelo.call_args.args[0], "qwen3:4b")
        persistir.assert_called_once_with("qwen3:4b")

    def test_falha_do_ollama_create_usa_fallback(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=self.gguf
        ), mock.patch.object(
            setup_llm, "registrar_modelo_local", return_value=None
        ), mock.patch.object(
            setup_llm, "baixar_modelo"
        ) as baixar_modelo, mock.patch.object(
            setup_llm, "persistir_modelo", return_value={}
        ):
            resultado = self._fluxo()

        self.assertEqual(resultado["origem"], "fallback")
        self.assertEqual(baixar_modelo.call_args.args[0], "qwen3:4b")

    def test_ollama_indisponivel_levanta_erro(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ):
            with self.assertRaises(setup_llm.ErroDownload):
                self._fluxo({"ativo": False, "mensagem": "sem Ollama"})

    def test_fallback_que_falha_levanta_erro(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "baixar_gguf_oficial", side_effect=setup_llm.ErroDownload("sem rede")
        ), mock.patch.object(
            setup_llm, "baixar_modelo", side_effect=RuntimeError("Ollama offline")
        ):
            with self.assertRaises(setup_llm.ErroDownload):
                self._fluxo()


class TestEntradaPrincipal(unittest.TestCase):
    """O ``--forcar`` controla o atalho e a janela de download."""

    def test_modelo_registrado_nao_abre_interface(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=True
        ), mock.patch.object(
            setup_llm, "persistir_modelo"
        ) as persistir, mock.patch.object(
            setup_llm, "abrir_interface"
        ) as abrir:
            self.assertEqual(setup_llm.principal([]), 0)

        persistir.assert_called_once_with(setup_llm.NOME_MODELO_LOCAL)
        abrir.assert_not_called()

    def test_forcar_refaz_registro_sem_interface(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=True
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=Path("gguf.gguf")
        ), mock.patch.object(
            setup_llm, "registrar_modelo_local", return_value=setup_llm.NOME_MODELO_LOCAL
        ), mock.patch.object(
            setup_llm, "persistir_modelo"
        ) as persistir, mock.patch.object(
            setup_llm, "abrir_interface"
        ) as abrir:
            self.assertEqual(setup_llm.principal(["--forcar"]), 0)

        persistir.assert_called_once_with(setup_llm.NOME_MODELO_LOCAL)
        abrir.assert_not_called()

    def test_sem_gguf_usa_interface(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=True
        ), mock.patch.object(setup_llm, "abrir_interface") as abrir:
            self.assertEqual(setup_llm.principal([]), 0)

        abrir.assert_called_once_with(forcar=False)

    def test_sem_tkinter_cai_para_cli(self):
        with mock.patch.object(
            setup_llm, "modelo_local_registrado", return_value=False
        ), mock.patch.object(
            setup_llm, "caminho_gguf_local", return_value=None
        ), mock.patch.object(
            setup_llm, "tkinter_disponivel", return_value=False
        ), mock.patch.object(
            setup_llm, "executar_fluxo_cli", return_value=0
        ) as cli:
            self.assertEqual(setup_llm.principal([]), 0)

        cli.assert_called_once_with(forcar=False)

    def test_falha_da_interface_retorna_codigo_de_erro(self):
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
        ):
            self.assertEqual(setup_llm.principal([]), 1)


class TestFluxoCli(unittest.TestCase):
    """O terminal executa o mesmo fluxo único e grava a configuração."""

    def test_cli_sucesso(self):
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
            codigo = setup_llm.executar_fluxo_cli()

        self.assertEqual(codigo, 0)
        garantir.assert_called_once_with(
            forcar=False,
            idioma="pt",
            ao_progresso=mock.ANY,
        )
        self.assertIn("config_local.json", saida.getvalue())

    def test_cli_falha(self):
        saida = io.StringIO()

        with mock.patch.object(
            setup_llm,
            "garantir_modelo_oficial",
            side_effect=setup_llm.ErroDownload("sem rede"),
        ), redirect_stdout(saida):
            codigo = setup_llm.executar_fluxo_cli()

        self.assertEqual(codigo, 1)
        self.assertIn("sem rede", saida.getvalue())


class TestConfigPrioridade(unittest.TestCase):
    """Prioridade config local > ambiente > fallback, sem tocar no disco."""

    def test_config_local_vence_o_ambiente(self):
        self.assertEqual(
            config.resolver_modelo_inicial(
                {"modelo_padrao": "nexusgeo-qwen3-4b-v2-q4"},
                {"OLLAMA_MODEL": "qwen3:4b"},
            ),
            "nexusgeo-qwen3-4b-v2-q4",
        )

    def test_ambiente_vence_o_fallback(self):
        self.assertEqual(
            config.resolver_modelo_inicial({}, {"OLLAMA_MODEL": "qwen3:4b"}),
            "qwen3:4b",
        )

    def test_fallback_qwen3_4b(self):
        self.assertEqual(
            config.resolver_modelo_inicial({}, {}),
            config.MODELO_FALLBACK,
        )
        self.assertEqual(config.MODELO_FALLBACK, "qwen3:4b")

    def test_prioridade_do_modelo_oficial(self):
        self.assertEqual(
            config.modelo_padrao_do_config(
                {
                    "modelos_instalados": [
                        "qwen3:4b",
                        "nexusgeo-qwen3-4b-v2-q4",
                    ]
                }
            ),
            "nexusgeo-qwen3-4b-v2-q4",
        )
        self.assertEqual(
            config.modelo_padrao_do_config(
                {"modelos_instalados": ["qwen3:4b"]}
            ),
            "qwen3:4b",
        )
        self.assertEqual(
            config.PRIORIDADE_MODELOS_PADRAO,
            ("nexusgeo-qwen3-4b-v2-q4", "qwen3:4b"),
        )

    def test_normalizar_lista_modelos(self):
        self.assertEqual(
            config.normalizar_lista_modelos(
                [" qwen3:4b ", "", "qwen3:4b", None]
            ),
            ["qwen3:4b"],
        )
        self.assertEqual(config.normalizar_lista_modelos("qwen3:4b"), ["qwen3:4b"])
        self.assertEqual(config.normalizar_lista_modelos(None), [])


if __name__ == "__main__":
    unittest.main()
