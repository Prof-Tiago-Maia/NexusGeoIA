# NexusGeo IA · v1.0.0

**🌐 Language / Idioma:** [🇧🇷 Português (BR)](README.md) · [🇬🇧 English](README.en.md)

![Version](https://img.shields.io/badge/version-v1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/Python-3.13%20%7C%203.14-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-x64-0078D6?logo=windows&logoColor=white)
![Streamlit](https://img.shields.io/badge/interface-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Ollama](https://img.shields.io/badge/local%20AI-Ollama-000000)
[![Hugging Face Model](https://img.shields.io/badge/Hugging_Face-nexusgeo--qwen3--4b--v2--GGUF-FFD21E?style=for-the-badge&logo=huggingface&logoColor=000)](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)

**Integrated Geoscience Data and Local Artificial Intelligence Platform**

**NexusGeo IA v1.0.0** brings together, in a single desktop workstation, a
technical assistant capable of querying Brazilian and international geoscience
databases, retrieving knowledge from local document collections (RAG),
interpreting coordinates and Map Index (CIM) sheets, extracting lithology from
drill-hole logs, rendering spatial maps, and issuing technical reports in Word
and Markdown — with explicit epistemic governance (`OBSERVED`/`INFERRED` and
`PASS`/`HOLD`/`FAIL`) and **100% local inference** through Ollama.

> **Visão geral (PT-BR).** O NexusGeo IA v1.0.0 é uma estação de trabalho
> geocientífica offline-first: um assistente com LLM local (Ollama) que
> consulta bases geológicas brasileiras e internacionais, executa RAG
> documental com OCR e extração de tabelas, interpreta coordenadas e folhas do
> Mapa Índice (CIM), extrai litologia de boletins de sondagem, renderiza camadas
> espaciais, exporta pareceres técnicos em `.docx` e audita cada resposta com
> governança explícita. A release entrega um modelo **fine-tuned por QLoRA e
> quantizado em GGUF Q4_K_M** (`nexusgeo-qwen3-4b-v2-q4`, ~2.5 GB) que roda em
> notebooks de 16 GB de RAM, com fallback automático para `qwen3:4b`. A
> interface técnica usa tema GIS escuro e um layout adaptativo de três colunas.
>
> **Modelo publicado (Hugging Face).** Os pesos GGUF oficiais são públicos em
> [huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
> sob licença **Apache-2.0**: `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`.

---

## Table of Contents

- [About the Project](#about-the-project)
- [What's New in v1.0.0](#whats-new-in-v100)
- [Local AI Engine and Fine-Tuning](#local-ai-engine-and-fine-tuning)
- [Key Features](#key-features)
- [Data Source Catalog by Macro-Domain](#data-source-catalog-by-macro-domain)
- [Visual Identity and Epistemic Governance (Phase D4)](#visual-identity-and-epistemic-governance-phase-d4)
- [Official Distribution of v1.0.0](#official-distribution-of-v100)
- [Official mode 1 — Windows Portable Build (`.zip`)](#official-mode-1--windows-portable-build-zip)
- [Official mode 2 — Running from Source](#official-mode-2--running-from-source-developers)
- [Project Architecture](#project-architecture)
- [Behavioral Evaluation and Fine-Tuning (`finetuning/`)](#behavioral-evaluation-and-fine-tuning-finetuning)
- [Roadmap & Future Updates](#roadmap--future-updates)
- [Packaging (Maintainers)](#packaging-maintainers)
- [Quality and Tests](#quality-and-tests)
- [Credits and Origin](#credits-and-origin)
- [How to Cite](#how-to-cite)
- [License](#license)

---

## About the Project

**NexusGeo IA v1.0.0** is the first stable release of a platform designed to
support research and technical work in the Geosciences. The project grew out of
the practice of integrating generative AI with Python and evolved into a
complete application organized into interface layers (`app.py`, `ui/`),
orchestration (`core/`), services (`services/`), domain adapters
(`adapters/`), local persistence (`services/db_service.py`, `data/`), and
packaging (`packaging/`).

| Item | Description |
| --- | --- |
| **Version** | `1.0.0` (stable) — single source of truth in `config.py` (`APP_VERSION`) |
| **Author** | **Tiago Felipe Arruda Maia** — Geologist; Adjunct Professor, Department of Geology / UFAM |
| **UI languages** | Brazilian Portuguese (default) and English |
| **Release platform** | Windows x64 — portable Build (`.zip`, `--onedir`) and source-code execution (Python/Streamlit) |
| **AI** | 100% local via [Ollama](https://ollama.com), with a custom fine-tuned model |
| **Interface** | [Streamlit](https://streamlit.io), Workstation GIS Dark Mode theme |
| **License** | MIT |

The distinguishing feature of NexusGeo IA is **domain-oriented geological
integration**: answers are not generic LLM text, but syntheses grounded in real
records from public databases, with traceable origin, a map of the cited
features, exportable tables, and an institutional technical report at the end.
Every statement receives an epistemic badge: **`OBSERVED`** when anchored to
an `evidence_id` and a source, **`INFERRED`** when it is an interpretive
synthesis produced by the model.

---

## What's New in v1.0.0

- **Validated custom model:** `nexusgeo-qwen3-4b-v2-q4`, fine-tuned with
  QLoRA on `Qwen3-4B` and quantized to **GGUF `Q4_K_M`** (~2.5 GB), with
  **62.00%** accuracy on the deterministic benchmark (`split=teste`, 50 cases,
  `seed=42`), versus **58.00%** for the `qwen3:4b` baseline.
- **100.00% JSON schema conformance** and **0.00% parsing failure**, with
  `p50 = 2,681 ms` and `p95 = 2,994 ms` latency.
- **Model published on Hugging Face:** the official GGUF weights are at
  [`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
  under the **Apache-2.0** license, installable with a single command:
  `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`.
- **Automatic fallback** to `qwen3:4b` when the fine-tuned model is not
  registered, Ollama is unavailable, or the user selects another model.
- **Workstation GIS Dark Mode (Phase D4):** technical dark theme, adaptive
  three-column layout, and visual epistemic traceability.
- **Drill-hole/lithology extraction (Phase D3b)** consolidated in
  `services/sondagem.py`, with interval validation, overlap, and gap checks.
- **Source catalog by macro-domain** in the sidebar, covering Brazil,
  international geological surveys, literature, and the local document
  collection.
- **Test suite with 738+ tests** (740 methods in the current version),
  `pytest` or `unittest`, fully offline.

---

## Local AI Engine and Fine-Tuning

### Model `nexusgeo-qwen3-4b-v2-q4` — the single model of v1.0.0

The **default model of v1.0.0** is `nexusgeo-qwen3-4b-v2-q4`. It **replaces the
old multi-model catalog of v0.9.0**: the release no longer maintains its own
model catalog, and the sidebar selector only reflects what is already installed
in Ollama. The only reserve model is `qwen3:4b`, used as an **automatic
fallback** by `services/llm_service.py` (`PREFERRED_LOCAL_MODELS`,
`modelo_padrao_do_sistema`, `resolve_default_ollama_model`).

The SLM is specialized in the **behavior** of NexusGeo IA, not in factual
memorization. It was built in two stages:

1. **QLoRA on `Qwen/Qwen3-4B`**, with 4-bit **NF4 quantization and double
   quantization** (`bitsandbytes`), a conservative LoRA adapter (`r=8`,
   `lora_alpha=16`), `seed=42`, and the deterministic split of the v2 corpus
   (70% training / 15% validation / 15% test).
2. **GGUF `Q4_K_M` conversion and quantization** (**2.33 GiB** / `~2.50 GB`),
   registered in Ollama with `temperature 0`, `seed 42`, and `num_ctx 32000`
   for deterministic decoding.

| Specification | Value |
| --- | --- |
| Ollama name | `nexusgeo-qwen3-4b-v2-q4` |
| Base model | `Qwen/Qwen3-4B` |
| Method | QLoRA — 4-bit **NF4**, double quantization |
| LoRA | `r=8`, `lora_alpha=16` |
| Corpus | `nexusgeoia_behavior_v2` — bilingual PT-BR/EN, 300 deterministic records (150 pairs) |
| Distribution | GGUF `Q4_K_M` — 2.33 GiB / `~2.50 GB` |
| Official repository | [`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF) |
| License | **Apache-2.0** |
| Hardware | 16 GB RAM (CPU) or a 4–8 GB VRAM GPU; **100% offline** |

The result fits on **16 GB RAM notebooks** and keeps the model loaded between
questions. Training artifacts live in
`finetuning/adaptadores/nexusgeo-qwen3-4b-v2/` and the registration templates
in `finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4`.

### Official Hugging Face repository

The quantized weights are officially published at
**[huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)**
under the **Apache-2.0** license, with the complete model card (intended use,
training details, limitations, and bias) in `finetuning/huggingface/README.md`.
The published file is `nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`, compatible with
Ollama and `llama.cpp`.

```powershell
# Direct install from Hugging Face, without cloning the project
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

### Behavior-first focus

Training is **behavior-first**: the target is the deterministic JSON
orchestration consumed by the platform, not an isolated factual encyclopedia.
The three contracts covered are:

- **`workflow_intent`** — workflow (`consulta_direta`, `triagem_area`,
  `hidrogeologia`, `sondagem`) and source intent (`LOCAL_ONLY`,
  `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`).
- **`sondagem_extract`** — structured From–To extraction in meters (hole,
  lithology, unit, thickness, and status/reason), with m/cm normalization.
- **`governance_label`** — `OBSERVED`/`INFERRED` label and
  `PASS`/`HOLD`/`FAIL` verdict, including downgrade for missing evidence.

The ground truth is recomputed by the real modules (`core/source_router.py`,
`services/sondagem.py`, `core/governance.py`), not written by hand; the corpus
is generated deterministically from the project code.

### Validated result on the deterministic benchmark

Behavioral benchmark on the **`nexusgeoia_behavior_v2`** dataset, with **50
cases from `split=teste`** (25 PT-BR/EN pairs), `seed=42`, comparing the
fine-tuned model with the `qwen3:4b` baseline:

| Metric | `qwen3:4b` (baseline) | `nexusgeo-qwen3-4b-v2-q4` | Gain |
| --- | ---: | ---: | ---: |
| Label/schema accuracy | 58.00% | **62.00%** | **+4.00 p.p.** |
| JSON schema conformance | 98.00% | **100.00%** | **+2.00 p.p.** |
| Parsing failure | 0.00% | **0.00%** | — |
| p50 latency | 2,701.8 ms | **2,681 ms** | −20.8 ms |
| p95 latency | 3,026.5 ms | **2,994 ms** | −32.5 ms |

The benchmark covers three tasks: `workflow`/`source-intent` routing,
structured From–To drill-hole extraction, and governance labeling
(`OBSERVED`/`INFERRED`, `PASS`/`HOLD`/`FAIL`). It measures **behavior and
conformance**, not factual accuracy of geological data.

In absolute numbers, the official model delivers **100.00% JSON schema
conformance** (0% parsing error) and **62.00% routing/extraction accuracy**
(+4.00 p.p. over `qwen3:4b`), with `p50` of **2.68 s** and `p95` of
**2.99 s**, running **100% offline** on 16 GB RAM (CPU) or GPUs with 4–8 GB
VRAM.

### Model resolution and fallback

The effective order is:

1. explicit choice in `config_local.json` (written by `setup_llm.py`);
2. `OLLAMA_MODEL` environment variable;
3. `nexusgeo-qwen3-4b-v2-q4`, if registered in Ollama;
4. `qwen3:4b` as the factory **silent fallback**.

The fallback is implemented in `services/llm_service.py`
(`PREFERRED_LOCAL_MODELS`, `modelo_padrao_do_sistema`,
`resolve_default_ollama_model`) and in `setup_llm.py`
(`registrar_modelo_local`). The interface never freezes when Ollama is down:
the selector opens on the configured default model and the model list is
resolved with a short timeout.

### External providers

Inference is local, but the **data layer is multi-provider**: public connectors
that require no API key live in `services/external_api_service.py` and are
activated by toggles. The project includes SGB/GeoSGB, RIGeo, ANM/SIGMINE,
ANA/HidroWeb, SIAGAS/RIMAS, INDE/GEOSSIT, Macrostrat, and **10 international
geological surveys** aggregated by
`consultar_servicos_geologicos_internacionais(...)`, with a
`ThreadPoolExecutor`, deduplication, a 12 h local cache, and silent fallback.
Literature comes from OpenAlex, and optional web search uses DuckDuckGo
(`ddgs`), keeping the application functional offline.

### Official local model

| Model | Hardware profile | RAM usage (approx.) | Recommended use |
| --- | --- | --- | --- |
| `nexusgeo-qwen3-4b-v2-q4` | No dedicated GPU, 16 GB RAM | ~2.5 GB | **Official v1.0.0 model**: routing, extraction, and governance |
| `qwen3:4b` | No dedicated GPU, 16 GB RAM | ~2.6 GB | Single technical fallback when the official GGUF is unavailable |

`setup_llm.py` automatically configures the single official model
(`nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`): if the model is already registered in
Ollama, it only writes `config_local.json`; if the local GGUF exists, it
registers via `ollama create`; if it does not exist, it downloads the official
GGUF from GitHub Releases and, on network failure, applies the `ollama pull
qwen3:4b` technical fallback. `NexusGeoIA.exe --setup-modelo` reopens this
flow. The configuration is persisted in `config_local.json`.

> **Simpler alternative:** since the GGUF is also published on Hugging Face
> (Apache-2.0), you can skip the manual download and `ollama create` by running
> `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`. In this case
> Ollama downloads and registers the model directly from the official
> repository; `config_local.json` is still written by `setup_llm.py` on the
> first application run.

---

## Key Features

### 📚 Document RAG with OCR and Table Extraction

- Upload and indexing of **`.pdf`, `.md`, and `.txt`** files in `data/docs/`.
- PDF-to-Markdown conversion with **lightweight CPU OCR**
  (RapidOCR/ONNX Runtime), with no need to install Tesseract on Windows.
  The parser accepts up to 500 pages and 100 MB per file.
- Cleanup of headers, footers, and page numbers; recalculable Markdown cache.
- **PT-BR / EN** hybrid search with a bilingual geological glossary and query
  expansion.
- Extraction and typing of tables from reports and drill-hole logs, with export
  to **Excel (`.xlsx`)** and **QGIS-ready CSV**.

### 📍 Spatial Parser and CIM Sheets

- `services/spatial_parser.py` is a lightweight engine (no GDAL/geopandas)
  that recognizes:
  - **decimal degree** pairs (`-3.1234, -60.0123`);
  - **DMS** coordinates (`03°07'24"S 60°00'44"W`, including longitude first);
  - **CIM sheet** codes (`SA.20`, `SB-21`, `SB.21-X-B`, `SC.22-Z-D-IV`),
    with centroid and bounds computed from the IBGE articulation down to
    1:50,000.
- Consolidates points from APIs, extracted tables, and text citations,
  deduplicates per layer, and assigns colors by source.
- Interactive map (`st.map`), layer filter, and CSV download (UTF-8 with BOM,
  `;` separator).
- Features are stored in the message: reopening an old conversation restores
  the map without repeating queries.

### 🧱 Drill Holes and Lithology (Phase D3b)

- `services/sondagem.py` reads PT-BR/EN headers, normalizes meters and
  centimeters, validates intervals, and preserves valid rows when another row
  fails.
- Detects **overlap and gap** per hole, computes thickness, and returns a
  deterministic signature for idempotent re-execution.
- The **Drill Holes & Lithology** tab is presentation-only
  (`ui/tab_sondagem.py`); stable codes are translated by `utils/i18n`.

### 🧠 Specialized Analytical Profiles

- Ready-made profiles: **General Geosciences**, **Regional Geology & Geological
  Mapping**, **Mineral Exploration & Geochemistry**, **Hydrogeology & Water
  Resources**, **Geotechnics & Engineering Geology**, **Remote Sensing &
  Geophysics**, **Environmental Licensing & Risk**, and **Custom**.
- The profile is appended to the base *system prompt*
  (`prompts/system_base.txt`), which can be edited in the UI, saved as default,
  or restored.

### 📄 Institutional Technical Report

- `services/report_generator.py` generates **`.docx`** and **`.md`** from
  any answer.
- Institutional header, scope, analysis with native tables, WGS84 spatial
  synthesis, **ABNT NBR 6023** references, and a footer with page numbering and
  a traceability hash.
- On-demand export, with no cost for long conversations.

### 🛡️ Governance, Drill Holes, and Safe Export

- Output contract validated by `core/governance.py`: every statement is
  classified as `OBSERVED` (requires `evidence_id`) or `INFERRED`; validation
  downgrades `OBSERVED` without evidence, removes invalid links, and prevents
  the model from declaring `PASS` on its own.
- Final verdict `PASS` (consistent), `HOLD` (review required), or `FAIL`
  (inconsistency), displayed by `ui/governanca.py` with the objective reason —
  no traceback, URL, or internal detail.
- Sanitized export: `services/exportacao_segura.py` neutralizes formulas
  (`=`, `+`, `-`, `@`, tab, CR/LF) in CSV, XLSX, and GeoJSON without
  corrupting valid negative numbers.

### 🗂️ Sources and Smart Routing

- `core/smart_router.py` classifies intent and optimizes query filters
  (municipality, state, substance, and river); `core/source_router.py` decides
  the answer origin (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`).
- `core/context_builder.py` builds the context with a token budget, and
  `core/prompt_manager.py` injects each source's tables.
- All sources with an enabled toggle are queried; intent classification only
  improves filters, without cutting databases.

### 🌐 Bilingual Interface and Local History

- **🇧🇷 PT-BR / 🇬🇧 EN** switch at the top of the sidebar; every UI string lives
  in `utils/i18n.py`.
- Transactional conversation history in SQLite (`data/nexusgeoia.db`), with
  title, sources, metadata, map, analytical profile, workflow, and governance
  preserved. The legacy JSON history in `data/historico/` is migrated
  additively on first open, without deleting the original files.
- Primary persistence in `data/nexusgeoia.db` (SQLite in **WAL** mode, with
  `-wal`/`-shm` sidecars, `foreign_keys=ON`, and a 30 s `busy_timeout`),
  resolved by `ASSISTENTE_DATA_DIR`/`NEXUSGEO_DB_PATH`. The
  `DB_INTOCADO=True` guard compares the SHA-256 of the database and sidecars
  before/after evaluation routines, which never open the file.

---

## Data Source Catalog by Macro-Domain

The **🗂️ Active Data Sources** section of the sidebar organizes databases into
four macro-domains. All public providers work **without an API key**, with a
short timeout, local cache, and silent fallback.

| Macro-domain | Source / service | Sidebar key | Scope and notes |
| --- | --- | --- | --- |
| **Geology & Geophysics** | **SGB / GeoSGB** | `geosgb_enabled` | Mineral occurrences and deposits via the Geological Survey of Brazil WFS, with an ArcGIS mirror |
| **Geology & Geophysics** | **RIGeo (SGB)** | `rigeo_enabled` | Technical-scientific collection, publications, maps, and SGB communities |
| **Geology & Geophysics** | **Macrostrat** | `macrostrat_enabled` | Lithostratigraphic units and ages (`macrostrat.org/api/v2`) |
| **Geology & Geophysics** | **OneGeology** | `intl_geo_enabled` | CSW/OpenSearch + GeoSciML WFS |
| **Geology & Geophysics** | **EGDI** | `intl_geo_enabled` | WordPress REST + CSW (Europe) |
| **Geology & Geophysics** | **Geoscience Australia** | `intl_geo_enabled` | CSW/WFS GA + CKAN GSQ |
| **Geology & Geophysics** | **GSJ / AIST (Japan)** | `intl_geo_enabled` | CKAN/GBank + 1:200,000 map |
| **Geology & Geophysics** | **GeoNet / GNS (New Zealand)** | `intl_geo_enabled` | `/quake?MMI=3` and `/volcano/val` |
| **Geology & Geophysics** | **USGS / ScienceBase** | `intl_geo_enabled` | USGS catalog and services |
| **Geology & Geophysics** | **NRCan / GEO.ca (Canada)** | `intl_geo_enabled` | CKAN/GEO.ca + GEOSCAN |
| **Geology & Geophysics** | **CGS (Africa)** | `intl_geo_enabled` | CGS + Digital Earth Africa STAC |
| **Geology & Geophysics** | **NGD (Saudi Arabia)** | `intl_geo_enabled` | WFS/GeoRSS + public search |
| **Geology & Geophysics** | **GSI / Bhukosh (India)** | `intl_geo_enabled` | WFS/OGC Bhukosh, no login |
| **Mineral Resources & ANM** | **ANM / SIGMINE** | `anm_enabled` | Active mining processes (REST + WFS), filters by substance, holder, and state, polygon centroid |
| **Mineral Resources & ANM** | **INDE / GEOSSIT** | `geossit_enabled` | Geosites and geological heritage layers |
| **Hydrogeology & Water** | **ANA / HidroWeb** | `ana_enabled` | Hydrometeorological station inventory (15-day cache, SNIRH REST + SOAP) |
| **Hydrogeology & Water** | **SIAGAS / RIMAS** | `siagas_enabled` | Wells and hydrogeological data (WFS `hidrogeologia:siagas` + ArcGIS mirror) |
| **Literature & Support** | **OpenAlex** | `openalex_enabled` | Scientific literature, with abstract reconstruction and PDF links |
| **Literature & Support** | **PDFs / local OCR** | `local_docs_enabled` | Local document collection in `data/docs/`, indexed for RAG |
| **Literature & Support** | **Web search (optional)** | `web_search_enabled` | DuckDuckGo (`ddgs`), with technical or open mode |

> **UI note:** in the sidebar, GeoSGB appears under **Mineral Resources & ANM**
> next to SIGMINE, and GEOSSIT under **Geology & Geophysics**; the table above
> groups databases by predominant technical domain.

> International services share the region multiselect (`intl_geo_regioes`) and
> run in parallel (`ThreadPoolExecutor(max_workers=6)`), with deduplication by
> title/link and preservation of origin in `fonte`. Results are cached locally
> in `data/cache_api/`.

---

## Visual Identity and Epistemic Governance (Phase D4)

### Workstation GIS Dark Mode

The theme is locked to dark mode in `.streamlit/config.toml` (no light/dark
toggle), with the technical palette below. Epistemic semantics are applied
exclusively by the CSS in `app.py` (`CSS_INTERFACE`), with reserved colors.

| Token | Hex | Use |
| --- | --- | --- |
| Background | `#0E1117` | Application background |
| Surface | `#161B22` | Cards, bars, and panels |
| Mineral cyan | `#00B4D8` | Primary color, focus, map, and actions |
| Text | `#E6EDF3` | Primary text |
| `OBSERVED` | `#2EA043` | Badge and bar for evidence-anchored statements |
| `INFERRED` | `#D29922` | Badge and bar for interpretive synthesis |

### Adaptive layout

The `ui/workstation_layout.py` module centralizes layout decisions and pure,
testable functions. The main area has two states:

- **Clean initial state:** with no indexed document, CIM feature/sheet, extracted
  table, or tracked evidence, the workspace stays centered and focused on the
  technical chat, quick suggestions, and upload.
- **Active state:** when a **document**, **map/CIM sheet**, or **active table**
  (or tracked evidence) exists, the area expands to the asymmetric three-column
  grid `[1.4, 4.6, 2.0]`:
  - **column 1 (1.4):** indicators — active sources, CIM targets, and the
    `OBSERVED` × `INFERRED` ratio;
  - **column 2 (4.6):** workspace — synthesis tabs, spatial map, data & export,
    and drill holes;
  - **column 3 (2.0):** traceability — `evidence_id` ranking, adherence,
    online/offline state, and active model.

Signals come only from already-loaded state; no PDF conversion or external query
is triggered just to decide the layout.

### Explicit traceability

| Classification | Color | Rule |
| --- | --- | --- |
| **`OBSERVED`** | `#2EA043` | Statement anchored to an `evidence_id` and a tracked source; without a link, it is downgraded |
| **`INFERRED`** | `#D29922` | Interpretive synthesis by the model, with no evidence requirement |

The final verdict is `PASS`, `HOLD`, or `FAIL`. The UI
(`ui/governanca.py` and `ui/workstation_layout.py`) only renders the badges, the
ratio, and the objective reason — the rule remains in `core/governance.py`.

---

## Official Distribution of v1.0.0

`v1.0.0` is officially distributed in **two ways**, and only two:

| # | Official mode | Artifact / command | Audience |
| --- | --- | --- | --- |
| **1** | **Windows Portable Build (`.zip`)** | `NexusGeoIA_v1.0.0_Portatil.zip` → `iniciar.bat` (or `NexusGeoIA.exe`), with `encerrar.bat` to shut down | End users on Windows, without Python |
| **2** | **Install/Run from Source Code** | `git clone` → `venv` → `pip install -r requirements.txt` → `python setup_llm.py` → `streamlit run app.py` | Developers, auditors, and other Python environments |

Both routes use the same official model `nexusgeo-qwen3-4b-v2-q4`, the same
local SQLite WAL database, and the same `setup_llm.py`. The source-code route
is detailed in [Official mode 2](#official-mode-2--running-from-source-developers).

### Official mode 1 — Windows Portable Build (`.zip`)

The portable package **`NexusGeoIA_v1.0.0_Portatil.zip`** (~210 MB, without
the Ollama models) is the recommended route for immediate use. No Python
installation or administrator privileges are required.

#### Portable build requirements

- **Windows 10/11 x64**.
- **8 GB RAM** (16 GB recommended for the official fine-tuned model).
- **~10 GB free disk** (package + Ollama models).
- **Ollama** installed — the package guides the download if it is missing.
- Internet connection only to download the package and the models on first run;
  afterwards, use is offline.

#### Step by step

1. Open the releases page:
   **[github.com/Prof-Tiago-Maia/NexusGeoIA/releases](https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases)**.
2. Under **Assets**, download **`NexusGeoIA_v1.0.0_Portatil.zip`**.
3. Extract **all** contents to a short, writable folder, for example
   `C:\NexusGeoIA` (avoid `Downloads` and paths longer than 100 characters).
   - In Explorer: right-click → **Extract All…**
   - Do not run the application from inside the `.zip`.
4. Open the extracted folder and run **`iniciar.bat`** (recommended) or
   **`NexusGeoIA.exe`**.
5. On first run, the local model configurator opens automatically: it uses the
   official GGUF when it already exists in the folder, downloads the official
   `nexusgeo-qwen3-4b-v2-Q4_K_M.gguf` model when needed, and writes
   `config_local.json` at the end. On network failure, it applies the
   `qwen3:4b` technical fallback.
6. The browser opens automatically at `http://localhost:8501` (or the next free
   port between 8501 and 8510).

> **Windows SmartScreen warning.** The executable may display an unsigned
> application warning. If the blue "Windows protected your PC" screen appears,
> click **More info** → **Run anyway**. The source code is public and auditable
> in this repository; commercial code signing is a distribution pending item,
> not an execution dependency.

#### Portable package contents

```text
NexusGeoIA_v1.0.0_Portatil/
├── NexusGeoIA.exe          # Main executable (no console)
├── _internal/              # Libraries, resources, and RapidOCR data
├── iniciar.bat             # Startup with port and Python detection
├── encerrar.bat            # Shuts down the server and child processes
├── setup_llm.py            # Official local model configurator
├── prompts/                # Base system prompt
├── .streamlit/             # UI configuration
├── ui/                     # Modularized interface modules
├── finetuning/             # Datasets, Modelfile templates, and reports
├── PROTOCOLO_PESQUISA.md   # Research and citation protocol
├── README.md               # Portuguese (Brazil) documentation
└── LEIA-ME.txt             # Bilingual quick guide
```

User data (history, documents, database, and `config_local.json`) stays **in the
extracted folder itself**: moving the folder carries the collection with it. If
the extracted folder is not writable (for example, `C:\Program Files`), the
launcher automatically falls back to the user data folder
(`%LOCALAPPDATA%\NexusGeoIA`), without requiring administrator privileges.

### Fine-tuned GGUF model registration

The GGUF **is not embedded in the package** (it is **2.33 GiB** / `~2.50 GB`).
There are two official paths to register it in Ollama.

#### Option A — direct from Hugging Face (recommended)

The official repository
[`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
(Apache-2.0) is served by Ollama itself:

```powershell
# Downloads and runs the Q4_K_M GGUF directly from Hugging Face
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

#### Option B — local GGUF + `setup_llm.py` / `ollama create`

Place the file at:

```text
models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf
```

Then run the local model configurator — it finds the GGUF, generates a temporary
`Modelfile` with the `FROM` line pointing to the absolute path, and registers
the model in Ollama:

```powershell
.\.venv\Scripts\python.exe setup_llm.py

# equivalent manual command, from the project root (the Modelfile is rewritten
# by setup_llm.py to the GGUF local absolute path):
ollama create nexusgeo-qwen3-4b-v2-q4 -f finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4
```

The versioned template
(`finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4`) fixes the official model's
deterministic decoding:

```text
FROM <absolute path of the local GGUF>
PARAMETER temperature 0
PARAMETER seed 42
PARAMETER num_ctx 32000
PARAMETER num_predict 1024
```

> In the versioned template, the `FROM` line points to
> `D:\hf_cache\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`; `setup_llm.py` rewrites it
> to the actual absolute path of the GGUF found in `models/`.

Without the local GGUF, `setup_llm.py` downloads the official file from GitHub
Releases into `models/` and registers it; if the download fails, it applies the
single `ollama pull qwen3:4b` technical fallback. The direct Hugging Face
download (Option A) is **not** executed by `setup_llm.py` in this version —
that flow remains manual and documented.

### Common issues

| Symptom | Likely cause | Solution |
| --- | --- | --- |
| "Ollama not found" | Service missing or stopped | Install from [ollama.com/download](https://ollama.com/download) and run `ollama serve` |
| Port 8501 unavailable | Another instance is open | `iniciar.bat` automatically picks the next free port (8501–8510) |
| Model download interrupted | Unstable network | Reopen `NexusGeoIA.exe --setup-modelo` and resume |
| Fine-tuned model missing | GGUF is not in `models/` | Copy the GGUF and run `setup_llm.py` again, or use `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M` |
| Error extracting the `.zip` | Long path (`MAX_PATH`) | Extract to `C:\NexusGeoIA` |
| Word report fails | `python-docx` missing from the package | Re-extract the official `.zip`; the `.md` report remains available |

---

## Official mode 2 — Running from Source (Developers)

The official route for development, auditing, and execution outside the
compiled package: the code runs straight from the repository with Python
3.13/3.14 and Streamlit. It is also how to run the project on a system other
than Windows x64.

### Source code requirements

- **Python 3.13 or 3.14** (the project is validated on Python 3.14 on Windows).
- **Git**.
- **Ollama** for LLM answers (the UI opens without it, but chat does not
  respond).

### Clone, prepare the environment, and run

```powershell
git clone https://github.com/Prof-Tiago-Maia/NexusGeoIA.git
cd NexusGeoIA

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m streamlit run app.py
```

The UI opens at `http://localhost:8501`. On first run, the local model
configurator can be opened with:

```powershell
.\.venv\Scripts\python.exe setup_llm.py
```

If you prefer not to download the GGUF manually, the official model can also be
obtained directly from Hugging Face (Apache-2.0), without copying weights into
`models/`:

```powershell
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

The main database is created automatically on first run. To create the legacy
service table (outside the main flow):

```powershell
.\.venv\Scripts\python.exe -c "from database.init_db import inicializar_banco; inicializar_banco()"
```

### Main environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `nexusgeo-qwen3-4b-v2-q4` if installed; otherwise `qwen3:4b` | Default model when there is no `config_local.json` |
| `OLLAMA_NUM_CTX` | `32000` | Context window in tokens |
| `OLLAMA_NUM_PREDICT` | `16384` | Maximum generated tokens |
| `OLLAMA_KEEP_ALIVE` | `-1` | Keeps the model loaded between questions |
| `ASSISTENTE_DATA_DIR` | project folder / `%LOCALAPPDATA%` | Writable data directory |
| `NEXUSGEO_DB_PATH` | `<data>/nexusgeoia.db` | Explicit main database path (diagnostics and tests) |
| `ANM_SSL_VERIFY` | `1` | TLS verification for the ANM service |
| `ANA_CACHE_VALIDADE_DIAS` | `15` | Validity of the ANA inventory cache |
| `CACHE_API_VALIDADE_HORAS` | `12` | Validity of the international services cache |

Secrets and local settings must **never** be versioned: use environment
variables or `config_local.json` (ignored by Git).

### Running the test suite

The suite is offline, does not access the network, does not require Ollama, and
does not open a browser. There are **738+ tests** (740 methods in the current
version). The canonical path is `unittest`; `pytest` also discovers the suite
when installed in the development environment:

```powershell
# Canonical project path
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# pytest alternative (if installed)
.\.venv\Scripts\python.exe -m pytest -q

# Packaging slice
.\.venv\Scripts\python.exe tests\test_packaging_offline.py -v

# Fine-tuning (offline, no Ollama)
.\.venv\Scripts\python.exe -m unittest tests.test_finetuning_dataset tests.test_finetuning_split tests.test_finetuning_idempotencia tests.test_finetuning_benchmark tests.test_finetuning_sft -v
```

### Generating the portable build

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1
```

The script runs `tests/test_packaging_offline.py`, compiles
`packaging/assistente.spec` with PyInstaller in `--onedir` mode, and builds
`dist/NexusGeoIA_v1.0.0_Portatil.zip` with `NexusGeoIA.exe`, `_internal/`,
`iniciar.bat`, `encerrar.bat`, `setup_llm.py`, `prompts/`, `.streamlit/`,
`ui/`, `finetuning/`, `PROTOCOLO_PESQUISA.md`, `README.md`, and `LEIA-ME.txt`.
That is the only compiled artifact of the official `v1.0.0` distribution.

---

## Project Architecture

### Layered Architecture and Persistence

| Layer | Main modules | Responsibility |
| --- | --- | --- |
| Interface | `app.py`, `ui/` | Chat, tabs, D4 layout, governance, maps, and export |
| Orchestration | `core/` | Routing (`smart_router.py`), context, prompt, and governance contract |
| Services | `services/` | RAG, OCR, LLM, connectors, drill holes, export, and report |
| Adapters | `adapters/spatial_cim.py` | Spatial resolution and offline package per CIM sheet |
| Persistence | `services/db_service.py`, `services/history_db.py`, `data/` | SQLite WAL, history, lineage, and spatial cache |
| Model | `finetuning/`, `models/` | Dataset, QLoRA, GGUF, benchmark, and Ollama registration |
| Packaging | `packaging/` | PyInstaller (`--onedir`) and Portable Build assembly |

Persistence is centralized in `services/db_service.py` (schema, WAL, and
migrations) and `services/history_db.py` (transactional history), in the data
directory (by default, `data/nexusgeoia.db`). The `database/` directory holds
only the legacy service, outside the main flow. Governance is not an optional
step: `core/governance.py` validates the output contract, and
`ui/governanca.py` exposes the `OBSERVED`/`INFERRED` badges and the
`PASS`/`HOLD`/`FAIL` verdict.

```text
NexusGeoIA/
├── app.py                     # Streamlit UI: chat, sources, map, report
├── config.py                  # Single source of version, directories, and Ollama
├── launcher_desktop.py        # Executable entry point (--onedir) and self-test
├── setup_llm.py               # Model assistant, GGUF, and download
├── iniciar.bat                # Portable package startup
├── requirements.txt           # Range-pinned dependencies
├── core/
│   ├── assistant.py           # Source and answer orchestration
│   ├── source_router.py       # Source selection by intent/keywords
│   ├── smart_router.py        # Query routing and classification
│   ├── prompt_manager.py      # Context and system prompt assembly
│   ├── context_builder.py     # Token-budgeted context (D1)
│   ├── governance.py          # OBSERVED/INFERRED contract and PASS/HOLD/FAIL
│   └── analytical_profiles.py # Specialized analytical profiles
├── services/
│   ├── llm_service.py         # Ollama client, default model, and fallback
│   ├── rag_service.py         # Bilingual RAG indexing and search
│   ├── document_parser.py     # PDF/MD/TXT → Markdown, OCR, and cleanup
│   ├── table_extractor.py     # Table extraction/typing
│   ├── external_api_service.py# SGB, ANM, ANA, GeoSGB, international connectors
│   ├── spatial_parser.py      # Coordinates, DMS, CIM sheets, and map layers
│   ├── sondagem.py            # From–To grid, validation, and signature (D3b)
│   ├── exportacao_segura.py   # Formula neutralization in CSV/XLSX/GeoJSON
│   ├── report_generator.py    # Technical report .docx/.md and ABNT references
│   ├── db_service.py          # SQLite WAL schema, lineage, and spatial cache
│   ├── history_db.py          # Transactional history in SQLite (D1)
│   ├── history_service.py     # Legacy JSON history (D1 migration)
│   ├── progress_service.py    # Per-step progress and cancellation (D3a)
│   ├── geocoding_service.py   # Locality geocoding
│   ├── weather_service.py     # Weather integration (Open-Meteo)
│   ├── database_service.py    # Legacy service
│   └── glossario_bilingue.py  # PT-BR/EN geological glossary
├── adapters/
│   └── spatial_cim.py         # Spatial resolution and offline CIM package (D2)
├── ui/
│   ├── sidebar.py             # Language, indicators, history, and shutdown
│   ├── tab_chat.py            # Workflow, answer card, and provenance
│   ├── tab_spatial.py         # Spatial resolution, offline package, and map
│   ├── tab_sondagem.py        # From–To grid and sanitized export
│   ├── workstation_layout.py  # Grid [1.4, 4.6, 2.0] and traceability (D4)
│   ├── progresso_consulta.py  # Progress and cancellation in the UI
│   └── governanca.py          # PASS/HOLD/FAIL and OBSERVED/INFERRED badges
├── utils/
│   └── i18n.py                # PT-BR/EN dictionary and language instruction
├── database/                  # Legacy service
├── data/                      # Local data (user content ignored)
│   ├── docs/                  # Uploaded documents (RAG)
│   ├── cache_md/              # Markdown derived from PDFs
│   ├── cache_ana/             # ANA inventory cache
│   ├── cache_api/             # International services cache
│   └── nexusgeoia.db          # Main database (generated at runtime)
├── models/                    # Fine-tuned GGUF (not versioned)
├── prompts/
│   └── system_base.txt        # Editable default system prompt
├── .streamlit/
│   └── config.toml            # Workstation GIS Dark Mode theme and server
├── packaging/                 # PyInstaller and portable build (internal scripts)
├── finetuning/                # Dataset, SFT, QLoRA, GGUF, benchmark, and audit
│   ├── datasets/              # Frozen v1, v2, split, and SFT
│   ├── adaptadores/           # LoRA adapter nexusgeo-qwen3-4b-v2
│   ├── relatorios/            # JSON and Markdown benchmarks
│   └── Modelfile.*            # Ollama registration templates
├── tests/                     # Offline suite (unittest + AppTest)
├── AGENTS.md                  # Project engineering guidelines
├── PROTOCOLO_PESQUISA.md      # Research and citation protocol
├── README.md                  # Portuguese (Brazil) documentation
├── README.en.md               # English documentation
└── LICENSE
```

### Query flow

```text
User question
       │
       ▼
intent classification and filters
(core/smart_router.py, core/source_router.py)
       │
       ├──► local RAG (services/rag_service.py, document_parser.py)
       ├──► SGB/RIGeo, GeoSGB, ANM, ANA, SIAGAS, GEOSSIT, Macrostrat
       └──► 10 international geological surveys + OpenAlex + web
       │
       ▼
context assembly with token budget
(core/context_builder.py → core/prompt_manager.py)
       │
       ▼
local LLM (services/llm_service.py → Ollama)
   nexusgeo-qwen3-4b-v2-q4 → fallback qwen3:4b
       │
       ▼
contract governance (core/governance.py)
   OBSERVED/INFERRED · PASS/HOLD/FAIL
       │
       ├──► Markdown answer (PT-BR or EN)
       ├──► extracted tables (sanitized CSV/XLSX)
       ├──► spatial map and CIM sheets (services/spatial_parser.py)
       ├──► drill holes/lithology (services/sondagem.py)
       ├──► technical report .docx/.md (services/report_generator.py)
       └──► transactional persistence
            (services/history_db.py → data/nexusgeoia.db, WAL)
```

---

## Behavioral Evaluation and Fine-Tuning (`finetuning/`)

The `finetuning/` package covers two phases: **evaluation** (isolated from the
production flow) and **training** (run on demand, never in tests). Evaluation is
not imported by `app.py` or `ui/`, does not open `data/nexusgeoia.db`, and
preserves `DB_INTOCADO=True`.

| Task | What it evaluates |
| --- | --- |
| `workflow_intent` | Workflow (`consulta_direta`, `triagem_area`, `hidrogeologia`, `sondagem`) and source intent (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`) |
| `sondagem_extract` | From–To interval with hole, lithology, unit, canonical meters, thickness, and status/reason |
| `governance_label` | `OBSERVED`/`INFERRED` normalization and `PASS`/`HOLD`/`FAIL` verdict, including downgrade and source failures |

- **Bilingual v2 dataset:** `finetuning/datasets/nexusgeoia_behavior_v2.jsonl`,
  with **300 records / 150 PT-BR/EN pairs** (the 212-record/106-pair v1 remains
  frozen). Ground truth is recomputed by `finetuning/oraculo.py` from
  `core/source_router.py`, `services/sondagem.py`, and `core/governance.py`;
  there are no manual labels.
- **Deterministic per-pair split:**
  `finetuning/datasets/nexusgeoia_behavior_v2.split.json` groups PT-BR and EN
  from the same case, stratifies by task, and sorts by `sha256(salt:pair)`,
  with 70% training, 15% validation, and 15% test fractions (206/44/50 records).
  The manifest records the dataset SHA-256, and the audit rejects stale splits
  or split pairs.
- **Oracle and audit:** `finetuning/auditoria.py` verifies AST, contract,
  uniqueness, bilingual parity, split integrity, and the `DB_INTOCADO=True`
  guard.
- **Benchmark:** `finetuning/benchmark.py` measures label/schema accuracy,
  parsing failure, execution error, and latency (p50/p95) with the `oraculo`,
  `falha`, `ruido`, and `ollama` predictors. The official release comparison
  is `qwen3:4b` (58.00%) versus `nexusgeo-qwen3-4b-v2-q4` (62.00%), on
  `split=teste` with 50 cases and `seed=42`. Without Ollama available, the
  command exits with code 2 and does not invent metrics.
- **QLoRA and GGUF training:** `finetuning/exportar_sft.py` generates the SFT
  JSONL files; `finetuning/treinar_lora.py` runs the portable LoRA/QLoRA
  (`--quantizar-4bit`, NF4 with double quantization, `r=8`, `alpha=16`,
  `seed=42`); `finetuning/gerar_modelfile.py` produces the registration
  template; the trained adapter lives in
  `finetuning/adaptadores/nexusgeo-qwen3-4b-v2/` and the `Q4_K_M` GGUF in
  `models/`. Registration in Ollama is done by `setup_llm.py` or manually with
  `ollama create`.

```powershell
# Static audit of the dataset/split and the database guard
.\.venv\Scripts\python.exe -m finetuning.auditoria

# SFT export and training plan (without downloading weights)
.\.venv\Scripts\python.exe -m finetuning.exportar_sft
.\.venv\Scripts\python.exe -m finetuning.treinar_lora --dry-run

# Ollama comparison (only on explicit request)
.\.venv\Scripts\python.exe -m finetuning.benchmark --preditor ollama --ollama-modelo qwen3:4b --limite 50 --timeout 120
```

See [`finetuning/README.md`](finetuning/README.md) for the record format,
metrics, complete commands, and reports.

---

## Roadmap & Future Updates

The roadmap below is **evolutionary** and subject to prioritization based on real
usage. Future versions are planned, not deadline commitments.

### `v1.0.0` — Current · Stable release

Focus: consolidate the platform, the custom model, and the workstation.

- [x] Multi-database geoscience architecture (Brazil + International).
- [x] Document RAG with lightweight OCR and Markdown cache.
- [x] Table extraction and Excel/CSV export (QGIS).
- [x] Spatial coordinate parser (decimal, DMS) and CIM sheets.
- [x] From–To grid with m/cm units, overlap/gap checks, and sanitized export
  (D3b).
- [x] Transactional history in SQLite, governance, and background execution
  (D1/D2).
- [x] PT-BR / EN bilingual interface and specialized analytical profiles.
- [x] Technical reports in `.docx` and `.md`.
- [x] **`nexusgeo-qwen3-4b-v2-q4` model** (QLoRA + GGUF `Q4_K_M`), with a
  deterministic benchmark and fallback to `qwen3:4b`.
- [x] **Official GGUF publication on Hugging Face**
  ([`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF),
  Apache-2.0), with installation via `ollama run hf.co/...`.
- [x] **Workstation GIS Dark Mode (D4)** with adaptive layout and
  `OBSERVED`/`INFERRED` traceability.
- [x] Official `v1.0.0` distribution as a Windows Portable Build (`--onedir`,
  `.zip`) and source-code execution via Python/Streamlit.
- [x] Technical and user documentation consolidated in PT-BR and EN.

### `v1.0.x` — Distribution stability

- [ ] **Digital signing** of the executable (commercial certificate),
  reducing SmartScreen warnings.
- [ ] Ollama service startup *polling* with explicit diagnostics for directory
  permissions, antivirus, and occupied port.
- [ ] GGUF integrity verification on first registration.

### `v1.1.0` — Interactive Visual Analysis, Geoscience Graphs & Petrological Diagrams

- [ ] **PyGWalker** for interactive visual exploration of extracted tables.
- [ ] **Local interactive graphs** (`NetworkX` + `PyVis`, 100% offline) for
  lithostratigraphic units, mineral occurrences, ANM processes, CIM sheets, and
  literature.
- [ ] **Native petrological and geochemical plotting**: **AFM**, **Jensen**,
  **QAPF**, and **TAS** diagrams; REE *spidergrams* normalized to chondrite and
  primitive mantle.

### `v1.2.0` — Advanced GIS & Geospatial Export

- [ ] **Multi-layer interactive maps** with ANM/SIGMINE polygons, GeoSGB
  occurrences, ANA/SIAGAS stations, and CIM articulation.
- [ ] **Geospatial export** to **GeoPackage (`.gpkg`)** and **Shapefile**,
  ready for QGIS.

### `v1.3.0+` — Decoupled Architecture, Multi-Platform & Collaboration

- [ ] **Frontend/backend decoupling** (Streamlit + FastAPI), with asynchronous
  execution of OCR and heavy queries.
- [ ] **Native packaging** for Linux (`.AppImage`/`.tar.gz`) and macOS
  (`.dmg`).
- [ ] **Optional cloud backend** (Supabase + PostGIS), preserving local mode as
  the default.

### Roadmap summary

| Version | Central theme | Status |
| --- | --- | --- |
| `v1.0.0` | Multi-database platform, custom model, D4, and Windows portable | ✅ Consolidated |
| `v1.0.x` | Signing and distribution robustness | 🚧 In progress |
| `v1.1.0` | PyGWalker, graphs, and petrological diagrams | 🗓️ Planned |
| `v1.2.0` | Multi-layer GIS and GeoPackage/Shapefile export | 🗓️ Planned |
| `v1.3.0+` | FastAPI, Linux/macOS, and cloud collaboration | 🗓️ Planned |

---

## Packaging (Maintainers)

The scripts read the version directly from `config.py` and generate versioned
artifacts. The **only compiled artifact** of the official `v1.0.0`
distribution is the Windows Portable Build (`.zip`).

```powershell
# Official Portable Build: dist\NexusGeoIA\ + dist\NexusGeoIA_v1.0.0_Portatil.zip
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1

# Clean build (removes previous artifacts)
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1 -Limpar
```

- **`--onedir`** mode (`NexusGeoIA.exe` + `_internal/`) eliminates the
  `Could not create temporary directory!` error of the old `--onefile`, opens
  faster, and reduces antivirus false positives. The `_internal/` folder must
  always travel next to the `.exe`.
- The portable build runs `tests/test_packaging_offline.py` **before**
  compiling: if a test fails, no artifact is published.
- Validation of the compiled `.exe` is performed by the maintainer in the
  native Windows terminal; automated tests do not open the GUI.
- Distribution hygiene: `.dsh/`, `.venv/`, `.git/`, `tests/`,
  `__pycache__/`, caches, and secrets never enter the `.zip`.

---

## Quality and Tests

The suite is **offline**: it does not access the network, does not require
Ollama, and does not open a browser. There are **738+ tests** (740 methods in
the current version), runnable with `unittest` or `pytest`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Main coverage:

- parsers and normalization of national and international connectors;
- region filtering, deduplication, cache, and timeouts;
- RAG, table extraction, and ABNT references;
- spatial parser (decimal coordinates, DMS, and CIM sheets);
- contract governance (`OBSERVED`/`INFERRED` and `PASS`/`HOLD`/`FAIL`);
- From–To drill holes, overlap/gap, and safe export;
- transactional history, lineage, and the `DB_INTOCADO=True` guard;
- behavioral dataset, contract, deterministic split, oracle, SFT, and benchmark
  (`finetuning/`), with simulated network and Ollama;
- fine-tuned model resolution, fallback to `qwen3:4b`, and GGUF registration;
- D4 adaptive layout, epistemic ratios, and traceability;
- internationalization (`utils/i18n.py`) and the LLM language instruction;
- Streamlit interface via `AppTest`, including language switching;
- syntax of the internal packaging scripts in `packaging/`.

---

## Credits and Origin

NexusGeo IA evolved from the base structure studied in:

- **[EricoBorgonove/ia-generativa-python-integracoes](https://github.com/EricoBorgonove/ia-generativa-python-integracoes)**
  — a reference repository on generative AI integrations with Python, which
  served as a starting point for the layered organization and the first
  connectors.

On top of that base, NexusGeo IA adds a geological scientific identity, Brazilian
and international databases, document RAG with OCR, a spatial parser,
drill-hole/lithology extraction, analytical profiles, Word technical reports, a
custom fine-tuned model, and a portable Windows distribution.

**Author and maintainer:** Tiago Felipe Arruda Maia — Geologist; Adjunct
Professor, Department of Geology, Federal University of Amazonas (UFAM).

Contributions are welcome via *issues* and *pull requests*. For larger changes,
open an issue describing the proposal before sending code.

---

## How to Cite

```text
MAIA, Tiago Felipe Arruda. NexusGeo IA: integrated geoscience data and local
artificial intelligence platform. Version 1.0.0. Manaus: Federal University of
Amazonas, 2026. Available at: https://github.com/Prof-Tiago-Maia/NexusGeoIA.
Accessed: [date].
```

---

## License

Distributed under the **MIT** license. See the [LICENSE](LICENSE) file for the
full text.

```text
MIT License

Copyright (c) 2026 Tiago Felipe Arruda Maia
```

The software is provided "as is", without warranties of any kind. Responses
generated by language models are technical support and **do not replace**
professional judgment, field survey, or peer review.
