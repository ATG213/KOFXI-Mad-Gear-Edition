"""KOF XI PS2 (JP): practice UKEMI option (2026-11-24): OFF / BACK / FWD / RANDOM, independent of GUARD.

Vanilla: GUARD value 4 "DOWN" makes the CPU dummy tech (ukemi) a knockdown.  The dummy AI FUN_00337230 does it at 0x337660..0x337754:
while the dummy is in a hit reaction (+0x494 bit 0), not in an untechable knockdown (+0x538 & 0xF0000 != 0x80000), airborne
(+0x490 & 0x2000), falling (+0x1C < 0) and near the floor (y +2 >= 0x220) it injects A+B (FUN_0016a220(ctx, dir 0, 0x300, 1)).
Bug (ATG: "the AI sometimes does not tech a juggled opponent"): after a press it sets bit 0 of +0x23C and clears it only on frames
with tick & 3 == 0 *inside* that condition, so the bit from the previous tech can survive until the next knockdown; the next press then
waits up to 4 frames, and a fast fall from a juggle passes the near-floor zone in a few frames.  The tech window itself is long:
input probe 2026-11-24 (Shen 2D): A+B works from 16 frames before landing up to the frame before it.

Replacement: the hook at 0x33764C (`lui v1,0x9d` before the GUARD == 4 test, delay slot `addiu a0,zero,4`) calls UK_CODE every AI frame:
* migration: a saved GUARD = 4 (DOWN, removed from the GUARD lists) becomes GUARD OFF + UKEMI BACK;
* UKEMI (byte UK_ADDR) != OFF and the vanilla condition holds: A+B on every second frame (edge every 2 frames, no stale lock),
  direction 0 = back tech, UK_FWD_DIR = forward tech; RANDOM picks one per knockdown (reset when the reaction ends);
* on return v1 = 0x9D0000 and a0 = 99, so the vanilla GUARD == 4 block is never entered again.
Direction codes of FUN_0016a220 (p < 0x12 -> table 0x3630A0[p - 2]): 0 neutral; measured live 2026-11-24 with UKEMI FWD and a debug
override: p = 3, 4, 5 give the forward tech (action 293, the dummy rolls through), 2, 6..9 the back tech (294); 4 = forward.
"""

UK_ADDR = 0x9CB24C            # option byte (practice settings 0x9CB240.. ; 0x24C was unused); saved at save+0x294FF
UK_CODE = 0x3B1E00            # zero run 0x3B1DF8..0x3B2F00 (next to the other practice caves; 0x3A88xx..0x3A9Cxx crashed the game, 2026-11-24)
UK_SAVE = 0x3B2000
UK_LOAD = 0x3B2080
UK_CHOICE = 0x3B2E00          # RANDOM: 0 none, 1 back, 2 forward (per knockdown)
UK_HOOK = (0x33764C, 0x3C03009D)
UK_FWD_DIR = 4
DEBUG_DIR = False             # test builds: a non-zero byte at UK_DIR_DEBUG overrides UK_FWD_DIR (find the forward code live)
UK_DIR_DEBUG = 0x3B2E04
UK_PEND = 0x3B2E08            # forward tech active in this AI frame: +0 direction + 1 (0 = none), +4 input context
UK_COMMIT = 0x3B2700          # wrapper of `jal 0x1726f0` at UK_COMMIT_SITE (end of the AI frame FUN_0013B910): clears UK_PEND
UK_COMMIT_SITE = (0x184D84, 0x0C000000 | (0x1726F0 >> 2))
UK_FILTER = 0x3B2780          # entry filter of the AI input function FUN_0016A220 (its first two instructions moved here)
UK_FILTER_SITE = (0x16A220, 0x27BDFFB0, 0x16A224, 0xFFBF0040)
UK_SAVE_OFF = 0x294FF         # free byte after the OPTIONS DISPLAY byte (+0x294FE) at the end of the save buffer
UK_STRINGS = ("OFF", "BACK", "FWD", "RANDOM")
GUARD_ADDR = 0x9CB244
ACTION_ADDR = 0x9CB241
TICK = 0x9BDA70


