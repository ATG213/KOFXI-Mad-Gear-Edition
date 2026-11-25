r"""KOF XI PS2 (JP and US): character colour palettes, read from and written to the user's own ISO.

Where the game keeps them (found 2026-11-25 in the JP decompile, FUN_0012ED00 -> FUN_0012E9C0):
* PACK\FIGHT.BCC and PACK\FIGHTA.BCC (the game loads one of the two, so both are patched), container entries 16-62.
  Character id 0x00-0x27 -> entry 16 + id, 0x29-0x2F (console characters) -> entry 56 + (id - 0x29).  Both files and
  the JP and US discs hold identical palettes.
* One entry = 12 colours x 16 sub-palettes x 16 entries x u16 = 6144 bytes (Shen Woo: 188 sub-palettes = 6016 bytes),
  the same layout as the arcade (Atomiswave) .PAL files.  u16 = BGR555: R = bits 10-14, G = 5-9, B = 0-4, bit 15 is
  kept as it is.  Entry 0 of every sub-palette is transparent (the game overwrites it).
* Colour index 0-11 = A, B, C, D, then the two modifier groups (arcade: E + button, Start + button).  The PS2 COLOR
  EDIT colours (index 12+) come from the memory card save, not from these files.
* The body of a character uses sub-palette 0; the others are effects, flashes etc.  Byte 0 of a sprite descriptor
  (section 11) is the sub-palette (row) the sprite is drawn with: 0 = body, e.g. 8-10 = Ash's green flames (checked by
  rendering).  Values above 15 (e.g. 125) are something else; those sprites are shown with row 0.

Preview: the first sprite (descriptor 0 of section 11) of DATA/PLA|PLA2/xxxx.UNI is the first idle frame of every
character.  Section 22 = linear 4 bpp 8x8 tiles (32 bytes, low nibble first), a descriptor = u8[4] (+2 width, +3 height
in tiles) followed by records u16 tile, run, column, row (a vertical run of consecutive tiles).  Nothing of the game
is shipped with the tool: everything is read from the ISO the user picks.

CLI (python -I):
  gfx_palettes.py list ISO
  gfx_palettes.py export ISO CHAR_ID out.pal|out.png        (CHAR_ID hex, e.g. 00 = Ash)
  gfx_palettes.py preview ISO CHAR_ID COLOUR out.png
  gfx_palettes.py patch* ISO FILE.PAL ...                    files named <id>*.pal, e.g. 00_ash.pal; patches IN PLACE
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kofxi_gfx as G

BCC_PATHS = ('DATA/PACK/FIGHT.BCC', 'DATA/PACK/FIGHTA.BCC')
FX_FILE = 'gfx_palette_fx.json'     # named sprites per character: {"00": [[540, "Green orb"], ...], ...}
IDLE_SPRITE = {0x0A: 1}             # preview frame where sprite 0 is a poor pick (Yuri: eye not visible in 0)
LDM_ROW = 4                         # every character: 4 sprites in row 4 = hit by Ash's LDM follow-up (purple-blue)
LDM_NAME = 'Ash LDM>236236E hit'
UNI_DIRS = ('DATA/PLA', 'DATA/PLA2')          # arcade data: preview and effect browser
UNI_DIRS_PL = ('DATA/PL', 'DATA/PL2')         # console data: a few sprites exist only here (Duck King's P-chan)
PL_REF = 10000                                # sprite reference >= PL_REF = console sprite (ref - PL_REF)
CHAR_NAMES = {
    0x00: 'Ash Crimson', 0x01: 'Oswald', 0x02: 'Shen Woo', 0x03: 'Elisabeth', 0x04: 'Duo Lon', 0x05: 'Benimaru',
    0x06: 'Terry Bogard', 0x07: 'Kim Jae Hoon', 0x08: 'Duck King', 0x09: 'Ryo Sakazaki', 0x0A: 'Yuri Sakazaki',
    0x0B: 'King', 0x0C: 'B. Jenet', 0x0D: 'Gato', 0x0E: 'Griffon', 0x0F: 'Ralf', 0x10: 'Clark', 0x11: 'Whip',
    0x12: 'Athena', 0x13: 'Kensou', 0x14: 'Momoko', 0x15: 'Vanessa', 0x16: 'Blue Mary', 0x17: 'Ramon', 0x18: 'Malin',
    0x19: 'Kasumi Todo', 0x1A: 'Eiji Kisaragi', 0x1B: "K'", 0x1C: 'Kula Diamond', 0x1D: 'Maxima', 0x1E: 'Kyo',
    0x1F: 'Iori', 0x20: 'Shingo', 0x21: 'Gai Tendo', 0x22: 'Hayate', 0x23: 'Adelheid', 0x24: 'Silber', 0x25: 'Jazu',
    0x26: 'Shion', 0x27: 'Magaki', 0x29: 'Mai Shiranui', 0x2A: 'Robert Garcia', 0x2B: 'Mr. Big', 0x2C: 'Geese Howard',
    0x2D: 'Hotaru Futaba', 0x2E: 'Tung Fu Rue', 0x2F: 'EX Kyo',
}
CHAR_IDS = sorted(CHAR_NAMES)
COLOR_LABELS = ['A', 'B', 'C', 'D', 'E+A', 'E+B', 'E+C', 'E+D', 'Start+A', 'Start+B', 'Start+C', 'Start+D']
BLOCK = 0x200            # one colour = 16 sub-palettes x 32 bytes
SUB = 32
SWATCH_CELL = 8          # swatch PNG: one 8x8 cell per palette entry, 16 cells wide, one row per sub-palette


def entry_index(cid):
    if 0 <= cid <= 0x27:
        return 16 + cid
    if 0x29 <= cid <= 0x2F:
        return 56 + cid - 0x29
    raise ValueError('no palette for character id 0x%02X' % cid)


def char_label(cid):
    return '%02X  %s' % (cid, CHAR_NAMES.get(cid, '?'))


# ---------------------------------------------------------------- colour helpers
def word_to_rgb(v):
    return (((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31)


def rgb_to_word(rgb, old=0):
    """8-bit RGB -> BGR555 word, keeping bit 15 of the old word."""
    r, g, b = (min(31, (int(c) * 31 + 127) // 255) for c in rgb[:3])
    return (old & 0x8000) | (r << 10) | (g << 5) | b


def get_word(pal, color, sub, i):
    return struct.unpack_from('<H', pal, color * BLOCK + sub * SUB + i * 2)[0]


def set_rgb(pal, color, sub, i, rgb):
    """pal: bytearray.  Returns True if the word changed."""
    o = color * BLOCK + sub * SUB + i * 2
    old = struct.unpack_from('<H', pal, o)[0]
    new = rgb_to_word(rgb, old)
    if new == old:
        return False
    struct.pack_into('<H', pal, o, new)
    return True


def sub_rgba(pal, color, sub):
    """16 RGBA tuples of one sub-palette (entry 0 transparent)."""
    res = []
    for i in range(16):
        o = color * BLOCK + sub * SUB + i * 2
        if o + 2 > len(pal):
            res.append((0, 0, 0, 0))
            continue
        res.append(word_to_rgb(struct.unpack_from('<H', pal, o)[0]) + ((0,) if i == 0 else (255,)))
    return res


def n_colors(pal):
    """Number of colour slots present (Shen Woo's last slot is shorter but still there)."""
    return min(12, (len(pal) + BLOCK - 1) // BLOCK)


def subs_in_color(pal, color):
    return max(0, min(16, (len(pal) - color * BLOCK) // SUB))


# ---------------------------------------------------------------- reading the ISO
class Source:
    """Palettes and idle sprites of one ISO, read once."""

    def __init__(self, iso_path):
        self.iso_path = iso_path
        iso = G.Iso(iso_path)
        try:
            self.variant = iso.variant()
            self.pals = {}
            self.mismatch = []
            datas = []
            for path in BCC_PATHS:
                lba, size, stream, data = G.bcc_load(iso, path)
                cnt, offs = G.container_entries(data)
                if cnt != 63:
                    raise SystemExit('%s has %d entries, expected 63: not a KOF XI PS2 disc?' % (path, cnt))
                datas.append((data, offs))
            (d0, o0), (d1, o1) = datas
            for cid in CHAR_IDS:
                e = entry_index(cid)
                p0, p1 = d0[o0[e]:o0[e + 1]], d1[o1[e]:o1[e + 1]]
                if len(p0) % SUB or len(p0) < 11 * BLOCK:
                    raise SystemExit('palette entry %d has %d bytes: unexpected layout' % (e, len(p0)))
                if p0 != p1:
                    self.mismatch.append(cid)
                self.pals[cid] = p0
            self.uni, self.uni_pl = {}, {}
            for dirs, target in ((UNI_DIRS, self.uni), (UNI_DIRS_PL, self.uni_pl)):
                for d in dirs:
                    try:
                        lst = iso.listdir(*iso.find(d))
                    except SystemExit:
                        continue
                    for n, e, s, is_dir in lst:
                        if n.upper().endswith('.UNI') and not is_dir:
                            try:
                                target.setdefault(int(n[:4], 16), (e, s))
                            except ValueError:
                                pass
        finally:
            iso.f.close()
        self._sprites = {}

    def sheet(self, cid, console=False):
        """(list of all sprite descriptors, tile data) of the character's UNI file (arcade data, or console data with
        console=True), or None."""
        key = (cid, console)
        if key in self._sprites:
            return self._sprites[key]
        res = None
        index = self.uni_pl if console else self.uni
        if cid in index:
            lba, size = index[cid]
            iso = G.Iso(self.iso_path)
            try:
                data = iso.read(lba, size)
            finally:
                iso.f.close()
            try:
                res = parse_sheet(data)
            except (struct.error, KeyError, IndexError, ValueError):
                res = None
        self._sprites[key] = res
        return res

    def ref_sprite(self, cid, ref):
        """(descriptor, tile data) for a sprite reference (index, or PL_REF + index for console sprites), or None."""
        console = ref >= PL_REF
        sh = self.sheet(cid, console)
        i = ref - PL_REF if console else ref
        if not sh or not 0 <= i < len(sh[0]) or not sprite_tiles(sh[0][i]):
            return None
        return sh[0][i], sh[1]

    def sprite(self, cid):
        """(first idle frame = descriptor 0, or the one from IDLE_SPRITE; tile data), or None."""
        sh = self.sheet(cid)
        if not sh or not sh[0]:
            return None
        i = IDLE_SPRITE.get(cid, 0)
        return (sh[0][i if i < len(sh[0]) else 0], sh[1])

    def effect_ids(self, cid, all_sprites=False):
        """Descriptor numbers of the character's effect sprites (row 1-15); all_sprites: every non-empty sprite."""
        sh = self.sheet(cid)
        if not sh:
            return []
        return [i for i, d in enumerate(sh[0]) if sprite_tiles(d) and (all_sprites or 0 < d[0] < 16)]

    def named(self, cid, with_ldm=True):
        """[(sprite, name)] of the character: the list from gfx_palette_fx.json (valid sprites only) and, when the
        character has row-4 sprites, the LDM hit state (biggest row-4 sprite)."""
        sh = self.sheet(cid)
        if not sh:
            return []
        res = [(i, n) for i, n in load_fx().get(cid, []) if self.ref_sprite(cid, i)]
        if with_ldm:
            ldm = [i for i, d in enumerate(sh[0]) if d and d[0] == LDM_ROW and sprite_tiles(d)]
            if ldm:
                res.append((max(ldm, key=lambda i: sprite_tiles(sh[0][i])), LDM_NAME))
        return res

    def default_effect(self, cid):
        """First named sprite, else the biggest effect sprite; None if there is none."""
        sh = self.sheet(cid)
        if not sh:
            return None
        named = self.named(cid, with_ldm=False)
        if named:
            return named[0][0]
        ids = self.effect_ids(cid)
        # rows 1-4 are mostly after-images / flashes of the body: prefer the real effect rows, then the biggest sprite
        return max(ids, key=lambda i: (sh[0][i][0] >= 5, sprite_tiles(sh[0][i]), -i)) if ids else None


def uni_sections(data):
    n = struct.unpack_from('<I', data, 0)[0]
    table = []
    for i in range(min(n, 64)):
        v = struct.unpack_from('<I', data, 4 + 4 * i)[0]
        if v == 0xFFFFFFFF:
            break
        table.append((v >> 24, v & 0xFFFFFF))
    table.sort(key=lambda e: e[1])
    out = {}
    for i, (sid, off) in enumerate(table):
        end = table[i + 1][1] if i + 1 < len(table) else len(data)
        out[sid] = (off, end)
    return out


def parse_sheet(data):
    """-> ([descriptor bytes of every sprite], tile data)."""
    secs = uni_sections(data)
    a, b = secs[11]
    s11 = data[a:b]
    cnt = struct.unpack_from('<I', s11, 0)[0]
    offs = list(struct.unpack_from('<%dI' % cnt, s11, 4)) + [len(s11)]
    a, b = secs[22]
    return [s11[offs[i]:offs[i + 1]] for i in range(cnt)], data[a:b]


def sprite_row(desc):
    """Sub-palette (row) a sprite is drawn with."""
    return desc[0] if desc and desc[0] < 16 else 0


def sprite_tiles(desc):
    """Number of 8x8 tiles of a sprite (0 = empty)."""
    n = 0
    for pos in range(4, len(desc) - 7, 8):
        tile, run, x, y = struct.unpack_from('<4H', desc, pos)
        if run == 0 or run > 64 or x >= 64 or y >= 64:
            break
        n += run
    return n


def _fx_paths():
    import gfx_targets as T
    return [os.path.join(T.BUNDLE_DIR, FX_FILE), os.path.join(T.APP_DIR, FX_FILE)]


def _read_fx(path):
    import json
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    res = {}
    for k, v in raw.items():
        try:
            cid = int(k, 16)
        except ValueError:
            continue
        if isinstance(v, int):                       # old format: one default sprite
            v = [[v, 'Main effect']]
        # [sprite, name] = arcade data; [sprite, name, "PL"] = console data (stored internally as PL_REF + sprite)
        res[cid] = [(int(e[0]) + (PL_REF if len(e) > 2 and e[2] == 'PL' else 0), str(e[1])) for e in v
                    if isinstance(e[0], int)]
    return res


def load_fx():
    """{char id: [(sprite, name)]}: the bundled list; a file next to the exe / script replaces whole characters."""
    res = {}
    for p in dict.fromkeys(_fx_paths()):
        res.update(_read_fx(p))
    return res


def save_fx(cid, items):
    """Store the named sprite list of one character next to the exe / script (curator mode); returns the path."""
    import json
    p = _fx_paths()[1]
    cur = {'%02X' % c: [[i - PL_REF, n, 'PL'] if i >= PL_REF else [i, n] for i, n in v] for c, v in _read_fx(p).items()}
    cur['%02X' % cid] = [[int(i) - PL_REF, n, 'PL'] if i >= PL_REF else [int(i), n] for i, n in items]
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(cur.items())), f, indent=1)
    return p


def render_idle(sprite, pal, color, sub=0, highlight=None, hl_rgba=(255, 0, 255, 255)):
    """RGBA PIL image of the idle sprite in one colour.  highlight = palette entry (1-15) whose pixels are drawn in
    hl_rgba instead (shows which part of the body an entry colours)."""
    import numpy as np
    from PIL import Image
    desc, pix = sprite
    w, h = max(1, desc[2]) * 8, max(1, desc[3]) * 8
    idx = np.zeros((h, w), np.uint8)
    tiles = np.frombuffer(pix[:len(pix) // 32 * 32], np.uint8).reshape(-1, 32)
    lo, hi = tiles & 15, tiles >> 4
    tile_px = np.stack([lo, hi], -1).reshape(-1, 8, 8)
    for pos in range(4, len(desc) - 7, 8):
        tile, run, x, y = struct.unpack_from('<4H', desc, pos)
        if run == 0 or run > 64 or x >= 64 or y >= 64:
            break
        for k in range(run):
            t = tile + k
            yy = (y + k) * 8
            if t < len(tile_px) and yy + 8 <= h and x * 8 + 8 <= w:
                idx[yy:yy + 8, x * 8:x * 8 + 8] = tile_px[t]
    lut = np.array(sub_rgba(pal, color, sub), np.uint8)
    if highlight:
        lut[highlight] = hl_rgba
    return Image.fromarray(lut[idx], 'RGBA')


# ---------------------------------------------------------------- files
def swatch_image(pal):
    """Swatch PNG: 16 cells per row (palette entries), one row per sub-palette, the 12 colours stacked (16 rows each).
    Entry 0 is transparent."""
    from PIL import Image
    rows = len(pal) // SUB
    im = Image.new('RGBA', (16 * SWATCH_CELL, rows * SWATCH_CELL), (0, 0, 0, 0))
    px = im.load()
    for r in range(rows):
        for i in range(1, 16):
            c = word_to_rgb(struct.unpack_from('<H', pal, r * SUB + i * 2)[0]) + (255,)
            for yy in range(SWATCH_CELL):
                for xx in range(SWATCH_CELL):
                    px[i * SWATCH_CELL + xx, r * SWATCH_CELL + yy] = c
    return im


def pal_from_swatch(im, orig):
    """Read a swatch PNG back (any cell size: width = 16 cells, height = one cell per sub-palette).  Entry 0 and bit
    15 are taken from orig."""
    im = im.convert('RGBA')
    rows = len(orig) // SUB
    if im.width % 16 or im.height % rows or im.width // 16 != im.height // rows:
        raise SystemExit('swatch PNG must be 16 cells wide and %d cells high (e.g. %dx%d px); this one is %dx%d'
                         % (rows, 16 * SWATCH_CELL, rows * SWATCH_CELL, im.width, im.height))
    cell = im.width // 16
    px = im.load()
    out = bytearray(orig)
    for r in range(rows):
        for i in range(1, 16):
            c = px[i * cell + cell // 2, r * cell + cell // 2]
            o = r * SUB + i * 2
            old = struct.unpack_from('<H', out, o)[0]
            struct.pack_into('<H', out, o, rgb_to_word(c, old))
    return bytes(out)


# ---------------------------------------------------------------- common palette file formats
# One colour slot = 16 rows x 16 entries = 256 colours, which is exactly what the usual palette formats hold:
# JASC-PAL (.pal, text: Paint Shop Pro, GIMP, Aseprite, GraphicsGale, ...), GIMP / Krita / Inkscape (.gpl) and
# Photoshop (.act).  Microsoft RIFF .pal is read as well.  Entry 0 of every row (transparent) and bit 15 are always
# kept from the game data on import.
PAL_FORMATS = [('JASC palette (Paint Shop Pro, GIMP, Aseprite, ...)', '.pal'),
               ('GIMP / Krita / Inkscape palette', '.gpl'), ('Photoshop palette', '.act')]


def color_rgbs(pal, color):
    """256 RGB tuples of one colour slot (rows missing in a short palette are black)."""
    res = []
    for sub in range(16):
        for i in range(16):
            o = color * BLOCK + sub * SUB + i * 2
            res.append(word_to_rgb(struct.unpack_from('<H', pal, o)[0]) if o + 2 <= len(pal) else (0, 0, 0))
    return res


def write_palette(path, rgbs, name='KOF XI palette'):
    """Write RGB tuples in the format given by the extension (.pal = JASC, .gpl, .act)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.act':
        data = b''.join(bytes(c[:3]) for c in rgbs[:256])
        data += bytes(768 - len(data))
        with open(path, 'wb') as f:
            f.write(data)
        return
    if ext == '.gpl':
        lines = ['GIMP Palette', 'Name: %s' % name, 'Columns: 16', '#']
        lines += ['%3d %3d %3d\trow %d entry %d' % (c[0], c[1], c[2], k // 16, k % 16) for k, c in enumerate(rgbs)]
    else:
        lines = ['JASC-PAL', '0100', str(len(rgbs))] + ['%d %d %d' % tuple(c[:3]) for c in rgbs]
    with open(path, 'w', encoding='ascii', newline='\r\n' if ext != '.gpl' else '\n') as f:
        f.write('\n'.join(lines) + '\n')


def read_palette(path):
    """RGB tuples from a JASC .pal, GIMP .gpl, Photoshop .act or Microsoft RIFF .pal file; None if it is none of
    these (e.g. the raw game format)."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] == b'JASC-PAL':
        rows = data.decode('ascii', 'replace').split()
        n = int(rows[2])
        vals = [int(v) for v in rows[3:3 + 3 * n]]
        return [tuple(vals[k:k + 3]) for k in range(0, len(vals) - 2, 3)]
    if data[:12] == b'GIMP Palette':
        res = []
        for line in data.decode('utf-8', 'replace').splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                res.append(tuple(int(p) for p in parts[:3]))
        return res
    if data[:4] == b'RIFF' and data[8:12] == b'PAL ':
        n = struct.unpack_from('<H', data, 22)[0]
        return [tuple(data[24 + 4 * k:27 + 4 * k]) for k in range(n)]
    if path.lower().endswith('.act') and len(data) in (768, 772):
        n = struct.unpack_from('>H', data, 768)[0] if len(data) == 772 else 256
        return [tuple(data[3 * k:3 * k + 3]) for k in range(min(256, n or 256))]
    return None


def apply_rgbs(orig, rgbs, colors):
    """Palette bytes with the given colour slots replaced by 256 RGB tuples each (rgbs holds the slots in order)."""
    out = bytearray(orig)
    for n, color in enumerate(colors):
        for sub in range(subs_in_color(out, color)):
            for i in range(1, 16):
                k = n * 256 + sub * 16 + i
                if k < len(rgbs):
                    set_rgb(out, color, sub, i, rgbs[k])
    return bytes(out)


def load_file(path, orig, color=None):
    """Palette bytes of the original's size from: the raw game .PAL, a swatch PNG, or a common palette file.
    color = slot that a single-colour (256 entry) palette file goes to; a palette with 12 x 256 entries replaces all
    colours."""
    if path.lower().endswith('.png'):
        from PIL import Image
        return pal_from_swatch(Image.open(path), orig)
    rgbs = read_palette(path)
    if rgbs is None:
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) != len(orig):
            raise SystemExit('%s is neither a palette file (JASC .pal, .gpl, .act) nor the game format (%d bytes, '
                             'this character needs %d)' % (os.path.basename(path), len(data), len(orig)))
        return data
    n = n_colors(orig)
    if len(rgbs) >= n * 256 - 64:            # whole character (Shen Woo's last slot is a bit shorter)
        return apply_rgbs(orig, rgbs, range(n))
    if len(rgbs) >= 16:
        if color is None:
            raise SystemExit('%s has %d colours = one colour slot: use "Import into this colour"'
                             % (os.path.basename(path), len(rgbs)))
        return apply_rgbs(orig, rgbs, [color])
    raise SystemExit('%s has only %d colours' % (os.path.basename(path), len(rgbs)))


def file_char_id(path):
    """'00_ash.pal' / '2E.PAL' / 'PAL_2E.pal' -> 0x00 / 0x2E; None if the name has no id."""
    import re
    m = re.match(r'(?i)(?:pal_?)?([0-9a-f]{2})(?:[^0-9a-f]|$)', os.path.basename(path))
    if not m:
        return None
    cid = int(m.group(1), 16)
    return cid if cid in CHAR_NAMES else None


def file_name(cid):
    return '%02X_%s.PAL' % (cid, ''.join(ch for ch in CHAR_NAMES[cid].replace(' ', '_') if ch.isalnum() or ch == '_'))


def scan_folder(folder, src=None):
    """-> {cid: path} of the palette files in a folder (later names win)."""
    res = {}
    if folder and os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            p = os.path.join(folder, fn)
            if os.path.isfile(p) and fn.lower().endswith('.pal'):
                cid = file_char_id(fn)
                if cid is not None:
                    res[cid] = p
    return res


# ---------------------------------------------------------------- patching
def patch_palettes(iso_path, pals, log=print):
    """Write {cid: palette bytes} into FIGHT.BCC and FIGHTA.BCC of iso_path (in place) and verify by reading back."""
    if not pals:
        return
    iso = G.Iso(iso_path, write=True)
    try:
        for path in BCC_PATHS:
            lba, size, stream, data = G.bcc_load(iso, path)
            cnt, offs = G.container_entries(data)
            new = bytearray(data)
            lo, hi = len(data), 0
            for cid, pal in sorted(pals.items()):
                e = entry_index(cid)
                a, b = offs[e], offs[e + 1]
                if len(pal) != b - a:
                    raise SystemExit('%s: palette has %d bytes, the disc has %d' % (CHAR_NAMES[cid], len(pal), b - a))
                if data[a:b] != pal:
                    new[a:b] = pal
                    lo, hi = min(lo, a), max(hi, b)
            if hi:
                G.bcc_write(iso, path, bytes(new), lo, hi)
        iso.f.flush()
    finally:
        iso.f.close()
    iso = G.Iso(iso_path)
    try:
        for path in BCC_PATHS:
            lba, size, stream, data = G.bcc_load(iso, path)
            cnt, offs = G.container_entries(data)
            for cid, pal in pals.items():
                e = entry_index(cid)
                if data[offs[e]:offs[e + 1]] != pal:
                    raise SystemExit('verification failed: %s palette in %s' % (CHAR_NAMES[cid], path))
    finally:
        iso.f.close()
    log('character palettes written and verified (FIGHT.BCC + FIGHTA.BCC): %s'
        % ', '.join(CHAR_NAMES[c] for c in sorted(pals)))


# ---------------------------------------------------------------- CLI
def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if not a:
        print(__doc__)
        return 1
    cmd = a[0]
    if cmd == 'list':
        src = Source(a[1])
        for cid in CHAR_IDS:
            print('%s  palette %d bytes  sprite %s' % (char_label(cid).ljust(20), len(src.pals[cid]),
                                                        'yes' if src.sprite(cid) else 'no'))
        if src.mismatch:
            print('FIGHT.BCC and FIGHTA.BCC differ for:', ', '.join(CHAR_NAMES[c] for c in src.mismatch))
    elif cmd == 'export':
        src = Source(a[1])
        cid, out = int(a[2], 16), a[3]
        if out.lower().endswith('.png'):
            swatch_image(src.pals[cid]).save(out)
        else:
            with open(out, 'wb') as f:
                f.write(src.pals[cid])
        print('written', out)
    elif cmd == 'preview':
        src = Source(a[1])
        render_idle(src.sprite(int(a[2], 16)), src.pals[int(a[2], 16)], int(a[3])).save(a[4])
        print('written', a[4])
    elif cmd == 'patch':
        src = Source(a[1])
        pals = {}
        for p in a[2:]:
            cid = file_char_id(p)
            if cid is None:
                raise SystemExit('%s: name must start with the character id, e.g. 00_ash.pal' % p)
            pals[cid] = load_file(p, src.pals[cid])
        patch_palettes(a[1], pals)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
