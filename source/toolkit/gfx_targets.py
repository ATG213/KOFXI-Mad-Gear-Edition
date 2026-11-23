r"""Catalog of replaceable KOF XI PS2 (JP and US) graphics: names, sizes, slot limits, file-name matching.

The numbers (sizes, maz slot bytes, entry headers) come from the unmodified JP ISO and live in gfx_catalog.json
next to this file, so PNGs can be checked WITHOUT an ISO.  Regenerate with
    python -I gfx_targets.py make-catalog "KOFXI JP.iso"
"""
import json
import os
import re
import sys

TOOL_VERSION = '1.17.1'          # bump on every release (new graphics, new checks)
HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, 'frozen', False))                      # running as the PyInstaller exe
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE     # where config / an updated catalog live
BUNDLE_DIR = getattr(sys, '_MEIPASS', HERE)                       # where the bundled catalog is
# a gfx_catalog.json next to the exe/script wins over the bundled one, so a new catalog can be dropped in
CATALOG_PATH = next((p for p in (os.path.join(APP_DIR, 'gfx_catalog.json'), os.path.join(BUNDLE_DIR, 'gfx_catalog.json'))
                     if os.path.isfile(p)), os.path.join(HERE, 'gfx_catalog.json'))

LOGO_NAMES = {
    'LOGO00': 'KDDI / Multi Matching BB (JP only)', 'LOGO01': 'GameSync SDK (JP only)',
    'LOGO02': 'ACCESS NetFront (JP only)', 'LOGO03': 'ADX (CRI)  [US: CRI.RAW]',
    'LOGO04': 'SNK Playmore (start-up logo)  [US: SNK.RAW]', 'LOGO05': 'KOF 10th Anniversary medal (JP only)',
}
NEW_NAMES = ['Gai Tendo', 'Sho Hayate', 'Adelheid', 'Silber', 'Jazu', 'Shion', 'Magaki', 'Mai Shiranui', 'Robert',
             'Mr. Big', 'Geese', 'Hotaru Futaba', 'Tung Fu Rue', 'EX Kyo',
             'gallery / character text (JP info screen)', 'gallery / ending unlock',
             'all elements unlocked (JP text)']
