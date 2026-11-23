r"""PS2 JP main menu edits: UI colour, switch off the 3D animations, replace the clock sprite.

All three work on a COPY of the ISO (written in place).  Findings (2026-11-19, savestates + live PCSX2 PINE writes):

* UI colour: the orange of the menu lives in palettes only.  DATA/MENU/SPR00..03.GRC are 8 bpp atlases with a 256 entry
  CLUT per 512 row page (CSM1 swizzle: entries 8-15 and 16-23 swapped in every group of 32).  The orange is a gradient
  of 127 entries (base ffb251 towards a light peach, button shine) in the first CLUT of SPR00..02, a flat ffb03f in the
  second-page CLUTs (selected row), one entry in BG00.GRC (window frame line) and one raw RGBA entry in
  KOF_BG01.BIN @0x60C38 and KOF_N.BIN @0x19A7F8 (rotating ring text).  All of them are recoloured, the shade steps
  of the gradient are kept.
* Animations: DATA/MENU/KOF_BG01.BIN is the 3D scene of the main menu.  Every node record starts with the name
  'MDL-alpha01.<node>' and holds its scale (x, y, z as floats) at name + 0xB0.  Scale 0 hides a node:
  kaiten = the swirly pattern behind the menu, naka = the rotating "THE KING OF FIGHTERS XI" ring text with its
  background and the orange outer line, b01..b03 = the three white dots with a ring that drift around.
  (Never write scale 1.0 into other nodes: t30 0.386, t40 1.535, naka 0.404.)
* Alphabets: orange text fill f07500 / turquoise 34c6b6 in the CLUTs of SPR00..06 (FONT_SETS); the memory card and network
  dialogs (DATA/MC, DNAS0/1, KDDI, NET_MES0-2, 3 CLUTs each) use an orange ramp from dark brown to ffde97 around ffad00
  with the window border fdb152 (dialog_colors).
* Frame: the grey window frame (outer border of the menu) is palette entry 253 of BG00.GRC (aaaaaa).
* Black background: the white panel behind the menu buttons is the huge node 'MDL-obj.cube50' (scale 338 x 223 x 223,
  material bg01.mat1); with it hidden the frame is black.  The white outer margin is palette entry 255 of BG00.GRC
  (entry 0 of BG00 is the transparent window interior: do NOT make it black, BG00 is drawn OVER the buttons).
* Clock: the target ring with the hand and the green dot is NOT a 3D node but one sprite of the page-0 atlas of
  SPR00, SPR01 and SPR02 (identical there): x 67..251, y 3..189 (185 x 187, the circle fills the box and the sprite
  is rotated around its centre by the code).  230 palette entries of that page are used by the clock only, they are
  re-used for the new graphic (colours are reduced with median cut; a smaller palette is tried when the compressed
  file would not fit the sector count of the file).
"""
import os
import re
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kofxi_gfx as G

BASE_OLD = (0xFE, 0xB2, 0x51)
GRC_FILES = ['DATA/MENU/SPR00.GRC', 'DATA/MENU/SPR01.GRC', 'DATA/MENU/SPR02.GRC', 'DATA/MENU/SPR03.GRC']
BIN_PATCHES = [('DATA/MENU/KOF_BG01.BIN', 0x60C38), ('DATA/MENU/KOF_N.BIN', 0x19A7F8)]
SCENE_PATH = 'DATA/MENU/KOF_BG01.BIN'
HIDE_NODES = ('kaiten', 'naka', 'b01', 'b02', 'b03')
CLOCK_FILES = ['DATA/MENU/SPR00.GRC', 'DATA/MENU/SPR01.GRC', 'DATA/MENU/SPR02.GRC']
CLOCK_RECT = (67, 3, 252, 190)          # x0, y0, x1, y1 (exclusive) in the 256 x 512 page-0 pixel area
CLOCK_SIZE = (CLOCK_RECT[2] - CLOCK_RECT[0], CLOCK_RECT[3] - CLOCK_RECT[1])     # 185 x 187
PAGE_ROWS = 512
CLOCK_DEPTH = 255       # LZ candidates per position for the clock (the files are nearly full)


