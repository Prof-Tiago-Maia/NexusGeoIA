# NexusGeo IA · v0.9.0

![Versão](https://img.shields.io/badge/vers%C3%A3o-v0.9.0-blue)
![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)
![Python](https://img.shields.io/badge/Python-3.13%20%7C%203.14-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-x64-0078D6?logo=windows&logoColor=white)
![Streamlit](https://img.shields.io/badge/interface-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Ollama](https://img.shields.io/badge/IA%20local-Ollama-000000)

**Plataforma Integrada de Dados Geocientíficos e Inteligência Artificial Local**

O **NexusGeo IA** reúne, em uma única interface desktop, um assistente técnico
capaz de consultar bases geocientíficas brasileiras e internacionais, recuperar
conhecimento de acervos documentais locais (RAG), interpretar coordenadas e
folhas do Mapa Índice (CIM), gerar mapas espaciais e emitir pareceres técnicos
em Word — tudo com **processamento 100 % local**, sem enviar dados para
serviços de nuvem.

> **Overview (EN).** NexusGeo IA is an offline-first geoscience workstation:
> a local LLM assistant (Ollama) that searches Brazilian and international
> geological databases, performs document RAG with OCR and table extraction,
> parses coordinates and CIM map sheets, renders spatial layers, and exports
> technical reports to `.docx`. Release **v0.9.0** targets a portable Windows
> build — no administrator privileges and no cloud dependency required.

---

## Sumário

- [Sobre o Projeto](#sobre-o-projeto)
- [Principais Funcionalidades](#principais-funcionalidades)
- [Instalação Rápida — Versão Portátil Windows (v0.9.0)](#instalação-rápida--versão-portátil-windows-v090)
- [Execução via Código-Fonte (Desenvolvedores)](#execução-via-código-fonte-desenvolvedores)
- [Arquitetura do Projeto](#arquitetura-do-projeto)
- [Roadmap & Atualizações Futuras](#roadmap--atualizações-futuras)
- [Empacotamento (Mantenedores)](#empacotamento-mantenedores)
- [Qualidade e Testes](#qualidade-e-testes)
- [Créditos e Origem](#créditos-e-origem)
- [Como Citar](#como-citar)
- [Licença](#licença)

---

## Sobre o Projeto

**NexusGeo IA v0.9.0** é uma *release candidate* de uma plataforma de apoio à
pesquisa e ao trabalho técnico em Geociências. O projeto nasceu da prática de
integração de IA generativa com Python e evoluiu para um aplicativo completo,
organizado em camadas de interface (`app.py`), orquestração (`core/`), serviços
(`services/`), persistência local (`database/`, `data/`) e empacotamento
(`packaging/`).

| Item | Descrição |
| --- | --- |
| **Versão** | `0.9.0` (Release Candidate) — fonte única em `config.py` (`APP_VERSION`) |
| **Autor** | **Tiago Felipe Arruda Maia** — Geólogo; Prof. Adjunto, Departamento de Geologia / UFAM |
| **Idiomas da interface** | Português do Brasil (padrão) e Inglês |
| **Plataforma da release** | Windows x64 — pacote portátil (`--onedir`) |
| **IA** | 100 % local via [Ollama](https://ollama.com) |
| **Interface** | [Streamlit](https://streamlit.io) |
| **Licença** | MIT |

O diferencial do NexusGeo IA é a **integração orientada ao domínio geológico**:
as respostas não são apenas texto genérico de um LLM, mas sínteses apoiadas em
registros reais de bases públicas, com origem rastreável, mapa das feições
citadas, tabelas exportáveis e um parecer técnico institucional ao final.

---

## Principais Funcionalidades

### 🤖 Inteligência Artificial 100 % Local

- Inferência via **Ollama**, sem chave de API e sem tráfego para a nuvem.
- Detecção automática de **RAM** para recomendar o modelo adequado ao hardware.
- Catálogo curado de três modelos, com download assistido e barra de progresso:

  | Modelo | Perfil de hardware | RAM ocupada (aprox.) | Uso recomendado |
  | --- | --- | --- | --- |
  | `qwen3:4b` | Sem GPU dedicada, 16 GB RAM | ~2,6 GB | Roteamento rápido e síntese RAG fluida |
  | `qwen3:14b` | Workstation / GPU (≥ 8 GB VRAM ou 32+ GB RAM) | ~9,0 GB | Máxima profundidade analítica |
  | `qwen2.5:3b` | Notebooks antigos, 8 GB RAM | ~1,9 GB | Operação ultraleve e consultas objetivas |

- Assistente gráfico (`setup_llm.py`) para escolher, baixar e trocar modelos;
  posteriormente, `NexusGeoIA.exe --setup-modelo` reabre o seletor.
- Configuração persistida em `config_local.json`. Sem configuração local nem
  `OLLAMA_MODEL`, o fallback é `qwen3:4b`; entre os modelos instalados, a
  prioridade é `qwen3:14b` > `qwen3:4b` > `qwen2.5:3b`.

### 📚 RAG Documental com OCR e Extração de Tabelas

- Upload e indexação de **`.pdf`, `.md` e `.txt`** em `data/docs/`.
- Conversão de PDF para Markdown com **OCR leve em CPU** (RapidOCR/ONNX
  Runtime), sem exigir a instalação do Tesseract no Windows.
- Limpeza de cabeçalhos, rodapés e numeração de páginas; cache de Markdown
  recalculável.
- Busca híbrida **PT-BR / EN** com glossário geológico bilíngue e expansão de
  consultas.
- Extração e tipagem de tabelas de relatórios e boletins de sondagem, com
  exportação para **Excel (`.xlsx`)** e **CSV** pronto para **QGIS**.

### 🗺️ Bases Geocientíficas Integradas

**Nacionais (sem chave de API):**

- **SGB / RIGeo** — acervo técnico-científico e comunidades do Serviço
  Geológico do Brasil.
- **GeoSGB** — ocorrências minerais e jazidas (WFS e espelho ArcGIS).
- **ANM / SIGMINE** — processos minerários ativos, com filtros por substância,
  titular e UF.
- **ANA / HidroWeb** — inventário de estações hidrometeorológicas (REST + SOAP,
  com cache local de 15 dias).
- **SIAGAS / RIMAS** — poços e dados hidrogeológicos.
- **INDE / GEOSSIT** — geossítios e camadas do patrimônio geológico.
- **Macrostrat** — unidades litoestratigráficas e idades.

**Internacionais (10 provedores, sem chave de API):**

- **OneGeology**, **USGS / ScienceBase**, **EGDI**, **Geoscience Australia**,
  **GSJ / AIST** (Japão), **GeoNet / GNS** (Nova Zelândia), **NRCan / GEO.ca**
  (Canadá), **CGS** (África), **NGD** (Arábia Saudita) e **GSI / Bhukosh**
  (Índia).
- Seleção por região na barra lateral, execução concorrente com
  `ThreadPoolExecutor`, deduplicação e cache local em `data/cache_api/`.
- **OpenAlex** para literatura científica, com reconstrução de resumos e links
  de PDF.
- Pesquisa web opcional via DuckDuckGo (`ddgs`), mantendo o aplicativo
  funcional offline.

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
- As feições ficam gravadas na mensagem: reabrir uma conversa antiga
  restaura o mapa sem repetir consultas.

### 🧠 Perfis Analíticos Especializados

- Perfis prontos: **Geociências Geral**, **Geologia Regional & Mapeamento
  Geológico**, **Exploração Mineral & Geoquímica**, **Hidrogeologia &
  Recursos Hídricos**, **Geotecnia & Geologia de Engenharia**,
  **Sensoriamento Remoto & Geofísica**, **Licenciamento & Risco Ambiental** e
  **Personalizado**.
- O perfil é anexado ao *system prompt* base (`prompts/system_base.txt`), que
  pode ser editado na interface, salvo como padrão ou restaurado.

### 📄 Parecer Técnico Institucional

- Geração de **`.docx`** e **`.md`** a partir de qualquer resposta.
- Cabeçalho institucional, escopo, análise com tabelas nativas, síntese
  espacial em WGS84, referências em **ABNT NBR 6023** e rodapé com numeração e
  hash de rastreabilidade.
- Exportação sob demanda, sem custo em conversas longas.

### 🌐 Interface Bilíngue e Histórico Local

- Alternância **🇧🇷 PT-BR / 🇬🇧 EN** no topo da barra lateral; todo texto de
  interface vive em `utils/i18n.py`.
- Histórico automático de conversas em `data/historico/` (JSON), com título,
  fontes, metadados, mapa e perfil analítico preservados.
- Banco SQLite local (`data/atendimentos.db`) para atendimentos.

---

## Instalação Rápida — Versão Portátil Windows (v0.9.0)

A distribuição oficial da `v0.9.0` é o pacote portátil
**`NexusGeoIA_v0.9.0_Portatil.zip`** (~211 MB). Não é necessário instalar
Python, nem usar privilégios de administrador.

### Requisitos

- **Windows 10/11 x64**.
- **8 GB de RAM** (16 GB recomendado; 32 GB para `qwen3:14b`).
- **~10 GB livres** em disco (pacote + modelos do Ollama).
- **Ollama** instalado — o pacote orienta o download caso ele não esteja
  presente.
- Conexão com a internet apenas para baixar o pacote e os modelos na primeira
  execução; depois, o uso é offline.

### Passo a passo

1. Acesse a página de releases:
   **[github.com/Prof-Tiago-Maia/NexusGeoIA/releases](https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases)**.
2. Em **Assets**, baixe **`NexusGeoIA_v0.9.0_Portatil.zip`**.
3. Extraia **todo** o conteúdo para uma pasta curta e gravável, por exemplo
   `C:\NexusGeoIA` (evite `Downloads` e caminhos com mais de 100 caracteres).
   - No Explorer: clique com o botão direito → **Extrair Tudo…**
   - Não execute o aplicativo de dentro do `.zip`.
4. Abra a pasta extraída e execute **`iniciar.bat`** (recomendado) ou
   **`NexusGeoIA.exe`**.
5. Na primeira execução, o assistente de modelos abre automaticamente:
   escolha um ou mais modelos e aguarde o download. O `config_local.json` é
   gravado ao final.
6. O navegador abre sozinho em `http://localhost:8501` (ou na próxima porta
   livre entre 8501 e 8510).

> **Aviso do Windows SmartScreen.** O executável ainda não possui assinatura
> digital comercial (prevista para a `v1.0.0`). Se aparecer a tela azul
> "O Windows protegeu o computador", clique em **Mais informações** →
> **Executar assim mesmo**. O código-fonte é público e auditável neste
> repositório.

### Conteúdo do pacote portátil

```text
NexusGeoIA_v0.9.0_Portatil/
├── NexusGeoIA.exe          # Executável principal (sem console)
├── _internal/              # Bibliotecas, recursos e dados do RapidOCR
├── iniciar.bat             # Inicialização com detecção de porta e Python
├── setup_llm.py            # Assistente de seleção/download de modelos
├── prompts/                # System prompt base
├── .streamlit/             # Configuração da interface
├── PROTOCOLO_PESQUISA.md   # Protocolo de pesquisa e citação
├── README.md               # Este documento
└── LEIA-ME.txt             # Orientação rápida bilíngue
```

Os dados do usuário (histórico, documentos, banco e `config_local.json`)
ficam **na própria pasta extraída**: mover a pasta leva o acervo junto. Se
a pasta extraída não for gravável (por exemplo, `C:\Program Files`), o
launcher cai automaticamente para `%LOCALAPPDATA%\NexusGeoIA`. O
executável instalado via Inno Setup também usa `%LOCALAPPDATA%\NexusGeoIA`.

### Problemas comuns

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| "Ollama não encontrado" | Serviço ausente ou parado | Instale em [ollama.com/download](https://ollama.com/download) e execute `ollama serve` |
| Porta 8501 indisponível | Outra instância aberta | O `iniciar.bat` escolhe automaticamente a próxima porta livre (8501–8510) |
| Download de modelo interrompido | Rede instável | Reabra `NexusGeoIA.exe --setup-modelo` e retome |
| Erro ao extrair o `.zip` | Caminho longo (`MAX_PATH`) | Extraia em `C:\NexusGeoIA` |
| Parecer em Word falha | `python-docx` ausente no pacote | Reinstale o pacote oficial; o `.md` continua disponível |

---

## Execução via Código-Fonte (Desenvolvedores)

### Requisitos

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
assistente de modelos pode ser aberto com:

```powershell
.\.venv\Scripts\python.exe setup_llm.py
```

Para criar explicitamente a tabela do banco SQLite:

```powershell
.\.venv\Scripts\python.exe -c "from database.init_db import inicializar_banco; inicializar_banco()"
```

### Variáveis de ambiente principais

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | Endereço do servidor Ollama |
| `OLLAMA_MODEL` | `qwen3:4b` (fallback) | Modelo padrão quando não há `config_local.json` |
| `OLLAMA_NUM_CTX` | `32000` | Janela de contexto em tokens |
| `OLLAMA_NUM_PREDICT` | `16384` | Máximo de tokens gerados |
| `OLLAMA_KEEP_ALIVE` | `-1` | Mantém o modelo carregado entre perguntas |
| `ASSISTENTE_DATA_DIR` | pasta do projeto / `%LOCALAPPDATA%` | Diretório gravável de dados |
| `ANM_SSL_VERIFY` | `1` | Verificação TLS do serviço da ANM |

Segredos e configurações locais **nunca** devem ser versionados: use variáveis
de ambiente ou `config_local.json` (ignorado pelo Git).

---

## Arquitetura do Projeto

```text
NexusGeoIA/
├── app.py                     # Interface Streamlit: chat, fontes, mapa, parecer
├── config.py                  # Fonte única de versão, diretórios e Ollama
├── launcher_desktop.py        # Entrada do executável (--onedir) e autoteste
├── setup_llm.py               # Assistente Tkinter de modelos + download
├── iniciar.bat                # Inicialização do pacote portátil
├── requirements.txt           # Dependências fixadas por faixa
├── core/
│   ├── assistant.py           # Orquestração das fontes e da resposta
│   ├── source_router.py       # Seleção de fontes por intenção/palavras-chave
│   ├── smart_router.py        # Roteamento e classificação de consultas
│   ├── prompt_manager.py      # Montagem do contexto e do system prompt
│   └── analytical_profiles.py # Perfis analíticos especializados
├── services/
│   ├── llm_service.py         # Cliente Ollama e listagem de modelos
│   ├── rag_service.py         # Indexação e busca RAG bilíngue
│   ├── document_parser.py     # PDF/MD/TXT → Markdown, OCR e limpeza
│   ├── table_extractor.py     # Extração/tipagem e exportação CSV/Excel
│   ├── external_api_service.py# Conectores SGB, ANM, ANA, GeoSGB, internacionais
│   ├── spatial_parser.py      # Coordenadas, GMS, folhas CIM e camadas do mapa
│   ├── report_generator.py    # Parecer técnico .docx/.md e referências ABNT
│   ├── history_service.py     # Persistência local das conversas (JSON)
│   ├── geocoding_service.py   # Geocodificação de localidades
│   ├── weather_service.py     # Integração meteorológica (Open-Meteo)
│   ├── database_service.py    # Consultas ao SQLite de atendimentos
│   └── glossario_bilingue.py  # Glossário geológico PT-BR/EN
├── utils/
│   └── i18n.py                # Dicionário PT-BR/EN e instrução de idioma
├── database/
│   ├── connection.py          # Conexão SQLite
│   └── init_db.py             # Criação idempotente da tabela
├── data/                      # Dados locais (conteúdo do usuário ignorado)
│   ├── docs/                  # Documentos enviados (RAG)
│   ├── historico/             # Conversas salvas
│   ├── cache_md/              # Markdown derivado de PDFs
│   ├── cache_ana/             # Cache do inventário ANA
│   └── cache_api/             # Cache dos serviços internacionais
├── prompts/
│   └── system_base.txt        # System prompt padrão editável
├── .streamlit/
│   └── config.toml            # Tema e servidor
├── packaging/
│   ├── assistente.spec        # Especificação PyInstaller (--onedir)
│   ├── installer.iss          # Script Inno Setup 6
│   ├── build_portatil.ps1     # Build do pacote portátil + .zip
│   ├── build_installer.ps1    # Build do instalador Windows
│   └── smoke_test_artefatos.py# Validação offline dos artefatos
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
classificação de intenção (core/smart_router.py, source_router.py)
       │
       ├──► RAG local (services/rag_service.py) ──► documentos em data/docs
       ├──► SGB/RIGeo, GeoSGB, ANM, ANA, SIAGAS, GEOSSIT, Macrostrat
       └──► 10 serviços geológicos internacionais + OpenAlex + web
       │
       ▼
montagem do contexto e do system prompt (core/prompt_manager.py)
       │
       ▼
LLM local (services/llm_service.py → Ollama)
       │
       ├──► resposta em Markdown (PT-BR ou EN)
       ├──► tabelas extraídas (CSV/Excel)
       ├──► mapa espacial (services/spatial_parser.py)
       └──► parecer técnico .docx/.md (services/report_generator.py)
```

---

## Roadmap & Atualizações Futuras

O roadmap abaixo é **evolutivo** e sujeito a priorização por uso real. As
versões futuras são planejadas, não compromissos de prazo.

### `v0.9.0` — Atual · Concluída

Foco: consolidar a plataforma e publicar a primeira distribuição portátil.

- [x] Arquitetura multi-base geocientífica (Brasil + Internacional).
- [x] RAG documental com OCR leve e cache de Markdown.
- [x] Extração de tabelas e exportação para Excel/CSV (QGIS).
- [x] Parser espacial de coordenadas (decimal, GMS) e folhas CIM.
- [x] Interface bilíngue PT-BR / EN.
- [x] Perfis analíticos especializados.
- [x] Geração de pareceres técnicos em `.docx` e `.md`.
- [x] Distribuição portátil Windows em `--onedir`
  (`NexusGeoIA_v0.9.0_Portatil.zip`).
- [x] Instalador Inno Setup inicial (complementar).

### `v1.0.0` — Estabilidade, Instalador Windows & Auditoria de Modelos

Foco: confiabilidade de instalação e rigor metodológico das respostas.

- [ ] **Instalador Windows (`Setup.exe`) aprimorado**
  - instalação no espaço do usuário (`PrivilegesRequired=lowest`), sem UAC;
  - **assinatura digital** do executável e do instalador, reduzindo alertas do
    SmartScreen;
  - ***polling* inteligente de inicialização do servidor Ollama**: aguardar o
    serviço ficar pronto antes de declarar indisponibilidade, eliminando
    alertas falsos;
  - diagnóstico explícito de **permissões de diretório** (`%LOCALAPPDATA%`,
    pasta portátil somente leitura, antivírus).
- [ ] **Sistema de auditoria e mitigação de viés entre famílias de LLMs**
  - uso de modelos de famílias distintas para revisão cruzada de consultas
    externas e sínteses técnicas;
  - registro da cadeia de revisão no parecer, evitando auto-confirmação.
- [ ] **Extração estruturada rigorosa (JSON Schema / Pydantic)**
  - validação de dados geoquímicos, litológicos e de coordenadas;
  - contratos tipados para exportação tabular, com erros explícitos em vez de
    campos silenciosamente vazios.

### `v1.1.0` — Análise Visual Interativa, Grafos Geocientíficos & Diagramas Petrológicos

Foco: transformar dados extraídos em interpretação visual.

- [ ] **PyGWalker** para exploração visual interativa das tabelas extraídas de
  relatórios e boletins de sondagem, diretamente na interface.
- [ ] **Grafos interativos locais** (`NetworkX` + `PyVis`, inspirados no padrão
  `graph-app-kit`), 100 % offline, para mapear redes de relações entre:
  - unidades litoestratigráficas;
  - ocorrências minerais (Au, Ni-Cu-PGE, ETR);
  - processos minerários da ANM;
  - folhas CIM;
  - literatura científica (OpenAlex).
- [ ] **Plotagem petrológica e geoquímica nativa**:
  - diagramas **AFM**, **Jensen**, **QAPF** e **TAS**;
  - *spidergrams* de **Elementos Terras Raras (ETR)** normalizados ao condrito
    e ao manto primitivo.

### `v1.2.0` — SIG Avançado & Exportação Geoespacial

Foco: sair do mapa de pontos para análise territorial completa.

- [ ] **Mapas interativos multicamada** sobrepondo:
  - polígonos de processos minerários (**ANM/SIGMINE**);
  - ocorrências minerais (**GeoSGB**);
  - estações hidrológicas (**ANA/SIAGAS**);
  - articulação de folhas **CIM**.
- [ ] **Exportação geoespacial direta**:
  - **GeoPackage (`.gpkg`)**;
  - **Shapefile**;
  - ambos prontos para abertura no **QGIS**, com camadas nomeadas e metadados
    de origem.

### `v1.3.0+` — Arquitetura Desacoplada, Multi-Plataforma & Colaboração em Nuvem

Foco: escalar o uso individual para equipes e outras plataformas.

- [ ] **Desacoplamento frontend/backend**:
  - frontend **Streamlit** e backend de processamento/inferência em **FastAPI**
    (inspirado no padrão `streamlit-fastapi-model-serving`);
  - execução assíncrona de OCR e consultas pesadas, sem bloquear a interface;
  - futura integração direta via **plugin no QGIS**.
- [ ] **Empacotamento nativo**:
  - **Linux** (`.AppImage` / `.tar.gz`);
  - **macOS** (`.dmg`).
- [ ] **Backend opcional em nuvem**:
  - **Supabase** + **PostGIS** para compartilhamento de acervos documentais;
  - histórico colaborativo de projetos;
  - consultas espaciais em equipe, preservando o modo local como padrão.

### Resumo do roadmap

| Versão | Tema central | Status |
| --- | --- | --- |
| `v0.9.0` | Plataforma multi-base + portátil Windows | ✅ Concluída |
| `v1.0.0` | Instalador assinado, auditoria de modelos, extração tipada | 🚧 Planejada |
| `v1.1.0` | PyGWalker, grafos e diagramas petrológicos | 🗓️ Planejada |
| `v1.2.0` | SIG multicamada e exportação GeoPackage/Shapefile | 🗓️ Planejada |
| `v1.3.0+` | FastAPI, Linux/macOS e colaboração em nuvem | 🗓️ Planejada |

---

## Empacotamento (Mantenedores)

Os scripts leem a versão diretamente de `config.py` e geram artefatos
versionados.

```powershell
# Pacote portátil: dist\NexusGeoIA\ + dist\NexusGeoIA_v0.9.0_Portatil.zip
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1

# Instalador Windows: executa o build portátil e compila o Inno Setup
powershell -ExecutionPolicy Bypass -File .\packaging\build_installer.ps1

# Opções úteis
powershell -ExecutionPolicy Bypass -File .\packaging\build_portatil.ps1 -Limpar
powershell -ExecutionPolicy Bypass -File .\packaging\build_installer.ps1 -SemInno
```

- O modo **`--onedir`** (`NexusGeoIA.exe` + `_internal/`) elimina o erro
  `Could not create temporary directory!` do antigo `--onefile`, abre mais
  rápido e reduz falsos positivos de antivírus. A pasta `_internal/` deve
  sempre viajar ao lado do `.exe`.
- O build portátil executa `tests/test_packaging_offline.py` **antes** de
  compilar: se um teste falhar, nenhum artefato é publicado.
- A validação do `.exe` compilado é feita pelo mantenedor no terminal nativo
  do Windows; os testes automatizados não abrem a GUI.

---

## Qualidade e Testes

A suíte é **offline**: não acessa a rede, não exige Ollama e não abre
navegador.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Cobertura principal:

- parsers e normalização dos conectores nacionais e internacionais;
- filtro por região, deduplicação e cache;
- RAG, extração de tabelas e referências ABNT;
- parser espacial (coordenadas decimais, GMS e folhas CIM);
- internacionalização (`utils/i18n.py`) e instrução de idioma do LLM;
- interface Streamlit via `AppTest`, incluindo troca de idioma;
- sintaxe dos scripts de empacotamento (`.spec`, `.iss` e `.ps1`).

---

## Créditos e Origem

O NexusGeo IA evoluiu a partir da estrutura base estudada em:

- **[EricoBorgonove/ia-generativa-python-integracoes](https://github.com/EricoBorgonove/ia-generativa-python-integracoes)**
  — repositório de referência sobre integrações de IA generativa com Python,
  que serviu de ponto de partida para a organização em camadas e para os
  primeiros conectores.

Sobre essa base, o NexusGeo IA acrescenta identidade científica geológica,
bases brasileiras e internacionais, RAG documental com OCR, parser espacial,
perfis analíticos, parecer técnico em Word e distribuição portátil Windows.

**Autor e mantenedor:** Tiago Felipe Arruda Maia — Geólogo; Professor Adjunto,
Departamento de Geologia, Universidade Federal do Amazonas (UFAM).

Contribuições são bem-vindas via *issues* e *pull requests*. Para mudanças
maiores, abra uma issue descrevendo a proposta antes de enviar o código.

---

## Como Citar

```text
MAIA, Tiago Felipe Arruda. NexusGeo IA: plataforma integrada de dados
geocientíficos e inteligência artificial local. Versão 0.9.0. Manaus:
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
