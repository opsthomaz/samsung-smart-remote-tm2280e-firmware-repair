# NVDS Format — Atmosic ATM3 (Samsung TM2280E)

> Reverse-engineered documentation. No official public specification exists for this format.

---

## Overview

NVDS (Non-Volatile Data Storage) is the Atmosic ATM3 system for storing persistent configuration, calibration, and BLE bonding data in external SPI flash.

---

## Physical Layout

The TM2280E uses **four NVDS slots** — two per firmware bank, each serving as primary/secondary for redundancy:

| Offset | Size | Role | Status in dump |
|--------|------|------|----------------|
| `0x30000` | 60 KB | Bank A — primary | ✅ 187 bytes valid |
| `0x3F000` | 4 KB | Bank A — secondary | ❌ BLANK |
| `0x70000` | 60 KB | Bank B — primary | ✅ 4085 bytes valid |
| `0x7F000` | 4 KB | Bank B — secondary | ⚠️ 13 bytes |

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
+0x04    ...  TLV entries (see below)
```

### TLV Entry

```
[tag: 1 byte][length: 1 byte][value: length bytes]
```

The sequence ends at the first `0xFF` byte (unprogrammed flash).

### Example

```
4E 56 44 53          Magic: "NVDS"
02 06 12 53 6D 61 72 74    tag=0x02, len=6, value="\x12Smart"
20 43 6F 6E 74 72 6F 6C   tag=0x20, len=0x43... (config block)
...
FF                          End of NVDS
```

---

## Known Tags

| Tag | Name | Description |
|-----|------|-------------|
| `0x01` | BD_ADDRESS | Bluetooth device address (6 bytes, little-endian) |
| `0x02` | DEVICE_NAME | Device name fragment (first byte = total length) |
| `0x11` | TX_POWER | Transmit power in dBm (1 byte) |
| `0x12` | APPEARANCE | BLE appearance value (2 bytes LE) or data block |
| `0x18` | CONN_PARAMS | Preferred connection parameters (8 bytes) |
| `0x20` | CONFIG_BLOCK | Multi-field configuration block (see below) |
| `0x36` | ADV_INTERVAL | Advertising interval in 0.625ms units (2 bytes LE) |
| `0x39` | GAP_CONFIG | GAP configuration byte |
| `0x3A` | BD_ADDRESS_SUB | BD Address as sub-entry in config block |
| `0xB4` | CONN_TIMEOUT | Connection supervision timeout |
| `0xB5` | PERIPH_LATENCY | Peripheral latency config |
| `0xC1` | CAL_ENTRY | Single RF calibration value (2 bytes) |
| `0xC3` | CONFIG_BYTE | Single configuration byte |
| `0xC4` | CAL_BLOCK | RF calibration block (variable length) |
| `0xC0` | POWER_CONFIG | Power management configuration block |
| `0x43`, `0x44`, `0x52`, `0x6C`, `0x81` | KEY_BLOCK | BLE security key material (IRK, LTK, etc.) |
| `0xD7` | CRYPTO_BLOCK | Cryptographic data block |

---

## Config Block (tag `0x20`)

The config block is a nested TLV structure. The first 11 bytes are a continuation of the device name string, followed by sub-entries using the same tag/length format:

```
[11 bytes: device name continuation "ontrol 2016"]
[sub-tag: 1 byte][sub-len: 1 byte][sub-value: sub-len bytes]
...
[0x00 or 0xFF: end of sub-entries]
```

Sub-tags observed:
- `0x11`: TX Power
- `0x12`: Appearance
- `0x18`: Connection parameters
- `0x36`: Advertising interval
- `0x39`: GAP config
- `0x3A`: BD Address
- `0xB4`, `0xB5`: Connection config
- `0xC3`: Config byte
- `0xC4`: Calibration block

---

## RF Calibration Entries (tag `0xC1`)

The NVDS Bank B primary contains approximately **156 individual calibration entries**, each with tag `0xC1`, length `0x02`, followed by 2 bytes of calibration data.

These entries represent factory RF calibration values programmed during manufacturing. They should never be modified.

---

## Device Name Encoding

The device name is stored split across two tags:

1. **tag `0x02`, len `6`**: First byte = total name length (18 for "Smart Control 2016"), followed by first 5 characters "Smart"
2. **tag `0x20` config block**: Begins with "ontrol 2016" completing the name

Full internal name: **"Smart Control 2016"** (project codename, not the consumer-facing name)  
BLE advertised name: **"Samsung Smart Control 2022"** (set in firmware code, not NVDS)

---

## BD Address

Found in both Bank A and Bank B NVDS primary slots:

```
Tag 0x3A, len 6: 2E CC 1A 71 09 70
```

Displayed as: **`70:09:71:1A:CC:2E`** (reversed for standard display)

---

## Using the Decoder

```bash
# Decode all NVDS regions
python3 analysis/nvds_decoder.py firmware/controller_original.bin

# Decode only Bank B primary
python3 analysis/nvds_decoder.py firmware/controller_original.bin --region 0x70000

# Show calibration entries (verbose)
python3 analysis/nvds_decoder.py firmware/controller_original.bin --verbose
```