# ---------------------------------------------------------------- helpers
def parse_color(text):
    """'cb0608', '#CB0608', '0xcb0608' -> (203, 6, 8) or None when invalid."""
    t = (text or '').strip().lstrip('#')
    if t.lower().startswith('0x'):
        t = t[2:]
    if not re.fullmatch(r'[0-9a-fA-F]{6}', t):
        return None
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def swz(i):
    """CSM1 swizzle: swap entries 8-15 with 16-23 inside every group of 32 (its own inverse)."""
    k = i & 31
    if 8 <= k < 16:
        return i + 8
    if 16 <= k < 24:
        return i - 8
    return i


def lighten(c, new):
    """Colour of a gradient entry c, re-based on the new main colour (same lightening step)."""
    t = min(1.0, max(0.0, (c[2] - BASE_OLD[2]) / (255 - BASE_OLD[2])))
    return bytes(round(x + t * (255 - x)) for x in new)


def gradient_preview(color, steps=8):
    """The colours a recoloured button gradient runs through (for the GUI preview)."""
    return [tuple(lighten((255, 255, 0x51 + round(i * (255 - 0x51) / (steps - 1))), color)) for i in range(steps)]


def _load(iso, path):
    lba, size = iso.find(path)
    sectors = (size + 2047) // 2048
    raw = iso.read(lba, sectors * 2048)
    d, used = G.grc_decompress(raw)
    return lba, sectors, raw[:used], d


def _write_grc(iso, lba, sectors, stream, old, new, path, log, depth=48):
    first = next(i for i in range(len(old)) if old[i] != new[i])
    last = max(i for i in range(len(old)) if old[i] != new[i]) + 1
    ns = G.grc_splice(stream, new, first, last, depth)
    chk, _ = G.grc_decompress(ns)
    if chk != new:
        raise SystemExit(path + ': GRC splice verification failed')
    if len(ns) > sectors * 2048:
        raise SystemExit('%s: %d bytes do not fit its %d sectors (%d bytes)' % (path, len(ns), sectors, sectors * 2048))
    iso.f.seek(lba * 2048)
    iso.f.write(ns + bytes(sectors * 2048 - len(ns)))
    return len(ns), sectors * 2048


def _is_clut(d, o):
    al = d[o + 3:o + 0x400:4]
    return set(al) <= {0, 0x40, 0x80} and sum(1 for a in al if a) > 200


# ---------------------------------------------------------------- UI colour
def recolor(iso_path, color, log=print):
    """Recolour the orange main colour of the menu to color = (r, g, b)."""
    iso = G.Iso(iso_path, write=True)
    try:
        d = _load(iso, 'DATA/MENU/SPR01.GRC')[3]
        ref = {}
        for i in range(5, 132):
            f = swz(i)
            if not (d[4 * f] >= 0xF0 and d[4 * f + 1] > d[4 * f + 2] + 0x20):
                continue    # entries 12 and 31 sit in the range but are not orange (31 is the green ring centre)
            ref.setdefault(d[4 * f + 2], set()).add((d[4 * f], d[4 * f + 1]))

        def flat(r, gg, b):
            return r >= 0xFD and abs(gg - 0xB0) <= 2 and abs(b - 0x3F) <= 2    # flat orange of the selected row

        def match(r, gg, b):
            return flat(r, gg, b) or (b in ref and any(abs(r - x) <= 1 and abs(gg - y) <= 1 for x, y in ref[b]))

        for path in GRC_FILES:
            lba, sectors, stream, d = _load(iso, path)
            nd = bytearray(d)
            n = 0
            for o in range(0, len(d) - 0x400 + 1, 0x400):
                if not _is_clut(d, o):
                    continue
                for i in range(256):
                    c = d[o + 4 * i:o + 4 * i + 3]
                    if flat(*c):
                        nd[o + 4 * i:o + 4 * i + 3] = bytes(color)
                        n += 1
                    elif match(*c):
                        nd[o + 4 * i:o + 4 * i + 3] = lighten(c, color)
                        n += 1
            nd = bytes(nd)
            if nd != d:
                _write_grc(iso, lba, sectors, stream, d, nd, path, log)
            log('UI colour: %s, %d palette entries' % (path, n))
        lba, sectors, stream, d = _load(iso, 'DATA/MENU/BG00.GRC')
        nd = bytearray(d)
        nd[4 * swz(254):4 * swz(254) + 3] = bytes(color)
        _write_grc(iso, lba, sectors, stream, d, bytes(nd), 'DATA/MENU/BG00.GRC', log)
        log('UI colour: DATA/MENU/BG00.GRC window frame line')
        for path, off in BIN_PATCHES:
            lba, size = iso.find(path)
            iso.f.seek(lba * 2048 + off)
            b = iso.f.read(4)
            if b[:3] != bytes.fromhex('ffb251'):
                raise SystemExit('%s: unexpected bytes at 0x%X (not the clean JP disc, or recoloured twice)' % (path, off))
            iso.f.seek(lba * 2048 + off)
            iso.f.write(bytes(color) + b[3:])
            log('UI colour: %s palette entry' % path)
        iso.f.flush()
    finally:
        iso.f.close()


