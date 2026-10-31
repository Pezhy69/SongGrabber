@echo off
rem pushd statt cd: funktioniert auch auf Netzlaufwerken (\\NAS\...), Windows leiht dafuer kurz einen Laufwerksbuchstaben
pushd "%~dp0"
python -m pip install -r requirements.txt >nul
if not exist "bin\ffmpeg.exe" python tools\fetch_tools.py
python main.py %*
