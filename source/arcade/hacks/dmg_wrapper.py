#!/usr/bin/env python3
"""SH-4 wrapper for the combo damage display ("NN DMG" under the HIT COMBO counter), with a tiny assembler.

build()  -> (code_bytes, assembler)
Run it as a script to get a Capstone disassembly (needs the `capstone` package).
"""
import struct, sys

OLD_CAVES = (0x8C125400, 0x8C125C00, 0x8C126000, 0x8C126200, 0x8C125E00, 0x8C125800)
CAVE = 0x8C126000          # code (v9, centered)
ADVP = 0x8C125730          # u32: advance per character (game pixels)
SPACEP = 0x8C125734        # u32: advance of the space
HOLDLEN = 0x8C125738       # u32 parameter: hold frames after the combo ends
HOLDBASE = 0x8C125740      # u32 per side: remaining hold frames
NEWTAB = 0x8C131FA4
SUFFIX = DATA_SUFFIX = 0x8C125760   # suffix string (max 31 characters)
DATA = 0x8C125700          # state per side: 16 bytes (start, dmg, x, y)

ORIG_FN = 0x8C0A8B88
DF798   = 0x8C0DF798
CTX     = 0x8C35BE94
GLYPH   = 0x8C12EDCC
TEAM    = 0x8C27CB54


class Asm:
    def __init__(s, base):
        s.base = base; s.items = []; s.labels = {}; s.pool = {}; s.pool_order = []
    def pc(s): return s.base + 2 * len(s.items)
    def op(s, v): s.items.append(("op", v & 0xFFFF))
    def label(s, n): s.labels[n] = s.pc()
    def lit(s, rn, value):               # mov.l @(disp,pc),rn
        if value not in s.pool: s.pool[value] = f"L{len(s.pool)}"; s.pool_order.append(value)
        s.items.append(("lit", rn, s.pool[value]))
    def br(s, kind, target):             # bt/bf/bra
        s.items.append(("br", kind, target))
    def finish(s):
        while s.pc() % 4: s.op(0x0009)
        for v in s.pool_order:
            s.labels[s.pool[v]] = s.pc()
            s.items.append(("word", v)); s.items.append(("word", None))   # 2 halfwords
        out = b""; pc = s.base; skip = 0
        for it in s.items:
            if it[0] == "op": out += struct.pack("<H", it[1])
            elif it[0] == "lit":
                tgt = s.labels[it[2]]; d = (tgt - ((pc & ~3) + 4)) // 4
                assert 0 <= d < 256, ("lit range", it, d)
                out += struct.pack("<H", 0xD000 | (it[1] << 8) | d)
            elif it[0] == "br":
                kind, t = it[1], s.labels[it[2]]
                d = (t - (pc + 4)) // 2
                if kind == "bra":
                    assert -2048 <= d < 2048; out += struct.pack("<H", 0xA000 | (d & 0xFFF))
                else:
                    assert -128 <= d < 128, ("br range", it, d)
                    out += struct.pack("<H", {"bt": 0x8900, "bf": 0x8B00}[kind] | (d & 0xFF))
            elif it[0] == "word":
                if it[1] is not None: out += struct.pack("<I", it[1]); skip = 1
                elif skip: skip = 0; pc += 2; continue
            pc += 2
        return out


