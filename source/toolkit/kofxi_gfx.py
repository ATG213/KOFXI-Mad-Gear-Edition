r"""KOF XI PS2 (JP) graphics tools: GRC / maz codecs, OPENING.GRC entry images, title-logo replacement.

Formats (all verified against the JP ISO and PCSX2 savestates, see docs/ps2-graphics-db.md):

* GRC (outer layer, FUN_001A43F0): byte LZ.  b < 0xC0 literal; 0xC0|n: n=0 end, n=1 next byte literal,
  n>=2 copy n bytes from (dst - next byte).
* maz (inner layer of OPENING.GRC entries, FUN_001986E0): [u32 unpacked size] then flag bytes; each flag byte
  controls 8 items (MSB first): bit 0 = literal byte, bit 1 = reference byte b: distance = 16 - (b >> 4)
  (1..16), length = b & 15 (0 means 16), byte-wise (overlapping) copy.
* OPENING.GRC after the GRC layer: u32 count, u32 offsets[count], entries.  Entries 1.. are maz streams.
  A decoded entry is a 0x40 byte header (+0xC data offset, +0x10/+0x12 u16 tile w/h, +0x14/+0x15 tile
  columns/rows, +0x18 == 2 means RGBA32 tiles (alpha 0x80 = opaque), else 16 bit ARGB1555) followed by tiles
  of w*h pixels in row-major tile order.

* Menu atlases (MENU\SPR0x.GRC, BG0x.GRC): GRC layer, then 0x400 bytes CLUT (256 x RGBA, CSM1 order: swap entries
  8-15 with 16-23 in every group of 32) and linear 8 bpp pixels, 256 px wide (BG0x: 640 wide).
* PACK\FIGHT.BCC / FIGHTA.BCC: [u32 size][GRC stream]; container like OPENING (count, offsets); entry 1 = PVR header
  with a 256 x 4096 linear ARGB1555 HUD atlas (R = bits 0-4, G 5-9, B 10-14, bit 15 = opaque).

CLI (run with python -I; commands marked * patch the ISO IN PLACE, work on a copy!):
  kofxi_gfx.py tree             ISO                          all files with LBA and size
  kofxi_gfx.py resident         ISO eeMemory.bin             which disc files are in a PCSX2 savestate's EE RAM
  kofxi_gfx.py list-opening     ISO                          OPENING.GRC entries (size, format)
  kofxi_gfx.py export-entry     ISO ENTRY out.png            OPENING.GRC entry as PNG (title logo = 116)
  kofxi_gfx.py replace-entry*   ISO ENTRY in.png             entry from a PNG of the same size
  kofxi_gfx.py export-menu      ISO MENU/SPR01.GRC out.png   menu atlas (read only)
  kofxi_gfx.py export-hud-atlas ISO out.png                  FIGHT.BCC entry 1, 256 x 4096 (read only)
  kofxi_gfx.py replace-attract-logo* ISO logo.png [scale] [dx] [dy]   attract-mode logo (FIGHT.BCC + FIGHTA.BCC)
"""
import struct
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

OPENING_PATH = 'DATA/DEMO/OPENING.GRC'
VARIANT_ELF = {'JP': 'SLPS_256.60', 'US': 'SLUS_216.87'}      # boot ELF in the disc root -> game version


def detect_variant(iso_path):
    """'JP' / 'US' / None (unknown disc or unreadable file)."""
    try:
        iso = Iso(iso_path)
        try:
            return iso.variant()
        finally:
            iso.f.close()
    except (OSError, SystemExit, struct.error, IndexError):
        return None


# ---------------------------------------------------------------- GRC (outer layer)
def grc_tokens(src):
    """Parse a GRC stream into tokens (src_off, out_off, kind, a, b); kind 'L' literal, 'E' escaped literal,
    'C' copy (a=n, b=dist), 'X' end."""
    toks = []
    i = 0
    outpos = 0
    while True:
        b = src[i]
        if (b & 0xC0) == 0xC0:
            n = b & 0x3F
            if n == 0:
                toks.append((i, outpos, 'X', 0, 0))
                return toks, i + 1
            if n == 1:
                toks.append((i, outpos, 'E', src[i + 1], 0))
                outpos += 1
                i += 2
            else:
                toks.append((i, outpos, 'C', n, src[i + 1]))
                outpos += n
                i += 2
        else:
            toks.append((i, outpos, 'L', b, 0))
            outpos += 1
            i += 1


