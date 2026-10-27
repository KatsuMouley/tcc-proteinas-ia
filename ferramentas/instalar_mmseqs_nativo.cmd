@echo off
setlocal
cd /d "%~dp0.."
echo Baixando o MMseqs2 nativo do Windows para ferramentas\mmseqs ...
if not exist "ferramentas\mmseqs" mkdir "ferramentas\mmseqs"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://github.com/soedinglab/MMseqs2/releases/latest/download/mmseqs-win64.zip' -OutFile 'ferramentas\mmseqs\mmseqs.zip'; Expand-Archive -Force 'ferramentas\mmseqs\mmseqs.zip' 'ferramentas\mmseqs'; Remove-Item 'ferramentas\mmseqs\mmseqs.zip'"
if errorlevel 1 goto falhou
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import sys; sys.path.insert(0,'etapas'); import preparar_base_ia as p; e=p.exe_nativo(); print('Executavel:', e); print('Versao:', p.Backend(None).version() if e else 'NAO ENCONTRADO')"
if errorlevel 1 goto falhou
echo.
echo Pronto. Em Configuracoes, o modo "Automatico" ja usa o MMseqs2 nativo.
pause
exit /b 0
:falhou
echo ERRO ao instalar o MMseqs2 nativo. Envie as mensagens acima. O modo WSL continua funcionando.
pause
exit /b 1
