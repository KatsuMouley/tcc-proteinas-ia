@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo O Python do projeto nao foi encontrado. Coloque este arquivo em C:\ai_tcc.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m sistema_tcc --abrir
if errorlevel 1 pause
