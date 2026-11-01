@echo off
setlocal
rem Gera Instalador_TCC.exe a partir de Instalar_TCC.cmd usando o IExpress (ja vem no Windows).
cd /d "%~dp0"
set "SED=%TEMP%\instalador_tcc.sed"
> "%SED%" echo [Version]
>> "%SED%" echo Class=IEXPRESS
>> "%SED%" echo SEDVersion=3
>> "%SED%" echo [Options]
>> "%SED%" echo PackagePurpose=InstallApp
>> "%SED%" echo ShowInstallProgramWindow=0
>> "%SED%" echo HideExtractAnimation=1
>> "%SED%" echo UseLongFileName=1
>> "%SED%" echo InsideCompressed=0
>> "%SED%" echo CAB_FixedSize=0
>> "%SED%" echo CAB_ResvCodeSigning=0
>> "%SED%" echo RebootMode=N
>> "%SED%" echo InstallPrompt=
>> "%SED%" echo DisplayLicense=
>> "%SED%" echo FinishMessage=
>> "%SED%" echo TargetName=%~dp0Instalador_TCC.exe
>> "%SED%" echo FriendlyName=Instalador TCC - Proteinas IA
>> "%SED%" echo AppLaunched=cmd /c Instalar_TCC.cmd
>> "%SED%" echo PostInstallCmd=^<None^>
>> "%SED%" echo AdminQuestion=0
>> "%SED%" echo UserQuestion=0
>> "%SED%" echo SelfDelete=0
>> "%SED%" echo NumberOfFiles=1
>> "%SED%" echo [SourceFiles]
>> "%SED%" echo SourceFiles0=%~dp0
>> "%SED%" echo [SourceFiles0]
>> "%SED%" echo %%FILE0%%=
>> "%SED%" echo [Strings]
>> "%SED%" echo FILE0="Instalar_TCC.cmd"
iexpress /N /Q "%SED%"
if exist "%~dp0Instalador_TCC.exe" (echo Gerado: %~dp0Instalador_TCC.exe) else (echo Nao foi possivel gerar o .exe. Use Instalar_TCC.cmd diretamente.)
pause
