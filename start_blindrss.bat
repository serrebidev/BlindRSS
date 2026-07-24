@echo off
@REM Copyright (c) serrebidev and contributors
@REM This file is part of BlindRSS
@REM SPDX-License-Identifier: MIT

setlocal

echo [BlindRss Launcher]
echo Checking system...

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Attempting install...
    :: Added agreement flags for silent install
    winget install -e --id Python.Python.3.13 --scope machine --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [X] Failed to install Python. Please install manually.
        pause
        exit /b 1
    )
    echo [+] Python installed. Please restart this script to initialize environment.
    pause
    exit /b
)

:: 2. Check Pip
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Pip not found. Installing...
    python -m ensurepip --default-pip
)

:: 3. Ensure WebRTC VAD dependency
pip show webrtcvad >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing webrtcvad (speech/silence detection)...
    pip install webrtcvad
)

:: 4. Run Application
echo Starting BlindRSS...
python main.py

:: 5. Pause on crash
if %errorlevel% neq 0 (
    echo.
    echo [!] Application crashed or exited with error level %errorlevel%
    pause
)
