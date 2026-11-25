#!/usr/bin/env python3
"""Combo damage display ("NN DMG" under HIT COMBO) for the PS2 KOF XI (JP, SLPS-25660).

Port of the arcade combo damage display (SH-4) to MIPS (R5900), patched statically
into the ELF (no runtime code writes, so no EE cache issue on real hardware).

  python -I make_combo_dmg_ps2.py --elf SLPS_25660_JP.elf --out SLPS_25660_JP.patched.elf
  python -I make_combo_dmg_ps2.py --iso "KOFXI JP.iso" --out-iso "KOFXI JP combo-dmg.iso"

Needs: keystone-engine, capstone.
"""
import argparse, shutil, struct, sys
import hitbox_ps2 as HB
import frameadv_ps2 as FA
import ukemi_ps2 as UK
import keystone as ks_mod
import capstone

# ---- JP ELF layout / addresses (see memory/project_ps2-hack-port.md) ----
ELF_OFF = 0x100            # file offset of the single loadable segment
ELF_BASE = 0x100000        # its vaddr
ELF_FILESZ = 0x305700

CAVE = 0x3AC000            # code (zero run 0x3A2D72-0x3B34BC, zero in RAM in all test states); v8: moved from 0x3AB100 (grew)
DATA = 0x3AB000            # state/params (see below)
TEAM0 = 0x9BDB50           # team struct P1 (P2 = +0x248)
STRIDE = 0x248
ORIG_FN = 0x192710         # HitCombo task fn
PRINTER = 0x1788C0         # text printer
CTX = 0x9BD538
GLYPHTAB = 0x363930        # name-entry glyph rects (63 x 8 bytes)
HOOKS = ((0x30FD80, 0x30FD88), (0x30FDA4, 0x30FDAC))   # (lui a0, addiu a0) pairs

# DATA+0x7C: u32 "practice display option active" flag (set by the practice hack: display=True in patch_elf)
PRACTICE_FLAG = DATA + 0x7C
# data layout (u32 each):
#   +0x00 side0 {start, dmg, centerX, y}   +0x10 side1
#   +0x20 hold frames   +0x24 advance   +0x28 space advance   +0x40 hold counters [2]
INIT = {
    DATA + 0x08: 61, DATA + 0x0C: 238,       # P1 center x / y (arcade / normal matches)
    DATA + 0x18: 570, DATA + 0x1C: 238,      # P2 center x / y
    # practice mode (2026-11-22): under the HP bars (GG training style), the edge position was covered by the INPUT display
    DATA + 0x30: 150, DATA + 0x34: 108,      # P1 center x / y
    DATA + 0x38: 490, DATA + 0x3C: 108,      # P2 center x / y
    DATA + 0x20: 10, DATA + 0x24: 14, DATA + 0x28: 8,
}
# +0x50 stun struct side0 {start, val}, +0x58 side1; +0x60 suffix " DMG", +0x70 suffix " STUN" (glyph idx, 0xFF end)
INIT_BYTES = {
    DATA + 0x60: bytes([60, 3, 12, 6, 255]),
    DATA + 0x70: bytes([60, 18, 19, 20, 13, 255]),
    DATA + 0xB0: bytes([60, 7, 8, 19, 18, 255]),     # " HITS" (H=7 I=8 T=19 S=18); +0xB8/+0xBC = hit count per side (NOT 0x80..0x9F: that is the quick-rematch BUF)
}
LINE_DY = 18               # pixel offset of the STUN line below the DMG line
MODE_ADDR = 0x9E9780       # game mode byte (8 = practice)
ACTOR_SLOTS = 0x1DC9410    # 'Director Sprite' actor slots (0x200 x 0x18), see HIDE_VANILLA in source()
REGVIS_HOOK = (0x323668, 0x24050001)   # addiu $a1, $zero, 1 (visible byte) in the actor registration 0x3235f0 -> jal regvis stub
OPT_ADDR = 0x9CB247        # DISPLAY option byte (unused practice slot): 0 DAMAGE 1 STUN 2 BOTH 3 OFF
OPT2_ADDR = 0x9CB287        # DISPLAY option of the OPTIONS > GRAPHIC SETTING page (normal matches), saved at save+0x294FE
STRTAB = 0x3AC800          # 4 value strings, stride 0x14
# glyph indices into the name-entry table: digits 0->35, d->25+d ; ' '=60 'D'=3 'M'=12 'G'=6 ; 0xFF = end
SUFFIX = (60, 3, 12, 6)


def hi_lo(v):
    lo = v & 0xFFFF
    hi = (v >> 16) + (1 if lo & 0x8000 else 0)
    return hi & 0xFFFF, lo


def digit(reg, n, out):
    """emit glyph index for the digit in reg into (s5)++"""
    out.append(f"""
    beqz {reg}, dz{n}
    nop
    addiu $t4, {reg}, 25
    b dw{n}
    nop
dz{n}:
    addiu $t4, $zero, 35
dw{n}:
    sb $t4, 0($s5)
    addiu $s5, $s5, 1
""")


def sx(v):
    """signed 16-bit immediate"""
    return v if v < 0x8000 else v - 0x10000


def source(input_hook=False, frameadv=False):
    d_hi, d_lo = hi_lo(DATA)
    t_hi, t_lo = hi_lo(TEAM0)
    g_hi, g_lo = hi_lo(GLYPHTAB)
    c_hi, c_lo = hi_lo(CTX)
    m_hi, m_lo = hi_lo(MODE_ADDR)
    o_hi, o_lo = hi_lo(OPT_ADDR)
    o2_hi, o2_lo = hi_lo(OPT2_ADDR)
    sd_hi, sd_lo = hi_lo(DATA + 0x60)      # suffix " DMG"
    ss_hi, ss_lo = hi_lo(DATA + 0x70)      # suffix " STUN"
    sh_hi, sh_lo = hi_lo(DATA + 0xB0)      # suffix " HITS"
    pi_hi, pi_lo = hi_lo(PM_INPUT_ADDR)    # practice INPUT option (0 OFF 1 1P 2 2P 3 BOTH)
    INPUT_CALL = f"""
    daddu $a0, $s1, $zero
    jal {QT:#x}
    nop
    daddu $a0, $s1, $zero
    jal {IN_CODE:#x}
    nop
"""
    f_hi, f_lo = hi_lo(PRACTICE_FLAG)
    a_hi, a_lo = hi_lo(ACTOR_SLOTS)
    # frame advantage display (frameadv_ps2.py): per-frame logic, and the extra line after the last line of the practice block
    FA_TICK_CALL = f"""
    daddu $a0, $s1, $zero
    jal {FA.FA_CODE:#x}
    nop
"""
    # practice DISPLAY values with the frame display (ATG 2026-11-24): 0 ALL (DMG + STUN + frames), 1 DMG+STN, 2 FRAMES, 3 OFF.
    # Mapped onto the internal values of the line code (2 = damage + stun, 3 = off); FRAMES jumps past the damage / stun lines.
    # The practice value is kept at 0x2C($sp) for fadraw.  Normal matches (OPTIONS DISPLAY) are unchanged.
    PV_MAP = """
    sltiu $t4, $s5, 4
    bnez $t4, pv_ok
    nop
    addu $s5, $zero, $zero
pv_ok:
    sw $s5, 0x2C($sp)
    addiu $t4, $zero, 3
    beq $s5, $t4, gotv
    nop
    addiu $t4, $zero, 2
    bne $s5, $t4, pv_dmgstn
    nop
    sw $zero, 0x34($sp)
    b nostun
    nop
pv_dmgstn:
    addiu $s5, $zero, 2
""" if frameadv else ""
    FA_DRAW_CALL = f"""
    lw $t4, 0x34($sp)
    addiu $t4, $t4, {LINE_DY}
    sw $t4, 0x34($sp)
fadraw:
    lw $t4, 0x2C($sp)
    addiu $t5, $zero, 1
    beq $t4, $t5, finish
    nop
    daddu $a0, $s1, $zero
    lw $a1, 0($s6)
    lw $a2, 4($s6)
    lw $t4, 0x34($sp)
    addu $a2, $a2, $t4
    jal {FA.FA_DRAW:#x}
    nop
""" if frameadv else "fadraw:\n"
    # practice mode, INPUT display on for this side: hide the vanilla HIT COMBO counter of this side (it overlaps the input list,
    # the "N HITS" line replaces it).  0x192710 drives the counter through 'Director Ctrl' tasks (anim group 2; side 0 = director
    # ids 0x15..0x1B + 0x23, side 1 = 0x1C..0x22 + 0x24), whose scripts spawn 'Director Sprite' actors.  Actor slots ACTOR_SLOTS
    # (0x200 x 0x18: +0 obj, +4 group, +8 director id, +0xC visible byte, set to 1 only by the registration 0x3235f0 and read by the
    # actor update 0x327f10 before drawing): clear it every frame for this side's directors.  New sprites are registered invisible by
    # the regvis stub (REGVIS_HOOK); this loop covers INPUT being switched on while a counter is already on screen.
    HIDE_VANILLA = f"""
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t4, $zero, 8
    bne $t1, $t4, novh
    nop
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, novh
    nop
    lui $t0, {pi_hi:#x}
    lbu $t1, {sx(pi_lo)}($t0)
    addiu $t4, $zero, 3
    beq $t1, $t4, vhok
    nop
    addiu $t4, $s1, 1
    bne $t1, $t4, novh
    nop
vhok:
    lui $t8, {a_hi:#x}
    addiu $t8, $t8, {sx(a_lo)}
    addiu $t9, $t8, 0x3000
    sll $t5, $s1, 3
    subu $t5, $t5, $s1
    addiu $t5, $t5, 0x15
    addiu $t6, $t5, 7
    addiu $t7, $s1, 0x23
vhloop:
    lw $t0, 0($t8)
    beqz $t0, vhnext
    nop
    lw $t0, 4($t8)
    addiu $t4, $zero, 2
    bne $t0, $t4, vhnext
    nop
    lw $t0, 8($t8)
    beq $t0, $t7, vhclr
    nop
    slt $t4, $t0, $t5
    bnez $t4, vhnext
    nop
    slt $t4, $t0, $t6
    beqz $t4, vhnext
    nop
vhclr:
    sb $zero, 0xC($t8)
vhnext:
    addiu $t8, $t8, 0x18
    bne $t8, $t9, vhloop
    nop
novh:
"""
    s = []
    # ---------------- wrapper (replaces the HitCombo task fn) ----------------
    s.append(f"""
    addiu $sp, $sp, -0x80
    sd $ra, 0x78($sp)
    sd $s0, 0x70($sp)
    sd $s1, 0x68($sp)
    sd $s2, 0x60($sp)
    sd $s3, 0x58($sp)
    sd $s4, 0x50($sp)
    sd $s5, 0x48($sp)
    sd $s6, 0x40($sp)
    sd $s7, 0x38($sp)
    daddu $s0, $a0, $zero
    jal {ORIG_FN:#x}
    nop
    lw $v0, 0x10($s0)
    lbu $s1, 0($v0)
{FA_TICK_CALL if frameadv else ''}
{INPUT_CALL if input_hook else ''}
{HIDE_VANILLA if input_hook else ''}
    lui $t0, {t_hi:#x}
    addiu $t0, $t0, {sx(t_lo)}
    addiu $t1, $t0, {STRIDE:#x}
    bnez $s1, side1
    nop
    daddu $s2, $t0, $zero
    daddu $s3, $t1, $zero
    b sidego
    nop
side1:
    daddu $s2, $t1, $zero
    daddu $s3, $t0, $zero
sidego:
    lui $s7, {d_hi:#x}
    addiu $s7, $s7, {sx(d_lo)}
    sll $t1, $s1, 4
    addu $s4, $s7, $t1
    sll $t1, $s1, 2
    addiu $t5, $s7, 0x40
    addu $s6, $t5, $t1
    lbu $s5, 7($s2)
    addu $t2, $zero, $zero
    addu $t9, $zero, $zero
""")
    for i in range(3):
        s.append(f"""
    lhu $t3, {0x154 + 0x20 * i:#x}($s3)
    sltiu $t4, $t3, 128
    bnez $t4, hpok{i}
    nop
    addu $t3, $zero, $zero
hpok{i}:
    addu $t2, $t2, $t3
    lhu $t3, {0x158 + 0x20 * i:#x}($s3)
    sltiu $t4, $t3, 128
    bnez $t4, stok{i}
    nop
    addu $t3, $zero, $zero
stok{i}:
    addu $t9, $t9, $t3
""")
    s.append(f"""
    sll $t1, $s1, 3
    addiu $t5, $s7, 0x50
    addu $s3, $t5, $t1
    bnez $s5, active
    nop
    sw $t2, 0($s4)
    sw $t9, 0($s3)
    # marker "no combo running" (-1 in DATA+0xC0+4*side): the first combo frame sees it and starts a fresh running max.  The combo counter
    # itself stays 1 for many frames until the 2nd hit, so it cannot tell the first frame (the max would be reset every frame and count down).
    sll $t1, $s1, 2
    addu $t1, $s7, $t1
    addiu $t5, $zero, -1
    sw $t5, 0xC0($t1)
    # practice mode (flag + game mode 8): keep the last result on screen (no hold timeout), it is overwritten by the next combo
    lw $t8, 0x7c($s7)
    beqz $t8, npr
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t4, $zero, 8
    beq $t1, $t4, show
    nop
npr:
    lw $t3, 0($s6)
    bnez $t3, holdgo
    nop
    sw $zero, 4($s3)
    sw $zero, 4($s4)
    sll $t1, $s1, 2
    addu $t1, $s7, $t1
    sw $zero, 0xB8($t1)
    b finish
    nop
holdgo:
    addiu $t3, $t3, -1
    sw $t3, 0($s6)
    b show
    nop
active:
    lw $t3, 0($s4)
    subu $t6, $t3, $t2
    bgtz $t6, pos
    nop
    addu $t6, $zero, $zero
pos:
    sw $t6, 4($s4)
    # STUN = running max of (start sum - current sum) of the victim team (never above 112; the natural recovery between the hits only
    # lowers the current difference, the max keeps the peak).
    lw $t3, 0($s3)
    subu $t6, $t3, $t9
    bgtz $t6, pos2
    nop
    # raw diff <= 0 after a counted hit = dizzy refill (stun jumped back to 112 in the same frame as the
    # stunning hit, so 0 is never visible): victim lost its whole gauge = start - cur + 112
    addiu $t5, $zero, 1
    beq $s5, $t5, stz2
    nop
    lw $t4, 4($s3)
    beqz $t4, stz2
    nop
    addiu $t6, $t6, 112
    bgtz $t6, pos2
    nop
stz2:
    addu $t6, $zero, $zero
pos2:
    lw $t4, 4($s3)
    sll $t1, $s1, 2
    addu $t1, $s7, $t1
    lw $t5, 0xC0($t1)
    addiu $t7, $zero, -1
    bne $t5, $t7, keepprev
    nop
    addu $t4, $zero, $zero
    sw $zero, 0xC0($t1)
keepprev:
    sltu $t5, $t6, $t4
    beqz $t5, setv
    nop
    daddu $t6, $t4, $zero
setv:
    sw $t6, 4($s3)
    sll $t1, $s1, 2
    addu $t1, $s7, $t1
    sw $s5, 0xB8($t1)
    sltiu $t4, $s5, 2
    beqz $t4, arm
    nop
    sw $zero, 0($s6)
    # first hit: arcade shows nothing yet, practice mode shows the result from hit 1
    lw $t8, 0x7c($s7)
    beqz $t8, finish
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t4, $zero, 8
    bne $t1, $t4, finish
    nop
    b show
    nop
arm:
    lw $t3, 0x20($s7)
    sw $t3, 0($s6)
show:
    addu $s5, $zero, $zero
    sw $zero, 0x30($sp)
    addiu $s6, $s4, 8
    lw $t2, 0x7c($s7)
    beqz $t2, normalmode
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t4, $zero, 8
    bne $t1, $t4, normalmode
    nop
    addiu $t4, $zero, 1
    sw $t4, 0x30($sp)
    sll $t1, $s1, 3
    addiu $s6, $s7, 0x30
    addu $s6, $s6, $t1
    lui $t0, {o_hi:#x}
    lbu $s5, {sx(o_lo)}($t0)
{PV_MAP}
    b gotv
    nop
normalmode:
    lui $t0, {o2_hi:#x}
    lbu $s5, {sx(o2_lo)}($t0)
gotv:
    sltiu $t4, $s5, 4
    bnez $t4, vok
    nop
    addu $s5, $zero, $zero
vok:
    addiu $t4, $zero, 3
    beq $s5, $t4, finish
    nop
    sw $zero, 0x34($sp)
    addiu $t4, $zero, 1
    beq $s5, $t4, skipdmg
    nop
    lw $a0, 4($s4)
    lui $a1, {sd_hi:#x}
    addiu $a1, $a1, {sx(sd_lo)}
    lw $a2, 0($s6)
    lw $a3, 4($s6)
    bal drawline
    nop
    addiu $t4, $zero, {LINE_DY}
    sw $t4, 0x34($sp)
skipdmg:
    beqz $s5, nostun
    nop
    lw $a0, 4($s3)
    lui $a1, {ss_hi:#x}
    addiu $a1, $a1, {sx(ss_lo)}
    lw $a2, 0($s6)
    lw $a3, 4($s6)
    lw $t4, 0x34($sp)
    addu $a3, $a3, $t4
    bal drawline
    nop
    lw $t4, 0x34($sp)
    addiu $t4, $t4, {LINE_DY}
    sw $t4, 0x34($sp)
nostun:
    # practice mode, INPUT display on for this side: "N HITS" line below the last line (replaces the hidden hit counter)
    lw $t4, 0x30($sp)
    beqz $t4, finish
    nop
    lui $t0, {pi_hi:#x}
    lbu $t1, {sx(pi_lo)}($t0)
    addiu $t4, $zero, 3
    beq $t1, $t4, hitsok
    nop
    addiu $t4, $s1, 1
    bne $t1, $t4, fadraw
    nop
hitsok:
    sll $t1, $s1, 2
    addu $t1, $s7, $t1
    lw $a0, 0xB8($t1)
    sltiu $t4, $a0, 2
    bnez $t4, fadraw
    nop
    lui $a1, {sh_hi:#x}
    addiu $a1, $a1, {sx(sh_lo)}
    lw $a2, 0($s6)
    lw $a3, 4($s6)
    lw $t4, 0x34($sp)
    addu $a3, $a3, $t4
    bal drawline
    nop
{FA_DRAW_CALL}
finish:
    ld $ra, 0x78($sp)
    ld $s0, 0x70($sp)
    ld $s1, 0x68($sp)
    ld $s2, 0x60($sp)
    ld $s3, 0x58($sp)
    ld $s4, 0x50($sp)
    ld $s5, 0x48($sp)
    ld $s6, 0x40($sp)
    ld $s7, 0x38($sp)
    jr $ra
    addiu $sp, $sp, 0x80
""")
    # ---------------- drawline(a0=value, a1=suffix glyphs (0xFF end), a2=center x, a3=y) ----------------
    s.append(f"""
drawline:
    addiu $sp, $sp, -0x60
    sd $ra, 0x58($sp)
    sd $s1, 0x50($sp)
    sd $s2, 0x48($sp)
    sd $s3, 0x40($sp)
    sd $s4, 0x38($sp)
    sd $s5, 0x30($sp)
    sd $s6, 0x28($sp)
    daddu $s1, $a2, $zero
    daddu $s2, $a3, $zero
    daddu $s3, $a1, $zero
    daddu $t6, $a0, $zero
    lui $t0, {d_hi:#x}
    addiu $t0, $t0, {sx(d_lo)}
    lw $s6, 0x24($t0)
    lw $s4, 0x28($t0)
    addu $t7, $zero, $zero
hl:
    sltiu $t4, $t6, 100
    bnez $t4, hd
    nop
    addiu $t6, $t6, -100
    addiu $t7, $t7, 1
    b hl
    nop
hd:
    addu $t8, $zero, $zero
tl:
    sltiu $t4, $t6, 10
    bnez $t4, td
    nop
    addiu $t6, $t6, -10
    addiu $t8, $t8, 1
    b tl
    nop
td:
    addiu $s5, $sp, 0
    addu $t9, $zero, $zero
    beqz $t7, skh
    nop
""")
    digit("$t7", "h", s)
    s.append("""
    addiu $t9, $zero, 1
skh:
    bnez $t8, dot
    nop
    beqz $t9, skt
    nop
dot:
""")
    digit("$t8", "t", s)
    s.append("skt:\n")
    digit("$t6", "o", s)
    s.append("""
sl:
    lbu $t4, 0($s3)
    sb $t4, 0($s5)
    addiu $s3, $s3, 1
    addiu $s5, $s5, 1
    addiu $t5, $zero, 255
    bne $t4, $t5, sl
    nop
    addiu $t1, $sp, 0
    addu $t0, $zero, $zero
wl:
    lbu $t4, 0($t1)
    addiu $t5, $zero, 255
    beq $t4, $t5, wd
    nop
    addiu $t5, $zero, 60
    beq $t4, $t5, wsp
    nop
    addu $t0, $t0, $s6
    b wn
    nop
wsp:
    addu $t0, $t0, $s4
wn:
    addiu $t1, $t1, 1
    b wl
    nop
wd:
    srl $t0, $t0, 1
    subu $s1, $s1, $t0
    addiu $s5, $sp, 0
dl:
    lbu $t4, 0($s5)
    addiu $t5, $zero, 255
    beq $t4, $t5, dfin
    nop
    sll $t4, $t4, 3
""")
    s.append(f"""
    lui $t0, {g_hi:#x}
    addiu $t0, $t0, {sx(g_lo)}
    addu $a0, $t0, $t4
    lui $a1, {c_hi:#x}
    addiu $a1, $a1, {sx(c_lo)}
    daddu $a2, $zero, $zero
    addiu $a3, $zero, 1
    addiu $t0, $zero, -1
    daddu $t1, $zero, $zero
    mtc1 $s1, $f0
    cvt.s.w $f12, $f0
    mtc1 $s2, $f1
    cvt.s.w $f13, $f1
    lui $t2, 0x4188
    mtc1 $t2, $f14
    lui $t2, 0x4400
    mtc1 $t2, $f15
    jal {PRINTER:#x}
    nop
    lbu $t4, 0($s5)
    addiu $t5, $zero, 60
    daddu $t2, $s6, $zero
    bne $t4, $t5, adv
    nop
    daddu $t2, $s4, $zero
adv:
    addu $s1, $s1, $t2
    addiu $s5, $s5, 1
    b dl
    nop
dfin:
    ld $ra, 0x58($sp)
    ld $s1, 0x50($sp)
    ld $s2, 0x48($sp)
    ld $s3, 0x40($sp)
    ld $s4, 0x38($sp)
    ld $s5, 0x30($sp)
    ld $s6, 0x28($sp)
    jr $ra
    addiu $sp, $sp, 0x60
""")
    return "".join(s)


def numeric_regs(src):
    """Keystone's MIPS64 mode uses N64 names ($t0 = $12). Our source uses the o32/EE meaning,
    so turn every $tN into its o32 register number to remove the ambiguity."""
    import re
    o32 = {f"t{i}": (8 + i if i < 8 else 24 + i - 8) for i in range(10)}
    return re.sub(r"\$(t\d)\b", lambda m: f"${o32[m.group(1)]}", src)


def assert_no_pic(code, base, name):
    """keystone turns `jal label` into `ld $t9, ($gp); jalr $t9` when it feels like it (v63..v67 froze the game on the second hit of a
    combo because of that: the HUD cave called drawline through $gp).  Any jalr in generated stub code is a bug: refuse it."""
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    for i in md.disasm(code, base):
        bad = i.mnemonic == "jalr" or (i.mnemonic == "ld" and "($gp)" in i.op_str.replace(" ", ""))
        assert not bad, f"{name}: PIC call at {i.address:#x}: {i.mnemonic} {i.op_str} (use absolute `jal 0x..` or `bal`)"


def regvis_stub(addr):
    """Called by `jal` at REGVIS_HOOK (replaces `addiu $a1, $zero, 1`) inside the sprite actor registration 0x3235f0: a1 = the
    visible byte of the new actor slot (s2 = director id, s0 = anim group).  0 for the HIT COMBO directors of a side whose practice
    INPUT display is on: otherwise a new counter sprite draws for a frame before the HUD wrapper clears it (flicker on every hit).
    Keeps a0, a2, a3, v0, t0-t2 (used by the caller afterwards)."""
    m_hi, m_lo = hi_lo(MODE_ADDR)
    f_hi, f_lo = hi_lo(PRACTICE_FLAG)
    pi_hi, pi_lo = hi_lo(PM_INPUT_ADDR)
    src = f"""
    addiu $a1, $zero, 1
    addiu $t3, $zero, 2
    bne $s0, $t3, rvret
    nop
    addiu $t3, $s2, -0x15
    sltiu $t4, $t3, 7
    bnez $t4, rvs0
    nop
    addiu $t3, $s2, -0x1c
    sltiu $t4, $t3, 7
    bnez $t4, rvs1
    nop
    addiu $t3, $zero, 0x23
    beq $s2, $t3, rvs0
    nop
    addiu $t3, $zero, 0x24
    bne $s2, $t3, rvret
    nop
rvs1:
    addiu $t5, $zero, 2
    b rvchk
    nop
rvs0:
    addiu $t5, $zero, 1
rvchk:
    lui $t3, {m_hi:#x}
    lbu $t4, {sx(m_lo)}($t3)
    addiu $t6, $zero, 8
    bne $t4, $t6, rvret
    nop
    lui $t3, {f_hi:#x}
    lw $t4, {sx(f_lo)}($t3)
    beqz $t4, rvret
    nop
    lui $t3, {pi_hi:#x}
    lbu $t4, {sx(pi_lo)}($t3)
    addiu $t6, $zero, 3
    beq $t4, $t6, rvhide
    nop
    bne $t4, $t5, rvret
    nop
rvhide:
    addu $a1, $zero, $zero
rvret:
    jr $ra
    nop
"""
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    enc, n = ks.asm(".set noreorder\n" + numeric_regs(src), addr)
    assert_no_pic(bytes(enc), addr, "regvis stub")
    return bytes(enc)


