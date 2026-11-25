# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: finetuning\datasets\nexusgeoia_behavior_v2.jsonl
- Registros avaliados: 50 de 300
- SHA-256 dos registros avaliados: 55d3b828c0647905e5b2feaa110fbb9d9c69f32f23a265db61cd7be1cf425554
- Split: teste (50 registros, 25 pares)
- SHA-256 do dataset no manifesto: 74a52f789726190f2a99eb84fa2b5afa089cfd806ab9aff6a1dd169561071ecc
- Manifesto do split: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v2.split.json
- Duração: 181296.436 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 58.00% |
| Esquema válido | 98.00% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 3625.887 |
| Latência p50 (ms) | 2701.787 |
| Latência p95 (ms) | 3026.472 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 20 | esquema válido, semântica divergente |
| esquema | 1 | saída fora do esquema |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 14 | 35.71% | 100.00% | 0.00% | 2784.409 |
| Extração estruturada de sondagem | 18 | 66.67% | 94.44% | 0.00% | 3034.253 |
| Roteamento de workflow / intenção | 18 | 66.67% | 100.00% | 0.00% | 9515.813 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 25 | 56.00% | 0.00% | 3012.751 |
| pt | 25 | 60.00% | 0.00% | 3043.700 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| wf-pt-026 | workflow_intent | esquema válido, semântica divergente |
| wf-en-026 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-027 | workflow_intent | esquema válido, semântica divergente |
| wf-en-027 | workflow_intent | esquema válido, semântica divergente |
| wf-pt-048 | workflow_intent | esquema válido, semântica divergente |
| wf-en-048 | workflow_intent | esquema válido, semântica divergente |
| sd-pt-027 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-027 | sondagem_extract | saída fora do esquema |
| sd-pt-046 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-046 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-047 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-047 | sondagem_extract | esquema válido, semântica divergente |
