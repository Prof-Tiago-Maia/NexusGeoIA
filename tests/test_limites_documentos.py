"""Testes dos limites de entrada de documentos (M1).

Um PDF/arquivo grande não pode consumir memória e CPU sem limite antes
de ser recusado. Os testes usam arquivos pequenos e objetos falsos; não
abrem PDF real, não fazem OCR e não acessam a rede.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from services import document_parser

RAIZ = Path(__file__).resolve().parent.parent


class TestLimitesDocumentos(unittest.TestCase):
    """Limites de tamanho e de páginas do parser."""

    def setUp(self):
        self.base = RAIZ / "build" / "_tmp_limites_documentos"
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_arquivo_acima_do_limite_e_recusado(self):
        caminho = self.base / "grande.txt"
        caminho.write_text("x" * 64, encoding="utf-8")

        with mock.patch.object(
            document_parser,
            "TAMANHO_MAXIMO_ARQUIVO",
            32,
        ):
            with self.assertRaises(document_parser.ErroConversao):
                document_parser.converter_arquivo(caminho)

    def test_arquivo_dentro_do_limite_continua_valido(self):
        caminho = self.base / "ok.txt"
        caminho.write_text("granito", encoding="utf-8")

        resultado = document_parser.converter_arquivo(caminho)

        self.assertIn("granito", resultado.markdown)

    def test_parser_e_mensagem_de_limite_sem_carregar_streamlit(self):
        """O parsing não pode importar o runtime da interface (M1).

        Roda em subprocesso para medir ``sys.modules`` antes de qualquer
        import do projeto: o teste garante que importar o parser e recusar
        um arquivo grande não carrega streamlit nem exige ScriptRunContext.
        """

        codigo = (
            "import sys\n"
            "import services.document_parser as p\n"
            "from utils.i18n import TEXTOS_I18N\n"
            "assert 'streamlit' not in sys.modules, 'streamlit importado'\n"
            "alvo = __import__('pathlib').Path("
            "'build/_tmp_streamlit_limite.txt')\n"
            "alvo.write_text('x' * 64, encoding='utf-8')\n"
            "p.TAMANHO_MAXIMO_ARQUIVO = 8\n"
            "try:\n"
            "    p.converter_arquivo(alvo)\n"
            "except p.ErroConversao as erro:\n"
            "    assert 'streamlit' not in sys.modules, (\n"
            "        'streamlit importado durante o limite'\n"
            "    )\n"
            "    esperado = TEXTOS_I18N['pt']['limite_arquivo_documento']\n"
            "    assert str(erro) == esperado, (str(erro), esperado)\n"
            "else:\n"
            "    raise AssertionError('o limite não foi aplicado')\n"
            "finally:\n"
            "    alvo.unlink(missing_ok=True)\n"
        )

        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(
            resultado.returncode,
            0,
            msg=resultado.stdout + resultado.stderr,
        )

    def test_pdf_acima_do_limite_de_paginas_e_recusado(self):
        documento = mock.Mock()
        documento.page_count = 501
        documento.needs_pass = False

        pymupdf = mock.Mock()
        pymupdf.open.return_value = documento

        with mock.patch.object(
            document_parser,
            "_importar_pymupdf",
            return_value=pymupdf,
        ), mock.patch.object(
            document_parser,
            "_importar_pymupdf4llm",
            return_value=mock.Mock(),
        ), mock.patch.object(
            document_parser,
            "MAXIMO_PAGINAS_PDF",
            500,
        ):
            with self.assertRaises(document_parser.ErroConversao):
                document_parser._converter_pdf(
                    self.base / "grande.pdf",
                    None,
                )

        documento.close.assert_called_once()
