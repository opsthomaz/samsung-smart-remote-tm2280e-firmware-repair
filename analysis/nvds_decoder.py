#!/usr/bin/env python3
"""
NVDS TLV decoder for Atmosic ATM3 (Samsung TM2280E / SC22)

The NVDS (Non-Volatile Data Storage) uses a simple TLV format:
  [magic: 4 bytes "NVDS"][tag: 1 byte][len: 1 byte][data: len bytes]...
  Terminated by 0xFF.

Usage:
  python3 nvds_decoder.py controller_original.bin
"""

import sys
import struct
import argparse

NVDS_MAGIC = b'NVDS'

# Known NVDS regions in the TM2280E dump
NVDS_REGIONS = {
    0x30000: "Bank A — primary",
    0x3F000: "Bank A — secondary",
    0x70000: "Bank B — primary",
    0x7F000: "Bank B — secondary",
}

# Known tag descriptions (best-effort based on reverse engineering)
TAG_NAMES = {
    0x01: "BD Address",
    0x02: "Device Name (fragment)",
    0x10: "Unknown data block",
    0x11: "TX Power",
    0x12: "Appearance / data block",
    0x18: "Peripheral Preferred Conn Params",
    0x1B: "Crypto/key block",
    0x1E: "Crypto/key block",
    0x1F: "Crypto/key block",
    0x20: "Config block (multi-field)",
    0x21: "Crypto/key block",
    0x22: "Crypto/key block",
    0x24: "Crypto/key block",
    0x2D: "Crypto/key block",
    0x2E: "Crypto/key block",
    0x36: "Advertising interval",
    0x39: "GAP config byte",
    0x3A: "BD Address (sub-entry)",
    0x43: "Crypto/calibration block",
    0x44: "Crypto/calibration block",
    0x52: "Crypto/calibration block",
    0x6C: "Crypto/calibration block",
    0x75: "Unknown",
    0x81: "Crypto/calibration block",
    0x90: "Unknown",
    0xA0: "Unknown",
    0xAB: "Unknown",
    0xB4: "Connection config",
    0xB5: "Connection config",
    0xC0: "Power config block",
    0xC1: "RF calibration entry (single)",
    0xC3: "Config byte",
    0xC4: "RF calibration block",
    0xC8: "Unknown",
    0xCE: "Unknown",
    0xD7: "Crypto block",
    0xDD: "Unknown",
    0xE7: "Unknown",
}


def format_bd_address(data: bytes) -> str:
    """Format 6 bytes as BD Address (big-endian display)."""
    if len(data) != 6:
        return data.hex()
    return ':'.join(f'{b:02X}' for b in reversed(data))


def decode_config_block(payload: bytes) -> list:
    """Decode sub-entries inside a config block (tag 0x20)."""
    entries = []
    # First 11 bytes are continuation of device name: "ontrol 2016"
    try:
        name_part = payload[:11].decode('latin1').rstrip('\x00')
        entries.append(f"  device_name_cont: '{name_part}'")
    except Exception:
        pass

    i = 11
    while i < len(payload) - 1:
        stag = payload[i]
        if stag == 0xFF or stag == 0x00:
            break
        if i + 1 >= len(payload):
            break
        slen = payload[i + 1]
        sval = payload[i + 2:i + 2 + slen]

        if stag == 0x11 and slen == 1:
            entries.append(f"  tx_power: {sval[0]} dBm")
        elif stag == 0x12 and slen == 2:
            appearance = struct.unpack('<H', sval)[0]
            entries.append(f"  appearance: 0x{appearance:04X}")
        elif stag == 0x18 and slen >= 4:
            ci_min = struct.unpack('<H', sval[0:2])[0]
            ci_max = struct.unpack('<H', sval[2:4])[0]
            entries.append(f"  conn_interval_min: {ci_min} ({ci_min*1.25:.0f}ms)")
            entries.append(f"  conn_interval_max: {ci_max} ({ci_max*1.25:.0f}ms)")
        elif stag == 0x36 and slen == 2:
            interval = struct.unpack('<H', sval)[0]
            entries.append(f"  adv_interval: {interval} ({interval*0.625:.1f}ms)")
        elif stag == 0x39 and slen == 1:
            entries.append(f"  gap_config: 0x{sval[0]:02X}")
        elif stag == 0x3A and slen == 6:
            entries.append(f"  bd_address: {format_bd_address(sval)}")
        elif stag == 0xC3 and slen == 1:
            entries.append(f"  config_byte: 0x{sval[0]:02X}")
        elif stag == 0xC4:
            entries.append(f"  calibration_block: {sval[:4].hex()}... ({slen} bytes)")
        elif stag == 0xB5 and slen == 4:
            entries.append(f"  periph_latency_config: {sval.hex()}")
        elif stag == 0xB4 and slen == 4:
            entries.append(f"  conn_timeout: {sval.hex()}")
        else:
            preview = sval[:4].hex() + ('...' if slen > 4 else '')
            entries.append(f"  sub_0x{stag:02X}: {preview} ({slen} bytes)")

        i += 2 + slen

    return entries


