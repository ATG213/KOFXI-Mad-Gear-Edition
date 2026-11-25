# KOF XI PS2 (JP, SLPS-25660) hack builder

`make_combo_dmg_ps2.py` (despite its name it builds all the hacks) patches the ELF `SLPS_256.60` **in place** (same size, same LBA, only changed bytes) and can
write a copy of the ISO with the patched ELF. Needs `keystone-engine` and `capstone` (pip).

```
set PYTHONUTF8=1
python -I make_combo_dmg_ps2.py --iso "KOFXI JP.iso" --out-iso "KOFXI JP all-hacks.iso" [--out patched.elf] [--dump]
  --no-unlock --no-rematch --no-samechars --no-skiplogos --no-version --no-optdisplay --no-display   (skip single hacks)
  --stage N    practice menu stages 1..7 (7 = everything, the default)
```

All patches are static (no code is written at run time), so there is no EE cache issue. Tested in PCSX2 2.8.2
(32 MB, default settings) and on a real PS2 (Mad Gear Edition).

A **cave** is an unused run of zero bytes in the ELF data where the added code and data live (see "Free space" below).

## Patches (all addresses are EE virtual addresses of the JP ELF)

| Hack | What | Where |
|---|---|---|
| Combo damage "NN DMG" | MIPS wrapper around the HitCombo task fn `0x192710`; victim HP sum at combo start minus now; text via printer `0x1788C0` with the name-entry glyph table `0x363930` | cave `0x3AB100`, data `0x3AB000`, hooks: `lui`/`addiu a0` at `0x30FD80/88`, `0x30FDA4/AC` |
| Unlock all | u16 mask `0x9BEC80` forced to `0x3FFF` (14 locked chars: ids `0x21-0x27`, `0x29-0x2F`) | `jal` hooks at `0x336DBC` (new save init) and `0x2FD8F8` (save loader), stubs `0x3AB500`, `0x3AB540` |
| Quick rematch (Arcade Versus, modes 1/3/5) | hold A (Square) on the victory screen: restore team and start match `0x30D750`; hold B (Cross): clear "leader chosen" (bit 1 of team+0x50) and open the order select `0x134850` | `WRAP` `0x3AB6C0` replaces the block at `0x19DD5C`; `STUB_SAVE` `0x3AB600` saves order/leader at the two sites that install `0x30D750` (`0x1348A8/B4`, `0x134904/0C`); buffer `0x3AB080`; diagnostics `0x3AB0A0`; **forced SIMPLE load**: WRAP writes byte `0x3AB0AC` = 1 when A or B is held (0 otherwise), `LT_CAVE` `0x3AB900` replaces the tail of `FUN_0030D7D0` (`0x30D818`) and returns `(load type | flag) != 0`. Reason: Load Type NORMAL after a rematch allocates an extra 5-7 MB block, heap runs dry, `FUN_001A4B80` returns 0, the char loader writes to address 0 (kernel vectors) -> freeze |
| Same chars | skip the "already in team" loop (`0x13210C` `bnez` -> `b`) and always load the palette (`0x12ED4C`, `0x12ED68`) | `FUN_00131e40`, `FUN_0012ED00` |
| Skip start-up logos | logo player `FUN_00307870` starts at LOGO04 (SNK Playmore) instead of LOGO00 (`0x307898` `move $s1,$zero` -> `addiu $s1,$zero,4`); save load before it is untouched | `LOGO_START` in the builder, `--no-skiplogos` |

Pad words: `0x9BEA20` held (side 0), `0x9BEA2C` (side 1); `+2` = press edge. Team structs: `0x9BDB50 + side * 0x248`.

Free space used: zero run `0x3A2D72-0x3B34BC` (zero in RAM in all tested states; used range `0x3AB000-0x3B1FFF`).

## Not done / open
- US port (SLUS-21687 has a different ELF layout, all addresses need to be found again).

