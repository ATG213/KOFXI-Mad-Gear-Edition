#!/usr/bin/env python3
"""Unlock all bosses (Shion, Magaki and the time-release characters) at ROM level, independent of the save data.

The routine at 0x8C066646 builds the release mask 0x8C18F09A.  Its `mov #0,r2` (0x8C06665A, file offset 0x5675A)
starts the mask at 0; with 0xFF the five time-release bits and the Shion/Magaki bits are always set.  This single
byte is also what separates the plain KOF XI ROM from the "All Fighters" variants of the Atomiswave ROM sets.

    file offset 0x5675A:  E2 00 (mov #0,r2)  ->  E2 FF

Works on the DECRYPTED program ROM.  Usage as a stand-alone tool:
    python unlock_bosses.py --in ax3201p01.fmem1 --out DIR      (encrypted in, encrypted out; DIR/ is created)
"""
import argparse
import sys
from pathlib import Path

OFFSET = 0x5675A


def apply(dec):
    """Patch the decrypted ROM in place; returns the list of changed file offsets."""
    if dec[OFFSET] != 0x00 or dec[OFFSET + 1] != 0xE2:
        sys.exit('unexpected ROM: at 0x%X expected 00 E2 (mov #0,r2), found %02X %02X'
                 % (OFFSET, dec[OFFSET], dec[OFFSET + 1]))
    dec[OFFSET] = 0xFF
    return [OFFSET]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='src', type=Path, required=True, help='encrypted ax3201p01.fmem1')
    ap.add_argument('--out', type=Path, required=True, help='output folder')
    args = ap.parse_args()
    from aw_crypto import AWCrypto
    crypto = AWCrypto(0xD3)
    dec = bytearray(crypto.decrypt_buffer(args.src.read_bytes()))
    print('changed offsets:', [hex(o) for o in apply(dec)])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'ax3201p01.fmem1').write_bytes(crypto.encrypt_buffer(bytes(dec)))


if __name__ == '__main__':
    main()