def assemble(input_hook=False, frameadv=False):
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    # noreorder: keystone would otherwise insert its own delay-slot nop after every branch/jal
    enc, n = ks.asm(".set noreorder\n" + numeric_regs(source(input_hook, frameadv)), CAVE)
    assert_no_pic(bytes(enc), CAVE, "HUD cave")
    return bytes(enc)


# ---- unlock-all: force the 14-bit unlock mask (u16 @ 0x9BEC80) to 0x3FFF ----
# Bits 0-6 / 7-13 gate the locked characters (ids 0x21-0x27 / 0x29-0x2F: bosses + console chars)
# and the extras. Hooks: new-save init (FUN_00336d50) and save load (FUN_002fd760).
STUB1 = 0x3AB500            # runs inside the init function, then tail-jumps to the original callee
STUB2 = 0x3AB540            # wraps the mask memcpy of the save loader
HOOK_INIT = (0x336DBC, 0x0C0692E0, 0x1A4B80)     # jal 0x1a4b80
HOOK_LOAD = (0x2FD8F8, 0x0C049C48, 0x127120)     # jal 0x127120 (a0=0x9BEC80, a1=save+0x29222, a2=2)


def unlock_stubs():
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    s1 = f""".set noreorder
    lui $8, 0x9c
    addiu $9, $zero, 0x3fff
    sh $9, -0x1380($8)
    j {HOOK_INIT[2]:#x}
    nop
"""
    s2 = f""".set noreorder
    addiu $sp, $sp, -0x10
    sd $ra, 8($sp)
    jal {HOOK_LOAD[2]:#x}
    nop
    lui $8, 0x9c
    addiu $9, $zero, 0x3fff
    sh $9, -0x1380($8)
    ld $ra, 8($sp)
    jr $ra
    addiu $sp, $sp, 0x10
"""
    return bytes(ks.asm(s1, STUB1)[0]), bytes(ks.asm(s2, STUB2)[0])


# ---- quick rematch (Arcade Versus = game mode 1/3/5): hold START + BTN_A on the victory screen ----
# Vanilla: scene 0x308 end -> FUN_0019eaf0 + callback 0x130EE0 (character select, wipes the teams).
# Patch: WRAP replaces that block; with A (Square) held alone (no Start needed in Arcade Versus) it restores the saved team (order bytes +0x28..0x2A,
# member position bytes with leader bit at +0x15C/+0x17C/+0x19C) and starts the match directly (0x30D750).
# SAVE runs when the VS order select finishes (the two places that install 0x30D750 in FUN_00134850).
BUF = 0x3AB080              # +4 valid, +0x10 side0 {order[3], pos[3]}, +0x18 side1
DBG = 0x3AB0A0             # diagnostics for WRAP (count, last held word, BUF valid)
STUB_SAVE = 0x3AB600
WRAP = 0x3AB6C0
# Load Type NORMAL (byte 0x9CB286 == 0) makes the match start (FUN_0030D7D0 -> 0x30D81C) take the long stage-loading-screen path, whose extra
# 5-7 MB heap block exhausts the heap after a rematch (FUN_001A4B80 returns 0, the char loader then writes to address 0 and wrecks the kernel).
# A rematch (A or B held in WRAP) therefore forces the SIMPLE path: FORCE_SIMPLE (byte DBG+0xC) is OR-ed into the load-type test by LT_CAVE.
LT_CAVE = 0x3AB900
FORCE_SIMPLE = 0x3AB0AC      # = DBG + 0xC
LT_SITE = 0x30D818           # lui v0,0x9d ; lbu v0,-0x4d7a(v0) ; sltu v0,zero,v0 ; jr ra
BTN_START = 0x0008
BTN_A = 0x8000              # PS2 pad bit: Square = the game's A button (confirmed in game)
BTN_B = 0x4000              # PS2 pad bit: Cross (assumed to be the game's B button)
REMATCH_SITE = 0x19DD5C     # jal 0x19eaf0 ; nop ; lui a0,0x13 ; move a1,s1 ; jal 0x155da0 ; addiu a0,a0,0xee0
SAVE_SITES = ((0x1348A8, 0x1348B4), (0x134904, 0x13490C))   # (lui a0,0x31 ; addiu a0,a0,-0x28b0) pairs


def rematch_stubs():
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    bh, bl = hi_lo(BUF)
    bl = bl if bl < 0x8000 else bl - 0x10000
    dh, dl = hi_lo(DBG)
    dl = dl if dl < 0x8000 else dl - 0x10000
    team_hi, team_lo = hi_lo(TEAM0)
    team_lo = team_lo if team_lo < 0x8000 else team_lo - 0x10000
    fields = (0x28, 0x29, 0x2A, 0x15C, 0x17C, 0x19C)
    save = [".set noreorder", f"lui $8, {bh:#x}", f"addiu $8, $8, {bl}",
            f"lui $10, {team_hi:#x}", f"addiu $10, $10, {team_lo}"]
    for side in (0, 1):
        for i, f in enumerate(fields):
            save += [f"lbu $11, {f:#x}($10)", f"sb $11, {0x10 + side * 8 + i}($8)"]
        if side == 0:
            save.append(f"addiu $10, $10, {STRIDE:#x}")
    save += ["addiu $11, $zero, 1", "sw $11, 4($8)", "j 0x30d750", "nop"]
    rest = [".set noreorder", f"lui $8, {bh:#x}", f"addiu $8, $8, {bl}", "lw $10, 4($8)",
            "beqz $10, deflt", "nop",
            f"lui $11, {team_hi:#x}", f"addiu $11, $11, {team_lo}"]
    for side in (0, 1):
        for i, f in enumerate(fields):
            rest += [f"lbu $12, {0x10 + side * 8 + i}($8)", f"sb $12, {f:#x}($11)"]
        if side == 0:
            rest.append(f"addiu $11, $11, {STRIDE:#x}")
    rest += ["lui $4, 0x31", "addiu $4, $4, -0x28b0", "b docall", "nop"]
    wrap = [".set noreorder", "addiu $sp, $sp, -0x20", "sd $ra, 0x18($sp)", "sd $s0, 0x10($sp)",
            "daddu $s0, $4, $zero", "jal 0x19eaf0", "nop",
            # held words: 0x9BEA20 (side 0) / 0x9BEA2C (side 1); 0x9BEA22/2E are the press edges
            "lui $8, 0x9c", "lhu $9, -0x15e0($8)", "lhu $10, -0x15d4($8)", "or $9, $9, $10",
            # diagnostics: DBG+0 call count, +4 last held word, +8 BUF valid flag
            f"lui $11, {dh:#x}", f"addiu $11, $11, {dl}", "lw $12, 0($11)", "addiu $12, $12, 1", "sw $12, 0($11)",
            "sw $9, 4($11)", f"lui $12, {bh:#x}", f"addiu $12, $12, {bl}", "lw $12, 4($12)", "sw $12, 8($11)",
            f"andi $10, $9, {BTN_A | BTN_B:#x}", "sltu $10, $zero, $10", "sb $10, 0xc($11)",
            f"andi $10, $9, {BTN_A:#x}", "beqz $10, chkb", "nop"] + rest[1:] + [
            # B held: keep the teams, clear "leader already chosen" (bit 1 of team+0x50) and open the
            # VS order/leader select (FUN_00134850); STUB_SAVE then stores the newly chosen order.
            "chkb:", f"andi $10, $9, {BTN_B:#x}", "beqz $10, deflt", "nop",
            f"lui $11, {team_hi:#x}", f"addiu $11, $11, {team_lo}",
            "lbu $12, 0x50($11)", "andi $12, $12, 0xfd", "sb $12, 0x50($11)",
            f"lbu $12, {0x50 + STRIDE:#x}($11)", "andi $12, $12, 0xfd", f"sb $12, {0x50 + STRIDE:#x}($11)",
            "lui $4, 0x13", "addiu $4, $4, 0x4850", "b docall", "nop",
            "deflt:", "lui $4, 0x13", "addiu $4, $4, 0xee0",
            "docall:", "daddu $5, $s0, $zero", "jal 0x155da0", "nop",
            "ld $s0, 0x10($sp)", "ld $ra, 0x18($sp)", "jr $ra", "addiu $sp, $sp, 0x20"]
    # "rest" starts with ".set noreorder" which we dropped via rest[1:]
    return (bytes(ks.asm("\n".join(save), STUB_SAVE)[0]), bytes(ks.asm("\n".join(wrap), WRAP)[0]))


def loadtype_stub():
    """Replacement for the tail of FUN_0030D7D0: return (load type byte | FORCE_SIMPLE) != 0."""
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    src = f""".set noreorder
lui $2, 0x9d
lbu $2, -0x4d7a($2)
lui $3, {FORCE_SIMPLE >> 16:#x}
ori $3, $3, {FORCE_SIMPLE & 0xFFFF:#x}
lbu $3, 0($3)
or $2, $2, $3
sltu $2, $zero, $2
jr $31
nop
"""
    return bytes(ks.asm(src, LT_CAVE)[0])


def patch_rematch(b, off):
    sv, wr = rematch_stubs()
    lt = loadtype_stub()
    assert not any(b[off(LT_CAVE):off(LT_CAVE) + len(lt)]), hex(LT_CAVE)
    b[off(LT_CAVE):off(LT_CAVE) + len(lt)] = lt
    assert struct.unpack_from("<I", b, off(LT_SITE))[0] == 0x3C02009D, "lui v0,0x9d"
    assert struct.unpack_from("<I", b, off(LT_SITE + 4))[0] == 0x9042B286, "lbu v0,-0x4d7a(v0)"
    struct.pack_into("<I", b, off(LT_SITE), 0x08000000 | (LT_CAVE >> 2))     # j LT_CAVE (the stub returns itself)
    struct.pack_into("<I", b, off(LT_SITE + 4), 0)                           # delay slot: nop
    assert len(sv) <= 0xC0 and len(wr) <= 0x200, (len(sv), len(wr))
    for a, st in ((STUB_SAVE, sv), (WRAP, wr), (BUF, bytes(0x20)), (DBG, bytes(0x10))):
        assert not any(b[off(a):off(a) + len(st)]), hex(a)
    b[off(STUB_SAVE):off(STUB_SAVE) + len(sv)] = sv
    b[off(WRAP):off(WRAP) + len(wr)] = wr
    # SAVE hooks: lui/addiu of the 0x30D750 callback address -> STUB_SAVE
    h, l = hi_lo(STUB_SAVE)
    for lui_a, addiu_a in SAVE_SITES:
        assert struct.unpack_from("<I", b, off(lui_a))[0] == 0x3C040031, hex(lui_a)
        assert struct.unpack_from("<I", b, off(addiu_a))[0] == 0x2484D750, hex(addiu_a)
        struct.pack_into("<I", b, off(lui_a), 0x3C040000 | h)
        struct.pack_into("<I", b, off(addiu_a), 0x24840000 | l)
    # rematch hook block (6 instrs): jal WRAP ; move a0,s1 ; 4x nop
    assert struct.unpack_from("<I", b, off(REMATCH_SITE))[0] == 0x0C067ABC, "jal 0x19eaf0"
    assert struct.unpack_from("<I", b, off(REMATCH_SITE + 0x14))[0] == 0x24840EE0, "addiu a0,0xee0"
    struct.pack_into("<I", b, off(REMATCH_SITE), 0x0C000000 | (WRAP >> 2))
    struct.pack_into("<I", b, off(REMATCH_SITE + 4), 0x0220202D)      # daddu $a0,$s1,$zero (delay slot)
    for k in range(2, 6):
        struct.pack_into("<I", b, off(REMATCH_SITE + 4 * k), 0)


# ---- same chars: allow the same character several times in one team ----
# FUN_00131e40 (arcade fn_8c06779c) skips its "already in this team" loop when bit 0x80 of the debug
# flag word 0x9BA210 ("PS SAME") is set: `bnez $v1, 0x132160` at 0x13210C. Make that branch unconditional.
SAMECHARS_SITE = 0x13210C
SAMECHARS_ORIG, SAMECHARS_NEW = 0x14600014, 0x10000014      # bnez $v1,+0x14  ->  b +0x14


# Palette fix: FUN_0012ed00(block, slot) loads the palette of one team slot but returns early when slot 1/2
# (resp. 4/5) holds the same character as slot 0 (resp. 3). With same-chars that leaves members 2 and 3 as
# black silhouettes, so always load:
#   0x12ED4C  bnel $v1,$a0,0x12ed74 (0x54640009)  -> b 0x12ed74 (0x10000009)   (same delay slot)
#   0x12ED68  beq  $v1,$a0,0x12edb0 (0x10640011)  -> nop
PALETTE_PATCHES = ((0x12ED4C, 0x54640009, 0x10000009), (0x12ED68, 0x10640011, 0x00000000))


def patch_samechars(b, off):
    assert struct.unpack_from("<I", b, off(SAMECHARS_SITE))[0] == SAMECHARS_ORIG, "same-chars site"
    struct.pack_into("<I", b, off(SAMECHARS_SITE), SAMECHARS_NEW)
    for site, orig, new in PALETTE_PATCHES:
        assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
        struct.pack_into("<I", b, off(site), new)


# ---- skip the start-up logos ----
# FUN_00307870 plays DATA\LOGO\LOGO00..LOGO04.DAT (194 frames each, fading) one after the other
# (caller 0x3079CC). The save-load step before it is a different function and stays untouched.
# Start the loop at LOGO_START instead of 0 (`move $s1,$zero` at 0x307898 -> `addiu $s1,$zero,LOGO_START`).
# 4 = only the last logo (SNK Playmore) is shown; 5 or more would skip all of them.
LOGO_SITE = 0x307898
LOGO_ORIG = 0x0000882D
LOGO_START = 4


def patch_skiplogos(b, off):
    assert struct.unpack_from("<I", b, off(LOGO_SITE))[0] == LOGO_ORIG, "logo loop init"
    struct.pack_into("<I", b, off(LOGO_SITE), 0x24110000 | LOGO_START)      # addiu $s1,$zero,LOGO_START


# ---- practice menu: row "AUTO CHARACTER" -> DISPLAY (byte 0x9CB247: DAMAGE/STUN/BOTH/OFF) ----
# FUN_003383d0 case 8 (input) and FUN_00338b80 case 0x10 (draw) used byte 0x9CB248 with 5 values, only active if LIFE=0-LIFE.
REGEN_FRAMES = 60          # practice LIFE: RECOVERY delay after the last hit / end of combo (vanilla 180)
REGEN_CAVE_A = 0x3AD480
REGEN_CAVE_B = 0x3AD490
DISPLAY_PATCHES = (
    (0x3387C4, 0x14430045, 0x00000000),   # bne cb245!=1 -> nop (row always active)
    (0x3387D4, 0x8044B248, 0x8044B247),   # lb  a0, cb248 -> cb247
    (0x3387E0, 0x24050005, 0x24050004),   # count 5 -> 4
    (0x3387EC, 0xA062B248, 0xA062B247),   # sb  v0, cb248 -> cb247
    (0x339198, 0x10430008, 0x10000008),   # beq cb245==1 -> b (always draw value)
    (0x3391C0, 0x3C03003D, 0x3C03003B),   # lui v1,0x3d -> 0x3b  (string table 0x3AC800)
    (0x3391C4, 0x9046B248, 0x9046B247),   # lbu a2, cb248 -> cb247
    (0x33A498, 0x10620003, 0x10000003),   # FUN_0033a390: beq cb247 equal -> b (ignore 0x247)
    (0x33A760, 0x10620003, 0x10000003),   # FUN_0033a750: same
    (0x3391C8, 0x24632BD0, 0x2463C800),   # addiu v1,v1,0x2bd0 -> 0xc800
    # practice COUNTER: ON freeze fix.  FUN_0033aaa0 forces the counter only while the combo counter of a side is 0, but it looked at the
    # DEFENDER's own side (always 0) instead of the attacker's, so every hit of a combo was forced (second hit froze the game).
    # FUN_0033a9b0 already uses the opponent side (FUN_00189e50).  Fix: side ^ 1 (lw moved into the delay slot of the bne, xori after the mask).
    (0x33AAF4, 0x00000000, 0x8C8300DC),   # nop -> lw v1,0xdc(a0)
    (0x33AAF8, 0x8C8300DC, 0x3063000C),   # lw v1,0xdc(a0) -> andi v1,v1,0xc
    (0x33AB04, 0x3063000C, 0x38630004),   # andi v1,v1,0xc -> xori v1,v1,4
    # practice LIFE: RECOVERY.  FUN_001870e0 arms the regen timer team+0x4a6 = 0xB4 (180F) on every damage; FUN_001873f0 counts it down
    # while the attacker has no combo and then refills HP.  Timer shortened to REGEN_FRAMES.
    (0x1871B8, 0x240200B4, 0x24020000 | REGEN_FRAMES),
    # practice LIFE: RECOVERY also refills STUN (team+0x158/0x15A of the active point, same 0x70 as HP).  The refill stores
    # `sh a2,8(v1)` / `sh a2,0xa(v1)` (HP, a2 = 0x70, v1 = point slot + 0x14c) exist twice (normal + replay branch): the 2nd store
    # becomes `j cave` (its delay slot keeps `sh a2,0x4a8(a0)`), the cave stores HP2 + both stun halves and returns to the `b 0x187690`.
    (0x1874F8, 0xA466000A, 0x08000000 | (REGEN_CAVE_A >> 2)),
    (0x18756C, 0xA466000A, 0x08000000 | (REGEN_CAVE_B >> 2)),
    # practice LIFE: RECOVERY must not refill while the victim is dizzy.  The function already skips when char object byte +0x4f0 has bit 0x80;
    # bit 0x40 of the same byte is the dizzy flag (set when the stun refills to 0x70, cleared when the dizzy ends; live log 2026-11-22).
    # `andi v1,v1,0x80` -> `andi v1,v1,0xC0`.  (+0x4b2 is NOT a flag, it toggles every frame.)
    (0x187414, 0x30630080, 0x306300C0),
)
REGEN_CAVES = (
    (REGEN_CAVE_A, 0x187500),
    (REGEN_CAVE_B, 0x187574),
)
DISPLAY_STRINGS = ("DAMAGE", "STUN", "BOTH", "OFF")
DISPLAY_STRINGS_FA = ("ALL", "DMG+STN", "FRAMES", "OFF")   # practice values with the frame display (frameadv_ps2.py)


# ---- practice COUNTER: ON hit-type fix ----
# FUN_0033a9b0 (called from the hit reaction picker FUN_001802a0) forces every hit record type < 5 to type 4 when the practice
# counter option is ON.  A real counter hit of a type-1 record (5E / j.E, the "absolutely no juggle" moves) uses type 3, which
# selects another hit animation (savestate diff 2026-11-20: anim 73 forced vs 67 real, record +0xC = 1/3) with 8F more limited
# juggle.  Fix: type 1 -> 3, everything else as before.  Site: `daddiu $s0,$zero,4` at 0x33AA74 -> `j PCFIX` (delay slot
# `sb $v0,1($s1)` stays); the cave code returns to 0x33AA7C (`move $v0,$s0`).
PCFIX = 0x3AD400
PCFIX_SITE = (0x33AA74, 0x64100004)


def pcfix_code():
    return opt_asm("""
    andi $8, $16, 0xff
    addiu $9, $zero, 1
    bne $8, $9, pcf_out
    addiu $16, $zero, 4
    addiu $16, $zero, 3
pcf_out:
    j 0x33AA7C
    nop
""", PCFIX)


def patch_display(b, off, frameadv=False):
    for a, orig, new in DISPLAY_PATCHES:
        assert struct.unpack_from("<I", b, off(a))[0] == orig, hex(a)
        struct.pack_into("<I", b, off(a), new)
    for cave, ret in REGEN_CAVES:
        words = (0xA466000A, 0xA466000C, 0x08000000 | (ret >> 2), 0xA466000E)   # sh a2,0xa/0xc(v1); j ret; (delay) sh a2,0xe(v1)
        assert not any(b[off(cave):off(cave) + 16]), "regen cave not free"
        struct.pack_into("<4I", b, off(cave), *words)
    code = pcfix_code()
    assert not any(b[off(PCFIX):off(PCFIX) + len(code)]), "practice counter fix cave not free"
    b[off(PCFIX):off(PCFIX) + len(code)] = code
    assert struct.unpack_from("<I", b, off(PCFIX_SITE[0]))[0] == PCFIX_SITE[1], "practice counter fix site"
    struct.pack_into("<I", b, off(PCFIX_SITE[0]), 0x08000000 | (PCFIX >> 2))
    assert off(STRTAB + 0x50) <= ELF_OFF + ELF_FILESZ and not any(b[off(STRTAB):off(STRTAB) + 0x50])
    for i, sname in enumerate(DISPLAY_STRINGS_FA if frameadv else DISPLAY_STRINGS):
        b[off(STRTAB + 0x14 * i):off(STRTAB + 0x14 * i) + len(sname)] = sname.encode("ascii")


# ---- practice menu layout: all rows move up, "SELECT BUTTON TO DEFAULT" text removed, new row INPUT under DISPLAY ----
# Rows are created by FUN_00337e70 (state 1, one row per frame, objects = task FUN_00338b80 with type in obj[0]; y = 0x60 + 24 * row).
# New visual order (v): 0 CONTROL .. 7 DISPLAY, 8 INPUT (new, types 0x1A label / 0x1B value), 9 STAGE SELECT, 10 SELECT BUTTON, 11 COMMAND,
# 12 KEY SETTING, 13 CHARACTER SELECT; y = PM_BASE_Y + 24 * v.  Cursor index i = v + 1 (0 = GAME START, 15 = GAME EXIT):
# input FUN_003383d0 (jump table 0x404ca0 gets one more entry, constants 0xb..0xe -> 0xc..0xf, movement wraps at 0x10), cursor bar
# FUN_003392e0 (exit = 0xf), position table 0x3D2830 (16 entries, patched in place), reset FUN_00336e10 (12 bytes).
# INPUT option byte 0x9CB24B: 0 OFF 1 1P 2 2P 3 BOTH.  Label graphic: SPR01.GRC page 1 at (128,192,128,32) (right half of the DISPLAY strip).
PM_BASE_Y = 0x5C
PM_INPUT_ADDR = 0x9CB24B
PM_JT_DRAW = 0x3AD500      # draw jump table (28 entries; 0x1A label, 0x1B value of the INPUT row)
PM_JT_IN = 0x3AD580        # input jump table (12 entries)
PM_RECT = 0x3AD5C0         # label rect of INPUT (u, v, w, h, 1, 0)
PM_ST_ROWY = 0x3AD600
PM_ST_ROWNEW = 0x3AD640
PM_ST_DLAB = 0x3AD6C0
PM_ST_DVAL = 0x3AD700
PM_ST_IN9 = 0x3AD780
PM_ST_AFTER = 0x3AD800     # after the DISPLAY label/value pair: creates the INPUT objects
PM_STR_INPUT = STRTAB + 0x50   # OFF / 1P / 2P / BOTH, stride 0x14
PM_INPUT_STRINGS = ("OFF", "1P", "2P", "BOTH")
PM_CURSOR_TAB = 0x3D2830
PM_RECT_DISPLAY = 0x3D2640 + 12 * 11 + 4    # width of the DISPLAY label rect: 256 -> 128 (INPUT label shares the strip)
PM_ORIG_CURSOR = [(416, 64)] + [(32, 120 + 24 * i) for i in range(13)] + [(416, 440), (0, 0)]
PM_PATCHES = (
    (0x33806C, 0x24500060, None),            # addiu s0,v0,0x60 -> jal ROWY
    (0x338110, 0x24480150, 0x24480000 | (PM_BASE_Y + 11 * 24)),   # COMMAND / KEY SETTING / CHARACTER SELECT start y
    (0x338174, 0x0C0CDBD0, 0x00000000),      # jal 0x336f40 (default text) -> nop (text stays removed)
    (0x338BAC, 0x2C61001A, 0x2C61001C),      # draw: types < 0x1C
    (0x338528, 0x2C41000B, 0x2C41000C),      # input: jump table size 12
    (0x3384CC, 0x2405000F, 0x24050010),      # cursor wraps at 0x10
    (0x3384F4, 0x2405000F, 0x24050010),
    (0x338988, 0x2403000B, 0x2403000C),      # COMMAND
    (0x338998, 0x2402000C, 0x2402000D),      # KEY SETTING
    (0x3389A4, 0x2402000E, 0x2402000F),      # GAME EXIT
    (0x3389B0, 0x2402000D, 0x2402000E),      # CHARACTER SELECT
    (0x33939C, 0x2402000E, 0x2402000F),      # cursor bar: GAME EXIT
    (0x336E28, 0x2406000B, 0x2406000C),
    (0x338130, 0x240801A0, 0x240801B0),      # GAME EXIT 16 px lower      # default: clear 12 bytes (incl. INPUT)
    (0x338144, 0x0100482D, 0x240901A0),      # GAME EXIT: `move t1,t0` (x target = y) -> t1 = 0x1A0, otherwise the button sat 16 px right of the cursor bar
)


