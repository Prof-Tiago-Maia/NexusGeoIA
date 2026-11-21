@echo off
rem ---------------------------------------------------------------------------
rem Inicia o NexusGeo IA.
rem
rem A pasta portatil gerada por packaging\build_portatil.ps1 traz o
rem NexusGeoIA.exe (PyInstaller) ao lado deste arquivo; nesse caso o
rem executavel e aberto direto e os dados ficam na propria pasta. Em
rem desenvolvimento o script usa python\python.exe ou o ambiente virtual
rem .venv. Na primeira execucao (sem config_local.json) o assistente de
rem modelos pergunta quais modelos do Ollama baixar. Depois disso o
rem Streamlit abre o aplicativo.
rem
rem Execute com duplo clique ou pelo Prompt de Comando, a partir da pasta
rem do projeto. Os dados ficam em data\ (ou em
rem %LOCALAPPDATA%\NexusGeoIA quando o aplicativo for o
rem executavel instalado).
rem ---------------------------------------------------------------------------

setlocal
set PYTHONUTF8=1

rem Trabalha sempre na pasta onde este arquivo esta, mesmo quando chamado
rem de outro diretorio.
pushd "%~dp0"

rem Inclui o Ollama recem-instalado no PATH desta sessao. O instalador
rem silencioso usa %LOCALAPPDATA%\Programs\Ollama e, sem estas linhas, o
rem assistente poderia nao encontrar o ollama.exe logo apos a instalacao.
if exist "%LOCALAPPDATA%\Programs\Ollama" (
    set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
)
if exist "%ProgramFiles%\Ollama" (
    set "PATH=%ProgramFiles%\Ollama;%PATH%"
)
if exist "%ProgramFiles(x86)%\Ollama" (
    set "PATH=%ProgramFiles(x86)%\Ollama;%PATH%"
)

rem ---------------------------------------------------------------------------
rem Pacote portatil: executavel unico gerado pelo PyInstaller
rem
rem Quando o NexusGeoIA.exe esta ao lado deste arquivo, a pasta e o pacote
rem portatil: o executavel ja traz app.py, prompts, .streamlit e o
rem assistente de modelos embutidos. ASSISTENTE_DATA_DIR fixa os dados
rem gravaveis (historico, banco, documentos e config_local.json) na propria
rem pasta do pacote, para que ele continue portatil ao ser copiado.
rem
rem O desvio usa goto porque dentro de um bloco "if (...)" o cmd.exe
rem expandiria %ERRORLEVEL% na leitura do bloco, antes de o executavel
rem rodar; fora do bloco o codigo de saida e lido corretamente.
rem ---------------------------------------------------------------------------

if exist "%~dp0NexusGeoIA.exe" goto :iniciar_executavel

set "PYTHON="

if exist "%~dp0python\python.exe" (
    set "PYTHON=%~dp0python\python.exe"
)

if not defined PYTHON (
    if exist "%~dp0.venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
    )
)

if not defined PYTHON (
    echo.
    echo [ERRO] Python nao encontrado.
    echo.
    echo A pasta portatil deve conter python\python.exe.
    echo Em desenvolvimento, crie o ambiente e instale as dependencias:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    popd
    pause
    exit /b 1
)

if not exist "%~dp0config_local.json" (
    echo.
    echo Primeira execucao: abrindo o assistente de modelos LLM...
    echo.
    "%PYTHON%" "%~dp0setup_llm.py"

    if errorlevel 1 (
        echo.
        echo [AVISO] O assistente de modelos nao foi concluido.
        echo         O aplicativo continuara abrindo em modo offline.
        echo         Para tentar de novo, execute:
        echo             "%PYTHON%" setup_llm.py --forcar
        echo.
    )
)

echo Iniciando o NexusGeo IA...
echo.

rem ---------------------------------------------------------------------------
rem Porta do servidor
rem
rem A porta preferida e 8501. Quando outra instancia do aplicativo (ou
rem qualquer outro programa) ja ocupa essa porta, o Python do pacote
rem testa 8502..8510 e devolve a primeira livre. A regra e a mesma de
rem launcher_desktop._encontrar_porta_livre: bind em 127.0.0.1. A porta
rem escolhida vale para o servidor (--server.port) e para a URL
rem anunciada; sem isso o Streamlit aborta com
rem "Port 8501 is not available".
rem ---------------------------------------------------------------------------

set "PORTA=8501"
set "ARQ_PORTA=%TEMP%\nexusgeo_porta.txt"

"%PYTHON%" -c "import socket,sys;exec('for p in range(8501,8511):\n c=socket.socket()\n try:\n  c.bind((\'127.0.0.1\',p));c.close();print(p);sys.exit(0)\n except OSError:\n  c.close()\nprint(8501)')" > "%ARQ_PORTA%" 2>nul

if not exist "%ARQ_PORTA%" goto porta_definida

set /p PORTA=<"%ARQ_PORTA%"
del "%ARQ_PORTA%" >nul 2>&1

:porta_definida

rem Saida inesperada do teste de porta volta para a porta preferida.
echo %PORTA%| findstr /r "^[0-9][0-9]*$" >nul || set "PORTA=8501"

echo O navegador abrira automaticamente em http://localhost:%PORTA%
echo.

rem --server.headless=false faz o proprio Streamlit abrir a aba assim
rem que o servidor responde; a porta vem do teste acima, entao a URL
rem aberta e sempre a que o servidor realmente reservou.
"%PYTHON%" -m streamlit run "%~dp0app.py" --server.headless=false --server.address=localhost --server.port=%PORTA%
set "CODIGO_SAIDA=%ERRORLEVEL%"

if not "%CODIGO_SAIDA%"=="0" (
    echo.
    echo [ERRO] O Streamlit foi encerrado com o codigo %CODIGO_SAIDA%.
    echo Verifique as mensagens acima.
    pause
)

popd
endlocal & exit /b %CODIGO_SAIDA%

rem ---------------------------------------------------------------------------
rem Modo executavel portatil (destino do goto acima).
rem
rem Fica fora de qualquer bloco "if (...)" para que %ERRORLEVEL% seja lido
rem depois da execucao do aplicativo, e nao na leitura do bloco.
rem ---------------------------------------------------------------------------

:iniciar_executavel

set "ASSISTENTE_DATA_DIR=%~dp0"

echo Iniciando o NexusGeo IA...
echo.

"%~dp0NexusGeoIA.exe" %*
set "CODIGO_SAIDA=%ERRORLEVEL%"

if not "%CODIGO_SAIDA%"=="0" (
    echo.
    echo [ERRO] O NexusGeo IA foi encerrado com o codigo %CODIGO_SAIDA%.
    echo Verifique as mensagens acima.
    pause
)

popd
endlocal & exit /b %CODIGO_SAIDA%
