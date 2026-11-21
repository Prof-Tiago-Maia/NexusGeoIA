"""Ponto de entrada do executável do NexusGeo IA.

Este é o alvo do PyInstaller (``packaging/assistente.spec``). Ele resolve
as diferenças entre a pasta portátil e a instalação em ``Program Files``:

1. define ``ASSISTENTE_DATA_DIR=%LOCALAPPDATA%\\NexusGeoIA``
   **antes** de importar ``config`` (a pasta de instalação é somente
   leitura; histórico, banco, documentos e ``config_local.json`` precisam
   ir para o perfil do usuário);
2. executa o assistente de modelos (``setup_llm.py``) quando o
   ``config_local.json`` ainda não existe ou quando recebe
   ``--setup-modelo`` (atalho *Gerenciar Modelos LLM* do instalador);
3. inicia o Streamlit programaticamente via
   ``streamlit.web.cli.main()``, apontando para o ``app.py`` empacotado,
   na primeira porta livre a partir de 8501 (a 8501 pode estar ocupada
   por outra instância do aplicativo), com ``--server.port=<porta>``,
   ``--server.headless=true`` (o launcher é o dono da abertura do
   navegador, evitando duas abas) e ``--global.developmentMode=false``;
4. aguarda o healthcheck HTTP local responder e só então executa
   ``webbrowser.open(f"http://localhost:{porta}")``.

Os recursos lidos por caminho (``app.py``, ``prompts/system_base.txt`` e
``.streamlit/config.toml``) são sempre resolvidos em
``sys._MEIPASS`` quando ``sys.frozen`` está ativo: no pacote ``--onedir``
do PyInstaller 6 isso é ``dist\\NexusGeoIA\\_internal``, e em
``Program Files`` a pasta de instalação é somente leitura (os arquivos
não ficam soltos nela).

Uso pelo executável:

    NexusGeoIA.exe
    NexusGeoIA.exe --setup-modelo
    NexusGeoIA.exe --autoteste
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.client import HTTPException
from pathlib import Path

NOME_APLICATIVO = "NexusGeoIA"

# Porta preferida; se estiver ocupada, a próxima livre é usada.
PORTA_PREFERIDA = 8501

# Interface de rede usada nos testes de porta livre. O Streamlit é
# iniciado em ``localhost``; verificar o mesmo loopback evita escolher
# uma porta que o ``bind`` do servidor recusaria em seguida.
ENDERECO_LOOPBACK = "127.0.0.1"

# Endereço que o navegador deve abrir quando a porta preferida responde.
URL_APLICATIVO = "http://localhost:8501"

# Endpoint de saúde exposto pelo servidor do Streamlit.
CAMINHO_SAUDE = "/_stcore/health"

# Espera máxima pela subida do servidor antes de desistir de abrir a aba
# (120 tentativas x 0,5 s = 60 s).
TENTATIVAS_SAUDE = 120
INTERVALO_SAUDE = 0.5

# Quantas portas subsequentes são testadas (8501..8510) antes de pedir
# uma porta efêmera ao sistema operacional.
TENTATIVAS_PORTA = 10

# Argumentos de linha de comando reconhecidos pelo launcher.
ARG_SETUP = "--setup-modelo"
ARG_FORCAR = "--forcar"


def diretorio_localappdata():
    """Pasta gravável do usuário, com o nome do aplicativo."""

    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")

    if base:
        return Path(base) / NOME_APLICATIVO

    return Path.home() / "AppData" / "Local" / NOME_APLICATIVO


def adicionar_ollama_ao_path():
    """Inclui a pasta do Ollama no ``PATH`` da sessão atual.

    O ``setup_llm.py`` instala o Ollama silenciosamente em
    ``%LOCALAPPDATA%\\Programs\\Ollama``; repetir a inclusão aqui evita
    que o assistente e o Streamlit (em processos subsequentes) não
    encontrem o ``ollama.exe`` até o próximo logon.
    """

    if os.name != "nt":
        return None

    candidatas = []

    base = os.getenv("LOCALAPPDATA")

    if base:
        candidatas.append(Path(base) / "Programs" / "Ollama")

    for variavel in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        base = os.getenv(variavel)

        if base:
            candidatas.append(Path(base) / "Ollama")

    pasta = next(
        (caminho for caminho in candidatas if caminho.is_dir()),
        candidatas[0] if candidatas else None,
    )

    if pasta is None:
        return None

    atual = os.environ.get("PATH", "")
    alvo = str(pasta).rstrip("\\/").casefold()
    partes = [
        str(Path(parte)).rstrip("\\/").casefold()
        for parte in atual.split(os.pathsep)
        if parte.strip()
    ]

    if alvo not in partes:
        os.environ["PATH"] = str(pasta) + (
            os.pathsep + atual if atual else ""
        )

    return str(pasta)


def configurar_diretorio_dados():
    """Define ``ASSISTENTE_DATA_DIR`` e devolve o diretório escolhido.

    ``setdefault`` preserva um valor já definido pelo usuário (ou pelos
    testes), mas garante o padrão em ``%LOCALAPPDATA%`` no executável.
    """

    padrao = str(diretorio_localappdata())

    os.environ.setdefault("ASSISTENTE_DATA_DIR", padrao)

    return Path(os.environ["ASSISTENTE_DATA_DIR"]).expanduser()


# Executado antes de qualquer import do projeto: ``config.py`` lê a
# variável no momento em que é importado.
DIRETORIO_DADOS = configurar_diretorio_dados()

# O Ollama pode ter acabado de ser instalado pelo assistente; o PATH da
# sessão precisa incluir a pasta antes de chamar o setup e o Streamlit.
PATH_OLLAMA = adicionar_ollama_ao_path()

# Importado depois de ``ASSISTENTE_DATA_DIR`` estar definido para que o
# ``config.py`` resolva o mesmo diretório gravável usado pelo launcher.
import config  # noqa: E402


def diretorio_recursos():
    """Pasta dos arquivos empacotados (``_MEIPASS``) ou do projeto."""

    base = getattr(sys, "_MEIPASS", None)

    if base:
        return Path(base).resolve()

    return Path(__file__).resolve().parent


def caminho_app():
    """Caminho absoluto do ``app.py`` que o Streamlit vai executar."""

    return diretorio_recursos() / "app.py"


# Arquivos empacotados que o executável lê por caminho em tempo de
# execução. A verificação é feita no bundle extraído (``_MEIPASS``), e
# não na pasta do ``.exe``: em ``Program Files`` a pasta de instalação é
# somente leitura e não contém esses arquivos.
RECURSOS_OBRIGATORIOS = (
    ("app.py", "aplicativo Streamlit"),
    ("prompts/system_base.txt", "system prompt padrão"),
    (".streamlit/config.toml", "configuração do Streamlit"),
)

# Argumentos que disparam o autoteste (smoke test do executável).
ARG_AUTOTESTE = "--autoteste"
ARG_AUTOTESTE_ALTERNATIVO = "--smoke-test"

# Variável de ambiente que recebe o caminho do relatório do autoteste.
ENV_RELATORIO_AUTOTESTE = "ASSISTENTE_SMOKE_REPORT"


def recursos_ausentes():
    """Lista os recursos obrigatórios que não estão no bundle.

    Devolve pares ``(caminho, descrição)``; lista vazia significa bundle
    completo. Usada pelo autoteste e por ``preparar_ambiente``.
    """

    base = diretorio_recursos()
    ausentes = []

    for relativo, descricao in RECURSOS_OBRIGATORIOS:
        if not (base / relativo).is_file():
            ausentes.append((str(base / relativo), descricao))

    return ausentes


def verificar_recursos():
    """Garante que o bundle traz os recursos lidos por caminho.

    Levanta :class:`FileNotFoundError` com a lista completa quando falta
    algum arquivo, em vez de deixar o Streamlit ou o system prompt
    falharem depois de o servidor já ter subido.
    """

    ausentes = recursos_ausentes()

    if ausentes:
        detalhes = "\n".join(
            f"  - {caminho} ({descricao})" for caminho, descricao in ausentes
        )

        raise FileNotFoundError(
            "Recursos do aplicativo ausentes no bundle:\n" + detalhes
        )

    return diretorio_recursos()



def _porta_disponivel(porta, endereco=ENDERECO_LOOPBACK):
    """Indica se ``porta`` pode ser reservada em ``endereco``.

    A checagem usa ``bind`` e fecha o socket em seguida. Existe uma
    janela entre o teste e a abertura real do Streamlit; se outra
    aplicação tomar a porta nesse intervalo, o Streamlit falha de forma
    visível em vez de abrir na porta errada.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        try:
            soquete.bind((str(endereco), int(porta)))
        except OSError:
            return False

    return True


