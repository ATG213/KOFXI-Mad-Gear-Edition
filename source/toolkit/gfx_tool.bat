@echo off
rem KOF XI PS2 graphics replacer: starts the GUI (installs Pillow + numpy on first run if missing)
cd /d "%~dp0"
py -3 -c "import PIL, numpy" 2>nul || py -3 -m pip install pillow numpy
start "" pyw -3 gfx_app.py
