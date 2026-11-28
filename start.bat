@echo off
setlocal
REM ================================================================
REM  Agent Platform one-click launcher (v0.9 desktop launcher)
REM  Double-click this file to start the app.
REM  ASCII-only messages to avoid codepage garbling; see README.
REM ================================================================

set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

cd /d "%ROOT%"

if not exist "%PY%" (
    echo [ERROR] Virtualenv not found: .venv\Scripts\python.exe
    echo.
    echo First-time setup ^(once^):
    echo   1. py -3.12 -m venv .venv
    echo   2. cd backend  ^&^&  ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo   3. cd ..  ^&^&  .\.venv\Scripts\python.exe scripts\init_db.py
    echo See README for details.
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%.env" (
    echo [WARN] .env not found. Copying .env.example to .env ...
    copy /y "%ROOT%.env.example" "%ROOT%.env" >nul
    echo.
    echo Please edit .env ^(DATABASE_URL password, optional LLM_API_KEY^),
    echo then double-click start.bat again.
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\dist\index.html" (
    echo [WARN] Frontend not built: frontend\dist
    echo Build once:  cd frontend  ^&^&  npm install  ^&^&  npm run build
    echo Or run a dev server separately:  cd frontend  ^&^&  npm run dev
    echo Continuing anyway -- backend will serve API/docs only.
    echo.
)

echo [1/2] Applying database migrations ^(idempotent^) ...
pushd "%ROOT%backend"
"%PY%" -m alembic upgrade head
if errorlevel 1 (
    popd
    echo.
    echo [ERROR] Migration failed. Is MySQL running? Is .env DATABASE_URL correct?
    echo.
    pause
    exit /b 1
)
popd

echo [2/2] Starting Agent Platform ...
echo.
"%PY%" "%ROOT%backend\run.py" %*
echo.
echo Server stopped.
pause
