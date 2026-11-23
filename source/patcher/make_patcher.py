#!/usr/bin/env python3
"""Build the stand-alone "KOF XI Mad Gear Edition" patcher.

Compares the ORIGINAL JP disc (SLPS-25660) with a finished Mad Gear Edition ISO and stores only the
differing byte runs (zlib-compressed, no game data besides what the mod itself changed) in
payload.bin next to madgear_patcher.py.  PyInstaller then bundles both into one exe.

usage: make_patcher.py ORIGINAL.iso MADGEAR.iso [--runs runs.json]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = b'KMGP1\0'


def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('original')
    ap.add_argument('madgear')
    ap.add_argument('--runs', help='precomputed runs.json ([[start,end],...]) to skip the comparison')
    ap.add_argument('--out', default=os.path.join(HERE, 'payload.bin'))
    a = ap.parse_args()

    size = os.path.getsize(a.original)
    if size != os.path.getsize(a.madgear):
        sys.exit('size mismatch: the patcher only supports same-size patches')
    runs = json.load(open(a.runs)) if a.runs else None
    if runs is None:
        sys.exit('pass --runs RUNS.json (create it with isodiff.py first)')

    chunks = []
    with open(a.madgear, 'rb') as f:
        for s, e in runs:
            f.seek(s)
            chunks.append((s, f.read(e - s)))
    body = b''.join(struct.pack('<QI', s, len(d)) + d for s, d in chunks)
    comp = zlib.compress(body, 9)
    print('runs %d, raw %d B, compressed %d B' % (len(chunks), len(body), len(comp)))

    print('hashing original ...')
    md5_orig = md5_file(a.original)
    print('hashing mad gear ...')
    md5_mg = md5_file(a.madgear)
    head = MAGIC + struct.pack('<QI', size, len(chunks)) + bytes.fromhex(md5_orig) + bytes.fromhex(md5_mg)
    with open(a.out, 'wb') as f:
        f.write(head + comp)
    print('wrote', a.out)
    print('original md5', md5_orig)
    print('madgear  md5', md5_mg)


if __name__ == '__main__':
    main()
