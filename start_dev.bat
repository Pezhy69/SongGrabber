@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt >nul
if not exist "bin\ffmpeg.exe" python tools\fetch_tools.py
python main.py %*
