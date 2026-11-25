# Fine-tuning comportamental — NexusGeo IA v1.0.0

Pacote de preparação, treino e avaliação do SLM local para três
comportamentos verificáveis, **isolado do fluxo de produção** do `app.py`.

## Garantias

- A avaliação não importa Streamlit nem o banco real.
- Não abre `data/nexusgeoia.db`; a guarda SHA-256 do banco e dos sidecars
  SQLite produz `DB_INTOCADO=True` antes/depois de cada execução.
- O treino QLoRA e a quantização GGUF **não rodam por padrão**: existem como
  scripts sob demanda e nunca são executados pela suíte de testes.
- O gabarito é calculado pelos módulos reais: `core.source_router`,
  `services.sondagem` e `core.governance`.
- A v1 do dataset é congelada; a v2 é a base atual.

## Tarefas

1. `workflow_intent` — classificar o workflow (`consulta_direta`,
   `triagem_area`, `hidrogeologia`, `sondagem`) e a intenção de fontes
   (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`).
2. `sondagem_extract` — extrair um intervalo De–Até com furo, litologia,
   unidade, metros canônicos, espessura e situação/motivo.
3. `governance_label` — normalizar `OBSERVED`/`INFERRED` e veredito
   `PASS`/`HOLD`/`FAIL`, incluindo downgrade, evidência desconhecida,
   contrato incompleto, texto livre e falha de fonte.

Cada tarefa cobre casos normais, ambíguos, incompletos e negativos, com pares
PT-BR/EN semanticamente equivalentes.

## Arquivos

- `contrato.py` — esquema, rótulos canônicos e validadores.
- `casos_workflow.py`, `casos_sondagem.py`, `casos_governanca.py` — entradas
  bilíngues; o gabarito nunca é escrito à mão.
- `oraculo.py` — recomputação determinística com os módulos do projeto.
- `gerador.py` — gera o JSONL e o manifesto.
- `split.py` — split determinístico treino/validação/teste por par PT/EN.
- `benchmark.py` — harness de acurácia, falha de parsing e latência.
- `exportar_sft.py` — exporta treino/validação no formato chat SFT, com
  prompts idênticos aos do benchmark e manifesto anti-vazamento.
- `treinar_lora.py` — CLI portátil de LoRA/QLoRA (dry-run, detecção de
  dispositivo/precisão e plano de treino sem baixar pesos).
- `gerar_modelfile.py` — template determinístico de registro no Ollama.
- `seguranca.py` — guarda do banco e auditoria AST.
- `auditoria.py` — CLI de auditoria estática, de paridade e do split.
- `datasets/nexusgeoia_behavior_v1.jsonl` — dataset original congelado
  (212 registros, 106 pares); não é regravado pela versão 2.
- `datasets/nexusgeoia_behavior_v2.jsonl` — dataset expandido (300 registros,
  150 pares) com os erros residuais do benchmark v2.
- `datasets/nexusgeoia_behavior_v2.split.json` — manifesto do split
  determinístico, com SHA-256 do dataset e atribuição por par.
- `datasets/sft_v2_treino.jsonl` — 206 conversas SFT do split treino.
- `datasets/sft_v2_validacao.jsonl` — 44 conversas SFT do split validação.
- `datasets/sft_v2.manifest.json` — hashes, contagens e prova de interseção
  zero com o split teste (por id e por par).
- `Modelfile.nexusgeo-qwen3-4b-v2` — template do adaptador LoRA.
- `Modelfile.nexusgeo-qwen3-4b-v2-q4` — template do GGUF `Q4_K_M` (usado
  pela release).
- `adaptadores/nexusgeo-qwen3-4b-v2/` — adaptador LoRA treinado, checkpoints
  52 e 78 e metadados do tokenizer.
- `relatorios/` — relatórios JSON e Markdown do benchmark.

## Uso

    .\.venv\Scripts\python.exe -m finetuning.gerador --resumo

    .\.venv\Scripts\python.exe -m finetuning.split --resumo

    .\.venv\Scripts\python.exe -m finetuning.auditoria

    .\.venv\Scripts\python.exe -m finetuning.exportar_sft

    .\.venv\Scripts\python.exe -m finetuning.treinar_lora --dry-run

    .\.venv\Scripts\python.exe -m finetuning.gerar_modelfile

    .\.venv\Scripts\python.exe -m finetuning.benchmark ^
        --preditor oraculo ^
        --json-saida finetuning\relatorios\benchmark_oraculo.json ^
        --relatorio-md finetuning\relatorios\benchmark_oraculo.md

Para um modelo local, com o Ollama já em execução:

    .\.venv\Scripts\python.exe -m finetuning.benchmark ^
        --preditor ollama --ollama-modelo qwen3:4b ^
        --limite 50 --timeout 120

O endpoint e o modelo também podem vir de `OLLAMA_HOST` e `OLLAMA_MODEL`.
Sem Ollama disponível, o comando sai com código 2 e não inventa métricas.

## Dataset v2 e split determinístico

A v2 preserva a v1 byte a byte e adiciona 88 registros (44 pares bilíngues)
focados nos erros residuais do `qwen3:4b` no consolidado v2: unidade
implícita e conversão cm → m, separador de milhar, preservação de
sinal/inválidos, `erro_contrato` versus linha inválida, múltiplos intervalos
com sobreposição/lacuna, viés otimista da governança (`OBSERVED` sem
evidência, evidência inexistente, `claims` ausente/inválido, falhas
`fonte_*`, PASS/HOLD/FAIL) e precedência de workflow com `HIBRIDO` apenas
quando RAG e SGB coexistem de fato.

O split agrupa por `metadados.par`: PT-BR e EN do mesmo caso caem sempre no
mesmo conjunto. A atribuição é estratificada por tarefa e ordenada por
`sha256(sal:par)`, sem `hash()` aleatório; as frações-alvo são 70% treino,
15% validação e 15% teste (206/44/50 registros). O manifesto registra o
SHA-256 dos registros e a auditoria recomputa a atribuição, então um split
velho ou com par dividido reprova `finetuning.auditoria`.

## Exportação SFT

A exportação reutiliza exatamente `finetuning.benchmark._prompt_sistema` e
`_prompt_usuario`, então o prompt de treino é o mesmo da avaliação. Cada
linha de `sft_v2_*.jsonl` tem `messages` com os papéis `system`, `user` e
`assistant`; a resposta é o `saida_esperada` serializado por
`contrato.json_compacto` (chaves ordenadas, sem espaços). O split é validado
por SHA-256 antes de qualquer gravação e o manifesto registra interseção zero
com o split `teste` por `id` e por `metadados.par`.

## Treino QLoRA

O treino é opcional e portátil:

- `--modelo-base` aceita `Qwen/Qwen3-4B` ou um diretório local;
- `--precisao {auto,bf16,fp16,fp32}` escolhe bf16 em CUDA com suporte
  nativo, fp16 em CUDA sem bf16 e fp32 em CPU/fallback;
- `--quantizar-4bit` ativa **QLoRA** com `BitsAndBytesConfig`
  (`load_in_4bit=True`, NF4, `bnb_4bit_use_double_quant=True`);
- LoRA conservador padrão (`r=8`, `lora_alpha=16`, `dropout=0.05`), batch
  1 com `gradient_accumulation_steps=8`, `gradient_checkpointing=True`,
  `seed=42`, `max_seq=1024` e 3 épocas;
- `--dry-run` valida os JSONL, lista as bibliotecas presentes/ausentes,
  reporta GPUs/CUDA e imprime o plano completo sem baixar pesos.

Exemplo do treino efetivamente executado (adaptador em
`adaptadores/nexusgeo-qwen3-4b-v2/`):

    .\.venv\Scripts\python.exe -m finetuning.treinar_lora ^
        --modelo-base Qwen/Qwen3-4B ^
        --quantizar-4bit --precisao auto --epocas 3 ^
        --rank 8 --alpha 16 --seed 42

## Quantização GGUF e registro no Ollama

O adaptador é mesclado ao modelo base e convertido para GGUF `Q4_K_M`
(~2,5 GB) com o `llama.cpp`. O arquivo final é procurado em
`models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf` (ou no cache
`D:\hf_cache\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`).

O `Modelfile` usa `temperature 0`, `seed 42`, `num_ctx 32000` e
`num_predict 1024` para decodificação determinística. O registro é feito por
`setup_llm.py` — que reescreve a linha `FROM` para o caminho absoluto do
GGUF — ou manualmente:

    ollama create nexusgeo-qwen3-4b-v2-q4 -f finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4
    ollama run nexusgeo-qwen3-4b-v2-q4

Em outro PC, copie o GGUF e rode novamente `setup_llm.py`. Nenhum benchmark
Ollama é executado automaticamente.

## Resultado validado da v1.0.0

Benchmark determinístico no `split=teste` (50 casos, 25 pares PT-BR/EN),
`seed=42`:

| Métrica | `qwen3:4b` | `nexusgeo-qwen3-4b-v2-q4` |
| --- | ---: | ---: |
| Acurácia de rótulo/esquema | 58,00% | **62,00%** |
| Conformidade de esquema JSON | 98,00% | **100,00%** |
| Falha de parsing | 0,00% | **0,00%** |
| Latência p50 | 2.701,8 ms | **2.681 ms** |
| Latência p95 | 3.026,5 ms | **2.994 ms** |

Os relatórios da linha de base estão em
`relatorios/benchmark_qwen3_4b_v2_teste.{json,md}`; o consolidado v2 fica em
`relatorios/benchmark_qwen3_4b_v2_consolidado.{json,md}`. O benchmark mede
comportamento e conformidade de esquema, **não** exatidão factual.

## Formato do registro

    {
      "id": "wf-pt-001",
      "tarefa": "workflow_intent",
      "idioma": "pt",
      "instrucao": "...",
      "entrada": "...",
      "saida": "{\"workflow\":\"...\",\"intencao\":\"...\"}",
      "saida_esperada": {"workflow": "...", "intencao": "..."},
      "verificador": "workflow_intent.v1",
      "metadados": {"familia": "normal", "par": "wf-001", "categoria": "..."}
    }

## Métricas do harness

- `acuracia` e `acuracia_esquema`, globais e por tarefa, idioma e família;
- `taxa_falha_parsing` e `taxa_erro_execucao`;
- latência média, p50, p95, mínima e máxima em milissegundos;
- matriz de confusão do rótulo principal;
- amostra de falhas com esperado e obtido;
- `DB_INTOCADO` e hashes do banco principal e dos sidecars.

## Testes

    .\.venv\Scripts\python.exe -m unittest ^
        tests.test_finetuning_dataset tests.test_finetuning_split ^
        tests.test_finetuning_idempotencia tests.test_finetuning_benchmark ^
        tests.test_finetuning_sft -v

Os testes usam dublês, fixtures locais e `urlopen` mockado. Nenhum deles
acessa rede, banco real, serviço externo ou treina pesos.
