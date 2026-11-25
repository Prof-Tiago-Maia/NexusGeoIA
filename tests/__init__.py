"""Pacote de testes offline do NexusGeo IA.

A guarda abaixo acompanha toda a suíte: ela tira uma impressão SHA-256
do banco real no primeiro import do pacote e a confere no encerramento
do processo, gravando o relatório e imprimindo ``DB_INTOCADO``. O
callback de ``atexit`` não derruba o interpretador: a falha vira
código de saída 1 no fluxo normal de ``python -B tests/_db_intocado.py``
(ou quando um runner consultar ``falha_de_integridade()``). Assim,
mesmo um teste futuro que esqueça o isolamento não passa silenciosamente
por cima de ``data/nexusgeoia.db`` nem interrompe outros hooks de
finalização.
"""

from tests._db_intocado import registrar_guarda_de_ambiente

registrar_guarda_de_ambiente()