def grc_decompress(src):
    out = bytearray()
    i = 0
    while True:
        b = src[i]
        if (b & 0xC0) == 0xC0:
            n = b & 0x3F
            if n == 0:
                return bytes(out), i + 1
            if n == 1:
                out.append(src[i + 1])
                i += 2
                continue
            dist = src[i + 1]
            i += 2
            p = len(out) - dist
            for _ in range(n):
                out.append(out[p])
                p += 1
        else:
            out.append(b)
            i += 1


def grc_encode_range(data, start, end, depth=48):
    """Greedy GRC encoding of data[start:end]; back references may reach into data[:start] (<=255 bytes).
    No end marker is written."""
    out = bytearray()
    last = {}
    for p in range(max(0, start - 255), start):
        if p + 3 <= len(data):
            last.setdefault(bytes(data[p:p + 3]), []).append(p)
    i = start
    while i < end:
        best_n, best_d = 0, 0
        if i + 3 <= end:
            key = bytes(data[i:i + 3])
            for p in reversed(last.get(key, [])[-depth:]):
                d = i - p
                if d > 255:
                    break
                n = 3
                while n < 63 and i + n < end and data[i + n] == data[i + n - d]:
                    n += 1
                if n > best_n:
                    best_n, best_d = n, d
                    if n == 63:
                        break
        if best_n >= 3:
            out.append(0xC0 | best_n)
            out.append(best_d)
            step = best_n
        else:
            b = data[i]
            if b >= 0xC0:
                out += bytes((0xC1, b))
            else:
                out.append(b)
            step = 1
        for q in range(i, i + step):
            if q + 3 <= len(data):
                lst = last.setdefault(bytes(data[q:q + 3]), [])
                lst.append(q)
                if len(lst) > max(64, depth + 16):
                    del lst[:len(lst) - depth - 16]
        i += step
    return bytes(out)


def grc_splice(orig_stream, new_data, change_start, change_end, depth=48):
    """Return a GRC stream for new_data re-using orig_stream's tokens outside the changed byte range
    [change_start, change_end).  new_data must have the same length as the original unpacked data."""
    toks, _ = grc_tokens(orig_stream)
    a_idx = max(i for i, t in enumerate(toks) if t[1] <= change_start and t[2] != 'X')
    guard = change_end + 255
    b_idx = next(i for i, t in enumerate(toks) if t[1] >= guard or t[2] == 'X')
    a_src, a_out = toks[a_idx][0], toks[a_idx][1]
    b_src, b_out = toks[b_idx][0], toks[b_idx][1]
    mid = grc_encode_range(new_data, a_out, b_out, depth)
    return orig_stream[:a_src] + mid + orig_stream[b_src:]


# ---------------------------------------------------------------- maz (inner layer)
def maz_decompress(src, start=0):
    size = int.from_bytes(src[start:start + 4], 'little')
    i = start + 4
    out = bytearray()
    while len(out) < size:
        flag = src[i]
        i += 1
        for bit in range(7, -1, -1):
            if len(out) >= size:
                break
            if not (flag >> bit) & 1:
                out.append(src[i])
                i += 1
            else:
                b = src[i]
                i += 1
                dist = 16 - (b >> 4)
                n = (b & 15) or 16
                for _ in range(n):
                    out.append(out[-dist])
    return bytes(out[:size]), i


