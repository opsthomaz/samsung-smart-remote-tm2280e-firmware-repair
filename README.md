# Samsung Smart Control TM2280E — Firmware Reverse Engineering

> **Complete reverse engineering and repair analysis of the Samsung Smart Control 2022 (TM2280E / SC22) firmware extracted from a Winbond W25Q40EW SPI flash chip.**
>
> This repository documents the first known public analysis of the Atmosic ATM3 dual-bank boot system as used in Samsung's 2022 Eco Remote. No prior public documentation exists for this firmware architecture.

---

## ⚠️ CRITICAL WARNING — READ BEFORE FLASHING ANYTHING

**DO NOT flash `controller_fixed5.bin` from this repo onto your remote.**

That file contains data uniquely tied to the researcher's specific hardware unit:

1. **BD Address (Bluetooth MAC):** `70:09:71:1A:CC:2E` — flashing this clones the researcher's Bluetooth identity onto your device, causing pairing conflicts if both remotes exist on the same network.

2. **RF Calibration (~156 entries, tag `0xC1`):** These values were measured and programmed at the factory specifically for the physical tolerances of the researcher's crystal oscillator and antenna. Overwriting them with someone else's calibration can severely degrade Bluetooth range or cause random disconnections.

**The correct approach:** Use `analysis/patch_your_firmware.py` to apply the two-byte fix to **your own dump**, preserving your unique BD Address and RF calibration.

```bash
# Read your own flash first (with 1.8V adapter!)
# Then patch your own dump:
python3 analysis/patch_your_firmware.py your_backup.bin
```

The `controller_fixed5.bin` and `controller_original.bin` files are provided for **educational analysis and comparison only**.

---

## Device

| Field | Value |
|---|---|
| **Product** | Samsung Smart Control 2022 |
| **Model code** | TM2280E (`TM2280E_HARV`) |
| **Internal name** | Samsung SC22 |
| **Compatible TVs** | QN85BA, QN90B, QN95B and similar 2022 QLED/Neo QLED |
| **SoC** | Atmosic ATM3 (ARM Cortex-M0, 16 MHz) |
| **External flash** | Winbond W25Q40EW — 4 Mbit (512 KB), **1.8V** |
| **Energy** | Solar panel + RF energy harvesting (2.4 GHz) — no battery, capacitor only |
| **BLE** | Bluetooth 5.0, ATVV (Android TV Voice), HID over GATT |
| **IR** | Samsung IR protocol, TV power on/off |

---

## Problem Statement

The remote stopped synchronizing with the TV after a failed OTA firmware update. LED, buttons, and IR all functioned normally. Factory reset (Back + Play/Pause) had no effect. No prior public documentation existed on the firmware structure or repair procedure.

---

## Firmware Files

| File | SHA256 | Notes |
|------|--------|-------|
| `firmware/controller_original.bin` | `433eb1e8...` | Raw dump — researcher's hardware only |
| `firmware/controller_fixed5.bin` | `12b4dfdf...` | Patched dump — researcher's hardware only |

**For your own repair, use `patch_your_firmware.py` on your own dump.**

---

## Flash Layout

```
Offset      Size    Region                       Contents
─────────────────────────────────────────────────────────────────────
0x00000  192 KB    Bank A — firmware code        App v0.0.0.9 / SDK 4.1.0
0x30000   60 KB    NVDS Bank A — primary         187 bytes valid (BD Address, config)
0x3F000    4 KB    NVDS Bank A — secondary       ❌ BLANK — erased
0x40000  192 KB    Bank B — firmware code        App v0.2.0.0 / SDK 4.1.1
0x70000   60 KB    NVDS Bank B — primary         4085 bytes valid (full calibration)
0x7F000    4 KB    NVDS Bank B — secondary       ⚠️  Nearly erased (13 bytes)
```

---

## Root Cause Analysis

### 1. Interrupted OTA Update

The ATM3 uses a **dual-bank system** with a proprietary boot header (Atmosic `USR` format). Each bank has a 1-byte flag field at header offset `+0x10`, where bits are progressively programmed (NOR flash: `1→0`) through the OTA lifecycle:

```
0xFF  →  0xFE  →  0xFC  →  0xF8  →  0xF0  →  0xE0  →  0xC0  →  0x80  →  0x08  →  0x00
        PROG    VALID   DL_OK   VRF_OK  FIN_OK  STARTED STABLE  ← here   CONFIRMED
```

