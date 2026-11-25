"""Internacionalização (i18n) da interface do NexusGeo IA.

Este módulo concentra **todo** o texto visível da interface em dois
idiomas — Português do Brasil (``"pt"``, padrão) e Inglês (``"en"``) — e
serve de fonte única para os rótulos da barra lateral, do cabeçalho, do
guia rápido, dos controles de chat e das mensagens de erro/aviso.

O idioma ativo fica em ``st.session_state["idioma"]`` e é trocado pelos
botões de bandeira no topo da barra lateral (``app.py``). A função
:func:`t` lê essa chave e devolve o texto correspondente, sempre com
fallback seguro: idioma desconhecido ou chave ausente caem em
Português do Brasil, e uma chave inexistente devolve a própria chave em
vez de levantar exceção (a interface nunca quebra por falta de
tradução).

Além dos textos de interface, o módulo guarda:

- :data:`PERFIS_EN` — nomes, rótulos curtos e descrições em inglês dos
  perfis analíticos de ``core.analytical_profiles`` (as chaves
  canônicas continuam em português, porque são gravadas no prompt);
- :data:`REGIOES_EN` — rótulos em inglês das regiões do seletor
  internacional, mantendo como *valor* a opção canônica em português
  que os conectores de ``services.external_api_service`` esperam;
- :data:`INSTRUCAO_IDIOMA_RESPOSTA` — a instrução explícita injetada no
  system prompt para orientar o idioma da resposta técnica do LLM
  (usada por ``core.assistant.responder``).

Nenhuma dependência externa é necessária: o módulo reaproveita o
``streamlit`` **somente quando a interface já o importou**, para ler o
estado da sessão, com proteção para quando é importado fora de um script
Streamlit (testes unitários, CLI). O import é deliberadamente tardio:
``services.document_parser`` importa este módulo para traduzir mensagens
de limite e não pode carregar o runtime da interface durante o parsing.
"""

import sys

from config import APP_DISPLAY_NAME, APP_NAME

# Idioma padrão e lista de idiomas realmente suportados.
IDIOMA_PADRAO = "pt"
IDIOMAS_SUPORTADOS = ("pt", "en")

# Rótulo curto de cada idioma, exibido nos botões de bandeira.
ROTULOS_IDIOMA = {
    "pt": "🇧🇷 PT-BR",
    "en": "🇬🇧 EN",
}

# Nome por extenso de cada idioma, usado no ``help`` dos botões.
NOMES_IDIOMA = {
    "pt": "Português (Brasil)",
    "en": "English",
}


# ---------------------------------------------------------------------------
# Textos da interface
# ---------------------------------------------------------------------------

