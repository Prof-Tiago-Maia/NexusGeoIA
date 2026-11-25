# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 74 de 212
- SHA-256 dos registros: d149f4554a07f4fcab375ec7c1c17914928fc6d71b666f0ebcc09cd9ee9c761a
- Duração: 218139.369 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 54.05% |
| Esquema válido | 94.59% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 2947.782 |
| Latência p50 (ms) | 2942.476 |
| Latência p95 (ms) | 3022.496 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 30 | esquema válido, semântica divergente |
| esquema | 4 | saída fora do esquema |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Extração estruturada de sondagem | 74 | 54.05% | 94.59% | 0.00% | 3022.496 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 37 | 48.65% | 0.00% | 3029.065 |
| pt | 37 | 59.46% | 0.00% | 3017.878 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| sd-en-001 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-005 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-006 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-007 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-012 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-018 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-018 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-021 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-023 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-023 | sondagem_extract | esquema válido, semântica divergente |
| sd-en-025 | sondagem_extract | esquema válido, semântica divergente |
| sd-pt-026 | sondagem_extract | saída fora do esquema |
