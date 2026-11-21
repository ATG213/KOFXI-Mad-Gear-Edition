# Arcade (Atomiswave) Mad Gear Edition: patcher and AW Multi setup

Build: `05-qr-v10-bilinear-off-dmg`, tested on the AW Multi (aje_fr) at the Mad Gear Dojo, 2026-11-21.

## Contents
- Unlock all bosses, same characters allowed on a team
- Quick Rematch (win screen: hold A + Start for an instant rematch, B + Start for team order select)
- Bilinear filter off
- Combo damage display under the HIT COMBO counter

**Known bug:** if the winner holds A or B while the loser presses Start, Quick Rematch is triggered as well.

## Patching
1. Get `KOFXI-MadGear-AW-Patcher-v1.0.exe`.
2. Choose **your own** original `ax3201p01.fmem1` (KOF XI MAME dump, CRC32 `6dbdd71b`, MD5 `36cde602c9bb8dc7b1e0749d663db8b9`).
3. The patcher writes a **new** `ax3201p01.fmem1` and verifies it. The checksum the Atomiswave cart needs (sum 0xD3) is already built in.

Result: CRC32 `6dbdd71b` (forged to match the original), SHA1 `23d2973cccb83fff3c35d10c183cb36d301825d7`, MD5 `72eff099fe810664408414936842309f`.

## AW Multi setup (per aje_fr)
1. Folder `kofxib/` on the stick: original `ax3201m01.mrom1` ... `ax3207m01.mrom7`, the patched `ax3201p01.fmem1`, plus `kofxib.bmp` and `kofxib.key`.
2. In `dc_atomiswave.cpp` at the stick root: copy the `ROM_START( kofxi )` block, rename it to `kofxib`, and use the SHA1 above for the fmem1 line.
3. Add at the end: `GAME( 2005, kofxib, awbios, aw2c, aw2c, atomiswave_state, init_atomiswave, ROT0, "Sammy / SNK Playmore", "The King of Fighters XI Mad Gear Edition", GAME_FLAGS )`
