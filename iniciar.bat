@echo off
rem ---------------------------------------------------------------------------
rem Inicia o NexusGeo IA.
rem
rem A pasta portatil gerada por packaging\build_portatil.ps1 traz o
rem NexusGeoIA.exe (PyInstaller) ao lado deste arquivo; nesse caso o
rem executavel e aberto direto e os dados ficam na propria pasta. Em
rem desenvolvimento o script usa python\python.exe ou o ambiente virtual
rem .venv. Na primeira execucao (sem config_local.json) o configurador
rem registra o unico modelo oficial nexusgeo-qwen3-4b-v2-q4 no Ollama.
rem Depois disso o Streamlit abre o aplicativo.
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

rem Encerramento manual imediato (tambem usado por encerrar.bat): le
rem instancia_ativa.json, mata a arvore do servidor e remove o registro.
if /I "%~1"=="--encerrar" goto :encerrar

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
rem configurador do modelo local embutido. ASSISTENTE_DATA_DIR fixa os dados
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
    echo Primeira execucao: configurando o modelo local oficial...
    echo.
    "%PYTHON%" "%~dp0setup_llm.py"

    if errorlevel 1 (
        echo.
        echo [AVISO] A configuracao do modelo local nao foi concluida.
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
rem Encerramento manual (destino do goto no topo).
rem ---------------------------------------------------------------------------

:encerrar

rem Usa a mesma pasta de dados do iniciar.bat para achar o
rem instancia_ativa.json gravado pelo servidor em execucao.
set "ASSISTENTE_DATA_DIR=%~dp0"

if not exist "%~dp0NexusGeoIA.exe" goto :encerrar_python

"%~dp0NexusGeoIA.exe" --encerrar
set "CODIGO_SAIDA=%ERRORLEVEL%"
popd
endlocal & exit /b %CODIGO_SAIDA%

:encerrar_python

set "PYTHON_ENCERRAR="

if exist "%~dp0python\python.exe" (
    set "PYTHON_ENCERRAR=%~dp0python\python.exe"
)

if not defined PYTHON_ENCERRAR (
    if exist "%~dp0.venv\Scripts\python.exe" (
        set "PYTHON_ENCERRAR=%~dp0.venv\Scripts\python.exe"
    )
)

if defined PYTHON_ENCERRAR (
    "%PYTHON_ENCERRAR%" "%~dp0launcher_desktop.py" --encerrar
)

popd
endlocal & exit /b 0

rem ---------------------------------------------------------------------------
rem Modo executavel portatil (destino do goto acima).
rem
rem O NexusGeoIA.exe e compilado com console=False. Nesse processo sem
rem console o Shell do Windows ignora os.startfile() em silencio: a aba
rem nunca abre e o monitor de sessao encerra o servidor por inatividade.
rem Quem abre o navegador e este .bat, que sempre roda numa sessao de
rem console visivel. Ele inicia o executavel em paralelo (start /B, sem
rem janela nova), espera o instancia_ativa.json publicado pelo servidor,
rem le a porta e chama start na URL.
rem
rem O vinculo de encerramento continua: o executavel herda este console e
rem os filhos ficam no Job Object, entao fechar a janela dispara
rem CTRL_CLOSE_EVENT. No sentido inverso, o .bat so termina depois que o
rem registro some, ou seja, quando o servidor encerra (inatividade, botao
rem da barra lateral ou --encerrar) e nenhuma janela fica aberta.
rem ---------------------------------------------------------------------------

:iniciar_executavel

set "ASSISTENTE_DATA_DIR=%~dp0"
set "EXE_PATH=%~dp0NexusGeoIA.exe"
set "REGISTRO_INSTANCIA=%~dp0instancia_ativa.json"

rem Modos de diagnostico nao sobem servidor: rodam de forma sincrona, sem
rem esperar registro e sem abrir navegador. O codigo de saida precisa
rem voltar para o build (smoke_exe.py roda --self-test).
if /I "%~1"=="--self-test" goto :executavel_sincrono
if /I "%~1"=="--autodiagnostico" goto :executavel_sincrono
if /I "%~1"=="--autoteste" goto :executavel_sincrono
if /I "%~1"=="--smoke-test" goto :executavel_sincrono
if /I "%~1"=="--verificar-imports" goto :executavel_sincrono

echo Iniciando o NexusGeo IA...
echo.

rem Remove o registro obsoleto apenas quando nao ha NexusGeoIA.exe ativo:
rem com uma instancia viva o arquivo e a fonte da porta dela.
call :existe_executavel_ativo
if errorlevel 1 (
    if exist "%REGISTRO_INSTANCIA%" del /q "%REGISTRO_INSTANCIA%" >nul 2>&1
)

rem start /B mantem o executavel no MESMO console (nenhuma janela nova) e
rem devolve o controle para este .bat abrir a aba.
start "" /B "%EXE_PATH%" %*

set "TENTATIVAS_REGISTRO=0"

:aguardar_registro
if exist "%REGISTRO_INSTANCIA%" goto :abrir_navegador
call :existe_executavel_ativo
if errorlevel 1 goto :executavel_encerrado
set /a TENTATIVAS_REGISTRO+=1
if %TENTATIVAS_REGISTRO% GEQ 30 goto :abrir_navegador
>nul ping -n 2 127.0.0.1
goto :aguardar_registro

:abrir_navegador
set "PORTA=8501"
if not exist "%REGISTRO_INSTANCIA%" goto :porta_do_registro
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try { $p = (ConvertFrom-Json (Get-Content -Raw -LiteralPath '%REGISTRO_INSTANCIA%')).porta; if ($p -gt 0 -and $p -lt 65536) { $p } } catch { }"`) do set "PORTA=%%P"
:porta_do_registro
rem Saida inesperada do PowerShell (campo ausente ou invalido) volta para
rem a porta preferida.
echo %PORTA%| findstr /r "^[0-9][0-9]*$" >nul || set "PORTA=8501"

rem O registro e gravado antes do import do Streamlit, ainda sem socket
rem escutando; abrir a URL nesse instante mostraria pagina de erro e a aba
rem seria fechada pela inatividade. Aguarda a porta aceitar conexao (ate
rem ~30 s) e so entao abre o navegador padrao em primeiro plano.
set "TENTATIVAS_PORTA=0"

:aguardar_porta
set "SERVIDOR_PRONTO="
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "try { $c = New-Object Net.Sockets.TcpClient; $t = $c.ConnectAsync('127.0.0.1', %PORTA%); if ($t.Wait(1000) -and $c.Connected) { '1' }; $c.Close() } catch { }"`) do set "SERVIDOR_PRONTO=%%R"
if "%SERVIDOR_PRONTO%"=="1" goto :navegador_pronto
set /a TENTATIVAS_PORTA+=1
if %TENTATIVAS_PORTA% GEQ 20 goto :navegador_pronto
>nul ping -n 2 127.0.0.1
goto :aguardar_porta

:navegador_pronto
echo Abrindo o navegador em http://localhost:%PORTA%
echo.
start "" "http://localhost:%PORTA%"

rem Mantem este console vivo enquanto o servidor existir. O launcher
rem remove instancia_ativa.json ao encerrar; se o executavel morrer antes
rem de publicar o registro, a checagem de processo evita espera eterna.
:aguardar_servidor
if not exist "%REGISTRO_INSTANCIA%" goto :executavel_encerrado
call :existe_executavel_ativo
if errorlevel 1 goto :executavel_encerrado
>nul ping -n 2 127.0.0.1
goto :aguardar_servidor

:executavel_encerrado
set "CODIGO_SAIDA=0"
popd
endlocal & exit /b %CODIGO_SAIDA%

rem Modo sincrono: autoteste e afins esperam o executavel terminar para
rem devolver o codigo de saida ao build.
:executavel_sincrono
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

rem ---------------------------------------------------------------------------
rem Ha um NexusGeoIA.exe em execucao?
rem
rem tasklist + findstr devolvem 0 quando o executavel aparece na lista. A
rem checagem protege o registro de uma instancia viva e evita aguardar
rem para sempre quando o processo morre antes de publicar a porta.
rem ---------------------------------------------------------------------------

:existe_executavel_ativo
tasklist /FI "IMAGENAME eq NexusGeoIA.exe" /NH 2>nul | findstr /I /C:"NexusGeoIA.exe" >nul
if errorlevel 1 exit /b 1
exit /b 0
