# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 12 de 212
- SHA-256 dos registros: e09e23549770303d100990fc491baad98b351499a749676feb5b71f6d93daf8f
- Duração: 48110.540 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 41.67% |
| Esquema válido | 100.00% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 4009.169 |
| Latência p50 (ms) | 2435.503 |
| Latência p95 (ms) | 11092.986 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 7 | esquema válido, semântica divergente |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Roteamento de workflow / intenção | 12 | 41.67% | 100.00% | 0.00% | 11092.986 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 6 | 50.00% | 0.00% | 2501.975 |
| pt | 6 | 33.33% | 0.00% | 16801.797 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| wf-pt-001 | workflow_intent | esquema válido, semântica divergente |
| wf-en-001 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-002 | workflow_intent | esquema válido, semântica divergente |
| wf-en-002 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-003 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-006 | workflow_intent | esquema válido, semântica divergente |
| wf-en-006 | workflow_intent | esquema válido, semântica divergente |