def hi_lo(v):
    lo = v & 0xFFFF
    hi = (v >> 16) + (1 if lo & 0x8000 else 0)
    return hi & 0xFFFF, lo


def sx(v):
    return v - 0x10000 if v & 0x8000 else v


def ukemi_source(ga_mode, ga_rng):
    u_hi, u_lo = hi_lo(UK_ADDR)
    g_hi, g_lo = hi_lo(GUARD_ADDR)
    a_hi, a_lo = hi_lo(ACTION_ADDR)
    m_hi, m_lo = hi_lo(ga_mode)
    r_hi, r_lo = hi_lo(ga_rng)
    c_hi, c_lo = hi_lo(UK_CHOICE)
    k_hi, k_lo = hi_lo(TICK)
    d_hi, d_lo = hi_lo(UK_DIR_DEBUG)
    p_hi, p_lo = hi_lo(UK_PEND)
    DIR_DEBUG = f"""
    lui $t3, {d_hi:#x}
    lbu $t3, {sx(d_lo)}($t3)
    beqz $t3, uk_nodbg
    nop
    daddu $a1, $t3, $zero
uk_nodbg:""" if DEBUG_DIR else ""
    return f"""
    addiu $sp, $sp, -0x40
    sd $ra, 0x30($sp)
    sd $v0, 0x28($sp)
    sd $s2, 0x20($sp)
    lui $t0, {g_hi:#x}
    lbu $t1, {sx(g_lo)}($t0)
    addiu $t2, $zero, 4
    bne $t1, $t2, uk_mdone
    nop
    sb $zero, {sx(g_lo)}($t0)
    lui $t3, {m_hi:#x}
    sb $zero, {sx(m_lo)}($t3)
    lui $t0, {u_hi:#x}
    lbu $t1, {sx(u_lo)}($t0)
    bnez $t1, uk_mdone
    nop
    addiu $t1, $zero, 1
    sb $t1, {sx(u_lo)}($t0)
uk_mdone:
    lui $t0, {u_hi:#x}
    lbu $s2, {sx(u_lo)}($t0)
    sltiu $t1, $s2, 4
    beqz $t1, uk_ret
    nop
    beqz $s2, uk_ret
    nop
    lui $t0, {a_hi:#x}
    lbu $t1, {sx(a_lo)}($t0)
    sltiu $t2, $t1, 11
    beqz $t2, uk_ret
    nop
    addiu $t2, $zero, 7
    beq $t1, $t2, uk_ret
    nop
    addiu $t2, $zero, 8
    beq $t1, $t2, uk_ret
    nop
    lw $t1, 0x494($s1)
    andi $t1, $t1, 1
    beqz $t1, uk_clear
    nop
    lw $t1, 0x538($s1)
    srl $t1, $t1, 16
    andi $t1, $t1, 0xF
    addiu $t2, $zero, 8
    beq $t1, $t2, uk_ret
    nop
    lw $t1, 0x490($s1)
    andi $t1, $t1, 0x2000
    beqz $t1, uk_ret
    nop
    lw $t1, 0x1C($s1)
    bgez $t1, uk_ret
    nop
    lh $t1, 2($s1)
    slti $t1, $t1, 0x220
    bnez $t1, uk_ret
    nop
    sw $zero, 0x208($s1)
    addu $a1, $zero, $zero
    addiu $t1, $zero, 2
    beq $s2, $t1, uk_fwd
    nop
    addiu $t1, $zero, 3
    bne $s2, $t1, uk_press
    nop
    lui $t0, {c_hi:#x}
    lbu $t1, {sx(c_lo)}($t0)
    bnez $t1, uk_have
    nop
    lui $t3, {r_hi:#x}
    lw $t2, {sx(r_lo)}($t3)
    lui $t3, {k_hi:#x}
    lw $t3, {sx(k_lo)}($t3)
    xor $t2, $t2, $t3
    srl $t3, $t2, 7
    xor $t2, $t2, $t3
    andi $t2, $t2, 1
    addiu $t1, $t2, 1
    sb $t1, {sx(c_lo)}($t0)
uk_have:
    addiu $t2, $zero, 2
    bne $t1, $t2, uk_press
    nop
uk_fwd:
    addiu $a1, $zero, {UK_FWD_DIR}
{DIR_DEBUG}
uk_press:
    beqz $a1, uk_nofwd
    nop
    lui $t0, {p_hi:#x}
    addiu $t1, $a1, 1
    sw $t1, {sx(p_lo)}($t0)
    sw $s0, {sx(p_lo) + 4}($t0)
uk_nofwd:
    lw $t1, 0x400($s1)
    andi $t1, $t1, 1
    bnez $t1, uk_ret
    nop
    daddu $a0, $s0, $zero
    addiu $a2, $zero, 0x300
    jal 0x16a220
    addiu $a3, $zero, 1
    b uk_ret
    nop
uk_clear:
    lui $t0, {c_hi:#x}
    sb $zero, {sx(c_lo)}($t0)
uk_ret:
    lui $v1, 0x9d
    addiu $a0, $zero, 99
    ld $ra, 0x30($sp)
    ld $v0, 0x28($sp)
    ld $s2, 0x20($sp)
    jr $ra
    addiu $sp, $sp, 0x40
"""


