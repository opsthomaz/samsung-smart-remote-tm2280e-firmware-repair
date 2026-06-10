# Repair Procedure — Samsung Smart Control TM2280E

## Prerequisites

### Hardware
- CH341A SPI flash programmer
- **1.8V level-shifter adapter for CH341A** ← MANDATORY
- Soldering iron with fine tip (or hot air station)
- Flux, solder wick
- Tweezers

### Software
- AsProgrammer or NeoProgrammer (Windows)
- Alternatively: `flashrom` (Linux/macOS)

### Files
- `analysis/patch_your_firmware.py` — patches **your own dump** (Python 3.8+, no dependencies)

> ⚠️ **Do NOT flash `firmware/controller_fixed5.bin` from this repo.** It contains the researcher's BD Address (Bluetooth MAC) and RF calibration data. Flashing it clones another device's Bluetooth identity and overwrites your factory calibration. It is included for analysis and comparison only.

---

## ⚠️ Critical Voltage Warning

The **Winbond W25Q40EW** is a **1.8V chip**. The "EW" suffix explicitly denotes the 1.65V–1.95V operating range.

The CH341A default configuration outputs **3.3V on SPI data lines** (CLK, MOSI, MISO, CS). Applying 3.3V to a 1.8V chip exceeds its absolute maximum ratings and may:
- Cause silent write errors (data appears written but is corrupted)
- Permanently damage the chip over repeated operations
- Result in the remote being completely unresponsive after flashing

**You must use a 1.8V adapter.** Search for "CH341A 1.8V adapter" on AliExpress, Amazon, or eBay. They cost approximately $2–5 USD.

---

## Step 1 — Disassemble the Remote

1. Remove the batteries/solar panel cover (back of remote)
2. Use a plastic spudger to carefully pry open the remote housing — there are clips along the edges, no screws
3. The PCB is held by clips; carefully lift it out

---

## Step 2 — Locate the Flash Chip

The W25Q40EW is an 8-pin SOIC package located on the PCB. Look for the Winbond marking `25Q40EW` or `W25Q40EW`. It will have a dot marking pin 1.

---

## Step 3 — Remove the Flash Chip

Two options:

**Option A (preferred) — Desolder:**
- Apply flux generously
- Use hot air at ~320°C or a fine soldering iron with solder wick
- Lift the chip carefully with tweezers
- Clean pads with IPA and solder wick

**Option B — SOIC clip (in-circuit):**
- Clip directly onto the chip without desoldering
- Works for reading but less reliable for writing
- Risk of interference from the ATM3 SoC sharing the SPI bus

---

## Step 4 — Read the Original Firmware (Backup)

Before writing anything:

1. Mount the chip in the CH341A socket (with 1.8V adapter installed)
2. Open AsProgrammer → Select chip type: **W25Q40EW**
3. Read the chip → Save as `backup_YYYYMMDD.bin`
4. **Read it twice and compare** — both reads must be identical (any difference means an unstable connection or voltage problem)

Your dump's SHA256 will **not** match the reference dump in this repo — your remote has its own BD Address and calibration data. That is expected. What matters is that the dump is 524,288 bytes and passes the structure checks below.

Confirm your remote has the same failure state before patching:

```bash
python3 analysis/boot_flag_analysis.py backup_YYYYMMDD.bin
```

You should see Bank B in state `NEARLY_CONFIRMED` (flag `0x08`). If your flags differ, open an issue with the output instead of blindly flashing.

---

## Step 5 — Patch Your Dump and Write It

1. Patch **your own backup** (preserves your BD Address and calibration):

   ```bash
   python3 analysis/patch_your_firmware.py backup_YYYYMMDD.bin
   # → writes backup_YYYYMMDD_fixed.bin and prints a report
   ```

2. Check the report: it should list 2 changes, confirm your BD Address was found, and confirm your RF calibration entries are preserved
3. Open `backup_YYYYMMDD_fixed.bin` in AsProgrammer
4. Select chip: **W25Q40EW** at **1.8V**
5. Erase → Program → Verify
6. The verify step must pass completely — any verify failure means the write did not work (likely voltage issue)

### Using flashrom (Linux/macOS)

```bash
# Read original (backup) — twice, then compare
flashrom -p ch341a_spi -r backup_YYYYMMDD.bin
flashrom -p ch341a_spi -r backup_check.bin
cmp backup_YYYYMMDD.bin backup_check.bin

# Patch your own dump
python3 analysis/patch_your_firmware.py backup_YYYYMMDD.bin

# Write the patched dump
flashrom -p ch341a_spi -w backup_YYYYMMDD_fixed.bin

# Verify
flashrom -p ch341a_spi -v backup_YYYYMMDD_fixed.bin
```

Note: flashrom may need `--chip W25Q40EW` specified explicitly.

---

## Step 6 — Resolder the Chip

1. Apply fresh solder to the PCB pads if needed
2. Align the chip (check pin 1 orientation — the dot on the chip)
3. Solder carefully, checking for bridges
4. Clean with IPA

---

## Step 7 — Charge the Capacitor

The TM2280E has **no battery** — only a capacitor for energy storage. After reassembly, the capacitor may be depleted.

**Before testing:**
- Place the remote face-up near a bright light source (window, lamp) for 30+ minutes, OR
- Place it within 2 meters of a 2.4 GHz WiFi router for 30+ minutes

The remote will not respond if the capacitor is insufficiently charged.

---

## Step 8 — Pair with the TV

1. Turn on the TV
2. Hold the remote close to the TV (within 50 cm)
3. Press and hold **Return (↩) + Play/Pause (⏯)** simultaneously for 3–5 seconds
4. The LED should blink and the TV should display a pairing notification
5. Confirm on the TV

If pairing does not work after 3 attempts:
- Ensure the TV's Bluetooth is on: **Settings → General → External Device Manager → Bluetooth Device List**
- Delete any existing "Samsung Smart Control" entries from the TV's Bluetooth list and retry

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|-------------|--------|
| LED does not light at all | Capacitor depleted | Charge for 60+ min |
| LED blinks rapidly and stops | OTA loop still active | Re-verify flash write, check voltage adapter |
| LED blinks slow but no TV response | BLE pairing issue | Force re-pair (Return + Play/Pause) |
| TV shows "Device not supported" | Wrong remote model for this TV | Verify TV model compatibility |
| Verify step fails in programmer | Voltage issue (3.3V on 1.8V chip) | Check 1.8V adapter, replace chip if damaged |

---

## What the Fix Does

The patch makes 2 changes (188 bytes on the reference dump; the NVDS copy size depends on your dump's contents):

1. **`0x40010`: `0x08` → `0x00`** — Programs the final `BOOT_CONFIRMED` bit in Bank B's header. This tells the bootloader that Bank B is the fully confirmed active firmware, ending the ambiguous OTA state.

2. **`0x3F000–0x3F0BA`** (187 bytes on the reference dump) — Restores the Bank A NVDS secondary slot from the primary slot data. This provides the redundant NVDS copy that was missing, preventing NVDS validation failures on future boots.

No firmware code is modified. No calibration data is touched. The BD Address is preserved.
