@echo off
echo ============================================
echo   Cluely Pro - Windows Build Script
echo ============================================
echo.

:: Step 1: Install Python dependencies + PyInstaller
echo [1/4] Installing Python dependencies...
cd backend
pip install -r requirements.txt pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Python dependencies
    pause
    exit /b 1
)
cd ..

:: Step 2: Bundle Python backend with PyInstaller
echo.
echo [2/4] Bundling Python backend with PyInstaller...
cd backend
python -m PyInstaller --noconfirm --clean --distpath ../python-dist --name cluely-backend main.py ^
    --hidden-import=dotenv ^
    --hidden-import=pynput ^
    --hidden-import=pynput.keyboard ^
    --hidden-import=pynput.keyboard._win32 ^
    --hidden-import=pynput.mouse ^
    --hidden-import=pynput.mouse._win32 ^
    --collect-all sounddevice ^
    --collect-all soundfile ^
    --collect-all numpy
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)
cd ..

:: Step 3: Install Node dependencies
echo.
echo [3/4] Installing Node dependencies...
call npm install
if %errorlevel% neq 0 (
    echo ERROR: npm install failed
    pause
    exit /b 1
)

:: Step 4: Build Electron app
echo.
echo [4/4] Building Electron installer...
call npx electron-builder --win
if %errorlevel% neq 0 (
    echo ERROR: electron-builder failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete!
echo   Output is in the "dist" folder.
echo ============================================
echo.
pause