def commit_source():
    """`jal 0x1726f0` (a0 = input context) at the end of the AI frame: clears UK_PEND (set again by the tech routine next frame)."""
    p_hi, p_lo = hi_lo(UK_PEND)
    return f"""
    lui $t0, {p_hi:#x}
    sw $zero, {sx(p_lo)}($t0)
    j 0x1726f0
    nop
"""


def filter_source():
    """Entry of FUN_0016A220(ctx a0, direction a1, buttons a2, a3).  Each call is one input step and the held directions are the OR of the
    last three steps (FUN_00173330), so the guard AI (GUARD / RANDOM / ALL, it runs after the practice handler) pushing 'back' every frame
    mixed back + forward and the dummy made a BACK tech with UKEMI FWD (ATG 2026-11-24).  While the tech routine marked the forward
    tech for this context in this AI frame, every call for it gets the forward direction (buttons unchanged)."""
    p_hi, p_lo = hi_lo(UK_PEND)
    return f"""
    lui $t0, {p_hi:#x}
    lw $t1, {sx(p_lo)}($t0)
    beqz $t1, uf_go
    nop
    lw $t2, {sx(p_lo) + 4}($t0)
    bne $t2, $a0, uf_go
    nop
    addiu $a1, $t1, -1
uf_go:
    addiu $sp, $sp, -0x50
    sd $ra, 0x40($sp)
    j 0x16a228
    nop
"""


def save_source(opt_save_stub):
    """wraps the OPTIONS-DISPLAY save stub (s0 = save buffer): also stores the UKEMI byte at save+UK_SAVE_OFF"""
    u_hi, u_lo = hi_lo(UK_ADDR)
    return f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x10($sp)
    jal {opt_save_stub:#x}
    nop
    lui $t0, {u_hi:#x}
    lbu $t0, {sx(u_lo)}($t0)
    lui $t1, {UK_SAVE_OFF >> 16:#x}
    ori $t1, $t1, {UK_SAVE_OFF & 0xFFFF:#x}
    addu $t1, $s0, $t1
    sb $t0, 0($t1)
    ld $ra, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x20
"""


def load_source(opt_load_stub):
    u_hi, u_lo = hi_lo(UK_ADDR)
    return f"""
    addiu $sp, $sp, -0x20
    sd $ra, 0x10($sp)
    jal {opt_load_stub:#x}
    nop
    lui $t1, {UK_SAVE_OFF >> 16:#x}
    ori $t1, $t1, {UK_SAVE_OFF & 0xFFFF:#x}
    addu $t1, $s0, $t1
    lbu $t0, 0($t1)
    sltiu $t2, $t0, 4
    bnez $t2, ukl_ok
    nop
    addu $t0, $zero, $zero
ukl_ok:
    lui $t1, {u_hi:#x}
    sb $t0, {sx(u_lo)}($t1)
    ld $ra, 0x10($sp)
    jr $ra
    addiu $sp, $sp, 0x20
"""
