@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt uvicorn
echo Open http://127.0.0.1:8000  (Ctrl+C to stop)
python -m uvicorn asset_hierarchy.web.app:app --host 127.0.0.1 --port 8000