def pm_stubs():
    o_hi, o_lo = hi_lo(PM_INPUT_ADDR)
    r_hi, r_lo = hi_lo(PM_RECT)
    s_hi, s_lo = hi_lo(PM_STR_INPUT)
    yin = PM_BASE_Y + 8 * 24
    st = {}
    st[PM_ST_ROWY] = opt_asm(f"""
    addiu $s0, $v0, {PM_BASE_Y}
    slti $at, $v1, 8
    bnez $at, rowy_out
    nop
    addiu $s0, $s0, 24
rowy_out:
    jr $ra
    nop
""", PM_ST_ROWY)
    st[PM_ST_ROWNEW] = opt_asm(f"""
    addiu $sp, $sp, -0x30
    sd $ra, 0x20($sp)
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addu $a1, $zero, $zero
    addiu $a2, $zero, 0x1a
    addiu $a3, $zero, -0x120
    addiu $t0, $zero, {yin:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x40
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addiu $a1, $zero, 1
    addiu $a2, $zero, 0x1b
    addiu $a3, $zero, 0x2e0
    addiu $t0, $zero, {yin:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x200
    ld $ra, 0x20($sp)
    jr $ra
    addiu $sp, $sp, 0x30
""", PM_ST_ROWNEW)
    st[PM_ST_AFTER] = opt_asm(f"""
    addiu $t2, $zero, 0x11
    bne $a0, $t2, af_out
    nop
    addiu $sp, $sp, -0x30
    sd $ra, 0x20($sp)
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addu $a1, $zero, $zero
    addiu $a2, $zero, 0x1a
    addiu $a3, $zero, -0x120
    addiu $t0, $zero, {yin:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x40
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addiu $a1, $zero, 1
    addiu $a2, $zero, 0x1b
    addiu $a3, $zero, 0x2e0
    addiu $t0, $zero, {yin:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x200
    ld $ra, 0x20($sp)
    addiu $sp, $sp, 0x30
af_out:
    j 0x338190
    nop
""", PM_ST_AFTER)
    st[PM_ST_DLAB] = opt_asm(f"""
    lui $a0, {r_hi:#x}
    addiu $a0, $a0, {sx(r_lo)}
    daddu $a1, $s2, $zero
    jal 0x302ae0
    daddu $a2, $s1, $zero
    j 0x3392bc
    nop
""", PM_ST_DLAB)
    st[PM_ST_DVAL] = opt_asm(f"""
    lui $v0, {o_hi:#x}
    lbu $v1, {sx(o_lo)}($v0)
    sltiu $t0, $v1, 4
    bnez $t0, dval_ok
    nop
    addu $v1, $zero, $zero
dval_ok:
    sll $a2, $v1, 4
    sll $v1, $v1, 2
    addu $a2, $a2, $v1
    lui $t1, {s_hi:#x}
    addiu $t1, $t1, {sx(s_lo)}
    addu $a2, $a2, $t1
    daddu $a0, $s2, $zero
    jal 0x3394c0
    daddu $a1, $s1, $zero
    j 0x3392bc
    nop
""", PM_ST_DVAL)
    st[PM_ST_IN9] = opt_asm(f"""
    lui $v0, {o_hi:#x}
    lb $a0, {sx(o_lo)}($v0)
    daddu $a2, $s1, $zero
    jal 0x3366d0
    addiu $a1, $zero, 4
    lui $v1, {o_hi:#x}
    sb $v0, {sx(o_lo)}($v1)
    j 0x3388dc
    nop
""", PM_ST_IN9)
    return st


def patch_pmlayout(b, off):
    import struct as _s
    def rd(a): return _s.unpack_from("<I", b, off(a))[0]
    def wr(a, v): _s.pack_into("<I", b, off(a), v)
    for a, orig, new in PM_PATCHES:
        assert rd(a) == orig, hex(a)
        if new is not None:
            wr(a, new)
    wr(0x33806C, 0x0C000000 | (PM_ST_ROWY >> 2))
    # INPUT row objects: created right after the pair of the DISPLAY row (counter 0x11), so that the row flies in with its neighbours
    assert rd(0x3380D0) == 0x1000002F          # b 0x338190 after a label/value pair
    wr(0x3380D0, 0x08000000 | (PM_ST_AFTER >> 2))
    # jump tables (draw: 26 + 2, input: 11 + 1)
    ents = [rd(0x404D00 + 4 * i) for i in range(26)] + [PM_ST_DLAB, PM_ST_DVAL]
    assert not any(b[off(PM_JT_DRAW):off(PM_JT_DRAW) + 4 * len(ents)])
    for i, e in enumerate(ents):
        wr(PM_JT_DRAW + 4 * i, e)
    old = [rd(0x404CA0 + 4 * i) for i in range(11)]
    ents = old[:9] + [PM_ST_IN9] + old[9:]      # idx 9 = INPUT, STAGE -> 10, SELECT BUTTON -> 11
    assert len(ents) == 12 and not any(b[off(PM_JT_IN):off(PM_JT_IN) + 4 * len(ents)])
    for i, e in enumerate(ents):
        wr(PM_JT_IN + 4 * i, e)
    for lui_a, addiu_a, lui_o, addiu_o, new in ((0x338BBC, 0x338BC0, 0x3C030040, 0x24634D00, PM_JT_DRAW),
                                               (0x338534, 0x33853C, 0x3C030040, 0x24634CA0, PM_JT_IN)):
        assert rd(lui_a) == lui_o and rd(addiu_a) == addiu_o, hex(lui_a)
        hi, lo = hi_lo(new)
        wr(lui_a, 0x3C030000 | hi)
        wr(addiu_a, 0x24630000 | lo)
    # cursor position table (in place, 16 entries)
    for i, (x, y) in enumerate(PM_ORIG_CURSOR):
        assert _s.unpack_from("<ii", b, off(PM_CURSOR_TAB + 8 * i)) == (x, y), i
    new_tab = [(416, 64)] + [(32, PM_BASE_Y + 24 * i) for i in range(1, 15)] + [(416, 456)]
    for i, (x, y) in enumerate(new_tab):
        _s.pack_into("<ii", b, off(PM_CURSOR_TAB + 8 * i), x, y)
    # DISPLAY label rect: 256 -> 128 wide; INPUT rect
    assert _s.unpack_from("<h", b, off(PM_RECT_DISPLAY))[0] == 256
    _s.pack_into("<h", b, off(PM_RECT_DISPLAY), 128)
    assert not any(b[off(PM_RECT):off(PM_RECT) + 12])
    _s.pack_into("<6h", b, off(PM_RECT), 128, 192, 128, 32, 1, 0)
    for a, code in pm_stubs().items():
        assert len(code) <= 0x100, (hex(a), len(code))
        assert not any(b[off(a):off(a) + len(code)]), hex(a)
        b[off(a):off(a) + len(code)] = code
    assert off(PM_STR_INPUT + 0x50) <= ELF_OFF + ELF_FILESZ and not any(b[off(PM_STR_INPUT):off(PM_STR_INPUT) + 0x50])
    for i, sname in enumerate(PM_INPUT_STRINGS):
        b[off(PM_STR_INPUT + 0x14 * i):off(PM_STR_INPUT + 0x14 * i) + len(sname)] = sname.encode("ascii")


# ---- practice INPUT display (history list of pad states, newest on top, 1P left edge / 2P right edge) ----
# Called from the HUD wrapper (HitCombo task, one task per side, runs every frame while the game is not paused: the scheduler skips
# tasks while cRam009e9738 != 0) with a0 = side.  Only active in practice mode (0x9E9780 == 8) with the practice flag set.
# State per side (IN_DATA + side * 0x100): +0 head, +8 inited, +0x10 16 ring entries (u32 = count << 16 | pad state), pad state = held
# word & 0xF8F0 (dirs 0x10 up 0x20 right 0x40 down 0x80 left; Square 0x8000 = A, Cross 0x4000 = B, Triangle 0x1000 = C,
# Circle 0x2000 = D, R1 0x0800 = E).  Drawing: menu sprite queue FUN_00302ea0 (flushed every frame by FUN_00303440), atlas = SPR03
# (resident after GAME START: FUN_00301ae0(0,7)), page 1: 16x16 icons at v=128 (u = 16 * idx: 0-7 arrows U UR R DR D DL L UL,
# 8 SP 9 LP 10 SK 11 LK 12 PR 13 BO 14 + 15 N), grey 16x16 font at v=0x180 (digits: v=0x190, u = 16 * digit).
IN_CODE = 0x3AE000
IN_DATA = 0x3AE800
IN_SPR = IN_CODE + 0x780        # sprite enqueue helper (assembled separately: keystone turns `jal label` into a PIC jalr here)
IN_DIRTAB = IN_DATA + 0x200     # 9 bytes: icon idx for (dy + 1) * 3 + (dx + 1)
IN_BTNTAB = IN_DATA + 0x210     # 5 x (u16 mask, u16 icon idx)
IN_DIR_ICONS = bytes([5, 4, 3, 6, 15, 2, 7, 0, 1])
# state = dirs (0xF0) | logical buttons << 8 (LP 1, LK 2, SP 4, SK 8, BO 0x10, PR 0x20), resolved through the KEY SETTING assignment
# (8 bytes per side at 0x9CB250 + side * 9: Square, Cross, Triangle, Circle, R1, L1, R2, L2; value -> button mask in IN_VALMASK)
IN_BUTTONS = ((0x100, 9), (0x200, 11), (0x400, 8), (0x800, 10), (0x1000, 13), (0x2000, 12))
IN_VALTAB = IN_DATA + 0x230
IN_PADTAB = IN_DATA + 0x240
IN_VALMASK = bytes([0, 1, 2, 4, 8, 0x20, 0x10, 3, 5, 0xA, 0x1C, 0x14, 0])   # none LP LK SP SK PR BO LP+LK LP+SP LK+SK SP+SK+BO SP+BO COMMAND
IN_PADBITS = (0x8000, 0x4000, 0x1000, 0x2000, 0x0800, 0x0400, 0x0200, 0x0100)
IN_CFG = 0x9CB250
IN_PAD = 0x9BEA20               # held word side 0, side 1 = +0xC
IN_ROWS = 20
IN_Y0 = 76
IN_QUEUE_LIMIT = 0xB8           # the sprite queue holds 0xB9 entries
IN_SPR_FLAGS = -0x57CD          # 0xA833 as used by all menu text sprites


def input_module():
    d_hi, d_lo = hi_lo(IN_DATA)
    f_hi, f_lo = hi_lo(DATA + 0x7C)
    m_hi, m_lo = hi_lo(MODE_ADDR)
    p_hi, p_lo = hi_lo(IN_PAD)
    o_hi, o_lo = hi_lo(PM_INPUT_ADDR)
    b_hi, b_lo = hi_lo(IN_BTNTAB)
    t_hi, t_lo = hi_lo(IN_DIRTAB)
    c_hi, c_lo = hi_lo(IN_CFG)
    vt_hi, vt_lo = hi_lo(IN_VALTAB)
    pt_hi, pt_lo = hi_lo(IN_PADTAB)
    q_hi, q_lo = hi_lo(0x1CB0C68)
    a_hi, a_lo = hi_lo(0x1CB0C73)     # tracker of the sprite set in the shared atlas buffer (7 = SPR03)
    src = f"""
input_mod:
    addiu $sp, $sp, -0x90
    sd $ra, 0x88($sp)
    sd $s0, 0x80($sp)
    sd $s1, 0x78($sp)
    sd $s2, 0x70($sp)
    sd $s3, 0x68($sp)
    sd $s4, 0x60($sp)
    sd $s5, 0x58($sp)
    sd $s6, 0x50($sp)
    sd $s7, 0x48($sp)
    daddu $s7, $a0, $zero
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, im_out
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t2, $zero, 8
    bne $t1, $t2, im_out
    nop
    lui $s0, {d_hi:#x}
    addiu $s0, $s0, {sx(d_lo)}
    sll $t0, $s7, 8
    addu $s0, $s0, $t0
    lui $t0, {p_hi:#x}
    addiu $t0, $t0, {sx(p_lo)}
    sll $t1, $s7, 3
    sll $t2, $s7, 2
    addu $t1, $t1, $t2
    addu $t0, $t0, $t1
    lhu $s1, 0($t0)
    daddu $t6, $s1, $zero
    andi $s1, $s1, 0xF0
    lui $t7, {c_hi:#x}
    addiu $t7, $t7, {sx(c_lo)}
    sll $t8, $s7, 3
    addu $t8, $t8, $s7
    addu $t7, $t7, $t8
    lui $t9, {vt_hi:#x}
    addiu $t9, $t9, {sx(vt_lo)}
    lui $t3, {pt_hi:#x}
    addiu $t3, $t3, {sx(pt_lo)}
    addu $t4, $zero, $zero
im_k:
    sltiu $t0, $t4, 8
    beqz $t0, im_kd
    nop
    sll $t0, $t4, 1
    addu $t0, $t0, $t3
    lhu $t1, 0($t0)
    and $t1, $t1, $t6
    beqz $t1, im_kn
    nop
    addu $t0, $t7, $t4
    lbu $t1, 0($t0)
    sltiu $t2, $t1, 13
    beqz $t2, im_kn
    nop
    addu $t0, $t9, $t1
    lbu $t1, 0($t0)
    sll $t1, $t1, 8
    or $s1, $s1, $t1
im_kn:
    addiu $t4, $t4, 1
    b im_k
    nop
im_kd:
    lw $t0, 8($s0)
    bnez $t0, im_have
    nop
    addiu $t0, $zero, 1
    sw $t0, 8($s0)
    sw $zero, 0($s0)
    lui $t1, 1
    or $t1, $t1, $s1
    sw $t1, 0x10($s0)
    b im_draw
    nop
im_have:
    lw $s2, 0($s0)
    sll $t0, $s2, 2
    addu $t0, $t0, $s0
    lw $t1, 0x10($t0)
    andi $t2, $t1, 0xFFFF
    bne $t2, $s1, im_new
    nop
    srl $t3, $t1, 16
    sltiu $t4, $t3, 999
    beqz $t4, im_wrap
    nop
    lui $t5, 1
    addu $t1, $t1, $t5
    sw $t1, 0x10($t0)
    b im_draw
    nop
im_wrap:
    andi $t1, $t1, 0xFFFF
    lui $t5, 1
    or $t1, $t1, $t5
    sw $t1, 0x10($t0)
    b im_draw
    nop
im_new:
    addiu $s2, $s2, 1
    andi $s2, $s2, 31
    sw $s2, 0($s0)
    sll $t0, $s2, 2
    addu $t0, $t0, $s0
    lui $t1, 1
    or $t1, $t1, $s1
    sw $t1, 0x10($t0)
im_draw:
    lui $t0, {o_hi:#x}
    lbu $t1, {sx(o_lo)}($t0)
    addiu $t2, $zero, 3
    beq $t1, $t2, im_en
    nop
    addiu $t2, $s7, 1
    bne $t1, $t2, im_out
    nop
im_en:
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    addiu $t2, $zero, 7
    beq $t1, $t2, im_atlas
    nop
    addu $a0, $zero, $zero
    jal 0x301ae0
    addiu $a1, $zero, 7
im_atlas:
    bnez $s7, im_right
    nop
    addiu $s3, $zero, 4
    addiu $s4, $zero, 54
    addiu $s5, $zero, 72
    addiu $s6, $zero, 16
    b im_rows
    nop
im_right:
    addiu $s3, $zero, 588
    addiu $s4, $zero, 568
    addiu $s5, $zero, 550
    addiu $s6, $zero, -16
im_rows:
    sw $zero, 0x10($sp)
im_row:
    lw $t0, 0x10($sp)
    sltiu $t1, $t0, {IN_ROWS}
    beqz $t1, im_out
    nop
    lw $t1, 0($s0)
    subu $t1, $t1, $t0
    andi $t1, $t1, 31
    sll $t1, $t1, 2
    addu $t1, $t1, $s0
    lw $s2, 0x10($t1)
    srl $t2, $s2, 16
    beqz $t2, im_out
    nop
    sll $t3, $t0, 4
    addiu $s1, $t3, {IN_Y0}
    sltiu $t4, $t2, 1000
    bnez $t4, im_capok
    nop
    addiu $t2, $zero, 999
im_capok:
    addu $t7, $zero, $zero
im_h:
    sltiu $t4, $t2, 100
    bnez $t4, im_hd
    nop
    addiu $t2, $t2, -100
    addiu $t7, $t7, 1
    b im_h
    nop
im_hd:
    addu $t8, $zero, $zero
im_t:
    sltiu $t4, $t2, 10
    bnez $t4, im_td
    nop
    addiu $t2, $t2, -10
    addiu $t8, $t8, 1
    b im_t
    nop
im_td:
    sw $t7, 0x14($sp)
    sw $t8, 0x18($sp)
    sw $t2, 0x1c($sp)
    sw $zero, 0x28($sp)
im_d:
    lw $t0, 0x28($sp)
    sltiu $t1, $t0, 3
    beqz $t1, im_dd
    nop
    sll $t1, $t0, 2
    addu $t1, $t1, $sp
    lw $t1, 0x14($t1)
    or $t6, $t0, $t1
    beqz $t6, im_dskip
    nop
    addiu $t7, $zero, 1
    bne $t0, $t7, im_notens
    nop
    bnez $t1, im_notens
    nop
    lw $t7, 0x14($sp)
    beqz $t7, im_dskip
    nop
im_notens:
    sll $t1, $t1, 4
    sll $t3, $t0, 4
    addu $a0, $s3, $t3
    daddu $a1, $s1, $zero
    addiu $t2, $zero, 0x190
    jal {IN_SPR:#x}
    nop
im_dskip:
    lw $t0, 0x28($sp)
    addiu $t0, $t0, 1
    sw $t0, 0x28($sp)
    b im_d
    nop
im_dd:
    andi $t5, $s2, 0xFFFF
    andi $t0, $t5, 0x20
    sltu $t0, $zero, $t0
    andi $t1, $t5, 0x80
    sltu $t1, $zero, $t1
    subu $t0, $t0, $t1
    addiu $t0, $t0, 1
    andi $t1, $t5, 0x10
    sltu $t1, $zero, $t1
    andi $t2, $t5, 0x40
    sltu $t2, $zero, $t2
    subu $t1, $t1, $t2
    addiu $t1, $t1, 1
    sll $t2, $t1, 1
    addu $t1, $t1, $t2
    addu $t1, $t1, $t0
    lui $t2, {t_hi:#x}
    addiu $t2, $t2, {sx(t_lo)}
    addu $t2, $t2, $t1
    lbu $t1, 0($t2)
    sll $t1, $t1, 4
    daddu $a0, $s4, $zero
    daddu $a1, $s1, $zero
    addiu $t2, $zero, 128
    jal {IN_SPR:#x}
    nop
    sw $s5, 0x20($sp)
    sw $zero, 0x24($sp)
im_b:
    lw $t0, 0x24($sp)
    sltiu $t1, $t0, 6
    beqz $t1, im_bd
    nop
    sll $t1, $t0, 2
    lui $t2, {b_hi:#x}
    addiu $t2, $t2, {sx(b_lo)}
    addu $t2, $t2, $t1
    lhu $t3, 0($t2)
    lhu $t4, 2($t2)
    andi $t5, $s2, 0xFFFF
    and $t3, $t3, $t5
    beqz $t3, im_bn
    nop
    lw $a0, 0x20($sp)
    daddu $a1, $s1, $zero
    sll $t1, $t4, 4
    addiu $t2, $zero, 128
    jal {IN_SPR:#x}
    nop
    lw $t0, 0x20($sp)
    addu $t0, $t0, $s6
    sw $t0, 0x20($sp)
im_bn:
    lw $t0, 0x24($sp)
    addiu $t0, $t0, 1
    sw $t0, 0x24($sp)
    b im_b
    nop
im_bd:
    lw $t0, 0x10($sp)
    addiu $t0, $t0, 1
    sw $t0, 0x10($sp)
    b im_row
    nop
im_out:
    ld $ra, 0x88($sp)
    ld $s0, 0x80($sp)
    ld $s1, 0x78($sp)
    ld $s2, 0x70($sp)
    ld $s3, 0x68($sp)
    ld $s4, 0x60($sp)
    ld $s5, 0x58($sp)
    ld $s6, 0x50($sp)
    ld $s7, 0x48($sp)
    jr $ra
    addiu $sp, $sp, 0x90
im_spr:
    addiu $sp, $sp, -0x30
    sd $ra, 0x28($sp)
    lui $t9, {q_hi:#x}
    lw $t8, {sx(q_lo)}($t9)
    sltiu $t8, $t8, {IN_QUEUE_LIMIT:#x}
    beqz $t8, im_sprout
    nop
    addiu $a2, $zero, {IN_SPR_FLAGS}
    addiu $a3, $zero, 16
    addiu $t0, $zero, 16
    addiu $t3, $zero, 16
    addiu $v0, $zero, 16
    sd $v0, 0($sp)
    addiu $v0, $zero, 0xFF
    sd $v0, 8($sp)
    sd $zero, 0x10($sp)
    addiu $v0, $zero, 1
    sd $v0, 0x18($sp)
    jal 0x302ea0
    nop
im_sprout:
    ld $ra, 0x28($sp)
    jr $ra
    addiu $sp, $sp, 0x30
"""
    main_src, spr_src = src.split("im_spr:" + chr(10))
    c1 = opt_asm(main_src, IN_CODE)
    c2 = opt_asm(spr_src, IN_SPR)
    assert len(c1) <= IN_SPR - IN_CODE, len(c1)
    return c1 + bytes(IN_SPR - IN_CODE - len(c1)) + c2


def patch_input(b, off):
    code = input_module()
    assert len(code) <= 0x7F0, len(code)
    assert off(IN_DATA + 0x250) <= ELF_OFF + ELF_FILESZ
    for a, n in ((IN_CODE, len(code)), (IN_DATA, 0x250)):
        assert not any(b[off(a):off(a) + n]), f"input module region {a:#x} not zero"
    b[off(IN_CODE):off(IN_CODE) + len(code)] = code
    b[off(IN_DIRTAB):off(IN_DIRTAB) + 9] = IN_DIR_ICONS
    b[off(IN_VALTAB):off(IN_VALTAB) + len(IN_VALMASK)] = IN_VALMASK
    for i, m in enumerate(IN_PADBITS):
        struct.pack_into("<H", b, off(IN_PADTAB + 2 * i), m)
    for i, (mask, idx) in enumerate(IN_BUTTONS):
        struct.pack_into("<HH", b, off(IN_BTNTAB + 4 * i), mask, idx)
    return len(code)


# ---- KEY SETTING: new button function 13 "COMMAND ENEMY" (practice mode) ----
# Plays the COMMAND recording (practice > COMMAND) of the OTHER side on that side, so a single pad is enough to test
# against a moving dummy.  Value 13 is stored in the normal key assignment bytes (0x9CB250 + side * 9 + button), the
# vanilla code ignores values >= 13 (bound checks `< 0xD`), so saves stay compatible.
#  * KEY SETTING menu: value cycle length 0xD -> 0xE (two input handlers, `addiu a1, zero, 0xD` before jal FUN_003366D0)
#  * value draw (FUN_00332F20, `jal 0x302AE0` at 0x333048): value 13 draws the vanilla COMMAND rect + a new ENEMY rect (SPR02.GRC p1)
#  * trigger: hook at the `jal FUN_001A3420` (pad press-edge word) inside FUN_001A28B0 (pad -> game buttons, called per side per
#    frame).  If a button of side S with assignment 13 is pressed, the playback entry of side S^1 (0x9E8AF0 + side * 0xC:
#    type 3, position 0, data pointer = command record of that side's active character) is started, exactly like the vanilla
#    `attack: COMMAND` dummy does (FUN_0033B1A0 caller).  Only in practice mode (mode 8) with the practice hack flag, not while
#    paused or in the command editor (0x9E95C0 == 9).
CE_CODE = 0x3AF000
CE_DRAW = 0x3AF200
CE_RECT = 0x3AF300              # (u, v, w, h, 1, 0) of the ENEMY word (atlas SPR02.GRC page 1)
CE_RECT_UVWH = (190, 64, 66, 32)
CE_LOGIC_SITE = (0x1A29AC, 0x0C068D08)   # jal 0x1a3420
CE_DRAW_SITE = (0x333048, 0x0C0C0AB8)    # jal 0x302ae0 (value sprite of a KEY SETTING row)
QK_RECT1 = 0x3AF310             # QUICK RESET word (two rects: QUICK, RESET) on the same atlas page
QK_RECT2 = 0x3AF320
QK_UVWH1 = (192, 352, 64, 32)
QK_UVWH2 = (192, 384, 64, 32)
QK_VALUE = 14                    # KEY SETTING value 14: QUICK RESET
QK_DX = 58
QRC = 0x3AF540                  # quick reset core (a0 = side); the select-handler entry stub sits at QR = 0x3AF500
CE_CYCLE_SITES = (0x332D38, 0x3336A0)    # addiu $a1, $zero, 0xd  (delay slot of jal 0x3366d0)
CE_VALUE = 13
CE_CMD_RECT = 0x3D1EF0 + 12 * 12         # vanilla COMMAND value rect
CE_DX = 100                              # x offset of the ENEMY rect from the COMMAND rect
CE_TEAM_STRIDE = 0x248
CE_REC_SIDE = 0xE612                     # 49 records * 0x4B2 per side (command data at 0x9CB290)
CE_REC_SIZE = 0x4B2


