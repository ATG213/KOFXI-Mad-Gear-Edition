r"""Replace row labels of the PS2 JP practice menu (DATA/MENU/SPR01.GRC, page 1).

The practice menu labels (CONTROL, ACTION, ATTACK, COUNTER, GUARD, LIFE, GAUGE, AUTO CHARACTER, STAGE SELECT,
SELECT BUTTON, ...) are 32 px high sprite rects of the second 256x512 page of SPR01.GRC (page base 0x20400: CLUT 0x400 +
8 bpp pixels, 256 wide).  They use only three palette indices: 0 transparent, 250 orange fill, 255 white outline (2 px).
The rect table is in the ELF at 0x3D2640 (x, y, w, h per entry); the practice row -> entry map is at 0x3D2790:
CONTROL 9, ACTION 13, ATTACK 10, COUNTER 5, GUARD 14, LIFE 3, GAUGE 7, AUTO CHARACTER 11, STAGE SELECT 2,
SELECT BUTTON 12.

  python practice_labels.py ISO --display DISPLAY [--input INPUT] [--preview out.png]

Works on a COPY of the ISO written in place (make the copy yourself).  Only pixel indices change, so any palette
recolour of the menu (gfx_menu.py) keeps working.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kofxi_gfx as G          # noqa: E402
import gfx_menu as M           # noqa: E402

PATH = 'DATA/MENU/SPR01.GRC'
PAGE_BASE = 0x20400
FILL, OUTLINE, CLEAR = 250, 255, 0
CAP = 15                       # cap height of the orange fill in px (original labels: 15)
OUT_R = 2                      # outline thickness
FONT_DIRS = [os.path.join(os.environ.get('WINDIR', ''), 'Fonts'), '/usr/share/fonts/truetype/msttcorefonts',
             os.path.expanduser('~/.fonts')]


def _fonts(*names):
    """Font candidates in preference order (Arial Black is the label look); KOFXI_LABEL_FONT overrides."""
    out = [os.environ['KOFXI_LABEL_FONT']] if os.environ.get('KOFXI_LABEL_FONT') else []
    return tuple(out + [os.path.join(d, n) for n in names for d in FONT_DIRS])


FONTS = _fonts('ariblk.ttf', 'impact.ttf', 'arialbd.ttf')

# rect (x, y, w, h) of the label sprites on the page and the row of the fill top
RECTS = {
    'AUTO CHARACTER': (0, 192, 256, 32),
    'SELECT BUTTON': (0, 224, 224, 32),
    # new INPUT row: right half of the DISPLAY strip (the DISPLAY rect in the ELF is narrowed to 128 px by the builder)
    'INPUT': (128, 192, 128, 32),
}
FILL_TOP = 10                  # first fill row inside the 32 px rect (AUTO CHARACTER: rows 202..216 of y 192)


def _font():
    for f in FONTS:
        if os.path.exists(f):
            # find the size whose capital letters are CAP px high
            for size in range(12, 40):
                fn = ImageFont.truetype(f, size)
                l, t, r, b = fn.getbbox('H')
                if b - t >= CAP:
                    return fn
    raise SystemExit('no bold font found (Arial Black / Impact / Arial Bold)')


def render(text, w, h, fill_idx=FILL, top=FILL_TOP, align='left', margin=None):
    """Return a (h, w) uint8 index image of `text` in the label style."""
    fn = _font()
    big = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(big)
    d.fontmode = '1'                              # no anti-aliasing
    l, t, r, b = fn.getbbox('H')
    bb = fn.getbbox(text)
    if align == 'right':
        x0 = w - (margin if margin is not None else 4) - (bb[2] - bb[0])
    else:
        x0 = margin if margin is not None else OUT_R + 1
    d.text((x0 - bb[0], top - t), text, font=fn, fill=255)
    fill = np.array(big) > 127
    # outline = disc dilation of the fill
    out = np.zeros_like(fill)
    for dy in range(-OUT_R, OUT_R + 1):
        for dx in range(-OUT_R, OUT_R + 1):
            if dx * dx + dy * dy <= OUT_R * OUT_R + 1:
                out |= np.roll(np.roll(fill, dy, 0), dx, 1)
    img = np.full((h, w), CLEAR, np.uint8)
    img[out] = OUTLINE
    img[fill] = fill_idx
    return img


def plan(iso, labels):
    """labels = {'AUTO CHARACTER': 'DISPLAY', ...}.  Returns (lba, sectors, stream, old, new)."""
    lba, sectors, stream, d = M._load(iso, PATH)
    nd = bytearray(d)
    for old_name, text in labels.items():
        if old_name == 'UKEMI':
            ukemi_label(nd, text)
            continue
        x, y, w, h = RECTS[old_name]
        img = render(text, w, h)
        if old_name == 'AUTO CHARACTER' and 'INPUT' in labels and img[:, 120:].any():
            raise SystemExit('DISPLAY label is wider than 120 px, it would collide with the INPUT label')
        for r in range(h):
            o = PAGE_BASE + 0x400 + (y + r) * 256 + x
            nd[o:o + w] = img[r].tobytes()
    return lba, sectors, stream, d, bytes(nd)


# new UKEMI row (make_combo_dmg_ps2.UKM_RECT_UVWH = (181, 268, 75, 19), drawn 8 px lower): right of GUARD, where the vertical
# "SELECT BUTTON TO DEFAULT" text was (that text is no longer shown since the INPUT row removed it from the menu)
UKEMI_VTEXT = (228, 266, 24, 22)        # x, y, w, h of the part of the vertical text under the label (erased); erasing all of it
                                        # (246 rows) made SPR01 compress so well that the game's in-place GRC decompression overran its
                                        # unread input and crashed (min. read/write margin -6032 vs -4305 of 1.6f, 2026-11-24)
UKEMI_DEST = (181, 268, 75, 19)
UKEMI_SRC_ROW = 8                       # first used row of a rendered 32 px label


def ukemi_label(nd, text='UKEMI'):
    x0, y0, w0, h0 = UKEMI_VTEXT
    for r in range(h0):
        o = PAGE_BASE + 0x400 + (y0 + r) * 256 + x0
        nd[o:o + w0] = bytes(w0)
    x, y, w, h = UKEMI_DEST
    for r in range(h):
        o = PAGE_BASE + 0x400 + (y + r) * 256 + x
        if any(nd[o:o + w]):
            raise SystemExit('UKEMI label area is not empty at row %d' % (y + r))
    img = render(text, w + 6, 32)
    cols = np.where(img.any(axis=0))[0]
    img = img[UKEMI_SRC_ROW:UKEMI_SRC_ROW + h, cols.min():cols.max() + 1]
    if img.shape[1] > w or render(text, w + 6, 32)[:UKEMI_SRC_ROW].any() or render(text, w + 6, 32)[UKEMI_SRC_ROW + h:].any():
        raise SystemExit('UKEMI label does not fit %dx%d' % (w, h))
    for r in range(h):
        o = PAGE_BASE + 0x400 + (y + r) * 256 + x
        nd[o:o + img.shape[1]] = img[r].tobytes()


def preview(nd, labels, out_png):
    base = PAGE_BASE
    pal = [tuple(nd[base + 4 * i:base + 4 * i + 4]) for i in range(256)]
    sw = pal[:]
    for g in range(0, 256, 32):
        for k in range(8):
            sw[g + 8 + k], sw[g + 16 + k] = pal[g + 16 + k], pal[g + 8 + k]
    px = np.frombuffer(nd[base + 0x400:base + 0x400 + 256 * 512], dtype=np.uint8).reshape(512, 256)
    lut = np.array([(r, g, b, min(255, a * 2)) for r, g, b, a in sw], dtype=np.uint8)
    im = Image.fromarray(lut[px[:290]], 'RGBA')
    bg = Image.new('RGBA', im.size, (110, 110, 110, 255))
    bg.alpha_composite(im)
    bg.convert('RGB').resize((768, 870), Image.NEAREST).save(out_png)


# ---- OPTIONS > GRAPHIC SETTING: label "DISPLAY" and the values DAMAGE / STUN / BOTH / OFF (SPR00.GRC, page 2) ----
# History: v11..v77 / Mad Gear 1.2 wrote these words over the rows JUDGMENT INDICATOR (y=64) and SINGLE ROUND (y=128) of page 5, but those two rows
# are used by GAME OPTION > BATTLE SETTING (reported 2026-11-22: "DAMAGE BOTH" instead of SINGLE ROUND, "DISPLAY STUN" instead of
# JUDGMENT INDICATOR).  Page 5 is full, so the words moved to the empty bottom of page 2 (y >= 384, rows 380..511 are index 0, only the palette
# indices 1 and 252-255 are used there).  p is a texture SLOT (slot 1 = page 3, slot 3 = page 5; page 2 is not loaded by GAME OPTION), see make_combo_dmg_ps2.OPT_RECT_P.
# The palette of page 2 has the unused indices 244..251 (pixels 0): 250 / 251 get the orange / teal of page 5 (outline = index 255, white, exists).
GRAPHIC_PATH = 'DATA/MENU/SPR00.GRC'
GRAPHIC_PAGE = 2
GRAPHIC_P = 4                           # texture SLOT of the rect entry (the setup stub loads page 2 into slot 4), must equal make_combo_dmg_ps2.OPT_RECT_P
TEAL = 251
GRAPHIC_PALETTE = {250: (240, 117, 0, 64), 251: (52, 198, 182, 64)}     # index -> (r, g, b, a) like page 5 (a = 64 = 0x40)
GRAPHIC_CLEAR = ()
GRAPHIC_LABEL = ('DISPLAY', (0, 384, 160, 32))
GRAPHIC_VALUES = (('STUN', (160, 384, 80, 32)), ('DAMAGE', (0, 416, 112, 32)), ('BOTH', (112, 416, 80, 32)),
                  ('OFF', (192, 416, 64, 32)))


def graphic_plan(iso):
    lba, sectors, stream, d = M._load(iso, GRAPHIC_PATH)
    nd = bytearray(d)
    base = GRAPHIC_PAGE * 0x20400 + 0x400
    pal0 = GRAPHIC_PAGE * 0x20400
    for i, rgba in GRAPHIC_PALETTE.items():
        assert bytes([i]) not in bytes(d[base:base + 256 * 512]), 'palette index %d is used on page %d' % (i, GRAPHIC_PAGE)
        nd[pal0 + 4 * i:pal0 + 4 * i + 4] = bytes(rgba)
    for y0, y1 in GRAPHIC_CLEAR:
        nd[base + y0 * 256:base + y1 * 256] = bytes(256 * (y1 - y0))
    for text, (x, y, w, h) in [(GRAPHIC_LABEL[0], GRAPHIC_LABEL[1])] + list(GRAPHIC_VALUES):
        for r in range(h):
            assert not any(d[base + (y + r) * 256 + x: base + (y + r) * 256 + x + w]), \
                'target rect of %s on page %d is not empty' % (text, GRAPHIC_PAGE)
    items = [(GRAPHIC_LABEL[0], GRAPHIC_LABEL[1], FILL, 'right')] + [(t, r, TEAL, 'left') for t, r in GRAPHIC_VALUES]
    for text, (x, y, w, h), fi, al in items:
        img = render(text, w, h, fill_idx=fi, top=9, align=al, margin=4)
        for r in range(h):
            o = base + (y + r) * 256 + x
            nd[o:o + w] = img[r].tobytes()
    return lba, sectors, stream, d, bytes(nd)


# ---- KEY SETTING: value word "ENEMY" for the new button function COMMAND ENEMY (SPR02.GRC, page 1) ----
# The vanilla COMMAND value rect (0, 224, 128, 32) is drawn first, ENEMY follows 100 px to the right.  The rect (190, 64, 66, 32)
# is empty in the atlas (right of "SP+BO").  Style of the page words: white fill (index 253), black outline (index 1), 12 px caps.
ENEMY_PATH = 'DATA/MENU/SPR02.GRC'
ENEMY_PAGE = 1
ENEMY_RECT = (190, 64, 66, 32)
ENEMY_FILL, ENEMY_OUTLINE = 253, 1
ENEMY_CAP = 12
ENEMY_FONTS = _fonts('arialbd.ttf', 'ariblk.ttf')


# The KEY SETTING value words exist twice in the atlases: SPR02 page 1 (practice menu) and SPR00 page 4 (OPTIONS >
# button config outside practice mode, GAME OPTION texture slot 2).  Same rects, same palette; both need the new words.
ENEMY_TARGETS = ((ENEMY_PATH, ENEMY_PAGE), ('DATA/MENU/SPR00.GRC', 4))
ENEMY_WORDS = (('ENEMY', ENEMY_RECT), ('QUICK', (192, 352, 64, 32)), ('RESET', (192, 384, 64, 32)))


def render_enemy(text='ENEMY', w=ENEMY_RECT[2], h=ENEMY_RECT[3]):
    fn = None
    for f in ENEMY_FONTS:
        if os.path.exists(f):
            for size in range(10, 40):
                cand = ImageFont.truetype(f, size)
                l, t, r, b = cand.getbbox('H')
                if b - t >= ENEMY_CAP:
                    fn = cand
                    break
            if fn:
                break
    if fn is None:
        raise SystemExit('no bold font found (Arial Bold / Arial Black)')
    big = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(big)
    d.fontmode = '1'
    l, t, r, b = fn.getbbox('H')
    bb = fn.getbbox(text)
    d.text((3 - bb[0], 10 - t), text, font=fn, fill=255)       # caps at rows 10..21 like COMMAND (234..245 of its rect at 224)
    fill = np.array(big) > 127
    fill |= np.roll(fill, 1, 1)                                # faux bold: the page words have thick strokes
    out = np.zeros_like(fill)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out |= np.roll(np.roll(fill, dy, 0), dx, 1)
    img = np.full((h, w), CLEAR, np.uint8)
    img[out] = ENEMY_OUTLINE
    img[fill] = ENEMY_FILL
    if img[:, w - 2:].any():
        raise SystemExit('%s is wider than the %d px rect' % (text, w))
    return img


def enemy_plan(iso, path=ENEMY_PATH, page=ENEMY_PAGE):
    """KEY SETTING words: ENEMY (COMMAND ENEMY) and QUICK + RESET (QUICK RESET), all on SPR02.GRC page 1 in empty areas."""
    lba, sectors, stream, d = M._load(iso, path)
    nd = bytearray(d)
    base = page * PAGE_BASE + 0x400
    for text, (x, y, w, h) in ENEMY_WORDS:
        cur = np.frombuffer(bytes(nd[base + y * 256:base + (y + h) * 256]), np.uint8).reshape(h, 256)[:, x:x + w]
        if cur.any():
            raise SystemExit('%s rect is not empty in %s page %d' % (text, path, page))
        img = render_enemy(text, w, h)
        for r in range(h):
            o = base + (y + r) * 256 + x
            nd[o:o + w] = img[r].tobytes()
    return lba, sectors, stream, d, bytes(nd)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--display', help='new text for the AUTO CHARACTER row label')
    ap.add_argument('--input', help='text of the new INPUT row label (right half of the DISPLAY strip)')
    ap.add_argument('--ukemi', help='text of the new UKEMI row label (right of GUARD)')
    ap.add_argument('--option-display', action='store_true', help='graphic setting page: DISPLAY label + value words')
    ap.add_argument('--command-enemy', action='store_true', help='KEY SETTING: ENEMY word of the new COMMAND ENEMY value')
    ap.add_argument('--preview')
    ap.add_argument('--dry', action='store_true', help='do not write the ISO')
    a = ap.parse_args(argv)
    labels = {}
    if a.display:
        labels['AUTO CHARACTER'] = a.display.upper()
    if a.input:
        labels['INPUT'] = a.input.upper()
    if a.ukemi:
        labels['UKEMI'] = a.ukemi.upper()
    if not labels and not a.option_display and not a.command_enemy:
        raise SystemExit('nothing to do')
    jobs = []          # (path, lba, sectors, stream, old, new)
    iso = G.Iso(a.iso, write=not a.dry)
    try:
        if labels:
            lba, sectors, stream, d, nd = plan(iso, labels)
            jobs.append((PATH, lba, sectors, stream, d, nd))
            if a.preview:
                preview(nd, labels, a.preview)
        if a.command_enemy:
            for epath, epage in ENEMY_TARGETS:
                lba, sectors, stream, d, nd = enemy_plan(iso, epath, epage)
                jobs.append((epath, lba, sectors, stream, d, nd))
        if a.option_display:
            lba, sectors, stream, d, nd = graphic_plan(iso)
            jobs.append((GRAPHIC_PATH, lba, sectors, stream, d, nd))
            if a.preview:
                gp = a.preview.replace('.png', '_graphic.png')
                base = GRAPHIC_PAGE * 0x20400
                pal = [tuple(nd[base + 4 * i:base + 4 * i + 4]) for i in range(256)]
                sw = pal[:]
                for g in range(0, 256, 32):
                    for k in range(8):
                        sw[g + 8 + k], sw[g + 16 + k] = pal[g + 16 + k], pal[g + 8 + k]
                px = np.frombuffer(nd[base + 0x400:base + 0x400 + 256 * 512], dtype=np.uint8).reshape(512, 256)
                lut = np.array([(r, g, b, min(255, a2 * 2)) for r, g, b, a2 in sw], dtype=np.uint8)
                im = Image.fromarray(lut[px], 'RGBA')
                bg = Image.new('RGBA', im.size, (110, 110, 110, 255))
                bg.alpha_composite(im)
                bg.convert('RGB').resize((768, 1536), Image.NEAREST).save(gp)
        merged = {}
        for path, lba, sectors, stream, d, nd in jobs:
            if path in merged:
                m = merged[path]
                buf = bytearray(m[5])
                for i in range(len(d)):
                    if nd[i] != d[i]:
                        buf[i] = nd[i]
                merged[path] = m[:5] + (bytes(buf),)
            else:
                merged[path] = (path, lba, sectors, stream, d, nd)
        jobs = list(merged.values())
        if not a.dry:
            for path, lba, sectors, stream, d, nd in jobs:
                n, lim = M._write_grc(iso, lba, sectors, stream, d, nd, path, print)
                print('%s written (%d of %d bytes)' % (path, n, lim))
            iso.f.flush()
    finally:
        iso.f.close()
    if not a.dry:
        iso = G.Iso(a.iso)
        try:
            for path, lba, sectors, stream, d, nd in jobs:
                if M._load(iso, path)[3] != nd:
                    raise SystemExit('verification failed: ' + path)
        finally:
            iso.f.close()
        print('verified: read back from', a.iso)


if __name__ == '__main__':
    main()