def maz_compress(data):
    """Minimum item count parse (jump-game greedy), dist 1..16, len 1..16."""
    import numpy as np
    a = np.frombuffer(data, dtype=np.uint8)
    n = len(a)
    best = np.zeros(n, np.int32)
    bestd = np.zeros(n, np.int32)
    for d in range(1, 17):
        eq = np.zeros(n, bool)
        eq[d:] = a[d:] == a[:-d]
        run = np.zeros(n, np.int32)
        cur = np.ones(n, bool)
        for k in range(16):
            e = np.zeros(n, bool)
            e[:n - k] = eq[k:]
            cur &= e
            run += cur
        better = run > best
        best[better] = run[better]
        bestd[better] = d
    length = np.maximum(best, 1)
    reach = np.arange(n) + length
    items = []
    pos = 0
    while pos < n:
        if pos + length[pos] >= n:
            j = n
        else:
            lo, hi = pos + 1, pos + int(length[pos])
            j = lo + int(np.argmax(reach[lo:hi + 1]))
        ln = j - pos
        if ln > 1:
            items.append((1, ((16 - int(bestd[pos])) << 4) | (ln & 15)))
        else:
            items.append((0, data[pos]))
        pos = j
    out = bytearray(n.to_bytes(4, 'little'))
    for g in range(0, len(items), 8):
        grp = items[g:g + 8]
        flag = 0
        for k, (t, _) in enumerate(grp):
            flag |= t << (7 - k)
        out.append(flag)
        for _, v in grp:
            out.append(v)
    return bytes(out)


# ---------------------------------------------------------------- OPENING.GRC container
def container_entries(cont):
    cnt = struct.unpack_from('<I', cont, 0)[0]
    offs = [struct.unpack_from('<I', cont, 4 + 4 * i)[0] for i in range(cnt)] + [len(cont)]
    return cnt, offs


def entry_header(d):
    w, h = struct.unpack_from('<HH', d, 0x10)
    return {'data': struct.unpack_from('<I', d, 0xC)[0], 'w': w, 'h': h, 'cols': d[0x14], 'rows': d[0x15],
            'rgba32': d[0x18] == 2}


