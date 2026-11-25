"""KOF XI PS2 (JP): frame advantage display for PRACTICE (2026-11-24).

After every contact (hit, block, throw, trade) both sides' first "free" frame is measured; when both are free, each side shows its own
value under its own HP bar, as an extra line of the DMG/STUN block: "+3" blue, "-3" red, "+0" white (no suffix, ATG 2026-11-24).

The rule was found with a PINE recorder and input probes in PCSX2 (research scripts, not part of this repository):
* FREE = first frame after the contact in which the character is not busy.  That frame is the game's guard-only / buffer frame on
  every side (normals, rolls, hitstun, guard stun, getup; the first landing frame), so the difference gives the wiki convention.
* busy = attack (+0x490 & 3) | hit stop (+0x494 bit 27) | reaction (+0x494 bit 0: hit, throw, knockdown, getup) | guard stun (+0x530 0x400)
  | airborne (pose byte +0x27E == 2) | uninterruptible movement (+0x48C mask BUSY_48C: jump start, jump, backdash, rolls, shift).
* contact = rising edge of reaction or hit stop on either side; a contact within 3 frames of the window start belongs to it (the
  victim's hit stop starts one frame after the attacker's).  Air hits count like any other hit (the victim is busy while airborne,
  through the knockdown and the getup); DROP_AIR = True would hide them.
  A window without result after 600 frames is dropped.

Code at FA_CODE (zero run 0x3A2D72..0x3AB008 of the executable), state at FA_DATA.  The HUD wrapper calls fa_tick(side) once per
side and frame (it works only for side 0, both sides at once).  Frames are counted with an own counter (D_LAST), advanced by every
side-0 call: the HUD task does not run while the game is paused, the global tick 0x9BDA70 does (opening the practice menu during a
knockdown added the whole pause to the getup, up to +140; ATG 2026-11-24) and fa_draw(side, center x, y) after its last line.
"""

FA_CODE = 0x3A8000
FA_DRAW = 0x3A8400
FA_DATA = 0x3A9800            # 0x80 bytes
FA_DATA_SIZE = 0x80

TICK = 0x9BDA70               # global game tick: keeps running in the pause menu, NOT used (see D_LAST)
TEAM0 = 0x9BDB50
TEAM_STRIDE = 0x248
MODE_ADDR = 0x9E9780
PRINTER = 0x1788C0
CTX = 0x9BD538
GLYPHTAB = 0x363930

BUSY_48C = 0x20 | 0x80 | 0x100 | 0x400 | 0x400000 | 0x01000000 | 0x02000000 | 0x10000000 | 0x2000 | 0x4000
TIMEOUT = 600
SAME_CONTACT = 3
DROP_AIR = False             # True: air hits show nothing (first version); ATG 2026-11-24: count them, air hits often knock down

# name-entry glyph indices (NAME_ORDER in the builder)
G_PLUS, G_MINUS, G_F, G_SPACE = 54, 55, 5, 60
ADV, SPACE_ADV = 14, 8
COL_PLUS = 0xFF50B4FF         # 0xAARRGGBB vertex colour of the printer (white glyphs are tinted): light blue
COL_MINUS = 0xFFFF4040        # red
COL_ZERO = 0xFFFFFFFF         # white

# FA_DATA layout (u32)
D_LAST, D_ACTIVE, D_T0, D_AIR = 0x00, 0x04, 0x08, 0x0C    # D_LAST = own frame counter (HUD task frames)
D_SIDE = 0x10                 # + side * 0x20
S_PREACT, S_PREHS, S_PREAIR, S_FREE, S_VAL, S_VALID, S_BUSY, S_REACT = 0, 4, 8, 0xC, 0x10, 0x14, 0x18, 0x1C
D_HS = 0x50                   # + side * 8: hit stop now, +4 airborne now


def hi_lo(v):
    lo = v & 0xFFFF
    hi = (v >> 16) + (1 if lo & 0x8000 else 0)
    return hi & 0xFFFF, lo


def sx(v):
    return v - 0x10000 if v & 0x8000 else v


