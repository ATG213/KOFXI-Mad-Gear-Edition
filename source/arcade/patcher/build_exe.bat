@echo off
rem Builds dist\KOFXI-MadGear-AW-Patcher.exe (single file, no console).
rem Needs: py -3 -m pip install pyinstaller
rem First create payload.bin:  python make_aw_patcher.py ORIGINAL_ax3201p01.fmem1 HACKED_ax3201p01.fmem1
rem (HACKED = output of ..\hacks\build_arcade_rom.py)
cd /d "%~dp0"
if not exist payload.bin goto nopayload
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name KOFXI-MadGear-AW-Patcher --add-data "payload.bin;." --exclude-module numpy --exclude-module PIL aw_patcher.py
echo.
echo Result: %~dp0dist\KOFXI-MadGear-AW-Patcher.exe
goto :eof
:nopayload
echo payload.bin is missing, see the comment at the top of this file.