def _encontrar_porta_livre(
    porta_inicial: int = PORTA_PREFERIDA,
    tentativas: int = TENTATIVAS_PORTA,
) -> int:
    """Primeira porta TCP livre a partir de ``porta_inicial``.

    Testa ``tentativas`` portas consecutivas em 127.0.0.1 — com os
    padrões, 8501..8510. Quando nenhuma delas está livre, pede uma porta
    efêmera ao sistema operacional, que sempre nasce desocupada.
    """

    inicial = int(porta_inicial)
    limite = max(1, int(tentativas))

    for porta in range(inicial, inicial + limite):
        if _porta_disponivel(porta):
            return porta

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soquete:
        soquete.bind((ENDERECO_LOOPBACK, 0))

        return int(soquete.getsockname()[1])


def porta_livre(preferida=PORTA_PREFERIDA, tentativas=TENTATIVAS_PORTA):
    """Compatibilidade: nome histórico de ``_encontrar_porta_livre``."""

    return _encontrar_porta_livre(preferida, tentativas)


def url_aplicativo(porta=PORTA_PREFERIDA):
    """URL local que o navegador deve abrir para a porta informada."""

    porta = int(porta)

    if porta == PORTA_PREFERIDA:
        return URL_APLICATIVO

    return f"http://localhost:{porta}"


