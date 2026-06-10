#!/usr/bin/env python3
"""
NVDS decoder for Atmosic ATM3 (Samsung TM2280E / SC22)

The NVDS (Non-Volatile Data Storage) uses a tag/status/length format:

  [magic: 4 bytes "NVDS"]
  [tag: 1 byte][status: 1 byte][length: 1 byte][value: length bytes]...

The entry chain ends at the first 0xFF tag byte (erased flash).

Status byte (observed values):
  0x06 = current (valid) entry
  0x02 = superseded entry — a newer copy of the same tag was appended
         later (NVDS updates are append-only in NOR flash)

Usage:
  python3 nvds_decoder.py controller_original.bin
  python3 nvds_decoder.py controller_original.bin --region 0x70000
  python3 nvds_decoder.py controller_original.bin --verbose
"""

import sys
import argparse

# Windows consoles often default to a legacy code page (cp1252) that
# cannot encode the checkmarks printed below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NVDS_MAGIC = b'NVDS'
STATUS_CURRENT = 0x06
STATUS_SUPERSEDED = 0x02

# Known NVDS slots in the TM2280E dump: (label, slot size)
NVDS_REGIONS = {
    0x30000: ("Bank A — primary", 0xF000),
    0x3F000: ("Bank A — secondary", 0x1000),
    0x70000: ("Bank B — primary", 0xF000),
    0x7F000: ("Bank B — secondary", 0x1000),
}

# Tag meanings confirmed by reverse engineering. Tags not listed here
# have unknown semantics — do not guess.
TAG_NAMES = {
    0x01: "BD Address",
    0x02: "Device Name",
    0xC1: "RF calibration entry",
}

STATUS_NAMES = {
    STATUS_CURRENT: "current",
    STATUS_SUPERSEDED: "superseded",
}


def format_bd_address(data: bytes) -> str:
    """Format 6 bytes as BD Address (stored little-endian, displayed reversed)."""
    if len(data) != 6:
        return data.hex()
    return ':'.join(f'{b:02X}' for b in reversed(data))


def iter_nvds_entries(data: bytes, offset: int, size: int):
    """Yield (pos, tag, status, length, value) for each NVDS entry."""
    pos = offset + 4
    end = offset + size
    while pos + 3 <= end:
        tag = data[pos]
        if tag == 0xFF:
            return
        status = data[pos + 1]
        length = data[pos + 2]
        if pos + 3 + length > end:
            return
        yield pos, tag, status, length, data[pos + 3:pos + 3 + length]
        pos += 3 + length


def describe_value(tag: int, value: bytes) -> str:
    if tag == 0x01 and len(value) == 6:
        return format_bd_address(value)
    if tag == 0x02:
        return repr(value.decode('latin1', errors='replace'))
    if len(value) <= 8:
        return value.hex()
    return f"{value[:8].hex()}... ({len(value)} bytes)"


def decode_nvds_region(data: bytes, offset: int, label: str, size: int,
                       verbose: bool = False):
    """Decode a single NVDS slot."""
    print(f"\n{'=' * 60}")
    print(f"NVDS Region: {label} @ 0x{offset:05X}")
    print(f"{'=' * 60}")

    magic = data[offset:offset + 4]
    if magic != NVDS_MAGIC:
        if all(b == 0xFF for b in data[offset:offset + 16]):
            print("  Status: BLANK (0xFF)")
        else:
            print(f"  Status: INVALID magic {magic.hex()}")
        return

    print(f"  Magic: {magic.decode()} ✓")

    total = current = superseded = 0
    cal_current = cal_superseded = 0
    hidden = 0
    end_pos = offset + 4

    for pos, tag, status, length, value in iter_nvds_entries(data, offset, size):
        total += 1
        end_pos = pos + 3 + length
        is_current = status == STATUS_CURRENT
        if is_current:
            current += 1
        else:
            superseded += 1

        if tag == 0xC1:
            if is_current:
                cal_current += 1
            else:
                cal_superseded += 1
            if not verbose:
                hidden += 1
                continue
        elif not is_current and not verbose:
            hidden += 1
            continue

        tag_name = TAG_NAMES.get(tag, "Unknown")
        status_name = STATUS_NAMES.get(status, f"status 0x{status:02X}")
        print(f"  #{total:3d} [0x{pos:05X}] tag 0x{tag:02X} ({tag_name}, "
              f"{status_name}): {describe_value(tag, value)}")

    print(f"  [entries end @ 0x{end_pos:05X}]")
    if hidden:
        print(f"  [+ {hidden} entries hidden (superseded / RF calibration) — "
              f"use --verbose to show]")
    if cal_current or cal_superseded:
        print(f"  RF calibration (tag 0xC1): {cal_current} current, "
              f"{cal_superseded} superseded")
    print(f"\n  Total entries: {total} ({current} current, {superseded} superseded)")


def main():
    parser = argparse.ArgumentParser(
        description="Decode NVDS regions from Atmosic ATM3 firmware dump (Samsung TM2280E)"
    )
    parser.add_argument("firmware", help="Path to firmware binary (.bin)")
    parser.add_argument("--region", type=lambda x: int(x, 0),
                        help="Decode only one region at this offset (e.g. 0x30000)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show superseded entries and RF calibration entries")
    args = parser.parse_args()

    with open(args.firmware, 'rb') as f:
        data = f.read()

    print(f"Firmware: {args.firmware}")
    print(f"Size: {len(data)} bytes ({len(data) // 1024} KB)")

    if args.region is not None:
        label, size = NVDS_REGIONS.get(args.region,
                                       (f"@ 0x{args.region:05X}", 0x1000))
        decode_nvds_region(data, args.region, label, size, args.verbose)
    else:
        for offset, (label, size) in NVDS_REGIONS.items():
            decode_nvds_region(data, offset, label, size, args.verbose)


if __name__ == "__main__":
    main()
