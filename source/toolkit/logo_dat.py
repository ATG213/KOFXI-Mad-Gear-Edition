r"""KOF XI PS2 DATA\LOGO\LOGO0x.DAT <-> PNG.

Format (verified on JP ISO): 0x140000 bytes, raw RGBA8888, no header, no compression.
Image = 640x512, stored as 5 x 4 tiles of 128x128 px (0x10000 bytes each), tile index = col + row*5.
Alpha is PS2 style: 0x80 = opaque, 0x00 = transparent.

  python -I logo_dat.py decode LOGO04.DAT out.png
  python -I logo_dat.py encode in.png LOGO04.DAT
"""
import sys, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from PIL import Image
W, H, T = 640, 512, 128

def decode(src, dst):
    d = open(src, 'rb').read()
    assert len(d) == 0x140000
    im = Image.new('RGBA', (W, H))
    for r in range(H // T):
        for c in range(W // T):
            o = (c + r * 5) * 0x10000
            t = Image.frombytes('RGBA', (T, T), d[o:o + 0x10000])
            px = [(R, G, B, min(255, A * 2)) for R, G, B, A in t.getdata()]
            t.putdata(px)
            im.paste(t, (c * T, r * T))
    im.save(dst)

def encode(src, dst):
    im = Image.open(src).convert('RGBA')
    assert im.size == (W, H), 'PNG must be 640x512'
    out = bytearray()
    for r in range(H // T):
        for c in range(W // T):
            t = im.crop((c * T, r * T, c * T + T, r * T + T))
            t.putdata([(R, G, B, (A * 128 + 127) // 255) for R, G, B, A in t.getdata()])
            out += t.tobytes()
    open(dst, 'wb').write(out)

if __name__ == '__main__':
    {'decode': decode, 'encode': encode}[sys.argv[1]](sys.argv[2], sys.argv[3])
