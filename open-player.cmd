@echo off
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 "%~dp0viewer\server.py" %*
) else (
    python "%~dp0viewer\server.py" %*
)
if errorlevel 1 pause
