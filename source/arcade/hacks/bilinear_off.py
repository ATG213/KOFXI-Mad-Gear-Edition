#!/usr/bin/env python3
"""Switch off bilinear texture filtering in KOF XI Atomiswave (point sampling, sharp pixels).

Three NOPs, the same sites that the Dreamcast port of the game uses.  Each site is an `or` that sets the TSP
FilterMode bits (13-14); with `nop` the FilterMode stays 0.

  file offset 0x000622 (0x8C010522): 4b 20  or r4,r0   global TSP setter (fn_8c010516)
  file offset 0x0A9184 (0x8C0B9084): 1b 20  or r1,r0   fn_8c0b8f4e, bit 0x2000 of ctx+0x494
  file offset 0x0A9208 (0x8C0B9108): 2b 21  or r2,r1   fn_8c0b8f4e, bit 0x4000 of ctx+0x494

file offset = guest address - 0x8C00FF00.  Works on the DECRYPTED program ROM.
"""
import argparse
import sys
from pathlib import Path

NOP = b'\x09\x00'
SITES = (
    (0x000622, b'\x4b\x20', 'or r4,r0 (fn_8c010516, global TSP setter)'),
    (0x0A9184, b'\x1b\x20', 'or r1,r0 (fn_8c0b8f4e, bit 0x2000)'),
    (0x0A9208, b'\x2b\x21', 'or r2,r1 (fn_8c0b8f4e, bit 0x4000)'),
)


def apply(dec):
    """Patch the decrypted ROM in place; returns the list of changed file offsets."""
    for off, orig, what in SITES:
        got = bytes(dec[off:off + 2])
        if got != orig:
            sys.exit('ERROR: file offset 0x%06X expected %s, found %s (%s)' % (off, orig.hex(' '), got.hex(' '), what))
    changed = []
    for off, _orig, _what in SITES:
        dec[off:off + 2] = NOP
        changed += [off, off + 1]
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='src', type=Path, required=True, help='encrypted ax3201p01.fmem1')
    ap.add_argument('--out', type=Path, required=True, help='output folder')
    args = ap.parse_args()
    from aw_crypto import AWCrypto
    crypto = AWCrypto(0xD3)
    dec = bytearray(crypto.decrypt_buffer(args.src.read_bytes()))
    apply(dec)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'ax3201p01.fmem1').write_bytes(crypto.encrypt_buffer(bytes(dec)))


if __name__ == '__main__':
    main()