def tick_source(practice_flag):
    m_hi, m_lo = hi_lo(MODE_ADDR)
    f_hi, f_lo = hi_lo(practice_flag)
    d_hi, d_lo = hi_lo(FA_DATA)
    t_hi, t_lo = hi_lo(TEAM0)
    b_hi, b_lo = hi_lo(BUSY_48C)
    s = [f"""
    bnez $a0, fa_ret0
    nop
    lui $t0, {m_hi:#x}
    lbu $t1, {sx(m_lo)}($t0)
    addiu $t2, $zero, 8
    bne $t1, $t2, fa_ret0
    nop
    lui $t0, {f_hi:#x}
    lw $t1, {sx(f_lo)}($t0)
    beqz $t1, fa_ret0
    nop
    lui $t8, {d_hi:#x}
    addiu $t8, $t8, {sx(d_lo)}
    lw $t9, {D_LAST}($t8)
    addiu $t9, $t9, 1
    sw $t9, {D_LAST}($t8)
"""]
    # per side state (unrolled)
    for side in (0, 1):
        sd = D_SIDE + side * 0x20
        s.append(f"""
    lui $t0, {t_hi:#x}
    addiu $t0, $t0, {sx(t_lo) + side * TEAM_STRIDE}
    lbu $t1, 3($t0)
    sll $t1, $t1, 2
    addu $t1, $t0, $t1
    lw $t1, 0x78($t1)
    beqz $t1, fa_ret0
    nop
    lw $t1, 0x10($t1)
    beqz $t1, fa_ret0
    nop
    lw $t2, 0x494($t1)
    srl $t3, $t2, 27
    andi $t3, $t3, 1
    sw $t3, {D_HS + side * 8}($t8)
    andi $t4, $t2, 1
    lw $t5, 0x530($t1)
    srl $t5, $t5, 10
    andi $t5, $t5, 1
    or $t4, $t4, $t5
    sw $t4, {sd + S_REACT}($t8)
    lbu $t5, 0x27E($t1)
    andi $t5, $t5, 0xF
    addiu $t6, $zero, 2
    xor $t5, $t5, $t6
    sltiu $t5, $t5, 1
    sw $t5, {D_HS + side * 8 + 4}($t8)
    lw $t6, 0x490($t1)
    andi $t6, $t6, 3
    or $t6, $t6, $t3
    or $t6, $t6, $t4
    or $t6, $t6, $t5
    lw $t7, 0x48C($t1)
    lui $t2, {b_hi:#x}
    ori $t2, $t2, {b_lo:#x}
    and $t7, $t7, $t2
    or $t6, $t6, $t7
    sw $t6, {sd + S_BUSY}($t8)
""")
    # contact detection
    s.append("    addu $t7, $zero, $zero\n")
    for side in (0, 1):
        sd = D_SIDE + side * 0x20
        s.append(f"""
    lw $t1, {sd + S_REACT}($t8)
    lw $t2, {sd + S_PREACT}($t8)
    sltu $t3, $t2, $t1
    or $t7, $t7, $t3
    lw $t1, {D_HS + side * 8}($t8)
    lw $t2, {sd + S_PREHS}($t8)
    sltu $t3, $t2, $t1
    or $t7, $t7, $t3
""")
    s0 = D_SIDE
    s1 = D_SIDE + 0x20
    if DROP_AIR:
        AIR_CODE = f"""
    lw $t1, {s0 + S_REACT}($t8)
    lw $t2, {s0 + S_PREAIR}($t8)
    and $t1, $t1, $t2
    lw $t3, {s1 + S_REACT}($t8)
    lw $t4, {s1 + S_PREAIR}($t8)
    and $t3, $t3, $t4
    or $t1, $t1, $t3
    sw $t1, {D_AIR}($t8)"""
    else:
        AIR_CODE = f"    sw $zero, {D_AIR}($t8)"
    s.append(f"""
    beqz $t7, fa_nocontact
    nop
    lw $t1, {D_ACTIVE}($t8)
    beqz $t1, fa_start
    nop
    lw $t1, {D_T0}($t8)
    subu $t1, $t9, $t1
    sltiu $t1, $t1, {SAME_CONTACT + 1}
    bnez $t1, fa_nocontact
    nop
fa_start:
    addiu $t1, $zero, 1
    sw $t1, {D_ACTIVE}($t8)
    sw $t9, {D_T0}($t8)
    sw $zero, {s0 + S_FREE}($t8)
    sw $zero, {s1 + S_FREE}($t8)
{AIR_CODE}
fa_nocontact:
    lw $t1, {D_ACTIVE}($t8)
    beqz $t1, fa_prev
    nop
""")
    for side in (0, 1):
        sd = D_SIDE + side * 0x20
        s.append(f"""
    lw $t1, {sd + S_FREE}($t8)
    bnez $t1, fa_f{side}
    nop
    lw $t1, {sd + S_BUSY}($t8)
    bnez $t1, fa_f{side}
    nop
    sw $t9, {sd + S_FREE}($t8)
fa_f{side}:
""")
    s.append(f"""
    lw $t1, {s0 + S_FREE}($t8)
    lw $t2, {s1 + S_FREE}($t8)
    beqz $t1, fa_timeout
    nop
    beqz $t2, fa_timeout
    nop
    sw $zero, {D_ACTIVE}($t8)
    lw $t3, {D_AIR}($t8)
    beqz $t3, fa_result
    nop
    sw $zero, {s0 + S_VALID}($t8)
    sw $zero, {s1 + S_VALID}($t8)
    b fa_prev
    nop
fa_result:
    subu $t3, $t2, $t1
    sw $t3, {s0 + S_VAL}($t8)
    subu $t4, $zero, $t3
    sw $t4, {s1 + S_VAL}($t8)
    addiu $t5, $zero, 1
    sw $t5, {s0 + S_VALID}($t8)
    sw $t5, {s1 + S_VALID}($t8)
    b fa_prev
    nop
fa_timeout:
    lw $t1, {D_T0}($t8)
    subu $t1, $t9, $t1
    sltiu $t1, $t1, {TIMEOUT + 1}
    bnez $t1, fa_prev
    nop
    sw $zero, {D_ACTIVE}($t8)
fa_prev:
""")
    for side in (0, 1):
        sd = D_SIDE + side * 0x20
        s.append(f"""
    lw $t1, {sd + S_REACT}($t8)
    sw $t1, {sd + S_PREACT}($t8)
    lw $t1, {D_HS + side * 8}($t8)
    sw $t1, {sd + S_PREHS}($t8)
    lw $t1, {D_HS + side * 8 + 4}($t8)
    sw $t1, {sd + S_PREAIR}($t8)
""")
    s.append("""
fa_ret0:
    jr $ra
    nop
""")
    return "".join(s)