def aplicacao_respondendo(porta=PORTA_PREFERIDA, timeout=1.0):
    """Consulta o healthcheck HTTP do Streamlit.

    Devolve ``True`` apenas quando ``/_stcore/health`` responde 2xx.
    Qualquer erro de rede, timeout ou status inesperado conta como
    "ainda não está pronta", sem interromper a espera.
    """

    url = f"{url_aplicativo(porta)}{CAMINHO_SAUDE}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            codigo = getattr(resposta, "status", None)

            if codigo is None:
                codigo = resposta.getcode()

            return 200 <= int(codigo) < 300
    except (urllib.error.URLError, OSError, HTTPException, ValueError):
        return False


def abrir_navegador_quando_pronto(
    porta=PORTA_PREFERIDA,
    tentativas=TENTATIVAS_SAUDE,
    intervalo=INTERVALO_SAUDE,
    abrir=None,
):
    """Aguarda o healthcheck e abre o navegador uma única vez.

    A função é síncrona para poder ser testada sem threads; em produção
    ``agendar_abertura_navegador`` a executa em segundo plano.
    """

    abrir = abrir or webbrowser.open

    for _ in range(max(1, int(tentativas))):
        if aplicacao_respondendo(porta):
            try:
                abrir(url_aplicativo(porta))
            except Exception:  # pragma: no cover - navegador indisponível
                return False

            return True

        time.sleep(float(intervalo))

    return False


def agendar_abertura_navegador(porta=PORTA_PREFERIDA):
    """Dispara a abertura do navegador em uma thread daemon."""

    thread = threading.Thread(
        target=abrir_navegador_quando_pronto,
        kwargs={"porta": porta},
        name="nexusgeo-navegador",
        daemon=True,
    )
    thread.start()

    return thread


def _imprimir(mensagem):
    """``print`` tolerante a executável sem console."""

    fluxo = sys.stdout

    if fluxo is None:
        return

    try:
        print(mensagem, file=fluxo)
    except (OSError, ValueError):  # pragma: no cover
        pass