## Display option (stun / damage) and practice menu
Two app hacks (`export_hack_patches.py` -> `gfx_hacks.json`, applied by `gfx_hacks.py`):
* **combo** = combo damage display with a stun line + the row `DISPLAY : DAMAGE / STUN / BOTH / OFF` in OPTIONS > GRAPHIC SETTING
  (default DAMAGE). Option byte `0x9CB287`, saved at save+0x294FE (hooks `0x2FD6F4` / `0x2FD9BC`), page code `0x3342D0`
  (input), `0x3347C0` (row objects, new type 11), `0x334E00` (cursor bar), jump tables copied to `0x3AD040..`, stubs
  `0x3AD100..`, rows 32 px higher. Stun shown = running maximum of (start - now) of the combo (stun regenerates).
  Graphics: the five words (DISPLAY, DAMAGE, STUN, BOTH, OFF) are in the empty bottom of **SPR00.GRC page 2** (y 384..447,
  `practice_labels.py --option-display`, palette indices 250 / 251 of page 2 are set to orange / teal).  Until Mad Gear 1.2 they overwrote the rows
  JUDGMENT INDICATOR and SINGLE ROUND of page 5, which GAME OPTION > BATTLE SETTING uses (reported 2026-11-22).  The 5th short `p` of a rect entry is a
  **texture slot** (while GAME OPTION is open: slot 0..3 = SPR00 pages 0 / 3 / 4 / 5, slots 4..7 free).  The setup stub `OPT_ST_SLOT` (`0x3AD340`) loads
  page 2 into slot 4 with the slot loader `0x3019D0(slot, page pointer)` (SPR00 pages are resident from `0xE2D880` in steps of `0x20400`, page 2 =
  `0xE6E080`) and SENDS it to VRAM itself with the body of the loop in `0x3020A0` (that loop only covers the first `[0x1CB0C58]` = 4 slots).  Rect
  entries use `p = 4` (`OPT_RECT_P`).  Pitfalls found on the way: `p = 0` is page 0 (main menu art), not a page offset; the ELF file offsets of the
  0x30xxxx code are +0x100 off against the real addresses, check against live memory.
* **practice** ("Better practice mode", needs combo): row AUTO CHARACTER of the practice menu becomes DISPLAY (byte `0x9CB247`,
  strings `0x3AC800`), the "settings changed" compares ignore it (`0x33A498`, `0x33A760`), flag word `DATA+0x7C` makes the HUD
  hook use it in mode 8. Label graphic: SPR01.GRC page 1 (`practice_labels.py --display DISPLAY`).
* **DMG/STUN HUD in practice mode** (HUD wrapper at `0x3AC000`, data block `DATA = 0x3AB000`; 2026-11-22):
  * Own coordinates for mode 8 (`DATA+0x30..0x3C`: P1 x/y, P2 x/y = 150/108, 490/108, under the HP bars); arcade keeps `DATA+0x08..0x1C` (61/570, y 238).
  * Practice shows the last result until the next combo overwrites it, starts at 0/0 and shows from hit 1 (arcade: from hit 2, hold timeout).
  * Third line "N HITS" (`DATA+0xB0` glyphs, count `DATA+0xB8/0xBC`) when the practice INPUT option (`0x9CB24B`) is on for that side, only from 2 hits.
  * The vanilla "N HIT COMBO" counter of a side is hidden while INPUT is on for that side (Mad Gear 1.3, tested live + real PS2): `HIDE_VANILLA`
    in the wrapper clears the visible byte of that side's counter sprites every frame, and `regvis_stub` (right after the cave code, `jal` at
    `REGVIS_HOOK = 0x323668` in the actor registration) registers new ones invisible; without the stub every new hit flickered for one frame.
    Background in `ps2-hacking-notes.md` (HUD animation system).
  * Stun = running max of (start - now), never above 112.  The stunning hit: the dizzy refill sets the stun back to 112 in the SAME frame, so 0 is
    never visible; if the raw difference is <= 0 after a counted hit the display shows `start - cur + 112`.  The combo counter (`team+7`) stays 1 for
    many frames until the 2nd hit, so the max is reset by a marker (`DATA+0xC0+4*side` = -1 while no combo runs), not by `counter == 1`.
  * practice LIFE: RECOVERY no longer refills during dizzy: dizzy flag = bit 0x40 of char object byte `+0x4f0` (objects P2 `0x936038 + k*0xFC0`),
    the regen function `FUN_001873f0` already skipped on bit 0x80, `andi v1,v1,0x80 -> 0xC0` at `0x187414`.  (`+0x4b2` toggles every frame, not a flag.)
  * The game's natural stun recovery (+1 per ~17F) runs during combos too; it is vanilla and left alone (only the display compensates).
