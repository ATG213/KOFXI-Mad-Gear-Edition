r"""Game hacks for the PS2 JP ISO as plain byte patches of the ELF (SLPS_256.60), no assembler needed.

The table gfx_hacks.json is generated from toolkit/make_combo_dmg_ps2.py by
export_hack_patches.py (which verifies that all patches together equal the builder's output).  Every patch carries the
bytes it expects: a patch whose target already holds the new bytes is reported as "already applied", anything else
aborts (wrong disc / other hack in the same place).
"""
import base64
import json
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gfx_targets as T
import kofxi_gfx as G

HACKS_FILES = {'JP': 'gfx_hacks.json', 'US': 'gfx_hacks_us.json'}      # one byte-patch table per disc version
DISC_NAMES = {'JP': 'JP disc (SLPS-25660)', 'US': 'US disc (SLUS-21687)'}


def hacks_path(variant='JP'):
    name = HACKS_FILES[variant]
    return next((p for p in (os.path.join(T.APP_DIR, name), os.path.join(T.BUNDLE_DIR, name)) if os.path.isfile(p)),
                os.path.join(T.HERE, name))


def load_hacks(variant='JP'):
    with open(hacks_path(variant), encoding='utf-8') as f:
        return json.load(f)


def hack_list(variant='JP'):
    """[(key, label, description)] in display order, for one disc version (variant None = JP)."""
    return [(h['key'], h['label'], h['desc']) for h in load_hacks(variant or 'JP')['hacks']]


def all_hack_keys():
    """{key: (label, desc, [variants])} over all disc versions, JP order first."""
    res = {}
    for v in HACKS_FILES:
        for k, label, desc in hack_list(v):
            res.setdefault(k, (label, desc, []))[2].append(v)
    return res


