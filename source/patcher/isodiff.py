#!/usr/bin/env python3
"""List the byte runs in which two files of the same size differ (step 1 of building the PS2 patcher / PPF).

usage: isodiff.py ORIGINAL.iso MADGEAR.iso OUT_runs.json [--gap 64]

Writes [[start, end], ...] (end exclusive).  Runs that are closer than --gap bytes are merged, so a few unchanged bytes
may be included; that does not change the result, it only keeps the number of runs small.
The output is the input of make_patcher.py (--runs) and make_ppf.py.
"""
import argparse
import json
import os
import sys

CHUNK = 1 << 22


def runs_between(path_a, path_b, gap):
    runs = []
    cur_start = cur_last = None
    with open(path_a, 'rb') as fa, open(path_b, 'rb') as fb:
        base = 0
        while True:
            a = fa.read(CHUNK)
            b = fb.read(CHUNK)
            if not a:
                break
            if a != b:
                for i in range(0, len(a), 512):                 # skip equal 512-byte blocks quickly
                    if a[i:i + 512] == b[i:i + 512]:
                        continue
                    for j in range(i, min(i + 512, len(a))):
                        if a[j] != b[j]:
                            pos = base + j
                            if cur_start is None:
                                cur_start = cur_last = pos
                            elif pos - cur_last <= gap:
                                cur_last = pos
                            else:
                                runs.append([cur_start, cur_last + 1])
                                cur_start = cur_last = pos
            base += len(a)
    if cur_start is not None:
        runs.append([cur_start, cur_last + 1])
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('original')
    ap.add_argument('madgear')
    ap.add_argument('out')
    ap.add_argument('--gap', type=int, default=64)
    a = ap.parse_args()
    if os.path.getsize(a.original) != os.path.getsize(a.madgear):
        sys.exit('size mismatch: only same-size patches are supported')
    runs = runs_between(a.original, a.madgear, a.gap)
    with open(a.out, 'w') as f:
        json.dump(runs, f)
    print('%d runs, %d bytes covered -> %s' % (len(runs), sum(e - s for s, e in runs), a.out))


if __name__ == '__main__':
    main()
