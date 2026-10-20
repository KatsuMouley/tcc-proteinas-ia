@echo off
rem Experimento EC7 (separado do painel). Uso: rodar_ec7.cmd [tudo|coletar|preparar|treinar|resumo]
chcp 65001 >nul
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente .venv nao encontrado. Rode instalar.cmd na raiz do projeto.
  pause
  exit /b 1
)
wsl.exe --distribution Ubuntu --exec mmseqs version >nul 2>&1
set "ACAO=%~1"
if "%ACAO%"=="" set "ACAO=tudo"
".venv\Scripts\python.exe" -X utf8 experimentos\ec7\rodar_ec7.py %ACAO%
echo.
pause
