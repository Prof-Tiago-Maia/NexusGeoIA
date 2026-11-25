# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 212 de 212
- SHA-256 dos registros: ed4edd9b6fd317cabc10c712edf3709013a1d98479be966e00d4086d2006fe5f
- Duração: 556253.584 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 55.19% |
| Esquema válido | 91.51% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 2623.796 |
| Latência p50 (ms) | 2562.922 |
| Latência p95 (ms) | 2842.498 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 77 | esquema válido, semântica divergente |
| esquema | 18 | saída fora do esquema |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 58 | 34.48% | 96.55% | 0.00% | 2665.906 |
| Extração estruturada de sondagem | 74 | 36.49% | 79.73% | 0.00% | 2892.691 |
| Roteamento de workflow / intenção | 80 | 87.50% | 98.75% | 0.00% | 2546.342 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 106 | 53.77% | 0.00% | 2831.755 |
| pt | 106 | 56.60% | 0.00% | 2854.603 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| wf-pt-011 | workflow_intent | esquema válido, semântica divergente |
| wf-en-011 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-014 | workflow_intent | esquema válido, semântica divergente |
| wf-en-014 | workflow_intent | esquema válido, semântica divergente |
| wf-en-023 | workflow_intent | esquema válido, semântica divergente |
| wf-en-024 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-026 | workflow_intent | saída fora do esquema |
| wf-en-026 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-027 | workflow_intent | esquema válido, semântica divergente |
| wf-en-027 | workflow_intent | esquema válido, semântica divergente |
| sd-pt-003 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-003 | sondagem_extract | esquema válido, semântica divergente |