# --- opcode helpers ---
def movl_push(rm):  return 0x2F06 | (rm << 4)                  # mov.l Rm,@-r15
def movl_pop(rn):   return 0x60F6 | (rn << 8)                  # mov.l @r15+,Rn
def mov(rm, rn):    return 0x6003 | (rn << 8) | (rm << 4)
def movi(rn, i):    return 0xE000 | (rn << 8) | (i & 0xFF)
def addi(rn, i):    return 0x7000 | (rn << 8) | (i & 0xFF)
def add(rm, rn):    return 0x300C | (rn << 8) | (rm << 4)
def sub(rm, rn):    return 0x3008 | (rn << 8) | (rm << 4)
def movl_ld(rm, rn): return 0x6002 | (rn << 8) | (rm << 4)      # mov.l @Rm,Rn
def movl_st(rm, rn): return 0x2002 | (rn << 8) | (rm << 4)      # mov.l Rm,@Rn
def movb_ld(rm, rn): return 0x6000 | (rn << 8) | (rm << 4)
def movb_st(rm, rn): return 0x2000 | (rn << 8) | (rm << 4)
def movl_ld_d(rm, d, rn): return 0x5000 | (rn << 8) | (rm << 4) | (d // 4)     # @(disp,Rm)
def movl_st_d(rn, d, rm): return 0x1000 | (rn << 8) | (rm << 4) | (d // 4)     # Rm,@(disp,Rn)
def movb_ld_r0(rm, rn): return 0x000C | (rn << 8) | (rm << 4)   # mov.b @(R0,Rm),Rn
def movw_ld_r0(rm, rn): return 0x000D | (rn << 8) | (rm << 4)   # mov.w @(R0,Rm),Rn
def extub(rm, rn):  return 0x600C | (rn << 8) | (rm << 4)
def extuw(rm, rn):  return 0x600D | (rn << 8) | (rm << 4)
def jsr(rm):        return 0x400B | (rm << 8)
def tst(rm, rn):    return 0x2008 | (rn << 8) | (rm << 4)
def cmpge(rm, rn):  return 0x3003 | (rn << 8) | (rm << 4)       # T = Rn >= Rm (signed)
def cmppl(rn):      return 0x4015 | (rn << 8)
def shll(rn):       return 0x4000 | (rn << 8)
def shll2(rn):      return 0x4008 | (rn << 8)
def mull(rm, rn):   return 0x0007 | (rn << 8) | (rm << 4)
def sts_macl(rn):   return 0x001A | (rn << 8)
def lds_fpul(rm):   return 0x405A | (rm << 8)
def float_fpul(n):  return 0xF02D | (n << 8)
def fsts(n):        return 0xF00D | (n << 8)                    # fsts FPUL,FRn
NOP, RTS = 0x0009, 0x000B
STS_PR_PUSH, LDS_PR_POP = 0x4F22, 0x4F26


def ldholdptr(a, rn):
    """rn = HOLDBASE + side*4 (r8 = side); clobbers r0"""
    a.lit(rn, HOLDBASE); a.op(mov(8, 0)); a.op(shll2(0)); a.op(add(0, rn))


def emit_digit(a, reg, tag):
    """r0 = 0x80 | name-entry index of the digit in reg (0 -> 35, d -> 25+d)"""
    a.op(mov(reg, 0)); a.op(tst(0, 0)); a.br("bf", "nz" + tag); a.op(NOP)
    a.op(movi(0, 10))
    a.label("nz" + tag)
    a.op(addi(0, 25)); a.op(0xCB80)                           # or #0x80,r0


def build():
    a = Asm(CAVE)
    # Prolog
    a.op(STS_PR_PUSH)
    for r in (8, 9, 10, 11, 12, 13, 14): a.op(movl_push(r))
    a.op(movl_push(4))
    a.lit(0, ORIG_FN); a.op(jsr(0)); a.op(NOP)           # call the original (r4 = task)
    a.op(movl_pop(4))
    # side = @(16,task)->byte0
    a.op(movl_ld_d(4, 16, 1))
    a.op(movb_ld(1, 8)); a.op(extub(8, 8))
    # r9 = attacker team, r10 = victim team
    a.lit(0, 0x1F8)
    a.op(mull(8, 0)); a.op(sts_macl(2))
    a.lit(9, TEAM); a.op(add(2, 9))
    a.op(movi(3, 1)); a.op(sub(8, 3))
    a.op(mull(3, 0)); a.op(sts_macl(2))
    a.lit(10, TEAM); a.op(add(2, 10))
    # r11 = state ptr = DATA + side*16
    a.lit(11, DATA)
    a.op(mov(8, 2)); a.op(shll2(2)); a.op(shll2(2)); a.op(add(2, 11))
    # r1 = counter
    a.op(movi(0, 0x57)); a.op(movb_ld_r0(9, 0)); a.op(extub(0, 1))
    # r2 = HP sum of victim slots
    a.op(movi(2, 0))
    a.lit(0, 0x150); a.op(mov(10, 3)); a.op(add(0, 3))
    a.op(movi(4, 127))
    for i in range(3):
        a.op(movi(0, 4)); a.op(movw_ld_r0(3, 0)); a.op(extuw(0, 0))
        a.op(0x3007 | (0 << 8) | (4 << 4)); a.br("bf", f"hpok{i}"); a.op(NOP)   # cmp/gt r4,r0: HP > 127 (0xFFFF = defeated)
        a.op(movi(0, 0))
        a.label(f"hpok{i}")
        a.op(add(0, 2)); a.op(addi(3, 32))
    # if counter==0: start=sum, done
    a.op(tst(1, 1)); a.br("bf", "active"); a.op(NOP)
    # counter == 0: start = sum; maybe still show the hold frames
    a.op(movl_st(2, 11))
    ldholdptr(a, 5)
    a.op(movl_ld(5, 3)); a.op(tst(3, 3)); a.br("bf", "holding"); a.op(NOP)
    a.br("bra", "end"); a.op(NOP)
    a.label("holding")
    a.op(addi(3, -1)); a.op(movl_st(3, 5))
    a.op(movl_ld_d(11, 4, 3))                               # r3 = stored dmg
    a.br("bra", "show"); a.op(NOP)
    a.label("active")
    a.op(movl_ld(11, 3)); a.op(sub(2, 3))                   # r3 = start - sum
    a.op(cmppl(3)); a.br("bt", "pos"); a.op(NOP)
    a.op(movi(3, 0))
    a.label("pos")
    a.op(movl_st_d(11, 4, 3))                               # store dmg
    a.op(movi(0, 2)); a.op(cmpge(0, 1)); a.br("bt", "arm"); a.op(NOP)   # only draw from counter >= 2
    # counter == 1 (a new hit is running): discard the remaining hold time, otherwise the value of a
    # single hit flashes up once more after the next counter reset (wake-up bug)
    ldholdptr(a, 5)
    a.op(movi(0, 0)); a.op(movl_st(0, 5))
    a.br("bra", "end"); a.op(NOP)
    a.label("arm")
    ldholdptr(a, 5)
    a.lit(0, HOLDLEN); a.op(movl_ld(0, 0)); a.op(movl_st(0, 5))   # hold = parameter
    a.label("show")
    # character buffer (16 bytes) on the stack
    a.op(addi(15, -48)); a.op(mov(15, 14))                  # r14 = buf (write/read pointer)
    # Ziffern: r4=hundreds, r6=tens, r3=ones
    a.op(movi(4, 0)); a.op(movi(5, 100))
    a.label("h"); a.op(cmpge(5, 3)); a.br("bf", "hd"); a.op(NOP)
    a.op(sub(5, 3)); a.op(addi(4, 1)); a.br("bra", "h"); a.op(NOP)
    a.label("hd")
    a.op(movi(6, 0)); a.op(movi(5, 10))
    a.label("t"); a.op(cmpge(5, 3)); a.br("bf", "td"); a.op(NOP)
    a.op(sub(5, 3)); a.op(addi(6, 1)); a.br("bra", "t"); a.op(NOP)
    a.label("td")
    # r12 = leading flag; r7 = write ptr
    a.op(movi(12, 0)); a.op(mov(14, 7))
    a.op(tst(4, 4)); a.br("bt", "skh"); a.op(NOP)
    emit_digit(a, 4, 'h'); a.op(movb_st(0, 7)); a.op(addi(7, 1)); a.op(movi(12, 1))
    a.label("skh")
    a.op(tst(6, 6)); a.br("bf", "dot"); a.op(NOP)
    a.op(tst(12, 12)); a.br("bt", "skt"); a.op(NOP)
    a.label("dot")
    emit_digit(a, 6, 't'); a.op(movb_st(0, 7)); a.op(addi(7, 1))
    a.label("skt")
    emit_digit(a, 3, 'o'); a.op(movb_st(0, 7)); a.op(addi(7, 1))
    a.lit(2, DATA_SUFFIX)                                    # copy the suffix (incl. terminator)
    a.label("sfx")
    a.op(0x6004 | (0 << 8) | (2 << 4))                       # mov.b @r2+,r0
    a.op(movb_st(0, 7)); a.op(addi(7, 1)); a.op(tst(0, 0)); a.br("bf", "sfx"); a.op(NOP)
    # x/y from state
    # compute the text width (sum of the advances), then center: r13 = middle - width/2
    a.op(mov(14, 2)); a.op(movi(6, 0))
    a.label("w")
    a.op(movb_ld(2, 0)); a.op(tst(0, 0)); a.br("bt", "wd"); a.op(NOP)
    a.op(0x8800 | 0xBC); a.br("bt", "wsp"); a.op(NOP)         # cmp/eq #-68,r0 (space)
    a.lit(1, ADVP); a.br("bra", "wadd"); a.op(movl_ld(1, 1))
    a.label("wsp")
    a.lit(1, SPACEP); a.op(movl_ld(1, 1))
    a.label("wadd")
    a.op(add(1, 6)); a.op(addi(2, 1)); a.br("bra", "w"); a.op(NOP)
    a.label("wd")
    a.op(0x4001 | (6 << 8))                                   # shlr r6
    a.op(movl_ld_d(11, 8, 13)); a.op(sub(6, 13))
    a.op(movl_ld_d(11, 12, 12))
    a.label("loop")
    a.op(movb_ld(14, 0)); a.op(extub(0, 0)); a.op(tst(0, 0)); a.br("bt", "enddraw"); a.op(NOP)
    a.op(0xC800 | 0x80)                                       # tst #0x80,r0  (T=1: old table)
    a.br("bt", "oldtab"); a.op(NOP)
    # new table (name entry): index = r0 & 0x7F
    a.op(0xC900 | 0x7F)                                       # and #0x7F,r0
    a.op(mov(0, 4)); a.op(shll2(4)); a.op(shll(4))
    a.lit(1, NEWTAB); a.op(add(1, 4))
    a.lit(1, 0x41880000)                                      # 17.0
    a.op(lds_fpul(1)); a.op(fsts(6))
    a.br("bra", "call"); a.op(NOP)
    a.label("oldtab")
    a.op(mov(0, 4)); a.op(addi(4, -28)); a.op(shll2(4)); a.op(shll(4))
    a.lit(1, GLYPH); a.op(add(1, 4))
    a.lit(1, 0x41780000)                                      # 15.5
    a.op(lds_fpul(1)); a.op(fsts(6))
    a.label("call")
    a.lit(5, CTX); a.op(movi(6, 0)); a.op(movi(7, 1))
    a.op(movi(1, 0)); a.op(movl_push(1)); a.op(movi(1, -1)); a.op(movl_push(1))
    a.lit(1, 0x44000000); a.op(lds_fpul(1)); a.op(fsts(7))    # fr7 = 512.0
    a.op(lds_fpul(13)); a.op(float_fpul(4))                   # fr4 = x
    a.op(lds_fpul(12)); a.op(float_fpul(5))                   # fr5 = y
    a.lit(1, DF798); a.op(jsr(1)); a.op(NOP)
    a.op(addi(15, 8))
    a.op(movb_ld(14, 0)); a.op(0x8800 | 0xBC)                 # cmp/eq #-68,r0 (space glyph 0x80|60)
    a.br("bt", "spadv"); a.op(NOP)
    a.lit(1, ADVP); a.br("bra", "addx"); a.op(movl_ld(1, 1))  # delay slot: r1 = advance
    a.label("spadv")
    a.lit(1, SPACEP); a.op(movl_ld(1, 1))
    a.label("addx")
    a.op(add(1, 13)); a.op(addi(14, 1))
    a.br("bra", "loop"); a.op(NOP)
    a.label("enddraw")
    a.op(addi(15, 48))
    a.label("end")
    for r in (14, 13, 12, 11, 10, 9, 8): a.op(movl_pop(r))
    a.op(LDS_PR_POP); a.op(RTS); a.op(NOP)
    return a.finish(), a


if __name__ == "__main__":
    code, a = build()
    print(f"{len(code):#x} bytes, pool={len(a.pool)}")
    import capstone as cs
    md = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_SHFPU | cs.CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    for i in md.disasm(code, CAVE):
        print(f"{i.address:#x}: {i.mnemonic} {i.op_str}")
