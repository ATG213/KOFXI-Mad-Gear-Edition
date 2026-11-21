# Arcade (Atomiswave) Mad Gear Edition: patcher and AW Multi setup

Build: `06-qr-v11-loser-only` (v1.1). The v1.0 base (build 05) was tested on the AW Multi (aje_fr) at the Mad Gear Dojo, 2026-11-21.

## Contents
- Unlock all bosses, same characters allowed on a team
- Quick Rematch (win screen: hold A + Start for an instant rematch, B + Start for team order select)
- Bilinear filter off
- Combo damage display under the HIT COMBO counter

## Patching
1. Get `KOFXI-MadGear-AW-Patcher-v1.1.exe`.
2. Choose **your own** original `ax3201p01.fmem1` (KOF XI MAME dump, CRC32 `6dbdd71b`, MD5 `36cde602c9bb8dc7b1e0749d663db8b9`).
3. The patcher writes a **new** `ax3201p01.fmem1` and verifies it. The checksum the Atomiswave cart needs (sum 0xD3) is already built in.

Result: CRC32 `6dbdd71b` (forged to match the original), SHA1 `32aec5f702d3e3d587d81584b5c65f4a3001a379`, MD5 `52fd5af6cc5cd416016c826175abdba9`.

## AW Multi setup (per aje_fr)
1. Folder `kofxib/` on the stick: original `ax3201m01.mrom1` ... `ax3207m01.mrom7`, the patched `ax3201p01.fmem1`, plus `kofxib.bmp` and `kofxib.key`.
2. In `dc_atomiswave.cpp` at the stick root: copy the `ROM_START( kofxi )` block, rename it to `kofxib`, and use the SHA1 above for the fmem1 line.
3. Add at the end: `GAME( 2005, kofxib, awbios, aw2c, aw2c, atomiswave_state, init_atomiswave, ROT0, "Sammy / SNK Playmore", "The King of Fighters XI Mad Gear Edition", GAME_FLAGS )`
