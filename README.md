# KOFXI Mad Gear Edition

Arcade & PS2 hacks for **The King of Fighters XI** for a better practice mode and tournament play.

| Hack | Platform | Status |
|---|---|---|
| [PS2 Mad Gear Edition](#ps2-mad-gear-edition) | PS2 (Japanese disc, SLPS-25660) | Released |
| [Arcade Mad Gear Edition](#arcade-mad-gear-edition-atomiswave) | Atomiswave (AW Multi) | Released |

> No game data is distributed here. The patches contain only the bytes that were changed. You need your own
> dump of the original game.

---

## PS2 Mad Gear Edition

A modified version of the Japanese PS2 release with arcade-style tools and quality-of-life features.

### Features

**Better Practice mode**
- **COUNTER: ON** option bugfixed, now correctly grants +8F air hit stun, like in the actual game
- **Display** (all / dmg+stn / frames / off): damage and stun numbers and the frame advantage under the health bars, plus an "N HITS" line when the input display is on
- **Frame advantage**: after every hit, block, throw or trade each side shows its own advantage (blue +, red -, white +0), knockdowns, techs, guard cancels and air hits included
- **Ukemi** (off / back / fwd / random): the dummy techs knockdowns, independent of the guard setting
- **Input** (1P / 2P / both): shows input history (the original hit counter is hidden on that side)
- **Hit Box**: SELECT BUTTON function that shows the hitboxes
- **Quick Reset**: instant reset to start or corner positions (use SELECT BUTTON or bind it via KEY SETTING); hold left / down-left / down / down-right / right for the different positions
- **Command Enemy**: plays back the other player's recorded "command" input; Triangle on COMMAND edits the command of the other player
- **Guard options**: added GUARD ALL, RANDOM and RANDOM ALL (DOWN moved to the new UKEMI row)
- **Gauge options**: "max+skill" added which can be drained
- **Automatic HP/Stun Refill:** Now faster, happens after 1 second (not while dizzy)
- When 1P opened practice mode, 2P can now use the practice menu by pressing Start, and vice versa

**Game improvements**
- **Quick Rematch** in Arcade Versus: during the win screen, hold Square to rematch, hold X for team order select
- **Yuri's** differences from the arcade version are fixed
- **Unlock everything** (all bosses, console characters and challenges) by default
- **Combo / stun damage display**, can be adjusted in the graphics options
- **Same characters** allowed on a team (with correct palettes)
- Start-up logos skipped

**Look**
- Mad Gear start-up logo, title logo and attract-mode logo
- Recolored menus

### How to use

1. Get the file `KOFXI-MadGear-Patcher-v1.6.1.exe` from the [Releases](../../releases) page.
2. Start it, choose **your own** dump of the Japanese disc image (`.iso`, SLPS-25660) and an output name.
3. The patcher checks your image, writes a **new** ISO (your original is never changed) and verifies the result.
4. Play the new ISO in PCSX2 or from a USB/HDD loader.

Prefer a patch file? Use `KOFXI-MadGear-Edition-v1.6.1.ppf` with a PPF patcher of your choice.

**Required source image:** Japanese disc, plain 2048-byte-sector `.iso`, size 2,540,208,128 bytes,
MD5 `2bb2d183e85964a799f3eb73b5812a71`. The patcher refuses any other file.

### Notes

- Tested in PCSX2 2.8.2 and on a real PS2 (OPL).
- Use a save from a clean card or backup your save; the unlock hack writes the unlocked state when you save.
- Please report bugs in the Issues tab, with the game mode and the steps to reproduce.

## Arcade Mad Gear Edition (Atomiswave)

A modified version of the Atomiswave arcade ROM of KOF XI, tested on a real AW Multi.

### Features

- **Quick Rematch** on the win screen: hold A + Start for an instant rematch, B + Start for team order select
- **Unlock everything**: all bosses available by default, including Shion & Magaki
- **Combo damage display** under the HIT COMBO counter
- **Bilinear filter off** (sharp pixels)
- **Same characters** allowed on a team (use at own discretion)

### How to use

1. Get `KOFXI-MadGear-AW-Patcher-v1.1.exe` from the [Releases](../../releases) page.
2. Start it, choose **your own** original `ax3201p01.fmem1` (KOF XI MAME dump, CRC32 `6dbdd71b`) and an output name.
3. The patcher checks your file, writes a **new** `ax3201p01.fmem1` and verifies the result. Your original is never changed.
4. AW Multi setup (`kofxib` entry in `dc_atomiswave.cpp`): see [AW-MULTI.md](AW-MULTI.md).

## Source code

The tools that build the PS2 and the Atomiswave Mad Gear Edition (toolkit, hack builders, patchers, documentation) are in [`source/`](source/), under the same license (CC BY-NC-SA 4.0). The PS2 toolkit there can also recolor the 12 colors of every character (preview of the character and its effects, export / import as GIMP, Aseprite or Photoshop palette): see [Character palettes](source/README.md#character-palettes).

## Credits

- **ATG** ([@ATG213](https://twitter.com/ATG213)): PS2 hacks, reverse engineering, graphics, patcher, testing
- **Tortita** ([ez2torta](https://github.com/ez2torta)): KOF XI Atomiswave reverse engineering and research that this work builds on
- **Vans** ([vans1belmont](https://github.com/vans1belmont/kofxi-international)): HIT BOX drawer for the PS2 version, used with his permission (CC BY-NC-SA 4.0)
- **[@odabugs](https://x.com/odabugs)** ([GitHub](https://github.com/odabugs)): hitbox viewer script; the HIT BOX colors and draw order follow his viewer
- Tools: PCSX2, Ghidra (emotionengine-reloaded), Claude (Anthropic AI assistant: used for reverse engineering help, patch code and the patcher tools; everything is tested by ATG in the emulator and on real hardware)
- Thanks to the KOF XI community

## Contact

- YouTube / streams: [youtube.com/atthegates](https://www.youtube.com/atthegates)
- Mad Gear streams: [youtube.com/@madgearffm7547](https://www.youtube.com/@madgearffm7547/streams)
- Twitter/X: [@ATG213](https://twitter.com/ATG213)

## Disclaimer

Unofficial fan project, not affiliated with SNK. You need a legally obtained copy of the game.

## License

The patchers, source code and documentation in this repository are released under [CC BY-NC-SA 4.0](LICENSE) (Creative Commons Attribution-NonCommercial-ShareAlike 4.0): free for any noncommercial use, sharing and modification with credit to ATG. Changed versions must use the same license; commercial use is not permitted. This applies to the mod only, not to the game or its assets.
