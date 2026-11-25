r"""KOF XI PS2 (JP): check / auto-convert PNGs and patch them into a COPY of the ISO.  Engine + CLI of gfx_app.py.

Targets are named like the exported files: LOGO00..LOGO05, NEW00..NEW10 (raw 640x512 RGBA), e001..e122 (OPENING.GRC
entries, e116 = title logo) and attract (attract-mode logo).  Any file whose name STARTS with such a key
('e116_my_logo.png') is matched to it.  See gfx_targets.py.

CLI (python -I; the source ISO is only read):
  gfx_convert.py check FILE.png [--target KEY] [--fit] [--quantize]
  gfx_convert.py patch SRC.iso DST.iso --folder DIR [--only KEY,KEY] [--fit] [--quantize] [--force] [--dry-run]
  gfx_convert.py patch SRC.iso DST.iso --title t.png --start s.png --attract a.png [--file KEY=PNG ...]

  --fit       scale a PNG of the wrong size (contain, centred) instead of reporting an error
  --quantize  allowed to reduce colours automatically when an OPENING entry does not fit its slot
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I does not add the script dir

import numpy as np
from PIL import Image

import gfx_targets as T
import kofxi_gfx as G

START_SIZE = 0x140000
RAW_PATHS = {'LOGO%02d' % i: 'DATA/LOGO/LOGO%02d.DAT' % i for i in range(6)}
RAW_PATHS.update({'NEW%02X' % i: 'DATA/PLUS/NEW%02X.DAT' % i for i in range(17)})
# US disc (SLUS-21687): start-up logos are plain RGB24 files (SNK = LOGO04, ADX/CRI = LOGO03; the other JP logos do not
# exist), the unlock pictures are DATA/PLUS/NEW01..11.RAW = JP NEW00..10, 640x448 BGR24 (no alpha, no padding rows).
US_RAW = {'LOGO03': ('DATA/LOGO/CRI.RAW', (640, 512), 'RGB'), 'LOGO04': ('DATA/LOGO/SNK.RAW', (640, 512), 'RGB')}
US_RAW.update({'NEW%02X' % i: ('DATA/PLUS/NEW%02X.RAW' % (i + 1), (640, 448), 'BGR') for i in range(17)})


def raw_spec(key, variant):
    """(path on the disc, (w, h), codec) of a raw target for a disc version ('JP' / 'US'); None if that disc has none."""
    key = key.upper()
    if variant == 'US':
        return US_RAW.get(key)
    return (RAW_PATHS[key], (640, 512), 'RGBA') if key in RAW_PATHS else None


def raw_sizes(key):
    """Accepted PNG sizes of a raw target: NEW pictures may come as 640x512 (JP) or 640x448 (US, same picture)."""
    return [(640, 512), (640, 448)] if key.upper().startswith('NEW') else [(640, 512)]


def adapt_raw(im, size):
    """Bring a PNG of an accepted size to the native size of the disc: crop the 64 padding rows (US) or pad them with
    opaque white (JP, the original has white there)."""
    if im.size == size:
        return im
    if im.height > size[1]:
        return im.crop((0, 0, size[0], size[1]))
    c = Image.new('RGBA', size, (255, 255, 255, 255))
    c.paste(im, (0, 0))
    return c


def encode_for(im, spec):
    """Raw file content for a native-size RGBA image."""
    codec = spec[2]
    if codec == 'RGBA':
        return encode_raw(im)
    a = np.array(im.convert('RGBA')).astype(np.float64)
    rgb = np.rint(a[..., :3] * (a[..., 3:4] / 255.0)).astype(np.uint8)       # transparent areas become black
    if codec == 'BGR':
        rgb = rgb[..., ::-1]
    return np.ascontiguousarray(rgb).tobytes()


def decode_for(d, spec):
    codec, (w, h) = spec[2], spec[1]
    if codec == 'RGBA':
        return decode_raw(d)
    arr = np.frombuffer(d[:w * h * 3], np.uint8).reshape(h, w, 3)
    if codec == 'BGR':
        arr = arr[..., ::-1]
    return Image.fromarray(np.ascontiguousarray(arr), 'RGB').convert('RGBA')
# colour ladder for entries that do not fit their slot: (colours or None = keep, binarise alpha)
LADDER = [(None, True), (256, True), (192, True), (128, True), (112, True), (96, True), (80, True), (64, True),
          (56, True), (48, True), (40, True), (32, True), (24, True), (16, True), (12, True), (8, True)]
_OPENING_CACHE = {}


# ---------------------------------------------------------------- image helpers
def clean_transparent(im):
    a = np.array(im)
    a[a[..., 3] == 0, :3] = 0
    return Image.fromarray(a, 'RGBA')


def fit_to(im, size):
    s = min(size[0] / im.width, size[1] / im.height)
    nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
    c = Image.new('RGBA', size, (0, 0, 0, 0))
    c.paste(im.resize((nw, nh), Image.LANCZOS), ((size[0] - nw) // 2, (size[1] - nh) // 2))
    return c


def quantize(im, ncolors, binarize):
    a = np.array(im)
    alpha = np.where(a[..., 3] >= 128, 255, 0).astype(np.uint8) if binarize else a[..., 3]
    out = a.copy()
    out[..., 3] = alpha
    if ncolors:
        mask = alpha > 0
        rgb = Image.fromarray(a[..., :3], 'RGB')
        vis = Image.fromarray(a[..., :3][mask].reshape(1, -1, 3), 'RGB') if mask.any() else rgb
        pal = vis.quantize(colors=ncolors, method=Image.MEDIANCUT, dither=Image.NONE)
        out[..., :3] = np.array(rgb.quantize(palette=pal, dither=Image.NONE).convert('RGB'))
    out[out[..., 3] == 0, :3] = 0
    return Image.fromarray(out, 'RGBA')


def count_colors(im):
    a = np.array(im).reshape(-1, 4)
    a = a[a[:, 3] > 0]
    return len(np.unique(a, axis=0)) if len(a) else 0


def encode_raw(im):
    out = bytearray()
    T_ = 128
    for r in range(4):
        for c in range(5):
            arr = np.array(im.crop((c * T_, r * T_, c * T_ + T_, r * T_ + T_)))
            arr[..., 3] = ((arr[..., 3].astype(int) * 128 + 127) // 255).astype(np.uint8)
            out += arr.tobytes()
    assert len(out) == START_SIZE
    return bytes(out)


def decode_raw(d):
    im = Image.new('RGBA', (640, 512))
    for r in range(4):
        for c in range(5):
            o = (c + r * 5) * 0x10000
            arr = np.frombuffer(d[o:o + 0x10000], np.uint8).reshape(128, 128, 4).copy()
            arr[..., 3] = np.minimum(255, arr[..., 3].astype(int) * 2).astype(np.uint8)
            im.paste(Image.fromarray(arr, 'RGBA'), (c * 128, r * 128))
    return im


def synth_template(target):
    """A decoded OPENING entry (header + zero pixels) of the right size, from the catalog header."""
    hd = G.entry_header(target.header)
    bpp = 4 if hd['rgba32'] else 2
    return target.header + bytes(hd['cols'] * hd['rows'] * hd['w'] * hd['h'] * bpp)


def attract_game_view(canvas):
    p = canvas.copy()
    # int math: on uint8 the product (n * 255) overflowed and the preview turned black
    p[..., :3] = (((canvas[..., :3].astype(int) >> 3) * 255) // 31).astype(np.uint8)
    p[..., 3] = np.where(canvas[..., 3] >= 128, 255, 0)
    return Image.fromarray(p, 'RGBA')


# ---------------------------------------------------------------- checking / converting one PNG
class Result:
    def __init__(self, target):
        self.target = target
        self.msgs = []            # (level, text), level: error / warn / info / ok
        self.final = None         # PIL RGBA image that gets saved to the ready folder / patched
        self.game = None          # PIL RGBA image as the game will show it
        self.needs_quant = None   # (label, cand image, compressed length) when a colour reduction is required
        self.comp_len = None
        self.stream_over = 0      # bytes by which this entry ALONE would exceed the OPENING.GRC limit

    def add(self, level, text):
        self.msgs.append((level, text))

    @property
    def errors(self):
        return [t for lv, t in self.msgs if lv == 'error']

    @property
    def ok(self):
        return self.final is not None and not self.errors and self.needs_quant is None


def opening_info(iso_path):
    """(stream, cont, offs, size limit in bytes) of OPENING.GRC of an ISO, cached."""
    key = os.path.normcase(os.path.abspath(iso_path))
    if key not in _OPENING_CACHE:
        iso = G.Iso(iso_path)
        lba, size, stream, cont = iso.load_opening()
        iso.f.close()
        cnt, offs = G.container_entries(cont)
        _OPENING_CACHE[key] = (stream, cont, offs, (size + 2047) // 2048 * 2048)
    return _OPENING_CACHE[key]


def opening_stream_len(iso_path, entry, comp, slot_len):
    """Real size of OPENING.GRC if this entry (alone) were replaced: (length, limit)."""
    stream, cont, offs, limit = opening_info(iso_path)
    new_cont = cont[:offs[entry]] + comp + b'\x00' * (slot_len - len(comp)) + cont[offs[entry + 1]:]
    return len(G.grc_splice(stream, new_cont, offs[entry], offs[entry + 1])), limit


def opening_combined_len(iso_path, ops):
    """OPENING.GRC size if all (target, Result) entries are patched together: (length, limit)."""
    stream, cont, offs, limit = opening_info(iso_path)
    for t, r in ops:
        n = int(t.key[1:])
        slot = cont[offs[n]:offs[n + 1]]
        tmpl, _ = G.maz_decompress(slot)
        comp = G.maz_compress(G.image_to_entry(r.final, tmpl))
        if len(comp) > len(slot):
            raise SystemExit('%s: %d bytes do not fit the slot of %d bytes' % (t.key, len(comp), len(slot)))
        cont = cont[:offs[n]] + comp + b'\x00' * (len(slot) - len(comp)) + cont[offs[n + 1]:]
        stream = G.grc_splice(stream, cont, offs[n], offs[n + 1])
    return len(stream), limit


def fit_entry(im, template, slot_len, log=None, stream_check=None):
    """Run the colour ladder: returns (image, comp, label) of the first step that fits, or None.
    Fits = compressed entry <= slot and, if stream_check(comp) -> (len, limit) is given, OPENING.GRC <= its sectors."""
    for ncol, binar in [(None, False)] + LADDER:
        cand = im if (ncol is None and not binar) else quantize(im, ncol, binar)
        entry = G.image_to_entry(cand, template)
        comp = G.maz_compress(entry)
        assert G.maz_decompress(comp)[0] == entry
        label = 'unchanged' if (ncol is None and not binar) else '%s colours, 1-bit alpha' % (ncol or 'all')
        ok = len(comp) <= slot_len
        info = ''
        if ok and stream_check:
            slen, limit = stream_check(comp)
            ok = slen <= limit
            info = ', OPENING.GRC %d of %d' % (slen, limit)
        if log:
            log('try %s: %d of %d bytes%s' % (label, len(comp), slot_len, info))
        if ok:
            return cand, comp, label
    return None


def check_png(target, path, fit=False, allow_quant=False, scale=1.0, dx=0, dy=0, log=None, iso_path=None, rot=0,
              variant=None):
    r = Result(target)
    if variant is None and iso_path and os.path.isfile(iso_path):
        variant = G.detect_variant(iso_path)
    variant = variant or 'JP'
    try:
        im0 = Image.open(path)
        im0.load()
    except Exception as e:
        r.add('error', 'cannot read the file as an image: %s' % e)
        return r
    if im0.format != 'PNG':
        r.add('warn', 'file is %s, not PNG (it works, but export as PNG)' % im0.format)
    if im0.mode != 'RGBA':
        r.add('info', 'mode %s will be converted to RGBA (8 bit per channel)' % im0.mode)
    im = im0.convert('RGBA')
    a = np.array(im)[..., 3]
    if not (a > 8).any():
        r.add('error', 'the image is completely transparent')
        return r
    r.add('info', 'size %dx%d, %d colours, file %d KiB' % (im.width, im.height, count_colors(im),
                                                         (os.path.getsize(path) + 1023) // 1024))

    if target.kind == 'attract':
        if im.size == T.ATTRACT_SIZE:
            canvas = np.array(im)
            r.add('info', 'already a %dx%d canvas (output of this tool), used as is' % T.ATTRACT_SIZE)
        else:
            bbox = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
            cw, ch = bbox[2] - bbox[0], bbox[3] - bbox[1]
            canvas = G.attract_canvas(im, scale, dx, dy)
            half = min(G.ATTRACT_CENTER_X - G.ATTRACT_CANVAS[0], G.ATTRACT_CANVAS[2] - G.ATTRACT_CENTER_X)
            s = min(2 * half / cw, (G.ATTRACT_CANVAS[3] - G.ATTRACT_CANVAS[1]) / ch) * scale
            r.add('info', 'content %dx%d is cropped to its visible part and scaled x%.2f to %dx%d (max %dx%d)'
                  % (cw, ch, s, cw * s, ch * s, 2 * half, G.ATTRACT_CANVAS[3] - G.ATTRACT_CANVAS[1]))
            if scale > 1.0 and (cw * s > 2 * half + 0.5 or ch * s > G.ATTRACT_CANVAS[3] - G.ATTRACT_CANVAS[1] + 0.5):
                r.add('warn', 'scale %.2f makes the logo larger than the drawable area: it will be cut off' % scale)
        soft = int(((canvas[..., 3] > 0) & (canvas[..., 3] < 128)).sum())
        if soft:
            r.add('info', '%d soft-edge pixels (alpha < 50%%) become transparent: the game has 1-bit alpha' % soft)
        r.final = Image.fromarray(canvas, 'RGBA')
        r.game = attract_game_view(canvas)
        r.add('ok', 'ready: %dx%d canvas' % r.final.size)
        return r

    if target.kind == 'clock':
        import gfx_menu as M
        want = target.size if rot % 180 == 0 else target.size[::-1]     # size the PNG needs so that nothing is scaled
        if im.size == want:
            r.add('info', 'size %dx%d is exactly right for this rotation: nothing is scaled' % want)
        else:
            r.add('warn', 'for a pixel-exact result the PNG should be %dx%d px (width x height) with this rotation; '
                  'it is %dx%d and gets scaled' % (want + im.size))
        if rot:
            im = M.rotate_cw(im, rot)
            r.add('info', 'rotated %d degrees clockwise before inserting (the game shows the frozen clock turned)' % rot)
        final = M.clock_fit(im)
        bbox = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
        soft = int(((np.array(im)[..., 3] > 0) & (np.array(im)[..., 3] < 128)).sum())
        if soft:
            r.add('info', '%d soft-edge pixels (alpha < 50%%) become transparent: the atlas has 1-bit alpha' % soft)
        r.final = final
        r.add('info', 'the preview shows the clock as it appears in the game (the game turns the sprite 90 degrees '
              'counter-clockwise; that is why the default rotation is 90 degrees clockwise)')
        if iso_path and os.path.isfile(iso_path):
            msgs = []
            try:
                iso = G.Iso(iso_path)
                try:
                    plan = M.clock_plan(iso, final, log=msgs.append)
                finally:
                    iso.f.close()
                r.game = M.game_view(M.clock_preview(plan, final))
                for m in msgs:
                    r.add('info', m)
                r.add('ok', 'ready: %d colours, fits all three atlas files' % plan[0][6])
            except SystemExit as e:
                r.add('error', str(e))
        else:
            r.game = M.game_view(final)
            r.add('warn', 'no input ISO set: the colour reduction and the size limit of the atlas files are checked '
                  'when an ISO is set on tab 2 (preview shows the unreduced graphic)')
            r.add('ok', 'ready (not checked against the atlas files)')
        return r

    spec = None
    if target.kind == 'raw':
        spec = raw_spec(target.key, variant)
        if spec is None:
            r.add('error', '%s does not exist on the %s disc (the US disc has only the SNK and ADX start-up logos and '
                  'the unlock pictures)' % (target.key, variant))
            return r
    sizes = raw_sizes(target.key) if spec else [target.size]
    if im.size not in sizes:
        want = spec[1] if spec else target.size
        if not fit:
            r.add('error', 'wrong size: %dx%d, this target needs exactly %s (tick "scale automatically" or '
                  'resize in GIMP)' % (im.width, im.height, ' or '.join('%dx%d' % s for s in sizes)))
            return r
        im = fit_to(im, want)
        r.add('warn', 'scaled to %dx%d (contain, centred, transparent padding)' % want)
    if spec and im.size != spec[1]:
        im = adapt_raw(im, spec[1])
        r.add('info', '%dx%d picture %s to the %dx%d of the %s disc' % (
            im.width, im.height, 'cropped' if spec[1][1] < 512 else 'padded with white rows', spec[1][0], spec[1][1],
            variant))
    im = clean_transparent(im)
    aa = np.array(im)[..., 3]
    partial = int(((aa > 0) & (aa < 255)).sum())
    if target.kind in ('opening', 'coin'):
        if partial:
            r.add('info', '%d semi-transparent pixels (kept as far as the slot allows; soft edges compress badly)'
                  % partial)

    if target.kind == 'raw':
        r.final = im
        r.game = decode_for(encode_for(im, spec), spec)
        if spec[2] == 'RGBA':
            r.add('ok', 'ready: raw RGBA, no size limit')
        else:
            r.add('ok', 'ready: raw %s (%s disc has no alpha channel: transparent areas become black)'
                  % (spec[2], variant))
        return r

    template = synth_template(target)
    stream_check = None
    if target.kind == 'coin':
        pass        # fixed slot inside COIN_IN1/2.BIN, no archive limit
    elif iso_path and os.path.isfile(iso_path):
        n = int(target.key[1:])
        stream_check = lambda comp: opening_stream_len(iso_path, n, comp, target.slot)
    else:
        r.add('warn', 'no input ISO set: only the entry slot (%d bytes) is checked, but OPENING.GRC as a whole has an '
              'even tighter limit. Set the input ISO on tab 2 for the real check.' % target.slot)
    # Strict mode (colour reduction wanted) = the entry alone must fit OPENING.GRC.  Otherwise only the slot decides
    # here: other entries of the same patch may shrink the file, the patch step checks the combination.
    res = fit_entry(im, template, target.slot, log, stream_check if allow_quant else None)
    if res is None:
        r.add('error', 'does not fit even with 8 colours: simplify the artwork (flat fills, no gradients, less '
              'detail)')
        return r
    cand, comp, label = res
    r.comp_len = len(comp)
    if label != 'unchanged':
        if allow_quant:
            im = cand
            r.add('info', 'colour reduction applied: %s (%d colours left, %d of %d slot bytes)'
                  % (label, count_colors(cand), len(comp), target.slot))
        else:
            r.add('warn', 'too big for its slot (%d bytes): needs a colour reduction to %s (%d colours left, '
                  '%d of %d entry bytes)' % (target.slot, label, count_colors(cand), len(comp), target.slot))
            r.needs_quant = (label, cand, len(comp))
    if stream_check and r.needs_quant is None:
        slen, limit = stream_check(comp)
        if slen > limit:
            r.stream_over = slen - limit
            r.add('warn', 'alone this entry would make OPENING.GRC %d bytes too big. That is fine if other entries '
                  'in the same patch shrink the file (the patch step checks the combination before copying); '
                  'otherwise use "Reduce colours".' % r.stream_over)
        else:
            r.add('ok', 'fits, also in OPENING.GRC alone: %d of %d entry bytes' % (len(comp), target.slot))
    elif label == 'unchanged':
        r.add('ok', 'fits its slot: %d of %d entry bytes' % (len(comp), target.slot))
    r.final = im if r.needs_quant is None else cand
    r.game = G.entry_to_image(G.image_to_entry(r.final, template))
    return r


# ---------------------------------------------------------------- originals straight from the ISO
def extract_original(iso_path, target, variant=None):
    """The original graphic of a target, decoded from the user's ISO (no dumped files needed).  Returns an RGBA PIL
    image, or None when this disc has no such graphic.  Orientation and size = what a replacement PNG should be."""
    iso = G.Iso(iso_path)
    try:
        variant = variant or iso.variant() or 'JP'
        kind = target.kind
        if kind == 'raw':
            spec = raw_spec(target.key, variant)
            if spec is None:
                return None
            lba, size = iso.find(spec[0])
            return decode_for(iso.read(lba, size), spec)
        if kind == 'opening':
            _, cont, offs, _ = opening_info(iso_path)          # cached: decoding OPENING.GRC takes ~0.4 s
            n = int(target.key[1:])
            d, _ = G.maz_decompress(cont[offs[n]:offs[n + 1]])
            return G.entry_to_image(d)
        if kind == 'coin':
            lba, size = iso.find(T.COIN_PATHS[0])
            data = iso.read(lba, size)
            cnt, offs = G.container_entries(data)
            n = T.COIN_ENTRIES[target.key]
            d, _ = G.maz_decompress(data[offs[n]:offs[n + 1]])
            return G.entry_to_image(d)
        if kind == 'attract':
            # the whole original logo (it is wider than the area a new logo is fitted into: the two left spikes)
            data, base = G.hud_atlas(iso)
            P = G.ATTRACT_PIECES
            cx0, cy0 = min(p[3] + p[6] for p in P), min(p[1] + p[5] for p in P)
            cx1, cy1 = max(p[4] + p[6] for p in P), max(p[2] + p[5] for p in P)
            out = np.zeros((cy1 - cy0, cx1 - cx0, 4), np.uint8)
            for name, y0, y1, x0, x1, dy, dx in P:
                for y in range(y0, y1):
                    row = np.frombuffer(data, '<u2', x1 - x0, base + (y * 256 + x0) * 2)
                    sy = y + dy - cy0
                    for i, v in enumerate(row):
                        sx = x0 + i + dx - cx0
                        if any(a <= y < b and c <= x0 + i < d for a, b, c, d in G.ATTRACT_KEEP):
                            continue         # QUICK bar texels, not part of the logo
                        # the rectangles are generous and overlap: the first piece (A, with the text line) wins
                        if v & 0x8000 and not out[sy, sx, 3]:
                            out[sy, sx] = ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31,
                                           ((v >> 10) & 31) * 255 // 31, 255)
            return Image.fromarray(out, 'RGBA')
        if kind == 'clock':
            import gfx_menu as M
            lba, sectors, stream, d = M._load(iso, M.CLOCK_FILES[0])
            pal = [tuple(d[4 * M.swz(i):4 * M.swz(i) + 4]) for i in range(256)]
            x0, y0, x1, y1 = M.CLOCK_RECT
            px = np.frombuffer(d[0x400:0x400 + 256 * M.PAGE_ROWS], np.uint8).reshape(M.PAGE_ROWS, 256)[y0:y1, x0:x1]
            lut = np.array([(r, g, b, 255 if a else 0) for r, g, b, a in pal], np.uint8)
            return M.game_view(Image.fromarray(lut[px], 'RGBA'))
        return None
    finally:
        iso.f.close()


# ---------------------------------------------------------------- folder scan
def scan_folder(folder):
    """-> list of (key, path) for every file whose name starts with a known key; later files of a key win."""
    by_key = {}
    dup = []
    for fn in sorted(os.listdir(folder)):
        p = os.path.join(folder, fn)
        if not os.path.isfile(p) or not fn.lower().endswith('.png'):
            continue
        k = T.match_name(fn)
        if k:
            if k in by_key:
                dup.append((k, by_key[k], p))
            by_key[k] = p
    return sorted(by_key.items()), dup


# ---------------------------------------------------------------- patching
def copy_iso(src, dst, progress=None):
    total = os.path.getsize(src)
    done = 0
    with open(src, 'rb') as a, open(dst, 'wb') as b:
        while True:
            buf = a.read(16 << 20)
            if not buf:
                break
            b.write(buf)
            done += len(buf)
            if progress:
                progress(done, total)


def apply_jobs(src, dst, jobs, fit=False, allow_quant=False, force=False, log=print, progress=None,
               scale=1.0, dx=0, dy=0, hacks=(), ui_color=None, hide_anim=False, black_bg=False, frame_color=None,
               margin_color=None, clock_rot=0, font_orange=None, font_teal=None, palettes=None):
    """jobs: [(key, png path)], hacks: keys from gfx_hacks.hack_list(), palettes: {char id: .PAL path}.  Validates
    everything first, copies src -> dst, patches, verifies."""
    cat = T.by_key()
    hacks = list(hacks)
    variant = G.detect_variant(src)
    if variant is None:
        raise SystemExit('%s is neither the JP (SLPS-25660) nor the US (SLUS-21687) disc' % src)
    log('disc: %s version' % variant)
    if hacks:
        import gfx_hacks
        known = {k for k, _, _ in gfx_hacks.hack_list(variant)}
        unknown = [h for h in hacks if h not in known]
        if unknown:
            raise SystemExit('hack(s) not available for the %s disc: %s (available: %s)'
                             % (variant, ', '.join(unknown), ', '.join(sorted(known)) or 'none'))
    log('checking %d file(s) ...' % len(jobs))
    checked = []
    bad = False
    for key, path in jobs:
        t = cat[key.upper()]
        r = check_png(t, path, fit, allow_quant, scale, dx, dy, iso_path=src, rot=clock_rot if t.kind == 'clock' else 0,
                      variant=variant)
        for lv, msg in r.msgs:
            if lv in ('error', 'warn'):
                log('  %s [%s] %s' % (lv.upper(), key, msg))
        if not r.ok:
            bad = True
            log('  -> %s cannot be patched as it is%s' % (key, ' (needs colour reduction: convert it first)'
                                                           if r.needs_quant else ''))
        checked.append((t, path, r))
    pal_data = {}
    if palettes:
        import gfx_palettes
        psrc = gfx_palettes.Source(src)
        for cid, path in sorted(palettes.items()):
            try:
                data = gfx_palettes.load_file(path, psrc.pals[cid])
            except (SystemExit, OSError) as e:
                log('  ERROR [palette %s] %s' % (gfx_palettes.CHAR_NAMES.get(cid, cid), e))
                bad = True
                continue
            if data != psrc.pals[cid]:
                pal_data[cid] = data
        log('character palettes: %s' % (', '.join(gfx_palettes.CHAR_NAMES[c] for c in sorted(pal_data)) or
                                        'none differ from the disc'))
    if bad:
        raise SystemExit('aborted: fix the files above first (nothing was copied or written)')
    ops_pre = [(t, r) for t, p, r in checked if t.kind == 'opening']
    if ops_pre:
        slen, limit = opening_combined_len(src, ops_pre)
        log('OPENING.GRC with %s: %d of %d bytes' % (', '.join(t.key for t, _ in ops_pre), slen, limit))
        if slen > limit:
            raise SystemExit('aborted before copying: OPENING.GRC would be %d bytes, %d over its limit of %d. Reduce '
                             'colours / detail of the big entries (%s) or patch fewer entries.'
                             % (slen, slen - limit, limit, ', '.join(t.key for t, _ in ops_pre)))
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if os.path.normcase(src) == os.path.normcase(dst):
        raise SystemExit('input and output ISO must differ: the input ISO is never modified')
    if os.path.exists(dst) and not force:
        raise SystemExit('%s already exists' % dst)
    created = True
    try:
        log('copying ISO (about %.1f GB) ...' % (os.path.getsize(src) / 1e9))
        copy_iso(src, dst, progress)
        iso = G.Iso(dst, write=True)
        raws = [(t, r) for t, p, r in checked if t.kind == 'raw']
        ops = [(t, r) for t, p, r in checked if t.kind == 'opening']
        att = [(t, r) for t, p, r in checked if t.kind == 'attract']
        clk = [(t, r) for t, p, r in checked if t.kind == 'clock']
        coins = [(t, r) for t, p, r in checked if t.kind == 'coin']
        for t, r in raws:
            spec = raw_spec(t.key, variant)
            lba, size = iso.find(spec[0])
            data = encode_for(r.final, spec)
            if size < len(data):
                raise SystemExit('%s on this ISO is smaller than expected: wrong disc?' % spec[0])
            iso.f.seek(lba * 2048)
            iso.f.write(data)
            log('%s (%s): written at LBA %d' % (t.key, spec[0], lba))
        iso.f.flush()
        if ops:
            patch_opening(iso, ops, log)
        logo = next((r for t, r in ops if t.key == 'e116'), None)
        if coins or logo is not None:
            patch_coin(iso, coins, logo, log)
        iso.f.close()
        for t, r in att:
            G.replace_attract_canvas(dst, np.array(r.final))
            log('attract: FIGHT.BCC and FIGHTA.BCC patched')
        if pal_data:
            import gfx_palettes
            gfx_palettes.patch_palettes(dst, pal_data, log)
        verify(dst, raws, ops, log, variant)
        if hacks:
            import gfx_hacks
            gfx_hacks.apply_hacks(dst, hacks, log)
        if ui_color or hide_anim or black_bg or frame_color or margin_color or font_orange or font_teal or clk:
            import gfx_menu
            if ui_color:                       # first: the clock graphic must not be recoloured
                gfx_menu.recolor(dst, ui_color, log)
            if hide_anim:
                gfx_menu.hide_animations(dst, log)
            if black_bg:
                gfx_menu.black_background(dst, log)
            if font_orange or font_teal:
                gfx_menu.font_colors(dst, {'orange': font_orange, 'teal': font_teal}, log)
            if font_orange or ui_color:      # memory card / network dialogs: orange font + window border
                gfx_menu.dialog_colors(dst, font_orange, ui_color, log)
            if margin_color:
                gfx_menu.margin_color(dst, margin_color, log)
            if frame_color:
                gfx_menu.recolor_frame(dst, frame_color, log)
            for t, r in clk:
                gfx_menu.replace_clock(dst, r.final, log)
    except BaseException:
        if created and os.path.exists(dst):
            try:
                os.remove(dst)
                log('error: the unfinished output ISO was deleted')
            except OSError:
                pass
        raise
    log('DONE: %s' % dst)


def patch_coin(iso, coins, logo, log):
    """The title screen after the intro video was skipped is loaded from DATA/DEMO/COIN_IN1.BIN and COIN_IN2.BIN (plain
    containers: entry 1 orange burst, entry 2 pink burst, entry 3 = the same title logo as OPENING.GRC e116).  The new
    e116 logo goes into entry 3 of both files automatically, coinA / coinB replace the two backgrounds."""
    jobs = {T.COIN_ENTRIES[t.key]: r.final for t, r in coins}
    if logo is not None:
        jobs[3] = logo.final
    for path in T.COIN_PATHS:
        lba, size = iso.find(path)
        sectors = (size + 2047) // 2048
        raw = bytearray(iso.read(lba, sectors * 2048))
        data = bytes(raw[:size])
        cnt, offs = G.container_entries(data)
        if cnt != 4:
            raise SystemExit('%s has %d entries, expected 3: wrong disc?' % (path, cnt - 1))
        expect = {}
        for n, img in sorted(jobs.items()):
            slot = data[offs[n]:offs[n + 1]]
            template, _ = G.maz_decompress(slot)
            entry = G.image_to_entry(img, template)
            comp = G.maz_compress(entry)
            if len(comp) > len(slot):
                raise SystemExit('%s entry %d: %d bytes do not fit the slot of %d bytes (simplify the graphic or reduce '
                                 'its colours)' % (path, n, len(comp), len(slot)))
            raw[offs[n]:offs[n] + len(slot)] = comp + bytes(len(slot) - len(comp))
            expect[n] = entry
            log('%s entry %d: %d of %d slot bytes' % (os.path.basename(path), n, len(comp), len(slot)))
        iso.f.seek(lba * 2048)
        iso.f.write(bytes(raw))
        iso.f.flush()
        back = iso.read(lba, size)
        bc, bo = G.container_entries(back)
        for n, entry in expect.items():
            if G.maz_decompress(back[bo[n]:bo[n + 1]])[0] != entry:
                raise SystemExit('verification of %s entry %d failed' % (path, n))
    log('COIN_IN1/2.BIN (title screen after skipping the intro): %s patched and verified'
        % ', '.join('entry %d' % n for n in sorted(jobs)))


def patch_opening(iso, ops, log):
    lba, size, stream, cont = iso.load_opening()
    cnt, offs = G.container_entries(cont)
    for t, r in ops:
        n = int(t.key[1:])
        slot = cont[offs[n]:offs[n + 1]]
        template, _ = G.maz_decompress(slot)
        hd = G.entry_header(template)
        if (hd['cols'] * hd['w'], hd['rows'] * hd['h']) != t.size:
            raise SystemExit('%s: entry has another size on this ISO: wrong disc?' % t.key)
        comp = G.maz_compress(G.image_to_entry(r.final, template))
        if len(comp) > len(slot):
            raise SystemExit('%s: %d bytes do not fit the slot of %d bytes' % (t.key, len(comp), len(slot)))
        new_cont = cont[:offs[n]] + comp + b'\x00' * (len(slot) - len(comp)) + cont[offs[n + 1]:]
        stream = G.grc_splice(stream, new_cont, offs[n], offs[n + 1])
        cont = new_cont
        log('%s: %d of %d slot bytes' % (t.key, len(comp), len(slot)))
    chk, _ = G.grc_decompress(stream)
    assert chk == cont, 'GRC splice verification failed'
    sectors = (size + 2047) // 2048
    if len(stream) > sectors * 2048:
        raise SystemExit('OPENING.GRC would be %d bytes but only %d fit its sectors: use fewer / simpler entries'
                         % (len(stream), sectors * 2048))
    iso.f.seek(lba * 2048)
    iso.f.write(stream + b'\x00' * (sectors * 2048 - len(stream)))
    iso.f.flush()
    log('OPENING.GRC: %d of %d bytes (%d bytes reserve)' % (len(stream), sectors * 2048,
                                                           sectors * 2048 - len(stream)))


def verify(dst, raws, ops, log, variant='JP'):
    iso = G.Iso(dst)
    for t, r in raws:
        spec = raw_spec(t.key, variant)
        lba, _ = iso.find(spec[0])
        data = encode_for(r.final, spec)
        if iso.read(lba, len(data)) != data:
            raise SystemExit('verification failed for ' + t.key)
    if ops:
        _, _, _, cont = iso.load_opening()
        cnt, offs = G.container_entries(cont)
        for t, r in ops:
            n = int(t.key[1:])
            d, _ = G.maz_decompress(cont[offs[n]:offs[n + 1]])
            want = G.image_to_entry(r.final, d)
            if d != want:
                raise SystemExit('verification failed for ' + t.key)
    iso.f.close()
    log('verified: every written file was read back from the new ISO and matches')


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('check')
    p.add_argument('png')
    p.add_argument('--target')
    p.add_argument('--iso', help='input ISO: check against the real OPENING.GRC size limit')
    p.add_argument('--fit', action='store_true')
    p.add_argument('--quantize', action='store_true')
    p = sub.add_parser('patch')
    p.add_argument('src')
    p.add_argument('dst')
    p.add_argument('--folder')
    p.add_argument('--only', help='comma separated keys, with --folder')
    p.add_argument('--start', metavar='PNG')
    p.add_argument('--title', metavar='PNG')
    p.add_argument('--attract', metavar='PNG')
    p.add_argument('--clock', metavar='PNG', help='main menu clock sprite')
    p.add_argument('--file', action='append', default=[], metavar='KEY=PNG')
    p.add_argument('--hack', action='append', default=[], metavar='KEY',
                   help='samechars, rematch, unlock, combo, skiplogos, fixps2 (repeatable)')
    p.add_argument('--all-hacks', action='store_true')
    p.add_argument('--ui-color', metavar='RRGGBB', help='main menu UI colour, e.g. cb0608')
    p.add_argument('--font-orange', metavar='RRGGBB', help='orange menu alphabet colour')
    p.add_argument('--font-teal', metavar='RRGGBB', help='turquoise menu alphabet colour')
    p.add_argument('--margin-color', metavar='RRGGBB', help='outer margin of the menu windows, e.g. 3050a0')
    p.add_argument('--clock-rotate', type=int, default=0, metavar='DEG', help='rotate the clock PNG clockwise (0/90/180/270)')
    p.add_argument('--frame-color', metavar='RRGGBB', help='grey window frame of the main menu, e.g. 202020')
    p.add_argument('--black-menu-bg', action='store_true', help='black main menu background')
    p.add_argument('--disable-menu-anim', action='store_true', help='hide the 3D swirl and the rotating KOF XI ring text')
    p.add_argument('--palettes', metavar='DIR', help='folder with character palettes (<id>_<name>.PAL)')
    for q in (p,):
        q.add_argument('--fit', action='store_true')
        q.add_argument('--quantize', action='store_true')
        q.add_argument('--force', action='store_true')
        q.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    cat = T.by_key()
    if a.cmd == 'check':
        key = (a.target or T.match_name(a.png) or '').upper()
        if key.lower() == 'attract':
            key = 'ATTRACT'
        if key not in cat:
            raise SystemExit('unknown target: name the file like e116*.png or give --target KEY')
        r = check_png(cat[key], a.png, a.fit, a.quantize, log=lambda s: print('  ', s), iso_path=a.iso)
        for lv, m in r.msgs:
            print('%-5s %s' % (lv.upper(), m))
        return 0 if r.ok else 1
    jobs = []
    if a.folder:
        found, dup = scan_folder(a.folder)
        only = {x.strip().upper() for x in a.only.split(',')} if a.only else None
        jobs += [(k, p) for k, p in found if only is None or k.upper() in only]
        for k, p1, p2 in dup:
            print('note: several files match %s, using %s' % (k, os.path.basename(p2)))
    for key, png in (('LOGO04', a.start), ('e116', a.title), ('attract', a.attract), ('clock', a.clock)):
        if png:
            jobs.append((key, png))
    for kv in a.file:
        k, _, p = kv.partition('=')
        jobs.append((T.match_name(k) or k, p))
    hacks = list(a.hack)
    if a.all_hacks:
        import gfx_hacks
        hacks = [k for k, _, _ in gfx_hacks.hack_list(G.detect_variant(a.src))]
    ui = None
    if a.ui_color:
        import gfx_menu
        ui = gfx_menu.parse_color(a.ui_color)
        if not ui:
            raise SystemExit('--ui-color needs 6 hex digits, e.g. cb0608')
    fo = ft = None
    if a.font_orange or a.font_teal:
        import gfx_menu
        fo = gfx_menu.parse_color(a.font_orange) if a.font_orange else None
        ft = gfx_menu.parse_color(a.font_teal) if a.font_teal else None
        if (a.font_orange and not fo) or (a.font_teal and not ft):
            raise SystemExit('--font-orange / --font-teal need 6 hex digits')
    mg = None
    if a.margin_color:
        import gfx_menu
        mg = gfx_menu.parse_color(a.margin_color)
        if not mg:
            raise SystemExit('--margin-color needs 6 hex digits, e.g. 3050a0')
    fr = None
    if a.frame_color:
        import gfx_menu
        fr = gfx_menu.parse_color(a.frame_color)
        if not fr:
            raise SystemExit('--frame-color needs 6 hex digits, e.g. 202020')
    pals = None
    if a.palettes:
        import gfx_palettes
        pals = gfx_palettes.scan_folder(a.palettes)
    if not jobs and not pals and not hacks and not ui and not fr and not mg and not fo and not ft and not a.disable_menu_anim and not a.black_menu_bg:
        raise SystemExit('nothing to do')
    if a.dry_run:
        for k, p in jobs:
            r = check_png(cat[k.upper()], p, a.fit, a.quantize, iso_path=a.src)
            print(k, 'OK' if r.ok else 'PROBLEM', '|', '; '.join(t for lv, t in r.msgs if lv in ('error', 'warn')))
        return 0
    apply_jobs(a.src, a.dst, jobs, a.fit, a.quantize, a.force, hacks=hacks, ui_color=ui,
               hide_anim=a.disable_menu_anim, black_bg=a.black_menu_bg, frame_color=fr,
               margin_color=mg, clock_rot=a.clock_rotate, font_orange=fo, font_teal=ft, palettes=pals)
    return 0


if __name__ == '__main__':
    sys.exit(main())
