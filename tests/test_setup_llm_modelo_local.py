"""Testes do registro automático do modelo fine-tuned local (GGUF).

Cobrem a substituição da linha FROM do template, a montagem do comando
ollama create, a remoção do Modelfile temporário e a ausência
silenciosa quando o GGUF/template não existem. Nenhum Ollama é chamado.
"""

import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import setup_llm

PASTA_TESTE = Path(__file__).resolve().parent / "_tmp_setup_modelo_local"


def _pasta_temporaria():
    PASTA_TESTE.mkdir(parents=True, exist_ok=True)
    pasta = PASTA_TESTE / uuid.uuid4().hex
    pasta.mkdir()
    return pasta


class TestModelfileComGguf(unittest.TestCase):
    """Só a linha FROM é trocada; o BOM do template não atrapalha."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(PASTA_TESTE, ignore_errors=True)

    def test_troca_apenas_a_linha_from(self):
        pasta = _pasta_temporaria()
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

        template = pasta / "Modelfile"
        template.write_text(
            "\ufeffFROM caminho/antigo.gguf\n"
            "TEMPLATE \"\"\"FROM texto interno\"\"\"\n"
            "PARAMETER temperature 0\n",
            encoding="utf-8",
        )

        gguf = pasta / "modelo.gguf"
        gguf.write_bytes(b"gguf")

        conteudo = setup_llm._modelfile_com_gguf(template, gguf)
        linhas = conteudo.splitlines()

        self.assertEqual(
            linhas[0],
            f"FROM {gguf.resolve()}",
        )
        self.assertEqual(
            linhas[1],
            'TEMPLATE """FROM texto interno"""',
        )
        self.assertEqual(linhas[2], "PARAMETER temperature 0")

    def test_template_sem_from_falha(self):
        pasta = _pasta_temporaria()
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

        template = pasta / "Modelfile"
        template.write_text("PARAMETER temperature 0\n", encoding="utf-8")
        gguf = pasta / "modelo.gguf"
        gguf.write_bytes(b"gguf")

        with self.assertRaises(ValueError):
            setup_llm._modelfile_com_gguf(template, gguf)


class TestRegistrarModeloLocal(unittest.TestCase):
    """ollama create recebe um Modelfile temporário e ele é removido."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(PASTA_TESTE, ignore_errors=True)

    def _arquivos(self):
        pasta = _pasta_temporaria()
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

        gguf = pasta / "nexusgeo-qwen3-4b-v2-Q4_K_M.gguf"
        gguf.write_bytes(b"gguf")

        template = pasta / "Modelfile.template"
        template.write_text(
            "\ufeffFROM antigo\nPARAMETER seed 42\n",
            encoding="utf-8",
        )

        return pasta, gguf, template

    def test_sem_gguf_nao_chama_ollama(self):
        with mock.patch.object(
            setup_llm,
            "subprocess",
        ) as subprocesso, mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=r"C:\Ollama\ollama.exe",
        ):
            resultado = setup_llm.registrar_modelo_local(
                gguf=Path("inexistente.gguf"),
                modelfile=Path("inexistente.Modelfile"),
            )

        self.assertIsNone(resultado)
        subprocesso.run.assert_not_called()

    def test_monta_comando_e_remove_temporario(self):
        pasta, gguf, template = self._arquivos()
        capturado = {}

        def executar(comando, **opcoes):
            capturado["comando"] = list(comando)
            capturado["temporario"] = Path(comando[-1])
            capturado["existia"] = Path(comando[-1]).is_file()
            capturado["opcoes"] = opcoes

            return SimpleNamespace(returncode=0, stdout="", stderr="")

        eventos = []
        (pasta / "temp").mkdir()

        with mock.patch.object(
            setup_llm,
            "subprocess",
        ) as subprocesso, mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=r"C:\Ollama\ollama.exe",
        ), mock.patch.object(
            setup_llm.tempfile,
            "mkdtemp",
            return_value=str(pasta / "temp"),
        ):
            subprocesso.run.side_effect = executar
            subprocesso.SubprocessError = Exception

            resultado = setup_llm.registrar_modelo_local(
                gguf=gguf,
                modelfile=template,
                ao_progresso=eventos.append,
            )

        self.assertEqual(resultado, setup_llm.NOME_MODELO_LOCAL)
        self.assertEqual(
            capturado["comando"][:3],
            [
                r"C:\Ollama\ollama.exe",
                "create",
                setup_llm.NOME_MODELO_LOCAL,
            ],
        )
        self.assertEqual(capturado["comando"][3], "-f")
        self.assertTrue(capturado["existia"])
        self.assertFalse(
            capturado["temporario"].exists(),
            "o Modelfile temporário deve ser removido ao final",
        )
        self.assertIn("check", capturado["opcoes"])
        self.assertFalse(capturado["opcoes"]["check"])
        self.assertIn("timeout", capturado["opcoes"])
        self.assertEqual(
            [evento["etapa"] for evento in eventos],
            ["registrando", "registrado"],
        )

    def test_falha_do_ollama_devolve_none(self):
        _pasta, gguf, template = self._arquivos()

        with mock.patch.object(
            setup_llm,
            "subprocess",
        ) as subprocesso, mock.patch.object(
            setup_llm,
            "localizar_ollama",
            return_value=r"C:\Ollama\ollama.exe",
        ):
            subprocesso.run.return_value = SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="erro de importação",
            )
            subprocesso.SubprocessError = Exception

            resultado = setup_llm.registrar_modelo_local(
                gguf=gguf,
                modelfile=template,
            )

        self.assertIsNone(resultado)


if __name__ == "__main__":
    unittest.main()
