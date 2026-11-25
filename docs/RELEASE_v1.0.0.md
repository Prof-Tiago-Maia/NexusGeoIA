# NexusGeo IA v1.0.0 — Release Notes

> **Data:** 24 de novembro de 2026 · **Status:** release estável
> **Repositório:** [github.com/Prof-Tiago-Maia/NexusGeoIA](https://github.com/Prof-Tiago-Maia/NexusGeoIA)

---

## Resumo executivo (PT-BR)

A **v1.0.0** é a primeira release estável do NexusGeo IA. Ela consolida a
plataforma de dados geocientíficos e IA local em torno de um único modelo
especializado, de uma persistência transacional em SQLite WAL e de uma camada
de governança epistêmica que torna explícita a diferença entre o que foi
observado nas fontes e o que foi inferido pelo modelo. A estação de trabalho
ganhou tema escuro fixo, modularização completa da interface e suporte
bilíngue PT-BR/EN. O pacote Windows passou a ser autoverificável: o build só
conclui depois que o executável compilado aprova um autodiagnóstico headless
dos 37 módulos internos, dos recursos de runtime, do banco WAL temporário, do
modelo oficial e dos imports de topo do `app.py`.

Em relação à **v0.9.0**, a mudança mais importante é a substituição do
catálogo genérico de três modelos pelo **`nexusgeo-qwen3-4b-v2-q4`**, um SLM
fine-tuned em GGUF `Q4_K_M` (~2,5 GB) para roteamento geocientífico, extração
estruturada e síntese RAG, com provisionamento automático e fallback técnico
único para `qwen3:4b`.

## Executive summary (EN)

**v1.0.0** is the first stable release of NexusGeo IA. It consolidates the
geoscience data and local-AI platform around a single specialized model,
transactional SQLite WAL persistence, and an explicit epistemic governance
layer that distinguishes observed evidence from model-inferred statements.
The workstation now ships with a fixed dark GIS theme, a fully modular UI, and
complete PT-BR/EN localization. The Windows package is self-verifying: the
build only succeeds after the compiled executable passes a headless self-test
covering all 37 internal modules, runtime resources, a temporary WAL database,
the official model, and the top-level imports of `app.py`.

Compared with **v0.9.0**, the key change is the replacement of the generic
three-model catalog with **`nexusgeo-qwen3-4b-v2-q4`**, a QLoRA-fine-tuned SLM
quantized to GGUF `Q4_K_M` (~2.5 GB) for geoscientific routing, structured
extraction, and RAG synthesis, with automatic provisioning and a single
technical fallback to `qwen3:4b`.

---

## Principais novidades da v1.0.0 em relação à v0.9.0

### 1. Modelo especializado único

- **`nexusgeo-qwen3-4b-v2-q4`**: fine-tuned por QLoRA sobre `Qwen3-4B`
  (4-bit NF4, dupla quantização, `r=8`, `alpha=16`, `seed=42`) e quantizado
  em **GGUF `Q4_K_M`** (~2,5 GB).
- **Provisionamento automático** em `setup_llm.py`: detecta o modelo já
  registrado no Ollama, registra via `ollama create` a partir do GGUF local
  (`models/` ou cache `D:\hf_cache`) ou baixa o GGUF oficial dos GitHub
  Releases.
- **Fallback técnico único** para `qwen3:4b` quando o GGUF oficial não está
  disponível por falha de rede ou de registro.
- **Benchmark determinístico** (`split=teste`, 50 casos, `seed=42`):
  **62,00%** de acurácia e **100,00%** de conformidade de esquema JSON, contra
  **58,00%** de `qwen3:4b`; `p50 = 2.681 ms`, `p95 = 2.994 ms` e **0,00%**
  de falha de parsing.

### 2. Persistência e concorrência com SQLite WAL

- Histórico, sessões e metadados migrados para **SQLite em modo WAL**.
- `journal_mode=WAL`, `foreign_keys=ON` e `busy_timeout=30000`.
- `services/db_service.py` centraliza schema, linhagem e cache espacial;
  `services/history_db.py` torna o histórico transacional.
- Banco principal em `data/nexusgeoia.db` (ou caminho definido por
  `NEXUSGEO_DB_PATH` / `ASSISTENTE_DATA_DIR`), com sidecars `-wal`/`-shm`.

### 3. Governança epistêmica e contexto

- `core/governance.py` valida o contrato de saída: `OBSERVED` exige
  `evidence_id`; sem vínculo válido, a afirmação é rebaixada para
  `INFERRED` e o veredito vira `HOLD`.
- O veredito final é `PASS`, `HOLD` ou `FAIL`, e o modelo nunca pode
  declarar `PASS` quando a validação encontrou problema.
- `core/context_builder.py` organiza fontes, trechos recuperados e
  rastreabilidade de evidências para prevenir alucinação em respostas
  geocientíficas.

### 4. Workstation GIS Dark Mode

- Tema escuro fixo em `.streamlit/config.toml`: fundo `#0E1117`,
  superfícies `#161B22` e cor primária `#00B4D8`.
- Interface modularizada em `ui/` (`tab_chat`, `tab_sondagem`,
  `tab_spatial`, `sidebar`, `governanca`, `progresso_consulta`,
  `workstation_layout`).
- Suporte bilíngue completo **PT-BR / EN** via `utils/i18n.py`, com troca
  de idioma na barra lateral e textos visíveis nos dois idiomas.

### 5. Extração segura, sondagem e fontes públicas

- `services/sondagem.py`: parser De–Até PT-BR/EN, normalização m/cm,
  validação de intervalos, detecção de sobreposição/lacuna e assinatura
  determinística.
- `services/exportacao_segura.py`: neutralização de fórmulas (`=`, `+`,
  `-`, `@`, tabulação, CR/LF) em CSV, XLSX e GeoJSON.
- `services/table_extractor.py` e `services/spatial_parser.py`: extração de
  tabelas, coordenadas decimais/GMS e folhas CIM.
- Conectores revisados em `adapters/` e
  `services/external_api_service.py` para **SGB/RIGeo**, **ANM/SIGMINE**,
  **USGS**, **Macrostrat**, **OpenAlex**, ANA/HidroWeb, SIAGAS/RIMAS,
  INDE/GEOSSIT e serviços geológicos internacionais.

### 6. Empacotamento Windows autoverificável

- Manifesto dinâmico `packaging/coleta_interna.py` cobre os **37 módulos
  internos** no PyInstaller (`packaging/assistente.spec`).
- Modo **`--self-test`** embutido no `launcher_desktop.py`.
- `packaging/smoke_exe.py` executa `NexusGeoIA.exe --self-test` em modo
  headless ao final do `build_portatil.ps1` e do `build_installer.ps1`.
- O autodiagnóstico valida recursos de runtime, banco SQLite WAL temporário,
  modelo oficial e imports de topo de `app.py`. Se qualquer verificação
  falhar, o `.zip` e o instalador **não** são gerados.

---

## Assets obrigatórios da Release

Anexe os **três arquivos** abaixo em **Assets** na Release `v1.0.0`:

| # | Arquivo | Descrição | Tamanho aprox. |
| --- | --- | --- | --- |
| 1 | **`NexusGeoIA_v1.0.0_Portatil.zip`** | Pacote portátil Windows sem instalação: `NexusGeoIA.exe` + `_internal/`, `iniciar.bat`, `setup_llm.py`, `prompts/`, `.streamlit/`, `README.md` e `PROTOCOLO_PESQUISA.md`. | ~210 MB (sem modelos) |
| 2 | **`NexusGeoIA_v1.0.0_Setup.exe`** | Instalador completo Windows (Inno Setup), com atalhos, desinstalador e o mesmo conteúdo `--onedir`. | — |
| 3 | **`nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`** | Pesos quantizados do modelo oficial. É baixado automaticamente pelo `setup_llm.py` na primeira execução do pacote portátil. | ~2,5 GB |

> **Por que o GGUF é obrigatório:** o pacote portátil é leve e **não** embute
> o modelo. Na primeira execução, o `setup_llm.py` procura o GGUF em
> `models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`; se não encontrar, baixa
> exatamente este asset da Release `v1.0.0` e o registra no Ollama via
> `ollama create`. Sem o asset, o fluxo cai no fallback `qwen3:4b`.

> **Nota de publicação:** o GitHub impõe limite de tamanho por asset. Se o
> GGUF exceder o limite da conta, publique-o em um espelho estável e ajuste
> `URL_GGUF_OFICIAL` em `setup_llm.py` para a mesma URL divulgada nesta
> Release.

---

## Requisitos mínimos

| Requisito | Mínimo | Recomendado |
| --- | --- | --- |
| Sistema operacional | Windows 10 ou 11 **64-bit** | Windows 11 64-bit atualizado |
| Memória RAM | **8 GB** | **16 GB** (modelo oficial ~2,5 GB) |
| Espaço em disco | **~10 GB livres** | 15 GB ou mais |
| Ollama | Instalado e em execução | Versão recente em [ollama.com/download](https://ollama.com/download) |
| Internet | Apenas no primeiro uso (download do GGUF) | — |
| Navegador | Edge, Chrome ou Firefox atualizado | — |
| Privilégios | Nenhum administrador necessário | — |

---

## Início rápido — Pacote portátil (Windows)

1. Baixe **`NexusGeoIA_v1.0.0_Portatil.zip`** em **Assets**.
2. Extraia **todo** o conteúdo para uma pasta curta e gravável, por exemplo
   `C:\NexusGeoIA`. Não execute o aplicativo de dentro do `.zip`.
3. Abra a pasta e execute **`iniciar.bat`** (recomendado) ou
   **`NexusGeoIA.exe`**.
4. Na primeira execução, o configurador do modelo local abre automaticamente:
   ele baixa o GGUF oficial (asset 3), registra o modelo no Ollama e grava o
   `config_local.json`. Em falha de rede, aplica o fallback `qwen3:4b`.
5. O navegador abre em `http://localhost:8501` (ou na próxima porta livre
   entre 8501 e 8510).

> **SmartScreen:** o executável ainda não é assinado digitalmente. Se aparecer
> o aviso "O Windows protegeu o computador", clique em **Mais informações** →
> **Executar assim mesmo**. O código-fonte é público e auditável.

## Início rápido — Instalador (Windows)

1. Baixe **`NexusGeoIA_v1.0.0_Setup.exe`** em **Assets**.
2. Execute o instalador. A instalação é **por usuário**, sem UAC
   (`PrivilegesRequired=lowest`).
3. Abra o NexusGeo IA pelo atalho do Menu Iniciar ou da Área de Trabalho.
4. Na primeira execução, o assistente de modelo baixa o GGUF oficial e o
   registra no Ollama, como no pacote portátil.
5. Os dados do usuário ficam em `%LOCALAPPDATA%\NexusGeoIA`.

> **Requisito comum:** o **Ollama** precisa estar instalado e em execução. Se
> ele não estiver disponível, o aplicativo orienta a instalação e mantém a
> interface funcional para consulta às fontes públicas.

---

## Primeira execução e modelo oficial

O fluxo do `setup_llm.py` é único e determinístico:

1. **Modelo já registrado** no Ollama → grava `config_local.json` e encerra.
2. **GGUF local** em `models/nexusgeo-qwen3-4b-v2-Q4_K_M.gguf` (ou no cache
   `D:\hf_cache`) → registra com `ollama create`.
3. **GGUF ausente** → baixa o asset oficial desta Release para `models/` e o
   registra.
4. **Falha de rede/registro** → `ollama pull qwen3:4b` como fallback técnico
   único.

Para reabrir o configurador a qualquer momento:

```powershell
NexusGeoIA.exe --setup-modelo
```

Para conferir o modelo registrado:

```powershell
ollama list
```

O nome esperado é **`nexusgeo-qwen3-4b-v2-q4`**.

---

## Validação da release

- O pacote compilado passou pela **validação manual** dos fluxos de instalação,
  primeira execução, download/registro do modelo e abertura da interface.
- O build é **autoverificável**: `packaging/smoke_exe.py` executa
  `NexusGeoIA.exe --self-test` antes de gerar o `.zip` e o instalador.
- O self-test cobre os **37 módulos internos**, os recursos de runtime
  (`.streamlit/`, `prompts/`, `ui/`, `finetuning/Modelfile.*`), um banco
  SQLite WAL temporário, a resolução do modelo oficial e os imports de topo de
  `app.py`, sem abrir navegador, servidor ou janela.
- O relatório da última execução fica em `build/self_test.json`.

---

## English quick start

1. Download **`NexusGeoIA_v1.0.0_Portatil.zip`** (portable) or
   **`NexusGeoIA_v1.0.0_Setup.exe`** (installer) from **Assets**.
2. Portable: extract the full archive to a short writable path such as
   `C:\NexusGeoIA` and run `iniciar.bat`. Installer: run the setup and open
   the Start Menu shortcut.
3. On first launch, `setup_llm.py` downloads
   **`nexusgeo-qwen3-4b-v2-Q4_K_M.gguf`** from this Release, registers
   `nexusgeo-qwen3-4b-v2-q4` in Ollama, and writes `config_local.json`. If
   the download fails, the app falls back to `qwen3:4b`.
4. The browser opens at `http://localhost:8501` (next free port up to 8510).
5. Requirements: **Windows 10/11 64-bit**, **Ollama installed**, **8 GB+ RAM**
   (16 GB recommended), and **~10 GB free disk**.

For the full documentation, see [README.md](../README.md) and
[PROTOCOLO_PESQUISA.md](../PROTOCOLO_PESQUISA.md).

---

## Documentação e suporte

- [README.md](../README.md) — instalação, uso, arquitetura e solução de
  problemas.
- [PROTOCOLO_PESQUISA.md](../PROTOCOLO_PESQUISA.md) — protocolo de pesquisa,
  citação e rastreabilidade.
- [CHANGELOG.md](../CHANGELOG.md) — histórico completo de versões.
- [AGENTS.md](../AGENTS.md) — regras de engenharia, arquitetura e
  empacotamento.
- **Issues:** [github.com/Prof-Tiago-Maia/NexusGeoIA/issues](https://github.com/Prof-Tiago-Maia/NexusGeoIA/issues)

---

**NexusGeo IA v1.0.0** · Plataforma de dados geocientíficos e IA local ·
Manaus, Amazonas, Brasil.
