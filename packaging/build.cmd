@echo off
rem Build JotThatDown -> dist\JotThatDown\JotThatDown.exe
cd /d "%~dp0.."
.venv\Scripts\python.exe -m PyInstaller packaging\JotThatDown.spec --noconfirm
if errorlevel 1 exit /b 1
del /q "dist\JotThatDown\_internal\PySide6\resources\qtwebengine_devtools_resources.debug.pak" 2>nul
echo Done: dist\JotThatDown\JotThatDown.exe
