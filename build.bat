@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Builds dist\topomask\ with PyInstaller. Run from a clean checkout on Windows.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo error: the Python launcher "py" was not found. Install Python 3.10 or later from python.org.
  exit /b 1
)

if not exist .venv-build (
  py -3 -m venv .venv-build || exit /b 1
)
call .venv-build\Scripts\activate.bat || exit /b 1

python -m pip install --disable-pip-version-check --require-hashes --no-deps -r requirements-build.txt || exit /b 1
python -m PyInstaller --noconfirm --clean topomask.spec || exit /b 1
python scripts\collect_licenses.py || exit /b 1

echo.
echo Build complete: dist\topomask\topomask.exe
endlocal
