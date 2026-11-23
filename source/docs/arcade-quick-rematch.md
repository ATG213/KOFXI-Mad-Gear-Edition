# KOF XI (Atomiswave): A+Start / B+Start quick rematch patch

ROM patch for `ax3201p01.fmem1` (SH4 program ROM), built by `arcade/hacks/quick_rematch.py` (design "v11"). Confirmed
in Flycast; the earlier v10 design ran on a real AW Multi, v11 differs from it by 42 bytes (see the end).

## What it does

On the result screen of a 2P-vs-2P match, the loser can join with Start (this costs a credit, unless free play). The
button held while pressing Start now decides what happens:

| Input        | Result |
|--------------|--------|
| Start        | Unchanged: "new challenger", full character select. |
| A + Start    | Straight back into the match. Same 6 characters, same order, same leader, no select screens. |
| B + Start    | Leader and order select with the same 6 characters, then the match. |

Only the pad of the side that joins (the loser) counts. A winner who holds A or B does not trigger a rematch.

## Background: how the vanilla flow wipes the team

All addresses are guest SH4 addresses (the program is loaded at `0x8C00FF00`; file offset = address - `0x8C00FF00`; the
fmem1 is encrypted, see `arcade/hacks/aw_crypto.py`). Function names `fn_XXXXXXXX` are just the address of the function.

- Scene word: `0x8C27CB64` (low 16 bits = current scene). Scenes involved: `0x0303` combat, `0x0308` KO/result freeze,
  `0x030A` "new challenger" screen, `0x0301` order/team select, `0x0302` VS screen with leader/order select.
- Team structs: `team = 0x8C27CB54 + side * 0x1F8`. Member descriptor blocks at `team + 0x14C + N * 0x20` (N = 0..2).
  Order word at `team + 0x78`. Flags at `team + 0xA0` (bit 1 = "leader already chosen"). Leader flag = bit 7 of the
  position byte at `block + 0x10`.
- When a side presses Start on the result screen, the scene handler for `0x0308` (inside the big per-frame dispatcher
  `fn_8c0da0dc`) calls `fn_8c0dabc8(side)`, which sets bit `1 << side` in the "wipe pending" mask `0x8C27CB5C`, and then
  registers `fn_8c06625c` as the next main-task callback (`main.next`, `0x8C213C60`, via `fn_8c07a118` / `fn_8c079b32`).
- `fn_8c06625c` requests scene `0x030A`, then calls `fn_8c095854`. That function loops over the sides, and for every set
  bit in `0x8C27CB5C` calls `fn_8c094bca(side)` (writes `0xFF` over the three member blocks of that side, which is the
  team wipe) and clears the bit. After that the "new challenger" task chain runs and ends in the select screen.
- Start is the only input that sets the wipe bit. Pressing anything else, or Start from the winner, does not.

So the wipe is not undone by anything later; the idea of the patch is to not reach it.

## Patch design

The patch does not overwrite any live instruction. It only redirects a callback pointer and puts new code into code
that is provably never executed.

### 1. Redirect the callback (7 literal pool entries)

`fn_8c06625c` is only ever referenced as a *callback pointer*, never called with `bsr`. A whole-ROM scan finds exactly
7 occurrences of its address as a 32-bit literal:

```
0x8C0CE0E0  0x8C0CE3E4  0x8C0DA73C  0x8C0DA7E4  0x8C0DA924  0x8C0DA9C0  0x8C0DAA94
```

All 7 are read only by `mov.l ...,r4` callback loaders (5 scene handlers in `fn_8c0da0dc`, 2 in the arcade outcome
dispatcher). The patch points all 7 at a wrapper in a code cave. The build script aborts if the scan finds any other
reference.

### 2. The wrapper (code cave F3, `0x8C0F8790..0x8C0F87C8`)

Located in `fn_8c0f8774`, in a block guarded by `cmp/eq #2` on the byte `0x8C38C5BF`. That byte is never written
anywhere in the binary (BSS, always 0), so the block is dead. Two live literals sit at `0x8C0F87C8` and `0x8C0F87CC`
and are left untouched (code must end before them).

Logic, in order:

1. `0x8C27CB5C == 0` -> jump to `fn_8c06625c` (vanilla). Nothing was joined; the arcade outcome dispatcher also uses
   this callback for rank screens, so this check is required.
2. Low byte of the scene word (`0x8C27CB64`) is not `8` (scene `0x0308`) -> vanilla.
3. Pick the raw, active-low input word of the side that joined: bit 1 of the wipe-pending mask set = 2P (`0x8C375A08`),
   else 1P (`0x8C374208`). Bit 2 = A, bit 3 = Start, bit 10 = B.
   - A held -> target = RESTORE (see below), then `fn_8c0ca038`.
   - else B held -> target = BSEL.
   - else -> vanilla.
4. For the two rematch cases: clear `0x8C27CB5C` (so `fn_8c095854` has nothing to wipe), and tail-jump (`jmp @r1`) to
   the target. Both targets are ordinary main-task callbacks (`r4` = task).

### 3. B + Start: BSEL (code cave F4, `0x8C0F87E2..0x8C0F8822`, also dead)

Clears bit 1 ("leader already chosen") in `team0+0xA0` for both sides, then jumps to `fn_8c0699bc` (the VS screen with
leader and order select, scene `0x0302`). The clearing is needed because the leader input task `fn_8c06b1e0` skips itself
when that bit is set. Normally the wipe clears the bit, which we deliberately avoid. F4 also holds the shared literal pool.

