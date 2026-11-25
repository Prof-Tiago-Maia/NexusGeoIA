# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 212 de 212
- SHA-256 dos registros: ed4edd9b6fd317cabc10c712edf3709013a1d98479be966e00d4086d2006fe5f
- Duração: 639978.540 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 64.62% |
| Esquema válido | 97.64% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.47% |
| Latência média (ms) | 3018.724 |
| Latência p50 (ms) | 2682.399 |
| Latência p95 (ms) | 2987.987 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 70 | esquema válido, semântica divergente |
| esquema | 4 | saída fora do esquema |
| timeout | 1 | timeout no prazo do registro |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 58 | 46.55% | 100.00% | 0.00% | 2775.200 |
| Extração estruturada de sondagem | 74 | 54.05% | 94.59% | 0.00% | 3022.496 |
| Roteamento de workflow / intenção | 80 | 87.50% | 98.75% | 0.00% | 2616.344 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 106 | 61.32% | 0.00% | 2982.443 |
| pt | 106 | 67.92% | 0.00% | 2989.508 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| wf-pt-001 | workflow_intent | timeout no prazo do registro |
| wf-pt-011 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-014 | workflow_intent | esquema válido, semântica divergente |
| wf-en-014 | workflow_intent | esquema válido, semântica divergente |
| wf-en-024 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-026 | workflow_intent | esquema válido, semântica divergente |
| wf-en-026 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-027 | workflow_intent | esquema válido, semântica divergente |
| wf-en-027 | workflow_intent | esquema válido, semântica divergente |
| wf-en-034 | workflow_intent | esquema válido, semântica divergente |
| sd-en-001 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-005 | sondagem_extract | esquema válido, semântica divergente |