TEXTOS_I18N = {
    "pt": {
        # -- Cabeçalho e status -------------------------------------
        "titulo": APP_NAME,
        "subtitulo": (
            "Plataforma Integrada de Dados Geocientíficos e IA Local"
        ),
        "ollama_online": "Ollama online · {host}",
        "ollama_offline": "Ollama offline · {host}",
        "badge_base_local": "📄 Base local",
        "badge_base_local_off": "Base local desligada",
        "ajuda_base_local": "Os arquivos de data/docs entram nas respostas.",
        "ajuda_base_local_off": (
            "A base documental local foi desligada na seção "
            "'Fontes de Dados Ativas'."
        ),
        "badge_rigeo_off": "RIGeo desligado",
        "ajuda_rigeo": "Acervo geocientífico do SGB (RIGeo) ativo.",
        "ajuda_rigeo_off": (
            "O acervo SGB/RIGeo foi desligado na seção "
            "'Fontes de Dados Ativas'."
        ),
        "ajuda_web_tecnico": (
            "Pesquisa na Web ligada na barra lateral. Somente domínios "
            "técnicos e institucionais."
        ),
        "ajuda_web_aberta": (
            "Pesquisa na Web ligada na barra lateral. Web aberta, sem "
            "restrição de domínio."
        ),
        "ajuda_ana": "Inventário de estações da ANA/HidroWeb ativo.",
        "ajuda_siagas": (
            "Poços tubulares do SIAGAS/RIMAS ligados na seção "
            "'Fontes de Dados Ativas'. O município e a UF saem da "
            "pergunta; com a ANA ligada, a resposta cruza águas "
            "superficiais e subterrâneas."
        ),
        "ajuda_geosgb": (
            "Cadastro geológico de ocorrências e jazidas do SGB (GeoSGB) "
            "ligado na seção 'Fontes de Dados Ativas'. A substância e a "
            "UF são extraídas da pergunta."
        ),
        "ajuda_anm": (
            "Processos minerários da ANM (SIGMINE) ligados na seção "
            "'Fontes de Dados Ativas'. A substância, o titular e a UF "
            "são extraídos da pergunta; a fase é a publicada pela ANM."
        ),
        "ajuda_geossit": (
            "Inventário de geossítios do INDE/GEOSSIT ligado na seção "
            "'Fontes de Dados Ativas': interesse, relevância e "
            "coordenadas."
        ),
        "ajuda_macrostrat": (
            "Unidades litoestratigráficas da Macrostrat ligadas na seção "
            "'Fontes de Dados Ativas': idade, litologia e ambiente "
            "deposicional."
        ),
        "ajuda_openalex": (
            "Base internacional OpenAlex ligada na barra lateral."
        ),
        "badge_intl_geo_regioes": "🌐 Geo Internacional · {regioes}",
        "ajuda_intl_geo_regioes": (
            "Serviços geológicos internacionais ativos, restritos a: "
            "{regioes}"
        ),
        "ajuda_intl_geo_todas": (
            "Todos os serviços geológicos internacionais abertos estão "
            "ativos (OneGeology, USGS, NRCan, EGDI, GA/GSQ, GSJ, "
            "GeoNet, CGS/DE Africa, NGD e GSI/Bhukosh)."
        ),
        "ajuda_perfil": (
            "Modo de análise: {perfil}. {descricao}"
        ),
        "badge_prompt_editado": "✍️ Prompt editado",
        "ajuda_prompt_editado": (
            "O system prompt ativo foi alterado em relação ao texto do "
            "modo de análise selecionado."
        ),
        # -- Barra lateral: base de documentos ----------------------
        "secao_documentos": "📄 Base de documentos (Upload)",
        "texto_documentos": (
            "Envie arquivos .txt, .md ou .pdf. Cada arquivo é convertido "
            "em Markdown limpo antes da indexação; páginas escaneadas "
            "passam por OCR local."
        ),
        "ocr_indisponivel": (
            "OCR local indisponível: PDFs escaneados não serão lidos. "
            "Rode pip install -r requirements.txt para habilitar."
        ),
        "rotulo_upload": "Adicionar documentos",
        "botao_salvar_documentos": "Salvar documentos",
        "status_convertendo": "Convertendo documentos para Markdown…",
        "progresso_convertidos": (
            "{feitos}/{total} arquivo(s) convertido(s)"
        ),
        "progresso_processados": (
            "{total}/{total} arquivo(s) processado(s)"
        ),
        "status_convertidos_resumo": (
            "{salvos} de {total} documento(s) convertido(s) em Markdown"
        ),
        "sucesso_indexados": (
            "{n} documento(s) convertido(s) em Markdown e indexado(s)."
        ),
        "ocr_aplicado": (
            "OCR local aplicado em {ocr} de {total} página(s)."
        ),
        "sem_ocr": "Nenhuma das {total} página(s) precisou de OCR.",
        "cache_reaproveitado": (
            "{n} documento(s) reaproveitado(s) do cache em "
            "data/cache_md/."
        ),
        "detalhe_paginas": "{paginas} página(s) convertida(s)",
        "detalhe_ocr": " · {paginas} via OCR",
        "detalhe_cache": " · cache reaproveitado",
        "limite_arquivo_documento": (
            "O arquivo excede o limite de 100 MB para indexação."
        ),
        "limite_paginas_pdf": (
            "O PDF excede o limite de 500 páginas para indexação."
        ),
        "titulo_arquivo_nao_indexado": "Arquivo não indexado",
        "titulo_arquivo_sem_texto": "Arquivo sem texto selecionável",
        "documentos_contagem": "{n} arquivo(s) em data/docs:",
        "documentos_excedente": "+ {n} arquivo(s) não exibido(s).",
        "botao_limpar_base": "🗑️ Limpar Base de Documentos",
        "ajuda_limpar_base": (
            "Remove todos os arquivos de data/docs e os Markdown em "
            "cache (data/cache_md/). A base documental volta a ficar "
            "vazia."
        ),
        "documentos_vazio": "Nenhum documento carregado em data/docs.",
        "selo_indexado_ocr": "Indexado (OCR)",
        "selo_indexado": "Indexado",
        "selo_sem_texto": "Sem texto",
        "ajuda_doc_ocr": (
            "Markdown gerado com OCR em {ocr} de {total} página(s)."
        ),
        "ajuda_doc_nativo": "Markdown gerado com texto nativo.",
        "ajuda_doc_sem_texto": (
            "Não foi possível ler o texto deste arquivo."
        ),
        "ajuda_excluir_documento": (
            'Excluir "{nome}" de data/docs e o cache em data/cache_md/.'
        ),
        "aviso_limpar_falhas": (
            "Não foi possível excluir: {falhas}."
        ),
        "aviso_limpeza_sucesso": (
            "{n} documento(s) excluído(s) de data/docs e do cache em "
            "data/cache_md/."
        ),
        "aviso_documento_excluido": (
            "{nome} excluído de data/docs e do cache em data/cache_md/."
        ),
        "aviso_excluir_documento_erro": (
            "Não foi possível excluir {nome}: {erro}"
        ),
        # -- Barra lateral: histórico -------------------------------
        "secao_historico": "💬 Histórico de Conversas",
        "historico_vazio": (
            "Nenhuma conversa salva ainda. As consultas aparecem aqui "
            "automaticamente."
        ),
        "historico_contagem": (
            "{n} conversa(s) salva(s) · mais recente primeiro"
        ),
        "historico_aberta": "Conversa aberta no momento.",
        "historico_abrir": (
            "Abrir esta conversa · última atualização: {data}"
        ),
        "historico_excluir": 'Excluir a conversa "{titulo}".',
        "historico_nao_salva": (
            "A conversa aberta ainda não foi concluída (não salva)."
        ),
        "botao_apagar_tudo": "🗑️ Apagar Todo o Histórico",
        "ajuda_apagar_tudo": (
            "Apaga todas as conversas salvas em data/historico. Os "
            "documentos de data/docs são preservados."
        ),
        "botao_apagar_confirmado": (
            "🗑️ Sim, apagar todo o histórico"
        ),
        "ajuda_apagar_confirmado": (
            "Confirma a exclusão definitiva de todas as conversas."
        ),
        "botao_cancelar": "Cancelar",
        "ajuda_cancelar": "Mantém o histórico como está.",
        "confirmar_apagar_titulo": (
            "⚠️ Confirmar exclusão de todas as conversas"
        ),
        "confirmar_apagar_texto": (
            "Todas as conversas salvas serão removidas de "
            "data/historico. Os documentos indexados em data/docs não "
            "são afetados."
        ),
        "aviso_abrir_erro": (
            "Não foi possível abrir esta conversa: o arquivo não existe "
            "mais ou está corrompido."
        ),
        "aviso_conversa_excluida": "Conversa excluída do histórico.",
        "aviso_historico_apagado": (
            "Histórico apagado: {n} conversa(s) removida(s). Os "
            "documentos indexados em data/docs foram preservados."
        ),
        "aviso_sem_conversas": "Não havia conversas salvas para apagar.",
        "nova_conversa": "Nova conversa",
        # -- Barra lateral: fontes ----------------------------------
        "secao_fontes": "🗂️ Fontes de Dados Ativas",
        "texto_fontes": (
            "Cada fonte ligada aqui entra em todas as perguntas. "
            "Desligue o que não quiser consultar; nada é ignorado nem "
            "ligado sem o seu consentimento."
        ),
        "toggle_local_docs": "📄 Base Documental Local (PDF/MD/TXT)",
        "ajuda_local_docs": (
            "Consulta os arquivos indexados em data/docs, convertidos "
            "para Markdown. Desligado, a resposta usa apenas as demais "
            "fontes ligadas."
        ),
        "grupo_geologia_geofisica": "Geologia & Geofísica",
        "grupo_recursos_minerais_anm": "Recursos Minerais & ANM",
        "grupo_hidrogeologia_hidricos": "Hidrogeologia & Hídricos",
        "grupo_literatura_apoio": "Literatura & Apoio",
        "web_tecnicos": (
            "Priorizar domínios técnicos (.gov / SciELO / USGS)"
        ),
        "ajuda_web_tecnicos": (
            "Restringe a busca a domínios técnicos e institucionais "
            "(site:gov.br OR site:sgb.gov.br OR site:anm.gov.br OR "
            "site:scielo.br OR site:usgs.gov). Deixe desmarcado para "
            "pesquisar a Web aberta inteira."
        ),
        "dica_siagas": (
            "Município e UF saem da pergunta (ex.: \"poços tubulares em "
            "Apui, Amazonas\"). Sem eles, a lista é uma amostra da UF."
        ),
        "dica_geosgb": (
            "Substância e UF saem da pergunta (ex.: \"ocorrências de "
            "ouro no Pará\"). Sem substância nem UF, o conector avisa em "
            "vez de disparar uma consulta nacional."
        ),
        "dica_anm": (
            "Aceita a substância (ex.: \"terras raras no Amazonas\"), o "
            "titular (ex.: \"Brazilian Critical Minerals\") ou a UF. A "
            "fase vem do SIGMINE, como publicada pela ANM."
        ),
        "dica_macrostrat": (
            "Usa as coordenadas da pergunta (ou de um documento local) "
            "quando existirem; fora isso, busca a unidade mencionada."
        ),
        "dica_geossit": (
            "Aceita o nome do geossítio ou um tema (\"estromatólito\", "
            "\"cachoeira\") e a UF. Sem filtro, devolve o inventário do "
            "recorte."
        ),
        "onde_buscar": "Onde buscar?",
        "placeholder_regioes": "Selecione onde buscar...",
        "ajuda_regioes": (
            "Escolha uma ou mais regiões/serviços. 'Todas as Regiões' "
            "consulta os dez conectores em paralelo; as demais opções "
            "restringem a busca exatamente aos serviços escolhidos."
        ),
        # -- Rótulos e ajudas dos conectores ------------------------
        "fonte_rigeo": "🏛️ SGB / RIGeo (Acervo Geocientífico)",
        "ajuda_fonte_rigeo": (
            "Consulta o acervo do Serviço Geológico do Brasil no RIGeo, "
            "com fallback no GeoBusca. É a fonte geocientífica "
            "principal."
        ),
        "fonte_ana": "💧 ANA / HidroWeb (Estações Hidrológicas)",
        "ajuda_fonte_ana": (
            "Consulta o inventário público de estações da ANA "
            "(HidroWeb/SNIRH) pelo município, rio, sub-bacia ou UF "
            "citados na pergunta. Ajuda em estudos hidrológicos, "
            "hidrogeológicos e de licenciamento ambiental."
        ),
        "fonte_web": "🌐 Pesquisar na Web (Internet aberta)",
        "ajuda_fonte_web": (
            "Acrescenta a pesquisa na internet (DuckDuckGo, sem chave "
            "de API) às demais fontes. Funciona em qualquer opção de "
            "fonte, inclusive 'Conhecimento geral'. Desligado, o "
            "assistente continua 100% local e funciona sem internet."
        ),
        "fonte_openalex": (
            "📚 OpenAlex (artigos científicos internacionais)"
        ),
        "ajuda_fonte_openalex": (
            "Consulta o OpenAlex filtrando Geologia, Geoquímica e "
            "Engenharia de Minas e ordenando por relevância. A pergunta "
            "é traduzida para o inglês pela camada bilíngue PT↔EN; "
            "título, autores, ano, resumo e DOI aparecem no status e "
            "nos cartões de fontes."
        ),
        "fonte_intl_geo": "🌐 Serviços Geológicos Internacionais",
        "ajuda_fonte_intl_geo": (
            "Liga o grupo unificado de serviços geológicos públicos, "
            "sem chave de API: OneGeology, USGS ScienceBase, "
            "NRCan/GSC (Canadá), EGDI (UE), Geoscience Australia/GSQ, "
            "GSJ/AIST (Japão), GeoNet/GNS (Nova Zelândia), "
            "CGS/Digital Earth Africa, NGD (Arábia Saudita) e "
            "GSI/Bhukosh WFS (Índia). Ao ligar, escolha exatamente em "
            "quais regiões/serviços buscar."
        ),
        "fonte_geosgb": "🗺️ SGB / Ocorrências Minerais (GeoSGB)",
        "ajuda_fonte_geosgb": (
            "Consulta o cadastro geológico de ocorrências e jazidas do "
            "Serviço Geológico do Brasil (GeoSGB WFS) e devolve as "
            "ocorrências minerais do recorte. A substância mineral "
            "(ouro, cobre, terras raras, nióbio...) e a UF são "
            "extraídas da pergunta. Cada ocorrência traz alvo, "
            "substância, status, município/UF, folha e coordenadas, sem "
            "chave de API. É uma base geológica, distinta dos processos "
            "minerários da ANM."
        ),
        "fonte_anm": "⛏️ ANM / Processos Minerários (SIGMINE)",
        "ajuda_fonte_anm": (
            "Consulta os processos, requerimentos e poligonais "
            "minerárias ativas da Agência Nacional de Mineração no "
            "SIGMINE (ArcGIS REST e WFS públicos). A substância (ouro, "
            "terras raras, estanho...), o titular ou a UF saem da "
            "pergunta. Cada processo traz número, ano, fase atual, "
            "titular, substância, área em hectares e UF, sem chave de "
            "API. É o cadastro regulatório, distinto das ocorrências "
            "geológicas do SGB/GeoSGB."
        ),
        "fonte_macrostrat": "🧱 Macrostrat (Estratigrafia & Idades)",
        "ajuda_fonte_macrostrat": (
            "Consulta a API REST pública da Macrostrat e devolve "
            "unidades litoestratigráficas com idade geológica (em Ma), "
            "litologia principal e ambiente deposicional. Usa as "
            "coordenadas citadas na pergunta (ou em um documento local) "
            "e, sem elas, o nome da unidade mencionada. Sem chave de "
            "API."
        ),
        "fonte_siagas": (
            "🚰 SIAGAS / RIMAS (Poços & Águas Subterrâneas)"
        ),
        "ajuda_fonte_siagas": (
            "Consulta o WFS público do Serviço Geológico do Brasil e "
            "devolve os poços tubulares do SIAGAS/RIMAS: código do "
            "ponto, município/UF, profundidade, níveis estático e "
            "dinâmico, vazão, aquífero captado e coordenadas. O "
            "município e a UF saem da pergunta, sem chave de API. Com a "
            "ANA ligada, a resposta cruza águas subterrâneas e "
            "superficiais."
        ),
        "fonte_geossit": "🏞️ INDE / GEOSSIT (Patrimônio Geológico)",
        "ajuda_fonte_geossit": (
            "Consulta as camadas públicas do GEOSSIT/INDE (SGB) e "
            "devolve geossítios e sítios da geodiversidade: nome, "
            "interesse principal (estratigráfico, paleontológico, "
            "geomorfológico, mineralógico, tectônico...), município/UF, "
            "relevância (nacional/internacional) e coordenadas. Sem "
            "chave de API."
        ),
        # -- Barra lateral: perfil analítico ------------------------
        "secao_perfil": "🧠 Perfil Analítico & System Prompt",
        "modo_analise": "Modo de análise",
        "ajuda_modo_analise": (
            "Cada modo acrescenta instruções geocientíficas ao texto "
            "base do system prompt. Trocar de modo substitui o bloco do "
            "perfil anterior e preserva o restante do texto."
        ),
        "perfil_personalizado_texto": (
            "✏️ No modo personalizado a instrução é exatamente o texto "
            "escrito na caixa de edição: nenhum bloco automático é "
            "acrescentado, e o editor já abre focado abaixo."
        ),
        "editar_prompt": "✏️ Editar system prompt",
        "ajuda_editar_prompt": (
            "Abre a edição do texto enviado ao modelo em todas as "
            "consultas."
        ),
        "texto_edicao": (
            "As alterações valem para as próximas perguntas, mesmo "
            "antes de serem salvas no arquivo."
        ),
        "rotulo_prompt_ativo": (
            "System prompt ativo (prompts/system_base.txt)"
        ),
        "ajuda_prompt_ativo": (
            "Texto base enviado ao modelo, já com as instruções do "
            "modo de análise selecionado. As instruções das fontes são "
            "acrescentadas automaticamente pelo sistema."
        ),
        "botao_salvar_padrao": "Salvar como padrão",
        "botao_restaurar": "Restaurar original",
        "expander_ver_prompt": "👁️ Ver prompt ativo",
        "texto_ver_prompt": (
            "{n} caracteres. As instruções das fontes são acrescentadas "
            "a este texto a cada consulta."
        ),
        "aviso_prompt_salvo": (
            "System prompt salvo em prompts/system_base.txt."
        ),
        "aviso_prompt_erro": (
            "Não foi possível salvar o system prompt: {erro}"
        ),
        "aviso_prompt_restaurado": (
            "Conteúdo de prompts/system_base.txt restaurado."
        ),
        # -- Barra lateral: configurações avançadas -----------------
        "config_avancadas": "⚙️ Configurações Avançadas",
        "modelo_ollama": "Modelo Ollama",
        "ajuda_modelo_ollama": (
            "Modelos instalados no Ollama local. Modelos menores "
            "respondem mais rápido; os maiores são mais detalhados."
        ),
        "limite_rigeo": "Limite de artigos do RIGeo",
        "ajuda_limite_rigeo": (
            "Quantidade máxima de estudos do SGB retornados pelo RIGeo."
        ),
        "comunidade_rigeo": "Comunidade do SGB",
        "ajuda_comunidade_rigeo": (
            "Restringe a busca do RIGeo a uma comunidade do acervo."
        ),
        "refinar_termos": "Refinar termos de busca com o Ollama",
        "ajuda_refinar_termos": (
            "Antes de consultar o RIGeo, pede ao modelo uma lista curta "
            "de termos de busca (2 a 4 palavras). Acelera muito a "
            "resposta, mas custa uma ida extra ao Ollama; se o modelo "
            "falhar, a remoção de stopwords assume. O termo usado "
            "aparece no status de cada consulta."
        ),
        "rodape_modelo": (
            f"{APP_DISPLAY_NAME} · Modelo ativo: {{modelo}} · "
            "Documentos indexados: {documentos}"
        ),
        "encerrar_servidor": "⏻ Encerrar servidor / Sair",
        "ajuda_encerrar_servidor": (
            "Fecha o servidor local do aplicativo e libera a porta. O "
            "histórico já salvo é preservado."
        ),
        "aviso_encerrando_servidor": (
            "Encerrando o servidor... você já pode fechar esta aba."
        ),
        "spinner_ollama": "Iniciando o serviço do Ollama...",
        # -- Chat ---------------------------------------------------
        "novo_chat": "➕ Novo Chat",
        "ajuda_novo_chat": (
            "Salva a conversa atual no histórico e abre uma conversa em "
            "branco. Os documentos indexados continuam ativos."
        ),
        "chat_placeholder": "Digite sua pergunta...",
        "status_analisando": "Analisando pergunta e buscando fontes",
        "status_fontes": " ({fontes})",
        "status_concluida": "Consulta concluída · {intencao}",
        "status_erro": "Não foi possível concluir a consulta.",
        "erro_consulta": (
            "Não foi possível concluir a consulta. Verifique o serviço "
            "selecionado."
        ),
        "fonte_legenda": "Fonte: {fonte}",
        "roteamento_legenda": " · Roteamento: {intencao}",
        # -- Progresso por etapa e cancelamento (Fase D3a) ----------
        "progresso_titulo": "Progresso da consulta",
        "progresso_etapa_atual": "Etapa atual: {etapa}",
        "progresso_texto_parcial": "Prévia da resposta em streaming",
        "progresso_aguardando": "Aguardando o início da consulta...",
        "botao_cancelar_consulta": "Cancelar consulta",
        "ajuda_cancelar_consulta": (
            "Interrompe a consulta em andamento. A resposta parcial e os "
            "arquivos temporários são descartados e nenhuma mensagem é "
            "salva no histórico."
        ),
        "consulta_em_andamento": (
            "Já existe uma consulta em andamento. Cancele-a ou aguarde a "
            "conclusão antes de enviar outra pergunta."
        ),
        "cancelamento_solicitado": (
            "Consulta cancelada. Nenhuma resposta foi salva no histórico "
            "e os arquivos temporários da conversão foram removidos."
        ),
        "status_cancelado": "Consulta cancelada.",
        "progresso_etapa_preparando": "Preparando a consulta",
        "progresso_etapa_roteamento": "Classificando a intenção da pergunta",
        "progresso_etapa_sgb": "Consultando o RIGeo / SGB",
        "progresso_etapa_documentos": "Buscando na base documental local",
        "progresso_etapa_documentos_consultas": (
            "Gerando as consultas bilíngues dos documentos"
        ),
        "progresso_etapa_documentos_indice": "Indexando os documentos locais",
        "progresso_etapa_documento_pagina": "Convertendo as páginas do documento",
        "progresso_etapa_documento_ocr": "Aplicando OCR nas páginas digitalizadas",
        "progresso_etapa_ana": "Consultando a ANA / HidroWeb",
        "progresso_etapa_web": "Pesquisando na Web aberta",
        "progresso_etapa_openalex": "Consultando o OpenAlex",
        "progresso_etapa_usgs": "Consultando o USGS ScienceBase",
        "progresso_etapa_intl_geo": (
            "Consultando os serviços geológicos internacionais"
        ),
        "progresso_etapa_geosgb": "Consultando o GeoSGB / SGB",
        "progresso_etapa_anm": "Consultando a ANM / SIGMINE",
        "progresso_etapa_macrostrat": "Consultando a Macrostrat",
        "progresso_etapa_siagas": "Consultando o SIAGAS / RIMAS",
        "progresso_etapa_geossit": "Consultando o INDE / GEOSSIT",
        "progresso_etapa_llm": "Gerando a resposta com o Ollama",
        "progresso_etapa_concluida": "Consulta concluída",
        "progresso_etapa_cancelando": "Cancelando a consulta...",
        "progresso_etapa_cancelada": "Consulta cancelada",
        "progresso_etapa_erro": "Falha ao concluir a consulta",
        # -- Detalhes do status da consulta -------------------------
        "status_intencao": "Intenção: {intencao}",
        "status_intencao_padrao": "definida na barra lateral",
        "status_decisao": "Decisão tomada por: {origem}",
        "status_busca_bilingue": "**Busca local bilíngue (PT-BR ↔ EN)**",
        "status_idioma_detectado": (
            "Idioma detectado na pergunta: {idioma}"
        ),
        "status_idioma_nao_identificado": (
            "Idioma da pergunta não identificado"
        ),
        "status_origem_llm": "termos pelo Ollama",
        "status_origem_fallback": "fallback determinístico (glossário)",
        "status_origem_identica": "pergunta original",
        "status_query": "- Query {lingua}: `{texto}`",
        "status_amostragem": (
            "Pergunta de visão geral ou busca fraca: foi acionada a "
            "amostragem representativa (início, seções centrais e "
            "conclusões) para cobrir os arquivos por inteiro."
        ),
        "status_trechos": (
            "{recuperados} trecho(s) por palavra-chave · {amostrados} "
            "por amostragem representativa."
        ),
        "status_termo_rigeo_vazio": (
            "Termo pesquisado no RIGeo: a pergunta não tem termos "
            "geocientíficos aproveitáveis; a busca usou a pergunta "
            "original."
        ),
        "status_termos_ollama": " · termos definidos pelo Ollama",
        "status_plano_rigeo": "Plano de busca do RIGeo: {plano}",
        "status_artigos_rigeo": (
            "**Artigos recuperados do RIGeo ({n})**"
        ),
        "status_titulo_nao_informado": "Título não informado",
        "status_trechos_documentos": (
            "{n} trecho(s) de documento local aproveitado(s) na resposta."
        ),
        "status_estacoes_recuperadas": (
            "**Estações recuperadas de {fonte} ({n})**"
        ),
        "status_ana_vazio": (
            "{fonte}: nenhuma estação encontrada para {recorte}."
        ),
        "status_anm_recuperados": (
            "Processos minerários recuperados da ANM / SIGMINE"
        ),
        "status_macrostrat_recuperadas": (
            "Unidades litoestratigráficas recuperadas da Macrostrat"
        ),
        "status_siagas_recuperados": "Poços recuperados do SIAGAS / RIMAS",
        "status_geossit_recuperados": (
            "Geossítios recuperados do INDE / GEOSSIT"
        ),
        "status_paginas_web": (
            "**Páginas recuperadas da Web aberta ({n})**"
        ),
        "status_pagina_sem_titulo": "Página sem título",
        "status_termo_ingles": (
            'Termo em inglês enviado ao {base}: "{termo}"'
        ),
        "status_publicacoes": (
            "**Publicações recuperadas de {base} ({n})**"
        ),
        "status_registro_sem_titulo": "Registro sem título",
        "status_intl_recuperados": (
            "**Serviços geológicos internacionais recuperados ({n})**"
        ),
        "status_vazio_registro": "nenhum registro encontrado.",
        # -- Guia rápido --------------------------------------------
        "guia_titulo": f"#### 🧭 Como usar o {APP_NAME}",
        "guia_intro": (
            "O assistente cruza os documentos locais que você enviar com "
            "bases públicas brasileiras e internacionais, do acervo "
            "RIGeo/SGB aos catálogos hidrogeológicos, minerários e "
            "científicos."
        ),
        "guia_passo_1_titulo": (
            "1. 📄 Adicione Documentos Locais (Opcional)"
        ),
        "guia_passo_1_texto": (
            "Na barra lateral, envie relatórios, boletins de sondagem ou "
            "artigos em PDF, MD ou TXT. O sistema indexa o texto, "
            "executa OCR quando necessário e libera a extração de "
            "tabelas."
        ),
        "guia_passo_2_titulo": "2. 🗂️ Ligue as Bases de Dados Desejadas",
        "guia_passo_2_texto": (
            "Ative os toggles das bases brasileiras que deseja cruzar — "
            "RIGeo, ANA / HidroWeb, SIAGAS / RIMAS, SGB / GeoSGB, "
            "ANM / SIGMINE e INDE / GEOSSIT — e das internacionais: "
            "Macrostrat, OpenAlex e Serviços Geológicos Internacionais. "
            "Neste último, escolha exatamente em quais serviços/países "
            "buscar: OneGeology, USGS/EUA, Canadá, Europa, Austrália, "
            "Japão, Nova Zelândia, África, Arábia Saudita ou Índia."
        ),
        "guia_passo_3_titulo": "3. 🧠 Escolha o Perfil Analítico",
        "guia_passo_3_texto": (
            "Selecione a lente técnica de interpretação (ex.: Geologia "
            "Regional, Exploração Mineral & Geoquímica, Hidrogeologia, "
            "Geotecnia) ou edite o System Prompt conforme o objetivo do "
            "estudo."
        ),
        "guia_passo_4_titulo": "4. 📊 Explore Resultados, Mapas e Tabelas",
        "guia_passo_4_texto": (
            "Faça sua pergunta no campo abaixo. Sempre que houver "
            "coordenadas, folhas CIM ou dados tabulares, o assistente "
            "gera automaticamente o mapa espacial interativo e permite "
            "exportar planilhas (.csv / .xlsx)."
        ),
        "guia_combinacao_titulo": (
            "🧩 Dicas de Combinação de Fontes por Tipo de Consulta"
        ),
        "guia_combinacao_intro": (
            "Combinações recomendadas para cada objetivo de investigação:"
        ),
        "guia_combinacao_1_titulo": (
            "🌍 Revisões Globais, Metalogênese e Literatura Internacional"
        ),
        "guia_combinacao_1_texto": (
            "Ative juntos Serviços Geológicos Internacionais + OpenAlex "
            "(artigos científicos internacionais) + Macrostrat para "
            "cruzar ocorrências de campo com literatura científica "
            "revisada por pares."
        ),
        "guia_combinacao_2_titulo": (
            "🇧🇷 Dados Oficiais do Brasil (Mapas, Poços, Mineração e "
            "Hidrologia)"
        ),
        "guia_combinacao_2_texto": (
            "Combine SGB / RIGeo, GeoSGB (Ocorrências Minerais), "
            "ANM / SIGMINE, ANA / HidroWeb e SIAGAS."
        ),
        "guia_combinacao_3_titulo": (
            "🌋 Sismicidade e Vulcanismo Ativo"
        ),
        "guia_combinacao_3_texto": (
            "Selecione GeoNet / GNS (Nova Zelândia), GSJ / AIST (Japão) "
            "ou USGS no seletor de regiões internacionais."
        ),
        "guia_combinacao_4_titulo": (
            "📄 Documentos Próprios (Relatórios, Teses e Laudos)"
        ),
        "guia_combinacao_4_texto": (
            "Ative Base Documental Local (PDF/MD/TXT) para cruzar seus "
            "arquivos com as bases públicas."
        ),
        "guia_dica": (
            "Dica: cite município/UF, substância mineral, unidade "
            "geológica ou código de folha CIM — ex.: 'terras raras em "
            "Apuí/AM' ou 'poços SIAGAS em Manaus/AM' — para ativar os "
            "filtros espaciais automaticamente."
        ),
        # -- Expander de fontes -------------------------------------
        "fontes_expander": "📚 Fontes e Metadados Consultados",
        "roteamento_caption": "Roteamento: {intencao}",
        "termo_rigeo": 'Termo pesquisado no RIGeo: "{termo}"',
        "termo_web": 'Termo pesquisado na Web: "{termo}"',
        "termo_internacional": (
            'Termo pesquisado em {bases}: "{termo}"'
        ),
        "sem_fontes": "Nenhuma fonte externa foi consultada nesta resposta.",
        "artigos_rigeo": "**Artigos do RIGeo ({n})**",
        "estacoes_ana": "**Estações {fonte} ({n})**",
        "ocorrencias_geosgb": (
            "**Ocorrências minerais do GeoSGB ({n})**"
        ),
        "processos_anm": (
            "**Processos minerários da ANM / SIGMINE ({n})**"
        ),
        "unidades_macrostrat": (
            "**Unidades litoestratigráficas (Macrostrat) ({n})**"
        ),
        "pocos_siagas": "**Poços do SIAGAS / RIMAS ({n})**",
        "geossitios_inde": (
            "**Geossítios do INDE / GEOSSIT ({n})**"
        ),
        "paginas_web": "**Páginas da Web aberta ({n})**",
        "openalex_titulo": "**OpenAlex ({n})**",
        "servicos_intl": (
            "**Serviços Geológicos Internacionais ({n})**"
        ),
        "usgs_sciencebase": "**USGS ScienceBase ({n})**",
        "documentos_locais_consultados": (
            "**Documentos locais consultados ({n})**"
        ),
        "termo_intl_consultado": (
            'Termo internacional consultado: "{termo}"'
        ),
        "servico_generico": "Serviço geológico internacional",
        "vazio_geosgb": "GeoSGB: {motivo}",
        "vazio_anm": "ANM / SIGMINE: {motivo}",
        "vazio_macrostrat": "Macrostrat: {motivo}",
        "vazio_siagas": "SIAGAS / RIMAS: {motivo}",
        "vazio_geossit": "INDE / GEOSSIT: {motivo}",
        "vazio_web": "Web: {motivo}",
        "vazio_openalex": "OpenAlex: {motivo}",
        "vazio_intl": "Serviços Geológicos Internacionais: {motivo}",
        "vazio_usgs": "USGS ScienceBase: {motivo}",
        "motivo_geosgb": "nenhuma ocorrência encontrada.",
        "motivo_anm": "nenhum processo encontrado.",
        "motivo_macrostrat": "nenhuma unidade encontrada.",
        "motivo_siagas": "nenhum poço encontrado.",
        "motivo_geossit": "nenhum geossítio encontrado.",
        "motivo_web": "nenhuma página encontrada.",
        "motivo_openalex": "nenhum registro encontrado.",
        "motivo_intl": "nenhum registro encontrado.",
        "motivo_usgs": "nenhum registro encontrado.",
        "link_abrir_macrostrat": "🔗 Abrir Macrostrat",
        "link_ficha_unidade": "📄 Ficha da unidade",
        "link_abrir_siagas": "🔗 Abrir SIAGAS",
        "link_ficha_poco": "📄 Ficha do poço",
        "link_abrir_geossit": "🔗 Abrir GEOSSIT",
        "link_ficha_geossitio": "📄 Ficha do geossítio",
        "link_abrir_openalex": "🔗 Abrir no OpenAlex",
        "link_abrir_servico": "🔗 Abrir no serviço geológico",
        "link_ficha_sciencebase": "🔗 Ficha no ScienceBase",
        "ultimo_evento": "Último evento: {evento}",
        "aviso_servicos_intl": "Serviços internacionais: {aviso}",
        "link_series_historicas": "🔗 Séries históricas",
        "link_abrir_pagina": "🌐 Abrir página",
        "link_abrir_geosgb": "🔗 Abrir GeoSGB",
        "link_abrir_sigmine": "🔗 Abrir SIGMINE",
        "link_abrir_pdf": "📄 Abrir PDF",
        "link_ficha_rigeo": "🔗 Ficha RIGeo",
        "resumo_rapido_expander": "📈 Resumo Estatístico Rápido",
        # -- Intenções do roteador ----------------------------------
        "intencao_local": "somente documentos locais",
        "intencao_rigeo": "somente RIGeo (SGB)",
        "intencao_hibrido": "documentos locais + RIGeo",
        "intencao_ana": "somente estações ANA/HidroWeb",
        "intencao_geral": "conhecimento geral",
        # -- Mapa espacial ------------------------------------------
        "mapa_expander": (
            "🗺️ Visualização Espacial das Áreas e Pontos Citados "
            "({n} feições)"
        ),
        "mapa_camadas": "Camadas exibidas",
        "ajuda_mapa_camadas": (
            "Isola, por exemplo, apenas poços do SIAGAS e estações da "
            "ANA, ou só ocorrências do SGB com processos da ANM."
        ),
        "mapa_sem_feicoes": (
            "Nenhuma feição nas camadas selecionadas. Escolha ao menos "
            "uma camada acima."
        ),
        "mapa_alt": (
            "Mapa com {n} ponto(s) geográfico(s) das fontes consultadas "
            "nesta resposta."
        ),
        "mapa_tabela_alt": (
            "Tabela com nome, camada, coordenadas, folha CIM, limites e "
            "detalhe de cada feição exibida no mapa."
        ),
        "col_nome": "Nome",
        "col_camada": "Camada",
        "col_latitude": "Latitude",
        "col_longitude": "Longitude",
        "col_folha_cim": "Folha CIM",
        "col_limites": "Limites (bounding box)",
        "col_detalhe": "Detalhe",
        "outras_fontes": "Outras fontes",
        "baixar_pontos": "📥 Baixar Pontos (CSV para QGIS)",
        "ajuda_baixar_pontos": (
            "CSV em UTF-8 com separador ';' e ponto decimal nas "
            "coordenadas: abre direto como camada delimitada no QGIS e "
            "como planilha no Excel."
        ),
        "mapa_rodape": (
            "{exibidas} de {total} feição(ões) exibida(s) · "
            "{camadas_ativas} de {camadas} camada(s) ativa(s)."
        ),
        # -- Parecer técnico ----------------------------------------
        "parecer_expander": "📄 Exportar Parecer Técnico",
        "parecer_texto": (
            "Documento com cabeçalho institucional, escopo, análise, "
            "síntese espacial e referências no padrão ABNT NBR 6023."
        ),
        "consulta_historico": "Consulta registrada no histórico",
        "word_indisponivel": "Word indisponível",
        "parecer_erro_word": (
            "Não foi possível gerar o arquivo Word desta resposta."
        ),
        "baixar_parecer_docx": "📥 Baixar Parecer (.docx)",
        "ajuda_parecer_docx": (
            "Word com tabelas nativas, cabeçalho institucional, rodapé "
            "numerado e referências ABNT."
        ),
        "parecer_erro_md": (
            "Não foi possível gerar o arquivo Markdown desta resposta."
        ),
        "baixar_relatorio_md": "📝 Baixar Relatório (.md)",
        "ajuda_relatorio_md": (
            "Versão estruturada em Markdown, pronta para edição ou "
            "versionamento."
        ),
        "parecer_rodape": (
            "Perfil analítico: {perfil} · {grupos} grupo(s) de fonte(s) "
            "· {feicoes} feição(ões) espacial(is)."
        ),
        # -- Planilhas e tabelas ------------------------------------
        "dados_expander": "📊 Extração & Exploração de Dados",
        "dados_caption": (
            "Tabelas Markdown e grades dos documentos locais, mais os "
            "registros das APIs usadas na conversa. Tipagem automática, "
            "filtros e download em CSV e Excel."
        ),
        "dados_spinner": "Extraindo tabelas dos documentos locais...",
        "dados_falhas_leitura": (
            "{n} documento(s) não puderam ser lidos para extração de "
            "tabelas."
        ),
        "dados_sem_tabelas": (
            "Nenhum bloco tabular foi reconhecido nos documentos "
            "indexados nem nas fontes desta conversa."
        ),
        "dados_contagem": (
            "{documentos} tabela(s) de documentos · {sessao} tabela(s) "
            "de fontes da sessão."
        ),
        "dados_tabela_rotulo": "Tabela extraída",
        "dados_origem": (
            "**{titulo}** · origem: {origem} · página: {pagina} · "
            "{linhas} linha(s) × {colunas} coluna(s)"
        ),
        "dados_unidades": "Unidades: {unidades}",
        "dados_visualizacao": "Visualização",
        "dados_tipados": "Dados tipados (numéricos)",
        "dados_brutos": "Dados originais (brutos)",
        "dados_busca_coluna": "Busca textual por coluna",
        "dados_sem_busca": "Sem busca",
        "dados_texto_procurado": "Texto procurado",
        "dados_placeholder_busca": "ex.: ouro, AM, 2023",
        "dados_filtrar_faixa": "Filtrar por faixa numérica",
        "dados_ajuda_faixa": (
            "A faixa é aplicada à tabela tipada e vale também para a "
            "visualização dos dados originais."
        ),
        "dados_coluna_numerica": "Coluna numérica",
        "dados_faixa": "Faixa de valores",
        "dados_sem_numericos": (
            "A coluna selecionada não tem valores numéricos."
        ),
        "dados_valor_unico": "Valor único na coluna: {valor}",
        "dados_sem_coluna_numerica": (
            "Nenhuma coluna numérica tipada nesta tabela."
        ),
        "exportacao_caption": (
            "A exportação inclui as linhas após os filtros ativos. "
            "Nenhum arquivo temporário é gravado no disco."
        ),
        "baixar_csv": "Baixar CSV",
        "ajuda_csv_dados": (
            "UTF-8 com BOM, separador ';' e decimal com vírgula: abre "
            "direto no Excel em português e no QGIS."
        ),
        "baixar_excel": "Baixar Excel",
        "ajuda_excel": (
            "Abas 'Dados' (tipados), 'Dados brutos' e 'Metadados' de "
            "origem, com cabeçalho formatado."
        ),
        "excel_indisponivel": "Excel indisponível",
        "resumo_numerico_alt": (
            "Resumo estatístico das colunas numéricas"
        ),
        "resumo_colunas_alt": (
            "Contagem de nulos e valores únicos por coluna"
        ),
        "resumo_coluna": "Coluna",
        "resumo_contagem": "Contagem",
        "resumo_media": "Média",
        "resumo_desvio": "Desvio padrão",
        "resumo_minimo": "Mínimo",
        "resumo_mediana": "Mediana",
        "resumo_maximo": "Máximo",
        "resumo_tipo": "Tipo",
        "resumo_nulos": "Nulos",
        "resumo_unicos": "Únicos",
        "resumo_linhas_colunas": (
            "{linhas} linha(s) na tabela original · {colunas} coluna(s) "
            "na tabela tipada."
        ),
        # -- Governança do contrato de saída (Fase D1) ----------------
        "governanca_motivo_texto_livre": (
            "Formato livre detectado: a resposta foi preservada, mas "
            "exige revisão humana."
        ),
        "governanca_motivo_resposta_vazia": (
            "O modelo devolveu uma resposta vazia."
        ),
        "governanca_motivo_contrato_invalido": (
            "O contrato de saída está incompleto ou malformado."
        ),
        "governanca_motivo_observado_sem_evidencia": (
            "Afirmação OBSERVED sem evidence_id foi rebaixada para "
            "INFERRED."
        ),
        "governanca_motivo_evidencia_desconhecida": (
            "A evidência citada não está no catálogo e o vínculo foi "
            "removido."
        ),
        "governanca_motivo_classificacao_desconhecida": (
            "Classificação de afirmação não reconhecida; tratada como "
            "INFERRED."
        ),
        "governanca_motivo_veredito_invalido": (
            "O veredito declarado pelo modelo é inválido."
        ),
        "governanca_motivo_falha_declarada": (
            "O modelo declarou veredito FAIL."
        ),
        "governanca_motivo_veredito_hold": (
            "O modelo declarou veredito HOLD."
        ),
        "governanca_motivo_fonte_timeout": (
            "Tempo esgotado ao consultar a fonte."
        ),
        "governanca_motivo_fonte_tls": (
            "Falha de TLS/certificado ao consultar a fonte."
        ),
        "governanca_motivo_fonte_rede": (
            "Falha de rede ao consultar a fonte."
        ),
        "governanca_motivo_fonte_http": (
            "A fonte respondeu com erro HTTP {status}."
        ),
        "governanca_motivo_fonte_indisponivel": (
            "A fonte está indisponível; o resultado exige nova tentativa."
        ),
        "governanca_motivo_contrato_valido": (
            "Contrato válido: todas as afirmações OBSERVED têm evidência."
        ),
        # -- Workstation D4: layout adaptativo e semântica epistêmica ---
        "aba_sintese": "🧠 Síntese Técnica",
        "aba_mapa_workstation": "🗺️ Mapa Espacial",
        "aba_dados_exportacao": "📊 Dados & Exportação",
        "workstation_indicadores": "Indicadores",
        "workstation_fontes_ativas": "Fontes ativas",
        "workstation_alvos_cim": "Alvos / Folhas CIM",
        "workstation_governanca_titulo": "Governança epistêmica",
        "workstation_sem_afirmacoes": (
            "Nenhuma afirmação auditada ainda. A proporção OBSERVED x "
            "INFERRED aparece na primeira resposta."
        ),
        "workstation_rastreabilidade_titulo": (
            "Rastreabilidade & Governança"
        ),
        "workstation_evidencias_alt": (
            "Tabela ranqueada dos evidence_id citados"
        ),
        "workstation_coluna_evidencia": "evidence_id",
        "workstation_coluna_citacoes": "Citações",
        "workstation_coluna_aderencia": "Aderência",
        "workstation_ajuda_aderencia": (
            "Proporção de citações OBSERVED deste evidence_id."
        ),
        "workstation_sem_evidencias": (
            "Nenhum evidence_id citado nas respostas desta conversa."
        ),
        "workstation_motor_titulo": "Governança & Motor",
        "workstation_modo_online": "Modo Online",
        "workstation_modo_offline": "Modo Offline",
        "workstation_modelo_ativo": "Modelo ativo: {modelo}",
        "workstation_modelo_fallback": "fallback local",
        "workstation_criterios": "Critérios de classificação",
        "workstation_criterio_observed": (
            "OBSERVED: ancorado em evidence_id/fonte rastreada."
        ),
        "workstation_criterio_inferred": (
            "INFERRED: síntese interpretativa do modelo."
        ),
        "workstation_resumo_proporcao": (
            "OBSERVED {observed:.1f}% · INFERRED {inferred:.1f}%"
        ),
        "workstation_mapa_vazio": (
            "Nenhum ponto ou folha CIM detectado nesta conversa."
        ),
        "workstation_mapa_contagem": (
            "{n} ponto(s) e folha(s) no mapa."
        ),
        "workstation_mapa_alt": (
            "Mapa espacial com {n} feição(ões) detectada(s)"
        ),
        "workstation_mapa_tabela_alt": (
            "Prévia tabular das feições do mapa"
        ),
        "workstation_coluna_nome": "Nome",
        "workstation_coluna_camada": "Camada",
        "workstation_coluna_folha": "Folha CIM",
        "workstation_baixar_csv": "Baixar CSV do mapa",
        "workstation_cim_ferramentas": (
            "Ferramentas CIM e pacote offline"
        ),
        # -- Barra lateral D1: serviço, rede, persistência e histórico ---
        "secao_servico": "⚙️ Serviço local",
        "servico_ollama_online": "Ollama online · {modelo}",
        "servico_ollama_offline": "Ollama offline · {modelo}",
        "servico_modelo_ativo": "Modelo ativo: {modelo}",
        "servico_roteador": "Roteador: SLM local (Ollama)",
        "servico_roteador_regra": "Roteador: regra local determinística",
        "servico_roteador_fallback": "Roteador: fallback determinístico",
        "servico_roteador_pendente": "Roteador: aguardando a primeira consulta",
        "ajuda_servico_roteador": (
            "Origem da última decisão de roteamento. O roteador usa o "
            "SLM local quando ele responde e cai em regra/heurística "
            "determinística quando o Ollama não está disponível."
        ),
        "ajuda_servico_ollama": (
            "Estado do serviço Ollama consultado em /api/version."
        ),
        "rede_online": "🌐 Online",
        "rede_cache_folha_cim": "🗂️ Cache Offline por Folha CIM",
        "rede_offline_sem_cache": "⚠️ Offline sem cache CIM",
        "rede_cache_folhas": "{n} folha(s) CIM em cache local",
        "ajuda_rede_online": (
            "Há conexão com o serviço local; as fontes externas podem "
            "ser consultadas."
        ),
        "ajuda_rede_cache": (
            "Sem conexão no momento: as respostas usam o cache espacial "
            "por folha CIM e os caches locais dos conectores."
        ),
        "dados_diretorio": "Persistência: {caminho}",
        "dados_origem_env": "origem: ASSISTENTE_DATA_DIR",
        "dados_origem_localappdata": "origem: %LOCALAPPDATA%\\NexusGeoIA",
        "dados_origem_projeto": "origem: pasta do aplicativo",
        "ajuda_dados_diretorio": (
            "Diretório gravável reservado ao banco SQLite, documentos e "
            "caches. Defina ASSISTENTE_DATA_DIR para trocar de pasta."
        ),
        "sidebar_nova_conversa": "➕ Nova Conversa",
        "ajuda_sidebar_nova_conversa": (
            "Grava a conversa atual no SQLite e abre uma conversa em "
            "branco, sem apagar documentos nem histórico."
        ),
        "historico_workflow_marcador": "Fluxo: {workflow}",
        "historico_folha_marcador": "Folha CIM: {folha}",
        "historico_sqlite_erro": (
            "Não foi possível acessar o histórico SQLite; a lista pode "
            "estar incompleta."
        ),
        "aviso_historico_salvar_erro": (
            "Não foi possível gravar a conversa no banco local."
        ),
        "aviso_historico_excluir_erro": (
            "Não foi possível excluir a conversa do banco local."
        ),
        # -- Aba 1 (Consulta & Evidência) -----------------------------
        "workflow_titulo": "🧭 Fluxo de trabalho",
        "workflow_ajuda": (
            "Escolha explícita do fluxo antes de enviar a pergunta. O "
            "fluxo é gravado em cada resposta e no histórico."
        ),
        "workflow_consulta_direta": "Consulta Direta",
        "workflow_triagem_area": "Triagem de Área / Viabilidade Mineral",
        "workflow_hidrogeologia": "Hidrogeologia",
        "workflow_sondagem": "Sondagem & Litologia",
        "workflow_caption": (
            "Fluxo ativo: {workflow}. A decisão fica registrada na "
            "resposta e no histórico."
        ),
        "workflow_instrucao_consulta_direta": (
            "Fluxo de trabalho: Consulta Direta. Responda objetivamente, "
            "sem etapas adicionais de triagem."
        ),
        "workflow_instrucao_triagem_area": (
            "Fluxo de trabalho: Triagem de Área / Viabilidade Mineral. "
            "Estruture a resposta em contexto geológico, evidências, "
            "viabilidade mineral e lacunas de dados."
        ),
        "workflow_instrucao_hidrogeologia": (
            "Fluxo de trabalho: Hidrogeologia. Priorize aquíferos, poços, "
            "vazões e o cruzamento entre águas superficiais e subterrâneas."
        ),
        "workflow_instrucao_sondagem": (
            "Fluxo de trabalho: Sondagem & Litologia. Priorize litologia, "
            "profundidade, testemunhos e correlação entre seções."
        ),
        "workflow_badge": "🧭 {workflow}",
        "governanca_veredito_pass": "PASS · contrato válido",
        "governanca_veredito_hold": "HOLD · revisão necessária",
        "governanca_veredito_fail": "FAIL · não conforme",
        "governanca_badge_observed": "OBSERVED · {n}",
        "governanca_badge_inferred": "INFERRED · {n}",
        "governanca_motivo": "Motivo objetivo: {motivo}",
        "governanca_sem_afirmacoes": (
            "A resposta não trouxe afirmações estruturadas; o veredito "
            "segue a regra do contrato."
        ),
        "governanca_afirmacoes": "Afirmações auditáveis ({n})",
        "governanca_evidencia": "Evidência",
        "governanca_ajuda": (
            "Veredito calculado por core/governance.py a partir do "
            "contrato de saída; nunca exibe traceback na interface."
        ),
        "governanca_coluna_afirmacao": "Afirmação",
        "governanca_coluna_classificacao": "Classificação",
        "governanca_coluna_evidencia": "evidence_id",
        "proveniencia_expander": "🧾 Proveniência da resposta",
        "proveniencia_contagem": "{n} evidência(s) rastreada(s)",
        "proveniencia_vazia": (
            "Nenhuma fonte rastreável registrada para esta resposta."
        ),
        "proveniencia_ajuda": (
            "Tabela estruturada de linhagem: tipo da fonte, localizador, "
            "data de coleta e se o dado veio ao vivo ou do cache offline."
        ),
        "proveniencia_origem_live": "Live",
        "proveniencia_origem_cache": "Cache Offline",
        "proveniencia_origem_local": "Local",
        "proveniencia_truncada": (
            "Exibindo {n} de {total} evidências rastreadas."
        ),
        # -- Abas da área principal (Fase D2) -----------------------
        "aba_consulta": "💬 Consulta & Evidência",
        "aba_espacial": "🧭 Resolução Espacial",
        "aba_dados": "📊 Dados & Exportação",
        "aba_sondagem": "🧪 Sondagem & Litologia",
        # -- Aba 4: grade de sondagem De-Ate (Fase D3b) -------------
        "sondagem_titulo": "Grade de sondagem De–Até",
        "sondagem_caption": (
            "Cole uma tabela de furos e intervalos com cabeçalhos em "
            "português ou inglês. O parser reconhece De/Até, Prof. de/até, "
            "Intervalo, From/To, Furo/Hole e Litologia/Lithology, "
            "normaliza vírgula e ponto decimal, converte m/cm e mantém as "
            "linhas inválidas no relatório sem descartar os intervalos "
            "válidos."
        ),
        "sondagem_texto_rotulo": "Tabela de sondagem (CSV/TSV colado)",
        "sondagem_texto_ajuda": (
            "Separador ';', tabulação, vírgula ou '|'. Use vírgula decimal "
            "com separador ';' para evitar ambiguidade. A coluna Unidade "
            "aceita m ou cm e o cabeçalho também pode declará-la, como em "
            "'Prof. de (cm)' ou 'Intervalo (m)'. A unidade escrita na "
            "célula tem precedência; 'Intervalo' aceita '0 - 1,5 m', "
            "'0 a 1,5' e '0 até 1,5 m'."
        ),
        "sondagem_exemplo": (
            "Furo;Prof. de;Prof. até;Unidade;Litologia;Amostra;Observação\n"
            "FQ-01;0,00;2,50;;Solo residual;A-01;Topo\n"
            "FQ-01;2,50;5,00;;Saprolito;A-02;\n"
            "FQ-01;5,00;8,00;;Rocha alterada;A-03;\n"
            "FQ-02;0;150;cm;Solo coluvial;A-04;\n"
            "FQ-02;150;300;cm;Granito fresco;A-05;\n"
        ),
        "sondagem_analisar": "Analisar grade",
        "sondagem_limpar": "Limpar resultado",
        "sondagem_erro_cabecalhos": (
            "Cabeçalhos obrigatórios não reconhecidos: {campos}. Use "
            "Furo/Hole e De/Até (ou Intervalo/From/To). A unidade pode "
            "vir entre parênteses, como em 'Prof. de (cm)'."
        ),
        "sondagem_erro_tabela_vazia": (
            "A tabela está vazia. Cole os furos e os intervalos De–Até."
        ),
        "sondagem_erro_sem_linhas": (
            "Nenhuma linha de dados encontrada depois do cabeçalho."
        ),
        "sondagem_erro_cabecalhos_ausentes": (
            "Para uma lista de valores, informe também os cabeçalhos."
        ),
        "sondagem_erro_leitura": (
            "Não foi possível ler a tabela de sondagem. Confira o "
            "separador e os cabeçalhos."
        ),
        "sondagem_erro_tabela_desalinhada": (
            "As linhas {linhas} têm número de campos diferente do "
            "cabeçalho. Confira o separador: com vírgula decimal, use "
            "';', tabulação ou '|' para não criar colunas extras."
        ),
        "sondagem_erro_tempo_excedido": (
            "A análise excedeu o prazo de {segundos} e foi interrompida "
            "sem gerar grade parcial. Reduza a tabela ou divida os furos "
            "em lotes."
        ),
        "sondagem_erro_cancelada": (
            "Análise cancelada. A grade anterior, se existir, foi "
            "preservada."
        ),
        "sondagem_sucesso": (
            "{n} intervalo(s) válido(s) em {furos} furo(s)."
        ),
        "sondagem_metric_intervalos": "Intervalos válidos",
        "sondagem_metric_invalidos": "Linhas inválidas",
        "sondagem_metric_sobreposicoes": "Sobreposições",
        "sondagem_metric_lacunas": "Lacunas",
        "sondagem_aviso_invalidos": (
            "{n} linha(s) inválida(s) foram mantidas no relatório e não "
            "entram na grade principal."
        ),
        "sondagem_aviso_sobreposicoes": (
            "{n} sobreposição(ões) de profundidade detectada(s)."
        ),
        "sondagem_aviso_lacunas": (
            "{n} lacuna(s) entre intervalos consecutivos detectada(s)."
        ),
        "sondagem_filtros": "Filtros da grade",
        "sondagem_filtro_furo": "Furo",
        "sondagem_filtro_todos_furos": "Todos os furos",
        "sondagem_filtro_litologia": "Litologia",
        "sondagem_filtro_situacao": "Situação",
        "sondagem_filtro_busca": "Busca textual",
        "sondagem_busca_placeholder": "ex.: granito, A-01, saprolito",
        "sondagem_grade_alt": (
            "Grade De–Até com {n} intervalo(s) de sondagem."
        ),
        "sondagem_contagem_exibida": (
            "{exibidos} de {total} intervalo(s) exibido(s)."
        ),
        "sondagem_sem_resultado_filtro": (
            "Nenhum intervalo atende aos filtros selecionados."
        ),
        "sondagem_invalidos_titulo": "Linhas inválidas ({n})",
        "sondagem_invalidos_alt": (
            "Relatório de linhas inválidas com número da linha, furo, "
            "profundidades originais e motivo."
        ),
        "sondagem_sobreposicoes_titulo": "Sobreposições ({n})",
        "sondagem_sobreposicoes_alt": (
            "Intervalos que avançam sobre o intervalo anterior do mesmo "
            "furo, com a espessura da sobreposição."
        ),
        "sondagem_lacunas_titulo": "Lacunas ({n})",
        "sondagem_lacunas_alt": (
            "Vãos entre intervalos consecutivos do mesmo furo, com a "
            "espessura da lacuna."
        ),
        "sondagem_coluna_linha": "Linha",
        "sondagem_coluna_furo": "Furo",
        "sondagem_coluna_de": "De (m)",
        "sondagem_coluna_ate": "Até (m)",
        "sondagem_coluna_de_original": "De (original)",
        "sondagem_coluna_ate_original": "Até (original)",
        "sondagem_coluna_unidade": "Unidade",
        "sondagem_coluna_espessura": "Espessura (m)",
        "sondagem_coluna_litologia": "Litologia",
        "sondagem_coluna_amostra": "Amostra",
        "sondagem_coluna_observacao": "Observação",
        "sondagem_coluna_situacao": "Situação",
        "sondagem_coluna_motivo": "Motivo",
        "sondagem_coluna_anterior": "Linha anterior",
        "sondagem_coluna_sobreposicao": "Sobreposição (m)",
        "sondagem_coluna_lacuna": "Lacuna (m)",
        "sondagem_situacao_valido": "Válido",
        "sondagem_situacao_sobreposicao": "Sobreposição",
        "sondagem_situacao_lacuna": "Lacuna",
        "sondagem_situacao_sobreposicao_lacuna": "Sobreposição e lacuna",
        "sondagem_situacao_invalido": "Inválido",
        "sondagem_situacao_desconhecida": "Não classificada",
        "sondagem_motivo_furo_ausente": "Furo não informado",
        "sondagem_motivo_de_ausente": "Profundidade inicial ausente",
        "sondagem_motivo_ate_ausente": "Profundidade final ausente",
        "sondagem_motivo_de_invalido": "Profundidade inicial inválida",
        "sondagem_motivo_ate_invalido": "Profundidade final inválida",
        "sondagem_motivo_intervalo_invalido": "Intervalo não reconhecido",
        "sondagem_motivo_de_negativo": "Profundidade inicial negativa",
        "sondagem_motivo_ate_nao_maior": (
            "Profundidade final menor ou igual à inicial"
        ),
        "sondagem_motivo_unidade_invalida": "Unidade de profundidade inválida",
        "sondagem_motivo_generico": "Linha inválida",
        "sondagem_aviso_neutralizacao": (
            "Fórmulas iniciadas por =, +, -, @, tabulação, CR ou LF são "
            "neutralizadas no CSV/XLSX; números negativos válidos são "
            "preservados."
        ),
        "sondagem_exportar_csv": "Baixar CSV sanitizado",
        "sondagem_exportar_xlsx": "Baixar XLSX sanitizado",
        "sondagem_ajuda_csv": (
            "UTF-8 com BOM, separador ';' e vírgula decimal; inclui as "
            "linhas inválidas no relatório."
        ),
        "sondagem_ajuda_xlsx": (
            "Planilha em memória; células perigosas ficam como texto e os "
            "números seguem numéricos."
        ),
        "sondagem_arquivo_csv": "grade_sondagem.csv",
        "sondagem_arquivo_xlsx": "grade_sondagem.xlsx",
        "aba_ajuda": (
            "A conversa, o histórico e as escolhas da barra lateral são "
            "preservados ao alternar entre as abas."
        ),
        # -- Aba 2: resolução espacial e pacote offline -------------
        "espacial_titulo": "Resolução espacial e pacote offline",
        "espacial_caption": (
            "Converta coordenadas ou códigos CIM, confira a hierarquia "
            "cartográfica de 1:1.000.000 a 1:25.000 e baixe a folha para "
            "consultar tudo sem rede."
        ),
        "espacial_modo": "Tipo de consulta",
        "espacial_modo_coordenadas": "Coordenadas",
        "espacial_modo_folha": "Folha CIM",
        "espacial_latitude": "Latitude",
        "espacial_longitude": "Longitude",
        "espacial_folha_cim": "Código da folha CIM",
        "espacial_placeholder_folha": "ex.: SA.20, SB.21-X-B, SC.22-Z-D-IV",
        "espacial_rotulado": "Coordenadas rotuladas (não inverter)",
        "espacial_ajuda_rotulado": (
            "Ligado, a ordem latitude/longitude é respeitada mesmo quando "
            "o par parece invertido; um erro de entrada é recusado em vez "
            "de virar um ponto falso."
        ),
        "espacial_consultar": "Resolver posição",
        "espacial_limpar": "Limpar resultado",
        "espacial_cartao_titulo": "Cartão de resolução espacial",
        "espacial_resultado_coordenadas": "Coordenadas normalizadas",
        "espacial_inversao_detectada": (
            "Eixos invertidos automaticamente: leitura corrigida para "
            "{par}."
        ),
        "espacial_inversao_indevida": (
            "A latitude informada está fora de ±90°. O par parece "
            "invertido; confirme a ordem latitude/longitude."
        ),
        "espacial_coordenada_invalida": (
            "Coordenadas inválidas. Use latitude entre -90 e 90 e "
            "longitude entre -180 e 180."
        ),
        "espacial_coordenada_ausente": "Informe latitude e longitude.",
        "espacial_folha_invalida": (
            "Código CIM inválido. Use o formato SA.20 ou "
            "SB.21-X-B-IV-1."
        ),
        "espacial_erro_generico": (
            "Não foi possível resolver a consulta espacial."
        ),
        "espacial_hierarquia": "Hierarquia cartográfica",
        "espacial_escala": "Escala",
        "espacial_codigo": "Código",
        "espacial_centroide": "Centroide",
        "espacial_limites": "Limites",
        "espacial_pacote_titulo": "Pacote offline da folha CIM",
        "espacial_pacote_caption": (
            "O pacote grava o manifesto e os registros por fonte na "
            "memória operacional SQLite (spatial_cache). Depois do "
            "download, a consulta e a exportação funcionam sem rede."
        ),
        "espacial_pacote_folha": "Folha do pacote",
        "espacial_pacote_baixar": (
            "Baixar / Atualizar Pacote Offline da Folha"
        ),
        "espacial_pacote_disponivel": "Pacote offline disponível",
        "espacial_pacote_indisponivel": (
            "Pacote offline ainda não baixado para esta folha"
        ),
        "espacial_pacote_collected_at": "Coletado em",
        "espacial_pacote_source_version": "Versão da fonte",
        "espacial_pacote_total": "Registros no pacote",
        "espacial_pacote_fontes": "Totais por fonte",
        "espacial_pacote_fonte": "Fonte",
        "espacial_pacote_registros": "Registros",
        "espacial_pacote_exportar_manifesto": "Baixar manifesto (JSON)",
        "espacial_pacote_exportar_dados": "Exportar dados offline (CSV)",
        "espacial_pacote_sem_dados": (
            "Nenhuma feição compatível cai nesta folha. O pacote "
            "anterior foi preservado e não foi sobrescrito com um "
            "snapshot vazio."
        ),
        "espacial_pacote_criado": (
            "Pacote offline gravado: {total} registro(s) em "
            "{fontes} fonte(s)."
        ),
        "espacial_pacote_erro": (
            "Não foi possível gravar o pacote offline: {erro}"
        ),
        "espacial_pacote_remover": "Remover pacote offline",
        "espacial_pacote_removido": "Pacote offline removido.",
        "espacial_pacote_memoria": (
            "Persistido em SQLite; nenhum arquivo temporário é gravado."
        ),
        "espacial_offline_titulo": "Consulta desconectada",
        "espacial_offline_caption": (
            "Leitura exclusiva do SQLite local. Nenhum conector é "
            "chamado nesta seção."
        ),
        "espacial_offline_sem_dados": (
            "Nenhum registro offline para o filtro de fonte selecionado."
        ),
        "espacial_offline_fonte": "Filtrar fonte offline",
        "espacial_offline_todas": "Todas as fontes",
        "espacial_mapa_titulo": "Mapa interativo por fonte",
        "espacial_mapa_fontes": "Fontes exibidas",
        "espacial_mapa_sem_feicoes": (
            "Nenhuma feição nas fontes selecionadas. Escolha ao menos "
            "uma fonte acima."
        ),
        "espacial_mapa_alt": (
            "Mapa interativo com {n} feição(ões) da resolução espacial."
        ),
        "espacial_mapa_tooltip": (
            "Nome: {nome}\nFonte: {fonte}\nFolha CIM: {folha}"
        ),
        "espacial_tabela_titulo": "Prévia tabular antes do download",
        "espacial_tabela_alt": (
            "Tabela com nome, fonte, coordenadas e folha CIM de cada "
            "feição exibida."
        ),
        "espacial_exportar_csv": "Baixar CSV sanitizado",
        "espacial_exportar_xlsx": "Baixar XLSX sanitizado",
        "espacial_exportar_qgis": "Baixar GeoJSON para QGIS",
        "espacial_ajuda_csv": (
            "UTF-8 com BOM e separador ';': abre no Excel e no QGIS."
        ),
        "espacial_ajuda_xlsx": (
            "Planilha com prévia e dados; células perigosas ficam como "
            "texto."
        ),
        "espacial_ajuda_qgis": (
            "GeoJSON WGS84 com atributos sanitizados, pronto para "
            "arrastar no QGIS."
        ),
        "espacial_aviso_neutralizacao": (
            "Fórmulas iniciadas por =, +, -, @, tabulação, CR ou LF são "
            "neutralizadas antes de qualquer download."
        ),
        "espacial_sem_feicoes_sessao": (
            "Ainda não há feições espaciais nesta sessão. Resolva uma "
            "posição ou consulte fontes na Aba 1 para alimentar o mapa."
        ),
        "espacial_coluna_fonte": "Fonte",
        "espacial_coluna_nome": "Nome",
        "espacial_coluna_latitude": "Latitude",
        "espacial_coluna_longitude": "Longitude",
        "espacial_coluna_folha": "Folha CIM",
        "espacial_pacote_manifesto": "Manifesto do pacote",
        "espacial_pacote_nao_encontrado": (
            "Pacote não encontrado para a folha {folha}."
        ),
    },
    "en": {
        # -- Header and status --------------------------------------
        "titulo": APP_NAME,
        "subtitulo": (
            "Integrated Geoscientific Data & Local AI Platform"
        ),
        "ollama_online": "Ollama online · {host}",
        "ollama_offline": "Ollama offline · {host}",
        "badge_base_local": "📄 Local base",
        "badge_base_local_off": "Local base off",
        "ajuda_base_local": "Files in data/docs are used in the answers.",
        "ajuda_base_local_off": (
            "The local document base was turned off in the "
            "'Active Data Sources' section."
        ),
        "badge_rigeo_off": "RIGeo off",
        "ajuda_rigeo": "SGB geoscience collection (RIGeo) active.",
        "ajuda_rigeo_off": (
            "The SGB/RIGeo collection was turned off in the "
            "'Active Data Sources' section."
        ),
        "ajuda_web_tecnico": (
            "Web search is on in the sidebar. Technical and "
            "institutional domains only."
        ),
        "ajuda_web_aberta": (
            "Web search is on in the sidebar. Open web, with no domain "
            "restriction."
        ),
        "ajuda_ana": "ANA/HidroWeb station inventory active.",
        "ajuda_siagas": (
            "SIAGAS/RIMAS water wells are on in the 'Active Data "
            "Sources' section. The municipality and state come from the "
            "question; with ANA on, the answer cross-references surface "
            "and groundwater."
        ),
        "ajuda_geosgb": (
            "SGB (GeoSGB) geological occurrence and deposit registry "
            "active in the 'Active Data Sources' section. The "
            "commodity and state are extracted from the question."
        ),
        "ajuda_anm": (
            "ANM (SIGMINE) mining processes active in the 'Active Data "
            "Sources' section. The commodity, holder and state are "
            "extracted from the question; the phase is the one "
            "published by ANM."
        ),
        "ajuda_geossit": (
            "INDE/GEOSSIT geosite inventory active in the 'Active Data "
            "Sources' section: interest, relevance and coordinates."
        ),
        "ajuda_macrostrat": (
            "Macrostrat lithostratigraphic units active in the 'Active "
            "Data Sources' section: age, lithology and depositional "
            "environment."
        ),
        "ajuda_openalex": "International OpenAlex database on in the sidebar.",
        "badge_intl_geo_regioes": "🌐 International Geo · {regioes}",
        "ajuda_intl_geo_regioes": (
            "International geological surveys active, restricted to: "
            "{regioes}"
        ),
        "ajuda_intl_geo_todas": (
            "All open international geological survey services are "
            "active (OneGeology, USGS, NRCan, EGDI, GA/GSQ, GSJ, "
            "GeoNet, CGS/DE Africa, NGD and GSI/Bhukosh)."
        ),
        "ajuda_perfil": "Analysis mode: {perfil}. {descricao}",
        "badge_prompt_editado": "✍️ Edited prompt",
        "ajuda_prompt_editado": (
            "The active system prompt was changed from the text of the "
            "selected analysis mode."
        ),
        # -- Sidebar: document base ---------------------------------
        "secao_documentos": "📄 Document Base (Upload)",
        "texto_documentos": (
            "Upload .txt, .md or .pdf files. Each file is converted to "
            "clean Markdown before indexing; scanned pages go through "
            "local OCR."
        ),
        "ocr_indisponivel": (
            "Local OCR unavailable: scanned PDFs will not be read. Run "
            "pip install -r requirements.txt to enable it."
        ),
        "rotulo_upload": "Add documents",
        "botao_salvar_documentos": "Save documents",
        "status_convertendo": "Converting documents to Markdown…",
        "progresso_convertidos": "{feitos}/{total} file(s) converted",
        "progresso_processados": "{total}/{total} file(s) processed",
        "status_convertidos_resumo": (
            "{salvos} of {total} document(s) converted to Markdown"
        ),
        "sucesso_indexados": (
            "{n} document(s) converted to Markdown and indexed."
        ),
        "ocr_aplicado": (
            "Local OCR applied to {ocr} of {total} page(s)."
        ),
        "sem_ocr": "None of the {total} page(s) needed OCR.",
        "cache_reaproveitado": (
            "{n} document(s) reused from the cache in data/cache_md/."
        ),
        "detalhe_paginas": "{paginas} page(s) converted",
        "detalhe_ocr": " · {paginas} via OCR",
        "detalhe_cache": " · cached copy reused",
        "limite_arquivo_documento": (
            "The file exceeds the 100 MB limit for indexing."
        ),
        "limite_paginas_pdf": (
            "The PDF exceeds the 500-page limit for indexing."
        ),
        "titulo_arquivo_nao_indexado": "File not indexed",
        "titulo_arquivo_sem_texto": "File with no selectable text",
        "documentos_contagem": "{n} file(s) in data/docs:",
        "documentos_excedente": "+ {n} file(s) not shown.",
        "botao_limpar_base": "🗑️ Clear Document Base",
        "ajuda_limpar_base": (
            "Removes every file in data/docs and the cached Markdown "
            "(data/cache_md/). The document base becomes empty again."
        ),
        "documentos_vazio": "No documents loaded in data/docs.",
        "selo_indexado_ocr": "Indexed (OCR)",
        "selo_indexado": "Indexed",
        "selo_sem_texto": "No text",
        "ajuda_doc_ocr": (
            "Markdown generated with OCR on {ocr} of {total} page(s)."
        ),
        "ajuda_doc_nativo": "Markdown generated from native text.",
        "ajuda_doc_sem_texto": (
            "The text of this file could not be read."
        ),
        "ajuda_excluir_documento": (
            'Delete "{nome}" from data/docs and the cache in '
            "data/cache_md/."
        ),
        "aviso_limpar_falhas": "Could not delete: {falhas}.",
        "aviso_limpeza_sucesso": (
            "{n} document(s) deleted from data/docs and the cache in "
            "data/cache_md/."
        ),
        "aviso_documento_excluido": (
            "{nome} deleted from data/docs and the cache in "
            "data/cache_md/."
        ),
        "aviso_excluir_documento_erro": (
            "Could not delete {nome}: {erro}"
        ),
        # -- Sidebar: history ---------------------------------------
        "secao_historico": "💬 Conversation History",
        "historico_vazio": (
            "No saved conversations yet. Queries appear here "
            "automatically."
        ),
        "historico_contagem": (
            "{n} saved conversation(s) · newest first"
        ),
        "historico_aberta": "Conversation currently open.",
        "historico_abrir": "Open this conversation · last update: {data}",
        "historico_excluir": 'Delete conversation "{titulo}".',
        "historico_nao_salva": (
            "The open conversation is not finished yet (not saved)."
        ),
        "botao_apagar_tudo": "🗑️ Delete All History",
        "ajuda_apagar_tudo": (
            "Deletes every conversation saved in data/historico. Files "
            "in data/docs are preserved."
        ),
        "botao_apagar_confirmado": "🗑️ Yes, delete all history",
        "ajuda_apagar_confirmado": (
            "Confirms the permanent deletion of every conversation."
        ),
        "botao_cancelar": "Cancel",
        "ajuda_cancelar": "Keeps the history as it is.",
        "confirmar_apagar_titulo": (
            "⚠️ Confirm deletion of all conversations"
        ),
        "confirmar_apagar_texto": (
            "Every saved conversation will be removed from "
            "data/historico. Documents indexed in data/docs are not "
            "affected."
        ),
        "aviso_abrir_erro": (
            "This conversation could not be opened: the file no longer "
            "exists or is corrupted."
        ),
        "aviso_conversa_excluida": "Conversation deleted from history.",
        "aviso_historico_apagado": (
            "History deleted: {n} conversation(s) removed. Documents "
            "indexed in data/docs were preserved."
        ),
        "aviso_sem_conversas": "There were no saved conversations to delete.",
        "nova_conversa": "New conversation",
        # -- Sidebar: sources ---------------------------------------
        "secao_fontes": "🗂️ Active Data Sources",
        "texto_fontes": (
            "Every source enabled here is used in all questions. Turn "
            "off what you do not want to query; nothing is ignored or "
            "enabled without your consent."
        ),
        "toggle_local_docs": "📄 Local Document Base (PDF/MD/TXT)",
        "ajuda_local_docs": (
            "Queries the files indexed in data/docs, converted to "
            "Markdown. When off, the answer uses only the other enabled "
            "sources."
        ),
        "grupo_geologia_geofisica": "Geology & Geophysics",
        "grupo_recursos_minerais_anm": "Mineral Resources & ANM",
        "grupo_hidrogeologia_hidricos": "Hydrogeology & Water",
        "grupo_literatura_apoio": "Literature & Support",
        "web_tecnicos": "Prioritize technical domains (.gov / SciELO / USGS)",
        "ajuda_web_tecnicos": (
            "Restricts the search to technical and institutional "
            "domains (site:gov.br OR site:sgb.gov.br OR "
            "site:anm.gov.br OR site:scielo.br OR site:usgs.gov). "
            "Leave it unchecked to search the whole open web."
        ),
        "dica_siagas": (
            "The municipality and state come from the question (e.g. "
            "\"water wells in Apui, Amazonas\"). Without them, the list "
            "is a sample from the state."
        ),
        "dica_geosgb": (
            "The commodity and state come from the question (e.g. "
            "\"gold occurrences in Para\"). Without a commodity or "
            "state, the connector warns instead of running a nationwide "
            "query."
        ),
        "dica_anm": (
            "Accepts the commodity (e.g. \"rare earths in Amazonas\"), "
            "the holder (e.g. \"Brazilian Critical Minerals\") or the "
            "state. The phase comes from SIGMINE, as published by ANM."
        ),
        "dica_macrostrat": (
            "Uses the coordinates from the question (or from a local "
            "document) when available; otherwise it looks up the named "
            "unit."
        ),
        "dica_geossit": (
            "Accepts the geosite name or a theme (\"stromatolite\", "
            "\"waterfall\") and the state. Without a filter, it returns "
            "the inventory for the area."
        ),
        "onde_buscar": "Where to search?",
        "placeholder_regioes": "Select where to search...",
        "ajuda_regioes": (
            "Choose one or more regions/services. 'All Regions' queries "
            "the ten connectors in parallel; the other options restrict "
            "the search to exactly the selected services."
        ),
        # -- Connector labels and help ------------------------------
        "fonte_rigeo": "🏛️ SGB / RIGeo (Geoscience Collection)",
        "ajuda_fonte_rigeo": (
            "Queries the Geological Survey of Brazil collection in "
            "RIGeo, with a GeoBusca fallback. It is the main "
            "geoscience source."
        ),
        "fonte_ana": "💧 ANA / HidroWeb (Hydrological Stations)",
        "ajuda_fonte_ana": (
            "Queries the public ANA station inventory (HidroWeb/SNIRH) "
            "by the municipality, river, sub-basin or state mentioned "
            "in the question. Useful for hydrological, hydrogeological "
            "and environmental licensing studies."
        ),
        "fonte_web": "🌐 Search the Web (open internet)",
        "ajuda_fonte_web": (
            "Adds internet search (DuckDuckGo, no API key) to the "
            "other sources. It works with any source option, including "
            "'General knowledge'. When off, the assistant stays 100% "
            "local and works without internet."
        ),
        "fonte_openalex": "📚 OpenAlex (international papers)",
        "ajuda_fonte_openalex": (
            "Queries OpenAlex filtering Geology, Geochemistry and "
            "Mining Engineering and sorting by relevance. The question "
            "is translated to English by the PT↔EN bilingual layer; "
            "title, authors, year, abstract and DOI appear in the "
            "status and in the source cards."
        ),
        "fonte_intl_geo": "🌐 International Geological Surveys",
        "ajuda_fonte_intl_geo": (
            "Turns on the unified group of public geological survey "
            "services with no API key: OneGeology, USGS ScienceBase, "
            "NRCan/GSC (Canada), EGDI (EU), Geoscience Australia/GSQ, "
            "GSJ/AIST (Japan), GeoNet/GNS (New Zealand), CGS/Digital "
            "Earth Africa, NGD (Saudi Arabia) and GSI/Bhukosh WFS "
            "(India). When turned on, choose exactly which "
            "regions/services to search."
        ),
        "fonte_geosgb": "🗺️ SGB / Mineral Occurrences (GeoSGB)",
        "ajuda_fonte_geosgb": (
            "Queries the Geological Survey of Brazil geological "
            "occurrence and deposit registry (GeoSGB WFS) and returns "
            "the mineral occurrences in the area. The commodity (gold, "
            "copper, rare earths, niobium...) and the state are "
            "extracted from the question. Each occurrence brings "
            "target, commodity, status, municipality/state, map sheet "
            "and coordinates, with no API key. It is a geological "
            "database, distinct from ANM mining processes."
        ),
        "fonte_anm": "⛏️ ANM / Mining Processes (SIGMINE)",
        "ajuda_fonte_anm": (
            "Queries the active mining processes, applications and "
            "claims of the National Mining Agency in SIGMINE (public "
            "ArcGIS REST and WFS). The commodity (gold, rare earths, "
            "tin...), the holder or the state come from the question. "
            "Each process brings number, year, current phase, holder, "
            "commodity, area in hectares and state, with no API key. It "
            "is the regulatory registry, distinct from the SGB/GeoSGB "
            "geological occurrences."
        ),
        "fonte_macrostrat": "🧱 Macrostrat (Stratigraphy & Ages)",
        "ajuda_fonte_macrostrat": (
            "Queries the public Macrostrat REST API and returns "
            "lithostratigraphic units with geological age (in Ma), main "
            "lithology and depositional environment. It uses the "
            "coordinates mentioned in the question (or in a local "
            "document) and, without them, the named unit. No API key."
        ),
        "fonte_siagas": "🚰 SIAGAS / RIMAS (Wells & Groundwater)",
        "ajuda_fonte_siagas": (
            "Queries the public Geological Survey of Brazil WFS and "
            "returns SIAGAS/RIMAS water wells: point code, "
            "municipality/state, depth, static and dynamic levels, "
            "flow rate, tapped aquifer and coordinates. The "
            "municipality and state come from the question, with no API "
            "key. With ANA on, the answer cross-references groundwater "
            "and surface water."
        ),
        "fonte_geossit": "🏞️ INDE / GEOSSIT (Geological Heritage)",
        "ajuda_fonte_geossit": (
            "Queries the public GEOSSIT/INDE (SGB) layers and returns "
            "geosites and geodiversity sites: name, main interest "
            "(stratigraphic, palaeontological, geomorphological, "
            "mineralogical, tectonic...), municipality/state, "
            "relevance (national/international) and coordinates. No "
            "API key."
        ),
        # -- Sidebar: analytical profile ----------------------------
        "secao_perfil": "🧠 Analytical Profile & System Prompt",
        "modo_analise": "Analysis mode",
        "ajuda_modo_analise": (
            "Each mode adds geoscientific instructions to the system "
            "prompt base text. Switching modes replaces the previous "
            "profile block and preserves the rest of the text."
        ),
        "perfil_personalizado_texto": (
            "✏️ In custom mode the instruction is exactly the text "
            "written in the edit box: no automatic block is added, and "
            "the editor opens focused below."
        ),
        "editar_prompt": "✏️ Edit system prompt",
        "ajuda_editar_prompt": (
            "Opens editing of the text sent to the model in every "
            "query."
        ),
        "texto_edicao": (
            "Changes apply to the next questions, even before they are "
            "saved to the file."
        ),
        "rotulo_prompt_ativo": (
            "Active system prompt (prompts/system_base.txt)"
        ),
        "ajuda_prompt_ativo": (
            "Base text sent to the model, already with the instructions "
            "of the selected analysis mode. Source instructions are "
            "added automatically by the system."
        ),
        "botao_salvar_padrao": "Save as default",
        "botao_restaurar": "Restore original",
        "expander_ver_prompt": "👁️ View active prompt",
        "texto_ver_prompt": (
            "{n} characters. Source instructions are added to this text "
            "on every query."
        ),
        "aviso_prompt_salvo": (
            "System prompt saved to prompts/system_base.txt."
        ),
        "aviso_prompt_erro": (
            "Could not save the system prompt: {erro}"
        ),
        "aviso_prompt_restaurado": (
            "Content of prompts/system_base.txt restored."
        ),
        # -- Sidebar: advanced settings -----------------------------
        "config_avancadas": "⚙️ Advanced Settings",
        "modelo_ollama": "Ollama model",
        "ajuda_modelo_ollama": (
            "Models installed in the local Ollama. Smaller models answer "
            "faster; larger ones are more detailed."
        ),
        "limite_rigeo": "RIGeo article limit",
        "ajuda_limite_rigeo": (
            "Maximum number of SGB studies returned by RIGeo."
        ),
        "comunidade_rigeo": "SGB community",
        "ajuda_comunidade_rigeo": (
            "Restricts the RIGeo search to one collection community."
        ),
        "refinar_termos": "Refine search terms with Ollama",
        "ajuda_refinar_termos": (
            "Before querying RIGeo, asks the model for a short list of "
            "search terms (2 to 4 words). It speeds up the answer a lot "
            "but costs an extra call to Ollama; if the model fails, "
            "stopword removal takes over. The term used appears in each "
            "query status."
        ),
        "rodape_modelo": (
            f"{APP_DISPLAY_NAME} · Active model: {{modelo}} · "
            "Indexed documents: {documentos}"
        ),
        "encerrar_servidor": "⏻ Shutdown server / Exit",
        "ajuda_encerrar_servidor": (
            "Stops the application's local server and frees the port. "
            "History already saved is preserved."
        ),
        "aviso_encerrando_servidor": (
            "Shutting down the server... you can close this tab now."
        ),
        "spinner_ollama": "Starting the Ollama service...",
        # -- Chat ---------------------------------------------------
        "novo_chat": "➕ New Chat",
        "ajuda_novo_chat": (
            "Saves the current conversation to history and opens a "
            "blank conversation. Indexed documents remain active."
        ),
        "chat_placeholder": "Type your question...",
        "status_analisando": "Analyzing the question and searching sources",
        "status_fontes": " ({fontes})",
        "status_concluida": "Query completed · {intencao}",
        "status_erro": "The query could not be completed.",
        "erro_consulta": (
            "The query could not be completed. Check the selected "
            "service."
        ),
        "fonte_legenda": "Source: {fonte}",
        "roteamento_legenda": " · Routing: {intencao}",
        # -- Per-step progress and cancellation (Phase D3a) ---------
        "progresso_titulo": "Query progress",
        "progresso_etapa_atual": "Current step: {etapa}",
        "progresso_texto_parcial": "Streaming answer preview",
        "progresso_aguardando": "Waiting for the query to start...",
        "botao_cancelar_consulta": "Cancel query",
        "ajuda_cancelar_consulta": (
            "Interrupts the running query. The partial answer and temporary "
            "files are discarded and no message is saved to history."
        ),
        "consulta_em_andamento": (
            "A query is already running. Cancel it or wait for it to finish "
            "before sending another question."
        ),
        "cancelamento_solicitado": (
            "Query cancelled. No answer was saved to history and the "
            "temporary conversion files were removed."
        ),
        "status_cancelado": "Query cancelled.",
        "progresso_etapa_preparando": "Preparing the query",
        "progresso_etapa_roteamento": "Classifying the question intent",
        "progresso_etapa_sgb": "Querying RIGeo / SGB",
        "progresso_etapa_documentos": "Searching the local document base",
        "progresso_etapa_documentos_consultas": (
            "Generating the bilingual document queries"
        ),
        "progresso_etapa_documentos_indice": "Indexing the local documents",
        "progresso_etapa_documento_pagina": "Converting document pages",
        "progresso_etapa_documento_ocr": "Running OCR on scanned pages",
        "progresso_etapa_ana": "Querying ANA / HidroWeb",
        "progresso_etapa_web": "Searching the open web",
        "progresso_etapa_openalex": "Querying OpenAlex",
        "progresso_etapa_usgs": "Querying USGS ScienceBase",
        "progresso_etapa_intl_geo": (
            "Querying the international geological surveys"
        ),
        "progresso_etapa_geosgb": "Querying GeoSGB / SGB",
        "progresso_etapa_anm": "Querying ANM / SIGMINE",
        "progresso_etapa_macrostrat": "Querying Macrostrat",
        "progresso_etapa_siagas": "Querying SIAGAS / RIMAS",
        "progresso_etapa_geossit": "Querying INDE / GEOSSIT",
        "progresso_etapa_llm": "Generating the answer with Ollama",
        "progresso_etapa_concluida": "Query completed",
        "progresso_etapa_cancelando": "Cancelling the query...",
        "progresso_etapa_cancelada": "Query cancelled",
        "progresso_etapa_erro": "The query failed",
        # -- Query status details -----------------------------------
        "status_intencao": "Intent: {intencao}",
        "status_intencao_padrao": "defined in the sidebar",
        "status_decisao": "Decision made by: {origem}",
        "status_busca_bilingue": (
            "**Bilingual local search (PT-BR ↔ EN)**"
        ),
        "status_idioma_detectado": (
            "Language detected in the question: {idioma}"
        ),
        "status_idioma_nao_identificado": (
            "Question language not identified"
        ),
        "status_origem_llm": "terms from Ollama",
        "status_origem_fallback": "deterministic fallback (glossary)",
        "status_origem_identica": "original question",
        "status_query": "- {lingua} query: `{texto}`",
        "status_amostragem": (
            "Overview question or weak search: representative sampling "
            "was used (beginning, central sections and conclusions) to "
            "cover the files in full."
        ),
        "status_trechos": (
            "{recuperados} excerpt(s) by keyword · {amostrados} by "
            "representative sampling."
        ),
        "status_termo_rigeo_vazio": (
            "Term searched in RIGeo: the question has no usable "
            "geoscientific terms; the search used the original question."
        ),
        "status_termos_ollama": " · terms defined by Ollama",
        "status_plano_rigeo": "RIGeo search plan: {plano}",
        "status_artigos_rigeo": "**RIGeo articles retrieved ({n})**",
        "status_titulo_nao_informado": "Title not provided",
        "status_trechos_documentos": (
            "{n} local document excerpt(s) used in the answer."
        ),
        "status_estacoes_recuperadas": (
            "**Stations retrieved from {fonte} ({n})**"
        ),
        "status_ana_vazio": (
            "{fonte}: no station found for {recorte}."
        ),
        "status_anm_recuperados": (
            "Mining processes retrieved from ANM / SIGMINE"
        ),
        "status_macrostrat_recuperadas": (
            "Lithostratigraphic units retrieved from Macrostrat"
        ),
        "status_siagas_recuperados": (
            "Wells retrieved from SIAGAS / RIMAS"
        ),
        "status_geossit_recuperados": (
            "Geosites retrieved from INDE / GEOSSIT"
        ),
        "status_paginas_web": (
            "**Pages retrieved from the open web ({n})**"
        ),
        "status_pagina_sem_titulo": "Untitled page",
        "status_termo_ingles": 'English term sent to {base}: "{termo}"',
        "status_publicacoes": (
            "**Publications retrieved from {base} ({n})**"
        ),
        "status_registro_sem_titulo": "Untitled record",
        "status_intl_recuperados": (
            "**International geological surveys retrieved ({n})**"
        ),
        "status_vazio_registro": "no record found.",
        # -- Quick guide --------------------------------------------
        "guia_titulo": f"#### 🧭 How to use {APP_NAME}",
        "guia_intro": (
            "The assistant cross-references the local documents you "
            "upload with Brazilian and international public databases, "
            "from the RIGeo/SGB collection to hydrogeological, mining "
            "and scientific catalogues."
        ),
        "guia_passo_1_titulo": "1. 📄 Add Local Documents (Optional)",
        "guia_passo_1_texto": (
            "In the sidebar, upload reports, drilling logs or papers in "
            "PDF, MD or TXT. The system indexes the text, runs OCR when "
            "needed and enables table extraction."
        ),
        "guia_passo_2_titulo": "2. 🗂️ Turn On the Desired Databases",
        "guia_passo_2_texto": (
            "Enable the toggles of the Brazilian databases you want to "
            "cross-reference — RIGeo, ANA / HidroWeb, SIAGAS / RIMAS, "
            "SGB / GeoSGB, ANM / SIGMINE and INDE / GEOSSIT — and the "
            "international ones: Macrostrat, OpenAlex and International "
            "Geological Surveys. In the latter, choose exactly which "
            "services/countries to search: OneGeology, USGS/USA, "
            "Canada, Europe, Australia, Japan, New Zealand, Africa, "
            "Saudi Arabia or India."
        ),
        "guia_passo_3_titulo": "3. 🧠 Choose the Analytical Profile",
        "guia_passo_3_texto": (
            "Select the technical interpretation lens (e.g. Regional "
            "Geology, Mineral Exploration & Geochemistry, "
            "Hydrogeology, Geotechnics) or edit the System Prompt "
            "according to the study objective."
        ),
        "guia_passo_4_titulo": "4. 📊 Explore Results, Maps and Tables",
        "guia_passo_4_texto": (
            "Ask your question in the field below. Whenever there are "
            "coordinates, CIM sheets or tabular data, the assistant "
            "automatically builds the interactive spatial map and lets "
            "you export spreadsheets (.csv / .xlsx)."
        ),
        "guia_combinacao_titulo": (
            "🧩 Source Combination Tips by Query Type"
        ),
        "guia_combinacao_intro": (
            "Recommended combinations for each research objective:"
        ),
        "guia_combinacao_1_titulo": (
            "🌍 Global Reviews, Metallogeny and International Literature"
        ),
        "guia_combinacao_1_texto": (
            "Enable International Geological Surveys + OpenAlex "
            "(international scientific papers) + Macrostrat together to "
            "cross-reference field occurrences with peer-reviewed "
            "scientific literature."
        ),
        "guia_combinacao_2_titulo": (
            "🇧🇷 Official Brazilian Data (Maps, Wells, Mining and "
            "Hydrology)"
        ),
        "guia_combinacao_2_texto": (
            "Combine SGB / RIGeo, GeoSGB (Mineral Occurrences), "
            "ANM / SIGMINE, ANA / HidroWeb and SIAGAS."
        ),
        "guia_combinacao_3_titulo": (
            "🌋 Seismicity and Active Volcanism"
        ),
        "guia_combinacao_3_texto": (
            "Select GeoNet / GNS (New Zealand), GSJ / AIST (Japan) or "
            "USGS in the international regions selector."
        ),
        "guia_combinacao_4_titulo": (
            "📄 Your Own Documents (Reports, Theses and Assessments)"
        ),
        "guia_combinacao_4_texto": (
            "Enable Local Document Base (PDF/MD/TXT) to cross-reference "
            "your files with the public databases."
        ),
        "guia_dica": (
            "Tip: mention municipality/state, a mineral commodity, a "
            "geological unit or a CIM sheet code — e.g. 'rare earths in "
            "Apuí/AM' or 'SIAGAS wells in Manaus/AM' — to trigger the "
            "spatial filters automatically."
        ),
        # -- Sources expander ---------------------------------------
        "fontes_expander": "📚 Sources and Metadata Consulted",
        "roteamento_caption": "Routing: {intencao}",
        "termo_rigeo": 'Term searched in RIGeo: "{termo}"',
        "termo_web": 'Term searched on the Web: "{termo}"',
        "termo_internacional": 'Term searched in {bases}: "{termo}"',
        "sem_fontes": "No external source was queried in this answer.",
        "artigos_rigeo": "**RIGeo articles ({n})**",
        "estacoes_ana": "**{fonte} stations ({n})**",
        "ocorrencias_geosgb": "**GeoSGB mineral occurrences ({n})**",
        "processos_anm": "**ANM / SIGMINE mining processes ({n})**",
        "unidades_macrostrat": (
            "**Lithostratigraphic units (Macrostrat) ({n})**"
        ),
        "pocos_siagas": "**SIAGAS / RIMAS wells ({n})**",
        "geossitios_inde": "**INDE / GEOSSIT geosites ({n})**",
        "paginas_web": "**Open web pages ({n})**",
        "openalex_titulo": "**OpenAlex ({n})**",
        "servicos_intl": "**International Geological Surveys ({n})**",
        "usgs_sciencebase": "**USGS ScienceBase ({n})**",
        "documentos_locais_consultados": (
            "**Local documents consulted ({n})**"
        ),
        "termo_intl_consultado": 'International term queried: "{termo}"',
        "servico_generico": "International geological survey",
        "vazio_geosgb": "GeoSGB: {motivo}",
        "vazio_anm": "ANM / SIGMINE: {motivo}",
        "vazio_macrostrat": "Macrostrat: {motivo}",
        "vazio_siagas": "SIAGAS / RIMAS: {motivo}",
        "vazio_geossit": "INDE / GEOSSIT: {motivo}",
        "vazio_web": "Web: {motivo}",
        "vazio_openalex": "OpenAlex: {motivo}",
        "vazio_intl": "International Geological Surveys: {motivo}",
        "vazio_usgs": "USGS ScienceBase: {motivo}",
        "motivo_geosgb": "no occurrence found.",
        "motivo_anm": "no process found.",
        "motivo_macrostrat": "no unit found.",
        "motivo_siagas": "no well found.",
        "motivo_geossit": "no geosite found.",
        "motivo_web": "no page found.",
        "motivo_openalex": "no record found.",
        "motivo_intl": "no record found.",
        "motivo_usgs": "no record found.",
        "link_abrir_macrostrat": "🔗 Open Macrostrat",
        "link_ficha_unidade": "📄 Unit sheet",
        "link_abrir_siagas": "🔗 Open SIAGAS",
        "link_ficha_poco": "📄 Well sheet",
        "link_abrir_geossit": "🔗 Open GEOSSIT",
        "link_ficha_geossitio": "📄 Geosite sheet",
        "link_abrir_openalex": "🔗 Open in OpenAlex",
        "link_abrir_servico": "🔗 Open in the geological survey",
        "link_ficha_sciencebase": "🔗 ScienceBase sheet",
        "ultimo_evento": "Last event: {evento}",
        "aviso_servicos_intl": "International surveys: {aviso}",
        "link_series_historicas": "🔗 Historical series",
        "link_abrir_pagina": "🌐 Open page",
        "link_abrir_geosgb": "🔗 Open GeoSGB",
        "link_abrir_sigmine": "🔗 Open SIGMINE",
        "link_abrir_pdf": "📄 Open PDF",
        "link_ficha_rigeo": "🔗 RIGeo record",
        "resumo_rapido_expander": "📈 Quick Statistical Summary",
        # -- Router intents -----------------------------------------
        "intencao_local": "local documents only",
        "intencao_rigeo": "RIGeo (SGB) only",
        "intencao_hibrido": "local documents + RIGeo",
        "intencao_ana": "ANA/HidroWeb stations only",
        "intencao_geral": "general knowledge",
        # -- Spatial map --------------------------------------------
        "mapa_expander": (
            "🗺️ Spatial View of Cited Areas and Points ({n} features)"
        ),
        "mapa_camadas": "Layers displayed",
        "ajuda_mapa_camadas": (
            "Isolate, for example, only SIAGAS wells and ANA stations, "
            "or only SGB occurrences with ANM processes."
        ),
        "mapa_sem_feicoes": (
            "No feature in the selected layers. Choose at least one "
            "layer above."
        ),
        "mapa_alt": (
            "Map with {n} geographic point(s) from the sources "
            "consulted in this answer."
        ),
        "mapa_tabela_alt": (
            "Table with name, layer, coordinates, CIM sheet, bounds and "
            "detail for each feature shown on the map."
        ),
        "col_nome": "Name",
        "col_camada": "Layer",
        "col_latitude": "Latitude",
        "col_longitude": "Longitude",
        "col_folha_cim": "CIM sheet",
        "col_limites": "Bounds (bounding box)",
        "col_detalhe": "Detail",
        "outras_fontes": "Other sources",
        "baixar_pontos": "📥 Download Points (CSV for QGIS)",
        "ajuda_baixar_pontos": (
            "UTF-8 CSV with ';' separator and decimal point in the "
            "coordinates: opens directly as a delimited layer in QGIS "
            "and as a spreadsheet in Excel."
        ),
        "mapa_rodape": (
            "{exibidas} of {total} feature(s) shown · "
            "{camadas_ativas} of {camadas} layer(s) active."
        ),
        # -- Technical report ---------------------------------------
        "parecer_expander": "📄 Export Technical Report",
        "parecer_texto": (
            "Document with an institutional header, scope, analysis, "
            "spatial synthesis and references in the ABNT NBR 6023 "
            "standard."
        ),
        "consulta_historico": "Query recorded in the history",
        "word_indisponivel": "Word unavailable",
        "parecer_erro_word": (
            "The Word file for this answer could not be generated."
        ),
        "baixar_parecer_docx": "📥 Download Technical Report (.docx)",
        "ajuda_parecer_docx": (
            "Word with native tables, institutional header, numbered "
            "footer and ABNT references."
        ),
        "parecer_erro_md": (
            "The Markdown file for this answer could not be generated."
        ),
        "baixar_relatorio_md": "📝 Download Report (.md)",
        "ajuda_relatorio_md": (
            "Markdown-structured version, ready for editing or version "
            "control."
        ),
        "parecer_rodape": (
            "Analytical profile: {perfil} · {grupos} source group(s) · "
            "{feicoes} spatial feature(s)."
        ),
        # -- Spreadsheets and tables --------------------------------
        "dados_expander": "📊 Data Extraction & Exploration",
        "dados_caption": (
            "Markdown tables and grids from local documents, plus the "
            "records of the APIs used in the conversation. Automatic "
            "typing, filters and download as CSV and Excel."
        ),
        "dados_spinner": "Extracting tables from local documents...",
        "dados_falhas_leitura": (
            "{n} document(s) could not be read for table extraction."
        ),
        "dados_sem_tabelas": (
            "No tabular block was recognized in the indexed documents "
            "or in the sources of this conversation."
        ),
        "dados_contagem": (
            "{documentos} table(s) from documents · {sessao} table(s) "
            "from session sources."
        ),
        "dados_tabela_rotulo": "Extracted table",
        "dados_origem": (
            "**{titulo}** · origin: {origem} · page: {pagina} · "
            "{linhas} row(s) × {colunas} column(s)"
        ),
        "dados_unidades": "Units: {unidades}",
        "dados_visualizacao": "View",
        "dados_tipados": "Typed data (numeric)",
        "dados_brutos": "Original data (raw)",
        "dados_busca_coluna": "Text search by column",
        "dados_sem_busca": "No search",
        "dados_texto_procurado": "Search text",
        "dados_placeholder_busca": "e.g. gold, AM, 2023",
        "dados_filtrar_faixa": "Filter by numeric range",
        "dados_ajuda_faixa": (
            "The range is applied to the typed table and also applies "
            "to the original data view."
        ),
        "dados_coluna_numerica": "Numeric column",
        "dados_faixa": "Value range",
        "dados_sem_numericos": (
            "The selected column has no numeric values."
        ),
        "dados_valor_unico": "Single value in the column: {valor}",
        "dados_sem_coluna_numerica": (
            "No typed numeric column in this table."
        ),
        "exportacao_caption": (
            "The export includes the rows after the active filters. No "
            "temporary file is written to disk."
        ),
        "baixar_csv": "Download CSV",
        "ajuda_csv_dados": (
            "UTF-8 with BOM, ';' separator and comma decimal: opens "
            "directly in Excel and QGIS."
        ),
        "baixar_excel": "Download Excel",
        "ajuda_excel": (
            "'Data' (typed), 'Raw data' and origin 'Metadata' sheets, "
            "with a formatted header."
        ),
        "excel_indisponivel": "Excel unavailable",
        "resumo_numerico_alt": "Statistical summary of numeric columns",
        "resumo_colunas_alt": (
            "Count of null and unique values per column"
        ),
        "resumo_coluna": "Column",
        "resumo_contagem": "Count",
        "resumo_media": "Mean",
        "resumo_desvio": "Standard deviation",
        "resumo_minimo": "Minimum",
        "resumo_mediana": "Median",
        "resumo_maximo": "Maximum",
        "resumo_tipo": "Type",
        "resumo_nulos": "Nulls",
        "resumo_unicos": "Unique",
        "resumo_linhas_colunas": (
            "{linhas} row(s) in the original table · {colunas} "
            "column(s) in the typed table."
        ),
        # -- Output contract governance (Phase D1) --------------------
        "governanca_motivo_texto_livre": (
            "Free-form output detected: the answer was preserved but "
            "requires human review."
        ),
        "governanca_motivo_resposta_vazia": (
            "The model returned an empty answer."
        ),
        "governanca_motivo_contrato_invalido": (
            "The output contract is incomplete or malformed."
        ),
        "governanca_motivo_observado_sem_evidencia": (
            "An OBSERVED claim without evidence_id was downgraded to "
            "INFERRED."
        ),
        "governanca_motivo_evidencia_desconhecida": (
            "The cited evidence is not in the catalog and the link was "
            "removed."
        ),
        "governanca_motivo_classificacao_desconhecida": (
            "Unrecognized claim classification; treated as INFERRED."
        ),
        "governanca_motivo_veredito_invalido": (
            "The verdict declared by the model is invalid."
        ),
        "governanca_motivo_falha_declarada": (
            "The model declared a FAIL verdict."
        ),
        "governanca_motivo_veredito_hold": (
            "The model declared a HOLD verdict."
        ),
        "governanca_motivo_fonte_timeout": (
            "Timed out while querying the source."
        ),
        "governanca_motivo_fonte_tls": (
            "TLS/certificate failure while querying the source."
        ),
        "governanca_motivo_fonte_rede": (
            "Network failure while querying the source."
        ),
        "governanca_motivo_fonte_http": (
            "The source returned HTTP error {status}."
        ),
        "governanca_motivo_fonte_indisponivel": (
            "The source is unavailable; the result requires a retry."
        ),
        "governanca_motivo_contrato_valido": (
            "Valid contract: every OBSERVED claim has evidence."
        ),
        # -- D4 workstation: adaptive layout and epistemic semantics ----
        "aba_sintese": "🧠 Technical Synthesis",
        "aba_mapa_workstation": "🗺️ Spatial Map",
        "aba_dados_exportacao": "📊 Data & Export",
        "workstation_indicadores": "Indicators",
        "workstation_fontes_ativas": "Active sources",
        "workstation_alvos_cim": "CIM targets / sheets",
        "workstation_governanca_titulo": "Epistemic governance",
        "workstation_sem_afirmacoes": (
            "No audited claim yet. The OBSERVED x INFERRED ratio appears "
            "with the first response."
        ),
        "workstation_rastreabilidade_titulo": (
            "Traceability & Governance"
        ),
        "workstation_evidencias_alt": (
            "Ranked table of the cited evidence_id values"
        ),
        "workstation_coluna_evidencia": "evidence_id",
        "workstation_coluna_citacoes": "Citations",
        "workstation_coluna_aderencia": "Adherence",
        "workstation_ajuda_aderencia": (
            "Share of OBSERVED citations for this evidence_id."
        ),
        "workstation_sem_evidencias": (
            "No evidence_id cited in this conversation's responses."
        ),
        "workstation_motor_titulo": "Governance & Engine",
        "workstation_modo_online": "Online mode",
        "workstation_modo_offline": "Offline mode",
        "workstation_modelo_ativo": "Active model: {modelo}",
        "workstation_modelo_fallback": "local fallback",
        "workstation_criterios": "Classification criteria",
        "workstation_criterio_observed": (
            "OBSERVED: anchored in evidence_id/traceable source."
        ),
        "workstation_criterio_inferred": (
            "INFERRED: interpretive synthesis by the model."
        ),
        "workstation_resumo_proporcao": (
            "OBSERVED {observed:.1f}% · INFERRED {inferred:.1f}%"
        ),
        "workstation_mapa_vazio": (
            "No point or CIM sheet detected in this conversation."
        ),
        "workstation_mapa_contagem": (
            "{n} point(s) and sheet(s) on the map."
        ),
        "workstation_mapa_alt": (
            "Spatial map with {n} detected feature(s)"
        ),
        "workstation_mapa_tabela_alt": (
            "Tabular preview of the map features"
        ),
        "workstation_coluna_nome": "Name",
        "workstation_coluna_camada": "Layer",
        "workstation_coluna_folha": "CIM sheet",
        "workstation_baixar_csv": "Download map CSV",
        "workstation_cim_ferramentas": "CIM tools and offline package",
        # -- D1 sidebar: service, network, persistence and history ------
        "secao_servico": "⚙️ Local service",
        "servico_ollama_online": "Ollama online · {modelo}",
        "servico_ollama_offline": "Ollama offline · {modelo}",
        "servico_modelo_ativo": "Active model: {modelo}",
        "servico_roteador": "Router: local SLM (Ollama)",
        "servico_roteador_regra": "Router: deterministic local rule",
        "servico_roteador_fallback": "Router: deterministic fallback",
        "servico_roteador_pendente": "Router: waiting for the first query",
        "ajuda_servico_roteador": (
            "Origin of the last routing decision. The router uses the "
            "local SLM when it answers and falls back to a deterministic "
            "rule/heuristic when Ollama is unavailable."
        ),
        "ajuda_servico_ollama": (
            "Ollama service state, queried at /api/version."
        ),
        "rede_online": "🌐 Online",
        "rede_cache_folha_cim": "🗂️ Offline cache by CIM sheet",
        "rede_offline_sem_cache": "⚠️ Offline with no CIM cache",
        "rede_cache_folhas": "{n} CIM sheet(s) in local cache",
        "ajuda_rede_online": (
            "The local service is reachable; external sources can be "
            "queried."
        ),
        "ajuda_rede_cache": (
            "No connection right now: answers use the spatial cache by "
            "CIM sheet and the connectors' local caches."
        ),
        "dados_diretorio": "Persistence: {caminho}",
        "dados_origem_env": "source: ASSISTENTE_DATA_DIR",
        "dados_origem_localappdata": "source: %LOCALAPPDATA%\\NexusGeoIA",
        "dados_origem_projeto": "source: application folder",
        "ajuda_dados_diretorio": (
            "Writable directory reserved for the SQLite database, "
            "documents and caches. Set ASSISTENTE_DATA_DIR to move it."
        ),
        "sidebar_nova_conversa": "➕ New Conversation",
        "ajuda_sidebar_nova_conversa": (
            "Saves the current conversation to SQLite and opens a blank "
            "one without deleting documents or history."
        ),
        "historico_workflow_marcador": "Workflow: {workflow}",
        "historico_folha_marcador": "CIM sheet: {folha}",
        "historico_sqlite_erro": (
            "The SQLite history could not be read; the list may be "
            "incomplete."
        ),
        "aviso_historico_salvar_erro": (
            "The conversation could not be saved to the local database."
        ),
        "aviso_historico_excluir_erro": (
            "The conversation could not be deleted from the local database."
        ),
        # -- Tab 1 (Query & Evidence) ----------------------------------
        "workflow_titulo": "🧭 Workflow",
        "workflow_ajuda": (
            "Explicit workflow choice before sending the question. The "
            "workflow is recorded in every answer and in the history."
        ),
        "workflow_consulta_direta": "Direct Query",
        "workflow_triagem_area": "Area Screening / Mineral Viability",
        "workflow_hidrogeologia": "Hydrogeology",
        "workflow_sondagem": "Drilling & Lithology",
        "workflow_caption": (
            "Active workflow: {workflow}. The decision is recorded in "
            "the answer and in the history."
        ),
        "workflow_instrucao_consulta_direta": (
            "Workflow: Direct Query. Answer objectively, without extra "
            "screening steps."
        ),
        "workflow_instrucao_triagem_area": (
            "Workflow: Area Screening / Mineral Viability. Structure the "
            "answer into geological context, evidence, mineral viability "
            "and data gaps."
        ),
        "workflow_instrucao_hidrogeologia": (
            "Workflow: Hydrogeology. Prioritize aquifers, wells, flow "
            "rates and the link between surface and groundwater."
        ),
        "workflow_instrucao_sondagem": (
            "Workflow: Drilling & Lithology. Prioritize lithology, depth, "
            "core samples and correlation between sections."
        ),
        "workflow_badge": "🧭 {workflow}",
        "governanca_veredito_pass": "PASS · valid contract",
        "governanca_veredito_hold": "HOLD · review required",
        "governanca_veredito_fail": "FAIL · non-compliant",
        "governanca_badge_observed": "OBSERVED · {n}",
        "governanca_badge_inferred": "INFERRED · {n}",
        "governanca_motivo": "Objective reason: {motivo}",
        "governanca_sem_afirmacoes": (
            "The answer brought no structured claims; the verdict "
            "follows the contract rule."
        ),
        "governanca_afirmacoes": "Auditable claims ({n})",
        "governanca_evidencia": "Evidence",
        "governanca_ajuda": (
            "Verdict computed by core/governance.py from the output "
            "contract; it never shows a traceback in the interface."
        ),
        "governanca_coluna_afirmacao": "Claim",
        "governanca_coluna_classificacao": "Classification",
        "governanca_coluna_evidencia": "evidence_id",
        "proveniencia_expander": "🧾 Answer provenance",
        "proveniencia_contagem": "{n} traced evidence item(s)",
        "proveniencia_vazia": (
            "No traceable source was recorded for this answer."
        ),
        "proveniencia_ajuda": (
            "Structured lineage table: source type, locator, collection "
            "date and whether the data came live or from the offline cache."
        ),
        "proveniencia_origem_live": "Live",
        "proveniencia_origem_cache": "Cache Offline",
        "proveniencia_origem_local": "Local",
        "proveniencia_truncada": (
            "Showing {n} of {total} traced evidence items."
        ),
        # -- Main-area tabs (Phase D2) ------------------------------
        "aba_consulta": "💬 Query & Evidence",
        "aba_espacial": "🧭 Spatial Resolution",
        "aba_dados": "📊 Data & Export",
        "aba_sondagem": "🧪 Drilling & Lithology",
        # -- Tab 4: De-To drilling grid (Phase D3b) ------------------
        "sondagem_titulo": "De–To drilling grid",
        "sondagem_caption": (
            "Paste a table of holes and intervals with Portuguese or "
            "English headers. The parser recognizes De/Até, Prof. de/até, "
            "Intervalo, From/To, Furo/Hole and Litologia/Lithology, "
            "normalizes comma and dot decimals, converts m/cm and keeps "
            "invalid rows in the report without discarding valid "
            "intervals."
        ),
        "sondagem_texto_rotulo": "Drilling table (pasted CSV/TSV)",
        "sondagem_texto_ajuda": (
            "Separator ';', tab, comma or '|'. Use a decimal comma with "
            "the ';' separator to avoid ambiguity. The Unit column "
            "accepts m or cm and the header may also declare it, as in "
            "'From (cm)' or 'Interval (m)'. A unit written in the cell "
            "takes precedence; 'Interval' accepts '0 - 1.5 m', "
            "'0 to 1.5' and '0 até 1.5 m'."
        ),
        "sondagem_exemplo": (
            "Hole;From (m);To (m);Unit;Lithology;Sample;Remarks\n"
            "BH-01;0.00;2.50;;Topsoil;S-01;Surface\n"
            "BH-01;2.50;5.00;;Saprolite;S-02;\n"
            "BH-01;5.00;8.00;;Weathered rock;S-03;\n"
            "BH-02;0;150;cm;Colluvial soil;S-04;\n"
            "BH-02;150;300;cm;Granite;S-05;\n"
        ),
        "sondagem_analisar": "Analyze grid",
        "sondagem_limpar": "Clear result",
        "sondagem_erro_cabecalhos": (
            "Required headers were not recognized: {campos}. Use "
            "Hole/Furo and From/To or a Depth interval column. The unit "
            "may appear in parentheses, as in 'From (cm)'."
        ),
        "sondagem_erro_tabela_vazia": (
            "The table is empty. Paste the holes and De–To intervals."
        ),
        "sondagem_erro_sem_linhas": (
            "No data row was found after the header."
        ),
        "sondagem_erro_cabecalhos_ausentes": (
            "For a list of values, provide the headers as well."
        ),
        "sondagem_erro_leitura": (
            "The drilling table could not be read. Check the separator "
            "and the headers."
        ),
        "sondagem_erro_tabela_desalinhada": (
            "Rows {linhas} have a different number of fields than the "
            "header. Check the separator: with a decimal comma, use "
            "';', tab or '|' so no extra columns are created."
        ),
        "sondagem_erro_tempo_excedido": (
            "The analysis exceeded the {segundos} time limit and was "
            "stopped without producing a partial grid. Reduce the table "
            "or split the holes into batches."
        ),
        "sondagem_erro_cancelada": (
            "Analysis cancelled. The previous grid, when present, was "
            "preserved."
        ),
        "sondagem_sucesso": (
            "{n} valid interval(s) in {furos} hole(s)."
        ),
        "sondagem_metric_intervalos": "Valid intervals",
        "sondagem_metric_invalidos": "Invalid rows",
        "sondagem_metric_sobreposicoes": "Overlaps",
        "sondagem_metric_lacunas": "Gaps",
        "sondagem_aviso_invalidos": (
            "{n} invalid row(s) were kept in the report and are not part "
            "of the main grid."
        ),
        "sondagem_aviso_sobreposicoes": (
            "{n} depth overlap(s) detected."
        ),
        "sondagem_aviso_lacunas": (
            "{n} gap(s) between consecutive intervals detected."
        ),
        "sondagem_filtros": "Grid filters",
        "sondagem_filtro_furo": "Hole",
        "sondagem_filtro_todos_furos": "All holes",
        "sondagem_filtro_litologia": "Lithology",
        "sondagem_filtro_situacao": "Status",
        "sondagem_filtro_busca": "Text search",
        "sondagem_busca_placeholder": "e.g. granite, S-01, saprolite",
        "sondagem_grade_alt": (
            "De–To grid with {n} drilling interval(s)."
        ),
        "sondagem_contagem_exibida": (
            "{exibidos} of {total} interval(s) displayed."
        ),
        "sondagem_sem_resultado_filtro": (
            "No interval matches the selected filters."
        ),
        "sondagem_invalidos_titulo": "Invalid rows ({n})",
        "sondagem_invalidos_alt": (
            "Invalid-row report with line number, hole, original depths "
            "and reason."
        ),
        "sondagem_sobreposicoes_titulo": "Overlaps ({n})",
        "sondagem_sobreposicoes_alt": (
            "Intervals that run into the previous interval of the same "
            "hole, with the overlap thickness."
        ),
        "sondagem_lacunas_titulo": "Gaps ({n})",
        "sondagem_lacunas_alt": (
            "Gaps between consecutive intervals of the same hole, with "
            "the gap thickness."
        ),
        "sondagem_coluna_linha": "Line",
        "sondagem_coluna_furo": "Hole",
        "sondagem_coluna_de": "From (m)",
        "sondagem_coluna_ate": "To (m)",
        "sondagem_coluna_de_original": "From (original)",
        "sondagem_coluna_ate_original": "To (original)",
        "sondagem_coluna_unidade": "Unit",
        "sondagem_coluna_espessura": "Thickness (m)",
        "sondagem_coluna_litologia": "Lithology",
        "sondagem_coluna_amostra": "Sample",
        "sondagem_coluna_observacao": "Remarks",
        "sondagem_coluna_situacao": "Status",
        "sondagem_coluna_motivo": "Reason",
        "sondagem_coluna_anterior": "Previous line",
        "sondagem_coluna_sobreposicao": "Overlap (m)",
        "sondagem_coluna_lacuna": "Gap (m)",
        "sondagem_situacao_valido": "Valid",
        "sondagem_situacao_sobreposicao": "Overlap",
        "sondagem_situacao_lacuna": "Gap",
        "sondagem_situacao_sobreposicao_lacuna": "Overlap and gap",
        "sondagem_situacao_invalido": "Invalid",
        "sondagem_situacao_desconhecida": "Unclassified",
        "sondagem_motivo_furo_ausente": "Hole not provided",
        "sondagem_motivo_de_ausente": "Missing from depth",
        "sondagem_motivo_ate_ausente": "Missing to depth",
        "sondagem_motivo_de_invalido": "Invalid from depth",
        "sondagem_motivo_ate_invalido": "Invalid to depth",
        "sondagem_motivo_intervalo_invalido": "Interval not recognized",
        "sondagem_motivo_de_negativo": "Negative from depth",
        "sondagem_motivo_ate_nao_maior": (
            "To depth is less than or equal to from depth"
        ),
        "sondagem_motivo_unidade_invalida": "Invalid depth unit",
        "sondagem_motivo_generico": "Invalid row",
        "sondagem_aviso_neutralizacao": (
            "Formulas starting with =, +, -, @, tab, CR or LF are "
            "neutralized in CSV/XLSX; valid negative numbers are "
            "preserved."
        ),
        "sondagem_exportar_csv": "Download sanitized CSV",
        "sondagem_exportar_xlsx": "Download sanitized XLSX",
        "sondagem_ajuda_csv": (
            "UTF-8 with BOM, ';' separator and decimal comma; invalid "
            "rows are included in the report."
        ),
        "sondagem_ajuda_xlsx": (
            "In-memory workbook; dangerous cells stay as text and numbers "
            "remain numeric."
        ),
        "sondagem_arquivo_csv": "drilling_grid.csv",
        "sondagem_arquivo_xlsx": "drilling_grid.xlsx",
        "aba_ajuda": (
            "The conversation, history and sidebar choices are preserved "
            "when switching tabs."
        ),
        # -- Tab 2: spatial resolution and offline package ----------
        "espacial_titulo": "Spatial resolution and offline package",
        "espacial_caption": (
            "Convert coordinates or CIM codes, inspect the cartographic "
            "hierarchy from 1:1,000,000 to 1:25,000 and download the "
            "sheet to query everything offline."
        ),
        "espacial_modo": "Query type",
        "espacial_modo_coordenadas": "Coordinates",
        "espacial_modo_folha": "CIM sheet",
        "espacial_latitude": "Latitude",
        "espacial_longitude": "Longitude",
        "espacial_folha_cim": "CIM sheet code",
        "espacial_placeholder_folha": "e.g. SA.20, SB.21-X-B, SC.22-Z-D-IV",
        "espacial_rotulado": "Labelled coordinates (do not invert)",
        "espacial_ajuda_rotulado": (
            "When on, the latitude/longitude order is respected even when "
            "the pair looks inverted; an input error is rejected instead "
            "of becoming a false point."
        ),
        "espacial_consultar": "Resolve position",
        "espacial_limpar": "Clear result",
        "espacial_cartao_titulo": "Spatial resolution card",
        "espacial_resultado_coordenadas": "Normalized coordinates",
        "espacial_inversao_detectada": (
            "Axes automatically inverted: reading corrected to {par}."
        ),
        "espacial_inversao_indevida": (
            "The informed latitude is outside ±90°. The pair looks "
            "inverted; confirm the latitude/longitude order."
        ),
        "espacial_coordenada_invalida": (
            "Invalid coordinates. Use latitude between -90 and 90 and "
            "longitude between -180 and 180."
        ),
        "espacial_coordenada_ausente": "Enter latitude and longitude.",
        "espacial_folha_invalida": (
            "Invalid CIM code. Use the format SA.20 or SB.21-X-B-IV-1."
        ),
        "espacial_erro_generico": "The spatial query could not be resolved.",
        "espacial_hierarquia": "Cartographic hierarchy",
        "espacial_escala": "Scale",
        "espacial_codigo": "Code",
        "espacial_centroide": "Centroid",
        "espacial_limites": "Bounds",
        "espacial_pacote_titulo": "CIM sheet offline package",
        "espacial_pacote_caption": (
            "The package stores the manifest and per-source records in "
            "the operational SQLite memory (spatial_cache). After the "
            "download, queries and exports work offline."
        ),
        "espacial_pacote_folha": "Package sheet",
        "espacial_pacote_baixar": (
            "Download / Update Sheet Offline Package"
        ),
        "espacial_pacote_disponivel": "Offline package available",
        "espacial_pacote_indisponivel": (
            "Offline package not downloaded for this sheet yet"
        ),
        "espacial_pacote_collected_at": "Collected at",
        "espacial_pacote_source_version": "Source version",
        "espacial_pacote_total": "Records in package",
        "espacial_pacote_fontes": "Totals per source",
        "espacial_pacote_fonte": "Source",
        "espacial_pacote_registros": "Records",
        "espacial_pacote_exportar_manifesto": "Download manifest (JSON)",
        "espacial_pacote_exportar_dados": "Export offline data (CSV)",
        "espacial_pacote_sem_dados": (
            "No compatible feature falls in this sheet. The previous "
            "package was preserved and not overwritten with an empty "
            "snapshot."
        ),
        "espacial_pacote_criado": (
            "Offline package saved: {total} record(s) in {fontes} "
            "source(s)."
        ),
        "espacial_pacote_erro": (
            "The offline package could not be saved: {erro}"
        ),
        "espacial_pacote_remover": "Remove offline package",
        "espacial_pacote_removido": "Offline package removed.",
        "espacial_pacote_memoria": (
            "Stored in SQLite; no temporary file is written."
        ),
        "espacial_offline_titulo": "Disconnected query",
        "espacial_offline_caption": (
            "Reads the local SQLite only. No connector is called in this "
            "section."
        ),
        "espacial_offline_sem_dados": (
            "No offline record for the selected source filter."
        ),
        "espacial_offline_fonte": "Filter offline source",
        "espacial_offline_todas": "All sources",
        "espacial_mapa_titulo": "Interactive map by source",
        "espacial_mapa_fontes": "Sources displayed",
        "espacial_mapa_sem_feicoes": (
            "No feature in the selected sources. Choose at least one "
            "source above."
        ),
        "espacial_mapa_alt": (
            "Interactive map with {n} spatial resolution feature(s)."
        ),
        "espacial_mapa_tooltip": (
            "Name: {nome}\nSource: {fonte}\nCIM sheet: {folha}"
        ),
        "espacial_tabela_titulo": "Tabular preview before download",
        "espacial_tabela_alt": (
            "Table with name, source, coordinates and CIM sheet for each "
            "displayed feature."
        ),
        "espacial_exportar_csv": "Download sanitized CSV",
        "espacial_exportar_xlsx": "Download sanitized XLSX",
        "espacial_exportar_qgis": "Download GeoJSON for QGIS",
        "espacial_ajuda_csv": (
            "UTF-8 with BOM and ';' separator: opens in Excel and QGIS."
        ),
        "espacial_ajuda_xlsx": (
            "Workbook with preview and data; dangerous cells stay as text."
        ),
        "espacial_ajuda_qgis": (
            "WGS84 GeoJSON with sanitized attributes, ready to drag into "
            "QGIS."
        ),
        "espacial_aviso_neutralizacao": (
            "Formulas starting with =, +, -, @, tab, CR or LF are "
            "neutralized before any download."
        ),
        "espacial_sem_feicoes_sessao": (
            "There are no spatial features in this session yet. Resolve a "
            "position or query sources in Tab 1 to feed the map."
        ),
        "espacial_coluna_fonte": "Source",
        "espacial_coluna_nome": "Name",
        "espacial_coluna_latitude": "Latitude",
        "espacial_coluna_longitude": "Longitude",
        "espacial_coluna_folha": "CIM sheet",
        "espacial_pacote_manifesto": "Package manifest",
        "espacial_pacote_nao_encontrado": (
            "Package not found for sheet {folha}."
        ),
    },
}


