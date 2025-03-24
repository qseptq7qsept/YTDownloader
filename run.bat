@echo off
REM Activate the virtual environment located in the env folder next to this script
call env\Scripts\activate
if errorlevel 1 goto error

REM Run the script from the current folder
python YTDownloader.py
if errorlevel 1 goto error

goto end

:error
echo An error occurred while running YTDownloader.py.
pause

:end
