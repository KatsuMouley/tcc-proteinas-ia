@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Coloque este arquivo na pasta do projeto, junto da .venv.
    pause
    exit /b 1
)
echo Acordando o WSL (Ubuntu) para o MMseqs2...
wsl.exe --distribution Ubuntu --exec mmseqs version >nul 2>&1
if errorlevel 1 echo AVISO: MMseqs2 no WSL nao respondeu. A etapa 2 do fluxo pode falhar.
".venv\Scripts\python.exe" -m sistema_tcc --abrir --novo-fluxo --limite 1000
if errorlevel 1 pause
