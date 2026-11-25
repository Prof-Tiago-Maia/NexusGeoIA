# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 58 de 212
- SHA-256 dos registros: 0ebafa0289b1e8b90f1ed8a4b87fd99c014ae884ca58e870545e5ba61206f252
- Duração: 156239.088 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 46.55% |
| Esquema válido | 100.00% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 2693.733 |
| Latência p50 (ms) | 2685.061 |
| Latência p95 (ms) | 2775.200 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 31 | esquema válido, semântica divergente |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 58 | 46.55% | 100.00% | 0.00% | 2775.200 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 29 | 41.38% | 0.00% | 2796.020 |
| pt | 29 | 51.72% | 0.00% | 2724.798 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
| gv-pt-008 | governance_label | esquema válido, semântica divergente |
| gv-en-008 | governance_label | esquema válido, semântica divergente |
| gv-pt-009 | governance_label | esquema válido, semântica divergente |
| gv-en-009 | governance_label | esquema válido, semântica divergente |
| gv-pt-011 | governance_label | esquema válido, semântica divergente |
| gv-en-011 | governance_label | esquema válido, semântica divergente |
| gv-pt-012 | governance_label | esquema válido, semântica divergente |
| gv-en-012 | governance_label | esquema válido, semântica divergente |
| gv-pt-013 | governance_label | esquema válido, semântica divergente |
| gv-en-013 | governance_label | esquema válido, semântica divergente |
| gv-pt-015 | governance_label | esquema válido, semântica divergente |
| gv-en-015 | governance_label | esquema válido, semântica divergente |
