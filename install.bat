@echo off
REM Create a Python virtual environment called "env"
python -m venv env
if errorlevel 1 goto error

REM Activate the virtual environment
call env\Scripts\activate
if errorlevel 1 goto error

REM Install yt-dlp and PySide6 into the virtual environment
pip install yt-dlp PySide6
if errorlevel 1 goto error

echo Installation complete! -q7
pause
goto end

:error
echo An error occurred during installation.
pause

:end
