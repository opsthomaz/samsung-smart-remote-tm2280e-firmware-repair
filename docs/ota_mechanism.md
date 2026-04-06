# OTA Boot Flag Mechanism — Atmosic ATM3 (Samsung TM2280E)

> **Note:** This is reverse-engineered documentation. No official Atmosic SDK documentation for ATM3 OTA boot flags exists publicly. The ATM3 SDK (v4.1.x) predates the public OpenAir/Zephyr SDK and was never released.

---

## Overview

The Atmosic ATM3 uses a **dual-bank firmware system** for OTA updates. Two complete firmware images coexist in the 512KB external flash, and a ROM bootloader selects which to execute based on header flags.

---

## Flash Layout

```
0x00000 ─────────────────────────── Bank A (192 KB)
          firmware code + data
0x30000 ─────────────────────────── NVDS Bank A (64 KB total)
          primary slot: 0x30000 (60 KB)
          secondary slot: 0x3F000 (4 KB)
0x40000 ─────────────────────────── Bank B (192 KB)
          firmware code + data
0x70000 ─────────────────────────── NVDS Bank B (64 KB total)
          primary slot: 0x70000 (60 KB)
          secondary slot: 0x7F000 (4 KB)
0x80000 ─────────────────────────── end
```

---

## The USR Header

Each bank begins with a proprietary Atmosic boot header. The critical field is a **1-byte flag** at offset `+0x10`, immediately before the 3-byte `USR` signature:

```
Offset  Size  Content
+0x00   16    ARM Thumb trampolim (jump instructions)
+0x10    1    Flag byte  ← boot decision field
+0x11    3    "USR" signature (0x55 0x53 0x52)
+0x14    4    Stack/entry pointer 1
+0x20    4    Entry point 1
+0x24    4    Entry point 2
...
+0xB0    4    Init function pointer
```

---

## Flag Byte Progression

The flag byte uses NOR flash semantics: **bits start at 1 (erased) and are programmed to 0 one at a time**. Each bit represents a milestone in the OTA lifecycle.

```
Value   Binary      State               Meaning
─────────────────────────────────────────────────────────
0xFF    11111111    ERASED              No firmware present
0xFE    11111110    MK_PROGRAMMED       Image written to flash
0xFC    11111100    MK_VALID            CRC verification passed
0xF8    11111000    DOWNLOAD_OK         Download phase complete
0xF0    11110000    VERIFY_OK           Verify phase complete
0xE0    11100000    FINISH_OK           OTA finish acknowledged
0xC0    11000000    APP_STARTED         Application executing
0x80    10000000    APP_STABLE          Stable execution confirmed
0x08    00001000    NEARLY_CONFIRMED    All bits set except bit3
0x00    00000000    BOOT_CONFIRMED      Fully active bank
```

The gap between `0x80` and `0x08` (bits 6, 5, 4, 3 all set to 0 simultaneously) suggests these four bits may be programmed together as a group when the app signals stability, leaving only bit3 for the final confirmation step.

---

## Boot Selection Logic

The ROM bootloader (not accessible in the external flash dump — it resides in the ATM3 internal ROM) reads both bank headers and selects based on flag values:

- A bank with `BOOT_CONFIRMED` (`0x00`) is preferred
- A bank with `MK_PROGRAMMED` (`0xFE`) serves as factory fallback
- The bootloader likely executes the bank with more bits programmed when no confirmed bank exists (needs verification)

**In the TM2280E failure case:**
- Bank A: `0xFE` — factory firmware, minimal state
- Bank B: `0x08` — OTA completed but `BOOT_CONFIRMED` never written

The bootloader may execute Bank B (more bits set) but without `BOOT_CONFIRMED`, the system is in an indeterminate state where each reboot may restart OTA verification.

---

## NVDS and Boot Confirmation

The `BOOT_CONFIRMED` bit is written by the application code after a successful boot sequence, which includes NVDS validation. The relevant code path (from string analysis):

```
"OTA complete, image marked as good!"
"First boot after OTA!"
"!!Critical NVDS parameters generated - resetting!"
```

If NVDS validation fails (e.g., secondary slot erased), the app resets before writing `BOOT_CONFIRMED`, creating a boot loop where:

1. Bootloader executes Bank B (most flags set)
2. Bank B app starts, validates NVDS
3. NVDS secondary slot is missing → critical error → reset
4. `BOOT_CONFIRMED` never written
5. Repeat from step 1

This is the failure mode in the TM2280E dump.

---

## OTA State Machine (from string analysis)

The `otasc` (OTA State Controller) module manages the OTA lifecycle over BLE:

```
IDLE
  │
  ▼ WSRU_OTA_COMMAND_PREPARE_DOWNLOAD
PREPARE_DOWNLOAD
  │
  ▼ WSRU_OTA_COMMAND_DOWNLOAD
DOWNLOAD  ──→ "DL size = %lu" / "UPGD, write failed"
  │
  ▼ OTA_COMMAND_VERIFY
VERIFY  ──→ CRC check: "CRC OK sent" / "!!!CRC MISMATCH!!! Abort OTA!"
  │
  ▼ OTA_COMMAND_FINISH
FINISH  ──→ "OTA finsih" [sic]
  │
  ▼ Reboot
FIRST_BOOT  ──→ "First boot after OTA!" / "otasc: first boot detected!"
  │
  ▼ App validation (NVDS check etc.)
CONFIRMED  ──→ "OTA complete, image marked as good!"
```

The TM2280E failure occurred after FINISH/Reboot — the first boot after OTA could not complete validation.

---

## Relevant Strings Found in Firmware

From `upgrade_proc.c` (Bank A):
```
UPGD too many erase sectors
UPGD, write failed: 0x%x, d:0x%lx, boff:%d, len:%lu
UPGD, idx:%d addr:0x%lx + sectors: %lu erase failed
UPGD, part. is not first boot! (0x%x)
```

From `otasc.c` (Bank B rodata, 0x5A000):
```
otasc: first boot detected!
First boot timer expired, resetting..
OTA Done!
!!!CRC MISMATCH!!! Abort OTA!
Disconnect during OTA!
```

From boot decision code (0x16700 region):
```
Enabling first boot
System RESET
Other upgrade status: %#lx
Other seq: %#lx, our seq: %#lx
BOOT GOOD value: 0x%lx
MK-BAD: %#lx
MK-PROGRAMMED: %#lx
```

---

## Fix Applied

To resolve the interrupted OTA state:

1. **Program bit3 of Bank B flag**: `0x08` → `0x00` at offset `0x40010`
   - Valid NOR flash operation (programming a bit from 1 to 0)
   - Tells bootloader Bank B is fully confirmed

2. **Restore NVDS Bank A secondary slot**: copy NVDS from `0x30000` to `0x3F000`
   - Provides the missing redundant NVDS copy
   - Prevents NVDS validation failure on future boots

See `firmware/controller_fixed5.bin` for the patched image.
