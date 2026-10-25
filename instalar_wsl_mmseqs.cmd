@echo off
rem Instala WSL + Ubuntu + MMseqs2 (so para agrupar e rodar fluxos novos; a consulta nao precisa).
rem Pode rodar varias vezes: o que ja estiver pronto e pulado.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ferramentas\instalar_wsl_mmseqs.ps1"
echo.
pause
