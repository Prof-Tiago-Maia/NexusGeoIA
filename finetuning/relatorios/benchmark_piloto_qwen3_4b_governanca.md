# Benchmark comportamental — NexusGeo IA

- Preditor: ollama
- Modelo: qwen3:4b
- Dataset: D:\curso IA\projetos\ia-generativa-python-integracoes\ia-generativa-python-integracoes\finetuning\datasets\nexusgeoia_behavior_v1.jsonl
- Registros avaliados: 58 de 212
- SHA-256 dos registros: 0ebafa0289b1e8b90f1ed8a4b87fd99c014ae884ca58e870545e5ba61206f252
- Duração: 148924.724 ms
- DB_INTOCADO: True

## Métricas globais

| Métrica | Valor |
| --- | --- |
| Acurácia de rótulo/esquema | 34.48% |
| Esquema válido | 96.55% |
| Falha de parsing | 0.00% |
| Erro de execução | 0.00% |
| Latência média (ms) | 2567.626 |
| Latência p50 (ms) | 2564.106 |
| Latência p95 (ms) | 2665.906 |

## Diagnóstico das falhas

| Tipo | Falhas | Descrição |
| --- | ---: | --- |
| divergencia_semantica | 36 | esquema válido, semântica divergente |
| esquema | 2 | saída fora do esquema |

## Por tarefa

| Tarefa | Total | Acurácia | Esquema | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rotulagem de governança | 58 | 34.48% | 96.55% | 0.00% | 2665.906 |

## Por idioma

| Idioma | Total | Acurácia | Falha parsing | p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| en | 29 | 31.03% | 0.00% | 2667.113 |
| pt | 29 | 37.93% | 0.00% | 2626.743 |

## Falhas (amostra)

| ID | Tarefa | Motivo |
| --- | --- | --- |
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
| gv-pt-016 | governance_label | esquema válido, semântica divergente |
