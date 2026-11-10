@echo off
rem Abre o Downverse direto desta pasta (Windows).
rem Primeira vez: cria o ambiente Python (.venv) e instala as dependencias. Depois abre na hora.
rem Para ver mensagens de erro na tela, rode:  iniciar.bat debug
setlocal EnableExtensions
cd /d "%~dp0"
title Downverse

set "VENV=%~dp0.venv"
set "PYC=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "INSTALLED=%VENV%\requirements.instalado.txt"

if exist "%PYC%" goto deps

call :find_python
if not defined PY goto no_python
echo Criando o ambiente do Downverse (so na primeira vez)...
%PY% -m venv "%VENV%"
if errorlevel 1 goto fail

:deps
rem Reinstala as dependencias apenas quando o requirements.txt mudou.
fc /b "requirements.txt" "%INSTALLED%" >nul 2>nul
if not errorlevel 1 goto launch
echo Instalando as dependencias (pode demorar alguns minutos)...
"%PYC%" -m pip install --disable-pip-version-check -q -r requirements.txt
if not errorlevel 1 goto deps_ok
echo.
echo Nao foi possivel instalar a janela nativa (pywebview).
echo Tentando sem ela: o Downverse vai abrir no navegador padrao.
findstr /v /i "pywebview" requirements.txt > "%TEMP%\downverse-requirements.txt"
"%PYC%" -m pip install --disable-pip-version-check -q -r "%TEMP%\downverse-requirements.txt"
if errorlevel 1 goto fail
:deps_ok
copy /y "requirements.txt" "%INSTALLED%" >nul

:launch
if /i "%~1"=="debug" goto debug
start "" "%PYW%" -m downverse
exit /b 0

:debug
"%PYC%" -m downverse
echo.
pause
exit /b %errorlevel%

:find_python
set "PY="
where py >nul 2>nul
if errorlevel 1 goto fp_python
py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY exit /b 0
:fp_python
where python >nul 2>nul
if errorlevel 1 exit /b 1
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
exit /b 0

:no_python
echo.
echo Python 3.10 ou mais novo nao foi encontrado.
echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH"
echo e abra este arquivo de novo.
echo.
pause
exit /b 1

:fail
echo.
echo Algo deu errado (veja as mensagens acima).
echo Rode "iniciar.bat debug" para ver os detalhes.
echo.
pause
exit /b 1