def entry_to_image(d):
    import numpy as np
    from PIL import Image
    hd = entry_header(d)
    w, h, c, r = hd['w'], hd['h'], hd['cols'], hd['rows']
    bpp = 4 if hd['rgba32'] else 2
    ts = w * h * bpp
    img = np.zeros((r * h, c * w, 4), np.uint8)
    for t in range(c * r):
        raw = np.frombuffer(d[hd['data'] + t * ts: hd['data'] + (t + 1) * ts], dtype=np.uint8)
        if bpp == 4:
            px = raw.reshape(h, w, 4).copy()
            px[..., 3] = np.minimum(255, px[..., 3].astype(int) * 2).astype(np.uint8)
        else:
            v = raw.view('<u2').reshape(h, w).astype(np.int32)
            a = np.where(v & 0x8000, 255, 0)
            # PS2 channel order: R = bits 0-4, G = 5-9, B = 10-14 (fixed 2026-11-19: it was decoded as R = bits 10-14,
            # which showed red and blue swapped for all 87 ARGB1555 entries)
            px = np.stack([(v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31, a],
                          -1).astype(np.uint8)
        x, y = (t % c) * w, (t // c) * h
        img[y:y + h, x:x + w] = px
    return Image.fromarray(img, 'RGBA')


def image_to_entry(img, template):
    """Build a decoded entry from an RGBA PNG using the header/tiling of the decoded template entry."""
    import numpy as np
    hd = entry_header(template)
    w, h, c, r = hd['w'], hd['h'], hd['cols'], hd['rows']
    if img.size != (c * w, r * h):
        raise SystemExit('PNG must be %dx%d, got %dx%d' % (c * w, r * h, img.size[0], img.size[1]))
    arr = np.array(img.convert('RGBA'))
    out = bytearray(template[:hd['data']])
    for t in range(c * r):
        x, y = (t % c) * w, (t // c) * h
        tile = arr[y:y + h, x:x + w]
        if hd['rgba32']:
            px = tile.copy()
            px[..., 3] = ((tile[..., 3].astype(int) * 128 + 127) // 255).astype(np.uint8)
            out += px.tobytes()
        else:
            R = (tile[..., 0].astype(int) * 31 + 127) // 255      # round to nearest: decode -> encode keeps every level
            G = (tile[..., 1].astype(int) * 31 + 127) // 255
            B = (tile[..., 2].astype(int) * 31 + 127) // 255
            A = np.where(tile[..., 3] >= 128, 0x8000, 0)
            out += (A | (B << 10) | (G << 5) | R).astype('<u2').tobytes()
    if len(out) != len(template):
        raise SystemExit('internal error: entry size changed')
    return bytes(out)


# ---------------------------------------------------------------- ISO access
class Iso:
    def __init__(self, path, write=False):
        self.f = open(path, 'r+b' if write else 'rb')
        pvd = self.read(16, 2048)
        self.root = struct.unpack('<I', pvd[158:162])[0]
        self.rsz = struct.unpack('<I', pvd[166:170])[0]

    def read(self, lba, n):
        self.f.seek(lba * 2048)
        return self.f.read(n)

    def listdir(self, lba, size):
        data = self.read(lba, size)
        o = 0
        res = []
        while o < size:
            ln = data[o]
            if ln == 0:
                o = (o // 2048 + 1) * 2048
                continue
            e = struct.unpack('<I', data[o + 2:o + 6])[0]
            s = struct.unpack('<I', data[o + 10:o + 14])[0]
            fl = data[o + 25]
            nm = data[o + 33:o + 33 + data[o + 32]].decode('latin1')
            if nm not in ('\x00', '\x01'):
                res.append((nm.split(';')[0], e, s, fl & 2))
            o += ln
        return res

    def find(self, path):
        lba, size = self.root, self.rsz
        for p in path.split('/'):
            for n, e, s, d in self.listdir(lba, size):
                if n.upper() == p.upper():
                    lba, size = e, s
                    break
            else:
                raise SystemExit('not found on ISO: ' + path)
        return lba, size

    def variant(self):
        """'JP' (SLPS-25660), 'US' (SLUS-21687) or None, from the boot ELF in the root directory."""
        names = {n.upper() for n, _, _, _ in self.listdir(self.root, self.rsz)}
        for key, elf in VARIANT_ELF.items():
            if elf in names:
                return key
        return None

    def load_opening(self):
        lba, size = self.find(OPENING_PATH)
        # the game reads whole sectors (count comes from the ELF file table), not the directory byte size
        raw = self.read(lba, (size + 2047) // 2048 * 2048)
        cont, used = grc_decompress(raw)
        return lba, size, raw[:used], cont


# ---------------------------------------------------------------- operations
def replace_entry(iso_path, entry, png_path):
    from PIL import Image
    iso = Iso(iso_path, write=True)
    lba, size, stream, cont = iso.load_opening()
    cnt, offs = container_entries(cont)
    slot = cont[offs[entry]:offs[entry + 1]]
    template, _ = maz_decompress(slot)
    new_entry = image_to_entry(Image.open(png_path), template)
    comp = maz_compress(new_entry)
    assert maz_decompress(comp)[0] == new_entry
    if len(comp) > len(slot):
        raise SystemExit('compressed entry %d bytes does not fit its slot of %d bytes' % (len(comp), len(slot)))
    new_slot = comp + b'\x00' * (len(slot) - len(comp))
    new_cont = cont[:offs[entry]] + new_slot + cont[offs[entry + 1]:]
    new_stream = grc_splice(stream, new_cont, offs[entry], offs[entry + 1])
    chk, _ = grc_decompress(new_stream)
    assert chk == new_cont, 'GRC splice verification failed'
    sectors = (size + 2047) // 2048
    if len(new_stream) > sectors * 2048:
        raise SystemExit('new OPENING.GRC (%d bytes) does not fit its %d sectors' % (len(new_stream), sectors))
    print('entry %d: compressed %d of slot %d; OPENING.GRC stream %d -> %d bytes (limit %d)'
          % (entry, len(comp), len(slot), len(stream), len(new_stream), sectors * 2048))
    iso.f.seek(lba * 2048)
    iso.f.write(new_stream + b'\x00' * (sectors * 2048 - len(new_stream)))
    iso.f.close()
    print('written at LBA', lba)


def bcc_load(iso, path):
    """Return (lba, size, stream, data) of a .BCC file: [u32 unpacked size][GRC stream]."""
    lba, size = iso.find(path)
    raw = iso.read(lba, (size + 2047) // 2048 * 2048)
    data, used = grc_decompress(raw[4:])
    assert struct.unpack_from('<I', raw, 0)[0] == len(data)
    return lba, size, raw[4:4 + used], data


def bcc_write(iso, path, new_data, change_start, change_end):
    lba, size, stream, data = bcc_load(iso, path)
    assert len(new_data) == len(data)
    new_stream = grc_splice(stream, new_data, change_start, change_end)
    chk, _ = grc_decompress(new_stream)
    assert chk == new_data, 'GRC splice verification failed'
    sectors = (size + 2047) // 2048
    blob = struct.pack('<I', len(new_data)) + new_stream
    if len(blob) > sectors * 2048:
        raise SystemExit('%s: new file %d bytes does not fit %d sectors' % (path, len(blob), sectors))
    iso.f.seek(lba * 2048)
    iso.f.write(blob + bytes(sectors * 2048 - len(blob)))
    print('%s: %d -> %d bytes (limit %d)' % (path, size, len(blob), sectors * 2048))


# ---------------------------------------------------------------- attract-mode logo (FIGHT.BCC / FIGHTA.BCC)
# Entry 1 of both files is a PVR container holding a 256 x 4096 linear ARGB1555 atlas (PS2 channel order:
# R = bits 0-4, G = bits 5-9, B = bits 10-14, bit 15 = opaque).  The attract logo is drawn 1:1 from four pieces
# (found with colour probes and template matching on a savestate screenshot, see docs/ps2-graphics-db.md).
# piece: (atlas rows y0, y1, cols x0, x1, screen_dy, screen_dx) with screen = (atlas y + dy, atlas x + dx)
# in the 640x480 PCSX2 screenshot frame.
# The rectangles are the regions that get overwritten (generous, so no pixel of the old logo stays behind), they
# must not touch other HUD sprites: the portrait icons end at atlas row 3839 for x >= 188, the next ones start at 3650.
ATTRACT_PIECES = [
    ('A', 2998, 3082, 0, 256, -2864, 228),    # upper half with the "THE KING OF FIGHTERS XI" line
    ('C1', 3826, 3892, 0, 188, -3632, 228),   # lower half, left part
    ('C2', 3840, 3892, 188, 256, -3632, 228),  # lower half, right part (below the portrait icons)
    ('B', 3584, 3648, 176, 256, -3376, -28),  # lower left spike
    ('D', 2788, 2820, 208, 256, -2608, -28),  # upper left corner
]
# Only the union of A and C is drawable under the middle of the logo (x 231-445, y 135-256 on screen); B and D only
# cover the two left spikes.  The new logo is fitted into this area, so nothing is cut off at the bottom.
# Atlas texels the logo tool must NOT write: the red "QUICK" bar (Quick Shift popup) is drawn from rows 3072-3079, x 120-224 of this atlas
# (found with a position-coded probe ISO, 2026-11-22: the bar sprite shares the texels of the original logo's orange underline).  Overwriting
# them made the bar vanish and left a brown/gold fragment of the new logo next to "QUICK".  (y0, y1, x0, x1), end exclusive, a bit generous.
# Piece C draws the same screen rows with the same logo content, so nothing is lost.
ATTRACT_KEEP = ((3072, 3080, 112, 232),)
ATTRACT_CANVAS = (231, 135, 445, 256)      # screen x0, y0, x1, y1 (214 x 121)
ATTRACT_CENTER_X = 320                     # horizontal screen centre of the 640 px wide frame
ATTRACT_PATHS = ('DATA/PACK/FIGHT.BCC', 'DATA/PACK/FIGHTA.BCC')


def attract_canvas(png_path, scale=1.0, dx=0, dy=0):
    """Fit an RGBA image into the attract canvas (contain, centred); returns an RGBA numpy array."""
    import numpy as np
    from PIL import Image
    im = (png_path if isinstance(png_path, Image.Image) else Image.open(png_path)).convert('RGBA')
    bbox = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    cw, ch = ATTRACT_CANVAS[2] - ATTRACT_CANVAS[0], ATTRACT_CANVAS[3] - ATTRACT_CANVAS[1]
    # centre on the screen centre (x = 320), not on the drawable area (its middle is x = 338): the logo may only be
    # as wide as the area is on both sides of x = 320
    half = min(ATTRACT_CENTER_X - ATTRACT_CANVAS[0], ATTRACT_CANVAS[2] - ATTRACT_CENTER_X)
    s = min(2 * half / im.width, ch / im.height) * scale
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    canvas = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    # dx / dy shift the logo in game pixels after centring (a logo whose visual mass is left of its bounding box centre
    # looks off-centre: Mad Gear measured 3 px left, so dx=3 compensates)
    canvas.paste(im, (ATTRACT_CENTER_X - ATTRACT_CANVAS[0] - im.width // 2 + dx, (ch - im.height) // 2 + dy))
    return np.array(canvas)


def replace_attract_logo(iso_path, png_path, scale=1.0, dx=0, dy=0):
    replace_attract_canvas(iso_path, attract_canvas(png_path, scale, dx, dy))


def replace_attract_canvas(iso_path, canvas):
    """Write a ready 214 x 121 RGBA canvas (numpy array, see attract_canvas) into both BCC files."""
    iso = Iso(iso_path, write=True)
    cx0, cy0 = ATTRACT_CANVAS[0], ATTRACT_CANVAS[1]
    for path in ATTRACT_PATHS:
        lba, size, stream, data = bcc_load(iso, path)
        cnt, offs = container_entries(data)
        e0 = offs[1]
        base = e0 + data[e0:offs[2]].index(b'PVRT') + 16
        new = bytearray(data)
        lo, hi = len(data), 0
        for name, y0, y1, x0, x1, dy, dx in ATTRACT_PIECES:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    if any(ky0 <= y < ky1 and kx0 <= x < kx1 for ky0, ky1, kx0, kx1 in ATTRACT_KEEP):
                        continue         # texels shared with another sprite (QUICK bar), keep the original
                    sy, sx = y + dy - cy0, x + dx - cx0
                    px = canvas[sy, sx] if 0 <= sy < canvas.shape[0] and 0 <= sx < canvas.shape[1] else None
                    if px is not None and px[3] >= 128:
                        v = 0x8000 | (int(px[0]) >> 3) | ((int(px[1]) >> 3) << 5) | ((int(px[2]) >> 3) << 10)
                    else:
                        v = 0x03E0       # transparent (green key colour like the original atlas)
                    struct.pack_into('<H', new, base + (y * 256 + x) * 2, v)
            lo = min(lo, base + y0 * 512)
            hi = max(hi, base + y1 * 512)
        bcc_write(iso, path, bytes(new), lo, hi)
    iso.f.close()


def iso_files(iso, lba=None, size=None, prefix=''):
    """Yield (path, lba, size) for every file of the ISO (recursive)."""
    if lba is None:
        lba, size = iso.root, iso.rsz
    for name, e, s, is_dir in iso.listdir(lba, size):
        if is_dir:
            yield from iso_files(iso, e, s, prefix + name + '/')
        else:
            yield prefix + name, e, s


def export_menu_atlas(iso, path, out_png):
    """MENU/SPR0x.GRC and BG0x.GRC: CLUT + linear 8 bpp (256 wide; BG0x 640 wide)."""
    import numpy as np
    from PIL import Image
    lba, size = iso.find(path)
    raw = iso.read(lba, (size + 2047) // 2048 * 2048)
    d, _ = grc_decompress(raw)
    w = 640 if '/BG' in path.upper() else 256
    pal = [tuple(d[4 * i:4 * i + 4]) for i in range(256)]
    sw = pal[:]
    for g in range(0, 256, 32):
        for k in range(8):
            sw[g + 8 + k], sw[g + 16 + k] = pal[g + 16 + k], pal[g + 8 + k]
    px = np.frombuffer(d[0x400:0x400 + (len(d) - 0x400) // w * w], dtype=np.uint8).reshape(-1, w)
    lut = np.array([(r, gg, b, min(255, a * 2)) for r, gg, b, a in sw], dtype=np.uint8)
    Image.fromarray(lut[px], 'RGBA').save(out_png)


def hud_atlas(iso):
    """Return (data, base) of FIGHT.BCC: decoded container and the byte offset of the 256x4096 ARGB1555 atlas."""
    lba, size, stream, data = bcc_load(iso, ATTRACT_PATHS[0])
    cnt, offs = container_entries(data)
    base = offs[1] + data[offs[1]:offs[2]].index(b'PVRT') + 16
    return data, base


def export_hud_atlas(iso, out_png):
    import numpy as np
    from PIL import Image
    data, base = hud_atlas(iso)
    px = np.frombuffer(data[base:base + 1024 * 1024 * 2], dtype='<u2').reshape(4096, 256).astype(int)
    rgba = np.stack([(px & 31) * 255 // 31, ((px >> 5) & 31) * 255 // 31, ((px >> 10) & 31) * 255 // 31,
                     np.where(px & 0x8000, 255, 0)], -1).astype(np.uint8)
    Image.fromarray(rgba, 'RGBA').save(out_png)


def find_resident(iso, ee_memory_path):
    """Print the disc files (raw or unpacked) whose contents are found in a savestate's EE RAM dump."""
    ram = open(ee_memory_path, 'rb').read()

    def probes(buf):
        out = []
        for frac in (0.2, 0.4, 0.6, 0.8):
            p = int(len(buf) * frac)
            c = buf[p:p + 40]
            if len(set(c)) >= 8 and c.count(0) < 20:
                out.append(c)
        return out

    for path, lba, size in iso_files(iso):
        if size < 6144 or size > 13_000_000 or path.startswith(('MODULES', 'NF/', 'NTCNFBIN', 'CNF', 'LICENSE')):
            continue
        if any(s in path for s in ('DNAS', 'KDDI', 'NET_MES', 'ZDX', '/MC/')):
            continue
        raw = iso.read(lba, size)
        views = [('raw', raw)]
        try:
            if path.endswith(('.GRC', '.LZ', '.PK', '.MDP')):
                views.append(('unpacked', grc_decompress(raw)[0]))
            elif path.endswith('.BCC'):
                views.append(('unpacked', grc_decompress(raw[4:])[0]))
        except Exception:
            pass
        for kind, buf in views:
            hits = sum(1 for c in probes(buf) if ram.find(c) >= 0)
            if hits:
                print('%-34s %-9s %d/4 probes' % (path, kind, hits))
                break


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'tree':
        for p, lba, size in iso_files(Iso(argv[2])):
            print('%s\t%d\t%d' % (p, lba, size))
    elif cmd == 'resident':
        find_resident(Iso(argv[2]), argv[3])
    elif cmd == 'export-menu':
        export_menu_atlas(Iso(argv[2]), argv[3], argv[4])
    elif cmd == 'export-hud-atlas':
        export_hud_atlas(Iso(argv[2]), argv[3])
    elif cmd == 'list-opening':
        _, _, _, cont = Iso(argv[2]).load_opening()
        cnt, offs = container_entries(cont)
        for k in range(1, cnt):
            d, _ = maz_decompress(cont[offs[k]:offs[k + 1]])
            hd = entry_header(d)
            print(k, '%dx%d' % (hd['cols'] * hd['w'], hd['rows'] * hd['h']), 'RGBA32' if hd['rgba32'] else 'ARGB1555')
    elif cmd == 'export-entry':
        _, _, _, cont = Iso(argv[2]).load_opening()
        cnt, offs = container_entries(cont)
        k = int(argv[3])
        d, _ = maz_decompress(cont[offs[k]:offs[k + 1]])
        entry_to_image(d).save(argv[4])
    elif cmd == 'replace-entry':
        replace_entry(argv[2], int(argv[3]), argv[4])
    elif cmd == 'replace-attract-logo':
        replace_attract_logo(argv[2], argv[3], float(argv[4]) if len(argv) > 4 else 1.0,
                             int(argv[5]) if len(argv) > 5 else 0, int(argv[6]) if len(argv) > 6 else 0)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
