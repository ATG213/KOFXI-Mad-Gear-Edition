#!/usr/bin/env python3
"""Combo damage display ("NN DMG" under the HIT COMBO counter, wrapper v9) for KOF XI Atomiswave.

Changes (only in space that is proven unused, no live instruction is overwritten):
  * code cave   0x8C126000..+0x254     wrapper (built by dmg_wrapper.py)
  * data        0x8C125700..0x8C12577F state / parameters (initial values, written at run time)
  * hook        2 literal pool entries 0x8C0CB468 / 0x8C0CB534: 0x8C0A8B88 (HitCombo task) -> cave

Works on the DECRYPTED program ROM; the other hacks may already be applied (the regions are independent).
    python combo_damage.py --in ax3201p01.fmem1 --out DIR      (encrypted in, encrypted out)
"""
import argparse
import struct
import sys
from pathlib import Path

import dmg_wrapper as W

BASE = 0x8C00FF00                            # file offset = address - BASE
off = lambda a: a - BASE
HOOKS = (0x8C0CB468, 0x8C0CB534)             # literals with 0x8C0A8B88 (task function HitCombo)

# initial values (= the final values tuned in the emulator)
CENTER_P1, CENTER_P2, Y = 61, 570, 238
ADV, SPACE_ADV, HOLD = 13, 9, 10
SUFFIX = bytes([0xBC, 0x83, 0x8C, 0x86, 0, 0, 0, 0])   # " DMG" as name-entry indices | 0x80
DATA_LEN = 0x80


def build_patch(dec):
    """Returns (patched copy of the decrypted ROM, code length)."""
    d = bytearray(dec)
    code, _ = W.build()

    # --- preconditions -------------------------------------------------------------------
    for a in HOOKS:
        v = struct.unpack_from("<I", dec, off(a))[0]
        if v != W.ORIG_FN:
            sys.exit(f"unexpected: literal {a:#x} = {v:#x} (expected {W.ORIG_FN:#x})")
    if dec[off(W.ORIG_FN):off(W.ORIG_FN) + 6].hex() != "862f224f5390":
        sys.exit("unexpected: head of fn_8c0a8b88 does not match")
    for a, n in ((W.CAVE, len(code)), (W.DATA, DATA_LEN)):
        if any(dec[off(a):off(a) + n]):
            sys.exit(f"region {a:#x}..+{n:#x} is not empty")
    lo, hi = 0x8C125340, 0x8C126470
    for i in range(len(dec) - 3):
        v = struct.unpack_from("<I", dec, i)[0]
        if lo <= v < hi:
            sys.exit(f"ROM pointer {BASE + i:#x} -> {v:#x} points into the cave region")
    if W.CAVE + len(code) > 0x8C126460:
        sys.exit("code reaches beyond the zero region")

    # --- write ---------------------------------------------------------------------------
    d[off(W.CAVE):off(W.CAVE) + len(code)] = code
    state = struct.pack("<IIII IIII", 0, 0, CENTER_P1, Y, 0, 0, CENTER_P2, Y)
    d[off(W.DATA):off(W.DATA) + len(state)] = state
    d[off(W.ADVP):off(W.ADVP) + 8] = struct.pack("<II", ADV, SPACE_ADV)
    d[off(W.HOLDLEN):off(W.HOLDLEN) + 4] = struct.pack("<I", HOLD)
    d[off(W.DATA_SUFFIX):off(W.DATA_SUFFIX) + len(SUFFIX)] = SUFFIX
    for a in HOOKS:
        struct.pack_into("<I", d, off(a), W.CAVE)
    return bytes(d), len(code)


def apply(dec):
    """Patch the decrypted ROM in place; returns the list of changed file offsets."""
    patched, _n = build_patch(bytes(dec))
    changed = [i for i in range(len(dec)) if dec[i] != patched[i]]
    dec[:] = patched
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", type=Path, required=True, help="encrypted ax3201p01.fmem1")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    a = ap.parse_args()

    from aw_crypto import AWCrypto
    crypto = AWCrypto(0xD3)
    dec = bytearray(crypto.decrypt_buffer(a.src.read_bytes()))
    diff = apply(dec)
    print(f"changed bytes: {len(diff)} in {BASE + diff[0]:#x}..{BASE + diff[-1]:#x}")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "ax3201p01.fmem1").write_bytes(crypto.encrypt_buffer(bytes(dec)))


if __name__ == "__main__":
    main()
