# NVDS Format — Atmosic ATM3 (Samsung TM2280E)

> Reverse-engineered documentation. No official public specification exists for this format.

---

## Overview

NVDS (Non-Volatile Data Storage) is the Atmosic ATM3 system for storing persistent configuration, calibration, and BLE bonding data in external SPI flash.

Updates are **append-only**, as required by NOR flash semantics: when a value changes, the old entry's status byte is reprogrammed to mark it superseded, and a new entry is appended at the end of the chain.

---

## Physical Layout

The TM2280E uses **four NVDS slots** — two per firmware bank, each serving as primary/secondary for redundancy:

| Offset | Size | Role | Status in dump |
|--------|------|------|----------------|
| `0x30000` | 60 KB | Bank A — primary | ✅ 187 bytes, 18 entries |
| `0x3F000` | 4 KB | Bank A — secondary | ❌ BLANK |
| `0x70000` | 60 KB | Bank B — primary | ✅ 4,224 bytes, 346 entries (12 current, 334 superseded) |
| `0x7F000` | 4 KB | Bank B — secondary | ⚠️ 13 bytes (BD Address only) |

Note that Bank B primary data extends past the first 4 KB sector (entries end at `0x7108B`).

The firmware accesses NVDS at memory-mapped addresses:
- `0x10030000` → dump offset `0x30000`
- `0x1003F000` → dump offset `0x3F000`

(Note: `0x7F000` is NOT referenced by Bank B code — this region's purpose is unclear)

---

## Binary Format

### Header

```
Offset  Size  Content
+0x00    4    Magic: 0x4E 0x56 0x44 0x53 ("NVDS")
+0x04    ...  Entries (see below)
```

### Entry

Each entry has a **3-byte header**:

```
[tag: 1 byte][status: 1 byte][length: 1 byte][value: length bytes]
```

The chain ends at the first `0xFF` tag byte (unprogrammed flash).

### Status Byte

Observed values:

| Status | Meaning |
|--------|---------|
| `0x06` | Current (valid) entry |
| `0x02` | Superseded — a newer entry with the same tag was appended later |

The transition `0x06 → 0x02` clears one bit (`1 → 0`), a valid in-place NOR flash program — this is how an entry is invalidated without erasing the sector.

### Example (actual bytes from the dump, offset 0x30004)

```
4E 56 44 53                                  Magic: "NVDS"
02 06 12 "Smart Control 2016"                tag=0x02 (Device Name), status=0x06, len=18
11 06 01 04                                  tag=0x11, status=0x06, len=1
...
01 06 06 2E CC 1A 71 09 70                   tag=0x01 (BD Address), status=0x06, len=6
...
FF                                           End of chain (erased flash)
```

---

## Known Tags

Only a few tag meanings have been confirmed. Other tags observed in the dump (`0x11`, `0x12`, `0x18`, `0x2E`, `0x36`, `0x39`, `0x3A`, `0x3C`, `0x3E`, `0x90`, `0xA0`, `0xC0`, `0xC3`, `0xC4`, …) carry configuration, calibration, and BLE bonding data, but their exact semantics are unknown — they are listed by the decoder as `Unknown`.

| Tag | Name | Description |
|-----|------|-------------|
| `0x01` | BD_ADDRESS | Bluetooth device address (6 bytes, little-endian) |
| `0x02` | DEVICE_NAME | Device name, full string in one entry |
| `0xC1` | CAL_ENTRY | RF calibration value (2 bytes) |

---

## RF Calibration Entries (tag `0xC1`)

The NVDS Bank B primary contains **157 calibration entries** with tag `0xC1`: **1 current and 156 superseded** — a history of recalibrations appended over the device's lifetime, with only the latest entry valid.

These values are device-specific (programmed for this unit's crystal oscillator and antenna tolerances) and should never be copied to another device.

---

## Device Name

Stored as a single entry:

```
tag=0x02, status=0x06, len=0x12 (18), value="Smart Control 2016"
```

Internal name: **"Smart Control 2016"** (project codename, not the consumer-facing name)
BLE advertised name: **"Samsung Smart Control 2022"** (set in firmware code, not NVDS)

---

## BD Address

Found in Bank A primary, Bank B primary, and Bank B secondary:

```
tag=0x01, status=0x06, len=6, value: 2E CC 1A 71 09 70
```

Displayed as: **`70:09:71:1A:CC:2E`** (reversed for standard display)

---

## Using the Decoder

```bash
# Decode all NVDS regions
python3 analysis/nvds_decoder.py firmware/controller_original.bin

# Decode only Bank B primary
python3 analysis/nvds_decoder.py firmware/controller_original.bin --region 0x70000

# Show superseded and calibration entries too
python3 analysis/nvds_decoder.py firmware/controller_original.bin --verbose
```
