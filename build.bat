@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo === SongGrabber Build ===

for /f "delims=" %%v in ('python -c "from agcore.paths import VERSION; print(VERSION)"') do set "VER=%%v"
if not defined VER goto :err
echo Version %VER%
python tools\check_release.py
if errorlevel 1 (
  echo.
  choice /m "Trotzdem weiterbauen"
  if errorlevel 2 goto :err
)

python -m pip install --upgrade -r requirements.txt pyinstaller || goto :err
rem Optional: Titel/Cover/Steuerung von Spotify & Co. ("Alles am PC")
python -m pip install --upgrade winrt-runtime winrt-Windows.Foundation winrt-Windows.Media.Control winrt-Windows.Storage.Streams >nul 2>&1
set "WINRT="
python -c "import winrt.windows.media.control" >nul 2>&1 && set "WINRT=--collect-all winrt"
if not defined WINRT echo Hinweis: Windows-Mediensteuerung nicht verfuegbar - "Alles am PC" zeigt dann keine Titel an.

if not exist "bin\ffmpeg.exe" python tools\fetch_tools.py
if not exist "bin\yt-dlp.exe" python tools\fetch_tools.py
if not exist "bin\fpcalc.exe" python tools\fetch_tools.py
if not exist "bin\ffmpeg.exe" goto :err

rem Portable-Einstellungen aus einem frueheren Build sichern (PyInstaller leert den Ordner)
if exist "dist\SongGrabber\data" (
  if exist "_data_backup" rmdir /s /q "_data_backup"
  move "dist\SongGrabber\data" "_data_backup" >nul
)

python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name SongGrabber --icon assets\icon.ico ^
  --add-data "ui;ui" --add-data "assets;assets" ^
  --collect-all soundcard --collect-submodules mutagen --hidden-import numpy %WINRT% ^
  main.py || goto :err

rem Werkzeuge neben die .exe legen
xcopy /e /i /y bin "dist\SongGrabber\bin" >nul
copy /y LIZENZEN.txt "dist\SongGrabber\" >nul
rem Zwischenordner entfernen
if exist build rmdir /s /q build
if exist SongGrabber.spec del /q SongGrabber.spec

rem ---------------- 1) Installationsprogramm (Setup.exe) ----------------
call :findiscc
if not defined ISCC (
  echo.
  echo Inno Setup wird einmalig installiert, um das Setup zu bauen ...
  winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
  call :findiscc
)
if defined ISCC (
  "%ISCC%" /Q /DAppVersion=%VER% "installer\SongGrabber.iss" || goto :err
  echo Setup: Setup\SongGrabber-Setup-%VER%.exe
) else (
  echo.
  echo HINWEIS: Inno Setup nicht gefunden - Setup.exe wurde nicht erstellt.
  echo Bitte von https://jrsoftware.org/isdl.php installieren und build.bat erneut starten.
)

rem ---------------- 2) Portable Version (Ordner zum Mitnehmen) -----------
type nul > "dist\SongGrabber\portable.txt"
if exist "_data_backup" move "_data_backup" "dist\SongGrabber\data" >nul

echo.
echo ============================================================
if defined ISCC echo  Installieren:  Setup\SongGrabber-Setup-%VER%.exe
echo  Portabel:      dist\SongGrabber\SongGrabber.exe
echo ============================================================
if exist "Setup" (start "" explorer "Setup") else (start "" explorer "dist\SongGrabber")
pause
exit /b 0

:findiscc
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
exit /b 0

:err
echo.
echo Build fehlgeschlagen.
pause
exit /b 1
