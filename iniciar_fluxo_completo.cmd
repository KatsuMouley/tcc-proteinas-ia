@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Coloque este arquivo na pasta do projeto, junto da .venv.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m sistema_tcc --abrir --novo-fluxo --limite 1000
if errorlevel 1 pause
