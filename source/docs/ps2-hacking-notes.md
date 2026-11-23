# KOF XI (PS2): reverse engineering and ROM-hack notes

Working notes from porting the Atomiswave hacks (combo damage display, quick rematch, ...) to the PS2 version of
The King of Fighters XI, plus everything learned about the game on the way. Written 2026-11-19, updated 2026-11-23. All addresses are **EE virtual addresses of the JP ELF** unless stated
otherwise. No game data (ISO, ELF, decompiled sources, saves) is stored in the repository.

Companion docs: [`hack-patch-table.md`](hack-patch-table.md) (patch table), [`ps2-graphics-db.md`](ps2-graphics-db.md) and
[`ps2-graphics-workflow.md`](ps2-graphics-workflow.md) (graphics).

## 1. Status

Nine hacks are built into one patcher (`toolkit/make_combo_dmg_ps2.py`). They are tested in PCSX2 2.8.2 (32 MB EE RAM,
default settings) and on a real PS2 (Mad Gear Edition, via OPL). Details and addresses are in
[`hack-patch-table.md`](hack-patch-table.md).

| Hack | Notes |
|---|---|
| Combo damage display | MIPS port of the SH-4 wrapper (task fn hook + text printer); stun line and DISPLAY option |
| Better practice mode | practice menu rework: DISPLAY, INPUT, QUICK RESET, GAUGE options, COMMAND ENEMY, GUARD ALL / RANDOM, 2P menu |
| Unlock all | one u16 unlock mask forced to 0x3FFF |
| Quick rematch (Arcade Versus) | hold Square (A) = same team, hold Cross (B) = order/leader select |
| Same characters | skip duplicate check, always load palettes |
| Skip start-up logos | only the SNK Playmore logo (LOGO04) is kept |
| Version display | Mad Gear version in the main menu |
| Main menu clock: no spin | the clock stays still |
| Fix PS2 differences | arcade frame data for characters that differ in PS2 Arcade Mode |

Not done: a US port (only Skip intro logos exists for the US disc).

## 2. The game versions

| | JP | US |
|---|---|---|
| Serial / ELF | SLPS-25660, `SLPS_256.60` | SLUS-21687, `SLUS_216.87` |
| ELF size | 3,168,728 bytes, MD5 `336650d6c0dd2a84dca7910ac134e20d` | 2,037,464 bytes |
| ISO | 2,540,208,128 bytes, MD5 `2bb2d183e85964a799f3eb73b5812a71` | MD5 `7a894aecf26968042f333a9732d412b6` |
| ELF location in the ISO | LBA 1228545 (2048-byte sectors), fixed size | different layout |

- The ELF has one file-backed `PT_LOAD` at vaddr `0x100000` (file offset `0x100`, filesz `0x305700` in JP) and a
  huge BSS (`memsz 0x1CFBF80`, i.e. up to about 31 MB of the 32 MB RAM). Code ends at about `0x359C88`, data follows.
  There are no symbols.
- The US ELF is a **different build** (smaller, completely shifted). Nothing in this repo's JP addresses applies to
  it. Same source code though, so the same functions exist and can be found again by strings and structure.
- The Atomiswave ROM and the PS2 game share the game logic source. Struct layouts are the same with different
  offsets and strides (see section 6).

## 3. Tools

### Other useful tools (not part of this repo)

- PCSX2 2.8.2 with stock settings (32 MB EE RAM) is the test base; "128mb" builds can hide bugs that show on a real PS2.
- Cheat Engine (CE base `0x20000000` for PCSX2 EE RAM) and the **kof-combo-hitboxes** (odabugs) KOF XI module, whose
  `lua/game/pcsx2/kof_xi/game.lua` holds the per-region team and player table pointers (NTSC-J, NTSC-U, PAL).
- A real PS2 loading the ISO through OPL (USB / network / HDD) for final tests.

### Tools used in this work

| Tool | Use |
|---|---|
| Ghidra **12.1.4** + `ghidra-emotionengine-reloaded` v2.1.39 (language `r5900:LE:32:default`) + JDK 21 (Temurin) | auto-analysis and whole-program decompile of the JP ELF |
| Python 3.12 + `capstone` (MIPS64 LE with `skipdata`) | disassembly of patch sites and stubs |
| Python 3.12 + `keystone-engine` (`pip install keystone-engine`) | assembling the MIPS stubs |
| Windows `tar.exe` (bsdtar) | unpacks PCSX2 savestates (`.p2s` = zip with zstd entries, GNU tar cannot read them) |
| PCSX2 debugger, savestate diffs | find RAM addresses without GDB (see method) |