def draw_source():
    """fa_draw(a0 = side, a1 = center x, a2 = y): '+N' / '-N' / '+0' with colour, nothing while no valid result."""
    d_hi, d_lo = hi_lo(FA_DATA)
    g_hi, g_lo = hi_lo(GLYPHTAB)
    c_hi, c_lo = hi_lo(CTX)
    p_hi, p_lo = hi_lo(COL_PLUS)
    n_hi, n_lo = hi_lo(COL_MINUS)

    def digit(reg, tag):
        return f"""
    addiu $t4, $zero, 35
    beqz {reg}, dz{tag}
    nop
    addiu $t4, {reg}, 25
dz{tag}:
    sb $t4, 0($t5)
    addiu $t5, $t5, 1
"""
    return f"""
    addiu $sp, $sp, -0x60
    sd $ra, 0x58($sp)
    sd $s0, 0x50($sp)
    sd $s1, 0x48($sp)
    sd $s2, 0x40($sp)
    sd $s3, 0x38($sp)
    daddu $s1, $a1, $zero
    daddu $s2, $a2, $zero
    lui $t8, {d_hi:#x}
    addiu $t8, $t8, {sx(d_lo)}
    sll $t0, $a0, 5
    addu $t8, $t8, $t0
    lw $t0, {D_SIDE + S_VALID}($t8)
    beqz $t0, fd_end
    nop
    lw $t6, {D_SIDE + S_VAL}($t8)
    addiu $s3, $zero, -1
    addiu $t5, $sp, 0
    beqz $t6, fd_zero
    nop
    bgtz $t6, fd_pos
    nop
    lui $s3, {n_hi:#x}
    ori $s3, $s3, {n_lo:#x}
    addiu $t4, $zero, {G_MINUS}
    sb $t4, 0($t5)
    addiu $t5, $t5, 1
    subu $t6, $zero, $t6
    b fd_abs
    nop
fd_zero:
    addiu $t4, $zero, {G_PLUS}
    sb $t4, 0($t5)
    addiu $t5, $t5, 1
    b fd_abs
    nop
fd_pos:
    lui $s3, {p_hi:#x}
    ori $s3, $s3, {p_lo:#x}
    addiu $t4, $zero, {G_PLUS}
    sb $t4, 0($t5)
    addiu $t5, $t5, 1
fd_abs:
    sltiu $t4, $t6, 1000
    bnez $t4, fd_ok
    nop
    addiu $t6, $zero, 999
fd_ok:
    addu $t7, $zero, $zero
fd_hl:
    sltiu $t4, $t6, 100
    bnez $t4, fd_hd
    nop
    addiu $t6, $t6, -100
    addiu $t7, $t7, 1
    b fd_hl
    nop
fd_hd:
    addu $t9, $zero, $zero
fd_tl:
    sltiu $t4, $t6, 10
    bnez $t4, fd_td
    nop
    addiu $t6, $t6, -10
    addiu $t9, $t9, 1
    b fd_tl
    nop
fd_td:
    beqz $t7, fd_noh
    nop
{digit('$t7', 'h')}
    b fd_t
    nop
fd_noh:
    beqz $t9, fd_o
    nop
fd_t:
{digit('$t9', 't')}
fd_o:
{digit('$t6', 'o')}
    addiu $t4, $zero, 255
    sb $t4, 0($t5)
    addiu $t1, $sp, 0
    addu $t0, $zero, $zero
fd_wl:
    lbu $t4, 0($t1)
    addiu $t2, $zero, 255
    beq $t4, $t2, fd_wd
    nop
    addiu $t2, $zero, {G_SPACE}
    addiu $t3, $zero, {ADV}
    bne $t4, $t2, fd_wn
    nop
    addiu $t3, $zero, {SPACE_ADV}
fd_wn:
    addu $t0, $t0, $t3
    addiu $t1, $t1, 1
    b fd_wl
    nop
fd_wd:
    srl $t0, $t0, 1
    subu $s1, $s1, $t0
    addiu $s0, $sp, 0
fd_dl:
    lbu $t4, 0($s0)
    addiu $t2, $zero, 255
    beq $t4, $t2, fd_end
    nop
    sll $t4, $t4, 3
    lui $t0, {g_hi:#x}
    addiu $t0, $t0, {sx(g_lo)}
    addu $a0, $t0, $t4
    lui $a1, {c_hi:#x}
    addiu $a1, $a1, {sx(c_lo)}
    daddu $a2, $zero, $zero
    addiu $a3, $zero, 1
    daddu $t0, $s3, $zero
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
    lbu $t4, 0($s0)
    addiu $t2, $zero, {G_SPACE}
    addiu $t3, $zero, {ADV}
    bne $t4, $t2, fd_adv
    nop
    addiu $t3, $zero, {SPACE_ADV}
fd_adv:
    addu $s1, $s1, $t3
    addiu $s0, $s0, 1
    b fd_dl
    nop
fd_end:
    ld $ra, 0x58($sp)
    ld $s0, 0x50($sp)
    ld $s1, 0x48($sp)
    ld $s2, 0x40($sp)
    ld $s3, 0x38($sp)
    jr $ra
    addiu $sp, $sp, 0x60
"""
