#!/usr/bin/env python3
"""Quick rematch ("A+Start / B+Start") for KOF XI Atomiswave, v11 design: only the joining side's buttons count.

On the win screen (scene 0x0308) the button that is held while the joining loser presses Start decides:
  - Start only   -> unchanged: "new challenger", full character select.
  - A + Start    -> straight into the match (scene 0x0303): same 6 characters, same order, same leader, no select.
                    For this the order that was confirmed at the last order select, including the leader flag, is
                    restored (see "Order backup" below) and fn_8c0ca038 is jumped to.
  - B + Start    -> leader select and order select (fn_8c0699bc, scene 0x0302) with the same characters, then the
                    match. For this the flag "leader already chosen" is cleared for both sides first (bit 1 of
                    team+0xA0; the leader input task fn_8c06b1e0 would otherwise skip itself and keep the old
                    leader - normally the team wipe clears this flag, which we avoid here).
Every entry costs a credit as in the original (except Free Play).

Mechanics: when a side joins on the win screen with Start, the scene handler `fn_8c06625c` sets the next callback of
the main task (main.next, 0x8C213C60, via fn_8c07a118). `fn_8c06625c` requests scene 0x030A, wipes the team of that
side (fn_8c095854 -> fn_8c094bca) and starts the "new challenger" screen. The patch redirects all 7 literals that
load the address of `fn_8c06625c` as a callback to a wrapper:
  0. Wipe-pending mask 0x8C27CB5C == 0 -> continue normally. (Only fn_8c0dabc8 / 0x8c0dad16 set it, so != 0 means
     somebody really just joined. Needed because the arcade outcome dispatcher 0x8c0ce0c2 also uses `fn_8c06625c`
     for the ranking screens.)
  1. Scene != 0x0308 (low byte of the scene word 0x8C27CB64 != 8) -> continue normally.
  2. Raw active-low input word of ONLY the joining side (mask bit 1 -> 0x8C375A08 for 2P, else 0x8C374208 for 1P):
     bit 2 = A, bit 10 = B. A -> RESTORE (-> fn_8c0ca038), else B -> BSEL (clear leader flags -> fn_8c0699bc),
     else continue normally. (v10 combined both sides with AND, so a winner who held a button also triggered it.)
  3. Rematch: clear the wipe-pending mask (the team is kept) and tail-jump to the target. Both targets are ordinary
     main-task callbacks (r4 = task); the complete match initialisation (health/stun/guard 112, meter, point,
     timer 99) is done by the game itself (fn_8c0ca0c8 -> fn_8c0ca158).
"Continue normally" is a tail jump to `fn_8c06625c`, so a plain Start stays unchanged.

No instruction of live code is overwritten: only 7 literal pool entries (all read exclusively by `mov.l ...,r4`
callback loaders, verified by a scan of the whole ROM) and two provably dead blocks in `fn_8c0f8774`. Both depend on
the byte 0x8C38C5BF, which is never written anywhere in the binary (BSS, always 0):
  - F3, 0x8c0f8790..0x8c0f87d8 (cmp/eq #2, bf 0x8c0f87d8): wrapper code. NOTE: this block contains two LIVE
    literals (0x8c0f87c8 = 0x8c38c53e, 0x8c0f87cc = 0x8c38c5bf); code may only use 0x8c0f8790..0x8c0f87c8.
  - F4, 0x8c0f87e2..0x8c0f8822 (cmp/eq #1, bf 0x8c0f8822): BSEL right at the start of the block, followed by the
    shared literal pool. Verified by a scan: no jump, no PC-relative reader and no raw pointer from outside targets
    F3 or F4.

Order backup: the game rotates the order (team+0x78..0x7A) at every KO and clears the leader flag of the loser (bit 7
of the position byte block+0x10 of each member); match initialisation simply takes order[0] as the starting fighter,
and the original choice is kept nowhere in RAM. Therefore:
  - SAVE: the literal 0x8c069a74 (fn_8c0699bc stores fn_8c0ca038 there as next callback after the order select; its
    only reader is 0x8c069a1e) points to SAVE. SAVE copies the order word and the three position bytes of both sides
    into a 16-byte buffer and jumps to fn_8c0ca038. At that moment order and leader flag are final (measured with a
    RAM watch: writer 0x8C06DBxx during scene 0x0302).
  - RESTORE (A+Start): copies the buffer back, then fn_8c0ca038.
Both routines and the buffer live in `fn_8c0661bc` (0x8c0661bc..0x8c06625c): an unreferenced twin of fn_8c06625c - no
raw pointer in the whole ROM, no bsr, no PC-relative reader from outside. The buffer is pre-filled with the default
order in case no SAVE ever ran.

Input is the UNMODIFIED decrypted program ROM; all expected original bytes are checked.

    python quick_rematch.py --in ax3201p01.fmem1 --out DIR [--no-scene-check]     (encrypted in, encrypted out)
"""
import argparse
import struct
import sys
from pathlib import Path

