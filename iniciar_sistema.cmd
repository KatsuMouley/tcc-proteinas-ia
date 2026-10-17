@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo O Python do projeto nao foi encontrado. Coloque este arquivo em C:\ai_tcc.
    pause
    exit /b 1
)
echo Acordando o WSL (Ubuntu) para o MMseqs2...
wsl.exe --distribution Ubuntu --exec mmseqs version >nul 2>&1
if errorlevel 1 echo AVISO: MMseqs2 no WSL nao respondeu. A etapa 2 do fluxo pode falhar.
".venv\Scripts\python.exe" -m sistema_tcc --abrir
if errorlevel 1 pause