# ---------------------------------------------------------------- animations
def hide_animations(iso_path, log=print, nodes=HIDE_NODES):
    iso = G.Iso(iso_path, write=True)
    try:
        lba, size = iso.find(SCENE_PATH)
        data = iso.read(lba, size)
        for n in nodes:
            m = re.search(rb'MDL-alpha01\.' + re.escape(n.encode()) + rb'\x00', data)
            if not m or m.start() > 0x44000:
                raise SystemExit('%s: node %s not found (not the JP disc?)' % (SCENE_PATH, n))
            off = m.start() + 0xB0
            old = struct.unpack_from('<3f', data, off)
            iso.f.seek(lba * 2048 + off)
            iso.f.write(bytes(12))
            iso.f.seek(lba * 2048 + off)
            if iso.f.read(12) != bytes(12):
                raise SystemExit('write check failed for node ' + n)
            log('main menu animation off: node %s (scale %.3f -> 0)' % (n, old[0]))
        iso.f.flush()
    finally:
        iso.f.close()


def recolor_frame(iso_path, color, log=print):
    """Grey window frame of the menu (BG00.GRC palette entry 253, aaaaaa) -> color = (r, g, b)."""
    iso = G.Iso(iso_path, write=True)
    try:
        lba, sectors, stream, d = _load(iso, 'DATA/MENU/BG00.GRC')
        f = 4 * swz(253)
        if d[f:f + 3] != bytes((0xAA, 0xAA, 0xAA)):
            raise SystemExit('BG00.GRC: entry 253 is not the grey frame colour (not the clean JP disc?)')
        nd = bytearray(d)
        nd[f:f + 3] = bytes(color)
        _write_grc(iso, lba, sectors, stream, d, bytes(nd), 'DATA/MENU/BG00.GRC', log)
        log('frame colour: BG00.GRC grey frame -> #%02x%02x%02x' % tuple(color))
        iso.f.flush()
    finally:
        iso.f.close()


MARGIN_FILES = ['DATA/MENU/BG00.GRC', 'DATA/MENU/BG01.GRC']


def margin_color(iso_path, color, log=print):
    """Outer margin of the menu windows (white palette entry 255 of BG00.GRC and BG01.GRC) -> color = (r, g, b)."""
    iso = G.Iso(iso_path, write=True)
    try:
        for path in MARGIN_FILES:
            lba, sectors, stream, d = _load(iso, path)
            f = 4 * swz(255)
            if d[f:f + 3] != bytes((0xFF, 0xFF, 0xFF)):
                raise SystemExit('%s: palette entry 255 is not white (not the clean JP disc, or changed twice)' % path)
            nd = bytearray(d)
            nd[f:f + 3] = bytes(color)
            _write_grc(iso, lba, sectors, stream, d, bytes(nd), path, log)
            log('outer margin colour: %s -> #%02x%02x%02x' % ((path,) + tuple(color)))
        iso.f.flush()
    finally:
        iso.f.close()