# ---------------------------------------------------------------------------
# Perfis analíticos e regiões internacionais em inglês
# ---------------------------------------------------------------------------

# Os nomes canônicos dos perfis continuam em português, porque são
# gravados em ``prompts/system_base.txt`` e comparados por
# ``core.analytical_profiles``. Este mapa fornece apenas a exibição em
# inglês (nome, rótulo curto e descrição), sem alterar o valor gravado.
PERFIS_EN = {
    "Geociências Geral (Padrão)": {
        "nome": "General Geosciences (Default)",
        "curto": "General",
        "descricao": (
            "Balanced technical synthesis, with bibliographic rigor and "
            "citation of every source."
        ),
    },
    "Geologia Regional & Mapeamento Geológico": {
        "nome": "Regional Geology & Geological Mapping",
        "curto": "Regional geology",
        "descricao": (
            "Lithostratigraphy, structural provinces, geochronology, "
            "tectonic evolution, contacts and map sheets "
            "(1:100,000 / 1:250,000)."
        ),
    },
    "Exploração Mineral & Geoquímica": {
        "nome": "Mineral Exploration & Geochemistry",
        "curto": "Mineral exploration",
        "descricao": (
            "Grades, lithological/structural controls and paragenesis, "
            "focused on resources, reserves and anomalies."
        ),
    },
    "Hidrogeologia & Recursos Hídricos": {
        "nome": "Hydrogeology & Water Resources",
        "curto": "Hydrogeology",
        "descricao": (
            "Water balance, aquifers, levels, flow rates, basins and "
            "ANA/SIAGAS monitoring."
        ),
    },
    "Geotecnia & Geologia de Engenharia": {
        "nome": "Geotechnics & Engineering Geology",
        "curto": "Geotechnics",
        "descricao": (
            "Rock masses and soils, weathering, slope stability, "
            "foundations, permeability and geological hazards."
        ),
    },
    "Sensoriamento Remoto & Geofísica": {
        "nome": "Remote Sensing & Geophysics",
        "curto": "Remote sensing",
        "descricao": (
            "Orbital sensors, geophysical methods, anomalies and "
            "integration with geological mapping."
        ),
    },
    "Licenciamento & Risco Ambiental": {
        "nome": "Environmental Licensing & Risk",
        "curto": "Environmental licensing",
        "descricao": (
            "Legal framework, environmental studies, hazards and "
            "mitigation measures for the project."
        ),
    },
    "Personalizado": {
        "nome": "Custom",
        "curto": "Custom",
        "descricao": (
            "Free instruction: the text written in the editor is used "
            "exactly as typed."
        ),
    },
}

