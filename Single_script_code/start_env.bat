@echo off
REM Opent de terminal in deze map met conda base actief - zoekt conda automatisch
cd /d "%~dp0"

set "CONDA_ACT="

REM 1) Bekende installatielocaties aflopen
for %%P in (
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\AppData\Local\miniconda3"
    "%USERPROFILE%\AppData\Local\anaconda3"
    "%LOCALAPPDATA%\miniconda3"
    "%LOCALAPPDATA%\anaconda3"
    "C:\ProgramData\miniconda3"
    "C:\ProgramData\Anaconda3"
    "C:\miniconda3"
    "C:\Anaconda3"
) do (
    if not defined CONDA_ACT if exist "%%~P\Scripts\activate.bat" set "CONDA_ACT=%%~P\Scripts\activate.bat"
)

REM 2) Niet gevonden? Probeer conda op PATH via 'where'
if not defined CONDA_ACT (
    for /f "delims=" %%C in ('where conda 2^>nul') do (
        if not defined CONDA_ACT (
            for %%D in ("%%~dpC..") do set "CONDA_ACT=%%~fD\Scripts\activate.bat"
        )
    )
)

if defined CONDA_ACT (
    cmd /k ""%CONDA_ACT%""
) else (
    echo Conda niet gevonden - controleer je installatie
    cmd /k
)