BASE = 0x8C00FF00

FN_RESULT_TASK = 0x8C06625C   # fn_8c06625c: "new challenger" flow (scene 0x030A, team wipe)
FN_VS_SCREEN = 0x8C0699BC     # fn_8c0699bc: VS screen (scene 0x0302), then fn_8c0ca038
FN_COMBAT = 0x8C0CA038        # fn_8c0ca038: scene 0x0303, match init via fn_8c0ca0c8/fn_8c0ca158
# All literal pool entries with the value FN_RESULT_TASK (whole-ROM scan: exactly these 7; no bsr callers).
# Readers: 5 scene handlers in fn_8c0da0dc (-> fn_8c07a118) and two places in the outcome dispatcher (-> fn_8c079b32).
CALLBACK_LITERALS = [0x8C0CE0E0, 0x8C0CE3E4, 0x8C0DA73C, 0x8C0DA7E4, 0x8C0DA924, 0x8C0DA9C0,
                     0x8C0DAA94]

WIPE_PENDING = 0x8C27CB5C     # bit mask "wipe the team of this side at the next fn_8c095854"
SCENE_LOW_OFF = 8             # 0x8C27CB64 (scene word, low byte) - WIPE_PENDING
SCENE_LOW_EXPECTED = 8        # scene 0x0308
RAW_INPUT_2P = 0x8C375A08     # 16 bit, active low: bit 2 = A, bit 3 = Start, bit 10 = B
RAW_INPUT_1P = 0x8C374208
BUTTON_BIT = 0x04             # A in the low byte, B in the high byte (after swap.b)

CAVE = 0x8C0F8790
CAVE_CODE_END = 0x8C0F87C8    # two live literals (8 bytes) from here on
ANCHOR_BF_ADDR, ANCHOR_BF_CODE = 0x8C0F878E, 0x8B23       # bf 0x8c0f87d8
LIVE_LITERALS = [(0x8C0F87C8, 0x8C38C53E), (0x8C0F87CC, 0x8C38C5BF)]

POOL_BLOCK = 0x8C0F87E2       # F4: BSEL code, then literals
POOL_END = 0x8C0F8822
TEAM0_FLAGS = 0x8C27CBF4      # team0+0xA0; bit 1 = "leader already chosen"
LEADER_CHOSEN_MASK = 0xFD     # and mask, clears bit 1
POOL_ANCHOR_BF_ADDR, POOL_ANCHOR_BF_CODE = 0x8C0F87E0, 0x8B1F   # bf 0x8c0f8822
FN_EXIT = 0x8C0F8864          # shared exit of fn_8c0f8774

# Order backup (SAVE/RESTORE + buffer) in the unreferenced twin fn_8c0661bc.
TWIN, TWIN_END = 0x8C0661BC, 0x8C06625C
TWIN_FIRST_WORD = 0x4F22          # sts.l pr,@-r15 (original function head)
MATCH_START_LITERAL = 0x8C069A74  # in fn_8c0699bc: main.next = fn_8c0ca038 after the order select
TEAM0_ORDER = 0x8C27CBCC          # team0+0x78 (order word); +0xE4 = position byte of block 0
TEAM_STRIDE = 0x1F8
POS_FROM_ORDER = 0xE4             # (team+0x14C+0x10) - (team+0x78)
BLOCK_STRIDE = 0x20
BACKUP_DEFAULT = bytes([0, 1, 2, 0, 0x80, 1, 2, 0]) * 2


def off(addr):
    return addr - BASE