OPENING_RANGES = [   # (first, last, text) from docs/ps2-graphics-db.md
    (1, 8, 'KOF 94-2001 logo'), (9, 10, 'KOF 2002/2003 logo'), (11, 20, 'white mask / glow of a logo'),
    (21, 21, 'EPISODE XI disc emblem'), (22, 40, 'character emblem / name caption'),
    (41, 49, 'playing card, pattern, effect'), (50, 70, 'character art crop'), (71, 79, 'banner / name caption'),
    (80, 115, 'portrait / flame / hand effect'), (116, 116, 'KOF XI TITLE LOGO'),
    (117, 117, 'KOF XI logo glow / mask'), (118, 118, 'light burst'), (119, 119, 'blank'), (120, 120, 'light burst'),
    (121, 121, 'title burst background (orange)'), (122, 122, 'title burst background (green)'),
]
def _build_opening_desc():
    d = {}
    years = ['KOF 94', 'KOF 95', 'KOF 96', 'KOF 97', 'KOF 98', 'KOF 99', 'KOF 2000', 'KOF 2001', 'KOF 2002', 'KOF 2003']
    for i, y in enumerate(years):
        d[1 + i] = y + ' logo'
        d[11 + i] = y + ' logo, white mask'
    d[22] = 'Ash Crimson: rune on sleeve'
    d[23] = 'Ash Crimson: sleeve'
    d[24] = 'Ash Crimson: artwork (black & white)'
    d[25] = 'Ash Crimson: name'
    d[26] = 'Iori Yagami: crescent'
    d[27] = 'Iori Yagami: artwork (black & white)'
    d[28] = 'Iori Yagami: name'
    for i in range(3):
        d[29 + i] = 'Kyo Kusanagi: solar eclipse (part %d/3)' % (i + 1)
    d[32] = 'Kyo Kusanagi: artwork (black & white)'
    d[33] = 'Kyo Kusanagi: name'
    d[34] = 'Burning circle'
    d[35] = "K': artwork (black & white)"
    d[36] = "K': name"
    d[37] = 'Bird rune emblem'
    d[38] = 'Elisabeth: sleeve'
    d[39] = 'Elisabeth: artwork (black & white)'
    d[40] = 'Oswald: artwork (colored)'
    d[41] = 'Playing card'
    d[42] = 'Diamond pattern background'
    d[43] = 'Momoko: pink'
    d[44] = 'Brown slash'
    d[45] = 'Momoko: silhouette'
    d[46] = 'Terry Bogard: portrait'
    d[47] = 'Ryo Sakazaki: portrait'
    d[48] = 'Blue / red swirl (2 colors)'
    d[49] = 'Blue / red swirl (fullscreen)'
    for e, who in ((50, 'Duck King'), (51, 'B.Jenet'), (52, 'Kensou')):
        d[e] = who + ': artwork'
    for first, who in ((53, 'Duck King'), (56, 'B.Jenet'), (59, 'Kensou'), (62, 'Vanessa'), (65, 'Ramon'), (68, 'Eiji')):
        for i in range(3):
            d[first + i] = '%s: artwork in pieces (part %d/3)' % (who, i + 1)
    d[71], d[72], d[73] = 'Vanessa: artwork', 'Ramon: artwork', 'Eiji Kisaragi: artwork'
    for e, who in ((74, 'Duck King'), (75, 'Eiji Kisaragi'), (76, 'B.Jenet'), (77, 'Kensou'), (78, 'Ramon'), (79, 'Vanessa')):
        d[e] = who + ': name'
    for e, who in ((80, 'Ash Crimson'), (81, 'Kyo Kusanagi'), (82, "K'"), (83, 'Iori Yagami')):
        d[e] = who + ': portrait'
        d[e + 4] = who + ': big artwork'
    for first, who in ((88, 'Ash Crimson'), (95, 'Kyo Kusanagi'), (102, "K'"), (109, 'Iori Yagami')):
        for i in range(7):
            d[first + i] = '%s: burning hand (frame %d/7)' % (who, i + 1)
    return d


OPENING_DESC = _build_opening_desc()     # per entry; entries not listed fall back to OPENING_RANGES

ATTRACT_SIZE = (214, 121)
CLOCK_SIZE = (185, 187)
COIN_PATHS = ('DATA/DEMO/COIN_IN1.BIN', 'DATA/DEMO/COIN_IN2.BIN')   # title screen after the intro video was skipped
COIN_ENTRIES = {'coinA': 1, 'coinB': 2, 'coinLogo': 3}                  # container entry numbers (3 = the e116 logo)
KEY_RE = re.compile(r'^(LOGO0[0-5]|NEW[0-9A-F]{2}|e\d{3}|attract|clock|coin[ab])(?![0-9A-Za-z])', re.I)


class Target:
    def __init__(self, key, kind, desc, size, status, slot=None, header=None, fmt=''):
        self.key, self.kind, self.desc, self.size = key, kind, desc, size
        self.status, self.slot, self.header, self.fmt = status, slot, header, fmt

    @property
    def size_text(self):
        if self.kind == 'attract':
            return 'any (fitted to %dx%d)' % ATTRACT_SIZE
        if self.kind == 'clock':
            return 'best %dx%d (187x185 if rotated 90)' % CLOCK_SIZE
        if self.kind == 'raw' and self.key.startswith('NEW'):
            return '640x512 (JP) or 640x448 (US)'
        return '%dx%d' % self.size


def load_catalog():
    with open(CATALOG_PATH, encoding='utf-8') as f:
        return json.load(f)


