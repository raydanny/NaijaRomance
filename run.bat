@echo off
echo ========================================
echo   NaijaRomance - Nigerian Dating Site
echo ========================================
echo.

REM Check if virtual environment exists
IF NOT EXIST ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo Creating default avatar...
python create_default_avatar.py

echo.
echo Starting NaijaRomance...
echo Open your browser and go to: http://localhost:5000
echo Press Ctrl+C to stop the server.
echo.
python app.py

pause
