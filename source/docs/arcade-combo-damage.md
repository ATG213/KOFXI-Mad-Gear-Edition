# KOF XI (Atomiswave): combo damage display ("NN DMG" under HIT COMBO)

ROM patch for `ax3201p01.fmem1` (SH4 program ROM). It prints the total damage of a combo below the HIT COMBO counter, from
the 2nd hit on, together with the counter (`18  DMG`). Built by `arcade/hacks/combo_damage.py` (wrapper from
`dmg_wrapper.py`). Developed live in Flycast (debug build with the GDB server) on the unmodified retail ROM, then built into
the full Mad Gear ROM. Ran on a real AW Multi (dojo test, 2026-11-21).

Addresses are guest SH4 addresses; the program is loaded at `0x8C010000` from file offset `0x100`
(file offset = address - `0x8C00FF00`).

## TL;DR: how the text / numbers are rendered

The game already has an immediate-mode text/sprite printer that anything can call once per frame:

```
fn_8c0df798(r4 = glyph rect ptr, r5 = ctx, fr4 = x, fr5 = y, r6 = 0, r7 = 1, fr6 = size, fr7 = depth, stack = (-1, 0))
```

| Arg | Value we use | Notes |
|---|---|---|
| `r4` | pointer to an 8-byte **glyph rect** `{u16 u, v, w, h}` | a rectangle in the font atlas (see tables below) |
| `r5` | `0x8C35BE94` | atlas/draw context; every caller (name entry, score text, HUD debug text) passes this |
| `fr4`, `fr5` | x, y as floats | screen pixels (the frame is at least 640 wide: P2 text sits at x = 570); x grows to the right, y grows downwards (y = 238 is just below the HIT COMBO label; verified by moving the text) |
| `r6`, `r7` | `0`, `1` | copied from the existing callers |
| `fr6` | `17.0` (name-entry glyphs), `15.5` (system font) | size/scale, copied from the callers |
| `fr7` | `512.0` | depth / sort value, copied from the callers |
| stack | `[sp] = -1`, `[sp+4] = 0` | two words pushed before the call, popped (`add #8,r15`) after it |

It draws one glyph per call, so a string is a loop: pick a glyph rect per character, call, add the advance to x.
It is immediate mode: nothing persists, so the call has to happen **every frame** while the text should be visible.
Drawn text sits **behind** the big HIT COMBO digits when they overlap.

### Two glyph tables (this is the important part)

Both use the same context `0x8C35BE94` (so the same atlas), they only differ in which rectangles they point at.

1. **System font table `0x8C12EDCC`**, entry = `(char - 28) * 8`. Only entries `0..46` (chars 28..74) are valid.
   Digits `0`-`9` are entries 20..29 (white italic 16x24), the rest are punctuation cells and wide word graphics
   ("INSERT MORE COIN(S)" etc.). **There are no letters in it.** Entries `>= 47` are not glyph rects but other
   data (pointers, `0xFFFF` fills), which the printer happily reads as huge rectangles. Symptom if you index past
   the end: a white block over half the screen, black vertical bars, garbage glyphs.
2. **Name-entry table `0x8C131FA4`**, 63 entries of 16x16 cells. Index = position of the character in the string
   at `0x8C131EE4`:

   ```
   ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?"#$%&'()[]:;,.<>+-*/=_ {}
   ```

   So `A`=0 ... `Z`=25, `1`..`9`=26..34, `0`=35, space=60. This table has the letters and a digit set that matches them
   (same size, same baseline), so the display uses it for **everything** (digits and "DMG"); the name-entry
   screen draws with `fr6 = 17.0`.

The name-entry code stores *indices* into this table in the name buffer (`0x8C189146...`), not ASCII.

### How it was found (reproducible)

1. `HitCombo` is a task. Search RAM for the string `HitCombo` (`0x8C111C50`); the literal refs lead to
   `0x8C0CB438` / `0x8C0CB482`: `fn_8c079918(fn = 0x8C0A8B88, name, prio = 57, flags = 3)`. Its per-frame function
   `0x8C0A8B88` runs once per side. It does **not** draw the big digits (it starts effect animations through
   `fn_8c06154c(animId, 1, 2)` and adds a combo bonus score to `team+0x44`), which is why scanning for the counter
   address finds no digit drawing.
2. The function directly after the HitCombo task, `0x8C0A9318`, prints a small `team+0x64` number with
   `sprintf` (`0x8C0FC934`, format `%02d`) and `fn_8c0df798`: this gave the call convention and the context.
   Its constants: x = `120 + 14*i` (P1) / `552 + 14*i` (P2), y = `-5.0`, `fr6 = 15.5`, `fr7 = 512.0`.
3. For letters: the name-entry string `ABC...` at `0x8C131EE4` is referenced by the name-entry logic
   (`0x8C0EB380`, `0x8C0EB49C`). A RAM scan for runs of plausible `{u,v,w,h}` entries (w,h in 8..0x40, u+w and v+h
   below 0x400) finds the glyph table exactly `0xC0` bytes behind that string (`0x8C131FA4`, 63 entries, first rect
   `(16,32,16,16)`). The name-entry draw code (`0x8C0EB690...`) calls the same `fn_8c0df798` with the same context and
   `fr6 = 17.0`, `fr7 = 512.0`, glyph pointer `0x8C131FA4 + index*8`.
4. Prototype live (below), tune positions/spacing live, then build into the ROM.

### Layout used