* **practice COUNTER: ON fixes** (part of `practice`, `DISPLAY_PATCHES` / `pcfix_code` in `make_combo_dmg_ps2.py`): (1) `FUN_0033aaa0` forced the
  counter on every hit of a combo because it read the combo counter (`0x9BDB57 + side*0x248`) of the defender's own side instead of the attacker's
  (`FUN_0033a9b0` correctly uses `FUN_00189e50` = opponent side); a fast second attack froze the game. Patch at `0x33AAF4/F8/0x33AB04`
  (side ^ 1). (2) `FUN_0033a9b0` mapped every hit record type < 5 to 4; a real counter hit of a type-1 record (5E / j.E) is type 3, which picks
  another hit animation (effect 39: anim 323 real vs 329 forced) with 8F more limited juggle. Site `0x33AA74` -> cave `0x3AD400`: type 1 -> 3, other types
  unchanged (record byte +1 is not rewritten). Found by comparing real vs forced counter-hit savestates (PCSX2-rr 1.5.0-dev slots are zips with `eeMemory.bin`).
Graphic patches are exported as zlib/base64 pixel runs (no font needed in the app); the app checks the original bytes first.

## Practice menu layout + INPUT display
* Menu: all rows start at y `PM_BASE_Y` (0x4C, was 0x60), "SELECT BUTTON TO DEFAULT" text removed, new row **INPUT**
  (OFF / 1P / 2P / BOTH, byte `0x9CB247+4 = 0x9CB24B`, cleared by the default reset which now memsets 12 bytes) under DISPLAY.
  Cursor indices: 0 GAME START, 1..8 rows up to DISPLAY, 9 INPUT, 10 STAGE, 11 SELECT BUTTON, 12 COMMAND, 13 KEY SETTING,
  14 CHARACTER SELECT, 15 GAME EXIT (jump tables copied to `0x3AD500/0x3AD580`, position table `0x3D2830` patched in place).
  New object types 0x1A / 0x1B (label / value) created in the slot of the old default text (`0x338174`). Label graphic: SPR01 page 1
  at (128,192,128,32) (right half of the DISPLAY strip, DISPLAY rect narrowed to 128 px).
* Display: module `0x3AE000` (data `0x3AE800`) called from the HUD wrapper per side and frame (practice mode + practice flag only):
  ring buffer of pad states (count << 16 | held & 0xF8F0), draws 9 rows with the menu sprite queue (SPR03 page 1 icons, grey
  16x16 digits), 1P left edge / 2P right edge. PS2 buttons: Square A, Cross B, Triangle C, Circle D, R1 E.

## COMMAND ENEMY (KEY SETTING value 13, tested)
New button function after COMMAND in KEY SETTING (practice hack group): pressing it plays the recorded COMMAND (practice > COMMAND)
of the OTHER side on that side, so one pad is enough to test against a moving dummy. Value 13 lives in the normal assignment bytes
(`0x9CB250 + side * 9 + button`); the vanilla code ignores values >= 13, saves stay compatible.
* Menu: value cycle length `0xD` -> `0xE` at `0x332D38` and `0x3336A0` (the two KEY SETTING input handlers).
* Draw: `jal 0x302AE0` at `0x333048` (value sprite of a row) -> stub `0x3AF200`: value 13 draws the vanilla COMMAND rect (`0x3D1F80`) and a new
  ENEMY rect (`0x3AF300`, 100 px to the right). Graphic: SPR02.GRC page 1 rect (190,64,66,32), `practice_labels.py --command-enemy`.
