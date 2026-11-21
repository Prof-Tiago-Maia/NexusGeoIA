"""Testes de sanitização de nomes de upload no Windows (B4).

O upload não pode criar fluxos alternativos NTFS, usar nomes
reservados (CON, NUL, COM1...) ou escapar de data/docs.
"""

from __future__ import annotations

import unittest

from services.rag_service import (
    DocumentoInvalidoError,
    _sanitizar_nome_documento,
)


class TestNomesUpload(unittest.TestCase):
    """Nomes perigosos são reduzidos a um arquivo seguro."""

    def test_remove_diretorios(self):
        self.assertEqual(
            _sanitizar_nome_documento("../fora.txt"),
            "fora.txt",
        )

    def test_remove_diretorios_com_barra_invertida_do_windows(self):
        self.assertEqual(
            _sanitizar_nome_documento(r"..\..\arquivo.txt"),
            "arquivo.txt",
        )

    def test_remove_fluxo_alternativo(self):
        self.assertEqual(
            _sanitizar_nome_documento("relatorio.txt:segredo"),
            "relatorio.txt",
        )

    def test_prefixa_nomes_reservados(self):
        for nome in ("CON.txt", "NUL", "COM1.pdf", "LPT9.md"):
            with self.subTest(nome=nome):
                self.assertTrue(
                    _sanitizar_nome_documento(nome).startswith("_")
                )

    def test_prefixa_reservados_com_espaco_antes_da_extensao(self):
        # O Windows ignora o espaço final do radical: "CON .txt" continua
        # sendo o dispositivo CON.
        for nome in ("CON .txt", "NUL .txt", "COM1 .pdf"):
            with self.subTest(nome=nome):
                resultado = _sanitizar_nome_documento(nome)

                self.assertTrue(resultado.startswith("_"))
                self.assertTrue(resultado.endswith(nome.split(" ", 1)[1]))

    def test_prefixa_reservados_com_digito_sobrescrito(self):
        # ¹/²/³ são variantes Unicode de 1/2/3 que o Windows também
        # reconhece em COM¹/LPT¹. A normalização NFKC precisa equipará-las.
        for nome in ("COM¹", "LPT¹", "COM².txt", "LPT³.pdf"):
            with self.subTest(nome=nome):
                self.assertTrue(
                    _sanitizar_nome_documento(nome).startswith("_")
                )

    def test_substitui_caracteres_invalidos(self):
        self.assertEqual(
            _sanitizar_nome_documento("relatorio?.pdf"),
            "relatorio_.pdf",
        )

    def test_remove_pontos_e_espacos_finais(self):
        self.assertEqual(
            _sanitizar_nome_documento("relatorio... "),
            "relatorio",
        )

    def test_nome_vazio_ou_pai_reprova(self):
        for nome in ("", "   ", ".", ".."):
            with self.subTest(nome=nome):
                with self.assertRaises(DocumentoInvalidoError):
                    _sanitizar_nome_documento(nome)
