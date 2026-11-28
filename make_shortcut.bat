@echo off
setlocal
REM ================================================================
REM  Create a desktop shortcut "Agent Platform" -> start.bat (v0.9)
REM  Run once; afterwards double-click the desktop icon to start.
REM ================================================================

set "ROOT=%~dp0"
set "TARGET=%ROOT%start.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path $d 'Agent Platform.lnk')); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%ROOT%'; $s.Description='Agent Platform one-click launcher'; $s.Save()"

if errorlevel 1 (
    echo [ERROR] Failed to create the desktop shortcut.
    pause
    exit /b 1
)

echo Done. Desktop shortcut "Agent Platform" created.
pause
