@echo off
rem Builds dist\KOFXI-MadGear-Patcher.exe (single file, no console). Needs: py -3 -m pip install pyinstaller
rem First create payload.bin:
rem   python isodiff.py ORIGINAL.iso MADGEAR.iso runs.json
rem   python make_patcher.py ORIGINAL.iso MADGEAR.iso --runs runs.json
cd /d "%~dp0"
if not exist payload.bin goto nopayload
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name KOFXI-MadGear-Patcher --add-data "payload.bin;." madgear_patcher.py
echo.
echo Result: %~dp0dist\KOFXI-MadGear-Patcher.exe
goto :eof
:nopayload
echo payload.bin is missing, see the comment at the top of this file.