FONT_FILES = ['DATA/MENU/SPR%02d.GRC' % i for i in range(7)]
# text colours of the menu alphabets (palette entries, found by scanning every CLUT of the menu atlases):
#   orange alphabet (labels like CPU-LEVEL):   fill f07500, darker shade c05a00
#   turquoise alphabet (values like NORMAL):   fill 34c6b6 / 33c4b4, darker shade 00b7a3
FONT_SETS = {
    'orange': {'fill': [(0xF0, 0x75, 0x00)], 'dark': [(0xC0, 0x5A, 0x00)]},
    'teal': {'fill': [(0x34, 0xC6, 0xB6), (0x33, 0xC4, 0xB4)], 'dark': [(0x00, 0xB7, 0xA3)]},
}


def _near(c, t, tol=2):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(c, t))


def font_colors(iso_path, colors, log=print):
    """Recolour the menu alphabets.  colors = {'orange': (r, g, b) or None, 'teal': (r, g, b) or None}.  The darker
    shade of a font (shadow / second tone) becomes 80 percent of the new colour; if a CLUT has only the dark shade, that
    shade is the main colour of that font and becomes the picked colour itself."""
    iso = G.Iso(iso_path, write=True)
    try:
        for path in FONT_FILES:
            lba, sectors, stream, d = _load(iso, path)
            nd = bytearray(d)
            counts = {k: 0 for k in colors}
            for o in range(0, len(d) - 0x400 + 1, 0x400):
                if not _is_clut(d, o):
                    continue
                ent = [d[o + 4 * i:o + 4 * i + 3] for i in range(256)]
                for name, new in colors.items():
                    if not new:
                        continue
                    sets = FONT_SETS[name]
                    fills = [i for i in range(256) if any(_near(ent[i], t) for t in sets['fill'])]
                    darks = [i for i in range(256) if any(_near(ent[i], t) for t in sets['dark'])]
                    if not fills and not darks:
                        continue
                    if not fills:
                        # fonts that only use the darker shade (record input screen of the practice mode): that
                        # shade is the main colour there, so it gets exactly the picked colour
                        fills, darks = darks, []
                    dark = bytes(round(c * 0.8) for c in new)
                    for i in fills:
                        nd[o + 4 * i:o + 4 * i + 3] = bytes(new)
                    for i in darks:
                        nd[o + 4 * i:o + 4 * i + 3] = dark
                    counts[name] += len(fills) + len(darks)
            if bytes(nd) != d:
                _write_grc(iso, lba, sectors, stream, d, bytes(nd), path, log)
                log('font colours: %s %s' % (path, ', '.join('%s %d entries' % kv for kv in counts.items() if kv[1])))
        iso.f.flush()
    finally:
        iso.f.close()


DIALOG_GROUPS = ('DATA/MC/', 'DATA/DNAS0/', 'DATA/DNAS1/', 'DATA/KDDI/', 'DATA/NET_MES0/', 'DATA/NET_MES1/',
                 'DATA/NET_MES2/')
DIALOG_BASE = (0xFF, 0xAD, 0x00)       # main orange of the system dialog font (memory card, network messages)
DIALOG_BORDER = (0xFD, 0xB1, 0x52)     # the orange window border of those dialogs


def _is_dialog_ramp(c):
    """Orange ramp of the dialog font: from dark brown outline shades to the light anti-alias tints."""
    import colorsys
    h, sv, v = colorsys.rgb_to_hsv(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)
    return 22 <= h * 360 <= 58 and sv > 0.25 and v > 0.25


def dialog_shade(c, new):
    """Shade c of the dialog font ramp, re-based on the new main colour (dark shades darker, light tints lighter)."""
    if c[0] >= 0xF0 and c[2] > 0:
        t = c[2] / 255.0                                   # light tint: mixed towards white
        return bytes(round(x + t * (255 - x)) for x in new)
    f = max(c) / 255.0                                     # dark shade: darker version of the new colour
    return bytes(round(x * f) for x in new)


