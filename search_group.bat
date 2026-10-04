@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Disable QuickEdit for THIS window only (clicking the window would otherwise
REM pause the running download until you press Enter).
if exist "%~dp0disable_quickedit.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0disable_quickedit.ps1" 2>nul

REM ============================================================
REM  Group Subtitle Downloader
REM  Search by keyword, put ALL results into ONE folder:
REM      <OUT>\group_<keyword>\
REM  Edit the options below, then double-click this file.
REM ============================================================

REM Output root directory
set "OUT=subtitles"

REM Skip already-downloaded videos (1 = on, 0 = off)
set "SKIP=1"

REM ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" goto :error_venv
if not exist cookie.txt echo [WARN] cookie.txt not found - official subtitles unavailable (STT only).

echo ============================================================
echo   Group Subtitle Downloader
echo   All results go into ONE folder under %OUT%\
echo ============================================================
echo.

set "KEYWORD="
set /p "KEYWORD=Search keyword: "
if not defined KEYWORD goto :no_keyword

set "COUNT="
set /p "COUNT=How many results [20]: "
if not defined COUNT set "COUNT=20"

set CMD=.venv\Scripts\python.exe -m bilibili_decoder search "%KEYWORD%" --max %COUNT% --group --cookie-file cookie.txt --out %OUT%
if "%SKIP%"=="1" set CMD=%CMD% --skip-existing

echo.
echo --------------------------------------------
echo   Keyword : %KEYWORD%
echo   Count   : %COUNT%
echo   Folder  : %OUT%\group_%KEYWORD%\
echo --------------------------------------------
%CMD%
echo.
goto :done

:no_keyword
echo [ERROR] Keyword cannot be empty.
goto :done

:error_venv
echo [ERROR] .venv not found.
echo         Run: python -m venv .venv  then  pip install -r requirements.txt
goto :done

:done
pause
