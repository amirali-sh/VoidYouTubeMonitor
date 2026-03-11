@echo off
setlocal enabledelayedexpansion

REM ── Find VLC install directory ──────────────────────────────────────────────
set "VLC_PATH=C:\Program Files\VideoLAN\VLC"
if not exist "!VLC_PATH!\libvlc.dll" (
    set "VLC_PATH=C:\Program Files (x86)\VideoLAN\VLC"
)
if not exist "!VLC_PATH!\libvlc.dll" (
    echo ERROR: VLC not found. Please install VLC from https://videolan.org
    pause
    exit /b 1
)
echo Found VLC at: !VLC_PATH!

REM ── Use the exact Python that has our packages ───────────────────────────────
set "PYTHON=C:\Users\AmirAli\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "!PYTHON!" (
    echo ERROR: Python not found at !PYTHON!
    pause
    exit /b 1
)
echo Using Python: !PYTHON!

REM ── Install dependencies ─────────────────────────────────────────────────────
echo Installing dependencies...
"!PYTHON!" -m pip install pyinstaller PyQt5 python-vlc yt-dlp
if errorlevel 1 (
    echo ERROR: pip failed.
    pause
    exit /b 1
)

REM ── Build ────────────────────────────────────────────────────────────────────
"!PYTHON!" -m PyInstaller --noconfirm --onedir --windowed ^
    --name "VoidYouTubeMonitor" ^
    --icon "icon.ico" ^
    --add-data "!VLC_PATH!\libvlc.dll;." ^
    --add-data "!VLC_PATH!\libvlccore.dll;." ^
    --add-data "!VLC_PATH!\plugins;plugins" ^
    --add-data "news.json;." ^
    main.py
if errorlevel 1 (
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo Build complete! Output is in dist\VoidYouTubeMonitor\
pause