### 4. A + Start: order backup (SAVE / RESTORE)

The game rotates the order word (`team+0x78..0x7A`) after every KO and clears the leader flag of the loser. Match init
simply takes `order[0]` as the starting fighter, so after a match the original order and leader are gone from RAM.
Therefore:

- **SAVE**: in `fn_8c0699bc`, the literal at `0x8C069A74` (the only reader is `0x8C069A1E`) holds `fn_8c0ca038` as the
  callback after order select. It now points to SAVE. SAVE copies, for both sides, the order word and the three position
  bytes (which contain the leader flag) into a 16-byte buffer, then jumps to `fn_8c0ca038`. At that point order and leader
  are final.
- **RESTORE**: copies the buffer back, then jumps to `fn_8c0ca038`.
- Code and buffer live in `fn_8c0661bc` (`0x8C0661BC..0x8C06625C`), an unreferenced twin of `fn_8c06625c`: no raw pointer
  to it anywhere in the ROM, no `bsr`, no PC-relative reader. The build script checks that nothing points into the range.
  The buffer is pre-filled with the default order in case no SAVE ever ran.

### 5. Why `fn_8c0ca038` is the right entry

It requests scene `0x0303` and registers `fn_8c0ca0c8`, which runs the normal match initialisation (health, stun, guard =
112, meter, point, timer 99). The patch does not reimplement any of it.

## How the build works

```
python quick_rematch.py --in ax3201p01.fmem1 --out DIR [--no-scene-check]
```

- Input: the **unmodified** ROM (decrypted internally). The script checks every expected original byte (anchor branches,
  live literals, the 7 callback literals, twin header) and aborts on a mismatch.
- `--no-scene-check` drops step 2 of the wrapper (diagnosis only).
- 256 bytes differ from the original ROM.
- `build_arcade_rom.py` applies it together with the other hacks (see [`arcade-build.md`](arcade-build.md)).

### Combining with other patches

The patch touches bytes in `0x562BC..0xE891D`. The other patches do not overlap with it:

- Boss unlock: file offset `0x5675A`, `00 -> FF` (immediate of `mov #0,r2` in `0x8C066646`), `unlock_bosses.py`.
- Same characters: file offset `0x579E5`, `8B -> A0` (`bf` -> `bra` at `0x8C0678E4`), `samechars.py`.
- Bilinear off (point sampling): three `or` instructions that set the TSP FilterMode bits (13-14) become `nop`
  (`09 00`), the same three sites the Dreamcast port patches, `bilinear_off.py`:
  - `0x000622` (`0x8C010522`): `4b 20` `or r4,r0`, global TSP setter `fn_8c010516`.
  - `0x0A9184` (`0x8C0B9084`): `1b 20` `or r1,r0`, `fn_8c0b8f4e`, bit `0x2000` of `ctx+0x494`.
  - `0x0A9208` (`0x8C0B9108`): `2b 21` `or r2,r1`, `fn_8c0b8f4e`, bit `0x4000` of `ctx+0x494`.
- Combo damage display: see [`arcade-combo-damage.md`](arcade-combo-damage.md).

Combine them in the *decrypted* domain (apply all patches, encrypt once). Do not merge encrypted files.

## Real hardware / AW Multi: program checksum

Emulators do not check it, real hardware does. The cart's ASIC sums the *decrypted* program bytes (range from the header:
offset `0x60`, size `0x68`, KOF XI `0x100..0x12291F`), each byte with its nibbles swapped, mod 256. The result must equal
the cart key (`0xD3`), otherwise the mask ROMs stay locked and the screen stays black. The original gives `0xD3`; patched
builds did not, which matched the black screen on the AW Multi (2026-11-14). The Metal Slug 6 "Blood" hack compensates this
exactly with a header byte. The rule is described in MAME (`awboard.cpp`). **Confirmed on hardware (AW Multi,
2026-11-21).**

Every patched fmem1 must go through `aw_checksum.py` as the last step (`build_arcade_rom.py` does this):

```
python aw_checksum.py fix IN.fmem1 OUT.fmem1 --forge-crc 6dbdd71b
python aw_checksum.py check OUT.fmem1
```

`fix` adds one compensation byte at decrypted `0x122910` (zero padding) and `--forge-crc` rewrites the last 4 bytes
(outside the checked range) so the CRC32 equals the original. Do the compensation after merging all patches, not per patch.

## v11: only the joining side counts (2026-11-22)

v10 ANDed the raw input words of both sides, so the *winner* holding A or B while the loser pressed plain Start also
triggered the rematch (found at the dojo on the AW Multi, 2026-11-21). v11 reads only the side that joins: the wipe-pending
mask `0x8C27CB5C` has bit 1 set for 2P and bit 0 for 1P, and the wrapper picks `0x8C375A08` (2P) or `0x8C374208` (1P)
accordingly (`mov.b @r3,r2` + `tst #2` + one more literal load; 27 of 28 available instructions). Confirmed in Flycast and
released as arcade patcher v1.1.

## Open points

- v11 is tested in Flycast; v10 ran on real AW Multi hardware.
- The rematch needs about 463 frames to load, which cannot be shortened simply (12-state loader, mostly resource loading).
- The stage choice between matches was not traced; observed behaviour in tests is a normal stage load.