# Rótulos em inglês das regiões do seletor internacional. A chave é a
# opção canônica em português (valor enviado aos conectores), então o
# filtro do backend continua funcionando sem alteração.
REGIOES_EN = {
    "🌎 Todas as Regiões (Global)": "🌎 All Regions (Global)",
    "🌍 OneGeology (Global WFS)": "🌍 OneGeology (Global WFS)",
    "🇺🇸 Estados Unidos / Global (USGS)": "🇺🇸 United States / Global (USGS)",
    "🇨🇦 Canadá (NRCan / GSC)": "🇨🇦 Canada (NRCan / GSC)",
    "🇪🇺 União Europeia (EGDI)": "🇪🇺 European Union (EGDI)",
    "🇦🇺 Austrália (GA / GSQ)": "🇦🇺 Australia (GA / GSQ)",
    "🇯🇵 Japão (GSJ / AIST)": "🇯🇵 Japan (GSJ / AIST)",
    "🇳🇿 Nova Zelândia (GeoNet / GNS)": (
        "🇳🇿 New Zealand (GeoNet / GNS)"
    ),
    "🇿🇦 África (CGS / Digital Earth Africa)": (
        "🇿🇦 Africa (CGS / Digital Earth Africa)"
    ),
    "🇸🇦 Arábia Saudita (NGD)": "🇸🇦 Saudi Arabia (NGD)",
    "🇮🇳 Índia (GSI / Bhukosh WFS)": "🇮🇳 India (GSI / Bhukosh WFS)",
}

