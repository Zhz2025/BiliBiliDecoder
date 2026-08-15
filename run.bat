@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  Bilibili Subtitle Downloader (double-click to run)
REM  Edit the options below, save, then double-click this file.
REM ============================================================

REM List file (default: list.txt)
set "LIST=list.txt"

REM Output directory (default: subtitles)
set "OUT=subtitles"

REM UP-main entries in list: ALL = all videos, or a number = recent N
set "RECENT=ALL"

REM Only process UP-main videos whose title contains this keyword (empty = no filter)
set "TAG="

REM Max results for "search:" entries in list
set "MAX=20"

REM Skip parts that are already downloaded (avoid re-transcribing). 1 = on, 0 = off
set "SKIP=1"

REM ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" goto :error_venv
if not exist "%LIST%" goto :error_list

set "CMD=.venv\Scripts\python.exe -m bilibili_decoder batch -f %LIST% --cookie-file cookie.txt --out %OUT%"
if /I "%RECENT%"=="ALL" set "CMD=%CMD% --all"
if not "%RECENT%"=="ALL" set "CMD=%CMD% --recent %RECENT%"
if not "%TAG%"=="" set "CMD=%CMD% --tag %TAG%"
set "CMD=%CMD% --max %MAX%"
if "%SKIP%"=="1" set "CMD=%CMD% --skip-existing"

if not exist cookie.txt echo [WARN] cookie.txt not found - official subtitles unavailable (STT only).

echo ============================================================
echo   Bilibili Subtitle Downloader
echo   List: %LIST%    Output: %OUT%    UP mode: %RECENT%
echo ============================================================
%CMD%
echo.
goto :done

:error_venv
echo [ERROR] .venv not found.
echo         Run: python -m venv .venv  then  pip install -r requirements.txt
goto :done

:error_list
echo [ERROR] List file not found: %LIST%
goto :done

:done
pause
