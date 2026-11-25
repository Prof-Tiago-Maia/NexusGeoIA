"""Isolamento de banco e histórico para AppTests que executam app.py.

Os testes de interface rodam o aplicativo real em processo. Sem esta
barreira, o autosave do histórico gravaria no ``data/nexusgeoia.db`` e a
migração aditiva varreria o ``data/historico`` do projeto. Cada caso
recebe uma pasta temporária própria, apontada por ``NEXUSGEO_DB_PATH``
e pela variável de teste que desliga a migração legada.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
BASE_TESTES = RAIZ / "build" / "_tmp_apptest"


def isolar_ambiente_apptest(caso):
    """Configura banco SQLite e histórico temporários para um AppTest.

    Devolve a pasta raiz do isolamento. Os ``addCleanup`` registrados no
    caso restauram as variáveis de ambiente e removem a pasta ao final,
    mesmo quando o teste falha.
    """

    # A pasta temporária do sistema pode ser somente leitura no sandbox
    # do Windows; build/_tmp_apptest fica dentro do workspace e mantém o
    # mesmo isolamento dos demais testes. O nome é determinístico por
    # caso e é limpo antes de cada execução.
    BASE_TESTES.mkdir(parents=True, exist_ok=True)
    nome = f"{type(caso).__name__}_{caso._testMethodName}"
    pasta = BASE_TESTES / nome
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True, exist_ok=True)
    caso.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

    banco = pasta / "data" / "nexusgeoia.db"
    historico = pasta / "data" / "historico"
    historico.mkdir(parents=True)

    ambiente = patch.dict(
        os.environ,
        {
            "ASSISTENTE_DATA_DIR": str(pasta),
            "NEXUSGEO_DB_PATH": str(banco),
            "NEXUSGEO_TEST_MODE": "1",
        },
        clear=False,
    )
    ambiente.start()
    caso.addCleanup(ambiente.stop)

    # O serviço legado também é usado pela migração aditiva; apontá-lo
    # para a pasta vazia garante que nenhum arquivo real seja lido.
    patch_historico = patch(
        "services.history_service.DIRETORIO_HISTORICO",
        historico,
    )
    patch_historico.start()
    caso.addCleanup(patch_historico.stop)

    from services import history_db

    history_db._INICIALIZADOS.discard(str(banco.resolve()))

    return pasta
