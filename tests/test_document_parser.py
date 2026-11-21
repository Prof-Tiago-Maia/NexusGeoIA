"""Testes offline da detecção do motor de OCR do ``document_parser``.

O RapidOCR é opcional: no executável empacotado ele pode falhar ao
resolver os próprios ``.yaml``/modelos ONNX dentro de ``_MEI...``. Estes
testes garantem que uma falha desse tipo vira ``ocr_disponivel() == False``
(com aviso em log) em vez de derrubar a interface do Streamlit, sem
instalar, importar de verdade ou baixar qualquer modelo.
"""

import unittest
from unittest import mock

import services.document_parser as document_parser


class ModuloFalso:
    """Imita um pacote importado, com os atributos informados."""

    def __init__(self, **atributos):
        self.__dict__.update(atributos)


def importlib_que_falha(erro):
    """Substitui ``document_parser.importlib`` por um import que falha."""

    return mock.Mock(import_module=mock.Mock(side_effect=erro))


class TestCarregarClasseOcr(unittest.TestCase):
    """``_carregar_classe_ocr`` nunca propaga a falha do import."""

    def test_devolve_none_quando_o_yaml_do_rapidocr_nao_existe(self):
        erro = FileNotFoundError(2, "No such file", "config.yaml")

        with mock.patch.object(
            document_parser, "importlib", importlib_que_falha(erro)
        ):
            self.assertIsNone(document_parser._carregar_classe_ocr())

    def test_devolve_none_quando_o_omegaconf_levanta_oserror(self):
        # Simula o erro real do executável: o Omegaconf não consegue
        # abrir o arquivo de configuração dentro de _MEI...
        erro = OSError("modelo ONNX ausente em _MEI123456")

        with mock.patch.object(
            document_parser, "importlib", importlib_que_falha(erro)
        ):
            self.assertIsNone(document_parser._carregar_classe_ocr())

    def test_devolve_none_quando_o_pacote_nao_expoe_rapidocr(self):
        importar = mock.Mock(import_module=mock.Mock(return_value=ModuloFalso()))

        with mock.patch.object(document_parser, "importlib", importar):
            self.assertIsNone(document_parser._carregar_classe_ocr())

    def test_usa_o_pacote_atual_quando_o_legado_falha(self):
        def importar(nome):
            if nome == "rapidocr":
                return ModuloFalso(RapidOCR=object)

            raise OSError("dados ausentes")

        with mock.patch.object(
            document_parser,
            "importlib",
            mock.Mock(import_module=mock.Mock(side_effect=importar)),
        ):
            self.assertIs(document_parser._carregar_classe_ocr(), object)


class TestOcrDisponivel(unittest.TestCase):
    """``ocr_disponivel`` responde sem lançar exceção em nenhum cenário."""

    def test_false_quando_o_import_levanta_erro_de_arquivo(self):
        erros = (
            FileNotFoundError(2, "No such file", "config.yaml"),
            FileNotFoundError(2, "No such file", "default_models.yaml"),
            OSError("modelo ONNX ausente em _MEI123456"),
            RuntimeError("OmegaConf load falhou"),
        )

        for erro in erros:
            with self.subTest(erro=type(erro).__name__, detalhe=str(erro)):
                with mock.patch.object(
                    document_parser, "importlib", importlib_que_falha(erro)
                ):
                    self.assertFalse(document_parser.ocr_disponivel())

    def test_false_quando_nenhum_pacote_do_rapidocr_esta_instalado(self):
        with mock.patch.object(
            document_parser,
            "importlib",
            importlib_que_falha(
                ModuleNotFoundError("No module named 'rapidocr'")
            ),
        ):
            self.assertFalse(document_parser.ocr_disponivel())

    def test_true_quando_o_rapidocr_esta_disponivel(self):
        def importar(nome):
            if nome == "rapidocr":
                return ModuloFalso(RapidOCR=object)

            raise ImportError(nome)

        with mock.patch.object(
            document_parser,
            "importlib",
            mock.Mock(import_module=mock.Mock(side_effect=importar)),
        ):
            self.assertTrue(document_parser.ocr_disponivel())


class TestObterMotorOcr(unittest.TestCase):
    """``obter_motor_ocr`` traduz a falha em erro de conversão legível."""

    def test_falha_de_dados_nao_vaza_file_not_found(self):
        erro = FileNotFoundError(2, "No such file", "config.yaml")

        with mock.patch.object(
            document_parser, "_MOTOR_OCR", None
        ), mock.patch.object(
            document_parser, "_ERRO_MOTOR_OCR", None
        ), mock.patch.object(
            document_parser, "importlib", importlib_que_falha(erro)
        ):
            with self.assertRaises(
                document_parser.DependenciaAusenteError
            ) as caso:
                document_parser.obter_motor_ocr()

        self.assertIn("RapidOCR", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
