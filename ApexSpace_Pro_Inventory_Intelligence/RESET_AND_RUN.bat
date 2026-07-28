@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONHOME=
set PYTHONNOUSERSITE=1

echo Closing any old ApexSpace server on port 8505...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8505" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

if exist ".venv" (
  echo Removing old local environment...
  rmdir /s /q ".venv"
)

echo Creating a clean Python 3.11 environment...
py -3.11 -m venv .venv
if errorlevel 1 goto :error

echo Installing clean packages. This can take a few minutes...
".venv\Scripts\python.exe" -I -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -I -m pip install --no-cache-dir --force-reinstall -r requirements.txt
if errorlevel 1 goto :error

echo Verifying package locations...
".venv\Scripts\python.exe" -I -c "import sys, streamlit, jinja2, altair, pandas; print('Python:', sys.executable); print('Streamlit:', streamlit.__file__); print('Jinja2:', jinja2.__file__); print('Pandas:', pandas.__file__)"
if errorlevel 1 goto :error

echo Starting ApexSpace Pro at http://localhost:8505
".venv\Scripts\python.exe" -I -m streamlit run app.py --server.port 8505
exit /b 0

:error
echo.
echo Setup failed. Confirm Python 3.11 is installed and that this folder contains requirements.txt.
pause
exit /b 1
