# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

- Sem alterações registradas após a `v1.0.0`.

## [1.0.0] - 2026-11-24

Primeira release estável da plataforma. A `v1.0.0` consolida o modelo
especializado único, a persistência transacional em SQLite WAL, a governança
epistêmica explícita, a workstation GIS em tema escuro e o empacotamento
Windows autoverificável.

### Added

- **Modelo Especializado Único (`nexusgeo-qwen3-4b-v2-q4`)** — substituição do
  catálogo genérico de três modelos por um SLM fine-tuned por QLoRA sobre
  `Qwen3-4B`, quantizado em GGUF `Q4_K_M` (~2,5 GB) para roteamento
  geocientífico, extração estruturada e síntese RAG.
  - Provisionamento automático via `setup_llm.py`: detecção do modelo já
    registrado no Ollama, registro por `ollama create` a partir do GGUF local
    (`models/` ou cache `D:\hf_cache`) e download direto do GGUF oficial dos
    GitHub Releases quando o arquivo não existe.
  - Fallback técnico único para `qwen3:4b` em falha de rede ou de registro,
    mantendo o aplicativo operacional sem intervenção manual.
  - Benchmark comportamental determinístico (`split=teste`, 50 casos,
    `seed=42`): **62,00%** de acurácia e **100,00%** de conformidade de esquema
    JSON, contra **58,00%** de `qwen3:4b`; `p50 = 2.681 ms` e
    `p95 = 2.994 ms`, com **0,00%** de falha de parsing.
  - **Publicação oficial do GGUF no Hugging Face** — pesos `Q4_K_M` em
    [`tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF`](https://huggingface.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF)
    sob licença **Apache-2.0**, instaláveis com
    `ollama run hf.co/tiagotmaia/nexusgeo-qwen3-4b-v2-GGUF:Q4_K_M`. O
    `setup_llm.py` continua baixando dos GitHub Releases; o caminho do Hugging
    Face é a alternativa manual documentada.
- **Persistência e Concorrência (`SQLite WAL`)** — migração do armazenamento
  de histórico, sessões e metadados para SQLite em modo WAL, com
  `journal_mode=WAL`, `foreign_keys=ON` e `busy_timeout=30000`.
  - Novo `services/db_service.py` centraliza caminho do banco, schema,
    linhagem de evidências e cache espacial.
  - Novo `services/history_db.py` torna o histórico transacional e preserva
    os campos de mensagem usados pela interface e pelos pareceres.
- **Governança Epistêmica e Contexto** — `core/governance.py` valida o
  contrato de saída e impede que o modelo declare `PASS` quando há problema
  de evidência.
  - `OBSERVED` exige `evidence_id`; sem vínculo válido a afirmação é
    rebaixada para `INFERRED` e o veredito vira `HOLD`.
  - `core/context_builder.py` organiza fontes, trechos recuperados e
    rastreabilidade de evidências para prevenir alucinação em respostas
    geocientíficas.
- **Interface Workstation GIS Dark Mode** — tema escuro fixo em
  `.streamlit/config.toml` (`#0E1117` de fundo, `#161B22` em superfícies e
  `#00B4D8` como cor primária).
  - UI modularizada em `ui/` (`tab_chat`, `tab_sondagem`, `tab_spatial`,
    `sidebar`, `governanca`, `progresso_consulta`, `workstation_layout`).
  - Suporte bilíngue completo (`PT-BR` / `EN`) via `utils/i18n.py`, com
    todos os textos visíveis nos dois idiomas.
- **Extração Segura, Sondagem e Fontes Públicas** — melhorias em
  `services/sondagem.py`, `services/exportacao_segura.py`,
  `services/table_extractor.py` e `services/spatial_parser.py`.
  - Sondagem De–Até com normalização m/cm, validação de intervalos, detecção
    de sobreposição/lacuna e assinatura determinística.
  - Exportação sanitizada contra injeção de fórmulas em CSV, XLSX e GeoJSON.
  - Conectores revisados em `adapters/` e
    `services/external_api_service.py` para SGB/RIGeo, ANM/SIGMINE, USGS,
    Macrostrat, OpenAlex, ANA/HidroWeb, SIAGAS/RIMAS, INDE/GEOSSIT e serviços
    geológicos internacionais.
- **Empacotamento Windows Autoverificável (`v1.0.0`)** — manifesto dinâmico
  `packaging/coleta_interna.py` cobrindo os **37 módulos internos** no
  PyInstaller (`packaging/assistente.spec`).
  - Modo `--self-test` embutido no `launcher_desktop.py`, executado em modo
    headless e validado automaticamente pelo `packaging/smoke_exe.py` ao final
    do `build_portatil.ps1`.
  - O self-test verifica recursos de runtime, banco SQLite WAL temporário,
    modelo oficial e imports de topo de `app.py` antes de gerar o `.zip`.

### Changed

- O catálogo próprio de modelos foi eliminado: a barra lateral reflete apenas
  os modelos instalados no Ollama e abre no modelo oficial da release.
- O `setup_llm.py` passou a aplicar um fluxo único de provisionamento, sem
  escolha interativa de catálogo e sem detecção de perfil de RAM.
- A distribuição Windows passou a ser bloqueante: o build só conclui quando o
  executável compilado passa integralmente no `--self-test`.
- A distribuição oficial da `v1.0.0` passou a ser **exclusivamente** o Build
  Portátil Windows (`.zip`, `build_portatil.ps1` / `NexusGeoIA.exe` /
  `iniciar.bat` / `encerrar.bat`) e a instalação/execução via código-fonte
  (`git clone`, `venv`, `pip install -r requirements.txt`, `python
  setup_llm.py`, `streamlit run app.py`). O Build Portátil (`.zip`) é o
  **único artefato compilado** da release `v1.0.0`.
- A documentação de release, o `README.md`, o `AGENTS.md` e o protocolo de
  pesquisa foram alinhados ao estado final da `v1.0.0`.
- A documentação principal ganhou a versão inglesa sincronizada
  `README.en.md`, com seletor de idioma no topo dos dois arquivos.

### Removed

- Catálogo legado de seleção múltipla de modelos (`qwen3:14b` e
  `qwen2.5:3b`).
- Detecção de perfil de RAM no `setup_llm.py`.
- Artefatos residuais da `v0.9.0` (scripts introdutórios, caminhos de
  empacotamento antigos e referências ao modo `--onefile`).

### Fixed

- Cadeia de certificados TLS (`certifi`) no ambiente congelado.
- Encerramento de processos e portabilidade do launcher desktop.
- Ajustes de auditoria e higiene de distribuição herdados da `v0.9.0`.

## [0.9.0] - 2026-11-21

Release de consolidação que serviu de linha de base para a `v1.0.0`.

### Added

- Workstation Streamlit com interface bilíngue `PT-BR` / `EN`, perfis
  analíticos e histórico de conversas.
- Camada multi-fonte com conectores públicos para SGB/GeoSGB, ANM/SIGMINE,
  ANA/HidroWeb, USGS, Macrostrat, OpenAlex e serviços geológicos
  internacionais.
- RAG documental com OCR leve em CPU, extração de tabelas e geração de
  pareceres técnicos em `.docx` e `.md`.
- Parser espacial de coordenadas decimais, GMS e folhas CIM.
- Empacotamento Windows em `--onedir` com pacote portátil, além da suíte
  offline de empacotamento.

### Changed

- Documentação de instalação, uso e distribuição consolidada.
- Higiene do repositório e dos artefatos de build revisada.

---

[Não lançado]: https://github.com/Prof-Tiago-Maia/NexusGeoIA/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases/tag/v1.0.0
[0.9.0]: https://github.com/Prof-Tiago-Maia/NexusGeoIA/releases/tag/v0.9.0