def _mostrar_erro(titulo, mensagem):
    """Mostra o erro em janela quando possível; senão imprime."""

    _imprimir(f"{titulo}: {mensagem}")

    try:
        import tkinter as tk
        from tkinter import messagebox

        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(titulo, mensagem, parent=raiz)
        raiz.destroy()
    except Exception:  # pragma: no cover - sem interface disponível
        pass


def preparar_ambiente():
    """Garante diretórios graváveis, ``sys.path`` e diretório corrente."""

    import config

    config.garantir_diretorios()

    # Reforça o PATH a cada preparação: o setup pode ter instalado o
    # Ollama nesta mesma sessão, depois da primeira chamada.
    adicionar_ollama_ao_path()

    recursos = diretorio_recursos()

    # Falha cedo e com a lista completa quando o bundle está incompleto.
    verificar_recursos()

    if str(recursos) not in sys.path:
        sys.path.insert(0, str(recursos))

    # O Streamlit procura ``.streamlit/config.toml`` no diretório
    # corrente; o bundle do executável inclui essa pasta.
    try:
        os.chdir(recursos)
    except OSError:  # pragma: no cover - pasta somente leitura exótica
        pass

    return recursos


def executar_setup(forcar=False):
    """Executa o assistente de modelos no próprio processo.

    Rodar como função (em vez de subprocesso) mantém o ``tkinter``
    empacotado e o diretório de dados já resolvido.
    """

    import setup_llm

    argumentos = [ARG_FORCAR] if forcar else []

    return setup_llm.main(argumentos)


def configuracao_pendente():
    """Indica se o ``config_local.json`` ainda não foi criado."""

    import setup_llm

    return setup_llm.precisa_configurar()


def iniciar_streamlit(porta, argumentos_extra=None):
    """Executa ``streamlit run app.py`` na porta indicada.

    Devolve o código de saída do Streamlit. Levanta ``FileNotFoundError``
    quando o ``app.py`` não está no bundle.
    """

    app = caminho_app()

    if not app.is_file():
        raise FileNotFoundError(f"app.py não encontrado em {app}")

    preparar_ambiente()

    from streamlit.web import cli as cli_streamlit

    argumentos = [
        "streamlit",
        "run",
        str(app),
        f"--server.port={porta}",
        "--server.address",
        "localhost",
        # O launcher abre a aba depois do healthcheck; deixar o
        # Streamlit também abrir geraria duas abas no navegador.
        "--server.headless=true",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]

    if argumentos_extra:
        argumentos.extend(str(item) for item in argumentos_extra)

    # O navegador só é aberto quando a porta responde de fato.
    agendar_abertura_navegador(porta)

    # O CLI do Streamlit lê ``sys.argv``; os argumentos do launcher não
    # podem vazar para ele.
    sys.argv = argumentos

    try:
        cli_streamlit.main()
    except SystemExit as saida:
        codigo = saida.code

        return int(codigo) if isinstance(codigo, int) else 0

    return 0


