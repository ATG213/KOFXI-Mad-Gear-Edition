# KOF XI PS2 (JP): graphics database

Which graphic is which file, how it is stored, and whether it can already be edited and written back.
All paths are relative to `\DATA\` on the JP disc (SLPS-25660) unless stated otherwise. LBAs are 2048-byte sectors
from the unmodified JP ISO. Exported PNGs are not part of the repo
(game data is never committed); export them from your own disc with the commands in the workflow guide. Last update: 2026-11-23. How to extract and re-import, tool commands and the method for
finding a graphic: [`ps2-graphics-workflow.md`](ps2-graphics-workflow.md).

Status values: **editable** = PNG to file to ISO round trip works (verified), **readable** = can be decoded to PNG but
no encoder yet, **unknown** = not analysed, **not found** = searched but not located.

## 1. Formats

| Format | Used by | Description | Tool |
|---|---|---|---|
| Raw RGBA | `LOGO\LOGO0x.DAT`, `PLUS\NEWxx.DAT` | 0x140000 bytes, no header, 640x512, 5x4 tiles of 128x128 px (tile = col + row*5), alpha 0x80 = opaque | `toolkit/logo_dat.py` |
| GRC / LZ / BCC | `.GRC`, `.LZ`, `.BCC` | Byte LZ: `b < 0xC0` literal; `0xC0 \| n`: n=0 end, n=1 next byte literal, n>=2 copy n bytes from `dst - nextbyte`. Decoder is `FUN_001A43F0`, files are read raw by `FUN_001A3F30` into the end of the buffer and unpacked from there. | `toolkit/kofxi_gfx.py` (`grc_decompress`, `grc_splice`) |
| Menu atlas (inside GRC) | `MENU\SPR0x.GRC`, `BG0x.GRC` | After unpacking: 0x400 bytes CLUT (256 x RGBA, alpha 0x40..0x80; CSM1 order, swap entries 8-15 with 16-23 in every group of 32) followed by linear 8 bpp pixels, 256 px wide (BG0x: 640 px wide) | `kofxi_gfx.py export-menu` |
| GRC table | `PACK\PS.GRC`, `PACK\ORDER.GRC`, `DEMO\OPENING.GRC`, `DEMO\STAFF.GRC` | After unpacking: u32 count, then `count` u32 entry offsets (first entry at 0x100 / 0x200) | partial |
| PVR texture | entries of `PACK\PS.GRC` | `GBIX` + `PVRT` (Dreamcast/Atomiswave PVR): entry 1 = 1024x1024 ARGB1555 twiddled, 2-7 = 64x64 ARGB4444, 8-54 = 256x256 8 bpp palettised | readable (16 bit), palettised not yet |
| maz (inner) | entries of `DEMO\OPENING.GRC` | flag-byte LZSS, dist 1..16, len 1..16, see section 3 | `toolkit/kofxi_gfx.py` (`maz_decompress`, `maz_compress`) |
| KOF BIN / BCC | `MENU\KOF_N.BIN`, `MENU\KOF_BG01.BIN`, `BG_BIN\KOF_0x.BIN` | 3D model scenes (strings like `MDL-alpha01.all01_4_1_2`, `bg01.mat5`) with a leading type table; `.BCC` is the compressed form of the same `.BIN` (first u32 = unpacked size) | unknown |

## 2. Files

### Start-up logos (editable, 640x512)

| File | LBA | Content | Status |
|---|---|---|---|
| `LOGO\LOGO00.DAT` | 243389 | KDDI / Multi Matching BB | editable |
| `LOGO\LOGO01.DAT` | 244029 | GameSync SDK | editable |
| `LOGO\LOGO02.DAT` | 244669 | ACCESS NetFront | editable |
| `LOGO\LOGO03.DAT` | 245309 | ADX (CRI) | editable |
| `LOGO\LOGO04.DAT` | 245949 | **SNK Playmore** (first logo kept by the skip-logos hack) | editable |
| `LOGO\LOGO05.DAT` | 246589 | KOF 10th Anniversary medal | editable |

### Unlock screens (editable, 640x512)

`PLUS\NEW00.DAT` to `NEW10.DAT` (17 files, 1,310,720 bytes each): green background with a character artwork and the
text "X ga shiyou kanou ni narimashita" (X is now available). Order seen so far: 00 Gai Tendo, 01 Sho Hayate,
02 Adelheid, 03 Silber, 04 Jazu, 05 Shion, 06 Magaki, 07 Mai Shiranui, 08 Robert, 09 Mr. Big, 0A Geese, 0B Hotaru Futaba, 0C Tung Fu Rue, 0D EX Kyo, 0E gallery / character text (Japanese info screen), 0F gallery / ending unlock, 10 "all elements unlocked" (assumed, to be confirmed). Same format as `LOGO0x.DAT`.

### Main menu and system UI (readable)

| File | Unpacked size | Content |
|---|---|---|
| `MENU\SPR00.GRC` | 0x1E3C00 | All menu UI atlas pages (menu buttons, key config, ranking fonts, gallery thumbnails, numbers) as stacked 256x1024 pages |
| `MENU\SPR01.GRC` | 0x40800 | Main menu atlas: target ring, MAIN MENU / GAME OPTION / GALLERY / RANKING / PRACTICE buttons |
| `MENU\SPR02..05.GRC` | 0x40800 each | other 256-wide menu pages (not yet reviewed) |
| `MENU\SPR06.GRC` | 0xA1400 | 2 x 256x... UI pages |
| `MENU\BG00.GRC`, `BG01.GRC` | 0x4B400 | 640x480 window frames (grey, green with "Complete") |
| `MENU\CSET.GRC` | 0x134E40 | character set icons / portraits (not yet reviewed) |

### Other packs

| File | Content | Status |
|---|---|---|
| `PACK\PS.GRC` | Character select (Player Select) textures: 1024x1024 background, 64x64 icons, 47 x 256x256 palettised textures | readable (partly) |
| `PACK\ORDER.GRC` | Team order screen, 50 entries | unknown |
| `PACK\LOAD.GRC` | Loading screen, 2 entries | unknown |
| `PACK\FIGHT.BCC`, `FIGHTA.BCC` | Fight HUD: entry 1 = HUD atlas (attract logo), entries 16-62 = the 47 character palettes (see workflow 3.3c) | attract logo + **palettes editable** |
| `DEMO\OPENING.GRC` | Opening / title assets, 122 images (KOF logos, **title logo = entry 116**, title backgrounds, art) | **editable** per entry, see section 3 |
| `DEMO\STAFF.GRC` | Staff roll, 48 entries | unknown |
| `GALLERY\*\*.GRC` | Gallery art / character / ending images | unknown |
| `WIN\*.LZ` | Win screen backgrounds and character busts | unknown |
| `CONT\*`, `OVER\*`, `RAND\*`, `RANKING\*` | Continue, game over, random select, ranking screens (`.LZ` + `.MDP`) | unknown |

## 3. Title screen and attract logo (title logo solved: editable)

Target: the green-and-yellow "THE KING OF FIGHTERS XI" logo, shown (a) on the title screen over the burst
background and (b) in the attract mode over a stage.

**Title logo = `DEMO\OPENING.GRC`, entry 116 (640x256 RGBA32).** It is replaceable with
`toolkit/kofxi_gfx.py` (verified: PNG to ISO to PNG is pixel identical, only that entry changes).
The attract-mode logo is a different artwork in `PACK\FIGHT.BCC` / `FIGHTA.BCC` (see below).

### OPENING.GRC (2 layers)

1. Outer layer: GRC-LZ over the whole file, decoder `FUN_001A43F0`. Result is a 6,689,984 byte container: `u32 count (123)`,
   `u32 offsets[123]`, entries (first entry at 0x200).
2. Entry 0 is the demo script / table (not an image). Entries 1..122 are **maz** streams:
   `[u32 unpacked size][flag byte, 8 items MSB first]` where a 0 bit is a literal byte and a 1 bit is a
   one-byte reference: distance = 16 - (b >> 4) (1..16), length = b & 15 (0 means 16), overlapping byte copy.
   Decoder `FUN_001986E0` (found with a PCSX2 write breakpoint on the decoded atlas, then `memset` hits skipped);
   the length table is at `0x3DE930` (16,1,2,...,15). Verified byte-exact against the decoded entry in EE RAM.
3. Decoded entry: 0x40 byte header (`'maz' 02`, `+0xC` data offset 0x40, `+0x10/+0x12` u16 tile w/h (64x64),
   `+0x14/+0x15` tile columns/rows, `+0x18 == 2` means RGBA32 tiles (alpha 0x80 opaque), else ARGB1555), then the tiles
   row-major. Image size = cols*64 x rows*64.

### Entries

| Entries | Content |
|---|---|
| 001-008 | KOF 94, 95, 96, 97, 98, 99, 2000, 2001 logos (256x128) |
| 009-010 | KOF 2002 and 2003 logos |
| 011-020 | white masks / glow versions of the same logos |
| 021 | "THE KING OF FIGHTERS EPISODE XI" disc emblem (448x448) |
| 022-025 | Ash Crimson: rune on sleeve, sleeve, artwork (black & white), name |
| 026-028 | Iori Yagami: crescent, artwork (black & white), name |
| 029-033 | Kyo Kusanagi: solar eclipse (3 parts), artwork (black & white), name |
| 034-037 | burning circle, K' artwork (black & white), K' name, bird rune emblem |
| 038-040 | Elisabeth sleeve and artwork (black & white), Oswald artwork (colored) |
| 041-049 | playing card, diamond pattern background, Momoko (pink), brown slash, Momoko silhouette, Terry and Ryo portraits, blue/red swirl (2 colors and fullscreen) |
| 050-073 | artworks of Duck King, B.Jenet, Kensou (050-052), the same three in 3 pieces each (053-061), Vanessa, Ramon, Eiji in 3 pieces each (062-070), Vanessa, Ramon, Eiji artwork (071-073) |
| 074-079 | name captions: Duck King, Eiji, B.Jenet, Kensou, Ramon, Vanessa |
| 080-087 | portraits and big artworks of Ash, Kyo, K', Iori |
| 088-115 | burning hand animation, 7 frames each: Ash, Kyo, K', Iori |
| **116** | **KOF XI title logo, 640x256 RGBA32** |
| **117** | KOF XI logo white glow / mask version, 576x256 |
| 118, 120 | light burst effects (320x256) |
| 119 | blank 640x512 |
| 121, 122 | title burst backgrounds, orange and green (640x448) |

### Replacing an entry

```
python -I kofxi_gfx.py export-entry  "KOFXI JP.iso" 116 logo.png            (read only)
python -I kofxi_gfx.py replace-entry "KOFXI JP copy.iso" 116 logo_new.png    (patches the ISO in place, work on a copy)
```

- The PNG must have exactly the entry size (116: 640x256). Alpha 0 is transparent, 255 opaque (stored as 0..0x80).
- The new entry must compress into the old entry's slot (`maz_compress` is a minimum-item parse, usually smaller than
  the original encoder; smooth anti-aliased art may not fit, reduce the colour count, 12 colours worked for a flat logo).
  The slot is padded, so no offsets in the container move.
- The outer GRC stream is only re-encoded around the changed entry (`grc_splice`); the new file must fit its original
  sector count (the ELF file table holds sectors, so the file must not grow past it). Size was 5,885,223 of 5,885,952 bytes.

### Attract-mode logo (FIGHT.BCC / FIGHTA.BCC, entry 1)

The attract logo is **not** OPENING.GRC entry 116. It is drawn 1:1 from the HUD atlas: `PACK\FIGHT.BCC` and
`PACK\FIGHTA.BCC` (both resident in the attract savestate, both must be patched). Format: `[u32 unpacked size][GRC-LZ]`,
decoded container = `u32 count (63)`, offsets (first at 0x100). Entry 1 is a PVR (`GBIX`/`PVRT`, 1024x1024 header) whose
data is really a **256 x 4096 linear ARGB1555 atlas** in PS2 channel order (R bits 0-4, G 5-9, B 10-14, bit 15 = opaque;
transparent pixels are stored as 0x03E0). It also holds the fight HUD: numbers, "K.O.", "DREAM CANCEL", portraits.

How the four pieces were found: a probe ISO that paints atlas regions in solid colours (magenta, yellow, cyan) and a
screenshot of the attract mode, then template matching of the atlas against the unmodified savestate screenshot
(masked SSD, 1:1 scale). Pieces (atlas rows/cols to screen position in the 640x480 PCSX2 frame):

| Piece | Atlas rows | Atlas cols | Screen = (y + dy, x + dx) | Content |
|---|---|---|---|---|
| A | 2998-3082 | 0-256 | dy -2864, dx +228 | upper half, includes the "THE KING OF FIGHTERS XI" line |
| C1 / C2 | 3826-3892 (x 0-188) / 3840-3892 (x 188-256) | 0-256 | dy -3632, dx +228 | lower half (C2 stays below the portrait icons that end at row 3839) |
| B | 3584-3648 | 176-256 | dy -3376, dx -28 | lower left spike |
| D | 2788-2820 | 208-256 | dy -2608, dx -28 | upper left corner |

These are the **overwrite rectangles** (generous, so no old pixel survives); the real art of each piece is a bit smaller.
Under the middle of the logo only A and C exist (screen x 231-445, y 135-256); B and D just cover the two left
spikes. The old art therefore extended to y 270 only at the far left. The new logo is fitted into the A+C area
(214 x 121) and centred on the screen centre x = 320 (the area's own middle is x = 338, which looked 18 px too far
right in v2), so it may be at most 178 px wide; B and D are made transparent; fitting the whole 329 x 136 box cuts off the bottom (seen in the first test).
The attract logo is a separate, smaller artwork (about 0.55 x the title logo, no (R) mark), not the title image squashed.

Replace it with any PNG (transparent background, cropped to its content and fitted into the 214 x 121 area, centred):

```
python -I kofxi_gfx.py replace-attract-logo "KOFXI JP copy.iso" logo.png [scale] [dx] [dy]
(dx/dy shift in game pixels after centring; Mad Gear looked off-centre because its visual mass is ~3 px left of its
bounding box centre, so v4 uses dx 3: bounding box centre 323.5, centroid 320.3 on a 320 screen centre)
```

Both BCC files get the same change; sizes stay below their sector limit (FIGHT.BCC 1,393,869 of 1,423,360). First test
(329x136 canvas, narrow rectangles) showed the new logo with old pixels left at the left
spikes and one black pixel at the right edge, and a cut-off bottom: fixed by the rectangles above. Confirmed in PCSX2 (2026-11-19): a clean attract logo, title logo and start-up logo.

### Savestate method used to find it

Unpack the PCSX2 `.p2s` with `tar`; every GRC/LZ/BCC of the disc was unpacked and probed against `eeMemory.bin`
(`kofxi_gfx.py resident`) to find which file the screen uses; the decoded logo atlas was then located by colour
scan (title state: `0x1240000` to `0x12F0000`), and a PCSX2 write breakpoint on `0x1280000` showed the decoder.

Ruled out: `LOGO0x`, `NEWxx`, `MENU\SPR00..06`, `MENU\BG00/01`, `PACK\PS.GRC`. `MENU\KOF_N.BIN` / `KOF_BG01.BIN` are
3D model scenes (`MDL-alpha01...`). Attract mode loads the stage (`BG\BG03.BCC`) and the fight HUD (`PACK\FIGHT.BCC`).

## 4. Working notes

- The disc directory is read with an ISO9660 walk (`Iso` and `iso_files` in `kofxi_gfx.py`), which gives `name, LBA, size`; all graphics files are
  stored in place, so a replacement of identical size can be written straight to `LBA * 2048` in a copy of the ISO.
  Compressed files (GRC/LZ) change size when re-packed, so they need either a packer that is no bigger than the
  original or a rebuilt ISO directory.
- `FUN_001A3DB0(path, buf)` reads a file raw; `FUN_001A3F30(path, buf, size)` reads and unpacks with `FUN_001A43F0`.
- The ELF holds a 920-entry file table at `0x366DE0` (name pointer, LBA, size), so the game reads files by LBA, not by
  walking the ISO directory.