# Rótulos curtos das regiões para o badge do cabeçalho.
ROTULOS_CURTOS_REGIOES_EN = {
    "🌎 Todas as Regiões (Global)": "All",
    "🌍 OneGeology (Global WFS)": "OneGeology",
    "🇺🇸 Estados Unidos / Global (USGS)": "USA",
    "🇨🇦 Canadá (NRCan / GSC)": "Canada",
    "🇪🇺 União Europeia (EGDI)": "EU",
    "🇦🇺 Austrália (GA / GSQ)": "Australia",
    "🇯🇵 Japão (GSJ / AIST)": "Japan",
    "🇳🇿 Nova Zelândia (GeoNet / GNS)": "New Zealand",
    "🇿🇦 África (CGS / Digital Earth Africa)": "Africa",
    "🇸🇦 Arábia Saudita (NGD)": "Saudi Arabia",
    "🇮🇳 Índia (GSI / Bhukosh WFS)": "India",
}


# Instrução explícita de idioma injetada no system prompt. Mantém as
# citações e os nomes próprios exatamente como aparecem nas fontes.
INSTRUCAO_IDIOMA_RESPOSTA = {
    "pt": (
        "IDIOMA OBRIGATÓRIO DA RESPOSTA — Redija toda a resposta "
        "técnica, as tabelas, os títulos, as listas e as conclusões em "
        "Português do Brasil. Mantenha inalterados os nomes próprios, "
        "as citações textuais, os títulos originais das publicações, os "
        "topônimos oficiais, os códigos (ANM, SIGMINE, folha CIM) e as "
        "unidades de medida. Quando uma fonte estiver em outro idioma, "
        "traduza apenas a explicação e preserve o trecho citado no "
        "idioma original."
    ),
    "en": (
        "MANDATORY RESPONSE LANGUAGE — Write the entire technical "
        "answer, including tables, headings, lists and conclusions, in "
        "technical English. Keep proper names, verbatim quotations, "
        "original publication titles, official place names, codes "
        "(ANM, SIGMINE, CIM sheet) and units of measure unchanged. "
        "When a source is in another language, translate only the "
        "explanation and preserve the quoted passage in its original "
        "language."
    ),
}


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def normalizar_idioma(idioma):
    """Devolve um idioma suportado, caindo em ``"pt"`` quando inválido."""

    codigo = str(idioma or "").strip().lower()

    return codigo if codigo in IDIOMAS_SUPORTADOS else IDIOMA_PADRAO


