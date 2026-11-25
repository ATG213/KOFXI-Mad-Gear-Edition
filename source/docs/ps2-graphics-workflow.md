# KOF XI PS2 (JP): replacing graphics, workflow and tool guide

How to extract a graphic from the JP disc image, edit it and put it back, plus how a new graphic is located.
Worked out on 2026-11-19 (start-up logo, title logo and attract-mode logo replaced with a custom logo, all confirmed in
PCSX2 2.8.2).  The per-file facts (which file is which, formats, rectangles) are in
[`ps2-graphics-db.md`](ps2-graphics-db.md); the general PS2 notes are in [`ps2-hacking-notes.md`](ps2-hacking-notes.md).

## 1. Where things are

| What | Where |
|---|---|
| Tools | `toolkit/kofxi_gfx.py` (everything except the LOGO files), `toolkit/logo_dat.py` (LOGO0x / NEWxx) |
| Graphics database | `docs/ps2-graphics-db.md` |
| Original JP ISO (never modify) | your own dump of the disc, MD5 `2bb2d183e85964a799f3eb73b5812a71` |
| Work ISOs | always a copy, in a local `out\` folder (not in the repo) |
| Exported PNGs (game data, never committed) | a local folder of your choice for what you export: the LOGO and NEW screens, the 122 OPENING.GRC entries, menu atlases |
| Ghidra decompile, ELF, savestate dumps | a local project folder (not in the repo) |

Needs Python 3 with `Pillow`, `numpy` (and `scipy` only for the analysis snippets).  Run scripts with `python -I`.
Game data (ISO, ELF, decompile, PNG exports, savestates) is never committed.

## 2. Rules that apply to every patch

1. **Patch a copy of the ISO**, the replace commands write in place.  PCSX2 keeps the file open: close it (or use a new
   file name) before copying over an ISO it has loaded.
2. **Same size, same sector count.**  The game finds files by LBA and sector count from a table in the ELF (about 920
   entries at `0x366DE0`), not from the ISO directory.  Raw files (LOGO, NEW) are replaced byte for byte.  Packed files may
   change size as long as they stay within their sector count; inside a container the entry is padded to its old slot so no
   offset moves.
3. Test with a **cold boot**.  Savestates do not carry patched data.
4. Never trust a first guess about which file a screen uses: use the savestate method in section 5.

## 3. Recipes

### 3.1 Start-up logos and unlock screens (`DATA\LOGO\LOGO0x.DAT`, `DATA\PLUS\NEWxx.DAT`)

Raw RGBA8888, 0x140000 bytes, 640x512, 5x4 tiles of 128x128 px, alpha 0x80 = opaque.

```
python -I logo_dat.py decode LOGO04.DAT logo.png     # file -> PNG
python -I logo_dat.py encode logo.png LOGO04.DAT     # PNG (640x512) -> file
```

To get the DAT out of the ISO or into it, use the LBA from `kofxi_gfx.py tree` and read or write `LBA * 2048`; the
SNK Playmore logo is `LOGO04.DAT` at LBA 245949 (640 sectors).  The "skip start-up logos" hack keeps only this one.

### 3.1b The US disc (SLUS-21687), supported by the GUI/CLI since tool 1.13.0

The tool detects the disc version from the boot ELF (`SLPS_256.60` = JP, `SLUS_216.87` = US).  What is the same and what
differs (checked 2026-11-21 by hashing the files of both discs):

| Part | US vs JP |
|---|---|
| `DEMO/OPENING.GRC` (title logo e116 ...), `DEMO/COIN_IN1/2.BIN`, `PACK/FIGHT.BCC`, `FIGHTA.BCC`, `MENU/BG00/BG01.GRC`, `KOF_BG01.BIN`, `KOF_N.BIN`, `SPR03.GRC` | byte-identical: every JP target works unchanged (only the LBAs differ, the tool looks files up by name) |
| `MENU/SPR00-02.GRC`, `MENU/CSET.GRC`, `MC/MC00-18.DAT` | English text, other bytes; menu colours, clock and dialog recolouring ran fine on a US copy (read-back verified), in-game look not yet checked |
| Start-up logos | no `LOGO00-05.DAT`; only `DATA/LOGO/SNK.RAW` (= LOGO04) and `CRI.RAW` (ADX = LOGO03), plain **RGB24** 640x512 (4 strips of 640x128, no alpha, no header).  Transparent PNG areas become black. |
| Unlock pictures | `DATA/PLUS/NEW01..11.RAW` = JP NEW00..10, **BGR24** 640x448 (the JP picture without the 64 white padding rows).  The tool accepts 640x512 or 640x448 PNGs for both discs (crops / pads with white). |
| ELF | `SLUS_216.87`, 2037464 bytes, PT_LOAD 0x100000 (file offset 0x100); a completely different layout, so no JP hack applies |

Hacks: `gfx_hacks.json` (JP) and `gfx_hacks_us.json` (US, built by `make_us_hacks.py`).  Only **Skip intro logos** exists
for US so far.  The others (combo, practice, unlock, rematch, same chars, clock, fixps2) are JP-only until they are ported.

US start-up flow (Ghidra): boot `FUN_001d5090` -> logo player `FUN_0027dde0`: 1. SNK Playmore
(`SNK.RAW`, 180 frames, Start skips) 2. ADX (`CRI.RAW`, 180 frames; `SKILL.DAT` / `SVCTEX.DAT` are loaded while it is
shown) 3. new memory-card overwrite warning popup 4. memory card load popup 5. intro video.  The US skip hack removes
step 2 (no upload / fade / wait for the ADX picture, the SKILL/SVCTEX load stays), so SNK is shown, then the popups.
Patched instructions: `jal 0x27cf50` at 0x27DEA8, `jal 0x27DB90` at 0x27DEB0, `slti $v0,$s0,0xB4` at 0x27DF00 (bound 0),
`jal 0x27DC20` at 0x27DF10.

### 3.2 Title logo and other OPENING.GRC images (`DATA\DEMO\OPENING.GRC`, 122 entries)

```
python -I kofxi_gfx.py list-opening    "KOFXI JP.iso"
python -I kofxi_gfx.py export-entry    "KOFXI JP.iso" 116 e116.png      # the title logo, 640x256
python -I kofxi_gfx.py replace-entry   "work copy.iso" 116 e116_new.png
```

Title backgrounds are entries 121 and 122.  The PNG must have exactly the entry's size.  The tool re-packs the entry with
`maz_compress`, checks that it fits the old slot and splices the outer GRC stream only around the changed bytes
(`grc_splice`), then verifies by decoding.  If the entry does not fit, reduce the number of colours (flat colours
compress far better; 12 colours worked for a flat logo).

### 3.3 Attract-mode logo (`DATA\PACK\FIGHT.BCC` and `FIGHTA.BCC`, entry 1, HUD atlas)

```
python -I kofxi_gfx.py export-hud-atlas      "KOFXI JP.iso" hud.png      # 256 x 4096 atlas, read only
python -I kofxi_gfx.py replace-attract-logo  "work copy.iso" logo.png [scale] [dx] [dy]
```

Both BCC files must be changed (both are resident).  The logo is drawn 1:1 from four atlas pieces; the tool distributes
the new logo over them (rectangles and screen mapping in `ATTRACT_PIECES`).  Only the union of pieces A and C exists under
the middle of the logo, so the logo is fitted into 214 x 121 px and centred on the screen centre x = 320; `dx`/`dy` shift
it (Mad Gear: `dx 3`, because its visual mass is left of its bounding box).  A logo is at most 178 px wide.  Bigger would
need the engine's sprite table (not found).

### 3.3c Character colour palettes (`DATA\PACK\FIGHT.BCC` and `FIGHTA.BCC`, entries 16-62)

```
python -I gfx_palettes.py list    "KOFXI JP.iso"                    # 47 characters, palette size, sprite found
python -I gfx_palettes.py export  "KOFXI JP.iso" 00 00_ash.pal      # or .png = swatch sheet
python -I gfx_palettes.py preview "KOFXI JP.iso" 00 0 ash_a.png     # idle frame in colour 1 (A)
python -I gfx_convert.py patch SRC.iso DST.iso --palettes DIR       # every <id>_<name>.PAL of DIR
```

* Loader (JP decompile): `FUN_0012ED00` -> `FUN_0032C8B0(5, DAT_0035C2F0[char id])` -> `FUN_0012E9C0` copies colour
  `block+5` (0x200 bytes) to RAM `0x4121F0 + slot*0x200`.  Resource slot 5 = `FIGHT.BCC` or `FIGHTA.BCC`, so both files
  are patched.  Colour index 12+ = PS2 COLOR EDIT colours from the save (`0x9BF240 + char*0x400`), not in these files.
* Entry = character id 0x00-0x27 -> 16 + id, 0x29-0x2F -> 56 + (id - 0x29).  6144 bytes = 12 colours x 16 sub-palettes x
  16 x u16 (Shen Woo 6016).  Same layout as the arcade `.PAL` files; identical to the arcade palettes for 33 of the 40
  arcade characters, Duck King, Ralf, Clark, Mary, Shingo, Shion and Magaki differ (PS2-edited palettes).  The loose
  `DATA\PAL\*.PAL` / `PAL2` files are the arcade originals and are NOT what the loader uses.
* u16 = BGR555: R = bits 10-14, B = bits 0-4 (the opposite of the OPENING / HUD ARGB1555 entries).  Bit 15 is kept.
  Entry 0 of every sub-palette (row) is transparent.
* Rows: byte 0 of a sprite descriptor (section 11 of the UNI file) is the row the sprite is drawn with.  Row 0 = body,
  row 4 = the purple-blue state after Ash's LDM > 236236E follow-up (every character, 4 sprites), higher rows =
  projectiles, flames, helpers.  Rows 1-3 are used by no sprite and showed no visible effect in tests (electric, fire
  and ice hits, LDM).
* Space: SNK's GRC stream of the palette range is about 9 KB larger than ours, so re-encoding makes room; a full
  channel swap of all 12 colours still shrinks the file.  Attract logo and palettes can be patched together.
* Preview: descriptor 0 of section 11 in `DATA\PLA|PLA2\xxxx.UNI` is the first idle frame of every character (Yuri:
  descriptor 1).  Section 22 = linear 4 bpp 8x8 tiles (32 bytes, low nibble first); a descriptor = u8[4] (+0 row,
  +2 width, +3 height in tiles) then records `u16 tile, run, column, row` (vertical runs).  Everything is rendered at
  run time from the user's ISO, no game graphics are shipped.  JP and US discs: same files.  The console data
  (`DATA\PL|PL2`) has a few more or other sprites for some characters (Duck King's P-chan: console sprite 320, row 8;
  in the arcade data it is not in Duck King's own UNI file but somewhere else); the preview uses the arcade data (`PLA`), a named entry `[sprite, name, "PL"]` in
  `gfx_palette_fx.json` points to a console sprite.

**GUI tab "Character palettes".**  Pick a character and a colour (1 A ... 12 Start+D) and click a swatch to change it;
changed swatches get a red border, "Original" and "Yours" are shown side by side.  Pointing at a swatch highlights the
pixels it colours.  Below the body there is an effect preview: a list of named sprites per character (projectiles,
helpers such as Jenet's crew, Duck King's P-chan, Kula's Foxy and Diana, from `gfx_palette_fx.json`) plus the automatic
"Ash LDM>236236E hit" entry; `<` `>` browses every effect sprite, "all sprites" also lists sprites in body colours.  The
names right of each swatch row show which listed sprites use that row (several sprites can share a row; changing it
changes all of them, as in the game).

* This colour: copy from another colour, reset, import, and **export as a common palette file** with 256 colours
  (16 rows x 16 entries): JASC `.pal` (Paint Shop Pro, GIMP, Aseprite, GraphicsGale, ...), `.gpl` (GIMP, Krita,
  Inkscape) or `.act` (Photoshop).  Import reads these plus Microsoft RIFF `.pal`; entry 0 of each row and bit 15 are
  always kept from the game data.  GIMP: Palettes > Import Palette > Palette file; GIMP saves the edited palette as
  `.gpl` in its own palettes folder (`%APPDATA%\GIMP\<version>\palettes`), import that file back.
* Whole character: import a palette with all 12 colours or a swatch PNG (16 cells wide, one row per sub-palette, any
  cell size), export the game `.PAL` (same format as the arcade files), the swatch PNG or a preview PNG.
* Every change is saved at once as `<id>_<name>.PAL` in the palettes folder (tab "Folders (optional)", default
  `<ready folder>\palettes`); the file is removed again when it equals the original.  Tab 2 patches all files of that
  folder into both BCC files and reads them back.
* Curator mode (for maintaining the sprite list): `"curator": true` in `gfx_tool_config.json` shows "Add shown sprite
  to list" / "Remove from list"; they write a `gfx_palette_fx.json` next to the exe / script that replaces whole
  characters of the bundled list.

### 3.5 GUI and batch tool (`gfx_app.py`, `gfx_convert.py`)

Start `toolkit/gfx_tool.bat` (needs Python 3; installs Pillow and numpy on first run).  All folders are chosen
in the app and saved in `gfx_tool_config.json` next to it; the folders (tab "Folders (optional)") are only needed if
you replace graphics or character colours.

1. **Convert** tab: pick a graphic (keys `LOGO00-05`, `NEW00-10`, `e001-e122`, `attract`), pick your PNG.  The app checks
   size, format, transparency, colours and (for OPENING entries) whether it fits the maz slot, shows original and
   "as the game shows it" side by side, and offers to scale a wrong-size PNG or reduce colours when needed.  OK files are
   written to the ready folder as `KEY.png`.  Slot sizes and entry headers come from `gfx_catalog.json`, so no ISO is
   needed for this step.  The "Original" preview is decoded straight from the input ISO (`gfx_convert.extract_original`,
   all 149 JP / 145 US targets), "Save original as PNG" writes it as a template, so nothing has to be exported first.
2. **Patch** tab: input ISO, output ISO (new file, never the input), an optional graphics folder; every PNG whose name starts with a known
   key is listed, ticked files are written to the copy, then read back and compared.  Several OPENING entries share one
   OPENING.GRC; the app checks the total against its sector limit.  `e116` is the only entry tested in the emulator,
   the others are marked experimental.

**Exe.** `toolkit/build_exe.bat` builds `dist\KOFXI-PS2-Toolkit.exe` (one file, about 30 MB, no
Python needed; the exe keeps `gfx_tool_config.json` next to itself).  `dist/` and `build/` are not committed and no
exe is distributed.  Adding a new graphic target:
1. Add the target: new OPENING entries only need `gfx_targets.py make-catalog` (or the ranges text in
   `gfx_targets.py`); a new kind of file (new container, new format) needs its own `kind` in `gfx_targets.py`, a
   check in `check_png` and a writer in `apply_jobs` of `gfx_convert.py`.
2. Test with the CLI (`gfx_convert.py patch ... --folder`), mark the target `experimental` until it ran in the emulator,
   then change it to `verified`.
3. Bump `TOOL_VERSION` in `gfx_targets.py` and rebuild the exe if you use one.
A `gfx_catalog.json` placed next to the exe overrides the bundled one, so pure catalog updates (new sizes / slots)
do not need a new exe.

**Game hacks in the Patch tab.** Checkboxes for the hacks (same characters, quick rematch, unlock all characters, combo
damage display, better practice mode, skip intro logos, version display, fix PS2 differences; the clock hack sits in the
main menu box) patch the ELF and a few menu files of the output ISO, so a clean ISO can get graphics, menu colours and
hacks in one run.  The patches come from `gfx_hacks.json`, a byte table exported from `toolkit/make_combo_dmg_ps2.py`
with `export_hack_patches.py` (no keystone needed in the exe; re-run the export after changing a hack).  The export
checks that all patches together equal the builder's output.  A hack that is already in the base ISO is reported as
"already applied"; unexpected bytes abort.  CLI: `--hack rematch --hack unlock` or `--all-hacks`.

**Colour order (fixed 2026-11-19).** The 87 ARGB1555 OPENING entries have red in the low bits; early exports with red
and blue swapped were wrong (and the encoder truncated levels, darkening unchanged pixels by one step).  Both are fixed
in `kofxi_gfx.py`; e121 is really blue, e122 green.

CLI of the same engine: `python -I gfx_convert.py check FILE.png [--fit] [--quantize]` and
`python -I gfx_convert.py patch SRC.iso DST.iso --folder DIR [--only e116,attract] [--fit] [--quantize] [--force]`.
Verified on the JP ISO 2026-11-19: batch of LOGO04, NEW0A, e001, e116, e121 and the attract logo, read back identical.
`gfx_targets.py make-catalog ISO` regenerates the catalog.

### 3.3b Title screen after skipping the intro (`DATA\DEMO\COIN_IN1.BIN`, `COIN_IN2.BIN`)

Pressing Start during the intro video or in the attract mode does NOT show the title screen from OPENING.GRC: the game
loads `COIN_IN1.BIN` / `COIN_IN2.BIN` (identical copies at different LBAs, 714752 bytes, plain container with 3 maz entries):
entry 1 = orange burst background (640x448 ARGB1555), entry 2 = pink burst background (same size), entry 3 = the title logo
(same pixels as OPENING e116, only the 4 byte size field in the entry header differs).  The "normal" title screen uses the
blue / green bursts e121 / e122 of OPENING.GRC, so the title cycles through four colour sets overall.  The graphics tool
writes the e116 logo into entry 3 of both files automatically and offers the targets `coinA` / `coinB` for the two
backgrounds.  Found with PINE RAM snapshots + a write breakpoint (the decoded OLD logo sat at 0xA9C080, its compressed source
at 0xA83740 was found in COIN_IN1/2.BIN by a whole-ISO search).

### 3.4 Menu atlases (`DATA\MENU\SPR0x.GRC`, `BG0x.GRC`)

`kofxi_gfx.py export-menu "KOFXI JP.iso" DATA/MENU/SPR01.GRC out.png` exports an atlas.  Editing is done by `gfx_menu.py`
(also in the GUI: the "Main menu colours and animations" box on tab 2 and the `clock` target), details in its docstring:

- **UI colour** (`--ui-color cb0608`): the orange of the menu is palette data only (gradient of 127 CLUT entries in the
  first CLUT of SPR00..02, flat `ffb03f` in the second-page CLUTs for the selected row, entry 254 of BG00, one RGBA
  palette entry in KOF_BG01.BIN @0x60C38 / KOF_N.BIN @0x19A7F8 for the rotating ring text).  Entries 12 and 31 lie inside
  the gradient range but are NOT orange (31 = green ring centre).
- **Menu animations off** (`--disable-menu-anim`): KOF_BG01.BIN is the 3D scene of the main menu; every node record starts
  with `MDL-alpha01.<node>` and has its scale (3 floats) at name + 0xB0.  Scale 0 hides it: `kaiten` = swirly background,
  `naka` = rotating "THE KING OF FIGHTERS XI" ring with its background and orange outer line.  Never set other nodes to 1.0
  (t30 0.386, t40 1.535).  KOF_N.BIN is a second scene (`kaiten_1`), not checked yet.
- **Clock sprite** (`clock` target / `--clock PNG`): the target ring with the hand and the green dot is one 185 x 187
  sprite at x 67..251, y 3..189 of the page-0 atlas (identical in SPR00, SPR01, SPR02), rotated by the game around its
  centre.  230 palette entries are used by it alone and get re-used for the new picture (median cut; fewer colours are
  tried until all three files fit their sector count).
- **Black background** (`--black-menu-bg`): hides the node `MDL-obj.cube50` (338 x 223 x 223, the white panel behind the
  buttons) and turns palette entry 255 of BG00 (white outer margin) black.  Do NOT blacken entry 0 of BG00: that is the
  transparent window interior and BG00 is drawn over the buttons.  `--disable-menu-anim` also hides `b01`..`b03` (three
  drifting white dots, only visible on black).
- **Frame / outer margin colours**: the grey frame is palette entry 253 of BG00.GRC (`--frame-color`), the white area outside it
  is entry 255 of BG00.GRC and BG01.GRC (`--margin-color`).  The white *inside* box (`cube50`) cannot be tinted: changing its
  material colour `bg01.mat1` (floats 1,1,1 at name + 0x20 of the second `bg01.mat1` record) had no effect on the hue (white
  in the main menu, grey in other menus), so only "white" or "black" (cube hidden) is offered for the inside.
- **Clock rotation**: with the no-spin hack the clock sprite is drawn turned 90 degrees counter-clockwise (frozen counter
  value), so the tool rotates the replacement 90 degrees clockwise first (`--clock-rotate 90`, Tab 1 "rotate before
  inserting").  Rotated images compress worse (LZ window 255): the colour reduction therefore goes down to 3 colours.
- **Clock does not spin** (hack `clockspin`): code at 0x3313B8 moves the clock pointer counter (object +0x10, step +0xC = +-1
  per frame, 16..166 ping-pong, +0x14 = frames left); `addu v0,v1,v0` at 0x331404 became `addu v0,v1,zero`.  Found with a
  write breakpoint in the PCSX2 debugger on the counter (0x92F814) after PINE snapshots (RAM diff after one cursor press each).
- Found live with PCSX2 PINE (Settings > Advanced > Enable PINE, TCP 28011): write the scale of a node to 0 in RAM and
  watch the menu.  RAM address of a node name = file offset + 0x9ED840.

## 4. File formats in short (details: `ps2-graphics-db.md`)

| Format | Layout |
|---|---|
| GRC (outer, `.GRC` `.LZ`) | byte LZ: `b < 0xC0` literal; `0xC0 | n`: n = 0 end, n = 1 next byte literal, else copy n bytes from `dst - nextbyte`; decoder `FUN_001A43F0` |
| BCC | `[u32 unpacked size][GRC stream]` (compressed `.BIN`) |
| maz (entries of OPENING.GRC) | `[u32 unpacked size]` then flag bytes, 8 items MSB first: 0 = literal, 1 = reference byte (distance `16 - (b >> 4)`, length `b & 15`, 0 means 16); decoder `FUN_001986E0`, length table at `0x3DE930` |
| Container | `u32 count`, `u32 offsets[count]`, entries |
| OPENING entry (decoded) | 0x40 header (`+0xC` data offset, `+0x10/+0x12` tile w/h = 64, `+0x14/+0x15` tile cols/rows, `+0x18 == 2` RGBA32 else ARGB1555) then 64x64 tiles row-major |
| HUD atlas (FIGHT.BCC entry 1) | PVR header, then 256 x 4096 linear ARGB1555, PS2 channel order (R bits 0-4), bit 15 opaque, transparent = `0x03E0` |
| Menu atlas | CLUT 0x400 bytes (CSM1 swizzle: swap entries 8-15 and 16-23 per 32) + linear 8 bpp, 256 px wide |

## 5. Finding where a new graphic lives (what worked)

1. Take two PCSX2 savestates (`.p2s`, zip with zstd; unpack with Windows `tar.exe -xf state.p2s -C dir`): the screen
   in question.  `eeMemory.bin` is the 32 MiB EE RAM, `GS.bin` ends with the 4 MiB VRAM (offset 509, hardware renderer
   keeps frames on the GPU, only uploaded textures are in it).
2. `kofxi_gfx.py resident "KOFXI JP.iso" eeMemory.bin` lists the disc files (raw or unpacked) whose contents are in RAM:
   the title screen used `OPENING.GRC`, the attract mode `FIGHT.BCC`/`FIGHTA.BCC`.
3. Decode the candidate with the tools and look at it (a contact sheet of all entries is the fastest way).  A colour scan
   of the RAM dump for the picture's own colours finds decoded copies (the title logo atlas sat at EE `0x1240000`).
4. Unknown packing: use the PCSX2 debugger (Debug > Breakpoints).  A **write breakpoint on the decoded copy** found the
   `maz` decoder (the first hits are `memset`/`memcpy` at `0x127120..0x127380`, press Run until the PC is elsewhere), then
   read that function in the Ghidra decompile.  A read breakpoint on the compressed data first stops in `memcpy`.
5. For a piece-wise sprite (attract logo): a **probe ISO** that paints candidate atlas regions in solid colours shows in a
   screenshot which regions are drawn and where; template matching of the atlas against the unmodified savestate
   screenshot (masked SSD, scale 1) gives exact screen offsets.  Keep overwrite rectangles away from other sprites (the
   portrait icons ended at atlas row 3839).

## 6. Gotchas

- `python -I` ignores the current directory and `PYTHON*` variables; pass absolute paths.
- The ISO directory size of a file is not updated when a packed file changes size (the game does not use it).
  `kofxi_gfx.py` reads whole sectors, as the game does.
- PS2 alpha is 0..0x80; ARGB1555 colour order is R in the low bits (Dreamcast PVR order is the opposite: wrong colours
  show red and blue swapped).
- Dreamcast "twiddle" does not apply to the PS2 `PVRT` data; those textures are linear strips.
- Tested in PCSX2 2.8.2 and on a real PS2 (OPL) with the Mad Gear Edition.
