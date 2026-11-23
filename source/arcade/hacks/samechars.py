#!/usr/bin/env python3
"""Allow the same character several times in a team, permanently.

A conditional branch in the character availability check skips the "already in the team" test when a debug flag is set.
The patch turns that branch into an unconditional one (same target), so the test never runs:

    file offset 0x579E4 (0x8C0678E4):  23 8B (bf #0x23)  ->  23 A0 (bra #0x23)

Works on the DECRYPTED program ROM and checks the two original bytes first.
"""
import argparse
import sys
from pathlib import Path

OFFSET = 0x579E4


def apply(dec):
    """Patch the decrypted ROM in place; returns the list of changed file offsets."""
    if dec[OFFSET] != 0x23 or dec[OFFSET + 1] != 0x8B:
        sys.exit('unexpected ROM: at 0x%X expected 23 8B (bf #0x23), found %02X %02X'
                 % (OFFSET, dec[OFFSET], dec[OFFSET + 1]))
    dec[OFFSET + 1] = 0xA0
    return [OFFSET + 1]


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
