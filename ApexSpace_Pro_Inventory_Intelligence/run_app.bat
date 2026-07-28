@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONHOME=
set PYTHONNOUSERSITE=1

if not exist ".venv\Scripts\python.exe" (
  call RESET_AND_RUN.bat
  exit /b %errorlevel%
)

".venv\Scripts\python.exe" -I -c "import streamlit" >nul 2>&1
if errorlevel 1 (
  echo The local environment is incomplete. Rebuilding it now...
  call RESET_AND_RUN.bat
  exit /b %errorlevel%
)

echo Starting ApexSpace Pro at http://localhost:8505
".venv\Scripts\python.exe" -I -m streamlit run app.py --server.port 8505
