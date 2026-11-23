#!/usr/bin/env python3
"""Write a PPF 3.0 patch (plain, no block check, no undo data) from a runs.json and the Mad Gear ISO.

usage: make_ppf.py MADGEAR.iso runs.json OUT.ppf [--apply ORIGINAL.iso OUT.iso]
--apply is a self-test: applies the PPF with an independent reader to a copy of the original.
"""
import json
import struct
import sys


def write_ppf(mg_path, runs, out):
    desc = b'KOF XI Mad Gear Edition (JP SLPS-25660)'.ljust(50, b' ')
    with open(out, 'wb') as o, open(mg_path, 'rb') as f:
        o.write(b'PPF30' + bytes([2]) + desc + bytes([0, 0, 0, 0]))
        for s, e in runs:
            f.seek(s)
            data = f.read(e - s)
            for p in range(0, len(data), 255):
                part = data[p:p + 255]
                o.write(struct.pack('<QB', s + p, len(part)) + part)


def apply_ppf(ppf, src, dst):
    import shutil
    shutil.copyfile(src, dst)
    d = open(ppf, 'rb').read()
    assert d[:5] == b'PPF30' and d[5] == 2
    blockcheck, undo = d[0x39], d[0x3A]
    assert not blockcheck and not undo
    p = 0x3C
    with open(dst, 'r+b') as f:
        while p < len(d):
            off, n = struct.unpack_from('<QB', d, p)
            p += 9
            f.seek(off)
            f.write(d[p:p + n])
            p += n


if __name__ == '__main__':
    mg, runs_path, out = sys.argv[1:4]
    write_ppf(mg, json.load(open(runs_path)), out)
    print('wrote', out)
    if len(sys.argv) >= 7 and sys.argv[4] == '--apply':
        apply_ppf(out, sys.argv[5], sys.argv[6])
        print('applied to', sys.argv[6])