* Trigger: `jal 0x1A3420` (press-edge word) at `0x1A29AC` inside `FUN_001A28B0` (pad -> game buttons, per side and frame) -> `0x3AF000`.
  For a pressed button with value 13 of side S it starts the playback entry of side S^1 (`0x9E8AF0 + side * 0xC`: type 3, position 0,
  data pointer `0x9CB290 + side * 0xE612 + record * 0x4B2`, record = byte `team + pt * 0x20 + 0x14D`), same as the vanilla
  `ATTACK: COMMAND` dummy (`FUN_0033B1A0` caller at `0x33B...`). Only in practice mode (mode 8, flag `DATA+0x7C`), not paused, not in the command editor
  (`0x9E95C0 == 9`); same global guards as the vanilla COMMAND button. Consumer `FUN_0033B4F0` cancels the playback when the dummy side has real pad input.

Works with CONTROL: PLAYER only. With CONTROL: CPU the dummy is not in the human input mask (see `FUN_001721E0`: `FUN_00172A10` is only called for
sides in `bdb00 | bdb10`), the team flag +0x5A / AI input (`FUN_001857C0`) are further gates; three attempts to force it failed and were removed.

**Triangle on COMMAND only works with CONTROL: PLAYER** (with CONTROL: CPU the editor opened but took no inputs, so the gate refuses it; the CPU parts of the description below are historical).

## Triangle on COMMAND: edit the command of the OTHER side (tested)
Practice menu, cursor on COMMAND (CONTROL byte 0 = CPU or 1 = PLAYER; with PLAYER either pad works, the pressing side stays and the other is edited, CONTROL restored to its old value): Triangle (instead of Circle) opens the command editor for the side that is NOT the menu owner,
driven by the owner's own pad (no second controller). Reuses the vanilla "both human" editor path (CONTROL value 1) for the duration of the editor
(`patch_cmdedit`, caves `0x3B0000..0x3B05xx`, data `DATA+0xE0..0xE3` = REQ, ACTIVE, SWAPPED, saved human mask):
* gate at `0x338960` (`jal 0x3369A0`, confirm pressed): Triangle (`0x1000`) of the owner pad + cursor 12 + CONTROL 0 -> REQ, returns "pressed";
* hook1 at `0x338AD4` (read of `0x9CB240`): with REQ starts the session: human mask `0x9BDB10 |= 3` (saved), `0x9CB240 := 1` so the vanilla branch runs;
* stub2 at `0x338AE4`: during a session the edited side `0x9E9730` = owner ^ 1;
* the 5 pad pollers (`jal 0x1A21D0`) go through a wrapper that swaps the two 12-byte port blocks `0x9BEA20` / `0x9BEA2C` after the poll while ACTIVE (and
  swaps back before the next poll, so the edge detection stays consistent): the owner pad acts as the port of the edited side;
* the first poll with `0x9E95C0 != 9` ends the session (CONTROL := 0, human mask restored). Types of the characters are re-evaluated by GAME START as usual.

## 2P in the practice menu (tested)
2P can open, operate and leave the practice menu with any CONTROL setting (CPU 0 / PLAYER 1 / WATCH 2). Patches in `patch_cmdedit`:
* Start opens the menu: wrapper `CX_START` (`0x3B0600`, replaces `jal 0x154AB0` at `0x31F3C8`) ORs the human mask `0x9BDB10` with 3 during the call in practice mode;
* `0x3055A4` (`FUN_003054D0`, practice branch): the "no new button on the owner pad -> cancel the pause" check reads both pads (`a0 = 2`), otherwise every 2P Start was cancelled at once;
* `FUN_003383D0` (menu input): Start to resume (`0x338444`) and the GAME START confirm (`0x3388F8`, port mask 3) accept either pad; the navigation pad and port mask for CONTROL != 1
  (`0x33841C`, `0x338434`) and the two sub-screens (`0x339AD0`, `0x339C20`) too.
The command editor itself still follows the edited side (see "Triangle on COMMAND").

