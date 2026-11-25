---
base_model: Qwen/Qwen3-4B
library_name: gguf
pipeline_tag: text-generation
language:
- en
- pt
license: apache-2.0
tags:
- gguf
- qwen3
- qlora
- geoscience
- geology
- structured-output
- json
- ollama
- llama.cpp
- nexusgeo
model-index:
- name: nexusgeo-qwen3-4b-v2-GGUF
  results:
  - task:
      type: text-generation
      name: Geoscientific Workflow Routing & Structured Extraction
    dataset:
      type: nexusgeoia_behavior_v2
      name: NexusGeoIA Behavior Benchmark v2
    metrics:
    - type: schema_compliance
      value: 100.0
      name: JSON Schema Conformance (%)
    - type: accuracy
      value: 62.0
      name: Label / Schema Accuracy (%)
---

# NexusGeo Qwen3-4B v2 — GGUF (`Q4_K_M`)

<div align="center">

[![GitHub Project](https://img.shields.io/badge/GitHub-NexusGeoIA_v1.0.0-181717?style=for-the-badge&logo=github)](https://github.com/Prof-Tiago-Maia/NexusGeoIA)
[![Base Model](https://img.shields.io/badge/Base_Model-Qwen%2FQwen3--4B-2563eb?style=for-the-badge)](https://huggingface.co/Qwen/Qwen3-4B)
[![Format](https://img.shields.io/badge/Format-GGUF_Q4__K__M-16a34a?style=for-the-badge)]()
[![Languages](https://img.shields.io/badge/Languages-EN%20%7C%20PT--BR-7c3aed?style=for-the-badge)]()
[![License](https://img.shields.io/badge/License-Apache_2.0-ea580c?style=for-the-badge)]()

</div>

A QLoRA-tuned, JSON-grounded geoscience assistant model for the [**NexusGeo IA**](https://github.com/Prof-Tiago-Maia/NexusGeoIA) local workstation. This repository hosts the GGUF `Q4_K_M` build of `nexusgeo-qwen3-4b-v2`, a parameter-efficient fine-tune of [`Qwen/Qwen3-4B`](https://huggingface.co/Qwen/Qwen3-4B). The adapter was trained on a bilingual (Brazilian Portuguese / English) behavioral dataset for geoscientific workflows and then merged and quantized for local inference with **Ollama** and **llama.cpp**.

* **Model:** `nexusgeo-qwen3-4b-v2` (GGUF `Q4_K_M`)
* **Base model:** [`Qwen/Qwen3-4B`](https://huggingface.co/Qwen/Qwen3-4B)
* **Fine-tuning:** QLoRA (4-bit NF4, double quantization) + LoRA merge
* **Quantization:** GGUF `Q4_K_M`, `2,497,280,608` bytes ($\approx 2.33\text{ GiB}$ / $\approx 2.50\text{ GB}$)
* **Languages:** English, Brazilian Portuguese
* **License:** Apache-2.0
* **Author:** Tiago Felipe Arruda Maia (Geologist; Adjunct Professor, Department of Geology, Federal University of Amazonas — UFAM)
* **Project:** [github.com/Prof-Tiago-Maia/NexusGeoIA](https://github.com/Prof-Tiago-Maia/NexusGeoIA)

---

## 1. Quickstart (Ollama & llama.cpp)

### Ollama — Direct from Hugging Face

```bash
# Pull the quantized model
ollama pull hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M

# Run it
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

### Ollama — REST API Call

```bash
curl http://localhost:11434/api/chat -d @- <<'JSON'
{
  "model": "nexusgeo-qwen3-4b-v2-q4",
  "stream": false,
  "options": {
    "temperature": 0,
    "seed": 42,
    "num_ctx": 32000
  },
  "messages": [
    {
      "role": "system",
      "content": "You are a behavior evaluator for NexusGeo IA. Answer only with one valid JSON object, without markdown, code fences, comments or any reasoning outside the JSON."
    },
    {
      "role": "user",
      "content": "TASK: workflow routing. Classify the workflow and source intention. Answer only with JSON: {\"workflow\":\"...\",\"intencao\":\"...\"}. Valid codes: workflow = consulta_direta | triagem_area | hidrogeologia | sondagem; intencao = LOCAL_ONLY | RIGEO_ONLY | HIBRIDO | ANA_ONLY. Input: Local documents: no. Question: triage a copper prospect with geochemical anomalies."
    }
  ]
}
JSON
```

### `llama.cpp`

```bash
# One-shot generation
llama-cli -hf tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF \
  --hf-file nexusgeo-qwen3-4b-v2-Q4_K_M.gguf \
  -c 32768 -n 1024 --temp 0 --seed 42 --jinja -cnv \
  -p "Classify the workflow and source intention for: triage a copper prospect with geochemical anomalies."

# OpenAI-compatible local server
llama-server -hf tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF \
  --hf-file nexusgeo-qwen3-4b-v2-Q4_K_M.gguf \
  -c 32768 --jinja --port 8080
```

### Python (`llama-cpp-python`)

```python
from llama_cpp import Llama

llm = Llama.from_pretrained(
    repo_id="tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF",
    filename="nexusgeo-qwen3-4b-v2-Q4_K_M.gguf",
    n_ctx=32768,
    n_threads=8,
    chat_format="chatml",
    verbose=False,
)

out = llm.create_chat_completion(
    messages=[
        {
            "role": "system",
            "content": "Answer only with one valid JSON object. No markdown, no comments, no text outside the JSON.",
        },
        {
            "role": "user",
            "content": 'TASK: governance labelling. Answer only with JSON: {"formato":"contrato|texto_livre","classificacoes":["OBSERVED|INFERRED"],"veredito":"PASS|HOLD|FAIL","motivo":"..."}. Input: a contract-valid claim whose evidence_id is missing.',
        },
    ],
    temperature=0,
    seed=42,
    max_tokens=1024,
)
print(out["choices"][0]["message"]["content"])
```
### Integration with NexusGeo IA

The application registers this GGUF through `setup_llm.py`, which rewrites the `FROM` line of the project `Modelfile` to the absolute path of the local GGUF and calls `ollama create`. From a clone of the project:

```bash
# finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4 points FROM to the local GGUF path
ollama create nexusgeo-qwen3-4b-v2-q4 -f finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4
```

> **Note:** The default model name in NexusGeo IA is `nexusgeo-qwen3-4b-v2-q4`; the application automatically falls back to `qwen3:4b` when the fine-tuned model is not registered.

---

## 2. Quantization & Hardware Requirements

### Quantization Specification

| Item | Value |
| :--- | :--- |
| **Format** | GGUF |
| **Quantization** | `Q4_K_M` (4-bit, k-quant, medium) |
| **File size** | `2,497,280,608` bytes = `2.33 GiB` (≈ 2.50 GB decimal) |
| **Quantization pipeline** | LoRA adapter merged into `Qwen/Qwen3-4B` → GGUF conversion and `Q4_K_M` quantization with `llama.cpp` |
| **Tokenizer** | Qwen3 BPE tokenizer, ChatML chat template |

`Q4_K_M` keeps most attention and feed-forward weights at 4 bits while retaining higher precision for selected tensors. It is the configuration used by the released **NexusGeo IA v1.0.0** model and is the recommended trade-off between quality and footprint for local deployment.

### Hardware Requirements

| Scenario | Requirement | Notes |
| :--- | :--- | :--- |
| **GPU, 4 GB VRAM** | Fits at short context (e.g., `num_ctx 4096`) | Reduce context; expect partial CPU offload for long prompts |
| **GPU, 6–8 GB VRAM** | Comfortable at moderate to full context | 8 GB recommended for longer documents and the `32k` context setting |
| **CPU only** | 16 GB RAM recommended (8 GB minimum) | Works on modern x86-64 laptops; throughput is CPU-bound |
| **Disk** | ≈ 2.5 GB for the GGUF | Plus Ollama / `llama.cpp` runtime |
| **Context** | Up to `32,000` tokens (`num_ctx 32000`) | Fine-tuned at `1024` tokens; long-context quality is not validated |

On CPU-only machines, the project targets 16 GB RAM notebooks and keeps the model resident between questions. No GPU is required for the application's default deployment.

---

## 3. Model Overview & Intended Use

### What This Model Is

`nexusgeo-qwen3-4b-v2` is a behavioral specialization of `Qwen3-4B` for the geoscience domain. It was fine-tuned to reproduce three verifiable behaviors that the NexusGeo IA platform relies on when answering technical geoscientific questions:

1. **Workflow and source routing** — classify a request into a workflow (`consulta_direta`, `triagem_area`, `hidrogeologia`, `sondagem`) and a source intention (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`).
2. **Structured drill-hole interval extraction** — parse *"De–Até"* (from–to) intervals from drill-hole / *sondagem* descriptions, normalizing metres, lithology, unit, thickness, and the associated status or failure reason.
3. **Epistemic governance labelling** — normalize `OBSERVED` / `INFERRED` classifications and `PASS` / `HOLD` / `FAIL` verdicts, including evidence downgrade, unknown evidence, incomplete contracts, and source failures.

> **Important:** The model is **not** a geological knowledge base. It is specialized in **behavior**, not factual memorization (*"não memoriza fatos, apenas roteamento, extração e rotulagem"*). Its value lies in producing deterministic, schema-valid JSON inside a governed pipeline—not recalling grades, ages, coordinates, or bibliographic facts.

### Geoscience Context

**NexusGeo IA** is an offline-first geoscience workstation covering geology, geochemistry, petrology, mineral exploration, and hydrogeology. Its data layer connects to Brazilian and international geological sources — **SGB/GeoSGB**, **RIGeo**, **ANM/SIGMINE**, **ANA/HidroWeb**, **SIAGAS/RIMAS**, **INDE/GEOSSIT**, **Macrostrat**, and ten international geological surveys — plus local document RAG with OCR and table extraction.

Within that platform, this model acts as the local reasoning and routing layer across:
* **Mineral exploration:** triage of prospects and targets, recognition of mineralization / anomaly / exploration vocabulary, and dispatch to the correct data sources.
* **Drilling and logging (*sondagem*):** conversion of descriptive intervals into structured, machine-readable records with canonical metre values.
* **Hydrogeology:** recognition of aquifer, well, yield, water-level, and ANA/HidroWeb station queries.
* **Geology, geochemistry, and petrology:** handling of domain vocabulary and question routing (lithology, geochemical anomalies, prospects, geological units) inside the platform's retrieval workflow.
* **Governance:** attaching an explicit epistemic status to each claim so that the interface, reports, and exports can distinguish observation from inference.

### Intended vs. Out-of-Scope Use

| Category | Scope |
| :--- | :--- |
| **Intended Use** | • Default local model of the NexusGeo IA application (`nexusgeo-qwen3-4b-v2-q4`) registered in Ollama.<br>• Direct JSON-oriented geoscientific routing, entity/interval extraction, and governance labelling in PT-BR or English.<br>• Downstream component of RAG pipelines, technical report generators, spatial/CIM workflows, and drill-hole databases needing a small, deterministic, offline model.<br>• Target hardware: notebooks/desktops without dedicated GPU (16 GB RAM), or 4–8 GB VRAM GPUs. |
| **Out-of-Scope Use** | • Factual geological consulting, resource/reserve estimation, grade calculation, geochronology, or geochemical interpretation without expert review.<br>• Autonomous exploration, drilling, or investment decisions.<br>• Medical, legal, financial, or safety-critical advice.<br>• Languages other than English and Brazilian Portuguese.<br>• General-purpose chat, coding assistance, or open-domain knowledge tasks.<br>• Treating a model-generated `OBSERVED` label as independent proof of factual truth. |

---

## 4. Evaluations

### Behavioral Evaluation (Project-Reported)

Evaluated on a deterministic behavioral benchmark using the held-out test split (**50 cases, 25 PT-BR/EN pairs, `seed=42`**), comparing the fine-tuned quantized model against the `qwen3:4b` baseline:

| Metric | `qwen3:4b` (Baseline) | `nexusgeo-qwen3-4b-v2-q4` | Improvement / Notes |
| :--- | :---: | :---: | :--- |
| **Label / Schema Accuracy** | 58.00% | **62.00%** | **+4.00 pp** behavioral routing & extraction gain |
| **JSON Schema Conformance** | 98.00% | **100.00%** | Zero schema violations across all 50 test cases |
| **Parsing Failure Rate** | 0.00% | **0.00%** | 100% valid JSON parseable output |
| **Latency `p50`** | 2,701.8 ms | **2,681.0 ms** | Measured locally via Ollama |
| **Latency `p95`** | 3,026.5 ms | **2,994.0 ms** | Measured locally via Ollama |

> **Interpretation:** This benchmark measures behavioral conformity—routing decisions, extraction correctness, and governance labelling—not factual geological accuracy. Because the test set is small (50 items) and drawn from the same synthetic generator family as the training data, these figures should be read as a regression check for the NexusGeo IA pipeline rather than a general geoscience capability score.

---

## 5. Training & Fine-Tuning Details

<details>
<summary><b>Click to expand full Training Configuration, Hyperparameters & Dataset Specs</b></summary>

### Base Model & Method

| Item | Value |
| :--- | :--- |
| **Base model** | `Qwen/Qwen3-4B` |
| **Fine-tuning method** | QLoRA (LoRA on a 4-bit quantized base) |
| **Quantization during training** | 4-bit NF4, double quantization (`bnb_4bit_use_double_quant=True`) |
| **Trainer** | TRL `SFTTrainer` (supervised fine-tuning, chat format) |
| **Adapter format** | PEFT LoRA (`task_type=CAUSAL_LM`, `bias=none`) |
| **Merging / export** | Adapter merged into the base model, then converted to GGUF with `llama.cpp` |
| **Seed** | `42` (Python, NumPy, PyTorch, CUDA; deterministic cuDNN) |

### LoRA & Optimization Hyperparameters

| LoRA Parameter | Value | Optimization Parameter | Value |
| :--- | :--- | :--- | :--- |
| **LoRA rank (`r`)** | `8` | **Epochs** | `3` |
| **`lora_alpha`** | `16` | **Learning rate** | `2e-4` |
| **`lora_dropout`** | `0.05` | **LR scheduler** | `cosine` (`warmup_ratio=0.03`) |
| **Target modules** | `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` | **Batch size** | `1` per device × `8` grad accum (`effective = 8`) |
| **Bias / Task type** | `none` / `CAUSAL_LM` | **Max sequence length** | `1024` tokens (packing disabled, gradient checkpointing enabled) |
| **Total steps** | `78` (`26 steps/epoch` × `3`) | **Precision** | `bf16` (CUDA native) / `fp16` / `fp32` |

### Training Data (`nexusgeoia_behavior_v2`)

The model was trained on `nexusgeoia_behavior_v2`, a synthetic, bilingual, paired PT-BR/EN corpus generated from the deterministic oracles of the NexusGeo IA codebase (`core.source_router`, `services.sondagem`, `core.governance`).

| Property | Value |
| :--- | :--- |
| **Dataset records** | `300` (`150` PT-BR/EN pairs) |
| **Tasks** | `sondagem_extract` (108) · `workflow_intent` (108) · `governance_label` (84) |
| **Languages** | `pt` (150) · `en` (150) |
| **Case families** | `normal` (134) · `negative` (70) · `ambiguous` (48) · `incomplete` (48) |
| **Dataset SHA-256** | `74a52f789726190f2a99eb84fa2b5afa089cfd806ab9aff6a1dd169561071ecc` |
| **Splits (70/15/15)** | Train: `206` (103 pairs) · Validation: `44` (22 pairs) · Test: `50` (25 pairs) |
| **Split & Leakage policy** | Grouped by pair, stratified by task, ordered by `sha256(salt:pair)`; verified zero ID/pair intersection with test split |

### Prompt Format & System Prompt

Training uses the Qwen3 ChatML format (`<|im_start|>` / `<|im_end|>`) with three roles: `system`, `user`, `assistant`.

```text
You are a behavior evaluator for NexusGeo IA. Answer only with one valid JSON object, without markdown, code fences, comments or any reasoning outside the JSON. Use exactly the schema keys and the allowed codes; never translate or invent codes. Use a dot as decimal separator and null for missing values. In classificacoes, keep one item per claim in the same order as the contract claims and use [] when there are no claims. Each enum field takes exactly one valid code; never concatenate codes with |. Apply the task rules before answering. Do not emit any text before or after the JSON object.
```

**Example target outputs:**
```json
{"workflow":"triagem_area","intencao":"RIGEO_ONLY"}
```
```json
{"furo":"F-01","de_m":12.5,"ate_m":18.0,"espessura_m":5.5,"unidade":"m","litologia":"gnaisse","situacao":"valido","motivo":null}
```

### Training Run Summary & Software Stack

* **Final train loss:** `0.00314` · **Final eval loss:** `0.00304` · **Eval mean token accuracy:** `0.9988` · **Total FLOPs:** `1.3859e16`
* **Software stack:** `PEFT 0.22.0` · `TRL 1.18.2` · `Transformers 5.24.1` · `PyTorch 2.14.1+cu126` · `Datasets 5.2.0` · `Tokenizers 0.23.3`

</details>

---

## 6. Limitations, Bias & Recommendations

### Functional Limitations
* **Behavior, not knowledge:** Trained on routing, extraction, and governance labels. Does not memorize geological facts, stratigraphic ages, mineral deposits, grades, or bibliographic references.
* **Narrow task scope:** Covers three output contracts (`workflow_intent`, `sondagem_extract`, `governance_label`). Prompts outside these contracts may produce plausible-looking JSON that does not follow any schema.
* **JSON-only behavior:** Optimized to emit a single JSON object; not trained for conversational explanation, tool calling, code generation, or long-form technical writing.
* **Short training context:** Fine-tuned at `max_seq = 1024`. Quality on long documents, multi-document RAG contexts, and long drill-hole tables up to 32k tokens is not validated.
* **Small evaluation set & quantization:** Evaluated on 50 synthetic test items; no systematic FP16-vs-`Q4_K_M` ablation is published, so minor edge-case degradation is expected.
* **No factuality guarantee or domain RLHF:** Cannot verify whether a cited `evidence_id` exists; the platform's deterministic `core/governance.py` remains the authority.

### Bias & Ethical Considerations
* **Geographic & linguistic bias:** Centered on Brazilian Portuguese/English and Brazilian geoscience sources (SGB/RIGeo, ANM/SIGMINE, ANA/HidroWeb) plus international survey vocabulary.
* **Synthetic-label & base-model bias:** Reproduces the project's deterministic rule conventions and inherits `Qwen3-4B` pre-training biases.
* **Exploration, economic & data sovereignty risks:** Schema-valid JSON is not proof of geological correctness. Outputs require review by a licensed geologist before drilling, land-use, or investment decisions, and users remain responsible for access control over local restricted documents.

### Operational Recommendations
1. Always validate JSON against the NexusGeo IA contract before acting on it.
2. Keep `temperature 0` and `seed 42` for reproducible pipeline runs.
3. Treat `OBSERVED` as a model-produced classification label, never as independent proof.
4. Review outputs with a domain expert before any technical, operational, or commercial decision.
5. Re-run the project's deterministic benchmark after any re-quantization or prompt change.

---

## 7. Citation, License & Contact

### Citation

**BibTeX:**
```bibtex
@misc{maia2026nexusgeoqwen3,
  author       = {Maia, Tiago Felipe Arruda},
  title        = {NexusGeo Qwen3-4B v2: A QLoRA-Tuned Geoscience Assistant Model (GGUF Q4\_K\_M)},
  year         = {2026},
  publisher    = {Hugging Face},
  howpublished = {\url{https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF}},
  note         = {Fine-tuned from Qwen/Qwen3-4B; part of the NexusGeo IA project},
  url          = {https://github.com/Prof-Tiago-Maia/NexusGeoIA}
}
```

**APA:**
> Maia, T. F. A. (2026). *NexusGeo Qwen3-4B v2: A QLoRA-tuned geoscience assistant model (GGUF Q4_K_M)* [Model]. Hugging Face. https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF

**Project Citation:**
> MAIA, Tiago Felipe Arruda. *NexusGeo IA: plataforma integrada de dados geocientíficos e inteligência artificial local*. Version 1.0.0. Manaus: Federal University of Amazonas, 2026. Available at: https://github.com/Prof-Tiago-Maia/NexusGeoIA.

### License
The model card and released weights are distributed under **Apache-2.0**, consistent with the `Qwen/Qwen3-4B` base model license. The **NexusGeo IA** application source code is distributed separately under the **MIT** license. The model is provided *"as is"*, without warranties of any kind.

### Contact
* **Author:** Tiago Felipe Arruda Maia — Geologist; Adjunct Professor, Department of Geology, Federal University of Amazonas (UFAM), Manaus, Brazil.
* **Project repository:** [github.com/Prof-Tiago-Maia/NexusGeoIA](https://github.com/Prof-Tiago-Maia/NexusGeoIA)
* **Model repository:** [huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
* **Issues & contributions:** Please open an issue in the [GitHub project repository](https://github.com/Prof-Tiago-Maia/NexusGeoIA/issues).
