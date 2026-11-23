r"""Builds gfx_hacks_us.json: game hacks for the US disc (SLUS-21687) as plain byte patches of the ELF.

    python -I make_us_hacks.py "King of Fighters XI, The (USA).iso"

The original bytes are read from the ISO and every patch is checked against the instruction it expects, so a wrong
disc or a wrong address stops the script.  Addresses are EE virtual addresses (ELF segment 0x100000 = file offset
0x100), the same convention as gfx_hacks.json.

Boot flow of the US disc (Ghidra: FUN_001d5090 calls the logo player FUN_0027dde0 first):
  1. SNK Playmore logo (DATA/LOGO/SNK.RAW, 180 frames, Start skips it)
  2. ADX logo (DATA/LOGO/CRI.RAW, 180 frames; SKILL.DAT / SVCTEX.DAT are loaded while it is shown)
  3. memory card overwrite warning popup (new on US), then the memory card load popup, then the intro video
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kofxi_gfx as G

ELF = 'SLUS_216.87'
ELF_BASE, ELF_OFF = 0x100000, 0x100


def jal(target):
    return struct.pack('<I', (3 << 26) | ((target >> 2) & 0x3FFFFFF))


NOP = bytes(4)
SLTI_S0_V0 = lambda imm: struct.pack('<I', (0x0A << 26) | (16 << 21) | (2 << 16) | imm)     # slti $v0,$s0,imm

# skip the ADX logo: no upload, no fade in, no 180 frame wait, no fade out; the SKILL/SVCTEX load (0x27f240) stays
SKIPLOGOS = [
    (0x27DEA8, jal(0x27CF50), NOP),             # FUN_0027cf50(CRI.RAW)  upload the ADX picture
    (0x27DEB0, jal(0x27DB90), NOP),             # FUN_0027db90()         fade in
    (0x27DF00, SLTI_S0_V0(0xB4), SLTI_S0_V0(0)),    # while (s0 < 180)  ->  never
    (0x27DF10, jal(0x27DC20), NOP),             # FUN_0027dc20()         fade out (screen is already black)
]


def main(iso_path, out=os.path.join(HERE, 'gfx_hacks_us.json')):
    iso = G.Iso(iso_path)
    if iso.variant() != 'US':
        raise SystemExit('%s is not the US disc' % iso_path)
    lba, size = iso.find(ELF)
    elf = iso.read(lba, size)
    hacks = []
    patches = []
    for addr, orig, new in SKIPLOGOS:
        o = addr - ELF_BASE + ELF_OFF
        if elf[o:o + 4] != orig:
            raise SystemExit('unexpected bytes at 0x%X: %s (expected %s)' % (addr, elf[o:o + 4].hex(), orig.hex()))
        patches.append({'addr': addr, 'orig': orig.hex(), 'new': new.hex()})
    hacks.append({'key': 'skiplogos', 'label': 'Skip intro logos',
                  'desc': 'Skips the ADX logo; the SNK Playmore logo stays (US start-up: SNK, ADX, memory card '
                          'warning, memory card load, intro video).',
                  'patches': patches})
    data = {'variant': 'US', 'elf': ELF, 'elf_size': size, 'elf_off': ELF_OFF, 'elf_base': ELF_BASE, 'hacks': hacks}
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1)
    print('wrote %s (%d hack(s), ELF %d bytes)' % (out, len(hacks), size))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