## GUARD: ALL (tested; animation look-ahead after 1.6.1, tested)
New value after S-SHIFT in the practice GUARD row (CONTROL CPU): the dummy blocks every attack whatever its height and switches its stance to match.
How the game decides block vs hit (found with PINE, see ps2-hacking-notes.md section 10): the dummy in guard pose has a guard hurtbox of type 0x1C (standing) / 0x1D (crouching),
copied to contact byte +0xC of the hit; `FUN_00180190` (called at `0x180674`) fails the guard when the attacker's `+0x280` has bit 0x80 (low, standing guard) or 0x40 (overhead,
crouching guard); those flags are only set in the frame the hitbox becomes active.  The action set follows the stance: stand light 39/41/40/42, crouch light 43/45/44/46,
stand heavy 47/49/48/50, crouch heavy 51/53/52/54 (pose / stun / recovery); switching the action inside the hit frame does not work (the game sets the old stun action again).
`patch_guardall`:
* **Pose before the hit** (the important part, the dummy must already be in the right stance when the hitbox appears):
  STAND dummy: `GA_AI` (`0x3B1600`, call at `0x140274` in `FUN_0013FAF0`, only runs while the AI expects an attack) turns the guard input from "back" into "down-back" when the
  look-ahead `GA_LA` finds a low.  CROUCH dummy: `GA_CR` (`0x3B1410`, `0x3B1800` up to 1.6.1; call at `0x337374` in `FUN_00337230`) holds "back" (stands up) when `GA_LA` finds an overhead, only while
  `FUN_00183570` ("attack incoming") is true, otherwise holding back just walks away.  When `GA_LA` finds no attack frame at all (projectiles), the learned table decides.
* **Look-ahead** `GA_LA` (`0x3B0C80`, added after 1.6.1): the low / overhead flags of `+0x280` are byte 4 of the animation frame record the attacker is in (the record is read by `FUN_0015F6D0`:
  12-byte header with duration, loop flags `byte 1 & 0xE0`, pose `byte 2` -> `+0x27E`, guard flags `byte 4` -> `+0x280`, box mask `byte 8` -> `+0x284`, sprite parts `byte 10`; then
  6 bytes per sprite part, a flag word, 6 bytes per box, sub-records whose sizes come from the handler tables `0x361D20` (per sprite part) / `0x361DA0` (two nibbles of the flag word),
  copied to `GA_LAT` `0x3B0F00`; then 4-byte lists while flag word bit 0x4000 / 0x8000).  Animation base = `[0x9BBD68 + 0x98 * byte[0x9BBCC0 + char id]]`, next record offset
  `+0x268`, loop start `+0x26C`.  `GA_LA` walks up to 24 records from the current one (following loops, stopping at a hold frame) and returns the height of the first record
  with a low / overhead flag or an attack box (box ids 0x20-0x60, 0x6E-0x7F in slots 0-3): 1 low, 2 overhead, 3 mid, 0 none.  Up to 1.6.1 the pose guesses "attacker crouched ->
  low" and "attacker airborne -> overhead" were used instead, which made the dummy duck for Kyo 2C and the 63214K follow-up and stand up for R.E.D. Kick (all mid).
  In guard stun (`+0x530 & 0x400`) a crouching dummy stands up when `GA_LA` finds an overhead (after 1.6.1, Vanessa 6A: mid, then overhead; before it stayed crouched), a standing dummy ducks when a low is incoming (this is what makes a chain like j.C -> 2B show the crouch block; an
  earlier version froze the stance in stun and the game then started the stand stun action when the second attack began, 7 frames before the contact).
* **Contact hook** `GA_RT` (`0x3B0900`, replaces the call at `0x180674`) is the fallback for what could not be predicted: if the stance does not match the attack (low flag with type 0x1C, overhead
  flag with type 0x1D) the contact type (`+0xC` and its copy `+0x52C`) is rewritten to the other stance and the original check runs (it then guards by itself), and the attack is
  recorded in the learned table `GA_TBL` (`0x3B1000`, 64 x 8 bytes: u16 char id `+0xEA`, u16 action `+0xEC`, u8 kind 1 low / 2 overhead, count `DATA+0xEA`, `GA_LK` lookup, `GA_ST` store; RAM only).
  With the look-ahead (after 1.6.1) the dummy knows ground overheads and lows from the first use; the table only matters for attacks without an attack frame in the attacker's own animation (projectiles).
