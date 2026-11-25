"""Preparacao de fine-tuning comportamental do SLM do NexusGeo IA.

Este pacote e **isolado do fluxo de producao**: nao e importado por
`app.py`, nao abre o banco `data/nexusgeoia.db` e nao executa
treinamento de pesos. Ele entrega tres instrumentos:

* :mod:`finetuning.gerador` - gera o dataset bilingue PT-BR/EN
  (instrucao/entrada/saida curta) para tres comportamentos;
* :mod:`finetuning.benchmark` - avalia acuracia de rotulo/esquema,
  falhas de parsing e latencia, com preditor oraculo, dubles de falha
  e suporte opcional ao Ollama local;
* :mod:`finetuning.split` - split deterministico treino/validacao/teste,
  agrupando os pares PT-BR/EN para evitar vazamento;
* :mod:`finetuning.auditoria` - auditoria estatica do pacote, do dataset
  e do split, com a guarda `DB_INTOCADO`.

Nenhum modulo deste pacote inicia treinamento LoRA/QLoRA. Apenas
prepara e mede o material comportamental.
"""

from __future__ import annotations

__all__ = [
    "VERSAO_PACOTE",
]

# Versao propria do pacote de fine-tuning, independente do app.
VERSAO_PACOTE = "1.0.0"
