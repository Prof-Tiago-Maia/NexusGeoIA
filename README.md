# NexusGeo IA · v1.0.0

**🌐 Language / Idioma:** [🇧🇷 Português (BR)](README.md) · [🇬🇧 English](README.en.md)

![Versão](https://img.shields.io/badge/vers%C3%A3o-v1.0.0-blue)
![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)
![Python](https://img.shields.io/badge/Python-3.13%20%7C%203.14-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-x64-0078D6?logo=windows&logoColor=white)
![Streamlit](https://img.shields.io/badge/interface-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Ollama](https://img.shields.io/badge/IA%20local-Ollama-000000)
[![Hugging Face Model](https://img.shields.io/badge/Hugging_Face-nexusgeo--qwen3--4b--v2--GGUF-FFD21E?style=for-the-badge&logo=huggingface&logoColor=000)](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)

**Plataforma Integrada de Dados Geocientíficos e Inteligência Artificial Local**

O **NexusGeo IA v1.0.0** reúne, em uma única estação de trabalho desktop, um
assistente técnico capaz de consultar bases geocientíficas brasileiras e
internacionais, recuperar conhecimento de acervos documentais locais (RAG),
interpretar coordenadas e folhas do Mapa Índice (CIM), extrair litologia de
boletins de sondagem, gerar mapas espaciais e emitir pareceres técnicos em Word
e Markdown — com governança epistêmica explícita (`OBSERVED`/`INFERRED` e
`PASS`/`HOLD`/`FAIL`) e **inferência 100 % local** via Ollama.

> **Overview (EN).** NexusGeo IA v1.0.0 is an offline-first geoscience
> workstation: a local LLM assistant (Ollama) that searches Brazilian and
> international geological databases, performs document RAG with OCR and table
> extraction, parses coordinates and CIM map sheets, extracts drill-hole
> lithology, renders spatial layers, exports technical reports to `.docx`, and
> audits every answer with explicit governance. The release ships a
> **QLoRA fine-tuned, GGUF Q4_K_M-quantized** model
> (`nexusgeo-qwen3-4b-v2-q4`, ~2.5 GB) that runs on 16 GB RAM notebooks, with
> automatic fallback to `qwen3:4b`. The technical workstation UI uses a
> dark GIS theme and an adaptive three-column layout.
>
> **Published model (Hugging Face).** The official GGUF weights are public at
> [huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
> under **Apache-2.0**: `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`.

---

## Sumário

- [Sobre o Projeto](#sobre-o-projeto)
- [O que há de novo na v1.0.0](#o-que-há-de-novo-na-v100)
- [Motor de IA Local e Fine-Tuning](#motor-de-ia-local-e-fine-tuning)
- [Principais Funcionalidades](#principais-funcionalidades)
- [Catálogo de Bases por Macrodomínio](#catálogo-de-bases-por-macrodomínio)
- [Identidade Visual e Governança Epistêmica (Fase D4)](#identidade-visual-e-governança-epistêmica-fase-d4)
- [Distribuição Oficial da v1.0.0](#distribuição-oficial-da-v100)
- [Modo oficial 1 — Build Portátil Windows (`.zip`)](#modo-oficial-1--build-portátil-windows-zip)
- [Modo oficial 2 — Execução via Código-Fonte](#modo-oficial-2--execução-via-código-fonte-desenvolvedores)
- [Arquitetura do Projeto](#arquitetura-do-projeto)
- [Avaliação Comportamental e Fine-Tuning (`finetuning/`)](#avaliação-comportamental-e-fine-tuning-finetuning)
- [Roadmap & Atualizações Futuras](#roadmap--atualizações-futuras)
- [Empacotamento (Mantenedores)](#empacotamento-mantenedores)
- [Qualidade e Testes](#qualidade-e-testes)
- [Créditos e Origem](#créditos-e-origem)
- [Como Citar](#como-citar)
- [Licença](#licença)

---

## Sobre o Projeto

**NexusGeo IA v1.0.0** é a primeira release estável de uma plataforma de apoio
à pesquisa e ao trabalho técnico em Geociências. O projeto nasceu da prática de
integração de IA generativa com Python e evoluiu para um aplicativo completo,
organizado em camadas de interface (`app.py`, `ui/`), orquestração
(`core/`), serviços (`services/`), adaptadores de domínio (`adapters/`),
persistência local (`services/db_service.py`, `data/`) e empacotamento
(`packaging/`).

| Item | Descrição |
| --- | --- |
| **Versão** | `1.0.0` (estável) — fonte única em `config.py` (`APP_VERSION`) |
| **Autor** | **Tiago Felipe Arruda Maia** — Geólogo; Prof. Adjunto, Departamento de Geologia / UFAM |
| **Idiomas da interface** | Português do Brasil (padrão) e Inglês |
| **Plataforma da release** | Windows x64 — Build Portátil (`.zip`, `--onedir`) e execução via código-fonte (Python/Streamlit) |
| **IA** | 100 % local via [Ollama](https://ollama.com), com modelo fine-tuned próprio |
| **Interface** | [Streamlit](https://streamlit.io), tema Workstation GIS Dark Mode |
| **Licença** | MIT |

O diferencial do NexusGeo IA é a **integração orientada ao domínio geológico**:
as respostas não são apenas texto genérico de um LLM, mas sínteses apoiadas em
registros reais de bases públicas, com origem rastreável, mapa das feições
citadas, tabelas exportáveis e um parecer técnico institucional ao final. Cada
afirmação recebe um selo epistêmico: **`OBSERVED`** quando ancorada em
`evidence_id` e fonte, **`INFERRED`** quando é síntese interpretativa do
modelo.

---

## O que há de novo na v1.0.0

- **Modelo próprio validado:** `nexusgeo-qwen3-4b-v2-q4`, fine-tuned por
  QLoRA sobre `Qwen3-4B` e quantizado em **GGUF `Q4_K_M`** (~2,5 GB), com
  **62,00 %** de acurácia no benchmark determinístico (`split=teste`, 50 casos,
  `seed=42`), contra **58,00 %** da linha de base `qwen3:4b`.
- **100,00 % de conformidade de esquema JSON** e **0,00 % de falha de
  parsing**, com latência `p50 = 2.681 ms` e `p95 = 2.994 ms`.
- **Modelo publicado no Hugging Face:** os pesos GGUF oficiais estão em
  [`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
  sob licença **Apache-2.0**, instaláveis com um único comando
  `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`.
- **Fallback automático** para `qwen3:4b` quando o modelo fine-tuned não está
  registrado, o Ollama está indisponível ou o usuário escolhe outro modelo.
- **Workstation GIS Dark Mode (Fase D4):** tema escuro técnico, layout
  adaptativo de três colunas e rastreabilidade epistêmica visual.
- **Extração de sondagem/litologia (Fase D3b)** consolidada em
  `services/sondagem.py`, com validação de intervalos, sobreposição e lacuna.
- **Catálogo de fontes por macrodomínio** na barra lateral, cobrindo Brasil,
  serviços geológicos internacionais, literatura e acervo documental local.
- **Suíte com 738+ testes** (740 métodos na versão atual), `pytest` ou
  `unittest`, totalmente offline.

---

## Motor de IA Local e Fine-Tuning

### Modelo `nexusgeo-qwen3-4b-v2-q4` — modelo único da v1.0.0

O **modelo padrão da v1.0.0** é `nexusgeo-qwen3-4b-v2-q4`. Ele **substitui o
catálogo antigo multi-modelo da v0.9.0**: a release não mantém mais um catálogo
próprio de modelos, e o seletor da barra lateral apenas reflete o que já está
instalado no Ollama. O único modelo de reserva é `qwen3:4b`, usado como
**fallback automático** por `services/llm_service.py` (`PREFERRED_LOCAL_MODELS`,
`modelo_padrao_do_sistema`, `resolve_default_ollama_model`).

O SLM é especializado no **comportamento** do NexusGeo IA, não em memorização
factual. Ele foi construído em duas etapas:

1. **QLoRA sobre `Qwen/Qwen3-4B`**, com quantização 4-bit **NF4 com dupla
   quantização** (`bitsandbytes`), adaptador LoRA conservador (`r=8`,
   `lora_alpha=16`), `seed=42` e o split determinístico do corpus v2
   (70 % treino / 15 % validação / 15 % teste).
2. **Conversão e quantização GGUF `Q4_K_M`** (**2,33 GiB** / `~2,50 GB`),
   registrada no Ollama com `temperature 0`, `seed 42` e `num_ctx 32000` para
   decodificação determinística.

| Especificação | Valor |
| --- | --- |
| Nome no Ollama | `nexusgeo-qwen3-4b-v2-q4` |
| Modelo-base | `Qwen/Qwen3-4B` |
| Método | QLoRA — 4-bit **NF4**, dupla quantização |
| LoRA | `r=8`, `lora_alpha=16` |
| Corpus | `nexusgeoia_behavior_v2` — bilíngue PT-BR/EN, 300 registros determinísticos (150 pares) |
| Distribuição | GGUF `Q4_K_M` — 2,33 GiB / `~2,50 GB` |
| Repositório oficial | [`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF) |
| Licença | **Apache-2.0** |
| Hardware | 16 GB de RAM (CPU) ou GPU de 4–8 GB de VRAM; **100 % offline** |

O resultado cabe em **notebooks de 16 GB de RAM** e mantém o modelo carregado
entre perguntas. Os artefatos de treino ficam em
`finetuning/adaptadores/nexusgeo-qwen3-4b-v2/` e os templates de registro em
`finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4`.

### Repositório oficial no Hugging Face

Os pesos quantizados são publicados oficialmente em
**[huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)**
sob licença **Apache-2.0**, com o cartão de modelo completo (uso pretendido,
detalhes de treino, limitações e viés) em
`finetuning/huggingface/README.md`. O arquivo publicado é
`nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`, compatível com Ollama e `llama.cpp`.

```powershell
# Instalação direta a partir do Hugging Face, sem clonar o projeto
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

### Foco comportamental (*behavior-first*)

O treino é **behavior-first**: o alvo é a orquestração determinística em JSON
que a plataforma consome, e não uma enciclopédia factual isolada. Os três
contratos cobertos são:

- **`workflow_intent`** — workflow (`consulta_direta`, `triagem_area`,
  `hidrogeologia`, `sondagem`) e intenção de fontes (`LOCAL_ONLY`,
  `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`).
- **`sondagem_extract`** — extração estruturada De–Até em metros (furo,
  litologia, unidade, espessura e situação/motivo), com normalização m/cm.
- **`governance_label`** — rótulo `OBSERVED`/`INFERRED` e veredito
  `PASS`/`HOLD`/`FAIL`, incluindo rebaixamento por ausência de evidência.

O gabarito é recomputado pelos módulos reais (`core/source_router.py`,
`services/sondagem.py`, `core/governance.py`), não escrito à mão; o corpus é
gerado de forma determinística a partir do código do projeto.

### Resultado validado no benchmark determinístico

Benchmark comportamental sobre o dataset **`nexusgeoia_behavior_v2`**, com **50 casos do `split=teste`** (25 pares PT-BR/EN),
`seed=42`, comparando o modelo fine-tuned com a linha de base `qwen3:4b`:

| Métrica | `qwen3:4b` (linha de base) | `nexusgeo-qwen3-4b-v2-q4` | Ganho |
| --- | ---: | ---: | ---: |
| Acurácia de rótulo/esquema | 58,00 % | **62,00 %** | **+4,00 p.p.** |
| Conformidade de esquema JSON | 98,00 % | **100,00 %** | **+2,00 p.p.** |
| Falha de parsing | 0,00 % | **0,00 %** | — |
| Latência p50 | 2.701,8 ms | **2.681 ms** | −20,8 ms |
| Latência p95 | 3.026,5 ms | **2.994 ms** | −32,5 ms |

O benchmark cobre três tarefas: roteamento de `workflow`/intenção de fontes,
extração estruturada De–Até de sondagem e rotulagem de governança
(`OBSERVED`/`INFERRED`, `PASS`/`HOLD`/`FAIL`). Ele mede **comportamento e
conformidade**, não exatidão factual de dados geológicos.

Em números absolutos, o modelo oficial entrega **100,00 % de conformidade de
esquema JSON** (0 % de erro de parsing) e **62,00 % de acurácia de
roteamento/extração** (+4,00 p.p. sobre `qwen3:4b`), com `p50` de **2,68 s** e
`p95` de **2,99 s**, rodando **100 % offline** em 16 GB de RAM (CPU) ou em GPUs
de 4–8 GB de VRAM.

### Resolução do modelo e fallback

A ordem efetiva é:

1. escolha explícita em `config_local.json` (gravada por `setup_llm.py`);
2. variável de ambiente `OLLAMA_MODEL`;
3. `nexusgeo-qwen3-4b-v2-q4`, se estiver registrado no Ollama;
4. `qwen3:4b` como **fallback silencioso** de fábrica.

O fallback está implementado em `services/llm_service.py`
(`PREFERRED_LOCAL_MODELS`, `modelo_padrao_do_sistema`,
`resolve_default_ollama_model`) e em `setup_llm.py`
(`registrar_modelo_local`). A interface nunca trava quando o Ollama está fora
do ar: o seletor abre no modelo padrão configurado e a lista de modelos é
resolvida com tempo limite curto.

### Provedores externos

A inferência é local, mas a **camada de dados é multi-provedor**: os
conectores públicos sem chave de API ficam em
`services/external_api_service.py` e são acionados por toggles. O projeto
inclui SGB/GeoSGB, RIGeo, ANM/SIGMINE, ANA/HidroWeb, SIAGAS/RIMAS,
INDE/GEOSSIT, Macrostrat e **10 serviços geológicos internacionais** reunidos
por `consultar_servicos_geologicos_internacionais(...)`, com
`ThreadPoolExecutor`, deduplicação, cache local de 12 h e fallback silencioso.
A literatura vem do OpenAlex e a pesquisa web opcional usa DuckDuckGo
(`ddgs`), mantendo o aplicativo funcional offline.

### Modelo local oficial

| Modelo | Perfil de hardware | RAM ocupada (aprox.) | Uso recomendado |
| --- | --- | --- | --- |
| `nexusgeo-qwen3-4b-v2-q4` | Sem GPU dedicada, 16 GB RAM | ~2,5 GB | **Modelo oficial da v1.0.0**: roteamento, extração e governança |
| `qwen3:4b` | Sem GPU dedicada, 16 GB RAM | ~2,6 GB | Fallback técnico único quando o GGUF oficial não está disponível |

O `setup_llm.py` configura automaticamente o único modelo oficial
(`nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`): se o modelo já está registrado no
Ollama, apenas grava o `config_local.json`; se o GGUF local existe, registra
via `ollama create`; se não existe, baixa o GGUF oficial dos GitHub Releases
e, em falha de rede, aplica o fallback técnico `ollama pull qwen3:4b`.
`NexusGeoIA.exe --setup-modelo` reabre esse fluxo. A configuração é
persistida em `config_local.json`.

> **Alternativa mais simples:** como o GGUF também está publicado no Hugging
> Face (Apache-2.0), é possível dispensar o download manual e o
> `ollama create` executando
> `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`. Nesse caso o
> Ollama baixa e registra o modelo diretamente do repositório oficial; o
> `config_local.json` continua sendo gravado pelo `setup_llm.py` na primeira
> execução do aplicativo.

---

## Principais Funcionalidades

### 📚 RAG Documental com OCR e Extração de Tabelas

- Upload e indexação de **`.pdf`, `.md` e `.txt`** em `data/docs/`.
- Conversão de PDF para Markdown com **OCR leve em CPU**
  (RapidOCR/ONNX Runtime), sem exigir a instalação do Tesseract no Windows.
  O parser aceita até 500 páginas e 100 MB por arquivo.
- Limpeza de cabeçalhos, rodapés e numeração de páginas; cache de Markdown
  recalculável.
- Busca híbrida **PT-BR / EN** com glossário geológico bilíngue e expansão de
  consultas.
- Extração e tipagem de tabelas de relatórios e boletins de sondagem, com
  exportação para **Excel (`.xlsx`)** e **CSV** pronto para **QGIS**.

### 📍 Parser Espacial e Folhas CIM

- `services/spatial_parser.py` é um motor leve (sem GDAL/geopandas) que
  reconhece:
  - pares em **graus decimais** (`-3.1234, -60.0123`);
  - coordenadas em **GMS** (`03°07'24"S 60°00'44"W`, inclusive longitude
    primeiro);
  - códigos de **folha CIM** (`SA.20`, `SB-21`, `SB.21-X-B`,
    `SC.22-Z-D-IV`), com cálculo de centróide e limites pela articulação IBGE
    até 1:50.000.
- Consolida pontos vindos das APIs, das tabelas extraídas e das citações no
  texto, deduplica por camada e atribui cores por fonte.
- Mapa interativo (`st.map`), filtro por camada e download CSV (UTF-8 com BOM,
  separador `;`).
- As feições ficam gravadas na mensagem: reabrir uma conversa antiga restaura
  o mapa sem repetir consultas.

### 🧱 Sondagem e Litologia (Fase D3b)

- `services/sondagem.py` lê cabeçalhos PT-BR/EN, normaliza metros e
  centímetros, valida intervalos e preserva linhas válidas quando outra falha.
- Detecta **sobreposição e lacuna** por furo, calcula espessura e devolve
  assinatura determinística para reexecução idempotente.
- A aba **Sondagem & Litologia** é somente apresentação
  (`ui/tab_sondagem.py`); códigos estáveis são traduzidos por `utils/i18n`.

### 🧠 Perfis Analíticos Especializados

- Perfis prontos: **Geociências Geral**, **Geologia Regional & Mapeamento
  Geológico**, **Exploração Mineral & Geoquímica**, **Hidrogeologia &
  Recursos Hídricos**, **Geotecnia & Geologia de Engenharia**,
  **Sensoriamento Remoto & Geofísica**, **Licenciamento & Risco Ambiental** e
  **Personalizado**.
- O perfil é anexado ao *system prompt* base (`prompts/system_base.txt`), que
  pode ser editado na interface, salvo como padrão ou restaurado.

### 📄 Parecer Técnico Institucional

- `services/report_generator.py` gera **`.docx`** e **`.md`** a partir de
  qualquer resposta.
- Cabeçalho institucional, escopo, análise com tabelas nativas, síntese
  espacial em WGS84, referências em **ABNT NBR 6023** e rodapé com numeração e
  hash de rastreabilidade.
- Exportação sob demanda, sem custo em conversas longas.

### 🛡️ Governança, Sondagem e Exportação Segura

- Contrato de saída validado por `core/governance.py`: cada afirmação é
  classificada como `OBSERVED` (exige `evidence_id`) ou `INFERRED`; a
  validação rebaixa `OBSERVED` sem evidência, remove vínculos inválidos e
  impede que o modelo declare `PASS` por conta própria.
- Veredito final `PASS` (consistente), `HOLD` (revisão necessária) ou
  `FAIL` (inconsistência), exibido por `ui/governanca.py` com o motivo
  objetivo — sem traceback, URL ou detalhe interno.
- Exportação sanitizada: `services/exportacao_segura.py` neutraliza
  fórmulas (`=`, `+`, `-`, `@`, tabulação, CR/LF) em CSV, XLSX e GeoJSON
  sem corromper números negativos válidos.

### 🗂️ Fontes e Roteamento Inteligente

- `core/smart_router.py` classifica a intenção e otimiza os filtros de
  consulta (município, UF, substância e rio); `core/source_router.py` decide a
  origem da resposta (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`).
- `core/context_builder.py` monta o contexto com orçamento de tokens e
  `core/prompt_manager.py` injeta as tabelas de cada fonte.
- Todas as fontes com toggle ligado são consultadas; a classificação de
  intenção apenas melhora os filtros, sem cortar bases.

### 🌐 Interface Bilíngue e Histórico Local

- Alternância **🇧🇷 PT-BR / 🇬🇧 EN** no topo da barra lateral; todo texto de
  interface vive em `utils/i18n.py`.
- Histórico transacional de conversas no SQLite (`data/nexusgeoia.db`), com
  título, fontes, metadados, mapa, perfil analítico, workflow e governança
  preservados. O histórico JSON legado de `data/historico/` é migrado de
  forma aditiva na primeira abertura, sem apagar os arquivos originais.
- Persistência principal em `data/nexusgeoia.db` (SQLite em modo **WAL**,
  com sidecars `-wal`/`-shm`, `foreign_keys=ON` e `busy_timeout` de 30 s),
  resolvida por `ASSISTENTE_DATA_DIR`/`NEXUSGEO_DB_PATH`. A guarda
  `DB_INTOCADO=True` compara o SHA-256 do banco e dos sidecars antes/depois
  das rotinas de avaliação, que nunca abrem o arquivo.

---

## Catálogo de Bases por Macrodomínio

A seção **🗂️ Fontes de Dados Ativas** da barra lateral organiza as bases em
quatro macrodomínios. Todos os provedores públicos funcionam **sem chave de
API**, com timeout curto, cache local e fallback silencioso.

| Macrodomínio | Base / serviço | Chave da sidebar | Escopo e observações |
| --- | --- | --- | --- |
| **Geologia & Geofísica** | **SGB / GeoSGB** | `geosgb_enabled` | Ocorrências minerais e jazidas via WFS do Serviço Geológico do Brasil, com espelho ArcGIS |
| **Geologia & Geofísica** | **RIGeo (SGB)** | `rigeo_enabled` | Acervo técnico-científico, publicações, mapas e comunidades do SGB |
| **Geologia & Geofísica** | **Macrostrat** | `macrostrat_enabled` | Unidades litoestratigráficas e idades (`macrostrat.org/api/v2`) |
| **Geologia & Geofísica** | **OneGeology** | `intl_geo_enabled` | CSW/OpenSearch + WFS GeoSciML |
| **Geologia & Geofísica** | **EGDI** | `intl_geo_enabled` | WordPress REST + CSW (Europa) |
| **Geologia & Geofísica** | **Geoscience Australia** | `intl_geo_enabled` | CSW/WFS GA + CKAN GSQ |
| **Geologia & Geofísica** | **GSJ / AIST (Japão)** | `intl_geo_enabled` | CKAN/GBank + mapa 1:200.000 |
| **Geologia & Geofísica** | **GeoNet / GNS (Nova Zelândia)** | `intl_geo_enabled` | `/quake?MMI=3` e `/volcano/val` |
| **Geologia & Geofísica** | **USGS / ScienceBase** | `intl_geo_enabled` | Catálogo e serviços do USGS |
| **Geologia & Geofísica** | **NRCan / GEO.ca (Canadá)** | `intl_geo_enabled` | CKAN/GEO.ca + GEOSCAN |
| **Geologia & Geofísica** | **CGS (África)** | `intl_geo_enabled` | CGS + STAC Digital Earth Africa |
| **Geologia & Geofísica** | **NGD (Arábia Saudita)** | `intl_geo_enabled` | WFS/GeoRSS + busca pública |
| **Geologia & Geofísica** | **GSI / Bhukosh (Índia)** | `intl_geo_enabled` | WFS/OGC Bhukosh, sem login |
| **Recursos Minerais & ANM** | **ANM / SIGMINE** | `anm_enabled` | Processos minerários ativos (REST + WFS), filtros por substância, titular e UF, centroide da poligonal |
| **Recursos Minerais & ANM** | **INDE / GEOSSIT** | `geossit_enabled` | Geossítios e camadas do patrimônio geológico |
| **Hidrogeologia & Hídricos** | **ANA / HidroWeb** | `ana_enabled` | Inventário de estações hidrometeorológicas (cache de 15 dias, SNIRH REST + SOAP) |
| **Hidrogeologia & Hídricos** | **SIAGAS / RIMAS** | `siagas_enabled` | Poços e dados hidrogeológicos (WFS `hidrogeologia:siagas` + espelho ArcGIS) |
| **Literatura & Apoio** | **OpenAlex** | `openalex_enabled` | Literatura científica, com reconstrução de resumos e links de PDF |
| **Literatura & Apoio** | **PDFs / OCR local** | `local_docs_enabled` | Acervo documental próprio em `data/docs/`, indexado para RAG |
| **Literatura & Apoio** | **Pesquisa web (opcional)** | `web_search_enabled` | DuckDuckGo (`ddgs`), com modo técnico ou aberto |

> **Nota de interface:** na barra lateral, o GeoSGB aparece no grupo
> **Recursos Minerais & ANM** ao lado do SIGMINE, e o GEOSSIT no grupo
> **Geologia & Geofísica**; a tabela acima agrupa as bases pelo domínio técnico
> predominante.

> Os serviços internacionais compartilham o multiselect de regiões
> (`intl_geo_regioes`) e são executados em paralelo
> (`ThreadPoolExecutor(max_workers=6)`), com deduplicação por título/link e
> preservação da origem em `fonte`. Resultados ficam em cache local em
> `data/cache_api/`.

---

## Identidade Visual e Governança Epistêmica (Fase D4)

### Workstation GIS Dark Mode

O tema é travado em modo escuro em `.streamlit/config.toml` (sem alternador
claro/escuro), com a paleta técnica abaixo. A semântica epistêmica é aplicada
exclusivamente pelo CSS de `app.py` (`CSS_INTERFACE`), com cores reservadas.

| Token | Hex | Uso |
| --- | --- | --- |
| Fundo | `#0E1117` | Plano de fundo da aplicação |
| Superfície | `#161B22` | Cartões, barras e painéis |
| Ciano-mineral | `#00B4D8` | Cor primária, foco, mapa e ações |
| Texto | `#E6EDF3` | Texto principal |
| `OBSERVED` | `#2EA043` | Selo e barra de afirmação ancorada em evidência |
| `INFERRED` | `#D29922` | Selo e barra de síntese interpretativa |

### Layout adaptativo

O módulo `ui/workstation_layout.py` concentra a decisão de layout e as funções
puras testáveis. A área principal tem dois estados:

- **Estado inicial limpo:** sem documento indexado, feição/folha CIM, tabela
  extraída ou evidência rastreada, o workspace fica centralizado e focado no
  chat técnico, nas sugestões rápidas e no upload.
- **Estado ativo:** ao existir **documento**, **mapa/folha CIM** ou **tabela
  ativa** (ou evidência rastreada), a área expande para a grade assimétrica de
  três colunas `[1.4, 4.6, 2.0]`:
  - **coluna 1 (1.4):** indicadores — fontes ativas, alvos CIM e proporção
    `OBSERVED` × `INFERRED`;
  - **coluna 2 (4.6):** workspace — abas de síntese, mapa espacial, dados &
    exportação e sondagem;
  - **coluna 3 (2.0):** rastreabilidade — ranking de `evidence_id`, aderência,
    estado online/offline e modelo ativo.

Os sinais vêm apenas de estado já carregado; nenhuma conversão de PDF ou
consulta externa é disparada só para decidir o layout.

### Rastreabilidade explícita

| Classificação | Cor | Regra |
| --- | --- | --- |
| **`OBSERVED`** | `#2EA043` | Afirmação ancorada em `evidence_id` e fonte rastreada; sem vínculo, é rebaixada |
| **`INFERRED`** | `#D29922` | Síntese interpretativa do modelo, sem exigência de evidência |

O veredito final é `PASS`, `HOLD` ou `FAIL`. A interface
(`ui/governanca.py` e `ui/workstation_layout.py`) apenas renderiza os selos, a
proporção e o motivo objetivo — a regra permanece em `core/governance.py`.

---

## Distribuição Oficial da v1.0.0

A `v1.0.0` é distribuída oficialmente de **duas formas**, e apenas duas:

| # | Modo oficial | Artefato / comando | Público-alvo |
| --- | --- | --- | --- |
| **1** | **Build Portátil Windows (`.zip`)** | `NexusGeoIA_v1.0.0_Portatil.zip` → `iniciar.bat` (ou `NexusGeoIA.exe`), com `encerrar.bat` para encerrar | Usuários finais no Windows, sem Python instalado |
| **2** | **Instalação/Execução via Código-Fonte** | `git clone` → `venv` → `pip install -r requirements.txt` → `python setup_llm.py` → `streamlit run app.py` | Desenvolvedores, auditores e execução em outros ambientes Python |

As duas rotas usam o mesmo modelo oficial `nexusgeo-qwen3-4b-v2-q4`, o mesmo
banco SQLite WAL local e o mesmo `setup_llm.py`. O detalhamento da rota por
código-fonte está em [Modo oficial 2](#modo-oficial-2--execução-via-código-fonte-desenvolvedores).

### Modo oficial 1 — Build Portátil Windows (`.zip`)

O pacote portátil **`NexusGeoIA_v1.0.0_Portatil.zip`** (~210 MB, sem os
modelos do Ollama) é a rota recomendada para uso imediato. Não é necessário
instalar Python nem usar privilégios de administrador.

#### Requisitos do Build Portátil

- **Windows 10/11 x64**.
- **8 GB de RAM** (16 GB recomendado para o modelo fine-tuned oficial).
- **~10 GB livres** em disco (pacote + modelos do Ollama).
- **Ollama** instalado — o pacote orienta o download caso ele não esteja
  presente.
- Conexão com a internet apenas para baixar o pacote e os modelos na primeira
  execução; depois, o uso é offline.

#### Passo a passo

1. Acesse a página de releases:
   **[github.com/Prof-Tiago-Maia/NexusGeoIA/releases](https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases)**.
2. Em **Assets**, baixe **`NexusGeoIA_v1.0.0_Portatil.zip`**.
3. Extraia **todo** o conteúdo para uma pasta curta e gravável, por exemplo
   `C:\NexusGeoIA` (evite `Downloads` e caminhos com mais de 100 caracteres).
   - No Explorer: clique com o botão direito → **Extrair Tudo…**
   - Não execute o aplicativo de dentro do `.zip`.
4. Abra a pasta extraída e execute **`iniciar.bat`** (recomendado) ou
   **`NexusGeoIA.exe`**.
5. Na primeira execução, o configurador do modelo local abre
   automaticamente: ele usa o GGUF oficial quando já existe na pasta, baixa
   o modelo oficial `nexusgeo-qwen3-4b-v2-Q4_K_M.gguf` quando necessário e
   grava o `config_local.json` ao final. Em falha de rede, aplica o fallback
   técnico `qwen3:4b`.
6. O navegador abre sozinho em `http://localhost:8501` (ou na próxima porta
   livre entre 8501 e 8510).

> **Aviso do Windows SmartScreen.** O executável pode exibir o aviso de
> aplicativo não assinado. Se aparecer a tela azul "O Windows protegeu o
> computador", clique em **Mais informações** → **Executar assim mesmo**. O
> código-fonte é público e auditável neste repositório; a assinatura digital
> comercial é uma pendência de distribuição, não uma dependência de execução.

#### Conteúdo do pacote portátil

```text
NexusGeoIA_v1.0.0_Portatil/
├── NexusGeoIA.exe          # Executável principal (sem console)
├── _internal/              # Bibliotecas, recursos e dados do RapidOCR
├── iniciar.bat             # Inicialização com detecção de porta e Python
├── encerrar.bat            # Encerra o servidor e os processos filhos
├── setup_llm.py            # Configurador do modelo local oficial
├── prompts/                # System prompt base
├── .streamlit/             # Configuração da interface
├── ui/                     # Módulos da interface modularizada
├── finetuning/             # Datasets, templates Modelfile e relatórios
├── PROTOCOLO_PESQUISA.md   # Protocolo de pesquisa e citação
├── README.md               # Este documento
└── LEIA-ME.txt             # Orientação rápida bilíngue
```

Os dados do usuário (histórico, documentos, banco e `config_local.json`)
ficam **na própria pasta extraída**: mover a pasta leva o acervo junto. Se
a pasta extraída não for gravável (por exemplo, `C:\Program Files`), o
launcher cai automaticamente para a pasta de dados do usuário
(`%LOCALAPPDATA%\NexusGeoIA`), sem exigir privilégios de administrador.

### Registro do modelo GGUF fine-tuned

O GGUF **não é embutido no pacote** (tem **2,33 GiB** / `~2,50 GB`). Há dois
caminhos oficiais para registrá-lo no Ollama.

#### Opção A — direto do Hugging Face (recomendada)

O repositório oficial
[`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
(Apache-2.0) é servido pelo próprio Ollama:

```powershell
# Baixa e executa o GGUF Q4_K_M diretamente do Hugging Face
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

#### Opção B — GGUF local + `setup_llm.py` / `ollama create`

Coloque o arquivo em:

```text
models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf
```

Depois execute o configurador do modelo local — ele encontra o GGUF, gera
um `Modelfile` temporário com a linha `FROM` apontando para o caminho
absoluto e registra o modelo no Ollama:

```powershell
.\.venv\Scripts\python.exe setup_llm.py

# equivalente manual, a partir da raiz do projeto (o Modelfile é reescrito
# pelo setup_llm.py para o caminho absoluto do GGUF local):
ollama create nexusgeo-qwen3-4b-v2-q4 -f finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4
```

O template versionado
(`finetuning/Modelfile.nexusgeo-qwen3-4b-v2-q4`) fixa a decodificação
determinística do modelo oficial:

```text
FROM <caminho absoluto do GGUF local>
PARAMETER temperature 0
PARAMETER seed 42
PARAMETER num_ctx 32000
PARAMETER num_predict 1024
```

> No template versionado, a linha `FROM` aponta para
> `D:\hf_cache\nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`; o `setup_llm.py` a reescreve
> para o caminho absoluto real do GGUF encontrado em `models/`.

Sem o GGUF local, o `setup_llm.py` baixa o arquivo oficial dos GitHub
Releases para `models/` e o registra; se o download falhar, aplica o fallback
técnico único `ollama pull qwen3:4b`. O download direto do Hugging Face
(Opção A) **não** é executado pelo `setup_llm.py` nesta versão — esse fluxo
permanece manual e documentado.

### Problemas comuns

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| "Ollama não encontrado" | Serviço ausente ou parado | Instale em [ollama.com/download](https://ollama.com/download) e execute `ollama serve` |
| Porta 8501 indisponível | Outra instância aberta | O `iniciar.bat` escolhe automaticamente a próxima porta livre (8501–8510) |
| Download de modelo interrompido | Rede instável | Reabra `NexusGeoIA.exe --setup-modelo` e retome |
| Modelo fine-tuned ausente | GGUF não está em `models/` | Copie o GGUF e rode `setup_llm.py` novamente, ou use `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M` |
| Erro ao extrair o `.zip` | Caminho longo (`MAX_PATH`) | Extraia em `C:\NexusGeoIA` |
| Parecer em Word falha | `python-docx` ausente no pacote | Reextraia o `.zip` oficial; o `.md` continua disponível |

---

## Modo oficial 2 — Execução via Código-Fonte (Desenvolvedores)

Rota oficial para desenvolvimento, auditoria e execução fora do pacote
compilado: o código roda direto do repositório, com Python 3.13/3.14 e
Streamlit. É também a forma de rodar o projeto em outro sistema que não o
Windows x64.

### Requisitos do Código-Fonte

- **Python 3.13 ou 3.14** (o projeto é validado em Python 3.14 no Windows).
- **Git**.
- **Ollama** para respostas do LLM (a interface abre sem ele, mas o chat não
  responde).

### Clonar, preparar o ambiente e executar

```powershell
git clone https://github.com/Prof-Tiago-Maia/NexusGeoIA.git
cd NexusGeoIA

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m streamlit run app.py
```

A interface abre em `http://localhost:8501`. Na primeira execução, o
configurador do modelo local pode ser aberto com:

```powershell
.\.venv\Scripts\python.exe setup_llm.py
```

Se preferir não baixar o GGUF manualmente, o modelo oficial também pode ser
obtido diretamente do Hugging Face (Apache-2.0), sem clonar pesos para
`models/`:

```powershell
ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M
```

O banco principal é criado automaticamente na primeira execução. Para criar a
tabela do serviço legado de atendimentos (fora do fluxo principal):

```powershell
.\.venv\Scripts\python.exe -c "from database.init_db import inicializar_banco; inicializar_banco()"
```

### Variáveis de ambiente principais

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | Endereço do servidor Ollama |
| `OLLAMA_MODEL` | `nexusgeo-qwen3-4b-v2-q4` se instalado; senão `qwen3:4b` | Modelo padrão quando não há `config_local.json` |
| `OLLAMA_NUM_CTX` | `32000` | Janela de contexto em tokens |
| `OLLAMA_NUM_PREDICT` | `16384` | Máximo de tokens gerados |
| `OLLAMA_KEEP_ALIVE` | `-1` | Mantém o modelo carregado entre perguntas |
| `ASSISTENTE_DATA_DIR` | pasta do projeto / `%LOCALAPPDATA%` | Diretório gravável de dados |
| `NEXUSGEO_DB_PATH` | `<data>/nexusgeoia.db` | Caminho explícito do banco principal (diagnóstico e testes) |
| `ANM_SSL_VERIFY` | `1` | Verificação TLS do serviço da ANM |
| `ANA_CACHE_VALIDADE_DIAS` | `15` | Validade do cache do inventário da ANA |
| `CACHE_API_VALIDADE_HORAS` | `12` | Validade do cache dos serviços internacionais |

Segredos e configurações locais **nunca** devem ser versionados: use variáveis
de ambiente ou `config_local.json` (ignorado pelo Git).

### Execução da suíte de testes

A suíte é offline, não acessa a rede, não exige Ollama e não abre navegador.
São **738+ testes** (740 métodos na versão atual). O caminho canônico é
`unittest`; o `pytest` também descobre a suíte quando instalado no ambiente de
desenvolvimento:

```powershell
# Caminho canônico do projeto
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# Alternativa com pytest (se instalado)
.\.venv\Scripts\python.exe -m pytest -q

# Recorte de empacotamento
.\.venv\Scripts\python.exe tests\test_packaging_offline.py -v

# Fine-tuning (offline, sem Ollama)
.\.venv\Scripts\python.exe -m unittest tests.test_finetuning_dataset tests.test_finetuning_split tests.test_finetuning_idempotencia tests.test_finetuning_benchmark tests.test_finetuning_sft -v
```

### Geração do build portátil

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1
```

O script roda `tests/test_packaging_offline.py`, compila
`packaging/assistente.spec` com PyInstaller em `--onedir` e monta
`dist/NexusGeoIA_v1.0.0_Portatil.zip` com `NexusGeoIA.exe`, `_internal/`,
`iniciar.bat`, `encerrar.bat`, `setup_llm.py`, `prompts/`, `.streamlit/`,
`ui/`, `finetuning/`, `PROTOCOLO_PESQUISA.md`, `README.md` e `LEIA-ME.txt`.
Esse é o único artefato compilado da distribuição oficial da `v1.0.0`.

---

## Arquitetura do Projeto

### Arquitetura em Camadas e Persistência

| Camada | Módulos principais | Responsabilidade |
| --- | --- | --- |
| Interface | `app.py`, `ui/` | Chat, abas, layout D4, governança, mapas e exportação |
| Orquestração | `core/` | Roteamento (`smart_router.py`), contexto, prompt e contrato de governança |
| Serviços | `services/` | RAG, OCR, LLM, conectores, sondagem, exportação e parecer |
| Adaptadores | `adapters/spatial_cim.py` | Resolução espacial e pacote offline por folha CIM |
| Persistência | `services/db_service.py`, `services/history_db.py`, `data/` | SQLite WAL, histórico, linhagem e cache espacial |
| Modelo | `finetuning/`, `models/` | Dataset, QLoRA, GGUF, benchmark e registro no Ollama |
| Empacotamento | `packaging/` | PyInstaller (`--onedir`) e montagem do Build Portátil |

A persistência é centralizada em `services/db_service.py` (schema, WAL e
migrações) e `services/history_db.py` (histórico transacional), no diretório
de dados (por padrão, `data/nexusgeoia.db`). O diretório `database/` mantém
apenas o serviço legado de atendimentos, fora do fluxo principal. A governança
não é uma etapa opcional: `core/governance.py` valida o contrato de saída e
`ui/governanca.py` expõe os selos `OBSERVED`/`INFERRED` e o veredito
`PASS`/`HOLD`/`FAIL`.

```text
NexusGeoIA/
├── app.py                     # Interface Streamlit: chat, fontes, mapa, parecer
├── config.py                  # Fonte única de versão, diretórios e Ollama
├── launcher_desktop.py        # Entrada do executável (--onedir) e autoteste
├── setup_llm.py               # Assistente de modelos, GGUF e download
├── iniciar.bat                # Inicialização do pacote portátil
├── requirements.txt           # Dependências fixadas por faixa
├── core/
│   ├── assistant.py           # Orquestração das fontes e da resposta
│   ├── source_router.py       # Seleção de fontes por intenção/palavras-chave
│   ├── smart_router.py        # Roteamento e classificação de consultas
│   ├── prompt_manager.py      # Montagem do contexto e do system prompt
│   ├── context_builder.py     # Contexto com orçamento de tokens (D1)
│   ├── governance.py          # Contrato OBSERVED/INFERRED e PASS/HOLD/FAIL
│   └── analytical_profiles.py # Perfis analíticos especializados
├── services/
│   ├── llm_service.py         # Cliente Ollama, modelo padrão e fallback
│   ├── rag_service.py         # Indexação e busca RAG bilíngue
│   ├── document_parser.py     # PDF/MD/TXT → Markdown, OCR e limpeza
│   ├── table_extractor.py     # Extração/tipagem de tabelas
│   ├── external_api_service.py# Conectores SGB, ANM, ANA, GeoSGB, internacionais
│   ├── spatial_parser.py      # Coordenadas, GMS, folhas CIM e camadas do mapa
│   ├── sondagem.py            # Grade De–Até, validação e assinatura (D3b)
│   ├── exportacao_segura.py   # Neutralização de fórmulas em CSV/XLSX/GeoJSON
│   ├── report_generator.py    # Parecer técnico .docx/.md e referências ABNT
│   ├── db_service.py          # Schema SQLite WAL, linhagem e cache espacial
│   ├── history_db.py          # Histórico transacional em SQLite (D1)
│   ├── history_service.py     # Histórico JSON legado (migração D1)
│   ├── progress_service.py    # Progresso por etapa e cancelamento (D3a)
│   ├── geocoding_service.py   # Geocodificação de localidades
│   ├── weather_service.py     # Integração meteorológica (Open-Meteo)
│   ├── database_service.py    # Serviço legado de atendimentos
│   └── glossario_bilingue.py  # Glossário geológico PT-BR/EN
├── adapters/
│   └── spatial_cim.py         # Resolução espacial e pacote offline CIM (D2)
├── ui/
│   ├── sidebar.py             # Idioma, indicadores, histórico e encerramento
│   ├── tab_chat.py            # Workflow, cartão da resposta e proveniência
│   ├── tab_spatial.py         # Resolução espacial, pacote offline e mapa
│   ├── tab_sondagem.py        # Grade De–Até e exportação sanitizada
│   ├── workstation_layout.py  # Grade [1.4, 4.6, 2.0] e rastreabilidade (D4)
│   ├── progresso_consulta.py  # Progresso e cancelamento na interface
│   └── governanca.py          # Badges PASS/HOLD/FAIL e OBSERVED/INFERRED
├── utils/
│   └── i18n.py                # Dicionário PT-BR/EN e instrução de idioma
├── database/                  # Serviço legado de atendimentos
├── data/                      # Dados locais (conteúdo do usuário ignorado)
│   ├── docs/                  # Documentos enviados (RAG)
│   ├── cache_md/              # Markdown derivado de PDFs
│   ├── cache_ana/             # Cache do inventário ANA
│   ├── cache_api/             # Cache dos serviços internacionais
│   └── nexusgeoia.db          # Banco principal (gerado em tempo de execução)
├── models/                    # GGUF fine-tuned (não versionado)
├── prompts/
│   └── system_base.txt        # System prompt padrão editável
├── .streamlit/
│   └── config.toml            # Tema Workstation GIS Dark Mode e servidor
├── packaging/                 # PyInstaller e build portátil (scripts internos)
├── finetuning/                # Dataset, SFT, QLoRA, GGUF, benchmark e auditoria
│   ├── datasets/              # v1 congelada, v2, split e SFT
│   ├── adaptadores/           # Adaptador LoRA nexusgeo-qwen3-4b-v2
│   ├── relatorios/            # Benchmarks JSON e Markdown
│   └── Modelfile.*            # Templates de registro no Ollama
├── tests/                     # Suíte offline (unittest + AppTest)
├── AGENTS.md                  # Diretrizes de engenharia do projeto
├── PROTOCOLO_PESQUISA.md      # Protocolo de pesquisa e citação
├── README.md
└── LICENSE
```

### Fluxo de uma consulta

```text
Pergunta do usuário
       │
       ▼
classificação de intenção e filtros
(core/smart_router.py, core/source_router.py)
       │
       ├──► RAG local (services/rag_service.py, document_parser.py)
       ├──► SGB/RIGeo, GeoSGB, ANM, ANA, SIAGAS, GEOSSIT, Macrostrat
       └──► 10 serviços geológicos internacionais + OpenAlex + web
       │
       ▼
montagem do contexto com orçamento de tokens
(core/context_builder.py → core/prompt_manager.py)
       │
       ▼
LLM local (services/llm_service.py → Ollama)
   nexusgeo-qwen3-4b-v2-q4 → fallback qwen3:4b
       │
       ▼
governança do contrato (core/governance.py)
   OBSERVED/INFERRED · PASS/HOLD/FAIL
       │
       ├──► resposta em Markdown (PT-BR ou EN)
       ├──► tabelas extraídas (CSV/XLSX sanitizados)
       ├──► mapa espacial e folhas CIM (services/spatial_parser.py)
       ├──► sondagem/litologia (services/sondagem.py)
       ├──► parecer técnico .docx/.md (services/report_generator.py)
       └──► persistência transacional
            (services/history_db.py → data/nexusgeoia.db, WAL)
```

---

## Avaliação Comportamental e Fine-Tuning (`finetuning/`)

O pacote `finetuning/` cobre duas fases: **avaliação** (isolada do fluxo de
produção) e **treinamento** (executado sob demanda, nunca nos testes). A
avaliação não é importada por `app.py` nem por `ui/`, não abre
`data/nexusgeoia.db` e preserva `DB_INTOCADO=True`.

| Tarefa | O que avalia |
| --- | --- |
| `workflow_intent` | Workflow (`consulta_direta`, `triagem_area`, `hidrogeologia`, `sondagem`) e intenção de fontes (`LOCAL_ONLY`, `RIGEO_ONLY`, `HIBRIDO`, `ANA_ONLY`) |
| `sondagem_extract` | Intervalo De–Até com furo, litologia, unidade, metros canônicos, espessura e situação/motivo |
| `governance_label` | Normalização `OBSERVED`/`INFERRED` e veredito `PASS`/`HOLD`/`FAIL`, incluindo downgrade e falhas de fonte |

- **Dataset v2 bilíngue:** `finetuning/datasets/nexusgeoia_behavior_v2.jsonl`,
  com **300 registros / 150 pares PT-BR/EN** (a v1 de 212 registros/106 pares
  permanece congelada). O gabarito é recomputado por `finetuning/oraculo.py`
  a partir de `core/source_router.py`, `services/sondagem.py` e
  `core/governance.py`; não há rótulo manual.
- **Split determinístico por par:**
  `finetuning/datasets/nexusgeoia_behavior_v2.split.json` agrupa PT-BR e EN
  do mesmo caso, estratifica por tarefa e ordena por `sha256(sal:par)`, com
  frações de 70 % treino, 15 % validação e 15 % teste (206/44/50 registros). O
  manifesto registra o SHA-256 do dataset e a auditoria reprova split velho ou
  com par dividido.
- **Oráculo e auditoria:** `finetuning/auditoria.py` verifica AST, contrato,
  unicidade, paridade bilíngue, integridade do split e a guarda
  `DB_INTOCADO=True`.
- **Benchmark:** `finetuning/benchmark.py` mede acurácia de rótulo/esquema,
  falha de parsing, erro de execução e latência (p50/p95) com preditores
  `oraculo`, `falha`, `ruido` e `ollama`. O comparativo oficial da release
  é `qwen3:4b` (58,00 %) contra `nexusgeo-qwen3-4b-v2-q4` (62,00 %), no
  `split=teste` com 50 casos e `seed=42`. Sem Ollama disponível, o comando
  sai com código 2 e não inventa métricas.
- **Treino QLoRA e GGUF:** `finetuning/exportar_sft.py` gera os JSONL SFT;
  `finetuning/treinar_lora.py` executa o LoRA/QLoRA portátil
  (`--quantizar-4bit`, NF4 com dupla quantização, `r=8`, `alpha=16`,
  `seed=42`); `finetuning/gerar_modelfile.py` produz o template de registro;
  o adaptador treinado fica em `finetuning/adaptadores/nexusgeo-qwen3-4b-v2/`
  e o GGUF `Q4_K_M` em `models/`. O registro no Ollama é feito por
  `setup_llm.py` ou manualmente com `ollama create`.

```powershell
# Auditoria estática, do dataset/split e da guarda do banco
.\.venv\Scripts\python.exe -m finetuning.auditoria

# Exportação SFT e plano de treino (sem baixar pesos)
.\.venv\Scripts\python.exe -m finetuning.exportar_sft
.\.venv\Scripts\python.exe -m finetuning.treinar_lora --dry-run

# Comparativo com Ollama (somente sob pedido explícito)
.\.venv\Scripts\python.exe -m finetuning.benchmark --preditor ollama --ollama-modelo qwen3:4b --limite 50 --timeout 120
```

Consulte [`finetuning/README.md`](finetuning/README.md) para o formato do
registro, as métricas, os comandos completos e os relatórios.

---

## Roadmap & Atualizações Futuras

O roadmap abaixo é **evolutivo** e sujeito a priorização por uso real. As
versões futuras são planejadas, não compromissos de prazo.

### `v1.0.0` — Atual · Release estável

Foco: consolidar a plataforma, o modelo próprio e a estação de trabalho.

- [x] Arquitetura multi-base geocientífica (Brasil + Internacional).
- [x] RAG documental com OCR leve e cache de Markdown.
- [x] Extração de tabelas e exportação para Excel/CSV (QGIS).
- [x] Parser espacial de coordenadas (decimal, GMS) e folhas CIM.
- [x] Grade De–Até com unidades m/cm, sobreposição/lacuna e exportação
  sanitizada (D3b).
- [x] Histórico transacional em SQLite, governança e execução em segundo plano
  (D1/D2).
- [x] Interface bilíngue PT-BR / EN e perfis analíticos especializados.
- [x] Pareceres técnicos em `.docx` e `.md`.
- [x] **Modelo `nexusgeo-qwen3-4b-v2-q4`** (QLoRA + GGUF `Q4_K_M`), com
  benchmark determinístico e fallback para `qwen3:4b`.
- [x] **Publicação oficial do GGUF no Hugging Face**
  ([`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF),
  Apache-2.0), com instalação por `ollama run hf.co/...`.
- [x] **Workstation GIS Dark Mode (D4)** com layout adaptativo e
  rastreabilidade `OBSERVED`/`INFERRED`.
- [x] Distribuição oficial da `v1.0.0` em Build Portátil Windows (`--onedir`,
  `.zip`) e execução via código-fonte Python/Streamlit.
- [x] Documentação técnica e de usuário consolidada em PT-BR e EN.

### `v1.0.x` — Estabilidade de distribuição

- [ ] **Assinatura digital** do executável (certificado comercial),
  reduzindo alertas do SmartScreen.
- [ ] *Polling* de inicialização do serviço Ollama com diagnóstico explícito de
  permissões de diretório, antivírus e porta ocupada.
- [ ] Verificação de integridade do GGUF no primeiro registro.

### `v1.1.0` — Análise Visual Interativa, Grafos Geocientíficos & Diagramas Petrológicos

- [ ] **PyGWalker** para exploração visual interativa das tabelas extraídas.
- [ ] **Grafos interativos locais** (`NetworkX` + `PyVis`, 100 % offline) para
  unidades litoestratigráficas, ocorrências minerais, processos da ANM, folhas
  CIM e literatura.
- [ ] **Plotagem petrológica e geoquímica nativa**: diagramas **AFM**,
  **Jensen**, **QAPF** e **TAS**; *spidergrams* de ETR normalizados ao condrito
  e ao manto primitivo.

### `v1.2.0` — SIG Avançado & Exportação Geoespacial

- [ ] **Mapas interativos multicamada** com polígonos da ANM/SIGMINE,
  ocorrências do GeoSGB, estações ANA/SIAGAS e articulação CIM.
- [ ] **Exportação geoespacial** em **GeoPackage (`.gpkg`)** e **Shapefile**,
  prontos para QGIS.

### `v1.3.0+` — Arquitetura Desacoplada, Multi-Plataforma & Colaboração

- [ ] **Desacoplamento frontend/backend** (Streamlit + FastAPI), com execução
  assíncrona de OCR e consultas pesadas.
- [ ] **Empacotamento nativo** para Linux (`.AppImage`/`.tar.gz`) e macOS
  (`.dmg`).
- [ ] **Backend opcional em nuvem** (Supabase + PostGIS), preservando o modo
  local como padrão.

### Resumo do roadmap

| Versão | Tema central | Status |
| --- | --- | --- |
| `v1.0.0` | Plataforma multi-base, modelo próprio, D4 e portátil Windows | ✅ Consolidada |
| `v1.0.x` | Assinatura e robustez de distribuição | 🚧 Em andamento |
| `v1.1.0` | PyGWalker, grafos e diagramas petrológicos | 🗓️ Planejada |
| `v1.2.0` | SIG multicamada e exportação GeoPackage/Shapefile | 🗓️ Planejada |
| `v1.3.0+` | FastAPI, Linux/macOS e colaboração em nuvem | 🗓️ Planejada |

---

## Empacotamento (Mantenedores)

Os scripts leem a versão diretamente de `config.py` e geram artefatos
versionados. O **único artefato compilado** da distribuição oficial da
`v1.0.0` é o Build Portátil Windows (`.zip`).

```powershell
# Build Portátil oficial: dist\NexusGeoIA\ + dist\NexusGeoIA_v1.0.0_Portatil.zip
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1

# Build do zero (remove artefatos anteriores)
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1 -Limpar
```

- O modo **`--onedir`** (`NexusGeoIA.exe` + `_internal/`) elimina o erro
  `Could not create temporary directory!` do antigo `--onefile`, abre mais
  rápido e reduz falsos positivos de antivírus. A pasta `_internal/` deve
  sempre viajar ao lado do `.exe`.
- O build portátil executa `tests/test_packaging_offline.py` **antes** de
  compilar: se um teste falhar, nenhum artefato é publicado.
- A validação do `.exe` compilado é feita pelo mantenedor no terminal nativo
  do Windows; os testes automatizados não abrem a GUI.
- Higiene de distribuição: `.dsh/`, `.venv/`, `.git/`, `tests/`,
  `__pycache__/`, caches e segredos nunca entram no `.zip`.

---

## Qualidade e Testes

A suíte é **offline**: não acessa a rede, não exige Ollama e não abre
navegador. São **738+ testes** (740 métodos na versão atual), executáveis por
`unittest` ou `pytest`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Cobertura principal:

- parsers e normalização dos conectores nacionais e internacionais;
- filtro por região, deduplicação, cache e timeouts;
- RAG, extração de tabelas e referências ABNT;
- parser espacial (coordenadas decimais, GMS e folhas CIM);
- governança do contrato (`OBSERVED`/`INFERRED` e `PASS`/`HOLD`/`FAIL`);
- sondagem De–Até, sobreposição/lacuna e exportação segura;
- histórico transacional, linhagem e guarda `DB_INTOCADO=True`;
- dataset comportamental, contrato, split determinístico, oráculo, SFT e
  benchmark (`finetuning/`), com rede e Ollama simulados;
- resolução do modelo fine-tuned, fallback para `qwen3:4b` e registro do GGUF;
- layout adaptativo D4, proporções epistêmicas e rastreabilidade;
- internacionalização (`utils/i18n.py`) e instrução de idioma do LLM;
- interface Streamlit via `AppTest`, incluindo troca de idioma;
- sintaxe dos scripts internos de empacotamento em `packaging/`.

---

## Créditos e Origem

O NexusGeo IA evoluiu a partir da estrutura base estudada em:

- **[EricoBorgonove/ia-generativa-python-integracoes](https://github.com/EricoBorgonove/ia-generativa-python-integracoes)**
  — repositório de referência sobre integrações de IA generativa com Python,
  que serviu de ponto de partida para a organização em camadas e para os
  primeiros conectores.

Sobre essa base, o NexusGeo IA acrescenta identidade científica geológica,
bases brasileiras e internacionais, RAG documental com OCR, parser espacial,
sondagem/litologia, perfis analíticos, parecer técnico em Word, modelo próprio
fine-tuned e distribuição portátil Windows.

**Autor e mantenedor:** Tiago Felipe Arruda Maia — Geólogo; Professor Adjunto,
Departamento de Geologia, Universidade Federal do Amazonas (UFAM).

Contribuições são bem-vindas via *issues* e *pull requests*. Para mudanças
maiores, abra uma issue descrevendo a proposta antes de enviar o código.

---

## Como Citar

```text
MAIA, Tiago Felipe Arruda. NexusGeo IA: plataforma integrada de dados
geocientíficos e inteligência artificial local. Versão 1.0.0. Manaus:
Universidade Federal do Amazonas, 2026. Disponível em:
https://github.com/Prof-Tiago-Maia/NexusGeoIA. Acesso em: [data].
```

---

## Licença

Distribuído sob a licença **MIT**. Consulte o arquivo [LICENSE](LICENSE) para
o texto completo.

```text
MIT License

Copyright (c) 2026 Tiago Felipe Arruda Maia
```

O software é fornecido "como está", sem garantias de qualquer tipo. As
respostas geradas por modelos de linguagem são apoio técnico e **não
substituem** julgamento profissional, levantamento de campo ou revisão por
pares.