* Menu: value 8 "ALL" is selectable (value lists / counts of ACTION 0, 1, 7, 8, 10, 11 +1, string table `GA_TAB`); the vanilla byte `0x9CB244` stays 1 while ALL is active, the ALL flag is
  `DATA+0xE8`, the displayed value is the mirror `DATA+0xE9` (synced in the poll wrapper, `POST` stub `0x3B0C00` after the menu cycles). Saves keep plain GUARD.
* Known: the AI also shows the guard pose on close whiffs (vanilla behaviour); live patches in the `0x337xxx` area do not take effect in PCSX2 (stale recompiler blocks), test those with a cold boot of a built ISO.

## GUARD: RANDOM / RANDOM ALL (tested)
GUARD values 9 RANDOM and 10 RANDOM ALL (flag `DATA+0xE8` = 2 / 3, mirror `DATA+0xE9`, vanilla byte stays 1). Per attack the dummy blocks with 50 %, otherwise it takes the hit.
RANDOM keeps the stance (like vanilla GUARD), RANDOM ALL also switches the height like ALL.
* **One stable decision per attack** (`GA_BLK`, `DATA+0xEB`): rolled in the poll wrapper (`CX_WRAP`, xorshift `GA_RNG`, no HI/LO use) when the attacker's attack bit (`+0x490` bit 0) falls (`GA_PREV` -> `GA_PEND`)
  and the dummy is idle (action 0 / 5, not in guard stun). Re-rolling per frame made the pose flicker (stand/crouch/back) and caused the "sometimes blocks standing" bug. `GA_RN` only returns `GA_BLK`.
* `GA_AI` for flag 2/3: BLK = 0 -> `s7 = 3` (no guard input); ACTION CROUCH mirrors the code `GA_CR` chose (`GA_CRCODE`: 8 back -> stand up, 7 down-back, else none), because the AI runs after
  `FUN_00337230` and used to override the crouch input with "back". For ACTION STAND the chosen code is kept for 6 ticks (`GA_STK`/`GA_STKT`) and re-injected by the wrapper `GA_SW`
  (`0x3B1B00`, replaces `jal 0x336fe0` at `0x13B97C`) while the dummy is not in guard stun.
* **Idle guard**: while the threat object is idle (no attack bit, action < 2) `GA_AI` sets `s7 = 3`. Before this, the re-roll to "block" while the attacker stood idle injected "back": the dummy walked back (action 2),
  and a second tap at the next attack was a backdash (action 35, double back tap). Projectiles are unaffected (their action is not < 2).
* **PIC trap**: keystone silently assembles `jal label` as `ld $t9, ($gp); jalr $t9`; the HUD cave called `drawline` that way and the game froze on the second combo hit. Now `bal drawline`
  and `assert_no_pic()` refuses any `jalr` / `ld ..($gp)` in all generated code.

