#!/usr/bin/env python3
r"""Export the PS2 hacks of make_combo_dmg_ps2.py as a plain byte-patch table (JSON) for the graphics tool.

The graphics tool (toolkit/gfx_app.py, gfx_hacks.py) applies hacks WITHOUT keystone/capstone from this
table, so the exe stays small.  Every entry carries the original bytes it expects, so a wrong or already patched ELF
is detected.  Re-run this after changing make_combo_dmg_ps2.py:

  python -I export_hack_patches.py "KOFXI JP.iso" gfx_hacks.json

Checks: the union of all exported patches applied to the clean ELF must equal patch_elf(all hacks).
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_combo_dmg_ps2 as M

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base64
import zlib
import kofxi_gfx as G
import practice_labels as PL

REQUIRES = {'practice': ['combo']}


def gfx_patches(iso_path, key):
    """Pixel patches of MENU atlases for a hack: [{'file', 'addr' (offset in the unpacked GRC), 'orig', 'new'}]
    with orig/new zlib+base64 (the app verifies orig before it writes)."""
    iso = G.Iso(iso_path)
    try:
        if key == 'combo':
            jobs = [(PL.GRAPHIC_PATH, PL.graphic_plan(iso))]
        elif key == 'practice':
            jobs = [(PL.PATH, PL.plan(iso, {'AUTO CHARACTER': 'DISPLAY', 'INPUT': 'INPUT'})),
                    ]
            # KEY SETTING words (COMMAND ENEMY, QUICK RESET): practice menu atlas and the OPTIONS button config atlas
            jobs += [(p, PL.enemy_plan(iso, p, pg)) for p, pg in PL.ENEMY_TARGETS]
        else:
            return []
    finally:
        iso.f.close()
    out = []
    for path, (lba, sectors, stream, d, nd) in jobs:
        for s, e in runs(d, nd, gap=64):
            out.append({'file': path, 'addr': s,
                        'orig': base64.b64encode(zlib.compress(d[s:e], 9)).decode(),
                        'new': base64.b64encode(zlib.compress(nd[s:e], 9)).decode()})
    return out

HACKS = [
    ('samechars', 'Same characters', 'Allow the same character several times in a team (palettes load correctly).'),
    ('rematch', 'Quick rematch', 'Arcade Versus victory screen: hold Square = same teams again, hold Cross = '
                                  'order / leader select.'),
    ('unlock', 'Unlock all characters', 'All 14 locked characters available (new saves and loaded saves).'),
    ('combo', 'Combo damage display', 'Shows "NN DMG" (and stun) under the HIT COMBO counter. Adds the row DISPLAY '
                                      '(DAMAGE / STUN / BOTH / OFF) to OPTIONS > GRAPHIC SETTING.'),
    ('practice', 'Better practice mode', 'Practice menu: Display DMG/STUN, Display Inputs, list position & item rework, COUNTER option fix, '
                                         'faster life recovery, quick reset, gauge MAX+SKILL, guard ALL / random guard, 2P can use the menu, '
                                         'Triangle on COMMAND edits the other side, new key binds COMMAND ENEMY & QUICK RESET'),
    ('skiplogos', 'Skip intro logos', 'Skips the start-up logos except the SNK Playmore logo (LOGO04).'),
    ('version', 'Version display', 'Shows "V%s" (the Mad Gear version of this build) in red at the bottom right of the main menu.' % M.MG_VERSION),
]

# Hacks that are not part of make_combo_dmg_ps2.py: (key, label, desc, [(address, original hex, new hex)]).
# clockspin: FUN around 0x3313B8 moves the position counter of the main menu clock pointer (object field +0x10,
# step = field +0xC = +-1 per frame, 16..166 ping-pong) with  addu v0,v1,v0  at 0x331404.  Replacing it with
# addu v0,v1,zero keeps the counter (and so the clock) where it is.
STATIC_HACKS = [
    ('clockspin', 'Main menu clock: no spin', 'The clock in the main menu stays still when the cursor moves.',
     [(0x331404, '21106200', '21106000')]),
]


def runs(a, b, gap=4):
    """Changed byte runs between two equal-length buffers (nearby runs are merged)."""
    out, i, n = [], 0, len(a)
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        j = i
        last = i
        while j < n and (j - last) <= gap:
            if a[j] != b[j]:
                last = j
            j += 1
        out.append((i, last + 1))
        i = last + 1
    return out


def main():
    iso, out = sys.argv[1], sys.argv[2]
    with open(iso, 'rb') as f:
        lba, size = M.find_elf_in_iso(f)
        f.seek(lba * 2048)
        elf = f.read(size)
    off = lambda v: v - M.ELF_BASE + M.ELF_OFF
    nothing = dict(unlock=False, rematch=False, samechars=False, skiplogos=False, version=False, display=False, optdisplay=True)
    base, _ = M.patch_elf(elf, **nothing)        # combo damage display (incl. the options menu row) only
    variants = {
        'samechars': dict(samechars=True),
        'rematch': dict(rematch=True),
        'unlock': dict(unlock=True),
        'skiplogos': dict(skiplogos=True),
        'version': dict(version=True),
        'practice': dict(display=True),
    }
    table = {}
    table['combo'] = (elf, base)
    for k, kw in variants.items():
        args = dict(nothing)
        args.update(kw)
        table[k] = (base, M.patch_elf(elf, **args)[0])
    result = {'elf': 'SLPS_256.60', 'elf_size': size, 'elf_off': M.ELF_OFF, 'elf_base': M.ELF_BASE, 'hacks': []}
    rebuilt = bytearray(elf)
    pending = []
    for key, label, desc in HACKS:
        a, b = table[key]
        patches = []
        for s, e in runs(a, b):
            patches.append({'addr': s - M.ELF_OFF + M.ELF_BASE, 'orig': a[s:e].hex(), 'new': b[s:e].hex()})
            pending.append((key != 'combo', s, e, b[s:e]))
        entry = {'key': key, 'label': label, 'desc': desc, 'patches': patches}
        if key in REQUIRES:
            entry['requires'] = REQUIRES[key]
        gp = gfx_patches(iso, key)
        if gp:
            entry['gfx'] = gp
        result['hacks'].append(entry)
        print('%-10s %2d patch runs, %5d bytes, %d graphic runs' % (key, len(patches),
                                                                      sum(len(p['new']) // 2 for p in patches), len(gp)))
    for _, s, e, data in sorted(pending, key=lambda t: t[0]):   # combo's runs (elf -> base) first, the others (base -> variant) on top
        rebuilt[s:e] = data
    full, _ = M.patch_elf(elf)
    for key, label, desc, plist in STATIC_HACKS:
        patches = []
        for addr, orig, new in plist:
            o = off(addr)
            assert elf[o:o + len(orig) // 2].hex() == orig, 'static hack %s: unexpected original bytes' % key
            patches.append({'addr': addr, 'orig': orig, 'new': new})
        result['hacks'].append({'key': key, 'label': label, 'desc': desc, 'patches': patches})
        print('%-10s %2d patch runs (static)' % (key, len(patches)))
    assert bytes(rebuilt) == full, 'union of exported patches differs from patch_elf(all hacks)'
    if os.path.isfile(out):                  # hacks that patch disc files (not the ELF) are not generated here: keep them
        with open(out, encoding='utf-8') as f:
            result['hacks'] += [h for h in json.load(f)['hacks'] if h.get('files')]
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, indent=1)
    print('verified: all patches together == patch_elf(all); wrote', out)


if __name__ == '__main__':
    main()