def _streamlit_carregado():
    """Devolve o ``streamlit`` já importado, sem forçar um novo import.

    O ``document_parser`` usa ``t()`` para as mensagens de limite, mas o
    parsing não deve carregar o runtime da interface (nem emitir o aviso
    de ``ScriptRunContext``). Quando o app Streamlit já está em execução,
    o módulo está em ``sys.modules`` e o idioma ativo é respeitado; em
    CLI/testes, o padrão PT-BR é usado sem importar streamlit.
    """

    return sys.modules.get("streamlit")


def idioma_atual():
    """Lê o idioma ativo de ``st.session_state``, com fallback seguro.

    Fora de um script Streamlit (testes unitários, CLI), a leitura falha
    silenciosamente e o padrão ``"pt"`` é devolvido.
    """

    st = _streamlit_carregado()

    if st is None:
        return IDIOMA_PADRAO

    try:
        return normalizar_idioma(st.session_state.get("idioma"))
    except Exception:
        return IDIOMA_PADRAO


def t(chave: str, idioma: str | None = None) -> str:
    """Traduz uma chave de interface para o idioma ativo.

    ``idioma`` explícito tem precedência sobre ``st.session_state``.
    Quando a chave não existe no idioma pedido, tenta o Português do
    Brasil e, por último, devolve a própria chave — nunca levanta erro.
    """

    codigo = normalizar_idioma(idioma) if idioma else idioma_atual()
    textos = TEXTOS_I18N.get(codigo) or {}

    if chave in textos:
        return textos[chave]

    return TEXTOS_I18N[IDIOMA_PADRAO].get(chave, chave)