## QUICK RESET (practice, SELECT BUTTON value 3 + KEY SETTING value 14)
Instant reset in practice mode. Entry points: the new SELECT BUTTON function QUICK RESET (the unused string slot 3 "COMMAND" of `0x3D2DD0 + val * 0x14`
is renamed; the value count bytes at `0x3D2F20` are +1 so value 3 is selectable, ACTION 11 keeps 2) via `j QR` at `0x33B41C` (dispatch of
`FUN_0033B1A0`), and the KEY SETTING button function 14 QUICK RESET (same pad hook as COMMAND ENEMY, `0x3AF000`). Both call the core `QRC` (`0x3AF540`,
a0 = pressing side); the held directions of that pad pick the variant: none = start (1P 608, 2P 928), Down+Left = 1P corner (32 / 99), Left = swapped
left corner (99 / 32), Right = 2P corner (1437 / 1504), Down+Right = swapped right corner (1504 / 1437), Y = 672 (table at `0x3AFB00`, 8 bytes per row:
x1P, x2P, facing bit of 1P).
What the core does (all verified by savestate diffs, see ps2-hacking-notes.md section 10):
* camera X (`0x9BDB20`) = clamp(midpoint - 0x140), then `FUN_0031F4C0` recomputes the screen bounds (otherwise they clamp the new positions);
* freeze controller reset `FUN_0017E850` + `0x9BB838/39`;
* per side: kill all projectile tasks (script task `team+0x100[i]` via `FUN_00164A20` first, then body task `team+0xC0[i]` via `FUN_001649D0`); combo
  counters; LIFE: RECOVERY refills HP / visible HP / stun / guard of all non-KO chars (0-LIFE leaves them);
* active char: full struct init `FUN_00189CD0`, position `FUN_00160FE0`, `FUN_00189AA0` (restoring the regen timer +0x4A6 which it sets to 300),
  facing, clear bit 0x20 of +0x3A4 (pushbox collision), +0x57D / +0x57E = 0, action 0 start `FUN_0016B440` (re-arms the hitbox validity mask +0x39F);
  char task fn = 0x141CF0, helper task (`team+0x6C+pt*4`) fn = 0x1860F0;
* gauges via `GA` (see below); a per-frame fixer `QT` (`0x3AF900`, called from the HUD wrapper) clears the freeze bit 27 of +0x494 for 10 frames and
  (the former 240-frame safety net, freeze record live but no helper in hit-stop mode 0x17FA60 -> controller reset + task fns restored, was removed: it fired during throws/knockdowns and made the victim stand up without a hit anim.)

