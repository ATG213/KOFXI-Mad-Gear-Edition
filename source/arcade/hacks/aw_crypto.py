#!/usr/bin/env python3
"""Atomiswave ROM board cipher (the program ROM `ax3201p01.fmem1` of a cartridge is stored encrypted).

Port of the public algorithm from MAME (src/mame/machine/awboard.cpp) as it is also found in Flycast
(core/hw/naomi/awcartridge.cpp).  The tables and the structure of the cipher are from there:

    license:BSD-3-Clause
    copyright-holders: Olivier Galibert, Andreas Naive (MAME awboard.cpp)

The 8-bit key (KOF XI: 0xD3) selects a bit permutation (bits 6-7), an S-box set (bits 4-5) and an XOR constant
(bits 0-3).  One 16-bit word is decrypted like this (address = word index, only the low 16 bits matter):

    1. permute the bits of the cipher word,
    2. XOR with a bit-shuffled copy of the word address,
    3. split into 5 / 4 / 4 / 3 bits and run each part through its S-box,
    4. XOR with the constant of the key.

Every step is a bijection, so encryption is the same chain backwards.

Command line:
    python aw_crypto.py decrypt IN OUT [--key 0xD3]
    python aw_crypto.py encrypt IN OUT [--key 0xD3]
"""
import argparse
import array
import sys

PERMUTATIONS = (
    (14, 1, 11, 15, 7, 3, 8, 13, 0, 4, 2, 12, 6, 10, 5, 9),
    (8, 10, 1, 3, 7, 4, 11, 2, 5, 15, 6, 0, 12, 13, 9, 14),
    (4, 5, 9, 6, 1, 13, 7, 11, 10, 0, 14, 12, 8, 15, 2, 3),
    (12, 7, 11, 2, 0, 5, 15, 6, 1, 8, 14, 4, 9, 13, 3, 10),
)

# per set: S0 (5 bit), S1 (4 bit), S2 (4 bit), S3 (3 bit)
SBOXES = (
    ((11, 8, 6, 25, 2, 7, 23, 28, 5, 10, 21, 20, 1, 26, 17, 19, 14, 27, 22, 30, 15, 4, 9, 24, 31, 3, 16, 12, 0, 18, 29, 13),
     (13, 5, 9, 6, 4, 2, 11, 10, 12, 0, 8, 1, 3, 14, 15, 7),
     (1, 13, 11, 3, 8, 7, 9, 10, 12, 15, 4, 14, 0, 5, 6, 2),
     (3, 0, 5, 6, 2, 4, 1, 7)),
    ((9, 15, 28, 7, 13, 24, 2, 23, 21, 1, 22, 16, 18, 8, 17, 31, 27, 6, 30, 12, 4, 20, 5, 19, 0, 25, 3, 29, 10, 14, 11, 26),
     (5, 2, 13, 11, 8, 6, 12, 1, 4, 3, 0, 10, 14, 15, 7, 9),
     (11, 6, 10, 0, 12, 1, 8, 14, 2, 9, 13, 3, 7, 4, 15, 5),
     (1, 5, 6, 2, 4, 7, 3, 0)),
    ((17, 25, 29, 27, 5, 11, 10, 21, 2, 8, 13, 0, 30, 3, 14, 16, 22, 1, 7, 15, 31, 18, 4, 20, 9, 19, 26, 24, 23, 28, 12, 6),
     (15, 3, 2, 11, 7, 14, 6, 12, 1, 13, 0, 8, 9, 4, 10, 5),
     (6, 12, 5, 7, 4, 8, 2, 3, 1, 14, 13, 11, 9, 10, 0, 15),
     (5, 1, 0, 3, 4, 6, 2, 7)),
    ((7, 21, 9, 20, 10, 28, 31, 11, 16, 15, 14, 30, 27, 23, 5, 25, 0, 22, 24, 2, 6, 17, 3, 18, 4, 12, 13, 19, 26, 1, 29, 8),
     (10, 6, 5, 1, 13, 0, 9, 2, 15, 14, 7, 11, 8, 3, 12, 4),
     (8, 6, 15, 13, 2, 7, 1, 3, 11, 0, 14, 10, 4, 5, 12, 9),
     (6, 5, 4, 1, 0, 2, 3, 7)),
)

# index = key & 0xF; 0 where MAME has no value (keys that are not used by any game)
XOR_CONSTANTS = (0x0000, 0x0000, 0x97CF, 0x4BE3, 0x2255, 0x8DD6, 0x0000, 0xC6A2,
                 0xA1E8, 0xB3BF, 0x3B1A, 0x547A, 0x0000, 0x935F, 0x0000, 0x0000)

ADDRESS_BITS = (13, 5, 2, 14, 10, 9, 4, 15, 11, 6, 1, 12, 8, 7, 3, 0)


def _bitswap16(value, order):
    out = 0
    for i in range(16):
        out |= ((value >> order[i]) & 1) << (15 - i)
    return out


def _inverse(table):
    inv = [0] * len(table)
    for i, v in enumerate(table):
        inv[v] = i
    return inv


class AWCrypto:
    def __init__(self, key):
        self.key = key & 0xFF
        pbox = PERMUTATIONS[self.key >> 6]
        self.sbox = SBOXES[(self.key >> 4) & 3]
        self.xor = XOR_CONSTANTS[self.key & 0xF]
        text_order = [pbox[15 - i] for i in range(16)]
        inv_pbox = _inverse(pbox)
        inv_text_order = [inv_pbox[15 - i] for i in range(16)]
        self.inv_sbox = tuple(_inverse(s) for s in self.sbox)
        self._fwd = [_bitswap16(v, text_order) for v in range(65536)]
        self._back = [_bitswap16(v, inv_text_order) for v in range(65536)]
        self._addr = [_bitswap16(a, ADDRESS_BITS) for a in range(65536)]

    def decrypt_word(self, cipher, address):
        aux = self._fwd[cipher & 0xFFFF] ^ self._addr[address & 0xFFFF]
        s0, s1, s2, s3 = self.sbox
        return ((s3[aux >> 13] << 13) | (s2[(aux >> 9) & 0xF] << 9) | (s1[(aux >> 5) & 0xF] << 5) | s0[aux & 0x1F]) ^ self.xor

    def encrypt_word(self, plain, address):
        val = (plain & 0xFFFF) ^ self.xor
        i0, i1, i2, i3 = self.inv_sbox
        aux = (i3[val >> 13] << 13) | (i2[(val >> 9) & 0xF] << 9) | (i1[(val >> 5) & 0xF] << 5) | i0[val & 0x1F]
        return self._back[aux ^ self._addr[address & 0xFFFF]]

    def _run(self, data, fn):
        words = array.array('H')
        words.frombytes(bytes(data[:len(data) & ~1]))
        for i, w in enumerate(words):
            words[i] = fn(w, i)
        return words.tobytes()

    def decrypt_buffer(self, data):
        return self._run(data, self.decrypt_word)

    def encrypt_buffer(self, data):
        return self._run(data, self.encrypt_word)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('decrypt', 'encrypt'))
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--key', type=lambda s: int(s, 0), default=0xD3, help='cartridge key (KOF XI: 0xD3)')
    a = ap.parse_args()
    crypto = AWCrypto(a.key)
    data = open(a.src, 'rb').read()
    out = crypto.decrypt_buffer(data) if a.cmd == 'decrypt' else crypto.encrypt_buffer(data)
    open(a.dst, 'wb').write(out)
    print('%s: %d bytes -> %s' % (a.cmd, len(out), a.dst))


if __name__ == '__main__':
    sys.exit(main())
