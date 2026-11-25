# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 80 de 212
- SHA-256 dos registros: fabb6c13e911e55edab11fb370175096cef9eed9d38de68a0eebd912908009c1
- Duração: 265600.083 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 87.50% |
| Esquema válido | 98.75% |
| Falha de parsing | 0.00% |
| Erro de execução | 1.25% |
| Latência média (ms) | 3319.964 |
| Latência p50 (ms) | 2579.563 |
| Latência p95 (ms) | 2616.344 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 9 | esquema válido, semântica divergente |
| timeout | 1 | timeout no prazo do registro |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Roteamento de workflow / intenção | 80 | 87.50% | 98.75% | 0.00% | 2616.344 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 40 | 87.50% | 0.00% | 2618.210 |
| pt | 40 | 87.50% | 0.00% | 2608.450 |

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