def dialog_colors(iso_path, orange=None, border=None, log=print):
    """System dialogs (memory card, DNAS, network messages, DATA/MC, DNAS0/1, KDDI, NET_MES0-2): recolour the orange font
    (orange = new main colour of the font ramp) and / or the window border (border).  Palette bytes only."""
    iso = G.Iso(iso_path, write=True)
    changed = 0
    try:
        for path, lba, size in G.iso_files(iso):
            if not path.startswith(DIALOG_GROUPS) or not path.upper().endswith('.DAT') or size < 100000:
                continue
            raw = bytearray(iso.read(lba, (size + 2047) // 2048 * 2048))
            data = bytes(raw[:size])
            bases = set()
            for m in re.finditer(bytes(DIALOG_BASE) + bytes([0x80]), data[:0x4000]):
                if m.start() % 4 == 0:
                    bases.add(m.start() & ~0x3FF)
            if not bases:
                continue
            n = 0
            for base in sorted(bases):
                for i in range(256):
                    o = base + 4 * i
                    c = data[o:o + 3]
                    if data[o + 3] != 0x80 or not _is_dialog_ramp(c):
                        continue
                    if _near(c, DIALOG_BORDER, 3):
                        if border:
                            raw[o:o + 3] = bytes(border)
                            n += 1
                    elif orange:
                        raw[o:o + 3] = dialog_shade(c, orange)
                        n += 1
            if n:
                iso.f.seek(lba * 2048)
                iso.f.write(bytes(raw))
                changed += 1
        iso.f.flush()
    finally:
        iso.f.close()
    log('dialog colours: %d system dialog files recoloured (memory card, DNAS, network messages)' % changed)


def black_background(iso_path, log=print):
    """White menu background -> black in all menus: hide the background cube obj.cube50 (scale 338 x 223 x 223, a
    white box behind the buttons; its material colour bg01.mat1 has no effect on the colour, tried).  The outer
    margin is a separate setting (margin_color)."""
    iso = G.Iso(iso_path, write=True)
    try:
        lba, size = iso.find(SCENE_PATH)
        data = iso.read(lba, size)
        m = re.search(rb'MDL-obj\.cube50\x00', data)
        if not m:
            raise SystemExit('%s: node obj.cube50 not found (not the JP disc?)' % SCENE_PATH)
        off = m.start() + 0xB0
        old = struct.unpack_from('<3f', data, off)
        iso.f.seek(lba * 2048 + off)
        iso.f.write(bytes(12))
        iso.f.flush()
        log('black background: node cube50 hidden (scale %.0f x %.0f x %.0f -> 0)' % old)
    finally:
        iso.f.close()


# ---------------------------------------------------------------- clock sprite
def rotate_cw(im, degrees):
    """Rotate an image clockwise by 0 / 90 / 180 / 270 degrees (the game shows the frozen clock turned by 90 degrees
    counter-clockwise, so a logo needs 90 clockwise to look upright)."""
    degrees %= 360
    if degrees == 0:
        return im
    return im.convert('RGBA').rotate(-degrees, expand=True)


GAME_TURN_CW = 270     # the game draws the frozen clock sprite turned 90 degrees counter-clockwise (= 270 clockwise)


def game_view(im):
    """The sprite as it appears on screen (the game turns it 90 degrees counter-clockwise)."""
    return rotate_cw(im, GAME_TURN_CW)


def clock_fit(im):
    """Any RGBA image -> exactly CLOCK_SIZE (contain, centred, transparent padding), alpha thresholded."""
    im = im.convert('RGBA')
    s = min(CLOCK_SIZE[0] / im.width, CLOCK_SIZE[1] / im.height)
    nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
    if (nw, nh) != im.size:
        # flat artwork (few colours) keeps its colours with nearest neighbour, LANCZOS would invent hundreds of shades
        flat = len(set(im.getdata())) <= 32
        im = im.resize((nw, nh), Image.NEAREST if flat else Image.LANCZOS)
    out = Image.new('RGBA', CLOCK_SIZE, (0, 0, 0, 0))
    out.alpha_composite(im, ((CLOCK_SIZE[0] - nw) // 2, (CLOCK_SIZE[1] - nh) // 2))
    a = np.array(out)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    a[a[..., 3] == 0] = 0
    return Image.fromarray(a, 'RGBA')


def _quantize(rgb_pixels, k):
    """Median cut of an (n, 3) uint8 array -> (palette (k', 3), index per pixel)."""
    n = len(rgb_pixels)
    im = Image.fromarray(rgb_pixels.reshape(1, n, 3), 'RGB')
    q = im.quantize(colors=k, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[:3 * k], dtype=np.uint8).reshape(-1, 3)
    return pal, np.array(q).reshape(-1)


def clock_plan(iso, final, log=print):
    """Compute the new data of the three atlases.  Returns [(path, lba, sectors, stream, old, new, k, size, limit)];
    raises SystemExit when nothing fits.  final = RGBA image of CLOCK_SIZE (see clock_fit)."""
    arr = np.array(final)
    opaque = arr[..., 3] == 255
    pix = arr[opaque][:, :3]
    x0, y0, x1, y1 = CLOCK_RECT
    atlases = []
    for path in CLOCK_FILES:
        lba, sectors, stream, d = _load(iso, path)
        if len(d) < 0x400 + 256 * PAGE_ROWS:
            raise SystemExit(path + ' is smaller than expected: wrong disc?')
        px = np.frombuffer(d[0x400:0x400 + 256 * PAGE_ROWS], dtype=np.uint8).reshape(PAGE_ROWS, 256)
        inr = np.zeros(px.shape, bool)
        inr[y0:y1, x0:x1] = True
        used_out = set(np.unique(px[~inr]).tolist())
        free = [i for i in range(1, 256) if i not in used_out]
        atlases.append((path, lba, sectors, stream, d, free))
    kmax = min(len(a[5]) for a in atlases)
    last_err = None
    n_unique = len(np.unique(pix, axis=0)) if len(pix) else 1
    tried = set()
    for k in [kmax, 192, 128, 96, 64, 48, 32, 24, 16, 12, 8, 6, 5, 4, 3]:
        if k > kmax:
            continue
        kk = max(1, min(k, n_unique))
        if kk in tried:
            continue
        tried.add(kk)
        pal, idx = _quantize(pix, kk) if len(pix) else (np.zeros((1, 3), np.uint8), np.zeros(0, int))
        plan = []
        try:
            for path, lba, sectors, stream, d, free in atlases:
                nd = bytearray(d)
                for j, c in enumerate(pal):
                    f = swz(free[j])
                    nd[4 * f:4 * f + 4] = bytes(int(v) for v in c) + b'\x40'
                new_idx = np.zeros(CLOCK_SIZE[::-1], np.uint8)
                new_idx[opaque] = np.array([free[j] for j in range(len(pal))], np.uint8)[idx]
                for y in range(CLOCK_SIZE[1]):
                    o = 0x400 + (y0 + y) * 256 + x0
                    nd[o:o + CLOCK_SIZE[0]] = new_idx[y].tobytes()
                nd = bytes(nd)
                first = next(i for i in range(len(d)) if d[i] != nd[i])
                last = max(i for i in range(len(d)) if d[i] != nd[i]) + 1
                ns = G.grc_splice(stream, nd, first, last, CLOCK_DEPTH)
                if len(ns) > sectors * 2048:
                    raise ValueError('%s: %d bytes > %d' % (path, len(ns), sectors * 2048))
                plan.append((path, lba, sectors, stream, d, nd, len(pal), len(ns), sectors * 2048))
            sizes = ', '.join('%s %d/%d bytes' % (os.path.basename(p[0]), p[7], p[8]) for p in plan)
            if len(pal) < n_unique:
                log('clock sprite: colour reduction %d -> %d colours (more would not fit the sector size of the atlas '
                    'files); sizes: %s' % (n_unique, len(pal), sizes))
            else:
                log('clock sprite: %d colours, fits (%s)' % (len(pal), sizes))
            return plan
        except ValueError as e:
            last_err = e
    raise SystemExit('the clock graphic does not fit the atlas files even with 8 colours (%s): use flatter artwork '
                     '(fewer gradients, no noise)' % last_err)


def clock_preview(plan, final):
    """What the game will show: the new atlas rectangle decoded through the new palette, on white."""
    path, lba, sectors, stream, d, nd, k, size, limit = plan[0]
    pal = [tuple(nd[4 * swz(i):4 * swz(i) + 4]) for i in range(256)]
    x0, y0, x1, y1 = CLOCK_RECT
    px = np.frombuffer(nd[0x400:0x400 + 256 * PAGE_ROWS], dtype=np.uint8).reshape(PAGE_ROWS, 256)[y0:y1, x0:x1]
    lut = np.array([(r, g, b, 255 if a else 0) for r, g, b, a in pal], np.uint8)
    return Image.fromarray(lut[px], 'RGBA')


def replace_clock(iso_path, final, log=print):
    iso = G.Iso(iso_path, write=True)
    try:
        plan = clock_plan(iso, final, log)
        for path, lba, sectors, stream, d, nd, k, size, limit in plan:
            _write_grc(iso, lba, sectors, stream, d, nd, path, log, CLOCK_DEPTH)
            log('clock sprite written: %s (%d colours, %d of %d bytes)' % (path, k, size, limit))
        iso.f.flush()
    finally:
        iso.f.close()
    iso = G.Iso(iso_path)
    try:
        for path, lba, sectors, stream, d, nd, k, size, limit in plan:
            got = _load(iso, path)[3]
            if got != nd:
                raise SystemExit('verification failed for ' + path)
    finally:
        iso.f.close()
    log('clock sprite verified: read back from the new ISO')


# ---------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='PS2 JP main menu edits on an ISO COPY (patched in place)')
    ap.add_argument('iso')
    ap.add_argument('--color', help='UI main colour, e.g. cb0608')
    ap.add_argument('--hide-animations', action='store_true')
    ap.add_argument('--black-background', action='store_true')
    ap.add_argument('--frame-color', help='grey window frame colour, e.g. 202020')
    ap.add_argument('--margin-color', help='outer margin colour (white by default), e.g. 3050a0')
    ap.add_argument('--font-orange', help='colour of the orange menu alphabet, e.g. cb0608')
    ap.add_argument('--font-teal', help='colour of the turquoise menu alphabet, e.g. 4080ff')
    ap.add_argument('--dialog-border', help='border colour of the memory card / network dialogs, e.g. cb0608')
    ap.add_argument('--clock-rotate', type=int, default=0, help='rotate the clock PNG clockwise by 0/90/180/270 degrees first')
    ap.add_argument('--clock', metavar='PNG', help='replacement for the clock sprite')
    a = ap.parse_args(argv)
    if a.color:
        c = parse_color(a.color)
        if not c:
            raise SystemExit('colour must be 6 hex digits')
        recolor(a.iso, c)
    if a.hide_animations:
        hide_animations(a.iso)
    if a.black_background:
        black_background(a.iso)
    if a.font_orange or a.font_teal:
        cols = {}
        for name, v in (('orange', a.font_orange), ('teal', a.font_teal)):
            if v:
                c = parse_color(v)
                if not c:
                    raise SystemExit('colour must be 6 hex digits')
                cols[name] = c
        font_colors(a.iso, cols)
        dialog_colors(a.iso, cols.get('orange'), parse_color(a.dialog_border) if a.dialog_border else None)
    if a.margin_color:
        c = parse_color(a.margin_color)
        if not c:
            raise SystemExit('colour must be 6 hex digits')
        margin_color(a.iso, c)
    if a.frame_color:
        c = parse_color(a.frame_color)
        if not c:
            raise SystemExit('colour must be 6 hex digits')
        recolor_frame(a.iso, c)
    if a.clock:
        replace_clock(a.iso, clock_fit(rotate_cw(Image.open(a.clock), a.clock_rotate)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