def decode_nvds_region(data: bytes, offset: int, label: str, verbose: bool = False):
    """Decode a single NVDS region."""
    print(f"\n{'='*60}")
    print(f"NVDS Region: {label} @ 0x{offset:05X}")
    print(f"{'='*60}")

    magic = data[offset:offset + 4]
    if magic != NVDS_MAGIC:
        if all(b == 0xFF for b in data[offset:offset + 16]):
            print("  Status: BLANK (0xFF)")
        else:
            print(f"  Status: INVALID magic {magic.hex()}")
        return

    print(f"  Magic: {magic.decode()} ✓")

    pos = offset + 4
    end = offset + 0x1000  # max 4KB per region
    entry_count = 0
    cal_count = 0

    while pos < end:
        tag = data[pos]
        if tag == 0xFF:
            print(f"  [END @ 0x{pos:05X}]")
            break
        if pos + 1 >= end:
            break

        length = data[pos + 1]
        value = data[pos + 2:pos + 2 + length]
        entry_count += 1

        tag_name = TAG_NAMES.get(tag, "UNKNOWN")

        if tag == 0xC1:
            # Count calibration entries silently unless verbose
            cal_count += 1
            if verbose:
                print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} ({tag_name}): {value.hex()}")
        elif tag == 0x02 and length == 6:
            name_len = value[0]
            name_part = value[1:].decode('latin1', errors='replace')
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} Device Name: "
                  f"len={name_len}, '{name_part}...'")
        elif tag == 0x20:
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} Config block ({length} bytes):")
            for line in decode_config_block(value):
                print(f"    {line}")
        elif tag == 0x3A and length == 6:
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} BD Address: {format_bd_address(value)}")
        elif tag == 0x01 and length == 6:
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} BD Address: {format_bd_address(value)}")
        elif length <= 8:
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} ({tag_name}): {value.hex()}")
        else:
            preview = value[:8].hex() + '...'
            print(f"  #{entry_count:3d} [0x{pos:05X}] 0x{tag:02X} ({tag_name}): {preview} ({length} bytes)")

        pos += 2 + length

    if cal_count > 0:
        print(f"  [+ {cal_count} RF calibration entries (tag 0xC1) — use --verbose to show]")

    print(f"\n  Total entries: {entry_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Decode NVDS regions from Atmosic ATM3 firmware dump (Samsung TM2280E)"
    )
    parser.add_argument("firmware", help="Path to firmware binary (.bin)")
    parser.add_argument("--region", type=lambda x: int(x, 0),
                        help="Decode only one region at this offset (e.g. 0x30000)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show individual calibration entries (tag 0xC1)")
    args = parser.parse_args()

    with open(args.firmware, 'rb') as f:
        data = f.read()

    print(f"Firmware: {args.firmware}")
    print(f"Size: {len(data)} bytes ({len(data) // 1024} KB)")

    if args.region:
        label = NVDS_REGIONS.get(args.region, f"@ 0x{args.region:05X}")
        decode_nvds_region(data, args.region, label, args.verbose)
    else:
        for offset, label in NVDS_REGIONS.items():
            decode_nvds_region(data, offset, label, args.verbose)


if __name__ == "__main__":
    main()
