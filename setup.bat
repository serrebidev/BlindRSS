@echo off
@REM Copyright (c) serrebidev and contributors
@REM This file is part of BlindRSS
@REM SPDX-License-Identifier: MIT

setlocal

echo [BlindRss Setup] Checking system requirements...

:: 1. Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found.
    echo [*] Attempting to install Python 3 via Winget...
    
    :: Check if Winget is available
    winget --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [X] Winget is not available. Please install Python 3.13+ manually from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    
    :: Install Python
    winget install -e --id Python.Python.3.13 --scope machine --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [X] Python installation failed. Please install manually.
        pause
        exit /b 1
    )
    
    echo [+] Python installed. You may need to restart your terminal or computer to refresh environment variables.
    echo     Please restart this script after doing so.
    pause
    exit /b 0
) else (
    echo [V] Python is present.
)

:: 2. Check for Pip
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Pip not found. Installing pip...
    python -m ensurepip --default-pip
    if %errorlevel% neq 0 (
        echo [X] Failed to install pip.
        pause
        exit /b 1
    )
) else (
    echo [V] Pip is present.
)

:: 3. Install Dependencies
echo [*] Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [X] Failed to install base requirements.
    pause
    exit /b 1
)

echo [*] Ensuring WebRTC VAD (webrtcvad) is installed...
pip install --upgrade webrtcvad
if %errorlevel% neq 0 (
    echo [X] Failed to install webrtcvad (required for skip-silence).
    pause
    exit /b 1
)

echo [*] Ensuring yt-dlp is up to date...
pip install --upgrade yt-dlp
if %errorlevel% neq 0 (
    echo [X] Failed to update yt-dlp.
    pause
    exit /b 1
)

:: 4. Check System Tools (VLC & FFmpeg)
echo [*] Checking system media tools...

:: Check VLC
if exist "%ProgramFiles%\VideoLAN\VLC\vlc.exe" (
    echo [V] VLC found.
) else if exist "%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe" (
    echo [V] VLC found.
) else (
    echo [!] VLC not found. Installing via Winget...
    winget install -e --id VideoLAN.VLC --silent --accept-package-agreements --accept-source-agreements
)

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] FFmpeg not found on PATH. Attempting install via Winget...
    winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
) else (
    echo [V] FFmpeg found.
)

:: 5. Run main.py to trigger full dependency check (final verification)
echo [*] Running application once to finalize configuration...
python main.py
if %errorlevel% neq 0 (
    echo [X] Application encountered an error during initial dependency setup.
    pause
    exit /b 1
) else (
    :: If main.py just exited, it means it finished dependency check or closed.
    :: We don't want to keep the UI running if it didn't crash.
    echo [V] Initial dependency setup complete.
)

echo [V] Setup complete! You can now run the application using: python main.py
pause
