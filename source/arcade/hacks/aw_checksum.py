#!/usr/bin/env python3
"""Make a patched KOF XI fmem1 acceptable to real Atomiswave hardware / the AW Multi.

Real hardware (the cart's "Romeo" ASIC) sums the *decrypted* program bytes, each with its two nibbles swapped, over
the range given by the header (offset @0x60, size @0x68, KOF XI: 0x100 .. 0x12291F). The 8-bit result must equal the
cart key (KOF XI: 0xD3), otherwise the mask ROMs stay locked and the screen stays black. Emulators do not check.
Verified 2026-11-16: the original sums to 0xD3, every patched build was off, and the Metal Slug 6 "Blood" hack
compensates exactly (header byte 0x130). The rule is described in MAME awboard.cpp.

This tool takes an ENCRYPTED fmem1 (any variant), then
  1. adds one compensation byte inside the checksummed range (default 0x122910, inside a run of zero padding
     0x122904..0x12291F) so the sum is the key again,
  2. optionally rewrites the last 4 bytes (unused padding outside the range) so the CRC32 equals the original MAME
     CRC (6dbdd71b); SHA-1 cannot be forged.

  python aw_checksum.py check IN
  python aw_checksum.py fix IN OUT [--offset 0x122910] [--forge-crc 6dbdd71b]
"""
import argparse
import os
import struct
import sys
import zlib

from aw_crypto import AWCrypto

KEY = 0xD3
DEFAULT_OFFSET = 0x122910


def swp(b):
    return ((b << 4) | (b >> 4)) & 0xFF


def rng(dec):
    start, _load, size = struct.unpack_from("<III", dec, 0x60)
    return start, size


def checksum(dec):
    start, size = rng(dec)
    return sum(swp(b) for b in dec[start:start + size]) & 0xFF


def forge_tail(data, target):
    """Rewrite the last 4 bytes of `data` so that its CRC32 equals `target`."""
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        tab.append(c)
    top = {t >> 24: i for i, t in enumerate(tab)}
    pre = data[:-4]
    reg = zlib.crc32(pre) ^ 0xFFFFFFFF
    cur = target ^ 0xFFFFFFFF
    js = [0] * 4
    for i in (3, 2, 1, 0):
        js[i] = top[cur >> 24]
        cur = ((cur ^ tab[js[i]]) << 8) & 0xFFFFFFFF
    out = []
    for i in range(4):
        out.append((reg & 0xFF) ^ js[i])
        reg = (reg >> 8) ^ tab[js[i]]
    new = pre + bytes(out)
    assert zlib.crc32(new) & 0xFFFFFFFF == target
    return new


def fix_rom(enc, offset=DEFAULT_OFFSET, forge_crc=None, log=print):
    """Return the encrypted ROM with the checksum compensation byte (and optionally a forged CRC32)."""
    crypto = AWCrypto(KEY)
    enc = bytearray(enc)
    dec = bytearray(crypto.decrypt_buffer(bytes(enc)))
    start, size = rng(dec)
    s = checksum(dec)
    if not (start <= offset < start + size):
        sys.exit("offset outside checksummed range")
    old = dec[offset]
    new = swp((swp(old) + KEY - s) & 0xFF)
    dec[offset] = new
    w = offset & ~1
    word = dec[w] | (dec[w + 1] << 8)
    struct.pack_into("<H", enc, w, crypto.encrypt_word(word, w // 2))
    assert checksum(bytearray(crypto.decrypt_buffer(bytes(enc)))) == KEY
    log(f"byte {offset:#x}: {old:#04x} -> {new:#04x}  (sum now {KEY:#04x})")
    if forge_crc is not None:
        enc = bytearray(forge_tail(bytes(enc), forge_crc))
        assert start + size <= len(enc) - 4            # the tail must be outside the checksummed range
        assert checksum(bytearray(crypto.decrypt_buffer(bytes(enc)))) == KEY
    return bytes(enc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "fix"])
    ap.add_argument("rom")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--offset", type=lambda s: int(s, 0), default=DEFAULT_OFFSET)
    ap.add_argument("--forge-crc", help="hex CRC32 to force via the last 4 bytes, e.g. 6dbdd71b")
    a = ap.parse_args()

    enc = open(a.rom, "rb").read()
    dec = bytearray(AWCrypto(KEY).decrypt_buffer(enc))
    start, size = rng(dec)
    s = checksum(dec)
    print(f"range {start:#x}..{start + size - 1:#x}  sum={s:#04x}  key={KEY:#04x}  "
          f"{'OK' if s == KEY else 'MISMATCH'}   crc32={zlib.crc32(enc) & 0xFFFFFFFF:08x}")
    if a.cmd == "check":
        sys.exit(0 if s == KEY else 1)
    if not a.out:
        sys.exit("fix needs OUT")
    out = fix_rom(enc, a.offset, int(a.forge_crc, 16) if a.forge_crc else None)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "wb").write(out)
    print(f"written {a.out}  crc32={zlib.crc32(out) & 0xFFFFFFFF:08x}")


if __name__ == "__main__":
    main()