def autoteste(relatorio=None):
    """Valida o bundle do executável sem abrir janela nem servidor.

    Executa as verificações que falham silenciosamente no empacotamento:

    1. ``app.py``, ``prompts/system_base.txt`` e ``.streamlit/config.toml``
       presentes em ``sys._MEIPASS`` (e não na pasta do ``.exe``);
    2. imports críticos (Streamlit, Tkinter, ``python-docx``,
       ``openpyxl``, PyMuPDF) resolvidos de dentro do bundle;
    3. o system prompt é lido pelo mesmo caminho usado em produção;
    4. um ``.docx`` real é gerado — é o que prova que o
       ``docx/templates/default.docx`` viajou para ``_internal``;
    5. um ``.xlsx`` real é gerado pelo motor ``openpyxl`` do pandas.

    Devolve o dicionário do relatório com ``ok`` e a lista de ``falhas``.
    Quando ``relatorio`` é informado, grava o JSON nesse caminho antes de
    devolver (o executável sem console não tem ``stdout``, então o
    arquivo é o canal de saída do teste).
    """

    import json

    verificacoes = []
    falhas = []

    def _gravar_progresso(concluido=False):
        """Grava o relatório parcial após cada verificação.

        Se uma verificação travar (import de uma DLL, extração do
        bundle), o arquivo mostra exatamente onde o autoteste parou -
        informação que um executável sem console não teria como dar.
        """

        if not relatorio:
            return

        parcial = {
            "ok": bool(concluido and not falhas),
            "congelado": bool(getattr(sys, "frozen", False)),
            "base_recursos": str(diretorio_recursos()),
            "verificacoes": verificacoes,
            "falhas": falhas,
            "concluido": concluido,
        }

        try:
            Path(relatorio).write_text(
                json.dumps(parcial, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Sem relatório em disco o código de saída continua válido.
            pass

    def registrar(nome, executar):
        _gravar_progresso()

        try:
            detalhe = executar()
        except Exception as erro:  # noqa: BLE001 - o autoteste reprova em qualquer falha
            falhas.append(f"{nome}: {type(erro).__name__}: {erro}")
            verificacoes.append({"nome": nome, "ok": False, "erro": str(erro)})
            _gravar_progresso()
            return None

        verificacoes.append({"nome": nome, "ok": True, "detalhe": detalhe})
        _gravar_progresso()
        return detalhe

    congelado = bool(getattr(sys, "frozen", False))
    base = diretorio_recursos()

    def _recursos():
        ausentes = recursos_ausentes()

        if ausentes:
            raise FileNotFoundError(
                "; ".join(f"{caminho} ({descricao})"
                          for caminho, descricao in ausentes)
            )

        return str(base)

    registrar("recursos", _recursos)

    def _prompt():
        from core.prompt_manager import (
            DIRETORIO_PROMPTS,
            arquivo_prompt_base,
            carregar_prompt_base,
        )

        texto = carregar_prompt_base()

        if not texto:
            raise ValueError("system prompt vazio")

        if congelado and not str(DIRETORIO_PROMPTS).startswith(str(base)):
            raise AssertionError(
                f"DIRETORIO_PROMPTS fora do bundle: {DIRETORIO_PROMPTS}"
            )

        return {
            "arquivo": str(arquivo_prompt_base()),
            "caracteres": len(texto),
        }

    registrar("system_prompt", _prompt)

    def _imports():
        import importlib

        modulos = (
            "streamlit",
            "tkinter",
            "docx",
            "openpyxl",
            "pymupdf",
            "core.assistant",
            "core.prompt_manager",
            "services.document_parser",
            "services.report_generator",
            "services.table_extractor",
            "services.external_api_service",
            "database.connection",
            "utils.i18n",
        )

        ausentes = []

        for modulo in modulos:
            try:
                importlib.import_module(modulo)
            except Exception as erro:  # noqa: BLE001 - qualquer erro conta como ausente
                ausentes.append(f"{modulo} ({type(erro).__name__}: {erro})")

        if ausentes:
            raise ImportError("; ".join(ausentes))

        return list(modulos)

    registrar("imports_criticos", _imports)

    def _docx():
        from services.report_generator import gerar_parecer_docx

        conteudo = gerar_parecer_docx(
            "Autoteste de empacotamento",
            "## Verificação\n\nGeração do parecer em memória.",
            [{"titulo": "Documento de teste", "ano": "2026",
              "fonte": "Autoteste"}],
            "Síntese integrada",
        )

        # Um .docx é um ZIP: a assinatura PK confirma o arquivo real.
        if not conteudo or not conteudo.startswith(b"PK"):
            raise ValueError("conteúdo .docx inválido")

        return {"bytes": len(conteudo)}

    registrar("parecer_docx", _docx)

    def _excel():
        import pandas as pd

        from services.table_extractor import gerar_excel

        tabela = {
            "titulo": "Autoteste",
            "secao": "Verificação",
            "origem": "autoteste",
            "pagina": 1,
            "formato": "tabela",
            "df_limpo": pd.DataFrame({"A": [1, 2], "B": ["x", "y"]}),
            "df_bruto": pd.DataFrame({"A": [1, 2], "B": ["x", "y"]}),
            "colunas_numericas": ["A"],
            "unidades": {},
            "observacoes": [],
        }

        conteudo = gerar_excel(tabela)

        if not conteudo or not conteudo.startswith(b"PK"):
            raise ValueError("conteúdo .xlsx inválido")

        return {"bytes": len(conteudo)}

    registrar("excel_openpyxl", _excel)

    resultado = {
        "ok": not falhas,
        "congelado": congelado,
        "base_recursos": str(base),
        "verificacoes": verificacoes,
        "falhas": falhas,
        "concluido": True,
    }

    _gravar_progresso(concluido=True)

    return resultado


def executar_autoteste(relatorio=None):
    """Roda :func:`autoteste` sem nunca abrir diálogo na tela.

    O executável usa ``console=False`` e o ``main`` mostra erros fatais
    em ``messagebox``; num smoke test automatizado essa janela ficaria
    aberta para sempre esperando um clique. Este caminho é o único usado
    pelo modo ``--autoteste``: qualquer falha vira relatório + código de
    saída, jamais uma janela.
    """

    try:
        return autoteste(relatorio=relatorio)
    except BaseException as erro:  # noqa: BLE001 - inclusive SystemExit/MemoryError
        import json
        import traceback

        relatorio_erro = {
            "ok": False,
            "congelado": bool(getattr(sys, "frozen", False)),
            "base_recursos": str(diretorio_recursos()),
            "verificacoes": [],
            "falhas": [
                f"erro fatal no autoteste: {type(erro).__name__}: {erro}"
            ],
            "concluido": False,
            "traceback": traceback.format_exc(),
        }

        _imprimir(relatorio_erro["traceback"])

        if relatorio:
            try:
                Path(relatorio).write_text(
                    json.dumps(relatorio_erro, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

        return relatorio_erro


def main(argv=None):
    """Fluxo completo do executável: setup opcional e Streamlit."""

    argumentos = list(sys.argv[1:] if argv is None else argv)

    # Autoteste tem prioridade absoluta: valida o bundle e sai, sem
    # assistente de modelos, sem porta, sem navegador e sem diálogo. É o
    # gancho usado pelo smoke test automatizado do build.
    if ARG_AUTOTESTE in argumentos or ARG_AUTOTESTE_ALTERNATIVO in argumentos:
        resultado = executar_autoteste(
            relatorio=os.getenv(ENV_RELATORIO_AUTOTESTE)
        )

        for verificacao in resultado["verificacoes"]:
            estado = "OK" if verificacao["ok"] else "FALHA"

            _imprimir(f"[autoteste] {estado}: {verificacao['nome']}")

        for falha in resultado["falhas"]:
            _imprimir(f"[autoteste] {falha}")

        return 0 if resultado["ok"] else 1

    pediu_setup = ARG_SETUP in argumentos
    pediu_forcar = ARG_FORCAR in argumentos

    try:
        if pediu_setup or pediu_forcar or configuracao_pendente():
            codigo = executar_setup(
                forcar=pediu_setup or pediu_forcar
            )

            if codigo != 0:
                _imprimir(
                    "Aviso: o assistente de modelos terminou com "
                    f"código {codigo}. O aplicativo continuará abrindo."
                )

        porta = _encontrar_porta_livre()

        _imprimir(
            f"{config.APP_NAME} v{config.APP_VERSION} em "
            f"{url_aplicativo(porta)} (dados em {DIRETORIO_DADOS})"
        )

        return iniciar_streamlit(porta)
    except Exception as erro:  # erro fatal: mostra de forma legível
        _mostrar_erro(
            f"{config.APP_NAME} v{config.APP_VERSION}",
            f"Não foi possível iniciar o aplicativo.\n\n"
            f"{type(erro).__name__}: {erro}",
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
