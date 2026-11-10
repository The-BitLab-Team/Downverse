@echo off
rem Cria o instalador do Downverse para Windows:
rem   1) gera o executavel com o PyInstaller  -> dist\Downverse\Downverse.exe
rem   2) monta o instalador com o Inno Setup  -> dist\Downverse-Setup-<versao>.exe
rem Se o Inno Setup nao estiver instalado, tenta instalar pelo winget; sem ele, gera um .zip portatil.
setlocal EnableExtensions
cd /d "%~dp0"
title Downverse - criar instalador

echo ==============================================
echo   Downverse - criador do instalador (Windows)
echo ==============================================
echo.

set "VENV=%~dp0.venv"
set "PYC=%VENV%\Scripts\python.exe"
set "PF86=%ProgramFiles(x86)%"
set "NOWEBVIEW="

if exist "%PYC%" goto deps

call :find_python
if not defined PY goto no_python
echo [1/4] Criando o ambiente Python...
%PY% -m venv "%VENV%"
if errorlevel 1 goto fail

:deps
echo [1/4] Instalando as dependencias e o PyInstaller...
"%PYC%" -m pip install --disable-pip-version-check -q -r requirements.txt
if not errorlevel 1 goto deps_pyinstaller
echo.
echo Aviso: a janela nativa (pywebview) nao pode ser instalada neste Python.
echo O programa gerado vai abrir no navegador padrao em vez de uma janela propria.
set "NOWEBVIEW=1"
findstr /v /i "pywebview" requirements.txt > "%TEMP%\downverse-requirements.txt"
"%PYC%" -m pip install --disable-pip-version-check -q -r "%TEMP%\downverse-requirements.txt"
if errorlevel 1 goto fail

:deps_pyinstaller
"%PYC%" -m pip install --disable-pip-version-check -q -U pyinstaller
if errorlevel 1 goto fail

"%PYC%" -c "import downverse; print(downverse.__version__)" > "%TEMP%\downverse-version.txt"
set /p VERSION=<"%TEMP%\downverse-version.txt"
if not defined VERSION goto fail

echo.
echo [2/4] Gerando o executavel (PyInstaller)...
if exist "dist\Downverse" rmdir /s /q "dist\Downverse"
if exist "build\downverse" rmdir /s /q "build\downverse"
"%PYC%" -m PyInstaller --noconfirm --clean --distpath "dist" --workpath "build" "packaging\downverse.spec"
if errorlevel 1 goto fail
if not exist "dist\Downverse\Downverse.exe" goto fail

echo.
echo [3/4] Procurando o Inno Setup...
call :find_iscc
if defined ISCC goto build_setup
echo Inno Setup nao encontrado. Tentando instalar pelo winget (pode pedir permissao de administrador)...
where winget >nul 2>nul
if errorlevel 1 goto no_inno
winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
call :find_iscc
if defined ISCC goto build_setup
goto no_inno

:build_setup
echo.
echo [4/4] Montando o instalador (Inno Setup)...
"%ISCC%" /Qp "/DAppVersion=%VERSION%" "packaging\installer.iss"
if errorlevel 1 goto fail
echo.
echo ==============================================
echo   Pronto! O instalador foi criado em:
echo   %~dp0dist\Downverse-Setup-%VERSION%.exe
echo ==============================================
if defined NOWEBVIEW echo   Lembrete: esta versao abre no navegador sem janela propria.
explorer "%~dp0dist"
echo.
pause
exit /b 0

:no_inno
echo.
echo Nao consegui obter o Inno Setup, entao o instalador (Setup.exe) nao foi criado.
echo Gerando uma versao portatil (.zip) como alternativa...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Downverse' -DestinationPath 'dist\Downverse-portatil-%VERSION%.zip' -Force"
if errorlevel 1 goto fail
echo.
echo Versao portatil: %~dp0dist\Downverse-portatil-%VERSION%.zip
echo Para criar o instalador, instale o Inno Setup 6 (https://jrsoftware.org/isdl.php)
echo e rode este arquivo de novo.
explorer "%~dp0dist"
echo.
pause
exit /b 0

:find_iscc
set "ISCC="
if exist "%PF86%\Inno Setup 6\ISCC.exe" set "ISCC=%PF86%\Inno Setup 6\ISCC.exe"
if defined ISCC exit /b 0
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC exit /b 0
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC exit /b 0
where ISCC >nul 2>nul
if not errorlevel 1 set "ISCC=ISCC"
exit /b 0

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
echo.
pause
exit /b 1