**Bank A flag: `0xFE`** — only `MK_PROGRAMMED` set. Factory/fallback state.  
**Bank B flag: `0x08`** — all OTA steps complete **except bit 3 (BOOT_CONFIRMED)**. The app never confirmed the boot.

### 2. Erased NVDS Secondary Slot

The firmware references NVDS at:
- `0x10030000` → `0x30000` (primary) — present but sparse
- `0x1003F000` → `0x3F000` (secondary) — **completely erased**

With the secondary slot erased, NVDS validation failed during first boot after OTA, preventing `BOOT_CONFIRMED` from ever being written — creating a permanent unconfirmed-OTA loop.

---

## The Fix (2 changes, 188 bytes total)

| Offset | Change | Reason |
|--------|--------|--------|
| `0x40010` | `0x08` → `0x00` | Bank B: program bit 3 → `BOOT_CONFIRMED` |
| `0x3F000–0x3F0BB` | `0xFF...` → NVDS data | Restore Bank A NVDS secondary from primary |

**Apply to your own dump:**
```bash
python3 analysis/patch_your_firmware.py your_backup.bin
# Creates: your_backup_fixed.bin
```

---

## Repository Structure

```
samsung-smart-remote-tm2280e-firmware-repair/
├── README.md
├── LICENSE-MIT                      ← Python scripts
├── LICENSE-CC-BY-NC-4.0             ← Documentation
├── .gitignore
├── firmware/
│   ├── controller_original.bin      ← Researcher's dump (reference only)
│   └── controller_fixed5.bin        ← Researcher's patched firmware (reference only)
├── analysis/
│   ├── patch_your_firmware.py       ← ✅ USE THIS to fix your own dump
│   ├── nvds_decoder.py              ← NVDS TLV decoder
│   ├── flash_layout.py              ← Flash region mapper and auditor
│   └── boot_flag_analysis.py        ← Boot decision flag analysis
├── docs/
│   ├── repair_procedure.md          ← Step-by-step repair guide
│   ├── ota_mechanism.md             ← OTA boot flag system documentation
│   └── nvds_format.md               ← NVDS structure documentation
└── hardware/
    └── ch341a_1v8_note.md           ← Critical: W25Q40EW is 1.8V
```

---

## Quick Start

```bash
git clone https://github.com/opsthomaz/samsung-smart-remote-tm2280e-firmware-repair
cd samsung-smart-remote-tm2280e-firmware-repair

# Analyze a dump (any TM2280E firmware)
python3 analysis/flash_layout.py your_backup.bin
python3 analysis/boot_flag_analysis.py your_backup.bin
python3 analysis/nvds_decoder.py your_backup.bin

# Fix your own dump
python3 analysis/patch_your_firmware.py your_backup.bin
# → writes your_backup_fixed.bin
```

---

## Tools Required

| Tool | Purpose | Note |
|------|---------|------|
| CH341A programmer | SPI flash read/write | |
| **1.8V level-shifter adapter** | Voltage compatibility | **Mandatory** — chip is 1.8V |
| AsProgrammer / NeoProgrammer | Flash software (Windows) | |
| `flashrom` | Flash software (Linux/macOS) | |
| Python 3.8+ | Analysis scripts | No external dependencies |

---

## Findings

| Finding | Status |
|---------|--------|
| Atmosic ATM3 dual-bank boot flag system documented | ✅ First public documentation |
| NVDS TLV format decoded | ✅ |
| Root cause of sync failure identified | ✅ Interrupted OTA + erased NVDS secondary |
| Automated patch script (preserves user's unique data) | ✅ |
| W25Q40EW 1.8V voltage warning | ✅ Critical |
| Public prior art | ❌ None found |

---

## License

- **Python scripts** (`analysis/*.py`): [MIT License](LICENSE-MIT)
- **Documentation** (`*.md`, `docs/`, `hardware/`): [CC BY-NC 4.0](LICENSE-CC-BY-NC-4.0)
- **Firmware binaries**: Provided for educational/repair reference only

---

## Disclaimer

This research was conducted for educational and repair purposes on hardware owned by the researcher. All trademarks belong to their respective owners (Samsung Electronics, Atmosic Technologies, Winbond Electronics).

---

## Contributing

If you have tested this fix on a TM2280E (or similar Atmosic ATM3-based Samsung remote), please open an issue with your results — board revision, firmware versions found, and whether the fix worked. Reports from different hardware revisions are especially valuable.