def all_targets():
    cat = load_catalog()
    res = [Target('attract', 'attract', 'Attract-mode logo (FIGHT.BCC + FIGHTA.BCC)', None, 'verified'),
           Target('clock', 'clock', 'Main menu clock / target ring (sprite in SPR00-02, rotated by the game)',
                  CLOCK_SIZE, 'verified')]
    for n, d in LOGO_NAMES.items():
        res.append(Target(n, 'raw', d, (640, 512), 'verified', fmt='RGBA8888 (US: RGB24)'))
    for i in range(17):
        k = 'NEW%02X' % i
        d = 'Unlock screen: ' + (NEW_NAMES[i] if i < len(NEW_NAMES) else '(not reviewed)')
        res.append(Target(k, 'raw', d, (640, 512), 'verified', fmt='RGBA8888 (US: BGR24, 640x448)'))
    for k in sorted(cat['opening'], key=int):
        e = cat['opening'][k]
        n = int(k)
        txt = OPENING_DESC.get(n) or next(t for a, b, t in OPENING_RANGES if a <= n <= b)
        res.append(Target('e%03d' % n, 'opening', txt, (e['w'], e['h']), 'verified' if n in (116, 117, 121, 122) else 'experimental',
                          slot=e['slot'], header=bytes.fromhex(e['header']), fmt=e['fmt']))
    for key, n in (('coinA', 1), ('coinB', 2)):
        e = cat.get('coin', {}).get(str(n))
        if e:
            col = 'orange' if n == 1 else 'pink'
            res.append(Target(key, 'coin', 'Title burst background after skipping the intro video (%s, both COIN_IN files)'
                              % col, (e['w'], e['h']), 'experimental', slot=e['slot'],
                              header=bytes.fromhex(e['header']), fmt=e['fmt']))
    return res


def by_key():
    return {t.key.upper(): t for t in all_targets()}


def match_name(filename):
    """File name -> target key (canonical spelling) or None.  'e116_madgear_test.png' -> 'e116'."""
    m = KEY_RE.match(os.path.splitext(os.path.basename(filename))[0])
    if not m:
        return None
    k = m.group(1)
    if k.lower() in ('attract', 'clock'):
        return k.lower()
    if k.lower() in ('coina', 'coinb'):
        return 'coin' + k[-1].upper()
    if k[0] in 'eE':
        return 'e%03d' % int(k[1:])
    return k.upper()


# ---------------------------------------------------------------- catalog generation (needs the ISO)
def make_catalog(iso_path, out=os.path.join(HERE, 'gfx_catalog.json')):
    sys.path.insert(0, HERE)
    import kofxi_gfx as G
    iso = G.Iso(iso_path)
    _, _, _, cont = iso.load_opening()
    cnt, offs = G.container_entries(cont)
    cat = {'note': 'metadata of the unmodified JP ISO (SLPS-25660), generated by gfx_targets.py make-catalog',
           'opening': {}}
    for k in range(1, cnt):
        slot = cont[offs[k]:offs[k + 1]]
        d, _ = G.maz_decompress(slot)
        hd = G.entry_header(d)
        cat['opening'][str(k)] = {'w': hd['cols'] * hd['w'], 'h': hd['rows'] * hd['h'],
                                  'fmt': 'RGBA32' if hd['rgba32'] else 'ARGB1555', 'slot': len(slot),
                                  'header': d[:hd['data']].hex()}
    # COIN_IN1/2.BIN: the title screen after the intro video was skipped (plain container, maz entries)
    lba, size = iso.find(COIN_PATHS[0])
    d = iso.read(lba, size)
    ccnt, coffs = G.container_entries(d)
    cat['coin'] = {}
    for k in range(1, ccnt):
        slot = d[coffs[k]:coffs[k + 1]]
        dd, _ = G.maz_decompress(slot)
        hd = G.entry_header(dd)
        cat['coin'][str(k)] = {'w': hd['cols'] * hd['w'], 'h': hd['rows'] * hd['h'],
                               'fmt': 'RGBA32' if hd['rgba32'] else 'ARGB1555', 'slot': len(slot),
                               'header': dd[:hd['data']].hex()}
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(cat, f, indent=0)
    print('wrote', out, len(cat['opening']), 'entries,', len(cat['coin']), 'coin entries')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'make-catalog':
        make_catalog(sys.argv[2])
    else:
        print(__doc__)