def tf(chave: str, idioma: str | None = None, **valores) -> str:
    """Traduz a chave e preenche os marcadores ``{nome}`` informados.

    Um marcador sem valor correspondente é mantido como está, para que a
    interface nunca quebre por um dado ausente.
    """

    texto = t(chave, idioma)

    try:
        return texto.format(**valores)
    except (KeyError, IndexError, ValueError):
        return texto


def rotulo_idioma(codigo):
    """Rótulo curto com a bandeira do idioma, usado nos botões."""

    return ROTULOS_IDIOMA.get(normalizar_idioma(codigo), ROTULOS_IDIOMA["pt"])


def nome_idioma(codigo):
    """Nome por extenso do idioma, usado no ``help`` dos botões."""

    return NOMES_IDIOMA.get(normalizar_idioma(codigo), NOMES_IDIOMA["pt"])


def rotulo_regiao(regiao, idioma=None):
    """Rótulo de exibição da região sem alterar o valor canônico."""

    codigo = normalizar_idioma(idioma) if idioma else idioma_atual()

    if codigo == "en":
        return REGIOES_EN.get(regiao, regiao)

    return regiao


def rotulo_curto_regiao(regiao, idioma=None):
    """Versão curta da região, para o badge compacto do cabeçalho."""

    codigo = normalizar_idioma(idioma) if idioma else idioma_atual()

    if codigo == "en":
        return ROTULOS_CURTOS_REGIOES_EN.get(regiao, rotulo_regiao(
            regiao,
            idioma,
        ))

    # Em português o mapa curto é montado em ``app.py``; aqui só se
    # garante um rótulo utilizável quando a região não tem forma curta.
    return regiao