def apply_hacks(iso_path, keys, log=print):
    """Patch the ELF inside iso_path (a COPY, written in place).  Returns {key: 'applied' | 'already applied'}."""
    variant = G.detect_variant(iso_path)
    if variant is None:
        raise SystemExit('%s is neither the JP (SLPS-25660) nor the US (SLUS-21687) disc' % iso_path)
    data = load_hacks(variant)
    keys = set(keys)
    missing = sorted(keys - {h['key'] for h in data['hacks']})
    if missing:
        raise SystemExit('hack(s) not available for the %s: %s' % (DISC_NAMES[variant], ', '.join(missing)))
    while True:                               # hacks that need other hacks (e.g. practice needs combo)
        more = {r for h in data['hacks'] if h['key'] in keys for r in h.get('requires', [])} - keys
        if not more:
            break
        log('hack requirement added: ' + ', '.join(sorted(more)))
        keys |= more
    chosen = [h for h in data['hacks'] if h['key'] in keys]
    iso = G.Iso(iso_path, write=True)
    try:
        lba, size = iso.find(data['elf'])
        if size != data['elf_size']:
            raise SystemExit('%s has %d bytes, expected %d: this is not the clean %s'
                             % (data['elf'], size, data['elf_size'], DISC_NAMES[variant]))
        elf = bytearray(iso.read(lba, size))
        if elf[:4] != bytes([127]) + b'ELF':
            raise SystemExit('%s is not an ELF file' % data['elf'])
        off = lambda v: v - data['elf_base'] + data['elf_off']
        status = {}
        discfiles = {}                        # path -> (lba, size, bytearray): disc files patched by "files" hacks
        for h in chosen:
            for fp in h.get('files', []):
                if fp['path'] not in discfiles:
                    flba, fsize = iso.find(fp['path'])
                    if fsize != fp['size']:
                        raise SystemExit('%s has %d bytes, expected %d: this is not the clean %s'
                                         % (fp['path'], fsize, fp['size'], DISC_NAMES[variant]))
                    discfiles[fp['path']] = (flba, fsize, bytearray(iso.read(flba, fsize)))
        for h in chosen:
            states = []
            for p in h['patches']:
                orig, new = bytes.fromhex(p['orig']), bytes.fromhex(p['new'])
                cur = bytes(elf[off(p['addr']):off(p['addr']) + len(new)])
                if cur == orig:
                    states.append('todo')
                elif cur == new:
                    states.append('done')
                else:
                    raise SystemExit('hack "%s": unexpected bytes at 0x%X (this ISO is not the clean %s, or '
                                     'another change sits there)' % (h['label'], p['addr'], DISC_NAMES[variant]))
            for fp in h.get('files', []):
                buf = discfiles[fp['path']][2]
                for p in fp['patches']:
                    orig, new = bytes.fromhex(p['orig']), bytes.fromhex(p['new'])
                    cur = bytes(buf[p['addr']:p['addr'] + len(new)])
                    if cur == orig:
                        states.append('todo')
                    elif cur == new:
                        states.append('done')
                    else:
                        raise SystemExit('hack "%s": unexpected bytes at 0x%X of %s (this ISO is not the clean %s, or '
                                         'another change sits there)' % (h['label'], p['addr'], fp['path'],
                                                                         DISC_NAMES[variant]))
            if all(s == 'done' for s in states):
                status[h['key']] = 'already applied'
                log('hack "%s": already applied' % h['label'])
                continue
            if any(s == 'done' for s in states):
                raise SystemExit('hack "%s" is only partly applied on this ISO' % h['label'])
            for p in h['patches']:
                new = bytes.fromhex(p['new'])
                elf[off(p['addr']):off(p['addr']) + len(new)] = new
            nfile = 0
            for fp in h.get('files', []):
                for p in fp['patches']:
                    new = bytes.fromhex(p['new'])
                    discfiles[fp['path']][2][p['addr']:p['addr'] + len(new)] = new
                    nfile += 1
            status[h['key']] = 'applied'
            log('hack "%s": applied (%d patches%s)' % (h['label'], len(h['patches']) + nfile,
                                                      ', incl. %d in disc files' % nfile if nfile else ''))
        iso.f.seek(lba * 2048)
        iso.f.write(bytes(elf))
        iso.f.flush()
        # read back
        iso.f.seek(lba * 2048)
        if iso.f.read(size) != bytes(elf):
            raise SystemExit('verification of the patched ELF failed')
        for path, (flba, fsize, buf) in discfiles.items():
            iso.f.seek(flba * 2048)
            iso.f.write(bytes(buf))
            iso.f.flush()
            iso.f.seek(flba * 2048)
            if iso.f.read(fsize) != bytes(buf):
                raise SystemExit('verification of the patched %s failed' % path)
    finally:
        iso.f.close()
    apply_hack_graphics(iso_path, chosen, log)
    return status


def apply_hack_graphics(iso_path, chosen, log=print):
    """Pixel patches of MENU atlases (SPR00/SPR01.GRC) that belong to hacks: new menu rows need label / value words.
    Patches carry the unpacked bytes they expect (zlib + base64); palettes are not touched, so menu colour changes
    stay intact."""
    import gfx_menu as M
    files = {}
    for h in chosen:
        for g in h.get('gfx', []):
            files.setdefault(g['file'], []).append((h, g))
    if not files:
        return
    iso = G.Iso(iso_path, write=True)
    try:
        for path, items in files.items():
            lba, sectors, stream, d = M._load(iso, path)
            nd = bytearray(d)
            for h, g in items:
                orig = zlib.decompress(base64.b64decode(g['orig']))
                new = zlib.decompress(base64.b64decode(g['new']))
                a = g['addr']
                cur = bytes(nd[a:a + len(new)])
                if cur == orig:
                    nd[a:a + len(new)] = new
                elif cur != new:
                    raise SystemExit('hack "%s": unexpected graphic data in %s at 0x%X (this ISO is not the clean '
                                     'JP disc, or the menu graphic was changed)' % (h['label'], path, a))
            if bytes(nd) == d:
                log('hack graphics in %s: already applied' % path)
                continue
            n, lim = M._write_grc(iso, lba, sectors, stream, d, bytes(nd), path, log)
            log('hack graphics written: %s (%d of %d bytes)' % (path, n, lim))
            iso.f.flush()
    finally:
        iso.f.close()
    iso = G.Iso(iso_path)
    try:
        for path in files:
            M._load(iso, path)
    finally:
        iso.f.close()
