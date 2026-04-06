#!/usr/bin/env python3
"""
Flash layout mapper and region auditor for Atmosic ATM3 (Samsung TM2280E)

Prints a full map of the 512KB flash dump, identifying code regions,
NVDS slots, boot header flags, and data density per 4KB block.

Usage:
  python3 flash_layout.py controller_original.bin
  python3 flash_layout.py controller_fixed5.bin --diff controller_original.bin
"""

import sys
import struct
import argparse
import hashlib


REGIONS = [
    (0x00000, 0x00100, "Boot vector / ARM trampolim"),
    (0x00100, 0x30000, "Bank A — application code"),
    (0x30000, 0x3F000, "NVDS Bank A — primary"),
    (0x3F000, 0x40000, "NVDS Bank A — secondary"),
    (0x40000, 0x40100, "Bank B — boot vector"),
    (0x40100, 0x70000, "Bank B — application code"),
    (0x70000, 0x7F000, "NVDS Bank B — primary"),
    (0x7F000, 0x80000, "NVDS Bank B — secondary"),
]

BOOT_FLAG_STEPS = [
    (0xFF, "ERASED  — no firmware"),
    (0xFE, "PROGRAMMED — written to flash"),
    (0xFC, "VALID — CRC verified"),
    (0xF8, "DOWNLOAD OK"),
    (0xF0, "VERIFY OK"),
    (0xE0, "FINISH OK"),
    (0xC0, "APP STARTED"),
    (0x80, "APP STABLE"),
    (0x08, "ALMOST CONFIRMED — bit3 missing"),
    (0x00, "BOOT CONFIRMED — fully active"),
]


def describe_flag(flag_byte: int) -> str:
    for val, desc in BOOT_FLAG_STEPS:
        if flag_byte == val:
            return desc
    # Partial match — find closest
    bits_set = bin(~flag_byte & 0xFF).count('1')
    return f"PARTIAL ({bits_set} bits programmed) — 0x{flag_byte:02X}"


def print_region_map(data: bytes):
    print(f"\n{'Offset':<10} {'End':<10} {'Size':>8}   {'FF%':>6}   {'Region'}")
    print("─" * 80)
    for start, end, name in REGIONS:
        chunk = data[start:end]
        ff_count = sum(1 for b in chunk if b == 0xFF)
        ff_pct = ff_count / len(chunk) * 100
        non_ff = len(chunk) - ff_count
        size_kb = len(chunk) // 1024

        if ff_pct == 100.0:
            status = "❌ BLANK"
        elif ff_pct > 95:
            status = "⚠️  SPARSE"
        elif ff_pct < 10:
            status = "✅ FULL"
        else:
            status = "✅ DATA"

        print(f"0x{start:05X}    0x{end:05X}   {size_kb:>4} KB   {ff_pct:>5.1f}%   {name}  {status}")


def print_boot_headers(data: bytes):
    print(f"\n{'─'*60}")
    print("Boot Header Analysis (Atmosic USR format)")
    print(f"{'─'*60}")

    for bank, offset, label in [("A", 0x0010, "Bank A"), ("B", 0x40010, "Bank B")]:
        flag = data[offset]
        sig = data[offset + 1:offset + 4]
        ptr = struct.unpack_from('<I', data, offset + 4)[0]

        sig_str = sig.decode('latin1') if sig == b'USR' else sig.hex()
        flag_desc = describe_flag(flag)

        ok = "✅" if sig == b'USR' else "❌"
        print(f"\n  {label} @ 0x{offset:05X}:")
        print(f"    Signature:  {ok} '{sig_str}'")
        print(f"    Flag byte:  0x{flag:02X} = {flag:08b}b")
        print(f"    State:      {flag_desc}")
        print(f"    Pointer:    0x{ptr:08X}")


def print_nvds_summary(data: bytes):
    print(f"\n{'─'*60}")
    print("NVDS Slot Summary")
    print(f"{'─'*60}")

    nvds_slots = [
        (0x30000, "Bank A primary"),
        (0x3F000, "Bank A secondary"),
        (0x70000, "Bank B primary"),
        (0x7F000, "Bank B secondary"),
    ]

    for offset, label in nvds_slots:
        magic = data[offset:offset + 4]
        if magic == b'NVDS':
            # Count non-FF bytes
            region = data[offset:offset + 0x1000]
            non_ff = sum(1 for b in region if b != 0xFF)
            # Find end of NVDS
            end_off = offset + 4
            while end_off < offset + 0x1000:
                if data[end_off] == 0xFF:
                    break
                length = data[end_off + 1] if end_off + 1 < offset + 0x1000 else 0
                end_off += 2 + length
            nvds_size = end_off - offset - 4
            print(f"  {label:<25} ✅ NVDS  {non_ff:5d} bytes  (entries end @ 0x{end_off:05X})")
        elif all(b == 0xFF for b in data[offset:offset + 16]):
            print(f"  {label:<25} ❌ BLANK")
        else:
            print(f"  {label:<25} ⚠️  PARTIAL  magic={magic.hex()}")


def print_diff(data_a: bytes, data_b: bytes):
    print(f"\n{'─'*60}")
    print("Diff Analysis")
    print(f"{'─'*60}")

    diffs = [(i, data_a[i], data_b[i]) for i in range(min(len(data_a), len(data_b)))
             if data_a[i] != data_b[i]]

    print(f"  Total bytes changed: {len(diffs)}")

    if not diffs:
        print("  Files are identical.")
        return

    # Group by region
    from collections import defaultdict
    by_region = defaultdict(list)
    for offset, old, new in diffs:
        for start, end, name in REGIONS:
            if start <= offset < end:
                by_region[name].append((offset, old, new))
                break

    for region, changes in by_region.items():
        print(f"\n  [{region}] — {len(changes)} bytes changed:")
        for offset, old, new in changes[:10]:
            print(f"    0x{offset:05X}: 0x{old:02X} → 0x{new:02X}")
        if len(changes) > 10:
            print(f"    ... and {len(changes) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Flash layout mapper for Atmosic ATM3 firmware (Samsung TM2280E)"
    )
    parser.add_argument("firmware", help="Firmware binary to analyze")
    parser.add_argument("--diff", metavar="OTHER",
                        help="Compare with another firmware file")
    args = parser.parse_args()

    with open(args.firmware, 'rb') as f:
        data = f.read()

    sha256 = hashlib.sha256(data).hexdigest()
    print(f"File:   {args.firmware}")
    print(f"Size:   {len(data)} bytes ({len(data) // 1024} KB)")
    print(f"SHA256: {sha256}")

    print_region_map(data)
    print_boot_headers(data)
    print_nvds_summary(data)

    if args.diff:
        with open(args.diff, 'rb') as f:
            data_b = f.read()
        print_diff(data, data_b)


if __name__ == "__main__":
    main()