def regiao_do_rotulo(rotulo):
    """Converte um rótulo exibido (pt ou en) na opção canônica.

    O seletor internacional é preenchido com os rótulos do idioma ativo,
    mas o valor enviado aos conectores precisa continuar sendo a opção
    canônica em português — é ela que ``core.assistant`` e
    ``services.external_api_service`` comparam. Devolve ``None`` quando o
    rótulo não pertence ao catálogo conhecido.
    """

    if rotulo in REGIOES_EN:
        return rotulo

    for canonica, traduzida in REGIOES_EN.items():
        if rotulo == traduzida:
            return canonica

    return None


def perfil_do_rotulo(rotulo):
    """Converte um rótulo de perfil (pt ou en) no nome canônico.

    O nome canônico em português é o valor gravado em
    ``session_state["perfil_analitico"]`` e usado por
    ``core.analytical_profiles``. Devolve ``None`` quando o rótulo não é
    reconhecido.
    """

    if rotulo in PERFIS_EN:
        return rotulo

    for canonico, dados in PERFIS_EN.items():
        if rotulo == dados.get("nome"):
            return canonico

    return None


def dados_perfil(perfil, idioma=None):
    """Nome, rótulo curto e descrição do perfil no idioma ativo.

    Em português devolve apenas ``None`` para os três campos: o
    chamador mantém os dados canônicos de ``core.analytical_profiles``,
    que são a fonte única nesse idioma.
    """

    codigo = normalizar_idioma(idioma) if idioma else idioma_atual()

    if codigo == "en":
        return PERFIS_EN.get(perfil) or {}

    return {}


def rotulo_perfil(perfil, idioma=None):
    """Nome do perfil analítico no idioma ativo (valor salvo intacto)."""

    dados = dados_perfil(perfil, idioma)

    return dados.get("nome") or perfil


def rotulo_curto_perfil(perfil, idioma=None):
    """Rótulo curto do perfil, usado no badge do cabeçalho."""

    dados = dados_perfil(perfil, idioma)

    return dados.get("curto") or perfil


def descricao_perfil(perfil, idioma=None, padrao=""):
    """Descrição do perfil no idioma ativo, com fallback ao texto padrão."""

    dados = dados_perfil(perfil, idioma)

    return dados.get("descricao") or padrao


def instrucao_idioma_resposta(idioma=None):
    """Instrução de idioma que orienta a resposta técnica do LLM."""

    codigo = normalizar_idioma(idioma) if idioma else idioma_atual()

    return INSTRUCAO_IDIOMA_RESPOSTA[codigo]