def enc_movl_pc(rn, instr_addr, target_addr):
    base_addr = (instr_addr & ~3) + 4
    delta = target_addr - base_addr
    assert target_addr % 4 == 0 and delta % 4 == 0 and 0 <= delta <= 1020, \
        (hex(instr_addr), hex(target_addr), delta)
    return 0xD000 | (rn << 8) | (delta // 4)


def enc_bf(addr, target):
    d = (target - (addr + 4)) // 2
    assert -128 <= d <= 127, d
    return 0x8B00 | (d & 0xFF)


def enc_bra(addr, target):
    d = (target - (addr + 4)) // 2
    assert -2048 <= d <= 2047, d
    return 0xA000 | (d & 0xFFF)


def build_wrapper(scene_check, restore_addr):
    """Returns [(address, bytes)] for the wrapper code (F3), BSEL and the literal pool (F4)."""
    def new_ops():
        ops = []
        return ops, (lambda code: ops.append(('raw', code))), \
            (lambda rn, value: ops.append(('lit', rn, value)))

    # --- wrapper (F3) ---
    ops, raw, lit = new_ops()
    lit(3, WIPE_PENDING)                      # mov.l WIPE_PENDING,r3
    raw(0x6230)                               # mov.b @r3,r2   (wipe-pending mask, bit = side)
    raw(0x2228)                               # tst r2,r2
    ops.append(('br', 'bt', 'normal'))        # 0 -> nobody joined, continue normally
    if scene_check:
        raw(0x8400 | (3 << 4) | SCENE_LOW_OFF)    # mov.b @(8,r3),r0   (scene low byte)
        raw(0x8800 | SCENE_LOW_EXPECTED)          # cmp/eq #8,r0
        ops.append(('br', 'bf', 'normal'))
    # v11: only the input of the joining (losing) side counts. Mask bit 1 (0x02) set = 2P joins, else 1P.
    # (v10 combined both sides with AND: a winner who held a button also triggered the rematch.)
    lit(1, RAW_INPUT_1P)                      # mov.l RAW_INPUT_1P,r1
    raw(0x6023)                               # mov r2,r0
    raw(0xC800 | 0x02)                        # tst #2,r0   (T=1 <=> 2P bit not set)
    ops.append(('br', 'bt', 'sel'))
    lit(1, RAW_INPUT_2P)                      # mov.l RAW_INPUT_2P,r1
    ops.append(('label', 'sel'))
    raw(0x6001 | (0 << 8) | (1 << 4))         # mov.w @r1,r0   (active low: 0 = held)
    lit(1, restore_addr)                      # mov.l RESTORE,r1  (-> fn_8c0ca038)
    raw(0xC800 | BUTTON_BIT)                  # tst #4,r0   (T=1 <=> A held)
    ops.append(('br', 'bt', 'go'))
    raw(0x6008)                               # swap.b r0,r0
    raw(0xC800 | BUTTON_BIT)                  # tst #4,r0   (T=1 <=> B held)
    ops.append(('br', 'bf', 'normal'))
    lit(1, POOL_BLOCK)                        # mov.l BSEL,r1  (-> fn_8c0699bc)
    ops.append(('label', 'go'))
    raw(0xE000)                               # mov #0,r0
    raw(0x2000 | (3 << 8) | (0 << 4))         # mov.b r0,@r3  (clear wipe-pending)
    raw(0x402B | (1 << 8))                    # jmp @r1
    raw(0x0009)                               # nop
    ops.append(('label', 'normal'))
    lit(1, FN_RESULT_TASK)                    # mov.l fn_8c06625c,r1
    raw(0x402B | (1 << 8))                    # jmp @r1
    raw(0x0009)                               # nop
    wrapper_ops = ops

    # --- BSEL (F4): clear "leader already chosen" for both sides ---
    ops, raw, lit = new_ops()
    lit(1, TEAM0_FLAGS)                       # mov.l TEAM0_FLAGS,r1
    ops.append(('wlit', 2))                   # mov.w TEAM_STRIDE,r2
    for side in range(2):
        raw(0x6010)                           # mov.b @r1,r0
        raw(0xC900 | LEADER_CHOSEN_MASK)      # and #0xFD,r0
        raw(0x2100)                           # mov.b r0,@r1
        if side == 0:
            raw(0x312C)                       # add r2,r1
    lit(1, FN_VS_SCREEN)                      # mov.l fn_8c0699bc,r1
    raw(0x402B | (1 << 8))                    # jmp @r1
    raw(0x0009)                               # nop
    bsel_ops = ops

    def place(start, ops):
        addr, placed, labels = start, [], {}
        for op in ops:
            if op[0] == 'label':
                labels[op[1]] = addr
                continue
            placed.append((addr, op))
            addr += 2
        return placed, labels, addr

    w_placed, w_labels, w_end = place(CAVE, wrapper_ops)
    if w_end > CAVE_CODE_END:
        sys.exit('wrapper code does not fit into the code cave (%#x > %#x)' % (w_end, CAVE_CODE_END))
    b_placed, b_labels, b_end = place(POOL_BLOCK, bsel_ops)

    pool = (b_end + 3) & ~3
    slots = {}
    for _, op in w_placed + b_placed:
        if op[0] == 'lit' and op[2] not in slots:
            slots[op[2]] = pool + 4 * len(slots)
    stride_addr = pool + 4 * len(slots)
    if stride_addr + 2 > POOL_END:
        sys.exit('literal pool does not fit into F4')

    chunks = []
    for placed, labels in ((w_placed, w_labels), (b_placed, b_labels)):
        for a, op in placed:
            if op[0] == 'raw':
                code = op[1]
            elif op[0] == 'lit':
                code = enc_movl_pc(op[1], a, slots[op[2]])
            elif op[0] == 'wlit':
                disp = (stride_addr - (a + 4)) // 2
                assert 0 <= disp <= 255, disp
                code = 0x9000 | (op[1] << 8) | disp
            else:
                code = enc_bf(a, labels[op[2]])
                if op[1] == 'bt':
                    code ^= 0x0200            # 0x8Bxx (bf) -> 0x89xx (bt)
            chunks.append((a, struct.pack('<H', code)))
    if pool != b_end:
        chunks.append((b_end, struct.pack('<H', 0x0009)))
    for value, a in slots.items():
        chunks.append((a, struct.pack('<I', value)))
    chunks.append((stride_addr, struct.pack('<H', TEAM_STRIDE)))
    return chunks


def build_twin():
    """SAVE, RESTORE, literals and buffer for the twin function. Returns (blob, save, restore)."""
    def body(restore):
        code = []
        code.append(('lit', 1, 'team'))               # mov.l TEAM0_ORDER,r1
        code.append(('lit', 2, 'bak'))                # mov.l BACKUP,r2
        code.append(('raw', 0xE302))                  # mov #2,r3
        code.append(('label', 'loop'))
        if restore:
            code.append(('raw', 0x6022))              # mov.l @r2,r0
            code.append(('raw', 0x2102))              # mov.l r0,@r1
        else:
            code.append(('raw', 0x6012))              # mov.l @r1,r0
            code.append(('raw', 0x2202))              # mov.l r0,@r2
        code.append(('raw', 0x6513))                  # mov r1,r5
        code.append(('raw', 0x7500 | (POS_FROM_ORDER // 2)))   # add #114,r5
        code.append(('raw', 0x7500 | (POS_FROM_ORDER // 2)))   # add #114,r5
        for n in range(3):
            if restore:
                code.append(('raw', 0x8400 | (2 << 4) | (4 + n)))   # mov.b @(4+n,r2),r0
                code.append(('raw', 0x2500))                        # mov.b r0,@r5
            else:
                code.append(('raw', 0x6050))                        # mov.b @r5,r0
                code.append(('raw', 0x8000 | (2 << 4) | (4 + n)))   # mov.b r0,@(4+n,r2)
            if n != 2:
                code.append(('raw', 0x7500 | BLOCK_STRIDE))         # add #32,r5
        code.append(('raw', 0x7208))                  # add #8,r2
        code.append(('wlit', 0, 'stride'))            # mov.w TEAM_STRIDE,r0
        code.append(('raw', 0x310C))                  # add r0,r1
        code.append(('raw', 0x4310))                  # dt r3
        code.append(('bf', 'loop'))
        code.append(('lit', 1, 'combat'))             # mov.l fn_8c0ca038,r1
        code.append(('raw', 0x412B))                  # jmp @r1
        code.append(('raw', 0x0009))                  # nop
        return code

    assert POS_FROM_ORDER % 2 == 0 and POS_FROM_ORDER // 2 <= 127
    save_ops, restore_ops = body(False), body(True)
    save_addr = TWIN
    restore_addr = save_addr + 2 * sum(1 for op in save_ops if op[0] != 'label')
    code_end = restore_addr + 2 * sum(1 for op in restore_ops if op[0] != 'label')
    stride_addr = code_end                            # 2-byte literal
    pool = (stride_addr + 2 + 3) & ~3
    slots = {'team': pool, 'bak': pool + 4, 'combat': pool + 8}
    backup = pool + 12
    end = backup + len(BACKUP_DEFAULT)
    if end > TWIN_END:
        sys.exit('SAVE/RESTORE do not fit into the twin function')
    values = {'team': TEAM0_ORDER, 'bak': backup, 'combat': FN_COMBAT}

    blob = bytearray(end - TWIN)

    def emit(addr, code):
        struct.pack_into('<H', blob, addr - TWIN, code)

    for start, ops in ((save_addr, save_ops), (restore_addr, restore_ops)):
        addr, labels = start, {}
        for op in ops:
            if op[0] == 'label':
                labels[op[1]] = addr
                continue
            if op[0] == 'raw':
                code = op[1]
            elif op[0] == 'lit':
                code = enc_movl_pc(op[1], addr, slots[op[2]])
            elif op[0] == 'wlit':
                disp = (stride_addr - (addr + 4)) // 2
                assert 0 <= disp <= 255, disp
                code = 0x9000 | (op[1] << 8) | disp
            else:
                code = enc_bf(addr, labels[op[1]])
            emit(addr, code)
            addr += 2
    emit(stride_addr, TEAM_STRIDE)
    if pool != stride_addr + 2:
        emit(stride_addr + 2, 0x0009)
    for name, addr in slots.items():
        struct.pack_into('<I', blob, addr - TWIN, values[name])
    blob[backup - TWIN:end - TWIN] = BACKUP_DEFAULT
    return bytes(blob), save_addr, restore_addr


def build_patch(data, scene_check=True):
    """Returns the patched copy of the decrypted ROM."""
    orig = bytes(data)
    patched = bytearray(data)

    def u16(addr):
        return struct.unpack_from('<H', orig, off(addr))[0]

    def u32(addr):
        return struct.unpack_from('<I', orig, off(addr))[0]

    for addr, code in [(ANCHOR_BF_ADDR, ANCHOR_BF_CODE), (POOL_ANCHOR_BF_ADDR, POOL_ANCHOR_BF_CODE)]:
        if u16(addr) != code:
            sys.exit('unexpected ROM: anchor bf at %#x is %#06x' % (addr, u16(addr)))
    for addr, value in LIVE_LITERALS:
        if u32(addr) != value:
            sys.exit('unexpected ROM: live literal at %#x is %#x' % (addr, u32(addr)))
    for addr in CALLBACK_LITERALS:
        if u32(addr) != FN_RESULT_TASK:
            sys.exit('unexpected ROM: literal at %#x is %#x' % (addr, u32(addr)))
    # Completeness: there must be no further 4-byte reference to fn_8c06625c.
    needle = struct.pack('<I', FN_RESULT_TASK)
    found, pos = [], orig.find(needle)
    while pos != -1:
        found.append(BASE + pos)
        pos = orig.find(needle, pos + 1)
    if sorted(found) != sorted(CALLBACK_LITERALS):
        sys.exit('unexpected ROM: references to fn_8c06625c: %s' % [hex(a) for a in found])

    # Twin fn_8c0661bc: check the original head and make sure again that nothing in the ROM points into it.
    if u16(TWIN) != TWIN_FIRST_WORD or u32(MATCH_START_LITERAL) != FN_COMBAT:
        sys.exit('unexpected ROM: twin function / match start literal do not match')
    for addr in range(TWIN, TWIN_END, 2):
        if orig.find(struct.pack('<I', addr)) != -1:
            sys.exit('unexpected ROM: raw pointer to %#x inside the twin function' % addr)

    twin_blob, save_addr, restore_addr = build_twin()
    patched[off(TWIN):off(TWIN) + len(twin_blob)] = twin_blob
    struct.pack_into('<I', patched, off(MATCH_START_LITERAL), save_addr)
    for addr, blob in build_wrapper(scene_check, restore_addr):
        patched[off(addr):off(addr) + len(blob)] = blob
    for addr in CALLBACK_LITERALS:
        struct.pack_into('<I', patched, off(addr), CAVE)

    for addr, value in LIVE_LITERALS:
        assert struct.unpack_from('<I', patched, off(addr))[0] == value, hex(addr)
    return patched


def apply(dec, scene_check=True):
    """Patch the decrypted ROM in place; returns the list of changed file offsets."""
    patched = build_patch(dec, scene_check)
    changed = [i for i in range(len(dec)) if dec[i] != patched[i]]
    dec[:] = patched
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='src', type=Path, required=True, help='encrypted ax3201p01.fmem1')
    ap.add_argument('--out', type=Path, required=True, help='output folder')
    ap.add_argument('--no-scene-check', action='store_true',
                    help='do not restrict the rematch to scene 0x0308 (diagnostics only)')
    args = ap.parse_args()

    from aw_crypto import AWCrypto
    crypto = AWCrypto(0xD3)
    dec = bytearray(crypto.decrypt_buffer(args.src.read_bytes()))
    diff = apply(dec, not args.no_scene_check)
    print('A+Start -> %#x, B+Start -> %#x, scene check: %s' % (FN_COMBAT, FN_VS_SCREEN, not args.no_scene_check))
    print('changed bytes: %d in %#x..%#x' % (len(diff), BASE + diff[0], BASE + diff[-1]))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'ax3201p01.fmem1').write_bytes(crypto.encrypt_buffer(bytes(dec)))


if __name__ == '__main__':
    main()
