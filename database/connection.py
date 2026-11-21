
"""Conexão com o banco SQLite de atendimentos.

O diretório vem de ``config``: em desenvolvimento (ou na pasta portátil)
é o ``data/`` do projeto; no executável instalado é
``%LOCALAPPDATA%\\NexusGeoIA\\data``. ``ASSISTENTE_DATA_DIR``
substitui os dois casos.
"""

import sqlite3
from pathlib import Path

from config import DATA_DIR, DB_PATH


def conectar():
    """Abre a conexão SQLite, criando ``data/`` quando necessário."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(DB_PATH)
    conexao.row_factory = sqlite3.Row

    return conexao
