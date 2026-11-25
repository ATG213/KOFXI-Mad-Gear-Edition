@echo off
rem Builds dist\KOFXI-PS2-Toolkit.exe (single file, no console). Needs: py -3 -m pip install pyinstaller pillow numpy
cd /d "%~dp0"
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name KOFXI-PS2-Toolkit ^
  --add-data "%~dp0gfx_catalog.json;." --add-data "%~dp0gfx_hacks.json;." --add-data "%~dp0gfx_hacks_us.json;." --add-data "%~dp0gfx_palette_fx.json;." --exclude-module scipy --exclude-module matplotlib --exclude-module pandas ^
  --distpath dist --workpath build --specpath build "%~dp0gfx_app.py"
echo.
echo Result: %~dp0dist\KOFXI-PS2-Toolkit.exe
