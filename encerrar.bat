@echo off
rem ---------------------------------------------------------------------------
rem Encerra imediatamente o NexusGeo IA.
rem
rem Le instancia_ativa.json (pasta de dados), mata a arvore do servidor
rem Streamlit e remove o registro. Funciona tanto no pacote portatil
rem (NexusGeoIA.exe --encerrar) quanto no modo desenvolvimento
rem (launcher_desktop.py --encerrar). Se o servidor ja tiver encerrado
rem sozinho ao fechar a ultima aba, apenas limpa o registro.
rem
rem Este arquivo acompanha o pacote gerado por packaging\build_portatil.ps1
rem ao lado de iniciar.bat.
rem ---------------------------------------------------------------------------

setlocal
pushd "%~dp0"

call "%~dp0iniciar.bat" --encerrar
set "CODIGO_SAIDA=%ERRORLEVEL%"

if not "%CODIGO_SAIDA%"=="0" (
    echo.
    echo [AVISO] Nao foi possivel confirmar o encerramento do NexusGeo IA.
    echo         Verifique o Gerenciador de Tarefas.
    echo.
    pause
)

popd
endlocal & exit /b %CODIGO_SAIDA%