def cmd_enemy_code():
    f_hi, f_lo = hi_lo(PRACTICE_FLAG)
    m_hi, m_lo = hi_lo(MODE_ADDR)
    ps_hi, ps_lo = hi_lo(0x9E9738)          # paused
    ed_hi, ed_lo = hi_lo(0x9E95C0)          # 9 = command editor
    a_hi, a_lo = hi_lo(0x9E9478)
    b_hi, b_lo = hi_lo(0x9BD590)
    c_hi, c_lo = hi_lo(0x9BD9D0)
    g_hi, g_lo = hi_lo(0x1D4D918)
    cf_hi, cf_lo = hi_lo(IN_CFG)
    pt_hi, pt_lo = hi_lo(0x3663F0)          # 8 pad bit masks
    tm_hi, tm_lo = hi_lo(TEAM0)
    en_hi, en_lo = hi_lo(0x9E8AF0)          # playback entries (side * 0xC)
    rc_hi, rc_lo = hi_lo(0x9CB290)          # command records
    cm_hi, cm_lo = hi_lo(CE_CMD_RECT)
    rt_hi, rt_lo = hi_lo(CE_RECT)
    logic = f"""
    addiu $sp, $sp, -0x30
    sd $ra, 0x28($sp)
    sd $s0, 0x20($sp)
    sd $s1, 0x18($sp)
    sd $s2, 0x10($sp)
    daddu $s0, $a0, $zero
    jal 0x1a3420
    nop
    daddu $s1, $v0, $zero
    andi $t0, $s1, 0xFFFF
    beqz $t0, ce_out
    nop
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, ce_out
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t2, $zero, 8
    bne $t1, $t2, ce_out
    nop
    lui $t0, {ps_hi:#x}
    lbu $t1, {sx(ps_lo)}($t0)
    bnez $t1, ce_out
    nop
    lui $t0, {ed_hi:#x}
    lbu $t1, {sx(ed_lo)}($t0)
    addiu $t2, $zero, 9
    beq $t1, $t2, ce_out
    nop
    lui $t0, {a_hi:#x}
    lw $t1, {sx(a_lo)}($t0)
    lui $t2, 0xFF00
    and $t1, $t1, $t2
    bnez $t1, ce_out
    nop
    lui $t0, {b_hi:#x}
    lw $t1, {sx(b_lo)}($t0)
    bnez $t1, ce_out
    nop
    lui $t0, {c_hi:#x}
    lbu $t1, {sx(c_lo)}($t0)
    addiu $t2, $zero, 0xFF
    beq $t1, $t2, ce_out
    nop
    lui $t0, {g_hi:#x}
    lw $t1, {sx(g_lo)}($t0)
    andi $t2, $t1, 4
    beqz $t2, ce_out
    nop
    lui $t3, 2
    ori $t3, $t3, 0x100
    and $t2, $t1, $t3
    bnez $t2, ce_out
    nop
    sll $t0, $s0, 3
    addu $t0, $t0, $s0
    lui $s2, {cf_hi:#x}
    addiu $s2, $s2, {sx(cf_lo)}
    addu $s2, $s2, $t0
    lui $t8, {pt_hi:#x}
    addiu $t8, $t8, {sx(pt_lo)}
    addu $t7, $zero, $zero
ce_loop:
    sll $t0, $t7, 1
    addu $t0, $t8, $t0
    lhu $t0, 0($t0)
    and $t0, $t0, $s1
    beqz $t0, ce_next
    nop
    addu $t1, $s2, $t7
    lbu $t1, 0($t1)
    addiu $t2, $zero, {QK_VALUE}
    bne $t1, $t2, ce_not14
    nop
    addu $a0, $s0, $zero
    jal {QRC:#x}
    nop
    b ce_out
    nop
ce_not14:
    addiu $t2, $zero, {CE_VALUE}
    bne $t1, $t2, ce_next
    nop
    xori $t3, $s0, 1
    subu $t4, $zero, $t3
    andi $t4, $t4, {CE_TEAM_STRIDE:#x}
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addu $t9, $t9, $t4
    lbu $a0, 3($t9)
    sll $a0, $a0, 5
    addu $a0, $a0, $t9
    lbu $a0, 0x14D($a0)
    sll $a1, $t3, 3
    sll $a2, $t3, 2
    addu $a1, $a1, $a2
    lui $a2, {en_hi:#x}
    addiu $a2, $a2, {sx(en_lo)}
    addu $a1, $a1, $a2
    addiu $a2, $zero, 3
    sb $a2, 0($a1)
    sh $zero, 2($a1)
    subu $a2, $zero, $t3
    andi $a2, $a2, {CE_REC_SIDE:#x}
    addiu $v1, $zero, {CE_REC_SIZE:#x}
    mult $a0, $v1
    mflo $v1
    addu $a2, $a2, $v1
    lui $v1, {rc_hi:#x}
    addiu $v1, $v1, {sx(rc_lo)}
    addu $a2, $a2, $v1
    sw $a2, 4($a1)
    b ce_out
    nop
ce_next:
    addiu $t7, $t7, 1
    sltiu $t0, $t7, 8
    bnez $t0, ce_loop
    nop
ce_out:
    daddu $v0, $s1, $zero
    ld $ra, 0x28($sp)
    ld $s0, 0x20($sp)
    ld $s1, 0x18($sp)
    ld $s2, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x30
"""
    q1_hi, q1_lo = hi_lo(QK_RECT1)
    q2_hi, q2_lo = hi_lo(QK_RECT2)
    draw = f"""
    addiu $t0, $zero, {QK_VALUE}
    beq $v1, $t0, cd_qk
    nop
    addiu $t0, $zero, {CE_VALUE}
    bne $v1, $t0, cd_orig
    nop
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a1, 0x10($sp)
    sd $a2, 8($sp)
    lui $a0, {cm_hi:#x}
    addiu $a0, $a0, {sx(cm_lo)}
    jal 0x302ae0
    nop
    lui $a0, {rt_hi:#x}
    addiu $a0, $a0, {sx(rt_lo)}
    ld $a1, 0x10($sp)
    addiu $a1, $a1, {CE_DX}
    ld $a2, 8($sp)
    jal 0x302ae0
    nop
    ld $ra, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
cd_qk:
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a1, 0x10($sp)
    sd $a2, 8($sp)
    lui $a0, {q1_hi:#x}
    addiu $a0, $a0, {sx(q1_lo)}
    jal 0x302ae0
    nop
    lui $a0, {q2_hi:#x}
    addiu $a0, $a0, {sx(q2_lo)}
    ld $a1, 0x10($sp)
    addiu $a1, $a1, {QK_DX}
    ld $a2, 8($sp)
    jal 0x302ae0
    nop
    ld $ra, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
cd_orig:
    j 0x302ae0
    nop
"""
    return opt_asm(logic, CE_CODE), opt_asm(draw, CE_DRAW)


def patch_cmdenemy(b, off):
    logic, draw = cmd_enemy_code()
    assert len(logic) <= CE_DRAW - CE_CODE, len(logic)
    assert len(draw) <= CE_RECT - CE_DRAW, len(draw)
    for a, n in ((CE_CODE, len(logic)), (CE_DRAW, len(draw)), (CE_RECT, 12), (QK_RECT1, 12), (QK_RECT2, 12)):
        assert off(a + n) <= ELF_OFF + ELF_FILESZ
        assert not any(b[off(a):off(a) + n]), f"command enemy region {a:#x} not zero"
    b[off(CE_CODE):off(CE_CODE) + len(logic)] = logic
    b[off(CE_DRAW):off(CE_DRAW) + len(draw)] = draw
    struct.pack_into("<6h", b, off(CE_RECT), *CE_RECT_UVWH, 1, 0)
    struct.pack_into("<6h", b, off(QK_RECT1), *QK_UVWH1, 1, 0)
    struct.pack_into("<6h", b, off(QK_RECT2), *QK_UVWH2, 1, 0)
    for (site, orig), stub in ((CE_LOGIC_SITE, CE_CODE), (CE_DRAW_SITE, CE_DRAW)):
        assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
        struct.pack_into("<I", b, off(site), 0x0C000000 | (stub >> 2))
    for site in CE_CYCLE_SITES:
        assert struct.unpack_from("<I", b, off(site))[0] == 0x2405000D, hex(site)
        struct.pack_into("<I", b, off(site), 0x2405000F)      # values 0..14
    return len(logic), len(draw)


# ---- practice menu: Triangle on COMMAND (CONTROL: PLAYER) opens the command editor of the OTHER side ----
# The editor edits side 0x9E9730 and reads the pad of the same port, so the other side normally needs a second controller.  Vanilla
# CONTROL "both human" (0x9CB240 == 1) already has the editor path for the 2P side (types of both chars set to human by FUN_0033A790,
# side = 1P pad did not press).  The hack reuses it:
#  * gate (`jal 0x3369A0` at 0x338960, "confirm pressed" of the practice menu): if confirm is not pressed, CONTROL is 0 (shown CPU) or 1 (PLAYER), the cursor is on
#    COMMAND (12) and Triangle (0x1000) is pressed (CONTROL 0: owner pad; 1: either pad, the presser's side is stored in WHO) -> REQ = 1 and the gate returns "pressed";
#  * hook1 (`lui/lbu` that reads 0x9CB240 at 0x338AD4): with REQ, session start: ACTIVE = 1, human mask 0x9BDB10 |= 3 (saved), CONTROL := 1, so the
#    vanilla cb240 == 1 branch runs (types, uRam01dde880 = 1);
#  * stub2 (`jal 0x3369A0` at 0x338AE4): during a session the edited side = owner ^ 1 (return value is the owner id);
#  * poll wrapper (the 5 `jal 0x1A21D0` pad pollers): the two port blocks 0x9BEA20 / 0x9BEA2C (12 bytes each) are swapped after every poll while ACTIVE
#    (un-swapped before the next poll so the edge detection stays consistent), so the owner's pad is the port of the edited side;
#  * session end: the first poll with 0x9E95C0 != 9 restores CONTROL := 0 and the human mask.
CX_GATE, CX_HOOK1, CX_STUB2, CX_WRAP, CX_SWAP, CX_END = 0x3B0000, 0x3B0100, 0x3B0200, 0x3B1C00, 0x3B0400, 0x3B0500
CX_REQ, CX_ACTIVE, CX_SWAPPED, CX_MASK = DATA + 0xE0, DATA + 0xE1, DATA + 0xE2, DATA + 0xE3
CX_WHO, CX_CB = DATA + 0xE4, DATA + 0xE5   # pressing side (the other one is edited), CONTROL value before the session
CX_CMD_ROW = 12
# 2P Start in practice: FUN_00154AB0 (Start -> pause, called from FUN_0031F390 at 0x31F3C8) only pauses for sides in the human mask 0x9BDB10; in
# practice only the starter is in it, 2P Start ran the join logic instead.  Wrapper CX_START: in practice mode (8 + flag) the mask is 3 during the call.
CX_START = 0x3B0600
CX_START_SITE = (0x31F3C8, 0x0C000000 | (0x154AB0 >> 2))
# FUN_003054D0 (open the pause menu), practice branch: `if (FUN_001A3420(owner, 0) == 0 && iRam01D11D40 != 0) paused = 0` cancels the pause when the OWNER
# pad has no new button, i.e. every 2P Start (found with PINE: FUN_001745F0(1) returned 5, paused flag went back to 0 at once).  a0 := 2 = both pads.
CX_OWNER_SITE = (0x3055A4, 0x90449748, 0x24040002)   # lbu a0,-0x68b8(v0) -> addiu a0,zero,2
# Practice menu (FUN_003383D0) read Start (resume, `FUN_001A3420(owner,0,8)`) and the GAME START confirm (`FUN_00336A10(0x2000, owner+1)`) from the owner pad
# only, so a menu opened by 2P could not be left by 2P.  Both now accept either pad (a0 = 2 / port mask 3).
CX_MENU_SITES = ((0x338444, 0x90449748, 0x24040002), (0x3388F8, 0x24420001, 0x24020003),
                 (0x33841C, 0x90449748, 0x24040002), (0x338434, 0x24420001, 0x24020003),    # navigation with CONTROL != 1 (pad + port mask)
                 (0x339AD0, 0x90449748, 0x24040002), (0x339C20, 0x90449748, 0x24040002))    # the two sub-screens (FUN_00339A90 / FUN_00339BE0)
CX_GATE_SITE = (0x338960, 0x0C0CDA68)       # jal 0x3369a0
CX_HOOK_SITE = (0x338AD4, 0x3C02009D, 0x9043B240)   # lui v0,0x9d ; lbu v1,-0x4dc0(v0)
CX_STUB2_SITE = (0x338AE4, 0x0C0CDA68)
CX_POLL_SITES = (0x1A1910, 0x1A1970, 0x1A2D08, 0x1A2D24, 0x1A2D74)   # jal 0x1a21d0
CX_POLL_ORIG = 0x0C068874


