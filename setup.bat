@echo off
echo.
echo  ╔══════════════════════════════════╗
echo  ║     Cluely Pro — Setup (Win)     ║
echo  ╚══════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    exit /b 1
)

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    exit /b 1
)

:: Install Python dependencies
echo [1/3] Installing Python dependencies...
pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies
    exit /b 1
)

:: Install Node dependencies
echo [2/3] Installing Node dependencies...
call npm install
if errorlevel 1 (
    echo [ERROR] Failed to install Node dependencies
    exit /b 1
)

:: Setup .env
echo [3/3] Setting up environment...
if not exist .env (
    copy .env.example .env >nul
    echo Created .env file — please add your GROQ_API_KEY
    echo Get your free key at: https://console.groq.com/keys
) else (
    echo .env already exists, skipping
)

:: Verify WASAPI loopback
echo.
echo Checking WASAPI loopback...
python -c "import sounddevice; print('Audio devices:', len(sounddevice.query_devices()))" 2>nul
if errorlevel 1 (
    echo [WARNING] Could not query audio devices
) else (
    echo WASAPI loopback should be available by default on Windows
)

echo.
echo ══════════════════════════════════════
echo  Setup complete!
echo.
echo  Next steps:
echo    1. Edit .env and add your GROQ_API_KEY
echo    2. Terminal mode:  python backend\main.py
echo    3. Overlay mode:   npm start
echo ══════════════════════════════════════
echo.
