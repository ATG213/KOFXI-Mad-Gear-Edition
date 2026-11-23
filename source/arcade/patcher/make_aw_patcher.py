#!/usr/bin/env python3
"""Build payload.bin for the KOF XI Mad Gear Edition Atomiswave patcher.

Compares the ORIGINAL ax3201p01.fmem1 (MAME dump, CRC32 6dbdd71b) with the finished hacked one and stores
only the differing byte runs (zlib-compressed). No game data besides what the mod changed.

usage: make_aw_patcher.py ORIGINAL.fmem1 HACKED.fmem1 [--out payload.bin]
"""
import argparse, hashlib, os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = b'KMGA1\0'
GAP = 16  # merge runs closer than this


def runs_of(a, b):
    runs, i, n = [], 0, len(a)
    while i < n:
        if a[i] == b[i]:
            i += 1
            continue
        s = last = i
        while i < n and i - last <= GAP:
            if a[i] != b[i]:
                last = i
            i += 1
        runs.append((s, last + 1))
        i = last + 1
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('original')
    ap.add_argument('hacked')
    ap.add_argument('--out', default=os.path.join(HERE, 'payload.bin'))
    x = ap.parse_args()
    a, b = open(x.original, 'rb').read(), open(x.hacked, 'rb').read()
    if len(a) != len(b):
        sys.exit('size mismatch')
    runs = runs_of(a, b)
    body = b''.join(struct.pack('<QI', s, e - s) + b[s:e] for s, e in runs)
    comp = zlib.compress(body, 9)
    head = (MAGIC + struct.pack('<QI', len(a), len(runs)) +
            bytes.fromhex(hashlib.md5(a).hexdigest()) + bytes.fromhex(hashlib.md5(b).hexdigest()))
    open(x.out, 'wb').write(head + comp)
    print('runs %d, changed %d B, payload %d B' % (len(runs), sum(e - s for s, e in runs), len(head) + len(comp)))
    print('orig md5', hashlib.md5(a).hexdigest(), 'sha1', hashlib.sha1(a).hexdigest())
    print('hack md5', hashlib.md5(b).hexdigest(), 'sha1', hashlib.sha1(b).hexdigest(), 'crc32 %08x' % zlib.crc32(b))


if __name__ == '__main__':
    main()
