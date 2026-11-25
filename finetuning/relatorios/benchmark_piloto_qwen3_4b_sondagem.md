# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 74 de 212
- SHA-256 dos registros: d149f4554a07f4fcab375ec7c1c17914928fc6d71b666f0ebcc09cd9ee9c761a
- Duração: 207620.397 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 36.49% |
| Esquema válido | 79.73% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 2805.637 |
| Latência p50 (ms) | 2798.049 |
| Latência p95 (ms) | 2892.691 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 32 | esquema válido, semântica divergente |
| esquema | 15 | saída fora do esquema |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Extração estruturada de sondagem | 74 | 36.49% | 79.73% | 0.00% | 2892.691 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 37 | 37.84% | 0.00% | 2894.640 |
| pt | 37 | 35.14% | 0.00% | 2890.412 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| sd-pt-003 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-003 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-005 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-005 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-006 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-006 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-007 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-007 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-012 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-012 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-013 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-013 | sondagem_extract | esquema válido, semântica divergente |