* Glyph advance 13 px, the space glyph has its own advance of 9 px (so number and "DMG" are 16 px apart on screen
  in the 2x screenshots); text is **centered** on a per-side x (P1 `61`, P2 `570`), y `238`, computed from the
  summed advances of the string (1, 2 or 3 digits).
* All of these are plain words in the data area, so they can be changed in a running game.

## What the display needs from the game

| Fact | Where |
|---|---|
| Combo counter | `team + 0x57` of the **attacker** (P1 `0x8C27CBAB`, P2 `0x8C27CDA3`), counts 1..N, back to 0 when the combo ends |
| (copies) | `+0x58` previous-frame copy, `+0x59` latched copy clamped to 99 (not reset at the end) |
| Team structs | `team = 0x8C27CB54 + side * 0x1F8` |
| HP of a member | `team + 0x150 + slot*0x20 + 4` (u16, `0x70` = full); `+6` visible (red bar lag), `+8` stun |
| **Defeated member** | its HP word becomes **`0xFFFF`** (not 0!). Summing raw words makes the sum jump by 65535 and the damage clamp to 0. Words `> 127` count as 0. |
| HitCombo task data | `@(16,task)`: byte 0 = side, byte 1 = state (0,1,16,17,18,32,33,48), byte 2 = anim id |

Damage = victim HP sum (3 slots, `0xFFFF` -> 0) at the moment before the combo started minus the HP sum now. No hook
into the damage formula is needed (damage is randomised, the HP delta is the real value). The "before" value is the
HP sum from the last frame in which the counter was 0 (the first hit's damage is already applied in the same frame the
counter becomes 1).

Display rules: nothing at counter 0/1, drawn from counter >= 2, and for a short hold after the counter drops to 0
(default 10 frames; the HUD counter fades out). A hold timer per side re-arms at counter >= 2 and counts down at
counter 0. It is **cleared as soon as the counter is 1** (fix): otherwise a single hit landing within the hold
window after a combo (e.g. a wake-up hit on a knocked-down opponent) would re-show its damage without a counter.

## Patch

Nothing live is overwritten: two literals and zero padding.

1. **Hook:** the two literal-pool entries `0x8C0CB468` and `0x8C0CB534` hold `0x8C0A8B88` (HitCombo task function
   pointer, read only by the `mov.l ...,r4` before `fn_8c079918`). They now point to the wrapper. The wrapper calls
   the original function first (so the counter animation is untouched), then runs the damage logic.
2. **Wrapper (code cave):** `0x8C126000..0x8C126260` (0x260 bytes).
3. **State/parameters:** `0x8C125700..0x8C12577F`: per side `{start, dmg, centerX, y}` (16 bytes) at `0x8C125700`,
   advance/space advance at `0x8C125730`, hold length at `0x8C125738`, hold counters at `0x8C125740`, suffix string at
   `0x8C125760` (name-entry indices with bit 7 set, " DMG" = `BC 83 8C 86`).
4. Both areas are inside the zero run `0x8C125354..0x8C126460` of the loaded image (before the BSS at `0x8C15EA80`).
   The build script checks that the targets are zero and that **no 32-bit value anywhere in the 8 MB image points
   into `0x8C125340..0x8C126470`**. A watcher over the whole region while going through fight, versus, both
   quick-rematch routes, arcade, demo, service menu and name entry saw no writes outside our own data.
5. The program checksum changes, so the finished ROM is fixed afterwards with `aw_checksum.py` (sum `0xD3`, compensation
   byte at decrypted `0x122910`, CRC32 forged back to `6dbdd71b`). `build_arcade_rom.py` does the whole chain
   (decrypt -> patches -> encrypt -> fix).

Wrapper pseudocode (registers: r8 side, r9 attacker team, r10 victim team, r11 state, r13 x, r14 string ptr):

```
orig_hitcombo_task(task)
side = *(u8 *)task->data;            att = TEAM + side*0x1F8;  vic = TEAM + (1-side)*0x1F8
cnt  = att[0x57];   sum = sum(hp>127 ? 0 : hp  for the 3 slots of vic)
if cnt == 0: state.start = sum; if hold == 0: return; hold--; dmg = state.dmg; goto draw
dmg = max(0, state.start - sum); state.dmg = dmg
if cnt < 2: hold = 0; return
hold = HOLDLEN
draw: build [digits (name-entry idx | 0x80)] + suffix, width = sum(advance), x = center - width/2
      for each char: DF798(NEWTAB + idx*8, 0x8C35BE94, x, y, 0, 1, 17.0, 512.0, -1, 0); x += advance
```

`bit 7` of a string byte means "name-entry table"; bytes without it index the system font table (kept for tests).

## Tooling

* `arcade/hacks/dmg_wrapper.py`: tiny SH4 assembler with labels, delay slots and a literal pool; `build()` returns the
  wrapper bytes (run it directly to get a Capstone disassembly for review, needs `pip install capstone`).
* Disassembling SH4 with Capstone: `CS_ARCH_SH`, `SH4|SHFPU|LITTLE_ENDIAN`, `skipdata=True`.
* While developing live in Flycast: the GDB stub asserts on long incoming packets, so write memory in `M` packets of at
  most 8 bytes. Live watchpoints (`Z2`/`Z3`) freeze Flycast; use static disassembly plus plain RAM reads instead.

## Open

* The large HIT COMBO digits themselves come from the effect/animation system (`fn_8c06154c` anim ids 21..36,
  "Director Ctrl" task `0x8C064EBC`); how the counter value becomes those sprites is not reverse engineered.
