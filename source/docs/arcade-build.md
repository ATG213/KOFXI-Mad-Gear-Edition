# Arcade (Atomiswave) Mad Gear Edition: building the ROM and the patcher

The arcade edition changes one file: the program ROM `ax3201p01.fmem1` of KOF XI (MAME set `kofxi`, 8,388,608 bytes,
CRC32 `6dbdd71b`, MD5 `36cde602c9bb8dc7b1e0749d663db8b9`). The mask ROMs and everything else stay as they are. **No game data
is included in this repository**: you need your own original `ax3201p01.fmem1`.

## Hacks

| Hack | Script | Notes |
|---|---|---|
| Unlock all bosses (incl. Shion and Magaki) | `unlock_bosses.py` | 1 byte, independent of the save data |
| Same characters on a team | `samechars.py` | 1 byte, the duplicate check is skipped permanently |
| Quick rematch (loser: A + Start rematch, B + Start order select) | `quick_rematch.py` | 256 bytes, see [`arcade-quick-rematch.md`](arcade-quick-rematch.md) |
| Bilinear filter off | `bilinear_off.py` | 3 NOPs |
| Combo damage display under HIT COMBO | `combo_damage.py` + `dmg_wrapper.py` | see [`arcade-combo-damage.md`](arcade-combo-damage.md) |

Everything works on the **decrypted** program ROM. `aw_crypto.py` is a port of the public Atomiswave cipher from MAME
(key `0xD3` for KOF XI) and also a small command line tool: `python aw_crypto.py decrypt IN OUT`.

## Build the ROM

```
cd arcade/hacks
python build_arcade_rom.py ORIGINAL_ax3201p01.fmem1 NEW_ax3201p01.fmem1
```

The script checks the CRC32 of your original, decrypts it, applies the five hacks, encrypts again and fixes the cartridge
checksum for real hardware (`aw_checksum.py`). With all five hacks the result is byte-identical to the file of the released
arcade patcher v1.1 (MD5 `52fd5af6cc5cd416016c826175abdba9`, SHA1 `32aec5f702d3e3d587d81584b5c65f4a3001a379`); the script
prints whether that is the case. `--no-unlock`, `--no-samechars`, `--no-rematch`, `--no-bilinear` and `--no-combo` skip single
hacks. Only the Python standard library is needed (the optional disassembly in `dmg_wrapper.py` needs `capstone`).

## Why the checksum fix matters

Emulators accept any patched ROM; a real cartridge or the AW Multi does not. The cart sums the decrypted program bytes and
the 8-bit result has to be the cart key (`0xD3`), otherwise the mask ROMs stay locked and the screen stays black.
`aw_checksum.py` adds one compensation byte in zero padding (decrypted offset `0x122910`) and rewrites the last four bytes so
the CRC32 is the original one again (SHA-1 cannot be forged, so a `dc_atomiswave.cpp` entry that checks SHA-1 needs the new
value). `python aw_checksum.py check FILE` verifies a ROM.

## Build the patcher (delta exe)

The released patcher does not contain the ROM, only the 24 changed byte runs (about 1 KB):

```
cd arcade/patcher
python make_aw_patcher.py ORIGINAL_ax3201p01.fmem1 NEW_ax3201p01.fmem1       (writes payload.bin)
build_exe.bat                                                              (needs: pip install pyinstaller)
```

`aw_patcher.py` is the window the user sees: it asks for the user's own original file, verifies its MD5, applies the runs
and verifies the result. Its `payload.bin` from the command above is byte-identical to the one in the released v1.1 exe.

## AW Multi setup

How to put the patched file on the micro SD card of an AW Multi (separate `kofxib` game entry or replacing the original) is
described in [AW-MULTI.md](https://github.com/ATG213/KOFXI-Mad-Gear-Edition/blob/main/AW-MULTI.md).
