@echo off
REM ============================================================================================
REM  Builds ONE installer: dist\ROVEN-Setup-1.3.0.exe   (run once, on any Windows 10/11 PC)
REM  Needs: Python 3.11 (python.org) and Inno Setup 6 (jrsoftware.org) — both free.
REM ============================================================================================
setlocal
cd /d "%~dp0\.."
if not exist .build-venv ( py -3.11 -m venv .build-venv || exit /b 1 )
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || exit /b 1
python -m pytest -q || exit /b 1
python packaging\make_icon.py || exit /b 1
pyinstaller packaging\ROVEN.spec --noconfirm --distpath dist --workpath build || exit /b 1
python packaging\fetch_models.py dist\ROVEN\models small tiny || exit /b 1
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% ( echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php then run this again. & exit /b 1 )
%ISCC% packaging\installer.iss || exit /b 1
echo.
echo  Done:  dist\ROVEN-Setup-1.3.0.exe   — copy this one file to any PC and double-click it.
