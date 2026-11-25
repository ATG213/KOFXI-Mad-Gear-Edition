# KOF XI Mad Gear Edition: source (PS2 and Atomiswave arcade)

The Mad Gear Edition is a modified version of **The King of Fighters XI**, named after the Mad Gear fighting game dojo in
Frankfurt: quick rematch, all characters unlocked, the same character several times in a team, a combo damage display,
a much better practice mode (PS2) and more. This repository holds the tools that build it. Ready-made patchers for players are on the
[releases page](https://github.com/ATG213/KOFXI-Mad-Gear-Edition/releases); you only need this repository if you want to
build, study or extend the hacks.

**No game data is included.** You need your own dump of the Japanese PS2 disc (SLPS-25660) or your own original arcade
program ROM `ax3201p01.fmem1`. Requirements: Python 3 (the GUI needs `tkinter`, which comes with the Windows installer).

| Folder | Contents |
|---|---|
| `toolkit/` | PS2: KOF XI PS2 Toolkit (GUI `gfx_app.py`, command line `gfx_convert.py`, character palettes `gfx_palettes.py` / `gfx_palette_tab.py`), the hack byte tables `gfx_hacks.json` / `gfx_hacks_us.json`, and the generators `make_combo_dmg_ps2.py` (builds all PS2 hacks, despite its name; parts in `hitbox_ps2.py`, `frameadv_ps2.py`, `ukemi_ps2.py`) and `export_hack_patches.py` |
| `patcher/` | PS2: self-patcher GUI (`madgear_patcher.py`), delta tools (`isodiff.py`, `make_patcher.py`), PPF writer (`make_ppf.py`) |
| `arcade/hacks/` | Atomiswave: the hack scripts, `build_arcade_rom.py` (original ROM in, Mad Gear ROM out), cipher and checksum tools |
| `arcade/patcher/` | Atomiswave: self-patcher GUI (`aw_patcher.py`) and its delta builder |
| `docs/` | PS2: [hack patch table](docs/hack-patch-table.md), [graphics database](docs/ps2-graphics-db.md), [graphics workflow](docs/ps2-graphics-workflow.md), [reverse engineering notes](docs/ps2-hacking-notes.md). Arcade: [build guide](docs/arcade-build.md), [quick rematch](docs/arcade-quick-rematch.md), [combo damage display](docs/arcade-combo-damage.md) |

## PS2: the toolkit

    pip install -r requirements.txt
    cd toolkit
    python gfx_app.py        (or gfx_tool.bat on Windows)

Pick your disc image, tick the hacks you want, click Patch: a new ISO is written, your original is never changed.
Replacing graphics (logos, title screen, menu colours) is optional and described in the
[graphics workflow](docs/ps2-graphics-workflow.md); the originals are shown straight from your disc image and can be
saved as PNG templates.

### Character palettes

The tab **Character palettes** recolours the 12 colours of all 47 characters (the palettes live in
`PACK/FIGHT.BCC` and `FIGHTA.BCC`, JP and US disc). Everything is read from your own disc image:

- a preview of each character (first frame of the idle stance) and of their effects, Original and Yours side by side;
  named effect sprites per character (projectiles, flames, helpers such as Jenet's crew, Duck King's P-chan, Kula's
  Foxy and Diana) and the purple-blue state after Ash's LDM follow-up;
- click a swatch to change it, point at it to see which pixels it colours; every row shows which listed sprites use
  it; copy, import or reset single colours or the whole character;
- export / import as common palette files (JASC `.pal` for GIMP, Aseprite, Paint Shop Pro and others, `.gpl` for GIMP /
  Krita / Inkscape, `.act` for Photoshop), as a swatch PNG or in the game's own `.PAL` format;
- changes are saved in the palettes folder and patched into the new ISO on the Patch tab.

Details, formats and the reverse engineering behind it: [graphics workflow, section 3.3c](docs/ps2-graphics-workflow.md).

### Toolkit settings

All folders are chosen in the app; settings are saved to
`gfx_tool_config.json` next to the script (or `~/.kofxi_gfx_tool.json`). Menu labels use Arial Black from the Windows font
folder; set `KOFXI_LABEL_FONT` to a `.ttf` path to use another font. `toolkit/build_exe.bat` builds a single-file exe with
PyInstaller (no exe is distributed with this repository).

## PS2: regenerate the hack table (developers)

    pip install -r requirements-dev.txt
    cd toolkit
    python -I export_hack_patches.py "KOFXI JP.iso" gfx_hacks.json

The check inside asserts that all exported patches together equal the builder's output. The hack "Fix PS2 differences"
patches disc files instead of the ELF; it is not generated here, and the export keeps its entry in an existing
`gfx_hacks.json`. To build the ELF hacks into an ISO without the app:

    python -I make_combo_dmg_ps2.py --iso "KOFXI JP.iso" --out-iso OUT.iso        (set PYTHONUTF8=1 on Windows)

## PS2: patcher and PPF (for releases)

A release contains only the byte differences to the original disc, never a game image. Build the finished ISO with the
toolkit first, then:

    cd patcher
    python isodiff.py ORIGINAL.iso MADGEAR.iso runs.json
    python make_ppf.py MADGEAR.iso runs.json MadGear.ppf --apply ORIGINAL.iso check.iso      (PPF, with a self-test)
    python make_patcher.py ORIGINAL.iso MADGEAR.iso --runs runs.json                          (payload.bin)
    build_exe.bat                                                                              (patcher exe, needs PyInstaller)

## Arcade: build the ROM

    cd arcade/hacks
    python build_arcade_rom.py ORIGINAL_ax3201p01.fmem1 NEW_ax3201p01.fmem1

No extra packages needed. Details, the patcher and the checksum fix for real hardware (AW Multi):
[docs/arcade-build.md](docs/arcade-build.md).

## License

[CC BY-NC-SA 4.0](LICENSE): free for any noncommercial use, modification and sharing with credit to ATG; changed
versions must use the same license; commercial use is not permitted. The HIT BOX drawer is based on the code of Vans
([kofxi-international](https://github.com/vans1belmont/kofxi-international), CC BY-NC-SA 4.0, used with his permission),
its colours follow the hitbox viewer of [odabugs](https://github.com/odabugs). This covers the code and docs of this
repository only, not the game or its assets (no SNK Playmore data is included; you need your own disc dump). The cipher tables in `arcade/hacks/aw_crypto.py` are ported from MAME and stay
under their original BSD-3-Clause license (see the header of that file). Unofficial, not affiliated with SNK Playmore.