## HIT BOX (practice, SELECT BUTTON value 4)
In-game collision box display. The drawer (380 words at `0x1141C0..0x1147B0`, over dead Sony stdio functions that nothing references), its SELECT stub, the box-kind
tables and the chain are by Vans (vans1belmont, [kofxi-international](https://github.com/vans1belmont/kofxi-international), CC BY-NC-SA 4.0), used with his permission;
`toolkit/hitbox_ps2.py` holds the words and the changes against his listing. Hooks: `jal 0x1A7D60` at `0x1A1A6C` -> `jal 0x1141C0` (draws after the frame, then continues),
the SELECT handler exit `0x33B41C` (the quick reset entry stub) continues at the select stub `0x114508` for values other than 3. The SELECT BUTTON value count bytes at
`0x3D2F20` are 5 for ACTION 0 and 4 for ACTION 1..10 (the last two entries keep 2), and the string slot 4 (formerly "COMMAND CLEAR") reads "HIT BOX". His immediates for the select value
(`0x11420C`, `0x114508`) are 4 here because value 3 is QUICK RESET.
Mad Gear changes on top (`make_combo_dmg_ps2.py`, `patch_hitbox`): colours follow the odabugs viewer (hurt 0,0,255; counter 127,127,255; guard 0,255,255; projectile hurt
255,128,0; attack red; throw magenta; collision green); draw order back to front (body, hurt, counter, guard, projectile, receiver, attack, throw; `HB_PASSES`); the collision
box is hidden whenever the game switches it off (`[+0x283] & 0x10`: rolls and other actions) through a trampoline at `0x3AF400`. Further caves: `0x3AF330`, `0x3AF360`,
`0x3AF440`, `0x3AFB40`. Flag `--no-hitbox` leaves it out. Mad Gear 1.6.1: the screen Y bias of his listing (`addiu ..., 0x708` at `0x114384` for the
boxes and `0x1143DC` for the pivot cross) is `0x6FE`, 10 px higher, which puts the pivot on the feet and matches odabugs' viewer (Screen Type A).

## Frame advantage display (practice, Mad Gear 1.6)
`toolkit/frameadv_ps2.py`, builder flag `frameadv=True`. After every contact (hit, block, throw, trade) both sides' first free frame is measured;
when both sides can act again, each side shows its own value under its own HP bar as an extra line of the DMG/STUN block: "+3" blue, "-3" red,
"+0" white. Air hits, knockdowns, techs, throws, Guard Cancel rolls and blowbacks are counted like any other contact. Free = first frame in which
the character is not busy (attack `+0x490 & 3`, hit stop `+0x494` bit 27, reaction `+0x494` bit 0, guard stun `+0x530 & 0x400`, airborne pose
`+0x27E == 2`, uninterruptible movement `+0x48C & BUSY_48C`); the values match the frame data of the community wiki. Code `fa_tick` at `0x3A8000`,
`fa_draw` at `0x3A8400`, state at `0x3A9800`, called from the HUD wrapper; frames are counted by an own counter, so pausing does not count. Practice
DISPLAY values: ALL (default) / DMG+STN / FRAMES / OFF; the OPTIONS DISPLAY setting of normal matches is unchanged.

## UKEMI (practice, Mad Gear 1.6)
`toolkit/ukemi_ps2.py`, builder flag `ukemi=True`. New practice row UKEMI under GUARD: OFF / BACK / FWD / RANDOM, independent of the GUARD setting
(the old GUARD value DOWN is gone; a saved DOWN becomes GUARD OFF + UKEMI BACK). Option byte `0x9CB24C`, saved at save+`0x294FF`. The dummy AI hook at
`0x33764C` calls `0x3B1E00`, which presses A+B every second frame in the tech window (16 frames before landing to 1 frame before; fixes the
vanilla bug that a fast juggle fall was often not teched). Forward tech: an entry filter at `0x16A220` (`0x3B2780`) replaces the direction of
every AI input call of that side in the same frame, so the guard AI cannot overwrite it; `jal 0x1726f0` at `0x184D84` -> `0x3B2700` clears it at
the end of the AI frame. The row shows "-----" and is locked when CONTROL is not CPU or for ACTION 7/8/11+.

## GAUGE option redesign (practice, byte 0x9CB246)
0 NORMAL, 1 SKILL, 2 MAX, 3 LEADER MAX, 4 MAX+SKILL (new; cycle count at `0x3387A8`, value strings in the cave table `GTAB 0x3AFC00`, draw patch
`0x33915C/164`). Vanilla forced the gauges every frame (`FUN_0018D010`); now only LEADER MAX does (the two forcing sites read a flag byte `DATA+0xD0`
maintained by `QT`). SKILL / MAX / MAX+SKILL set the gauge at the practice start (`FUN_0033A8D0` -> `GA`, a0 = 0) and at every quick reset (`GA`, a0 = 1:
zero first, so NORMAL resets to 0) and play normally afterwards. The 3/4/5 stock cap per alive member is the game's own per-frame clamp.

## Smaller practice fixes
* INPUT display vs. SKILL LIST (movelist): the input module keeps atlas set 7 (SPR03) resident; the movelist draws with whatever is resident. Stub `0x3AFE00`
  at the two `jal 0x3059E0` (`0x30561C`, `0x305644`) loads set 3 first when the tracker byte `0x1CB0C73` is 7.
* Practice menu: GAME EXIT cursor (the create call has `move t1,t0`, x target = y; patched to `0x1A0`), INPUT row objects are created right after the DISPLAY pair
  (stub `0x3AD800` at `0x3380D0`) so the row flies in with its neighbours.
* KEY SETTING words (ENEMY, QUICK, RESET): the atlas page with the vanilla value words exists twice, SPR02.GRC page 1 (practice menu) and SPR00.GRC page 4
  (button config in the options menu, outside practice mode; GAME OPTION texture slot 2). `practice_labels.py --command-enemy` writes the same rects into both
  (`ENEMY_TARGETS`): ENEMY (190,64,66,32), QUICK (192,352,64,32), RESET (192,384,64,32). Keep clear of the colon sprite rect (160,384,32,32).
  Until Mad Gear 1.5 only the SPR02 copy was patched, so the options screen showed an empty field.
