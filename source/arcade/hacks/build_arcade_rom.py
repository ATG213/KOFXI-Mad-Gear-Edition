#!/usr/bin/env python3
"""Build the Atomiswave Mad Gear Edition program ROM from your own original `ax3201p01.fmem1`.

Steps (all in memory, the input file is never modified):
  1. check that the input is the original KOF XI MAME dump (CRC32 6dbdd71b),
  2. decrypt it (aw_crypto.py, key 0xD3),
  3. apply the hacks: unlock all bosses, same characters, quick rematch (A/B + Start), bilinear filter off,
     combo damage display,
  4. encrypt again and fix the cartridge checksum (aw_checksum.py: sum 0xD3, CRC32 forged back to 6dbdd71b).

    python build_arcade_rom.py ORIGINAL_ax3201p01.fmem1 OUT_ax3201p01.fmem1 [--no-unlock] [--no-samechars]
                               [--no-rematch] [--no-bilinear] [--no-combo]

The result of the full hack set is the file that the released arcade patcher (v1.1) produces; its MD5 is printed.
"""
import argparse
import hashlib
import sys
import zlib
from pathlib import Path

import aw_checksum
import bilinear_off
import combo_damage
import quick_rematch
import samechars
import unlock_bosses
from aw_crypto import AWCrypto

ORIGINAL_CRC32 = 0x6DBDD71B
ORIGINAL_MD5 = '36cde602c9bb8dc7b1e0749d663db8b9'
FULL_SET_MD5 = '52fd5af6cc5cd416016c826175abdba9'      # arcade patcher v1.1, all five hacks

HACKS = (
    ('unlock', 'unlock all bosses', unlock_bosses.apply),
    ('samechars', 'same characters', samechars.apply),
    ('rematch', 'quick rematch', quick_rematch.apply),
    ('bilinear', 'bilinear filter off', bilinear_off.apply),
    ('combo', 'combo damage display', combo_damage.apply),
)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('original', type=Path)
    ap.add_argument('out', type=Path)
    for key, text, _fn in HACKS:
        ap.add_argument('--no-' + key, action='store_true', help='skip: ' + text)
    a = ap.parse_args()

    enc = a.original.read_bytes()
    if zlib.crc32(enc) & 0xFFFFFFFF != ORIGINAL_CRC32:
        sys.exit('This is not the original ax3201p01.fmem1 (CRC32 %08x, expected %08x).'
                 % (zlib.crc32(enc) & 0xFFFFFFFF, ORIGINAL_CRC32))
    if a.out.resolve() == a.original.resolve():
        sys.exit('The output must be a new file.')

    crypto = AWCrypto(0xD3)
    dec = bytearray(crypto.decrypt_buffer(enc))
    skipped = []
    for key, text, fn in HACKS:
        if getattr(a, 'no_' + key):
            skipped.append(key)
            continue
        changed = fn(dec)
        print('applied: %-22s %d bytes changed' % (text, len(changed)))
    out = crypto.encrypt_buffer(bytes(dec))
    assert bytes(crypto.decrypt_buffer(out)) == bytes(dec), 'encryption round trip failed'
    out = aw_checksum.fix_rom(out, forge_crc=ORIGINAL_CRC32, log=lambda s: print('checksum:', s))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(out)

    md5 = hashlib.md5(out).hexdigest()
    print('written %s' % a.out)
    print('CRC32 %08x  MD5 %s  SHA1 %s' % (zlib.crc32(out) & 0xFFFFFFFF, md5, hashlib.sha1(out).hexdigest()))
    if not skipped:
        print('matches the released patcher v1.1 output' if md5 == FULL_SET_MD5 else
              'NOTE: differs from the released patcher v1.1 output (%s)' % FULL_SET_MD5)


if __name__ == '__main__':
    main()