Ghidra 12.2 needs JDK 25 and failed headless here with a Felix/OSGi NPE ("The data file must be inside the data
dir"); 12.1.4 on JDK 21 works. The project lives outside the repo (ELF copies, `proj/`, decompile text).

## 4. Method that worked

1. **Extract the ELF** from the ISO by reading the ISO9660 root directory (a few lines of Python or PowerShell),
   import into Ghidra headless without analysis, then analyse and decompile every function into one text file. `grep` the decompile text.
2. **Find anchors by strings**: task names (`"HitCombo"` at `0x4036D8`), file name formats (`"LOGO\LOGO%02x.DAT"` at
   `0x4035B0`), the name-entry alphabet (`0x3638F0`). MIPS code builds addresses with `lui`/`addiu`; scan the ELF
   for those pairs (a small script that scans the ELF for the `lui`/`addiu` pair).
3. **Compare with the arcade (Atomiswave) version**: the structure of the functions is
   identical, so a decompile comparison confirms a pair quickly.
4. **Savestate diffs**: save in two situations (neutral / 2-hit combo / 5-hit combo / victory screen), unpack
   `eeMemory.bin` (32 MiB, file offset = EE physical address) and diff. This found the combo counter, HP slots, scene
   word, mode byte and the save buffer. The savestate does **not** carry code patches (RAM holds the old code), so
   patched builds must be tested from a cold boot.
5. **Patch statically in the ELF** (no runtime code writes, so no EE cache issue on hardware): hooks are 1 to 6
   instructions in the ELF, stubs live in a zero run of the ELF data, the ISO is rebuilt by overwriting the ELF in
   place (same size, same LBA). The builder asserts every original word before patching.
6. **Check frame sensitive input on the right word**: the game keeps a held word and a press-edge word (section 6).

## 5. Free space and patching rules

- Zero run `0x3A2D72-0x3B34BC` (about 67 KB) inside the file-backed data; all hack code and data lives there (range
  `0x3AB000-0x3B1FFF` so far). It stayed zero in every tested savestate; if you add more, check with a write breakpoint
  that the game does not write there.
- `keystone` in MIPS64 mode uses N64 register names (`$t0` is `$12`). Write `$8`..`$15`, `$24`, `$25` numerically.
  Always start with `.set noreorder`, otherwise keystone inserts its own delay-slot `nop` after every branch.
- The R5900 `sq`/`lq` instructions show up in capstone as `ext`/`...qb` garbage; relocated prologues must be copied
  as raw words.
- Hooks are installed by rewriting the `lui`/`addiu` pair that loads a callback address, or a `jal` target.

## 6. Key structures (JP)

Task framework (same as arcade): `FUN_00155B50(fn, name, prio, flags, 0)` creates a task, `FUN_00155DA0(cb, task)`
sets its callback, `FUN_00156340(cb)` sets the "main.next" callback, `FUN_001A0530(scene)` sets the scene word
(u16 at `0x9BDAB0`).

- **Team structs**: `0x9BDB50 + side * 0x248` (side 0/1; up to 4 teams are iterated).
  - `+0x07` combo counter (`+0x08`, `+0x09` copies, clamped to 99), `+0x0A` side state (2 = human playing),
    `+0x28..+0x2A` order bytes, `+0x50` flags (bit 0 team selected, bit 1 "leader chosen", bit 3 cpu pick done).
  - Member blocks at `+0x14C + n * 0x20`: `+0` type, `+1..3` committed copy, `+4` char id, `+5` color, `+0x10`
    position byte (bit 7 = leader). HP u16 at `+0x154 + n*0x20` (0x70 full), visible HP `+0x156`, stun `+0x158`.
- **Player table** `0x9B6BC0`, camera pointer `0x9BDB20` (hitbox viewer, NTSC-J).
- **Input**: per pad `0x9BEA20 + side * 0xC`: `+0` held, `+2` newly pressed edge, `+4` previous, `+6` repeat.
  Bits are active high: Start `0x0008`, Triangle `0x1000`, Circle `0x2000`, Cross `0x4000`, Square `0x8000`.
  In-game button A is Square, B is Cross (confirmed for A; B works in the rematch hack). `FUN_001A3420(side, kind,
  mask)` reads them for the game.
- **Game mode** byte `0x9E9780` (0/1 arcade, 2/3, 4/5, 6/0xE, 7, 8, 0xD ...; mode 1 is the console-only "Arcade
  Versus" that returns to character select after every win). Play-sides mask `0x9BDB10`, wipe/join mask `0x9BDAF8`.
- **Scenes** (low byte of the scene word): `0x300` select, `0x301` team select, `0x302` VS order/leader screen,
  `0x303` combat, `0x308` result/victory, `0x30A` new challenger.
- **Post-scene router** `FUN_0019D740` picks the next flow by scene and mode; the victory screen of modes 1/3/5
  goes to `FUN_00130EE0` (character select) at `0x19DD5C`.
- **Unlock mask** u16 at `0x9BEC80` (14 bits). Character ids `0x21-0x27` map to bits 0-6, `0x29-0x2F` to bits 7-13
  (bosses and console characters, id `0x28` is not gated). Filled by the clear counters `0x9BEC78` and `0x9BEC44`
  (challenge progress, thresholds 5/10/15/20/25, 100/149/200) through `FUN_00357EC0`. 40 challenge flags at
  `0x9BEC50`. Char availability check `FUN_00131E40` also reads debug flag word `0x9BA210` (bit 0x80 = "PS SAME").
- **Load type** option (normal/simple/auto): `FUN_001347F0()` in `FUN_00134850` decides whether the order/leader
  select is skipped (auto: team in selection order, third member leader).
- **Resources**: sprite data are cached per char id (`FUN_0018EA60`, tables `0x9BBC40`/`0x9BBCC0`), palettes are
  loaded per slot by `FUN_0012ED00` (slot = side * 3 + member); duplicate characters skipped the palette load.
- **Text printer** `FUN_001788C0` (f12/f13 x/y, f14 x scale, f15 512.0, a0 glyph rect ptr, a1 ctx `0x9BD538`,
  a3 = 1, t0 = -1). Glyph rect tables: system font `0x3660C0 + (char-28)*8` (digits OK, most letters invalid),
  name-entry glyphs `0x363930` (63 x 16x16 rects, order of the string at `0x3638F0`).
- **Start-up**: save load first (separate function), then `FUN_00307870` (only caller `0x3079CC`) plays
  `\DATA\LOGO\LOGO00..04.DAT` for 194 frames each with fades; `FUN_00307350(n)` loads one via
  `FUN_001A3DB0(path, buffer)`; `FUN_00307800` computes the fade alpha, `FUN_003076D0`/`FUN_00307390` upload the
  image in 5 x 4 tiles to the GS. `LOGO05.DAT` exists but is unused there.
- **HUD animation system ("Director", 2026-11-22)**: battle HUD pieces like the HIT COMBO counter are scripted.
  - `0x321f90(id, group)` returns the director slot `0x1DCC410 + (base + id) * 20`, base = u16 at `0x1DCF028 + group * 4`
    (group 2 base = 3). Slot `+0` = 'Director Ctrl' task (fn `0x327CF0`), `+0xA` = **pause** flag (not visibility!),
    `+0x12` frame counter. `0x323890(id, 1, group)` starts a script, `0x323B40(id, group)` = finished, `0x323B70` = playing,
    `0x323510(id, v, group)` writes `+0xA`.
  - The director scripts spawn 'Director Sprite' actors (task fn `0x327F10`) registered by `0x3235F0` in the actor slots
    `0x1DC9410` (0x200 x 0x18: `+0` task, `+4` group, `+8` director id, `+0xC` visible byte, `+0x10` depth float).
    The visible byte is set to 1 ONLY there (`0x323668`) and cleared by the slot reset `0x322B40`; `0x327F10` draws only
    when it is set. Clearing it hides a sprite without touching the script logic.
  - The HitCombo task `0x192710` (one per side, state byte task+1, `0x1924D0` sets the pause flags) is pure logic plus
    script starts: side 0 uses directors `0x15..0x1B` + `0x23`, side 1 `0x1C..0x22` + `0x24` (group 2). It also computes a
    per-combo value (stored at team `+0x48`, passed to `0x18D3E0` / `0x19FE60`, probably score/bonus), so never skip the whole call.

### Arcade to PS2 function map (verified in the decompile)

| Arcade | PS2 | Role |
|---|---|---|
| `0x8C0A8B88` | `0x192710` | HitCombo task |
| `0x8C079918` | `0x155B50` | create task |
| `0x8C06154C` | `0x323890` | start effect animation |
| `0x8C0DF798` | `0x1788C0` | text printer |
| `0x8C0DA0DC` | `0x154AB0` | scene dispatcher |
| `0x8C06625C` | `0x193980` | "new challenger" callback |
| `0x8C0699BC` | `0x134850` | VS order/leader select |
| `0x8C0CA038` | `0x30D750` | match start callback |
| `0x8C06779C` | `0x131E40` | char availability / duplicate check |

## 7. Save data

PS2 memory card save (`BISLPS-25660SYS` JP, `BASLUS-21687SYS` US), 169,400 bytes. Built by `FUN_002FD4A0`, read by
`FUN_002FD760`: file offset to RAM: `+4` u16 (0x80), `+6` 0xC000 to `0x9BF240`, `+0xC006` 0x2A8 to `0x9BEF90`,
`+0xC2AE` 0x2A8 to `0x9BECE0`, `+0xC556` 1 byte to `0x9CB288`, `+0xC557` 0x1CC24 to `0x9CB290` (2 x 49 records of
0x4B2 bytes, replay/ghost data), then small blocks (`+0x2917B` ... `+0x294F8`), including `+0x291AE` 0x2A to
`0x9BEC50` (challenge flags), `+0x29222` mask to `0x9BEC80`, `+0x294F8` 6 bytes to `0x9BEC40`. The first four
bytes are four byte-sums, each over a quarter of the data (`FUN_002FD2C0` / `FUN_002FD3A0`). A modified save needs
correct sums.

## 8. Gotchas

- PCSX2 "128mb" builds enable `ExtraMemory` (128 MB EE RAM). A mod can look fine there and fail on a real PS2 (32 MB).
  Test on stock settings; check `eeMemory.bin` in a savestate (33,554,432 bytes = 32 MB).
- PCSX2's auto updater fails on paths containing `#` (error 3 "failed to open update.7z").
- PCSX2's Frame Advance hotkey only works while the game runs; it cannot be used to land a savestate on a held
  button. Use the diagnostics words (`0x3AB0A0`) instead.
- Pad words: `+2` is the press edge only (lasts one frame); a "hold" check must read `+0`.
- Hardware reminders: 32 MB EE RAM, 2 MB IOP RAM, 4 MB GS memory, no extended RAM, EE cache is on. Static patches in
  the ELF avoid cache coherency problems; runtime code writes would need a cache flush.

## 9. The `LOGO0x.DAT` format (solved 2026-11-19)

Format and replacement are solved (2026-11-19), plus the title logo and the attract-mode logo; see
[`ps2-graphics-workflow.md`](ps2-graphics-workflow.md) and [`ps2-graphics-db.md`](ps2-graphics-db.md).  The notes below
record how the format was found.

### Result (2026-11-19, analysed on the unmodified JP ISO)

- All six files sit in `\DATA\LOGO\` at LBA 243389, 244029, 244669, 245309, 245949 (LOGO04), 246589, each exactly
  `0x140000` = 1,310,720 bytes (640 sectors). **No header, no compression**: raw RGBA8888.
- Image is 640x512, stored as 5 x 4 tiles of 128x128 px (0x10000 bytes each, tile index `col + row*5`, pixels
  row-major inside a tile). Alpha is PS2 style: `0x80` = opaque, `0x00` = transparent (LOGO04 uses only those two).
- LOGO04 shows "SNK PLAYMORE" (light blue and green on white) in the upper-middle part, the rest is white.
- Replacement: `toolkit/logo_dat.py decode|encode` (PNG 640x512 <-> DAT, bit-exact roundtrip verified).
  Same size, so the file can be overwritten in place in the ISO (LBA 245949, 640 sectors), same as the ELF patch.
- The game may crop to 640x448 on screen, so keep important content in the centre. The in-game result was confirmed in
  PCSX2 and on a real PS2. The "skip logos" hack keeps only LOGO04.

Do not commit ISO/ELF/decompile output or saves; keep them next to the project (`.gitignore` covers common cases).


## 10. Quick reset and practice hacks (2026-11-20, lessons)
How the instant reset was found (details in `hack-patch-table.md`). Method: PCSX2 savestates are zips; `tar.exe -xf x.p2s eeMemory.bin` gives the
32 MiB EE RAM; the task list lives at `0x9AFFD0 + prio * 8` (head, tail), task: +4 prio, +8 function, +0x10 data, +0x14 next, name at +0x22. Diffing a healthy
savestate against a broken one (same character, same situation) found every bug below in one or two rounds, guessing from the decompile alone failed three
times (CPU dummy for COMMAND ENEMY).
* Character struct (`*(obj + 0x10)`, obj = `team + 0x78 + pt * 4`): action +0xEC (+0xF0 request), flags +0x48C..+0x4A0, hitbox validity +0x39F (re-armed only by an action
  start `FUN_0016B440`, cleared by the init `FUN_00189CD0`), pushbox exclusion bit 0x20 of +0x3A4 (set by the init, `(+0x3A4 & 0x38) == 0` is the collision test),
  freeze kind +0x57D / +0x57E, freeze bit 27 of +0x494 (the char task then only advances the animation, no input), regen timer +0x4A6.
* A hit swaps task functions: victim char task 0x141CF0 -> 0x1829D0, helper task 0x1860F0 -> 0x17FA60 (counts +0x57D down); the freeze controller records
  are at `0x9BB860`. A reset in the middle of a hit has to restore all of them.
* Projectiles are two tasks sharing one struct: BUL_CTL (prio 31..34, `team+0xC0` list) and BULLET (prio 41..44, `team+0x100` list, runs the char fn 0x141CF0).
* Round setup `FUN_0030DA70` respawns everything (tasks killed by `FUN_00155A10`); the instant reset reuses its per-char init calls instead.
* ELF file offset = vaddr - 0x100000 + 0x100 (forgetting the +0x100 shifts every disassembly).
* `jal label` inside a long keystone source becomes a PIC `jalr`: use absolute `jal 0x...` and grep the output for `jalr`.
* Practice settings (bytes `0x9CB240..`) are saved to the memory card with the save, so a value chosen once is loaded at the next start.
* **PINE is faster than savestates for live questions** (PCSX2 > Settings > Advanced > PINE, slot 28011, TCP localhost; packet = u32 total size, u8 opcode, args; opcodes read8/16/32 = 0/1/2,
  write32 = 6; reply = u32 size, u8 status (0 ok), data). Reading the pad words (`0x9BEA20 + port * 0xC`: held, pressed edge) and temporarily writing a probe stub into a free cave
  (call a function, store the result in `DATA+0xF0`) found the 2P-Start bug in minutes: the detection worked (`FUN_001745F0(1)` = 5), `FUN_003054D0` cancelled the pause again.
* Practice menu pads: CONTROL byte `0x9CB240` 0 = CPU, 1 = PLAYER (both human), 2 = WATCH. The menu, Start-to-pause and the editor read the pad of the owner (`0x9E9748`) or of the edited side
  (`0x9E9730`); the 2P / other-side features patch those reads (see hack-patch-table.md "Triangle on COMMAND" and "2P in the practice menu").
* **Block vs hit** (practice dummy, found live): see hack-patch-table.md "GUARD: ALL". Pose byte of an animation frame: char struct `+0x27E` (0 stand, 1 crouch, 2 air); `+0x490` bit 0 = attack action active; `+0x530` bit 0x400 = guard
  stun; action IDs: crouch idle 5, stand guard pose/stun/recovery 47/49/48, crouch guard 43/45/44/46 (light) and 51/53/52/54, stand hit 39..42. Stun action = guard pose action + 2.
* PINE tooling: batched reads (several read32 commands in one packet) read a 0x600-byte char struct per frame in < 1 ms, enough for per-frame recordings; write probes into a free cave (counters at e.g. `0x3B1F00`) and flip a call site.
  Caveat: the EE recompiler keeps stale blocks for some pages (writes at `0x337xxx` never took effect, the menu / `0x140xxx` / `0x180xxx` sites did), so verify a live patch with a counter before trusting a negative result.
* Guard action sets and the rule "do not freeze the stance in stun": see hack-patch-table.md "GUARD: ALL". Debug recipe that finally found the chain bug: ring buffer probe at the hook site (type, attacker flags, defender `+0x530`, `+0x48C`, action before / after the hook), then a per-frame recording with `prev action` (`+0xEE`) in the print: `prev` shows an action that was set and overwritten inside one frame.
* GUARD RANDOM / RANDOM ALL and the PIC trap (keystone `jal label` -> `jalr` through `$gp`, froze the game; `assert_no_pic()` in the builder): see hack-patch-table.md "GUARD: RANDOM / RANDOM ALL". Debug recipes that worked: savestate of the freeze + capstone of the cave (found `jalr`), trigger-on-first-contact recorder with per-frame (attacker act, dummy act, BLK, STK, tick) to find the idle re-roll that injected "back".
