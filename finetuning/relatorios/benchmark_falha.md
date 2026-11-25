# Benchmark comportamental — NexusGeo IA

- Preditor: falha
- Modelo: -
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 212 de 212
- SHA-256 dos registros: ed4edd9b6fd317cabc10c712edf3709013a1d98479be966e00d4086d2006fe5f
- Duração: 0.339 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 0.00% |
| Esquema válido | 0.00% |
| Falha de parsing | 0.00% |
| Erro de execução | 100.00% |
| Latência média (ms) | 0.001 |
| Latência p50 (ms) | 0.001 |
| Latência p95 (ms) | 0.001 |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 58 | 0.00% | 0.00% | 0.00% | 0.001 |
| Extração estruturada de sondagem | 74 | 0.00% | 0.00% | 0.00% | 0.001 |
| Roteamento de workflow / intenção | 80 | 0.00% | 0.00% | 0.00% | 0.002 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 106 | 0.00% | 0.00% | 0.001 |
| pt | 106 | 0.00% | 0.00% | 0.001 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| wf-pt-001 | workflow_intent | RuntimeError: falha_injetada:wf-pt-001 |
| wf-en-001 | workflow_intent | RuntimeError: falha_injetada:wf-en-001 |
| wf-pt-002 | workflow_intent | RuntimeError: falha_injetada:wf-pt-002 |
| wf-en-002 | workflow_intent | RuntimeError: falha_injetada:wf-en-002 |
| wf-pt-003 | workflow_intent | RuntimeError: falha_injetada:wf-pt-003 |
| wf-en-003 | workflow_intent | RuntimeError: falha_injetada:wf-en-003 |
| wf-pt-004 | workflow_intent | RuntimeError: falha_injetada:wf-pt-004 |
| wf-en-004 | workflow_intent | RuntimeError: falha_injetada:wf-en-004 |
| wf-pt-005 | workflow_intent | RuntimeError: falha_injetada:wf-pt-005 |
| wf-en-005 | workflow_intent | RuntimeError: falha_injetada:wf-en-005 |
| wf-pt-006 | workflow_intent | RuntimeError: falha_injetada:wf-pt-006 |
| wf-en-006 | workflow_intent | RuntimeError: falha_injetada:wf-en-006 |