def cmdedit_code():
    r_hi, r_lo = hi_lo(CX_REQ)
    ed_hi, ed_lo = hi_lo(0x9E95C0)
    ow_hi, ow_lo = hi_lo(0x9E9748)
    cu_hi, cu_lo = hi_lo(0x1DDE8F0)
    c0_hi, c0_lo = hi_lo(0x9CB240)
    mk_hi, mk_lo = hi_lo(0x9BDB10)
    pf_hi, pf_lo = hi_lo(PRACTICE_FLAG)
    d = {}
    d[CX_GATE] = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a1, 0x10($sp)
    sd $s0, 0x8($sp)
    lui $t0, {r_hi:#x}
    sb $zero, {sx(r_lo)}($t0)
    jal 0x3369a0
    nop
    bnez $v0, g_out
    nop
    lui $t0, {cu_hi:#x}
    lw $t1, {sx(cu_lo)}($t0)
    addiu $t2, $zero, {CX_CMD_ROW}
    bne $t1, $t2, g_out
    nop
    lui $t0, {c0_hi:#x}
    lbu $s0, {sx(c0_lo)}($t0)
    addiu $t1, $zero, 1
    bne $s0, $t1, g_out
    nop
    lui $t0, {pf_hi:#x}
    lw $t1, {sx(pf_lo)}($t0)
    beqz $t1, g_out
    nop
g_both:
    addiu $a0, $zero, 0x1000
    addiu $a1, $zero, 1
    jal 0x3369a0
    nop
    bnez $v0, g_p0
    nop
    addiu $a0, $zero, 0x1000
    addiu $a1, $zero, 2
    jal 0x3369a0
    nop
    beqz $v0, g_out
    nop
    addiu $t1, $zero, 1
    b g_set
    nop
g_p0:
    addu $t1, $zero, $zero
g_set:
    lui $t0, {r_hi:#x}
    sb $t1, {sx(hi_lo(CX_WHO)[1])}($t0)
    lui $t0, {r_hi:#x}
    addiu $t1, $zero, 1
    sb $t1, {sx(r_lo)}($t0)
    addiu $v0, $zero, 1
g_out:
    ld $s0, 0x8($sp)
    ld $ra, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
"""
    d[CX_HOOK1] = f"""
    lui $t0, {c0_hi:#x}
    lbu $v1, {sx(c0_lo)}($t0)
    lui $t1, {r_hi:#x}
    lbu $t2, {sx(r_lo)}($t1)
    beqz $t2, h_out
    nop
    sb $zero, {sx(r_lo)}($t1)
    addiu $t2, $zero, 1
    sb $t2, {sx(hi_lo(CX_ACTIVE)[1])}($t1)
    sb $zero, {sx(hi_lo(CX_SWAPPED)[1])}($t1)
    lui $t3, {mk_hi:#x}
    lbu $t4, {sx(mk_lo)}($t3)
    sb $t4, {sx(hi_lo(CX_MASK)[1])}($t1)
    ori $t4, $t4, 3
    sb $t4, {sx(mk_lo)}($t3)
    sb $v1, {sx(hi_lo(CX_CB)[1])}($t1)
    sb $t2, {sx(c0_lo)}($t0)
    addiu $v1, $zero, 1
h_out:
    jr $ra
    nop
"""
    d[CX_STUB2] = f"""
    lui $t0, {r_hi:#x}
    lbu $t1, {sx(hi_lo(CX_ACTIVE)[1])}($t0)
    beqz $t1, s_orig
    nop
    lbu $v0, {sx(hi_lo(CX_WHO)[1])}($t0)
    jr $ra
    nop
s_orig:
    j 0x3369a0
    nop
"""
    d[CX_WRAP] = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    lui $t0, 0x9d
    lbu $t1, -0x4dbc($t0)
    lui $t2, {r_hi:#x}
    lbu $t3, {sx(hi_lo(GA_ALL)[1])}($t2)
    addiu $t4, $zero, 1
    bne $t1, $t4, gm_set
    nop
    beqz $t3, gm_set
    nop
    addiu $t1, $t3, 7
gm_set:
    sb $t1, {sx(hi_lo(GA_MODE)[1])}($t2)
    lw $t5, {sx(hi_lo(GA_RNG)[1])}($t2)
    bnez $t5, rng_ok
    nop
    lui $t5, 0x9e37
    ori $t5, $t5, 0x79b1
rng_ok:
    sll $t6, $t5, 13
    xor $t5, $t5, $t6
    srl $t6, $t5, 17
    xor $t5, $t5, $t6
    sll $t6, $t5, 5
    xor $t5, $t5, $t6
    sw $t5, {sx(hi_lo(GA_RNG)[1])}($t2)
    lw $t5, {sx(hi_lo(GA_TICK)[1])}($t2)
    addiu $t5, $t5, 1
    sw $t5, {sx(hi_lo(GA_TICK)[1])}($t2)
    lui $t0, 0x9f
    lbu $t1, -0x68b8($t0)
    sltiu $t8, $t1, 2
    beqz $t8, wk_done
    nop
    sll $t3, $t1, 9
    sll $t4, $t1, 6
    addu $t3, $t3, $t4
    sll $t4, $t1, 3
    addu $t3, $t3, $t4
    addu $t8, $t3, $zero
    lui $t4, {TEAM0_HI:#x}
    addiu $t4, $t4, {sx(TEAM0_LO)}
    addu $t4, $t4, $t3
    lbu $t5, 3($t4)
    sll $t5, $t5, 2
    addu $t6, $t4, $t5
    lw $t6, 0x78($t6)
    beqz $t6, wk_done
    nop
    lw $t6, 0x10($t6)
    beqz $t6, wk_done
    nop
    lw $t7, 0x490($t6)
    andi $t7, $t7, 1
    lbu $t5, {sx(hi_lo(GA_PREV)[1])}($t2)
    sb $t7, {sx(hi_lo(GA_PREV)[1])}($t2)
    beqz $t5, wk_chk
    nop
    bnez $t7, wk_chk
    nop
    addiu $t5, $zero, 1
    sb $t5, {sx(hi_lo(GA_PEND)[1])}($t2)
wk_chk:
    lbu $t5, {sx(hi_lo(GA_PEND)[1])}($t2)
    beqz $t5, wk_done
    nop
    addiu $t3, $zero, 0x248
    subu $t3, $t3, $t8
    lui $t4, {TEAM0_HI:#x}
    addiu $t4, $t4, {sx(TEAM0_LO)}
    addu $t4, $t4, $t3
    lbu $t5, 3($t4)
    sll $t5, $t5, 2
    addu $t6, $t4, $t5
    lw $t6, 0x78($t6)
    beqz $t6, wk_done
    nop
    lw $t6, 0x10($t6)
    beqz $t6, wk_done
    nop
    lw $t7, 0x530($t6)
    andi $t7, $t7, 0x400
    bnez $t7, wk_done
    nop
    lhu $t7, 0xec($t6)
    beqz $t7, wk_roll
    nop
    addiu $t5, $zero, 5
    bne $t7, $t5, wk_done
    nop
wk_roll:
    lw $t4, {sx(hi_lo(GA_RNG)[1])}($t2)
    srl $t4, $t4, 16
    andi $t4, $t4, 1
    sb $t4, {sx(hi_lo(GA_BLK)[1])}($t2)
    sb $zero, {sx(hi_lo(GA_PEND)[1])}($t2)
wk_done:
    lui $t0, {r_hi:#x}
    lbu $t1, {sx(hi_lo(CX_SWAPPED)[1])}($t0)
    beqz $t1, w1
    nop
    jal {CX_SWAP:#x}
    nop
    lui $t0, {r_hi:#x}
    sb $zero, {sx(hi_lo(CX_SWAPPED)[1])}($t0)
w1:
    lui $t0, {r_hi:#x}
    lbu $t1, {sx(hi_lo(CX_ACTIVE)[1])}($t0)
    beqz $t1, w2
    nop
    lui $t2, {ed_hi:#x}
    lbu $t2, {sx(ed_lo)}($t2)
    addiu $t3, $zero, 9
    beq $t2, $t3, w2
    nop
    jal {CX_END:#x}
    nop
w2:
    jal 0x1a21d0
    nop
    lui $t0, {r_hi:#x}
    lbu $t1, {sx(hi_lo(CX_ACTIVE)[1])}($t0)
    beqz $t1, w3
    nop
    jal {CX_SWAP:#x}
    nop
    lui $t0, {r_hi:#x}
    addiu $t1, $zero, 1
    sb $t1, {sx(hi_lo(CX_SWAPPED)[1])}($t0)
w3:
    ld $ra, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
"""
    d[CX_SWAP] = """
    lui $t0, 0x9c
    lw $t1, -0x15e0($t0)
    lw $t2, -0x15dc($t0)
    lw $t3, -0x15d8($t0)
    lw $t4, -0x15d4($t0)
    lw $t5, -0x15d0($t0)
    lw $t6, -0x15cc($t0)
    sw $t4, -0x15e0($t0)
    sw $t5, -0x15dc($t0)
    sw $t6, -0x15d8($t0)
    sw $t1, -0x15d4($t0)
    sw $t2, -0x15d0($t0)
    sw $t3, -0x15cc($t0)
    jr $ra
    nop
"""
    d[CX_END] = f"""
    lui $t0, {r_hi:#x}
    sb $zero, {sx(hi_lo(CX_ACTIVE)[1])}($t0)
    lbu $t1, {sx(hi_lo(CX_MASK)[1])}($t0)
    lui $t2, {mk_hi:#x}
    sb $t1, {sx(mk_lo)}($t2)
    lbu $t1, {sx(hi_lo(CX_CB)[1])}($t0)
    lui $t2, {c0_hi:#x}
    sb $t1, {sx(c0_lo)}($t2)
    jr $ra
    nop
"""
    m_hi, m_lo = hi_lo(MODE_ADDR)
    d[CX_START] = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sb $zero, 0x11($sp)
    lui $t0, {mk_hi:#x}
    lbu $t1, {sx(mk_lo)}($t0)
    sb $t1, 0x10($sp)
    lui $t2, {m_hi:#x}
    lbu $t2, {sx(m_lo)}($t2)
    addiu $t3, $zero, 8
    bne $t2, $t3, st_call
    nop
    lui $t2, {pf_hi:#x}
    lw $t2, {sx(pf_lo)}($t2)
    beqz $t2, st_call
    nop
    ori $t1, $t1, 3
    sb $t1, {sx(mk_lo)}($t0)
    addiu $t4, $zero, 1
    sb $t4, 0x11($sp)
st_call:
    jal 0x154ab0
    nop
    lbu $t4, 0x11($sp)
    beqz $t4, st_end
    nop
    lbu $t1, 0x10($sp)
    lui $t0, {mk_hi:#x}
    sb $t1, {sx(mk_lo)}($t0)
st_end:
    ld $ra, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
"""
    return {a: opt_asm(src, a) for a, src in d.items()}


def patch_cmdedit(b, off):
    code = cmdedit_code()
    addrs = sorted(code)
    for i, a in enumerate(addrs):
        n = len(code[a])
        assert n <= (addrs[i + 1] if i + 1 < len(addrs) else a + 0x200) - a, (hex(a), n)
        assert off(a + n) <= ELF_OFF + ELF_FILESZ
        assert not any(b[off(a):off(a) + n]), f"cmdedit region {a:#x} not zero"
        b[off(a):off(a) + n] = code[a]
    assert not any(b[off(CX_REQ):off(CX_REQ) + 4]), "cmdedit data not zero"
    for site, orig in (CX_GATE_SITE, CX_STUB2_SITE):
        assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
    struct.pack_into("<I", b, off(CX_GATE_SITE[0]), 0x0C000000 | (CX_GATE >> 2))
    struct.pack_into("<I", b, off(CX_STUB2_SITE[0]), 0x0C000000 | (CX_STUB2 >> 2))
    assert struct.unpack_from("<2I", b, off(CX_HOOK_SITE[0])) == CX_HOOK_SITE[1:], "cmdedit hook1 site"
    struct.pack_into("<2I", b, off(CX_HOOK_SITE[0]), 0x0C000000 | (CX_HOOK1 >> 2), 0)
    assert struct.unpack_from("<I", b, off(CX_START_SITE[0]))[0] == CX_START_SITE[1], "start site"
    struct.pack_into("<I", b, off(CX_START_SITE[0]), 0x0C000000 | (CX_START >> 2))
    assert struct.unpack_from("<I", b, off(CX_OWNER_SITE[0]))[0] == CX_OWNER_SITE[1], "owner site"
    struct.pack_into("<I", b, off(CX_OWNER_SITE[0]), CX_OWNER_SITE[2])
    for site, orig, new in CX_MENU_SITES:
        assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
        struct.pack_into("<I", b, off(site), new)
    for site in CX_POLL_SITES:
        assert struct.unpack_from("<I", b, off(site))[0] == CX_POLL_ORIG, hex(site)
        struct.pack_into("<I", b, off(site), 0x0C000000 | (CX_WRAP >> 2))


# ---- practice SELECT BUTTON function QUICK RESET (value 3 of the SELECT BUTTON option) ----
# The option value lists (0x3D2ED0: 0 APPROACH, 1 RESTART, 2 SKILL LIST, then 3 4 5 behind the list end) are cut to the first N entries by the
# count bytes at 0x3D2F20 (3 for ACTION STAND, 2 for the other actions).  Counts +1 makes value 3 selectable; its string slot
# (0x3D2DD0 + 3 * 0x14, "COMMAND", never reachable) is renamed to "QUICK RESET".  FUN_0033B1A0 (SELECT pressed, dispatch at 0x33B3F4)
# jumps to the end for values >= 3: that `b 0x33b4c0` (0x33B41C) becomes `j QR`.  QR puts both active characters (player struct =
# *(object + 0x10), object = team + 0x78 + point * 4 (task: +8 = function, restored to the char fn 0x141CF0 because a hit swaps it to 0x1829D0), X/Y int16 at +0, +2, facing bit 1 of byte +0x8C) on the start positions; with
# the pressing pad's held LEFT / RIGHT: 1P / 2P corner.  Velocity is cleared.  The camera (X i16 @0x9BDB20, moves max 0x20 px per frame)
# is set first to the clamped midpoint and its screen bounds are refreshed with FUN_0031F4C0, otherwise the bounds of the old camera
# position clamp the new character positions.  The freeze (hit stop) controller is reset with FUN_0017E850 (as the round setup does),
# otherwise its active record keeps setting bit 27 of struct +0x494 (frozen) on the characters.  Positions from testing (X, Y = 672).
QR = 0x3AF500
QT = 0x3AF900                  # per-frame fixer called from the HUD wrapper (practice): clears the freeze bit after a quick reset
QT_CNT = DATA + 0xCC           # 2 bytes: frames left per side
QR_TAB = 0x3AFB00              # 3 rows (start, left corner, right corner) of u16 x1P, x2P
# rows: start, DOWN+LEFT, LEFT, RIGHT, DOWN+RIGHT; (x1P, x2P, facing bit of 1P: 2 = right)
QR_POS = ((608, 928, 2), (32, 99, 2), (99, 32, 0), (1437, 1504, 2), (1504, 1437, 0))
QR_Y = 672
QR_SITE = (0x33B41C, 0x10000028)         # b 0x33b4c0
QR_COUNTS = 0x3D2F20
QR_STR = 0x3D2DD0 + 3 * 0x14


def quickreset_code(exit_target=0x33b4c0):
    f_hi, f_lo = hi_lo(PRACTICE_FLAG)
    h_hi, h_lo = hi_lo(IN_PAD)
    tb_hi, tb_lo = hi_lo(QR_TAB)
    tm_hi, tm_lo = hi_lo(TEAM0)
    sw_hi, sw_lo = hi_lo(0x92F100)          # stage width (u16)
    cam_hi, cam_lo = hi_lo(0x9BDB20)        # camera X (i16); FUN_0031F4C0 recomputes the screen bounds from it
    sc_hi, sc_lo = hi_lo(DATA + 0xC8)       # scratch word
    qc_hi, qc_lo = hi_lo(QT_CNT)
    lf_hi, lf_lo = hi_lo(0x9CB245)          # practice LIFE option: 0 RECOVERY, 1 0-LIFE
    fz_hi, fz_lo = hi_lo(0x9BB838)          # per-side freeze flags (cleared by the freeze controller reset FUN_0017E850 callers)
    src_entry = f"""
    addiu $t0, $zero, 3
    bne $a1, $t0, qe_out
    nop
    addu $a0, $s4, $zero
    jal {QRC:#x}
    nop
    j 0x33b4c0
    nop
qe_out:
    j {exit_target:#x}
    nop
"""
    src = f"""
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, qr_out
    nop
    addiu $sp, $sp, -0x50
    sd $ra, 0x48($sp)
    sd $s0, 0x40($sp)
    sd $s1, 0x38($sp)
    sd $s2, 0x30($sp)
    sd $s3, 0x28($sp)
    sd $s5, 0x20($sp)
    sll $t2, $a0, 3
    sll $t3, $a0, 2
    addu $t2, $t2, $t3
    lui $t0, {h_hi:#x}
    addiu $t0, $t0, {sx(h_lo)}
    addu $t0, $t0, $t2
    lhu $t1, 0($t0)
    addu $s3, $zero, $zero
    andi $t2, $t1, 0x80
    beqz $t2, qr_nl
    nop
    addiu $s3, $zero, 2
qr_nl:
    andi $t2, $t1, 0x20
    beqz $t2, qr_nr
    nop
    addiu $s3, $zero, 3
qr_nr:
    andi $t2, $t1, 0x40
    beqz $t2, qr_nd
    nop
    andi $t2, $t1, 0x80
    beqz $t2, qr_ndl
    nop
    addiu $s3, $zero, 1
qr_ndl:
    andi $t2, $t1, 0x20
    beqz $t2, qr_nd
    nop
    addiu $s3, $zero, 4
qr_nd:
    lui $s5, {tb_hi:#x}
    addiu $s5, $s5, {sx(tb_lo)}
    sll $t0, $s3, 3
    addu $s5, $s5, $t0
    lhu $t1, 0($s5)
    lhu $t2, 2($s5)
    addu $t1, $t1, $t2
    srl $t1, $t1, 1
    addiu $t1, $t1, -0x140
    lui $t3, {sw_hi:#x}
    lhu $t4, {sx(sw_lo)}($t3)
    addiu $t4, $t4, -0x280
    slt $t5, $t4, $t1
    beqz $t5, qr_c1
    nop
    addu $t1, $t4, $zero
qr_c1:
    slt $t5, $t1, $zero
    beqz $t5, qr_c2
    nop
    addu $t1, $zero, $zero
qr_c2:
    lui $t3, {cam_hi:#x}
    sh $t1, {sx(cam_lo)}($t3)
    jal 0x31f4c0
    nop
    jal 0x17e850
    nop
    lui $t0, {fz_hi:#x}
    sb $zero, {sx(fz_lo)}($t0)
    sb $zero, {sx(fz_lo) + 1}($t0)
    addu $s0, $zero, $zero
qr_side:
    subu $t4, $zero, $s0
    andi $t4, $t4, {CE_TEAM_STRIDE:#x}
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addu $s1, $t9, $t4
    addu $s2, $zero, $zero
qa_proj:
    sll $t0, $s2, 2
    addu $t0, $t0, $s1
    lw $t1, 0x100($t0)
    beqz $t1, qa_pb
    nop
    addu $a0, $t1, $zero
    jal 0x164a20
    nop
qa_pb:
    sll $t0, $s2, 2
    addu $t0, $t0, $s1
    lw $t1, 0xC0($t0)
    beqz $t1, qa_pn
    nop
    addu $a0, $t1, $zero
    jal 0x1649d0
    nop
qa_pn:
    addiu $s2, $s2, 1
    sltiu $t0, $s2, 16
    bnez $t0, qa_proj
    nop
    sb $zero, 7($s1)
    sb $zero, 8($s1)
    lui $t0, {lf_hi:#x}
    lbu $t1, {sx(lf_lo)}($t0)
    bnez $t1, qr_nolife
    nop
    addiu $t2, $zero, 3
    addu $t3, $s1, $zero
qr_life:
    lh $t4, 0x154($t3)
    bltz $t4, qr_lnext
    nop
    addiu $t5, $zero, 0x70
    sh $t5, 0x154($t3)
    sh $t5, 0x156($t3)
    sh $t5, 0x158($t3)
    sh $t5, 0x15A($t3)
qr_lnext:
    addiu $t3, $t3, 0x20
    addiu $t2, $t2, -1
    bnez $t2, qr_life
    nop
qr_nolife:
    lbu $t0, 3($s1)
    sll $t0, $t0, 2
    addu $t0, $t0, $s1
    lw $t0, 0x78($t0)
    beqz $t0, qr_next
    nop
    lw $s2, 0x10($t0)
    beqz $s2, qr_next
    nop
    lhu $t1, 0x4A6($s2)
    sh $t1, 0x10($sp)
    lw $a0, 0xDC($s2)
    lhu $a1, 0xEA($s2)
    addu $a2, $s2, $zero
    jal 0x189cd0
    nop
    sll $t1, $s0, 1
    addu $t1, $t1, $s5
    lhu $a1, 0($t1)
    addu $a0, $s2, $zero
    addiu $a2, $zero, {QR_Y}
    jal 0x160fe0
    nop
    lw $t0, 0x49C($s2)
    ori $t0, $t0, 0x100
    sw $t0, 0x49C($s2)
    lw $a0, 0xDC($s2)
    lhu $a1, 0xEA($s2)
    addu $a2, $s2, $zero
    jal 0x189aa0
    nop
    lhu $t1, 0x10($sp)
    sh $t1, 0x4A6($s2)
    lbu $t1, 0x8C($s2)
    andi $t1, $t1, 1
    lhu $t2, 4($s5)
    beqz $s0, qr_face
    nop
    xori $t2, $t2, 2
qr_face:
    or $t1, $t1, $t2
    sb $t1, 0x8C($s2)
    lhu $t1, 0x3A4($s2)
    andi $t1, $t1, 0xFFDF
    sh $t1, 0x3A4($s2)
    sb $zero, 0x57D($s2)
    sb $zero, 0x57E($s2)
    sh $zero, 0xF0($s2)
    addu $a0, $s2, $zero
    jal 0x16b440
    nop
    lbu $t0, 3($s1)
    sll $t0, $t0, 2
    addu $t0, $t0, $s1
    lw $t2, 0x6C($t0)
    beqz $t2, qr_nohelp
    nop
    lui $t1, 0x18
    addiu $t1, $t1, 0x60F0
    sw $t1, 8($t2)
qr_nohelp:
    lw $t0, 0x78($t0)
    beqz $t0, qr_next
    nop
    lui $t1, 0x14
    addiu $t1, $t1, 0x1CF0
    sw $t1, 8($t0)
qr_next:
    addiu $s0, $s0, 1
    sltiu $t0, $s0, 2
    bnez $t0, qr_side
    nop
    addiu $a0, $zero, 1
    jal {GA:#x}
    nop
    lui $t0, {qc_hi:#x}
    addiu $t1, $zero, 10
    sb $t1, {sx(qc_lo)}($t0)
    sb $t1, {sx(qc_lo) + 1}($t0)
    ld $ra, 0x48($sp)
    ld $s0, 0x40($sp)
    ld $s1, 0x38($sp)
    ld $s2, 0x30($sp)
    ld $s3, 0x28($sp)
    ld $s5, 0x20($sp)
    addiu $sp, $sp, 0x50
qr_out:
    jr $ra
    nop
"""
    ent = opt_asm(src_entry, QR)
    assert len(ent) <= QRC - QR, len(ent)
    return ent + bytes(QRC - QR - len(ent)) + opt_asm(src, QRC)


# ---- practice GAUGE option redesign (byte 0x9CB246: 0 NORMAL, 1 SKILL, 2 MAX, 3 LEADER MAX, 4 MAX+SKILL (new)) ----
# Vanilla forces the gauges every frame (FUN_0018D010: skill 0xE0 / team+0x3C when the option != 0, super 0x230 / team+0x38 when > 1;
# the per-frame clamp to 3/4/5 stocks (alive members) stays).  New: only LEADER MAX forces them every frame; SKILL / MAX / MAX+SKILL
# set the gauge at the practice start (FUN_0033A8D0, replaced by GA) and at every QUICK RESET (GA with a0 = 1, NORMAL then zeroes both
# like a round start) and play normally afterwards.  The two forcing sites read a flag byte (3 when the option is LEADER MAX, else 0)
# that the HUD wrapper maintains (GFLAG).  New menu value 4: cycle count 4 -> 5 and a string table in the cave.
GA = 0x3AFD00
GTAB = 0x3AFC00
GFLAG = DATA + 0xD0
GAUGE_STRINGS = ("NORMAL", "SKILL", "MAX", "LEADER MAX", "MAX+SKILL")
GAUGE_CB = 0x9CB246
GAUGE_PATCHES = (
    (0x18D080, 0x3C03009D, 0x3C030000 | (hi_lo(GFLAG)[0])),      # super forcing: lui v1,0x9d -> flag byte
    (0x18D084, 0x9063B246, 0x90630000 | hi_lo(GFLAG)[1]),
    (0x18D248, 0x3C03009D, 0x3C030000 | (hi_lo(GFLAG)[0])),      # skill forcing
    (0x18D24C, 0x9063B246, 0x90630000 | hi_lo(GFLAG)[1]),
    (0x33915C, 0x3C03003D, 0x3C030000 | hi_lo(GTAB)[0]),         # value strings of the menu row
    (0x339164, 0x24632B80, 0x24630000 | hi_lo(GTAB)[1]),
    (0x3387A8, 0x24050004, 0x24050005),                          # 5 values
)


def gauge_code():
    cb_hi, cb_lo = hi_lo(GAUGE_CB)
    tm_hi, tm_lo = hi_lo(TEAM0)
    src = f"""
    lui $t0, {cb_hi:#x}
    lbu $t1, {sx(cb_lo)}($t0)
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addiu $t7, $zero, 2
ga_side:
    beqz $a0, ga_nz
    nop
    sw $zero, 0x38($t9)
    sw $zero, 0x3C($t9)
ga_nz:
    addiu $t2, $zero, 0x1A
    srlv $t3, $t2, $t1
    andi $t3, $t3, 1
    beqz $t3, ga_np
    nop
    addiu $t4, $zero, 0xE0
    sw $t4, 0x3C($t9)
ga_np:
    addiu $t2, $zero, 0x1C
    srlv $t3, $t2, $t1
    andi $t3, $t3, 1
    beqz $t3, ga_ns
    nop
    addiu $t4, $zero, 0x230
    sw $t4, 0x38($t9)
ga_ns:
    addiu $t9, $t9, {CE_TEAM_STRIDE:#x}
    addiu $t7, $t7, -1
    bnez $t7, ga_side
    nop
    jr $ra
    nop
"""
    return opt_asm(src, GA)


def patch_gauge(b, off):
    code = gauge_code()
    assert len(code) <= 0x100, len(code)
    for a, n in ((GA, len(code)), (GTAB, 0x14 * len(GAUGE_STRINGS))):
        assert not any(b[off(a):off(a) + n]), f"gauge region {a:#x} not zero"
    b[off(GA):off(GA) + len(code)] = code
    for i, t in enumerate(GAUGE_STRINGS):
        b[off(GTAB + 0x14 * i):off(GTAB + 0x14 * i) + len(t)] = t.encode()
    for site, orig, new in GAUGE_PATCHES:
        assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
        struct.pack_into("<I", b, off(site), new)
    site = 0x33A8D0                                              # FUN_0033A8D0 (practice start) -> GA with a0 = 0
    assert struct.unpack_from("<I", b, off(site))[0] == 0x3C03009D
    struct.pack_into("<I", b, off(site), 0x08000000 | (GA >> 2))
    # The original 2nd instruction `lbu $a0, -0x4dba($v1)` now sits in the delay slot of that j and would run with a stale $v1 (the replaced
    # `lui $v1,0x9d` never ran): a load from a random address, harmless in PCSX2 but a bus error on real hardware (black screen when the
    # practice mode starts, found 2026-11-21 by bisecting).  Make it `addiu $a0,$zero,0` (GA treats a0 = 0 as "practice start").
    assert struct.unpack_from("<I", b, off(site + 4))[0] == 0x9064B246
    struct.pack_into("<I", b, off(site + 4), 0x24040000)
    return len(code)


# ---- practice GUARD option: new value ALL (the dummy blocks every attack, whatever its height) ----
# How the game decides block vs hit (found with PINE, see docs/ps2-hacking-notes.md): the dummy in guard pose has a guard hurtbox of type
# 0x1C (standing) / 0x1D (crouching), copied to contact byte +0xC of the hit.  FUN_00180190 (called from FUN_00180640 at 0x180674) then
# checks the attacker's flags at +0x280: standing guard fails when bit 0x80 (low) is set, crouching guard fails with bit 0x40 (overhead);
# a failed check makes the contact a normal hit (+0xC := 2), otherwise guard bit 0x400 of the defender's +0x530 is set.  The flags are only
# set in the frame the hitbox becomes active, so the dummy cannot react beforehand.
# Pose choice before the hit: STAND dummy ducks in FUN_0013FAF0 (GA_AI) when the attacker's frame pose byte +0x27E is 1 or the attack is a learned low; CROUCH
# dummy stands up in FUN_00337230 (GA_CR) when an airborne attacker is attacking (+0x490 bit 0) or the attack is a learned overhead AND the game's own "attack incoming"
# test FUN_00183570 is true (otherwise holding back just walks away).  Learned table GA_TBL: the contact hook records (char id, action, low/overhead) the first
# time a forced guard had the wrong stance.
# GUARD ALL: stub GA_RT replaces the call: for the dummy (CONTROL CPU, practice, side != owner) and contact types 0x1C/0x1D guard is always set.
# Menu: value 8 "ALL" is shown from a mirror byte GMODE (= ALL ? 8 : 0x9CB244); the vanilla byte 0x9CB244 stays 1 (GUARD) while ALL is active so all
# AI code keeps working; ALL flag DATA+0xE8 (only valid while 0x9CB244 == 1).  The value lists / counts of the ACTIONs with the full list get one more entry.
GA_LIST = 0x3B0780
GA_TAB = 0x3B0800            # 11 value strings (stride 0x14): the vanilla 8 (copied) + ALL, RANDOM, RANDOM ALL
GA_RT = 0x3B0900
GA_POST = 0x3B0C00
GA_AI = 0x3B1600             # FUN_0013FAF0: STAND dummy ducks (code 7) when the attacker's frame pose byte +0x27E is 1 (crouch; 0 stand, 2 air)
GA_TBL = 0x3B1000            # learned attacks: 64 entries x 8 bytes (u16 char id, u16 action, u8 kind 1 low / 2 overhead), count byte GA_CNT
GA_LK = 0x3B1200             # lookup (a0 = attacker char) -> v0 kind
GA_ST = 0x3B1300             # store (a0 = attacker char, a1 = kind)
GA_CNT = DATA + 0xEA
GA_RN = 0x3B1400             # random block decision for the current attack (a0 = attacker char) -> v0 1 block / 0 no block
GA_STK, GA_STKT, GA_TICK = DATA + 0xEC, DATA + 0xF8, DATA + 0xFC   # sticky guard input: held code (0 none / 7 / 8), expiry tick, poll tick counter
GA_STK_N = 6                                 # ticks (about 4 frames) the guard input is bridged when the AI prediction flickers (prevents the accidental back dash)
GA_SW = 0x3B1B00                             # wrapper of the FUN_00336FE0 call in FUN_0013B910: re-injects the held guard input
TEAM0_HI, TEAM0_LO = hi_lo(TEAM0)
GA_PREV, GA_PEND = DATA + 0x105, DATA + 0x106   # attacker attack bit of the previous poll; re-roll pending (set when an attack ended, executed when the dummy is idle)
GA_CRCODE = DATA + 0x104                    # guard code chosen by GA_CR this frame; GA_AI mirrors it for ACTION CROUCH (the AI runs after FUN_00337230 and used to override it with 'back')
GA_LASTT = DATA + 0x100                     # tick of the previous GA_RN call (a gap of more than 6 frames = new attack)
GA_BLK, GA_RNG, GA_LAST = DATA + 0xEB, DATA + 0xF0, DATA + 0xF4   # decision byte, LCG state (stepped by the poll wrapper), last attack key (char id << 16 | action)
GA_STUN_CROUCH, GA_STUN_STAND = 45, 49       # guard stun actions the dummy is switched to directly when a forced guard has the wrong stance (the 0x530 guard bit is already cleared again in a chain, so no stun precondition)
GA_CR = 0x3B1800             # FUN_00337230 (ACTION CROUCH): the dummy stands up (code 8) while the attacker is airborne
GA_ALL, GA_MODE = DATA + 0xE8, DATA + 0xE9
GA_STRINGS_ORIG = 0x3D2AB0
GA_NEW_STRINGS = ("ALL", "RANDOM", "RANDOM ALL")
GA_NVAL = 11                                # menu values 0..10; GA_ALL flag: 0 off, 1 ALL, 2 RANDOM, 3 RANDOM ALL (shown as 8 / 9 / 10)
GA_PTR_TAB = 0x3D2F40
GA_CNT_TAB = 0x3D2F78
GA_LIST_ORIG = 0x3D2F30
GA_ACTIONS = (0, 1, 7, 8, 10, 11)           # ACTION values whose GUARD list is the full one


def guardall_code():
    a_hi, a_lo = hi_lo(GA_ALL)
    mo_lo = hi_lo(GA_MODE)[1]
    m_hi, m_lo = hi_lo(MODE_ADDR)
    d = {}
    d[GA_POST] = f"""
    lui $t0, 0x9d
    lbu $t1, -0x4dbc($t0)
    lui $t3, {a_hi:#x}
    sltiu $t2, $t1, 8
    bnez $t2, gp_not
    nop
    addiu $t4, $zero, 1
    sb $t4, -0x4dbc($t0)
    addiu $t5, $t1, -7
    sb $t5, {sx(a_lo)}($t3)
    sb $t1, {sx(mo_lo)}($t3)
    b gp_out
    nop
gp_not:
    sb $zero, {sx(a_lo)}($t3)
    sb $t1, {sx(mo_lo)}($t3)
gp_out:
    j 0x3388dc
    nop
"""
    d[GA_RT] = f"""
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    beqz $t1, rt_orig
    nop
    addiu $t4, $zero, 2
    beq $t1, $t4, rt_orig
    nop
    lui $t2, 0x9d
    lbu $t3, -0x4dbc($t2)
    addiu $t4, $zero, 1
    bne $t3, $t4, rt_orig
    nop
    lbu $t3, -0x4dc0($t2)
    bnez $t3, rt_orig
    nop
    lui $t5, {m_hi:#x}
    lbu $t6, {sx(m_lo)}($t5)
    addiu $t7, $zero, 8
    bne $t6, $t7, rt_orig
    nop
    lw $v0, 0xdc($a0)
    andi $v0, $v0, 0xc
    srl $v0, $v0, 2
    lui $v1, 0x9f
    lbu $v1, -0x68b8($v1)
    beq $v0, $v1, rt_orig
    nop
    lbu $t6, 0xc($a1)
    addiu $t7, $t6, -0x1c
    sltiu $t7, $t7, 2
    beqz $t7, rt_orig
    nop
    lw $v1, 0x518($a0)
    beqz $v1, rt_orig
    nop
    lbu $a2, 0x280($v1)
    addiu $a3, $zero, 0x1c
    bne $t6, $a3, rt_c2
    nop
    andi $t7, $a2, 0x80
    beqz $t7, rt_orig
    nop
    addiu $t7, $zero, 0x1d
    addiu $t8, $zero, 1
    b rt_fix
    nop
rt_c2:
    andi $t7, $a2, 0x40
    beqz $t7, rt_orig
    nop
    addiu $t7, $zero, 0x1c
    addiu $t8, $zero, 2
rt_fix:
    sb $t7, 0xc($a1)
    sb $t7, 0x52c($a0)
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    sd $a1, 8($sp)
    addu $a0, $v1, $zero
    jal {GA_ST:#x}
    addu $a1, $t8, $zero
    ld $a0, 0x10($sp)
    ld $a1, 8($sp)
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
    j 0x180190
    nop
    addiu $sp, $sp, -0x30
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    sd $a1, 8($sp)
    lw $t6, 0x530($a0)
    andi $t7, $t6, 0x400
    sd $t7, 0($sp)
    ori $t6, $t6, 0x400
    sw $t6, 0x530($a0)
    jal 0x33ab40
    nop
    ld $a0, 0x10($sp)
    ld $a1, 8($sp)
    lbu $v0, 0xc($a1)
    lw $v1, 0x518($a0)
    beqz $v1, rt_end
    nop
    lbu $a2, 0x280($v1)
    addiu $a3, $zero, 0x1c
    bne $v0, $a3, rt_hi
    nop
    andi $a2, $a2, 0x80
    beqz $a2, rt_end
    nop
    addiu $a1, $zero, 1
    b rt_rec
    nop
rt_hi:
    andi $a2, $a2, 0x40
    beqz $a2, rt_end
    nop
    addiu $a1, $zero, 2
rt_rec:
    sd $a1, 0x20($sp)
    addu $a0, $v1, $zero
    jal {GA_ST:#x}
    nop
    ld $a0, 0x10($sp)
    ld $t8, 0x20($sp)
    addiu $a3, $zero, {GA_STUN_CROUCH}
    addiu $a2, $zero, 1
    beq $t8, $a2, rt_sw
    nop
    addiu $a3, $zero, {GA_STUN_STAND}
rt_sw:
    sh $a3, 0xf0($a0)
    jal 0x16abf0
    nop
    ld $a0, 0x10($sp)
    lw $t6, 0x530($a0)
    ori $t6, $t6, 0x400
    sw $t6, 0x530($a0)
rt_end:
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x30
    addiu $v0, $zero, -1
    jr $ra
    nop
rt_stun:
    addiu $sp, $sp, -0x30
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    sd $a1, 8($sp)
    jal 0x180190
    nop
    ld $a0, 0x10($sp)
    lw $t6, 0x530($a0)
    sd $t6, 0x20($sp)
    lw $v1, 0x518($a0)
    beqz $v1, rs_end
    nop
    lbu $a2, 0x280($v1)
    lw $t6, 0x48c($a0)
    andi $t6, $t6, 8
    bnez $t6, rs_crouched
    nop
    andi $a2, $a2, 0x80
    beqz $a2, rs_end
    nop
    addiu $a3, $zero, {GA_STUN_CROUCH}
    addiu $a1, $zero, 1
    b rs_sw
    nop
rs_crouched:
    andi $a2, $a2, 0x40
    beqz $a2, rs_end
    nop
    addiu $a3, $zero, {GA_STUN_STAND}
    addiu $a1, $zero, 2
rs_sw:
    sd $a3, 0x28($sp)
    addu $a0, $v1, $zero
    jal {GA_ST:#x}
    nop
    ld $a0, 0x10($sp)
    ld $a3, 0x28($sp)
    sh $a3, 0xf0($a0)
    jal 0x16abf0
    nop
    ld $a0, 0x10($sp)
    ld $t6, 0x20($sp)
    sw $t6, 0x530($a0)
rs_end:
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x30
    addiu $v0, $zero, -1
    jr $ra
    nop
rt_orig:
    j 0x180190
    nop
"""
    rng_lo, blk_lo, last_lo = hi_lo(GA_RNG)[1], hi_lo(GA_BLK)[1], hi_lo(GA_LAST)[1]
    lastt_lo = hi_lo(GA_LASTT)[1]
    tick_lo = hi_lo(GA_TICK)[1]
    d[GA_RN] = f"""
    lui $t2, {a_hi:#x}
    lbu $v0, {sx(blk_lo)}($t2)
    jr $ra
    nop
"""
    d[GA_AI] = f"""
    bnez $s7, ai_out
    nop
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    beqz $t1, ai_out
    nop
    lui $t2, 0x9d
    lbu $t3, -0x4dc0($t2)
    bnez $t3, ai_out
    nop
    lbu $t4, -0x4dbf($t2)
    addiu $t5, $zero, 1
    bne $t4, $t5, ai_normal
    nop
    lbu $t6, {sx(hi_lo(GA_CRCODE)[1])}($t0)
    addiu $t7, $zero, 8
    beq $t6, $t7, ai_out
    nop
    addiu $t7, $zero, 7
    beq $t6, $t7, ai_c7
    nop
    addiu $s7, $zero, 3
    b ai_out
    nop
ai_c7:
    addiu $s7, $zero, 1
    b ai_out
    nop
ai_normal:
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    jal 0x18a010
    lw $a0, 0xdc($s5)
    beqz $v0, ai_ret
    nop
    sd $v0, 0x10($sp)
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    sltiu $t2, $t1, 2
    bnez $t2, ai_pose
    nop
    addu $a1, $zero, $zero
    jal {GA_RN:#x}
    ld $a0, 0x10($sp)
    bnez $v0, ai_chk
    nop
    addiu $s7, $zero, 3
    b ai_ret
    nop
ai_chk:
    ld $t5, 0x10($sp)
    lw $t4, 0x490($t5)
    andi $t4, $t4, 1
    bnez $t4, ai_chk2
    nop
    lhu $t4, 0xec($t5)
    sltiu $t4, $t4, 2
    beqz $t4, ai_chk2
    nop
    addiu $s7, $zero, 3
    b ai_ret
    nop
ai_chk2:
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    addiu $t2, $zero, 2
    beq $t1, $t2, ai_ret
    nop
ai_pose:
    lw $t4, 0x530($s5)
    andi $t4, $t4, 0x400
    beqz $t4, ai_att
    nop
    lw $t4, 0x48c($s5)
    andi $t4, $t4, 8
    beqz $t4, ai_att
    nop
    addiu $s7, $zero, 1
    b ai_ret
    nop
ai_att:
    jal {GA_LK:#x}
    ld $a0, 0x10($sp)
    addiu $t4, $zero, 1
    beq $v0, $t4, ai_duck
    nop
    addiu $t4, $zero, 2
    beq $v0, $t4, ai_ret
    nop
    ld $t5, 0x10($sp)
    lbu $t4, 0x27e($t5)
    andi $t4, $t4, 0xf
    addiu $t6, $zero, 1
    bne $t4, $t6, ai_ret
    nop
ai_duck:
    addiu $s7, $zero, 1
ai_ret:
    lui $t0, {a_hi:#x}
    addiu $t4, $zero, 3
    beq $s7, $t4, ai_nost
    nop
    sltiu $t4, $s7, 2
    beqz $t4, ai_rest
    nop
    lui $t5, 0x9d
    lbu $t6, -0x4dbf($t5)
    bnez $t6, ai_rest
    nop
    addiu $t5, $zero, 8
    beqz $s7, ai_stk
    nop
    addiu $t5, $zero, 7
ai_stk:
    sb $t5, {sx(hi_lo(GA_STK)[1])}($t0)
    lw $t6, {sx(hi_lo(GA_TICK)[1])}($t0)
    addiu $t6, $t6, {GA_STK_N}
    sw $t6, {sx(hi_lo(GA_STKT)[1])}($t0)
    b ai_rest
    nop
ai_nost:
    sb $zero, {sx(hi_lo(GA_STK)[1])}($t0)
ai_rest:
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
ai_out:
    addiu $v1, $zero, 2
    jr $ra
    nop
"""
    d[GA_CR] = f"""
    addiu $a1, $zero, 7
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    beqz $t1, cr_out
    nop
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    addiu $t7, $zero, 7
    sd $t7, 8($sp)
    jal 0x18a010
    lw $a0, 0xdc($s1)
    beqz $v0, cr_ret
    nop
    sd $v0, 0x10($sp)
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    sltiu $t2, $t1, 2
    bnez $t2, cr_pose
    nop
    addiu $a1, $zero, 1
    jal {GA_RN:#x}
    ld $a0, 0x10($sp)
    bnez $v0, cr_chk
    nop
    addiu $t7, $zero, 6
    sd $t7, 8($sp)
    b cr_ret
    nop
cr_chk:
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    addiu $t2, $zero, 2
    beq $t1, $t2, cr_ret
    nop
cr_pose:
    lw $t4, 0x530($s1)
    andi $t4, $t4, 0x400
    beqz $t4, cr_norm
    nop
    lw $t4, 0x48c($s1)
    andi $t4, $t4, 8
    bnez $t4, cr_ret
    nop
    addiu $t7, $zero, 8
    sd $t7, 8($sp)
    jal {GA_LK:#x}
    ld $a0, 0x10($sp)
    addiu $t4, $zero, 1
    beq $v0, $t4, cs_duck
    nop
    ld $t5, 0x10($sp)
    lbu $t2, 0x27e($t5)
    andi $t2, $t2, 0xf
    addiu $t4, $zero, 1
    bne $t2, $t4, cr_ret
    nop
cs_duck:
    addiu $t7, $zero, 7
    sd $t7, 8($sp)
    b cr_ret
    nop
cr_norm:
    jal {GA_LK:#x}
    ld $a0, 0x10($sp)
    addiu $t4, $zero, 2
    beq $v0, $t4, cr_stand
    nop
    addiu $t4, $zero, 1
    beq $v0, $t4, cr_ret
    nop
    ld $t5, 0x10($sp)
    lbu $t2, 0x27e($t5)
    andi $t2, $t2, 0xf
    addiu $t3, $zero, 2
    bne $t2, $t3, cr_ret
    nop
    lw $t2, 0x490($t5)
    andi $t2, $t2, 1
    beqz $t2, cr_ret
    nop
cr_stand:
    ld $t5, 0x10($sp)
    addu $a0, $s1, $zero
    lw $t6, 0xdc($t5)
    andi $t6, $t6, 0xc
    srl $a1, $t6, 2
    jal 0x183570
    nop
    beqz $v0, cr_ret
    nop
    addiu $t7, $zero, 8
    sd $t7, 8($sp)
cr_ret:
    ld $a1, 8($sp)
    lui $t0, {a_hi:#x}
    sb $a1, {sx(hi_lo(GA_CRCODE)[1])}($t0)
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
cr_out:
    lui $v0, 0x9d
    lbu $v0, -0x4dbe($v0)
    jr $ra
    nop
"""
    d[GA_SW] = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    jal 0x336fe0
    nop
    sd $v0, 8($sp)
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(hi_lo(GA_STK)[1])}($t0)
    beqz $t1, sw_done
    nop
    lw $t2, {sx(hi_lo(GA_TICK)[1])}($t0)
    lw $t3, {sx(hi_lo(GA_STKT)[1])}($t0)
    sltu $t4, $t3, $t2
    bnez $t4, sw_clr
    nop
    lui $t5, 0x9d
    lbu $t6, -0x4dc0($t5)
    bnez $t6, sw_done
    nop
    lbu $t6, -0x4dbf($t5)
    bnez $t6, sw_done
    nop
    ld $a0, 0x10($sp)
    lw $t2, 0x530($a0)
    andi $t2, $t2, 0x400
    bnez $t2, sw_done
    nop
    jal 0x171ab0
    lw $a0, 0xdc($a0)
    sltiu $t2, $v0, 2
    beqz $t2, sw_done
    nop
    addu $a0, $v0, $zero
    lui $t0, {a_hi:#x}
    lbu $a1, {sx(hi_lo(GA_STK)[1])}($t0)
    addu $a2, $zero, $zero
    jal 0x16a220
    addiu $a3, $zero, 1
    b sw_done
    nop
sw_clr:
    sb $zero, {sx(hi_lo(GA_STK)[1])}($t0)
sw_done:
    ld $v0, 8($sp)
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
    jr $ra
    nop
"""
    t_hi, t_lo = hi_lo(GA_TBL)
    c_lo = hi_lo(GA_CNT)[1]
    d[GA_LK] = f"""
    lhu $t0, 0xea($a0)
    lhu $t1, 0xec($a0)
    lui $t2, {a_hi:#x}
    lbu $t3, {sx(c_lo)}($t2)
    sltiu $t4, $t3, 65
    beqz $t4, lk_none
    nop
    addu $t4, $zero, $zero
    lui $t5, {t_hi:#x}
    addiu $t5, $t5, {t_lo:#x}
lk_loop:
    beq $t4, $t3, lk_none
    nop
    lhu $t6, 0($t5)
    bne $t6, $t0, lk_next
    nop
    lhu $t6, 2($t5)
    bne $t6, $t1, lk_next
    nop
    lbu $v0, 4($t5)
    jr $ra
    nop
lk_next:
    addiu $t5, $t5, 8
    b lk_loop
    addiu $t4, $t4, 1
lk_none:
    jr $ra
    addu $v0, $zero, $zero
"""
    d[GA_ST] = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    sd $a1, 8($sp)
    jal {GA_LK:#x}
    nop
    ld $a0, 0x10($sp)
    ld $a1, 8($sp)
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
    bnez $v0, st_out
    nop
    lui $t2, {a_hi:#x}
    lbu $t3, {sx(c_lo)}($t2)
    sltiu $t4, $t3, 64
    beqz $t4, st_out
    nop
    sll $t5, $t3, 3
    lui $t6, {t_hi:#x}
    addiu $t6, $t6, {t_lo:#x}
    addu $t6, $t6, $t5
    lhu $t0, 0xea($a0)
    sh $t0, 0($t6)
    lhu $t1, 0xec($a0)
    sh $t1, 2($t6)
    sb $a1, 4($t6)
    addiu $t3, $t3, 1
    sb $t3, {sx(c_lo)}($t2)
st_out:
    jr $ra
    nop
"""
    return {a: opt_asm(src, a) for a, src in d.items()}


def patch_guardall(b, off):
    code = guardall_code()
    for a, c in code.items():
        assert len(c) <= 0x300, (hex(a), len(c))
        assert not any(b[off(a):off(a) + len(c)]), f"guard-all region {a:#x} not zero"
        b[off(a):off(a) + len(c)] = c
    # value list [0..8] + terminator, strings copied from the vanilla table + new ones
    assert not any(b[off(GA_LIST):off(GA_LIST) + 16]) and not any(b[off(GA_TAB):off(GA_TAB) + 0x14 * GA_NVAL])
    b[off(GA_LIST):off(GA_LIST) + GA_NVAL + 1] = bytes(list(range(GA_NVAL)) + [0xFF])
    b[off(GA_TAB):off(GA_TAB) + 0x14 * 8] = b[off(GA_STRINGS_ORIG):off(GA_STRINGS_ORIG) + 0x14 * 8]
    for i, t in enumerate(GA_NEW_STRINGS):
        b[off(GA_TAB + 0x14 * (8 + i)):off(GA_TAB + 0x14 * (8 + i)) + len(t)] = t.encode()
    for i in GA_ACTIONS:
        assert struct.unpack_from("<I", b, off(GA_PTR_TAB + 4 * i))[0] == GA_LIST_ORIG, i
        assert b[off(GA_CNT_TAB + i)] == 8, i
        struct.pack_into("<I", b, off(GA_PTR_TAB + 4 * i), GA_LIST)
        b[off(GA_CNT_TAB + i)] = GA_NVAL
    a_hi = hi_lo(GA_ALL)[0]
    tab_hi, tab_lo = hi_lo(GA_TAB)
    mo_lo = hi_lo(GA_MODE)[1]
    patches = (
        (0x338714, 0x3C02009D, 0x3C020000 | a_hi),                  # menu input: current value for the list lookup = GMODE
        (0x33871C, 0x9045B244, 0x90450000 | mo_lo),
        (0x338768, 0x1000005C, 0x08000000 | (GA_POST >> 2)),        # b 0x3388dc -> j POST (delay slot stores 0x9CB244)
        (0x3390F0, 0x3C02009D, 0x3C020000 | a_hi),                  # draw: value index = GMODE, strings from GA_TAB
        (0x3390F4, 0x3C03003D, 0x3C030000 | tab_hi),
        (0x3390F8, 0x9046B244, 0x90460000 | mo_lo),
        (0x3390FC, 0x24632AB0, 0x24630000 | tab_lo),
        (0x180674, 0x0C060064, 0x0C000000 | (GA_RT >> 2)),          # jal 0x180190 -> GA_RT
        (0x13B97C, 0x0C0CDBF8, 0x0C000000 | (GA_SW >> 2)),          # jal 0x336fe0 (FUN_0013B910) -> GA_SW
        (0x140274, 0x24030002, 0x0C000000 | (GA_AI >> 2)),          # addiu v1,zero,2 (FUN_0013FAF0, before the guard input choice) -> jal GA_AI
        (0x337374, 0x24050007, 0x0C000000 | (GA_CR >> 2)),          # addiu a1,zero,7 (FUN_00337230 case CROUCH) -> jal GA_CR
    )
    for site, orig, new in patches:
        assert struct.unpack_from("<I", b, off(site))[0] == orig, (hex(site), hex(struct.unpack_from("<I", b, off(site))[0]))
        struct.pack_into("<I", b, off(site), new)


# ---- INPUT display vs. SKILL LIST (movelist): restore the fight atlas before the movelist opens ----
# The input module keeps the SPR03 atlas (set 7) resident in the shared atlas buffer (tracker byte 0x1CB0C73).  In a normal fight
# the tracker is 3 (SPR01) and the movelist task (FUN_003070A0, started by FUN_003054D0 at 0x30561C / 0x305644 via FUN_003059E0)
# draws with whatever is resident -> with set 7 it drew grey boxes.  Stub: if the tracker is 7 (practice flag on), load set 3 first.
# The module reloads set 7 itself on its next tick after the pause.
MLF = 0x3AFE00
ML_SITES = (0x30561C, 0x305644)       # jal 0x3059e0 with a0 = 0x3070A0


def movelist_code():
    f_hi, f_lo = hi_lo(PRACTICE_FLAG)
    t_hi, t_lo = hi_lo(0x1CB0C73)
    src = f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x18($sp)
    sd $a0, 0x10($sp)
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, ml_go
    nop
    lui $t0, {t_hi:#x}
    lbu $t1, {sx(t_lo)}($t0)
    addiu $t2, $zero, 7
    bne $t1, $t2, ml_go
    nop
    addu $a0, $zero, $zero
    addiu $a1, $zero, 3
    jal 0x301ae0
    nop
ml_go:
    ld $a0, 0x10($sp)
    ld $ra, 0x18($sp)
    addiu $sp, $sp, 0x20
    j 0x3059e0
    nop
"""
    return opt_asm(src, MLF)


def patch_movelist(b, off):
    code = movelist_code()
    assert len(code) <= 0x80, len(code)
    assert not any(b[off(MLF):off(MLF) + len(code)]), "movelist stub region not zero"
    b[off(MLF):off(MLF) + len(code)] = code
    for site in ML_SITES:
        assert struct.unpack_from("<I", b, off(site))[0] == 0x0C0C1678, hex(site)
        struct.pack_into("<I", b, off(site), 0x0C000000 | (MLF >> 2))


def quickreset_tick_code():
    qc_hi, qc_lo = hi_lo(QT_CNT)
    qs_hi, qs_lo = hi_lo(QT_CNT + 2)      # frames the "freeze without ticking helper" state has lasted
    tm_hi, tm_lo = hi_lo(TEAM0)
    cb_hi, cb_lo = hi_lo(GAUGE_CB)
    gf_hi, gf_lo = hi_lo(GFLAG)
    ct_hi, ct_lo = hi_lo(0x9BB868)        # first freeze controller record (pointer of the frozen char struct)
    src = f"""
    addiu $sp, $sp, -0x30
    sd $ra, 0x28($sp)
    sd $s0, 0x20($sp)
    sd $s1, 0x18($sp)
    addu $s0, $a0, $zero
    lui $t0, {cb_hi:#x}
    lbu $t1, {sx(cb_lo)}($t0)
    addiu $t2, $zero, 3
    xor $t3, $t1, $t2
    sltiu $t3, $t3, 1
    sll $t4, $t3, 1
    addu $t3, $t3, $t4
    lui $t0, {gf_hi:#x}
    sb $t3, {sx(gf_lo)}($t0)
    lui $t0, {qc_hi:#x}
    addiu $t0, $t0, {sx(qc_lo)}
    addu $t0, $t0, $s0
    lbu $t1, 0($t0)
    beqz $t1, qt_p2
    nop
    addiu $t1, $t1, -1
    sb $t1, 0($t0)
    subu $t4, $zero, $s0
    andi $t4, $t4, {CE_TEAM_STRIDE:#x}
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addu $t9, $t9, $t4
    lbu $t2, 3($t9)
    sll $t2, $t2, 2
    addu $t2, $t2, $t9
    lw $t2, 0x78($t2)
    beqz $t2, qt_p2
    nop
    lw $t2, 0x10($t2)
    beqz $t2, qt_p2
    nop
    lw $t3, 0x494($t2)
    lui $t5, 0xF7FF
    ori $t5, $t5, 0xFFFF
    and $t3, $t3, $t5
    sw $t3, 0x494($t2)
qt_p2:
    b qt_out                 # safety net disabled (v72): it fired every 240 frames during throws / knockdowns and reset the victim's tasks
    nop
    lui $t0, {ct_hi:#x}
    lw $t1, {sx(ct_lo)}($t0)
    beqz $t1, qt_ok
    nop
    addu $t7, $zero, $zero
qt_chk:
    subu $t4, $zero, $t7
    andi $t4, $t4, {CE_TEAM_STRIDE:#x}
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addu $t9, $t9, $t4
    lbu $t2, 3($t9)
    sll $t2, $t2, 2
    addu $t2, $t2, $t9
    lw $t2, 0x6C($t2)
    beqz $t2, qt_cn
    nop
    lw $t3, 8($t2)
    lui $t5, 0x17
    ori $t5, $t5, 0xFA60
    beq $t3, $t5, qt_ok
    nop
qt_cn:
    addiu $t7, $t7, 1
    sltiu $t0, $t7, 2
    bnez $t0, qt_chk
    nop
    lui $t0, {qs_hi:#x}
    lbu $t1, {sx(qs_lo)}($t0)
    addiu $t1, $t1, 1
    sb $t1, {sx(qs_lo)}($t0)
    sltiu $t2, $t1, 240
    bnez $t2, qt_out
    nop
    sb $zero, {sx(qs_lo)}($t0)
    jal 0x17e850
    nop
    addu $s1, $zero, $zero
qt_rec:
    subu $t4, $zero, $s1
    andi $t4, $t4, {CE_TEAM_STRIDE:#x}
    lui $t9, {tm_hi:#x}
    addiu $t9, $t9, {sx(tm_lo)}
    addu $t9, $t9, $t4
    lbu $t2, 3($t9)
    sll $t2, $t2, 2
    addu $t2, $t2, $t9
    lw $t2, 0x78($t2)
    beqz $t2, qt_rn
    nop
    lui $t5, 0x14
    ori $t5, $t5, 0x1CF0
    sw $t5, 8($t2)
    lw $t2, 0x10($t2)
    beqz $t2, qt_rn
    nop
    lw $t3, 0x494($t2)
    lui $t5, 0xF7FF
    ori $t5, $t5, 0xFFFF
    and $t3, $t3, $t5
    sw $t3, 0x494($t2)
    sb $zero, 0x57D($t2)
    sb $zero, 0x57E($t2)
qt_rn:
    addiu $s1, $s1, 1
    sltiu $t0, $s1, 2
    bnez $t0, qt_rec
    nop
    b qt_out
    nop
qt_ok:
    lui $t0, {qs_hi:#x}
    sb $zero, {sx(qs_lo)}($t0)
qt_out:
    ld $ra, 0x28($sp)
    ld $s0, 0x20($sp)
    ld $s1, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x30
"""
    return opt_asm(src, QT)


def patch_quickreset(b, off, hitbox=False):
    code = quickreset_code(HB.HB_SELECT if hitbox else 0x33b4c0)
    assert len(code) <= QT - QR, len(code)
    for a, n in ((QR, len(code)), (QR_TAB, 8 * len(QR_POS))):
        assert off(a + n) <= ELF_OFF + ELF_FILESZ
        assert not any(b[off(a):off(a) + n]), f"quick reset region {a:#x} not zero"
    b[off(QR):off(QR) + len(code)] = code
    qt = quickreset_tick_code()
    assert not any(b[off(QT):off(QT) + len(qt)]), "QT region not zero"
    b[off(QT):off(QT) + len(qt)] = qt
    for i, (x1, x2, f) in enumerate(QR_POS):
        struct.pack_into("<HHH", b, off(QR_TAB + 8 * i), x1, x2, f)
    site, orig = QR_SITE
    assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
    struct.pack_into("<I", b, off(site), 0x08000000 | (QR >> 2))     # j QR
    counts = bytes(b[off(QR_COUNTS):off(QR_COUNTS) + 13])
    assert counts == bytes([3] + [2] * 12), counts.hex()
    b[off(QR_COUNTS):off(QR_COUNTS) + 11] = bytes([4] + [3] * 10)     # ACTION 0..10; ACTION 11 (REPLAY) keeps 2
    old = bytes(b[off(QR_STR):off(QR_STR) + 0x14])
    assert old.startswith(b"COMMAND" + bytes(1)), old
    b[off(QR_STR):off(QR_STR) + 0x14] = b"QUICK RESET".ljust(0x14, bytes(1))
    return len(code)


# ---- practice REPLAY label with the INPUT display on (found 2026-11-24 with ATG's paused emulator: sprite queue entry 96x16 at u=96, v=368) ----
# The practice replay/record code (0x33B5xx) draws the word REPLAY (top right, x = 0x20 + 368 * side, y = 16) as ONE 96x16 sprite taken from the rect
# (96, 368, 96, 16) at 0x3D2778 through `jal 0x302AE0` (0x33B970), i.e. from the atlas that is resident in normal fights (set 3).  The INPUT display keeps
# SPR03 (set 7) resident (tracker byte 0x1CB0C73 == 7); at (96, 368) that atlas holds the letters V W X Y Z [ -> garbage text.  READY / RECORDING... go through the
# text routine 0x3396F0, which indexes ASCII glyphs at the same positions in both atlases, so they stay readable.  Wrapper: with the tracker at 7 the word is drawn
# as six 16x16 glyphs of the SPR03 grey font (u = 16 * (c & 15), v = 0x180 + 16 * ((c >> 4) - 2)) through the INPUT module's sprite helper IN_SPR
# (a0 = x, a1 = y - 16 (0x302AE0 subtracts 16 from y itself: queue entry y = 0 for y = 16), t1 = u, t2 = v); otherwise the original call.
RL_CODE = 0x3AF440
RL_TAB = 0x3AF4E0                       # 6 x (u16 u, u16 v): R E P L A Y
RL_SITE = (0x33B970, 0x0C0C0AB8)        # jal 0x302ae0
RL_GLYPHS = ((32, 0x1B0), (80, 0x1A0), (0, 0x1B0), (192, 0x1A0), (16, 0x1A0), (144, 0x1B0))


def replaylabel_code():
    t_hi, t_lo = hi_lo(0x1CB0C73)
    tb_hi, tb_lo = hi_lo(RL_TAB)
    src = f"""
    lui $t8, {t_hi:#x}
    lbu $t9, {sx(t_lo)}($t8)
    addiu $t7, $zero, 7
    bne $t9, $t7, rl_orig
    nop
    addiu $sp, $sp, -0x30
    sd $ra, 0x28($sp)
    sd $s0, 0x20($sp)
    sd $s1, 0x18($sp)
    sd $s2, 0x10($sp)
    sd $s3, 0x08($sp)
    addu $s0, $a1, $zero
    addu $s1, $a2, $zero
    lui $s2, {tb_hi:#x}
    addiu $s2, $s2, {sx(tb_lo)}
    addiu $s3, $zero, 6
rl_loop:
    lhu $t1, 0($s2)
    lhu $t2, 2($s2)
    addu $a0, $s0, $zero
    addiu $a1, $s1, -16
    jal {IN_SPR:#x}
    nop
    addiu $s0, $s0, 16
    addiu $s2, $s2, 4
    addiu $s3, $s3, -1
    bnez $s3, rl_loop
    nop
    ld $s3, 0x08($sp)
    ld $s2, 0x10($sp)
    ld $s1, 0x18($sp)
    ld $s0, 0x20($sp)
    ld $ra, 0x28($sp)
    jr $ra
    addiu $sp, $sp, 0x30
rl_orig:
    j 0x302ae0
    nop
"""
    return opt_asm(src, RL_CODE)


def patch_replaylabel(b, off):
    code = replaylabel_code()
    assert len(code) <= RL_TAB - RL_CODE, len(code)
    for a, n in ((RL_CODE, len(code)), (RL_TAB, 4 * len(RL_GLYPHS))):
        assert off(a + n) <= ELF_OFF + ELF_FILESZ
        assert not any(b[off(a):off(a) + n]), f"replay label region {a:#x} not zero"
    b[off(RL_CODE):off(RL_CODE) + len(code)] = code
    struct.pack_into("<%dH" % (2 * len(RL_GLYPHS)), b, off(RL_TAB), *[x for g in RL_GLYPHS for x in g])
    site, orig = RL_SITE
    assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
    struct.pack_into("<I", b, off(site), 0x0C000000 | (RL_CODE >> 2))
    return len(code)


# ---- practice SELECT BUTTON function HIT BOX (value 4): in-game collision box display, by Vans (see hitbox_ps2.py) ----
# The drawer sits over dead stdio functions at 0x1141C0..0x1147B0 and is called from the main loop's last draw call (0x1A1A6C).
# The SELECT handler's exit (0x33B41C, our quick reset entry stub) continues at HB_SELECT for values other than 3; HB_SELECT toggles the
# on/off byte for value 4.  Value strings: slot 4 of 0x3D2DD0 ("COMMAND CLEAR", unreachable, no other reference) is renamed.
HB_STR = 0x3D2DD0 + HB.HB_VALUE * 0x14
HB_TR = 0x3AF400              # trampoline of the collision box test (zero run 0x3AF32C..0x3AF500)
HB_FILT = 0x3AF330            # draw order: kind filter at have_kind
HB_AXC = 0x3AF360             # draw order: origin cross only in the last pass
HB_NEXT = 0x3AFB40            # draw order: next pass / finish (zero run 0x3AFB24..0x3AFC00)
HB_ORDER = 0x3AFBF0           # kind of each pass, back to front
HB_PASSES = (8, 2, 3, 4, 5, 6, 1, 7)   # body (green), hurt (blue), counter (light blue), guard (turquoise), projectile (orange), receiver (white), attack (red), throw (magenta, over attack as odabugs)


def patch_hitbox(b, off):
    n = len(HB.HB_WORDS)
    lo, hi = HB.HB_BASE, HB.HB_BASE + 4 * n
    assert off(hi) <= ELF_OFF + ELF_FILESZ
    for site in (QR, QT, DATA):
        assert not lo <= site < hi
    b[off(lo):off(hi)] = struct.pack("<%dI" % n, *HB.HB_WORDS)
    # collision (body) box hidden while [+0x283] & 0x10 (odabugs: playerFlags.collisionActive), e.g. during a roll: the slot-6 test
    # at 0x114294 jumps to a trampoline that also reads that byte (t1 = fighter, t2 = [+0x8C], delay slot loads t3)
    tr = opt_asm(f"""
    srl $t3, $t3, 2
    or $t2, $t2, $t3
    andi $t2, $t2, 4
    .word 0x000A480B
    sll $t1, $t1, 6
    or $s4, $s4, $t1
    addiu $s5, $s2, 0x314
    bnez $s4, tr_go
    nop
    j 0x11440c
    nop
tr_go:
    j 0x1142b4
    nop
""", HB_TR)
    assert off(HB_TR + len(tr)) <= ELF_OFF + ELF_FILESZ and not any(b[off(HB_TR):off(HB_TR) + len(tr)]), "HB_TR not free"
    b[off(HB_TR):off(HB_TR) + len(tr)] = tr
    for a_, orig, new in ((0x114294, 0x000A5082, 0x08000000 | (HB_TR >> 2)), (0x114298, 0x314A0001, 0x924B0283)):
        assert struct.unpack_from("<I", b, off(a_))[0] == orig, hex(a_)
        struct.pack_into("<I", b, off(a_), new)
    site, orig, new = HB.HB_HOOK
    assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
    struct.pack_into("<I", b, off(site), new)
    # draw order: one pass over all objects per box kind (back to front), instead of object by object.  PASS (word 0x11462C, unused in his listing) = the current
    # pass; HB_ORDER = kind per pass.  3 hooks: have_kind (0x114300) skips slots of another kind, `clear` (0x114418) starts the next pass or finishes,
    # `axis` (0x1143B8) draws the origin cross only in the last pass.
    o_hi, o_lo = hi_lo(HB_ORDER)
    flt = opt_asm(f"""
    lui $t1, 0x11
    lw $t2, 0x462c($t1)
    lui $t3, {o_hi:#x}
    addu $t3, $t3, $t2
    lbu $t3, {sx(o_lo)}($t3)
    sll $t3, $t3, 4
    bne $t0, $t3, f_skip
    nop
    j 0x114304
    nop
f_skip:
    j 0x1143ac
    nop
""", HB_FILT)
    nxt = opt_asm(f"""
    lui $t1, 0x11
    lw $t2, 0x462c($t1)
    addiu $t2, $t2, 1
    sltiu $t3, $t2, {len(HB_PASSES)}
    beqz $t3, p_done
    sw $t2, 0x462c($t1)
    lui $s0, 0x9b
    addiu $s0, $s0, 0x6bc0
    lw $s2, 0($s0)
    j 0x114244
    nop
p_done:
    sw $zero, 0x462c($t1)
    lui $t0, 0x9b
    addiu $t0, $t0, 0x6bc0
    j 0x114420
    nop
""", HB_NEXT)
    axc = opt_asm(f"""
    lui $t1, 0x11
    lw $t2, 0x462c($t1)
    addiu $t3, $zero, {len(HB_PASSES) - 1}
    bne $t2, $t3, ax_skip
    nop
    .word 0x792A4680
    j 0x1143c0
    nop
ax_skip:
    j 0x11440c
    nop
""", HB_AXC)
    for a_, code_, cap in ((HB_FILT, flt, 0x30), (HB_AXC, axc, 0x30), (HB_NEXT, nxt, 0xB0)):
        assert len(code_) <= cap, (hex(a_), len(code_))
        assert off(a_ + len(code_)) <= ELF_OFF + ELF_FILESZ and not any(b[off(a_):off(a_) + len(code_)]), f"{a_:#x} not free"
        b[off(a_):off(a_) + len(code_)] = code_
    assert not any(b[off(HB_ORDER):off(HB_ORDER) + len(HB_PASSES)])
    b[off(HB_ORDER):off(HB_ORDER) + len(HB_PASSES)] = bytes(HB_PASSES)
    assert struct.unpack_from("<I", b, off(0x11462C))[0] == 0
    for a_, orig, new in ((0x114300, 0x3C090011, 0x08000000 | (HB_FILT >> 2)),
                          (0x114418, 0x3C08009B, 0x08000000 | (HB_NEXT >> 2)),
                          (0x1143B8, 0x3C090011, 0x08000000 | (HB_AXC >> 2)),
                          (0x1143BC, 0x792A4680, 0x00000000)):
        assert struct.unpack_from("<I", b, off(a_))[0] == orig, hex(a_)
        struct.pack_into("<I", b, off(a_), new)
    counts = bytes(b[off(QR_COUNTS):off(QR_COUNTS) + 13])
    assert counts == bytes([4] + [3] * 10 + [2, 2]), counts.hex()      # as patch_quickreset left them
    b[off(QR_COUNTS):off(QR_COUNTS) + 11] = bytes([5] + [4] * 10)      # value 4 selectable (ACTION 11 keeps 2)
    old = bytes(b[off(HB_STR):off(HB_STR) + 0x14])
    assert old.startswith(b"COMMAND CLEAR" + bytes(1)), old
    b[off(HB_STR):off(HB_STR) + 0x14] = b"HIT BOX".ljust(0x14, bytes(1))
    return 4 * n


# ---- OPTIONS > GRAPHIC SETTING: new row "DISPLAY : DAMAGE/STUN/BOTH/OFF" (byte 0x9CB287, saved at save+0x294FE) ----
# The page = input FUN_003342d0, row objects FUN_003347c0 (task, type in obj[0] selects a draw case through a jump table),
# cursor bar FUN_00334e00.  Rows 0..6 + EXIT(7) become rows 0..6 + DISPLAY(7) + EXIT(8); all rows move up by 32 px (centred next to the
# character preview panel; 16 px would be the minimum so that the eighth row fits above EXIT, y 400).  The three jump tables are copied into the cave and get one more entry.
OPT_RECTS = 0x3AD000       # 5 rect entries (u, v, w, h, p, 0): label, DAMAGE, STUN, BOTH, OFF (atlas SPR00 page 2, p = 0)
OPT_JT_IN = 0x3AD040       # input jump table (8)
OPT_JT_SETUP = 0x3AD060    # setup jump table (12)
OPT_JT_DRAW = 0x3AD0A0     # draw jump table (12)
OPT_ST_IN = 0x3AD100
OPT_ST_SETUP = 0x3AD140
OPT_ST_DRAW = 0x3AD1C0
OPT_ST_SAVE = 0x3AD280
OPT_ST_LOAD = 0x3AD2C0
OPT_ST_SLOT = 0x3AD340     # loads SPR00 page 2 into texture slot 4 and sends it to VRAM (see OPT_RECT_P)
# label, DAMAGE, STUN, BOTH, OFF.  Atlas SPR00 page 2, y 384..447 (empty; must match practice_labels.GRAPHIC_*): the words used to sit on page 5 over the
# JUDGMENT INDICATOR / SINGLE ROUND rows, which GAME OPTION > BATTLE SETTING uses (reported 2026-11-22).  The 5th short of the entry is p = page - 2.
OPT_RECT_LIST = ((0, 384, 160, 32), (0, 416, 112, 32), (160, 384, 80, 32), (112, 416, 80, 32), (192, 416, 64, 32))
# The 5th short of a rect entry is the texture SLOT, not a page offset (slot 0 = SPR00 page 0, 1 = page 3, 2 = page 4, 3 = page 5 while GAME OPTION is open;
# p=0 showed the RANKING button of page 0 in v78).  Slots 4..7 are free, so the setup stub loads SPR00 page 2 (empty at y >= 384) into slot 4 with the
# slot loader 0x3019D0(slot, page pointer); all SPR00 pages are resident from 0xE2D880 in steps of 0x20400 (page 2 = 0xE6E080).
OPT_RECT_P = 4
OPT_PAGE_PTR = 0xE2D880 + 2 * 0x20400
OPT_SAVE_HOOK = (0x2FD6F4, 0x0C049C48)    # jal 0x127120 (a2 = 6) copying 0x9BEC40 -> save+0x294F8
OPT_LOAD_HOOK = (0x2FD9BC, 0x0C049C48)


def opt_asm(src, base):
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)
    enc, n = ks.asm(".set noreorder\n" + numeric_regs(src), base)
    assert_no_pic(bytes(enc), base, f"stub at {base:#x}")
    return bytes(enc)


def opt_stubs():
    o_hi, o_lo = hi_lo(OPT2_ADDR)
    r_hi, r_lo = hi_lo(OPT_RECTS)
    v_hi, v_lo = hi_lo(OPT_RECTS + 12)
    st = {}
    st[OPT_ST_IN] = opt_asm(f"""
    lui $v0, {o_hi:#x}
    lb $a0, {sx(o_lo)}($v0)
    jal 0x3367c0
    addiu $a1, $zero, 4
    lui $v1, {o_hi:#x}
    sb $v0, {sx(o_lo)}($v1)
    j 0x3346c0
    nop
""", OPT_ST_IN)
    # Slot loader 0x3019D0(slot, ptr) only registers the slot and builds its two GIF packets (texture at 0x1CC2180 + 0x60 * slot, CLUT at 0x1CC1E80 + 0x60 * slot);
    # the packets are SENT by the loop of 0x3020A0, which runs over the first [0x1CB0C58] (= 4) slots only.  So slot 4 is registered AND sent here, with the
    # body of that loop (wait 0x10CEE0, send packet 0x1017F0(packet, data), kick 0x101150), texture data = [0x1CB0CB0 + 4 * slot], CLUT data = [0x1CB0CE0 + 4 * slot].
    st[OPT_ST_SLOT] = opt_asm(f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x10($sp)
    addiu $a0, $zero, {OPT_RECT_P}
    lui $a1, {OPT_PAGE_PTR >> 16:#x}
    ori $a1, $a1, {OPT_PAGE_PTR & 0xFFFF:#x}
    jal 0x3019d0
    nop
    jal 0x10cee0
    addu $a0, $zero, $zero
    lui $a1, 0x1cb
    lw $a1, {0xcb0 + 4 * OPT_RECT_P:#x}($a1)
    lui $a0, 0x1cc
    jal 0x1017f0
    addiu $a0, $a0, {0x2180 + 0x60 * OPT_RECT_P:#x}
    addu $a0, $zero, $zero
    jal 0x101150
    addu $a1, $zero, $zero
    jal 0x10cee0
    addu $a0, $zero, $zero
    lui $a1, 0x1cb
    lw $a1, {0xce0 + 4 * OPT_RECT_P:#x}($a1)
    lui $a0, 0x1cc
    jal 0x1017f0
    addiu $a0, $a0, {0x1e80 + 0x60 * OPT_RECT_P:#x}
    addu $a0, $zero, $zero
    jal 0x101150
    addu $a1, $zero, $zero
    ld $ra, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x20
""", OPT_ST_SLOT)
    st[OPT_ST_SETUP] = opt_asm(f"""
    jal {OPT_ST_SLOT:#x}
    nop
    lui $a0, 0x33
    addiu $a0, $a0, 0x47c0
    addiu $a1, $zero, 0
    addiu $a2, $zero, 11
    addiu $a3, $zero, -0x160
    addiu $t0, $zero, {0x70 + 7 * 0x20:#x}
    jal 0x32ff70
    addiu $t1, $zero, 0xc8
    lui $a0, 0x1de
    lw $v0, -0x1838($a0)
    addiu $v0, $v0, 1
    sw $v0, -0x1838($a0)
    j 0x334508
    nop
""", OPT_ST_SETUP)
    st[OPT_ST_DRAW] = opt_asm(f"""
    lui $a0, {r_hi:#x}
    addiu $a0, $a0, {sx(r_lo)}
    addiu $a1, $s1, -0xa0
    jal 0x302ae0
    daddu $a2, $s0, $zero
    addiu $a0, $s2, 0xa8
    daddu $a1, $s1, $zero
    jal 0x302ae0
    daddu $a2, $s0, $zero
    lui $v0, {o_hi:#x}
    lbu $a0, {sx(o_lo)}($v0)
    sltiu $t0, $a0, 4
    bnez $t0, okv
    nop
    addu $a0, $zero, $zero
okv:
    sll $v1, $a0, 1
    addu $v1, $v1, $a0
    sll $v1, $v1, 2
    lui $v0, {v_hi:#x}
    addiu $v0, $v0, {sx(v_lo)}
    addu $a0, $v0, $v1
    addiu $a1, $s1, 0x20
    jal 0x302ae0
    daddu $a2, $s0, $zero
    j 0x334bf8
    nop
""", OPT_ST_DRAW)
    st[OPT_ST_SAVE] = opt_asm(f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x10($sp)
    jal 0x127120
    nop
    lui $t0, {o_hi:#x}
    lbu $t0, {sx(o_lo)}($t0)
    lui $t1, 2
    ori $t1, $t1, 0x94fe
    addu $t1, $s0, $t1
    sb $t0, 0($t1)
    ld $ra, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x20
""", OPT_ST_SAVE)
    st[OPT_ST_LOAD] = opt_asm(f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x10($sp)
    jal 0x127120
    nop
    lui $t1, 2
    ori $t1, $t1, 0x94fe
    addu $t1, $s0, $t1
    lbu $t0, 0($t1)
    sltiu $t2, $t0, 4
    bnez $t2, okl
    nop
    addu $t0, $zero, $zero
okl:
    lui $t1, {o_hi:#x}
    sb $t0, {sx(o_lo)}($t1)
    ld $ra, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x20
""", OPT_ST_LOAD)
    return st


def lui_a0(v):
    hi, lo = hi_lo(v)
    return 0x3C040000 | hi, 0x24840000 | lo


OPT_PATCHES = (
    # input FUN_003342d0: 9 rows, 8 jump table entries (7 = DISPLAY), EXIT index 8
    (0x334588, 0x24050008, 0x24050009),
    (0x3345A8, 0x2C810007, 0x2C810008),
    (0x3346F8, 0x24040007, 0x24040008),
    # setup: 12 objects (11 = DISPLAY row), rows start 16 px higher
    (0x3343C0, 0x28E1000B, 0x28E1000C),
    (0x3343CC, 0x2CE1000B, 0x2CE1000C),
    (0x334474, 0x244800A0, 0x24480070),
    # draw: type 11 allowed
    (0x3347F4, 0x2C61000B, 0x2C61000C),
    # cursor bar: EXIT index 8, rows 16 px higher
    (0x334E0C, 0x24030007, 0x24030008),
    (0x334E28, 0x245000A0, 0x24500070),
)


def patch_optdisplay(b, off):
    import struct as _s
    def rd(a): return _s.unpack_from("<I", b, off(a))[0]
    for a, orig, new in OPT_PATCHES:
        assert rd(a) == orig, hex(a)
        _s.pack_into("<I", b, off(a), new)
    # copied jump tables
    for src, n, dst, stub in ((0x404890, 7, OPT_JT_IN, OPT_ST_IN), (0x4048B0, 11, OPT_JT_SETUP, OPT_ST_SETUP),
                              (0x4048E0, 11, OPT_JT_DRAW, OPT_ST_DRAW)):
        ents = [rd(src + 4 * i) for i in range(n)] + [stub]
        assert not any(b[off(dst):off(dst) + 4 * len(ents)]), hex(dst)
        for i, e in enumerate(ents):
            _s.pack_into("<I", b, off(dst + 4 * i), e)
    for (lui_a, addiu_a, lui_o, addiu_o, new) in ((0x3345B8, 0x3345BC, 0x3C040040, 0x24844890, OPT_JT_IN),
                                                 (0x3343D8, 0x3343E0, 0x3C040040, 0x248448B0, OPT_JT_SETUP),
                                                 (0x334800, 0x334808, 0x3C040040, 0x248448E0, OPT_JT_DRAW)):
        assert rd(lui_a) == lui_o and rd(addiu_a) == addiu_o, hex(lui_a)
        l, a = lui_a0(new)
        _s.pack_into("<I", b, off(lui_a), l)
        _s.pack_into("<I", b, off(addiu_a), a)
    # rect table
    for i, (u, v, w, h) in enumerate(OPT_RECT_LIST):
        assert not any(b[off(OPT_RECTS + 12 * i):off(OPT_RECTS + 12 * i) + 12])
        _s.pack_into("<6h", b, off(OPT_RECTS + 12 * i), u, v, w, h, OPT_RECT_P, 0)
    # stubs
    for a, code in opt_stubs().items():
        assert len(code) <= 0x80, (hex(a), len(code))
        assert not any(b[off(a):off(a) + len(code)]), hex(a)
        b[off(a):off(a) + len(code)] = code
    # save / load hooks
    for (site, orig), stub in ((OPT_SAVE_HOOK, OPT_ST_SAVE), (OPT_LOAD_HOOK, OPT_ST_LOAD)):
        assert rd(site) == orig, hex(site)
        _s.pack_into("<I", b, off(site), 0x0C000000 | (stub >> 2))


# ---- version display: "V1.2" in red at the bottom right of the main menu ----
# The main menu draw task (task fn 0x330D40, scene 0x202) calls the text printer FUN_001788C0 once per glyph before running its own body. The printer
# draws into the currently bound menu texture (white glyphs); the vertex colour (t0 = 0xAARRGGBB, factor about 0.94) tints it to the UI red cb0608.
# Glyph rects: name-entry table GLYPHTAB (same shapes as the Character Setting alphabet), index = position in NAME_ORDER.
# Bump MG_VERSION for every release, then re-run export_hack_patches.py (gfx_hacks.json) and rebuild the patcher.
MG_VERSION = "1.6.1"
VER_CAVE = 0x3B2F00
VER_SITE = 0x330D40                  # addiu sp,sp,-0xa0 ; sd ra,0x90(sp)   (task fn of the main menu draw)
VER_X, VER_Y = 524.0, 409.0          # pixels (640 x 448), left edge of the first glyph; inside the black area, lower right (540 until 1.6; "V1.6.1" is 16 px longer)
VER_COLOR = 0x80D8070A               # tint -> about cb0608 on screen
VER_SCALE = 17.0                     # printer f14 (same value the combo damage display uses)
NAME_ORDER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?\"#$%&'()[]:;,.<>+-*/=_ {}"
VER_ADV = {"1": 10, ".": 6, " ": 8, "6": 12}  # glyph advance in pixels, default 14 ("6" 12: same gap before "." as after "1")


def version_stub():
    import struct as _st
    ks = ks_mod.Ks(ks_mod.KS_ARCH_MIPS, ks_mod.KS_MODE_MIPS64 + ks_mod.KS_MODE_LITTLE_ENDIAN)

    def fbits(v):
        return _st.unpack("<I", _st.pack("<f", v))[0]

    def li(reg, val):
        return [f"lui ${reg}, {(val >> 16) & 0xFFFF:#x}", f"ori ${reg}, ${reg}, {val & 0xFFFF:#x}"]
    gh, gl = hi_lo(GLYPHTAB)
    ch, cl = hi_lo(CTX)
    s = [".set noreorder", "addiu $29, $29, -0x50", "sd $31, 0x48($29)", "sd $4, 0x40($29)", "sd $5, 0x38($29)",
         "sd $6, 0x30($29)", "sd $7, 0x28($29)"]
    x = VER_X
    for ch_ in "V" + MG_VERSION:
        idx = NAME_ORDER.index(ch_)
        s += [f"lui $14, {gh:#x}", f"addiu $14, $14, {gl if gl < 0x8000 else gl - 0x10000}",
              f"addiu $4, $14, {idx * 8}", f"lui $5, {ch:#x}", f"addiu $5, $5, {cl if cl < 0x8000 else cl - 0x10000}",
              "daddu $6, $zero, $zero", "addiu $7, $zero, 1"]
        s += li(8, VER_COLOR)
        s += ["daddu $9, $zero, $zero"]
        s += li(10, fbits(x)) + ["mtc1 $10, $f12"]
        s += li(10, fbits(VER_Y)) + ["mtc1 $10, $f13"]
        s += li(10, fbits(VER_SCALE)) + ["mtc1 $10, $f14"]
        s += li(10, fbits(512.0)) + ["mtc1 $10, $f15"]
        s += [f"jal {PRINTER:#x}", "nop"]
        x += VER_ADV.get(ch_, 14)
    s += ["ld $31, 0x48($29)", "ld $4, 0x40($29)", "ld $5, 0x38($29)", "ld $6, 0x30($29)", "ld $7, 0x28($29)",
          "addiu $29, $29, 0x50",
          "addiu $29, $29, -0xa0", "sd $31, 0x90($29)", f"j {VER_SITE + 8:#x}", "nop"]
    return bytes(ks.asm("\n".join(s), VER_CAVE)[0])


def patch_version(b, off):
    code = version_stub()
    assert len(code) <= 0x300, len(code)          # zero run ends 0x3B34BC; "V1.6.1" needs 0x280
    assert not any(b[off(VER_CAVE):off(VER_CAVE) + len(code)]), hex(VER_CAVE)
    assert struct.unpack_from("<I", b, off(VER_SITE))[0] == 0x27BDFF60, "addiu sp,sp,-0xa0"
    assert struct.unpack_from("<I", b, off(VER_SITE + 4))[0] == 0xFFBF0090, "sd ra,0x90(sp)"
    b[off(VER_CAVE):off(VER_CAVE) + len(code)] = code
    struct.pack_into("<I", b, off(VER_SITE), 0x08000000 | (VER_CAVE >> 2))     # j VER_CAVE (the cave re-runs the replaced prologue)
    struct.pack_into("<I", b, off(VER_SITE + 4), 0)                           # delay slot: nop


# Practice-mode build stages (cumulative) for hardware bisecting: --stage N builds only the first N groups.
# 1 display+pmlayout+input (pre QUICK RESET state), 2 +movelist stub, 3 +gauge, 4 +quickreset, 5 +cmdenemy, 6 +cmdedit, 7 +guardall (= everything)
PRACTICE_STAGES = ("display", "pmlayout", "input", "movelist", "gauge", "quickreset", "cmdenemy", "cmdedit", "guardall")
STAGE_LAST_GROUP = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9}


def patch_frameadv(b, off):
    """frame advantage display in practice (frameadv_ps2.py): logic at FA_CODE, drawer at FA_DRAW, state at FA_DATA (all zero run)."""
    tick = opt_asm(FA.tick_source(PRACTICE_FLAG), FA.FA_CODE)
    draw = opt_asm(FA.draw_source(), FA.FA_DRAW)
    assert FA.FA_CODE + len(tick) <= FA.FA_DRAW, hex(len(tick))
    assert FA.FA_DRAW + len(draw) <= FA.FA_DATA, hex(len(draw))
    for a, code in ((FA.FA_CODE, tick), (FA.FA_DRAW, draw)):
        assert not any(b[off(a):off(a) + len(code)]), f"frameadv region {a:#x} not zero"
        b[off(a):off(a) + len(code)] = code
    assert not any(b[off(FA.FA_DATA):off(FA.FA_DATA) + FA.FA_DATA_SIZE]), "frameadv data not zero"
    return len(tick), len(draw)


GA_LIST_SHORT = 0x3D2F38          # vanilla GUARD list of the other ACTIONs: OFF, DOWN, S-SHIFT


def patch_ukemi(b, off):
    """practice UKEMI option (ukemi_ps2.py): own tech routine in the dummy AI, DOWN removed from the GUARD lists, option byte reset and saved."""
    code = opt_asm(UK.ukemi_source(GA_MODE, GA_RNG), UK.UK_CODE)
    assert UK.UK_CODE + len(code) <= UK.UK_SAVE, hex(len(code))
    sv = opt_asm(UK.save_source(OPT_ST_SAVE), UK.UK_SAVE)
    ld = opt_asm(UK.load_source(OPT_ST_LOAD), UK.UK_LOAD)
    assert UK.UK_SAVE + len(sv) <= UK.UK_LOAD and UK.UK_LOAD + len(ld) <= UKM_ST
    for a, c in ((UK.UK_CODE, code), (UK.UK_SAVE, sv), (UK.UK_LOAD, ld)):
        assert not any(b[off(a):off(a) + len(c)]), f"ukemi region {a:#x} not zero"
        b[off(a):off(a) + len(c)] = c
    assert b[off(UK.UK_CHOICE)] == 0
    cm = opt_asm(UK.commit_source(), UK.UK_COMMIT)
    assert not any(b[off(UK.UK_COMMIT):off(UK.UK_COMMIT) + len(cm)]) and len(cm) <= 0x80
    b[off(UK.UK_COMMIT):off(UK.UK_COMMIT) + len(cm)] = cm
    csite, corig = UK.UK_COMMIT_SITE
    assert struct.unpack_from("<I", b, off(csite))[0] == corig, hex(csite)
    struct.pack_into("<I", b, off(csite), 0x0C000000 | (UK.UK_COMMIT >> 2))
    fl = opt_asm(UK.filter_source(), UK.UK_FILTER)
    assert not any(b[off(UK.UK_FILTER):off(UK.UK_FILTER) + len(fl)]) and len(fl) <= 0x80
    b[off(UK.UK_FILTER):off(UK.UK_FILTER) + len(fl)] = fl
    s1, o1, s2, o2 = UK.UK_FILTER_SITE
    assert struct.unpack_from("<II", b, off(s1)) == (o1, o2) and s2 == s1 + 4
    struct.pack_into("<II", b, off(s1), 0x08000000 | (UK.UK_FILTER >> 2), 0)
    site, orig = UK.UK_HOOK
    assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
    struct.pack_into("<I", b, off(site), 0x0C000000 | (UK.UK_CODE >> 2))
    # GUARD lists without DOWN (4): the full list of the ACTIONs in GA_ACTIONS and the short list (OFF, DOWN, S-SHIFT) of the others
    assert bytes(b[off(GA_LIST):off(GA_LIST) + GA_NVAL + 1]) == bytes(list(range(GA_NVAL)) + [0xFF])
    new = [v for v in range(GA_NVAL) if v != 4] + [0xFF]
    b[off(GA_LIST):off(GA_LIST) + GA_NVAL + 1] = bytes(new + [0])
    for i in range(16):
        if struct.unpack_from("<I", b, off(GA_PTR_TAB + 4 * i))[0] == GA_LIST:
            assert b[off(GA_CNT_TAB + i)] == GA_NVAL, i
            b[off(GA_CNT_TAB + i)] = GA_NVAL - 1
    assert bytes(b[off(GA_LIST_SHORT):off(GA_LIST_SHORT) + 4]) == bytes([0, 4, 7, 0])
    b[off(GA_LIST_SHORT):off(GA_LIST_SHORT) + 4] = bytes([0, 7, 0xFF, 0])
    for i in range(16):
        if struct.unpack_from("<I", b, off(GA_PTR_TAB + 4 * i))[0] == GA_LIST_SHORT:
            assert b[off(GA_CNT_TAB + i)] == 3, i
            b[off(GA_CNT_TAB + i)] = 2
    # default reset clears 13 bytes (0x9CB240..0x24C, incl. INPUT and UKEMI)
    assert struct.unpack_from("<I", b, off(0x336E28))[0] == 0x2406000C
    struct.pack_into("<I", b, off(0x336E28), 0x2406000D)
    # save / load: the OPTIONS DISPLAY stubs are wrapped
    for (site, _orig), stub, new_stub in ((OPT_SAVE_HOOK, OPT_ST_SAVE, UK.UK_SAVE), (OPT_LOAD_HOOK, OPT_ST_LOAD, UK.UK_LOAD)):
        assert struct.unpack_from("<I", b, off(site))[0] == 0x0C000000 | (stub >> 2), hex(site)
        struct.pack_into("<I", b, off(site), 0x0C000000 | (new_stub >> 2))
    return len(code)


# ---- practice menu row UKEMI (under GUARD), rows 22 px apart (ATG 2026-11-24) ----
# Visual order: 0 CONTROL .. 4 GUARD, 5 UKEMI, 6 LIFE, 7 GAUGE, 8 DISPLAY, 9 INPUT, 10 STAGE SELECT, 11 SELECT BUTTON, 12 COMMAND, 13 KEY SETTING,
# 14 CHARACTER SELECT;
# y = PM_BASE_Y + 22 * v.  Cursor index i = v + 1 (0 GAME START, 16 GAME EXIT).  Applied on top of patch_pmlayout (which inserted INPUT).
# New tables (the old places have no room for one more entry): draw jump table 30 entries (UKEMI label 0x1C / value 0x1D), input jump
# table 13 entries (UKEMI = index 6), cursor position table 17 entries (6 lui/addiu users).  Label: SPR01.GRC page 1 at UKM_RECT, right of
# GUARD, where the vertical "SELECT BUTTON TO DEFAULT" text was (removed from the menu since the INPUT row); the rect is 19 px high, drawn 8 px lower.
UKM_PITCH = 22
UKM_JT_DRAW = 0x3B2400
UKM_JT_IN = 0x3B2480
UKM_CURSOR = 0x3B2500
UKM_RECT = 0x3B25A0
UKM_STR = 0x3B2600
UKM_ST = 0x3B2100                 # stubs: +0 rowy, +0x40 after (up to 0xC0), +0x100 cmdy, +0x140 dlab, +0x180 dval, +0x220 input
UKM_RECT_UVWH = (181, 268, 75, 19)
UKM_LABEL_DY = 8
UKM_CURSOR_SITES = ((0x3392E4, 0x3392F4), (0x339308, 0x339310), (0x339D60, 0x339D68), (0x339D6C, 0x339D74),
                    (0x339D98, 0x339DA0), (0x339DA4, 0x339DAC))


def _mul22(dst, src):
    """dst = 22 * src (uses $t8 / $t9)"""
    return f"""
    sll $t9, {src}, 4
    sll $t8, {src}, 2
    addu $t9, $t9, $t8
    sll $t8, {src}, 1
    addu {dst}, $t9, $t8
"""


def _row_pair(lt, vt, y):
    return f"""
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addu $a1, $zero, $zero
    addiu $a2, $zero, {lt:#x}
    addiu $a3, $zero, -0x120
    addiu $t0, $zero, {y:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x40
    lui $a0, 0x34
    addiu $a0, $a0, -0x7480
    addiu $a1, $zero, 1
    addiu $a2, $zero, {vt:#x}
    addiu $a3, $zero, 0x2e0
    addiu $t0, $zero, {y:#x}
    jal 0x336ea0
    addiu $t1, $zero, 0x200
"""


def ukemi_menu_stubs():
    assert UKM_PITCH == 22
    yin, yuk = PM_BASE_Y + 9 * UKM_PITCH, PM_BASE_Y + 5 * UKM_PITCH
    u_hi, u_lo = hi_lo(UK.UK_ADDR)
    r_hi, r_lo = hi_lo(UKM_RECT)
    s_hi, s_lo = hi_lo(UKM_STR)
    a = UKM_ST
    src = {
        # row y of the vanilla rows (v1 = row 0..9): 22 * v1, from LIFE on one row lower (UKEMI), from STAGE SELECT on two (+ INPUT)
        a: _mul22("$s0", "$v1") + f"""
    addiu $s0, $s0, {PM_BASE_Y}
    slti $at, $v1, 5
    bnez $at, ry_out
    nop
    addiu $s0, $s0, {UKM_PITCH}
    slti $at, $v1, 8
    bnez $at, ry_out
    nop
    addiu $s0, $s0, {UKM_PITCH}
ry_out:
    jr $ra
    nop
""",
        # after the DISPLAY pair (counter 0x11): INPUT and UKEMI objects
        a + 0x40: f"""
    addiu $t2, $zero, 0x11
    bne $a0, $t2, af_out
    nop
    addiu $sp, $sp, -0x30
    sd $ra, 0x20($sp)
{_row_pair(0x1A, 0x1B, yin)}
{_row_pair(0x1C, 0x1D, yuk)}
    ld $ra, 0x20($sp)
    addiu $sp, $sp, 0x30
af_out:
    j 0x338190
    nop
""",
        # COMMAND / KEY SETTING / CHARACTER SELECT (v1 = 0..2): y = BASE + 22 * (12 + v1), then the object constructor (ra = caller)
        a + 0x100: _mul22("$t0", "$v1") + f"""
    j 0x336ea0
    addiu $t0, $t0, {PM_BASE_Y + 12 * UKM_PITCH}
""",
        a + 0x140: f"""
    lui $a0, {r_hi:#x}
    addiu $a0, $a0, {sx(r_lo)}
    daddu $a1, $s2, $zero
    jal 0x302ae0
    addiu $a2, $s1, {UKM_LABEL_DY}
    j 0x3392bc
    nop
""",
        # value: "-----" (vanilla string 0x3D2E50) while the option has no effect: CONTROL not CPU, or ACTION 7 / 8 / >= 11 (same rule as the tech routine)
        a + 0x180: """
    lui $t2, 0x9d
    lbu $t3, -0x4dc0($t2)
    bnez $t3, uv_dash
    nop
    lbu $t3, -0x4dbf($t2)
    addiu $t4, $zero, 7
    beq $t3, $t4, uv_dash
    nop
    addiu $t4, $zero, 8
    beq $t3, $t4, uv_dash
    nop
    sltiu $t4, $t3, 11
    beqz $t4, uv_dash
    nop
""" + f"""
    lui $v0, {u_hi:#x}
    lbu $v1, {sx(u_lo)}($v0)
    sltiu $t0, $v1, 4
    bnez $t0, uv_ok
    nop
    addu $v1, $zero, $zero
uv_ok:
    sll $a2, $v1, 4
    sll $v1, $v1, 2
    addu $a2, $a2, $v1
    lui $t1, {s_hi:#x}
    addiu $t1, $t1, {sx(s_lo)}
    addu $a2, $a2, $t1
    b uv_draw
    nop
uv_dash:
    lui $a2, 0x3d
    addiu $a2, $a2, 0x2e50
uv_draw:
    daddu $a0, $s2, $zero
    jal 0x3394c0
    daddu $a1, $s1, $zero
    j 0x3392bc
    nop
""",
        # input: locked like the value
        a + 0x220: """
    lui $t2, 0x9d
    lbu $t3, -0x4dc0($t2)
    bnez $t3, ui_out
    nop
    lbu $t3, -0x4dbf($t2)
    addiu $t4, $zero, 7
    beq $t3, $t4, ui_out
    nop
    addiu $t4, $zero, 8
    beq $t3, $t4, ui_out
    nop
    sltiu $t4, $t3, 11
    beqz $t4, ui_out
    nop
""" + f"""
    lui $v0, {u_hi:#x}
    lb $a0, {sx(u_lo)}($v0)
    daddu $a2, $s1, $zero
    jal 0x3366d0
    addiu $a1, $zero, 4
    lui $v1, {u_hi:#x}
    sb $v0, {sx(u_lo)}($v1)
ui_out:
    j 0x3388dc
    nop
""",
    }
    return {k: opt_asm(v, k) for k, v in src.items()}


def patch_ukemi_menu(b, off):
    rd = lambda a: struct.unpack_from("<I", b, off(a))[0]

    def wr(a, v):
        struct.pack_into("<I", b, off(a), v)
    st = ukemi_menu_stubs()
    keys = sorted(st) + [UKM_ST + 0x280]
    for a, c in st.items():
        assert a + len(c) <= keys[keys.index(a) + 1], (hex(a), len(c))
        assert not any(b[off(a):off(a) + len(c)]), f"ukemi menu stub region {a:#x} not zero"
        b[off(a):off(a) + len(c)] = c
    a = UKM_ST
    assert rd(0x33806C) == 0x0C000000 | (PM_ST_ROWY >> 2)
    wr(0x33806C, 0x0C000000 | (a >> 2))
    assert rd(0x3380D0) == 0x08000000 | (PM_ST_AFTER >> 2)
    wr(0x3380D0, 0x08000000 | ((a + 0x40) >> 2))
    assert rd(0x33810C) == 0x0C000000 | (0x336EA0 >> 2)
    wr(0x33810C, 0x0C000000 | ((a + 0x100) >> 2))
    # jump tables: draw 28 -> 30 entries, input 12 -> 13 (UKEMI = index 6, after GUARD)
    ents = [rd(PM_JT_DRAW + 4 * i) for i in range(28)] + [a + 0x140, a + 0x180]
    in_ents = [rd(PM_JT_IN + 4 * i) for i in range(12)]
    in_ents = in_ents[:6] + [a + 0x220] + in_ents[6:]
    for base, e in ((UKM_JT_DRAW, ents), (UKM_JT_IN, in_ents)):
        assert not any(b[off(base):off(base) + 4 * len(e)])
        for i, x in enumerate(e):
            wr(base + 4 * i, x)
    for lui_a, addiu_a, old, new in ((0x338BBC, 0x338BC0, PM_JT_DRAW, UKM_JT_DRAW), (0x338534, 0x33853C, PM_JT_IN, UKM_JT_IN)):
        oh, ol = hi_lo(old)
        assert rd(lui_a) == 0x3C030000 | oh and rd(addiu_a) == 0x24630000 | ol, hex(lui_a)
        nh, nl = hi_lo(new)
        wr(lui_a, 0x3C030000 | nh)
        wr(addiu_a, 0x24630000 | nl)
    # bounds and cursor indices (everything from STAGE SELECT on moves one down)
    for site, old, new in ((0x338BAC, 0x2C61001C, 0x2C61001E), (0x338528, 0x2C41000C, 0x2C41000D),
                           (0x3384CC, 0x24050010, 0x24050011), (0x3384F4, 0x24050010, 0x24050011),
                           (0x338988, 0x2403000C, 0x2403000D), (0x338998, 0x2402000D, 0x2402000E),
                           (0x3389A4, 0x2402000F, 0x24020010), (0x3389B0, 0x2402000E, 0x2402000F),
                           (0x33939C, 0x2402000F, 0x24020010),
                           # cursor after returning from a sub-screen: vanilla 0xB (COMMAND, FUN_00339A40) and 0xC (KEY SETTING); patch_pmlayout
                           # (INPUT row) never moved them, so the cursor came back one row too high (ATG's "cursor not on COMMAND" bug)
                           (0x339A44, 0x2404000B, 0x2404000D), (0x33993C, 0x2403000C, 0x2403000E)):
        assert rd(site) == old, (hex(site), hex(rd(site)))
        wr(site, new)
    # cursor position table, 17 entries (the bar sits 24 px below the row y, like the vanilla table)
    tab = [(416, 64)] + [(32, PM_BASE_Y + 24 + UKM_PITCH * (i - 1)) for i in range(1, 16)] + [(416, 456)]
    assert not any(b[off(UKM_CURSOR):off(UKM_CURSOR) + 8 * len(tab)])
    for i, (x, y) in enumerate(tab):
        struct.pack_into("<ii", b, off(UKM_CURSOR + 8 * i), x, y)
    for lui_a, addiu_a in UKM_CURSOR_SITES:
        lw, aw = rd(lui_a), rd(addiu_a)
        assert lw & 0xFFFF == 0x3D and (lw >> 26) == 0x0F and aw & 0xFFFF in (0x2830, 0x2834), hex(lui_a)
        k = (aw & 0xFFFF) - 0x2830
        nh, nl = hi_lo(UKM_CURSOR + k)
        wr(lui_a, (lw & 0xFFFF0000) | nh)
        wr(addiu_a, (aw & 0xFFFF0000) | nl)
    # GUARD label rect (entry 14, x 96 w 96) narrowed to its art (ends at x 180): it showed the left edge of the UKEMI label at x 181
    assert struct.unpack_from("<4h", b, off(0x3D2640 + 12 * 14)) == (96, 256, 96, 32)
    struct.pack_into("<h", b, off(0x3D2640 + 12 * 14 + 4), UKM_RECT_UVWH[0] - 96)
    # label rect and value strings
    assert not any(b[off(UKM_RECT):off(UKM_RECT) + 12]) and not any(b[off(UKM_STR):off(UKM_STR) + 0x50])
    struct.pack_into("<6h", b, off(UKM_RECT), *UKM_RECT_UVWH, 1, 0)
    for i, t in enumerate(UK.UK_STRINGS):
        b[off(UKM_STR + 0x14 * i):off(UKM_STR + 0x14 * i) + len(t)] = t.encode("ascii")


def patch_elf(elf: bytes, hitbox=True, unlock=True, rematch=True, samechars=True, skiplogos=True, display=True, optdisplay=True, stage=7, qt_stub=False, version=True, frameadv=True, ukemi=True):
    global CX_CMD_ROW
    CX_CMD_ROW = 13 if ukemi else 12           # cursor index of the COMMAND row (the UKEMI row shifts it by one)
    b = bytearray(elf)
    off = lambda v: v - ELF_BASE + ELF_OFF
    if skiplogos:
        patch_skiplogos(b, off)
    if version:
        patch_version(b, off)
    if display:
        active = set(PRACTICE_STAGES[:STAGE_LAST_GROUP[stage]])
        patch_display(b, off, frameadv)
        patch_pmlayout(b, off)
        patch_input(b, off)
        patch_replaylabel(b, off)
        if "cmdenemy" in active:
            patch_cmdenemy(b, off)
        if "cmdedit" in active:
            patch_cmdedit(b, off)
        if "quickreset" in active:
            patch_quickreset(b, off, hitbox)
            if hitbox:
                patch_hitbox(b, off)
            if qt_stub:            # bisect aid: keep the QR code but make the per-frame fixer QT a no-op
                struct.pack_into("<II", b, off(QT), 0x03E00008, 0)
        else:                      # the HUD wrapper still calls QT every frame: leave a harmless "jr ra / nop"
            assert not any(b[off(QT):off(QT) + 8]), "QT region not zero"
            struct.pack_into("<II", b, off(QT), 0x03E00008, 0)
        if "gauge" in active:
            patch_gauge(b, off)
        if "movelist" in active:
            patch_movelist(b, off)
        if "guardall" in active:
            patch_guardall(b, off)
    if optdisplay:
        patch_optdisplay(b, off)
    if ukemi and display and optdisplay and "guardall" in set(PRACTICE_STAGES[:STAGE_LAST_GROUP[stage]]):
        patch_ukemi(b, off)
        patch_ukemi_menu(b, off)
    if samechars:
        patch_samechars(b, off)
    if rematch:
        patch_rematch(b, off)
    if unlock:
        st1, st2 = unlock_stubs()
        for a, st in ((STUB1, st1), (STUB2, st2)):
            assert len(st) <= 0x40 and not any(b[off(a):off(a) + len(st)])
            b[off(a):off(a) + len(st)] = st
        for site, orig, _ in (HOOK_INIT, HOOK_LOAD):
            assert struct.unpack_from("<I", b, off(site))[0] == orig, hex(site)
        struct.pack_into("<I", b, off(HOOK_INIT[0]), 0x0C000000 | (STUB1 >> 2))
        struct.pack_into("<I", b, off(HOOK_LOAD[0]), 0x0C000000 | (STUB2 >> 2))
    if display and frameadv:
        patch_frameadv(b, off)
    code = assemble(display, display and frameadv)
    assert len(code) < 0x800, len(code)   # cave 0x3AC000-0x3AC7FF, strings at 0x3AC800
    # verify target regions are zero (and inside the file-backed segment)
    for a, n in ((DATA, 0x80), (CAVE, len(code))):
        assert off(a + n) <= ELF_OFF + ELF_FILESZ
        assert not any(b[off(a):off(a) + n]), f"region {a:#x} not zero"
    b[off(CAVE):off(CAVE) + len(code)] = code
    if display:
        # practice: new HIT COMBO sprites of a side with INPUT on are registered invisible (stub right after the HUD cave code)
        rv_addr = CAVE + ((len(code) + 7) & ~7)
        rv = regvis_stub(rv_addr)
        assert rv_addr + len(rv) <= STRTAB, hex(rv_addr + len(rv))
        assert not any(b[off(rv_addr):off(rv_addr) + len(rv)]), f"region {rv_addr:#x} not zero"
        b[off(rv_addr):off(rv_addr) + len(rv)] = rv
        assert struct.unpack_from("<I", b, off(REGVIS_HOOK[0]))[0] == REGVIS_HOOK[1], hex(REGVIS_HOOK[0])
        struct.pack_into("<I", b, off(REGVIS_HOOK[0]), 0x0C000000 | (rv_addr >> 2))
    for a, v in INIT.items():
        struct.pack_into("<I", b, off(a), v)
    for a, v in INIT_BYTES.items():
        b[off(a):off(a) + len(v)] = v
    if display:
        struct.pack_into("<I", b, off(PRACTICE_FLAG), 1)
    hi, lo = hi_lo(CAVE)
    for lui_a, addiu_a in HOOKS:
        assert struct.unpack_from("<I", b, off(lui_a))[0] == 0x3C040019, hex(lui_a)   # lui $a0,0x19
        assert struct.unpack_from("<I", b, off(addiu_a))[0] == 0x24842710, hex(addiu_a)  # addiu $a0,$a0,0x2710
        struct.pack_into("<I", b, off(lui_a), 0x3C040000 | hi)
        struct.pack_into("<I", b, off(addiu_a), 0x24840000 | lo)
    return bytes(b), code


def find_elf_in_iso(f):
    def rb(o, n): f.seek(o); return f.read(n)
    pvd = rb(16 * 2048, 2048)
    rl, rs = struct.unpack_from("<I", pvd, 156 + 2)[0], struct.unpack_from("<I", pvd, 156 + 10)[0]
    d = rb(rl * 2048, rs); p = 0
    while p < len(d) and d[p]:
        ln, nl = d[p], d[p + 32]
        name = d[p + 33:p + 33 + nl].decode("ascii", "replace")
        if name.startswith("SLPS_256.60"):
            return struct.unpack_from("<I", d, p + 2)[0], struct.unpack_from("<I", d, p + 10)[0]
        p += ln
    raise SystemExit("ELF not found in ISO")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf"); ap.add_argument("--out")
    ap.add_argument("--iso"); ap.add_argument("--out-iso")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--no-hitbox", action="store_true", help="skip HIT BOX (SELECT BUTTON value 4) in practice")
    ap.add_argument("--no-unlock", action="store_true", help="skip the unlock-all patch")
    ap.add_argument("--no-rematch", action="store_true", help="skip the quick-rematch patch")
    ap.add_argument("--no-samechars", action="store_true", help="skip the same-chars patch")
    ap.add_argument("--no-version", action="store_true", help="skip the main menu version text")
    ap.add_argument("--no-skiplogos", action="store_true", help="keep all start-up logos")
    ap.add_argument("--no-optdisplay", action="store_true", help="skip the DISPLAY row in OPTIONS > GRAPHIC SETTING")
    ap.add_argument("--no-display", action="store_true", help="skip the practice DISPLAY option (stun line + menu row)")
    ap.add_argument("--stage", type=int, default=7, choices=sorted(STAGE_LAST_GROUP), help="practice stages 1..7 (7 = everything), see PRACTICE_STAGES")
    ap.add_argument("--qt-stub", action="store_true", help="bisect aid: replace the per-frame fixer QT by 'jr ra'")
    a = ap.parse_args()
    if a.iso:
        with open(a.iso, "rb") as f:
            lba, size = find_elf_in_iso(f)
            f.seek(lba * 2048); elf = f.read(size)
    else:
        elf = open(a.elf, "rb").read()
        lba = size = None
    patched, code = patch_elf(elf, hitbox=not a.no_hitbox, unlock=not a.no_unlock, rematch=not a.no_rematch, samechars=not a.no_samechars, skiplogos=not a.no_skiplogos, version=not a.no_version, display=not a.no_display, optdisplay=not a.no_optdisplay, stage=a.stage, qt_stub=a.qt_stub)
    print(f"cave {CAVE:#x}: {len(code):#x} bytes; hooks patched at {[hex(x) for p in HOOKS for x in p]}")
    if a.dump:
        md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 + capstone.CS_MODE_LITTLE_ENDIAN)
        for i in md.disasm(code, CAVE):
            print(f"{i.address:#x}: {i.mnemonic} {i.op_str}")
    if a.out:
        open(a.out, "wb").write(patched); print("wrote", a.out)
    if a.out_iso:
        assert a.iso and len(patched) == size
        shutil.copyfile(a.iso, a.out_iso)
        with open(a.out_iso, "r+b") as f:
            f.seek(lba * 2048); f.write(patched)
        print("wrote", a.out_iso)


if __name__ == "__main__":
    main()
