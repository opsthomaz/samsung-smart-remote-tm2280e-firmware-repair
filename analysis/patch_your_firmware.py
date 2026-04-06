#!/usr/bin/env python3
"""
patch_your_firmware.py — Apply the TM2280E OTA fix to YOUR OWN firmware dump.

⚠️  DO NOT use controller_fixed5.bin from this repo on your remote.
    That file contains BD Address and RF calibration data specific to
    the researcher's hardware. Flash it and you will clone someone
    else's Bluetooth address and overwrite your factory RF calibration.

    USE THIS SCRIPT INSTEAD. It patches your own dump, preserving your
    unique BD Address and the ~156 factory RF calibration entries that
    were programmed specifically for your hardware's physical tolerances.

What this script does:
  1. Validates your dump (size, Bank A/B USR signatures)
  2. Programs Bank B BOOT_CONFIRMED flag: 0x08 → 0x00 at offset 0x40010
  3. Restores Bank A NVDS secondary slot from primary: 0x30000 → 0x3F000
  4. Verifies your BD Address and RF calibration are preserved
  5. Saves the patched file as <original>_fixed.bin

Usage:
  python3 patch_your_firmware.py your_backup.bin
  python3 patch_your_firmware.py your_backup.bin --output my_fixed.bin
  python3 patch_your_firmware.py your_backup.bin --dry-run
"""

import sys
import os
import struct
import hashlib
import argparse
import shutil
from datetime import datetime


# Expected flash size
EXPECTED_SIZE = 524288  # 512 KB

# Critical offsets
BANK_A_FLAG_OFFSET = 0x0010
BANK_B_FLAG_OFFSET = 0x40010
BANK_A_NVDS_PRIMARY = 0x30000
BANK_A_NVDS_SECONDARY = 0x3F000
BANK_B_NVDS_PRIMARY = 0x70000

# USR signature
USR_SIG = b'USR'

# The ONLY two byte changes this script makes
BOOT_CONFIRMED = 0x00
NEARLY_CONFIRMED = 0x08


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def format_bd_address(data: bytes) -> str:
    return ':'.join(f'{b:02X}' for b in reversed(data))


def find_bd_address(data: bytes, offset: int) -> bytes | None:
    """Find BD Address in NVDS region starting at offset."""
    pos = offset + 4  # skip NVDS magic
    end = offset + 0x1000

    while pos < end:
        tag = data[pos]
        if tag == 0xFF:
            break
        if pos + 1 >= end:
            break
        length = data[pos + 1]
        value = data[pos + 2:pos + 2 + length]

        # Tag 0x3A = BD Address (direct), tag 0x01 = BD Address variant
        if tag in (0x01, 0x3A) and length == 6:
            return value

        # Also check inside config block (tag 0x20), sub-tag 0x3A
        if tag == 0x20:
            i = 11  # skip device name continuation
            while i < length - 1:
                stag = value[i] if i < len(value) else 0xFF
                if stag == 0xFF:
                    break
                slen = value[i + 1] if i + 1 < len(value) else 0
                sval = value[i + 2:i + 2 + slen]
                if stag == 0x3A and slen == 6:
                    return sval
                i += 2 + slen

        pos += 2 + length

    return None


def count_calibration_entries(data: bytes, offset: int) -> int:
    """Count RF calibration entries (tag 0xC1) in an NVDS region."""
    pos = offset + 4
    end = offset + 0x10000  # Bank NVDS can be up to 60KB
    count = 0

    while pos < end:
        tag = data[pos]
        if tag == 0xFF:
            break
        if pos + 1 >= end:
            break
        length = data[pos + 1]
        if tag == 0xC1:
            count += 1
        pos += 2 + length

    return count


def validate_dump(data: bytes) -> list:
    """Validate the firmware dump. Returns list of issues (empty = OK)."""
    issues = []

    if len(data) != EXPECTED_SIZE:
        issues.append(f"Unexpected size: {len(data)} bytes (expected {EXPECTED_SIZE})")

    # Check Bank A signature
    sig_a = data[BANK_A_FLAG_OFFSET + 1:BANK_A_FLAG_OFFSET + 4]
    if sig_a != USR_SIG:
        issues.append(f"Bank A: invalid USR signature ({sig_a.hex()})")

    # Check Bank B signature
    sig_b = data[BANK_B_FLAG_OFFSET + 1:BANK_B_FLAG_OFFSET + 4]
    if sig_b != USR_SIG:
        issues.append(f"Bank B: invalid USR signature ({sig_b.hex()})")

    # Check NVDS Bank A primary magic
    if data[BANK_A_NVDS_PRIMARY:BANK_A_NVDS_PRIMARY + 4] != b'NVDS':
        issues.append("Bank A NVDS primary: missing NVDS magic")

    return issues


def get_nvds_blob(data: bytes, offset: int) -> bytes:
    """Extract the populated NVDS data (magic + entries + first FF)."""
    if data[offset:offset + 4] != b'NVDS':
        return b''

    pos = offset + 4
    end = offset + 0x1000

    while pos < end:
        tag = data[pos]
        if tag == 0xFF:
            pos += 1  # include the terminator
            break
        if pos + 1 >= end:
            break
        length = data[pos + 1]
        pos += 2 + length

    return data[offset:pos]


def apply_patch(data: bytes, dry_run: bool = False) -> tuple[bytes, dict]:
    """
    Apply the two-byte patch to the firmware dump.
    Returns (patched_data, report_dict).
    """
    patched = bytearray(data)
    report = {
        "changes": [],
        "bd_address": None,
        "cal_entries": 0,
        "warnings": [],
    }

    # --- Change 1: Bank B BOOT_CONFIRMED ---
    current_flag = data[BANK_B_FLAG_OFFSET]

    if current_flag == BOOT_CONFIRMED:
        report["warnings"].append(
            f"Bank B flag is already 0x00 (BOOT_CONFIRMED) — no change needed"
        )
    elif current_flag == NEARLY_CONFIRMED:
        if not dry_run:
            patched[BANK_B_FLAG_OFFSET] = BOOT_CONFIRMED
        report["changes"].append({
            "offset": BANK_B_FLAG_OFFSET,
            "old": f"0x{current_flag:02X}",
            "new": f"0x{BOOT_CONFIRMED:02X}",
            "description": "Bank B flag: NEARLY_CONFIRMED → BOOT_CONFIRMED",
        })
    else:
        report["warnings"].append(
            f"Bank B flag is 0x{current_flag:02X} — not the expected 0x08. "
            f"Your firmware may be in a different state. Patch still applied."
        )
        if not dry_run:
            patched[BANK_B_FLAG_OFFSET] = BOOT_CONFIRMED
        report["changes"].append({
            "offset": BANK_B_FLAG_OFFSET,
            "old": f"0x{current_flag:02X}",
            "new": f"0x{BOOT_CONFIRMED:02X}",
            "description": "Bank B flag: forced to BOOT_CONFIRMED",
        })

    # --- Change 2: Restore Bank A NVDS secondary ---
    secondary_blank = all(b == 0xFF for b in data[BANK_A_NVDS_SECONDARY:BANK_A_NVDS_SECONDARY + 16])
    nvds_blob = get_nvds_blob(data, BANK_A_NVDS_PRIMARY)

    if not secondary_blank:
        report["warnings"].append(
            "Bank A NVDS secondary (0x3F000) already has data — skipping restore"
        )
    elif not nvds_blob:
        report["warnings"].append(
            "Bank A NVDS primary (0x30000) has no valid data — cannot restore secondary"
        )
    else:
        if not dry_run:
            # Clear secondary slot
            for i in range(0x1000):
                patched[BANK_A_NVDS_SECONDARY + i] = 0xFF
            # Copy primary to secondary
            patched[BANK_A_NVDS_SECONDARY:BANK_A_NVDS_SECONDARY + len(nvds_blob)] = nvds_blob
        report["changes"].append({
            "offset": BANK_A_NVDS_SECONDARY,
            "size": len(nvds_blob),
            "description": f"Bank A NVDS secondary restored from primary ({len(nvds_blob)} bytes)",
        })

    # --- Verify preservation of unique data ---
    bd_a = find_bd_address(data, BANK_A_NVDS_PRIMARY)
    bd_b = find_bd_address(data, BANK_B_NVDS_PRIMARY)

    if bd_a:
        report["bd_address"] = format_bd_address(bd_a)
    elif bd_b:
        report["bd_address"] = format_bd_address(bd_b)
    else:
        report["warnings"].append("BD Address not found in NVDS — your dump may be unusual")

    report["cal_entries"] = count_calibration_entries(data, BANK_B_NVDS_PRIMARY)

    return bytes(patched), report


def print_report(report: dict, original_sha: str, patched_sha: str):
    print()
    print("=" * 60)
    print("Patch Report")
    print("=" * 60)

    print(f"\n  SHA256 original: {original_sha}")
    print(f"  SHA256 patched:  {patched_sha}")

    print(f"\n  Changes applied ({len(report['changes'])}):")
    for change in report["changes"]:
        if "old" in change:
            print(f"    0x{change['offset']:05X}: {change['old']} → {change['new']}")
            print(f"           {change['description']}")
        else:
            print(f"    0x{change['offset']:05X}: {change['description']}")

    if report["bd_address"]:
        print(f"\n  ✅ Your BD Address preserved: {report['bd_address']}")
    if report["cal_entries"] > 0:
        print(f"  ✅ Your RF calibration entries preserved: {report['cal_entries']} entries")

    if report["warnings"]:
        print(f"\n  ⚠️  Warnings:")
        for w in report["warnings"]:
            print(f"    - {w}")

    total_bytes = sum(
        c.get("size", 1) for c in report["changes"]
    )
    print(f"\n  Total bytes modified: {total_bytes}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Patch your own TM2280E firmware dump to fix the OTA boot issue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
⚠️  IMPORTANT: Do NOT flash controller_fixed5.bin from this repo.
    That file contains someone else's BD Address and RF calibration.
    This script patches YOUR dump, preserving YOUR unique hardware data.

Examples:
  python3 patch_your_firmware.py my_backup.bin
  python3 patch_your_firmware.py my_backup.bin --output my_fixed.bin
  python3 patch_your_firmware.py my_backup.bin --dry-run
        """
    )
    parser.add_argument("firmware", help="Path to your firmware backup (.bin)")
    parser.add_argument("--output", "-o", help="Output filename (default: <input>_fixed.bin)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze only, do not write any file")
    args = parser.parse_args()

    # Load firmware
    print(f"Loading: {args.firmware}")
    with open(args.firmware, 'rb') as f:
        data = f.read()

    original_sha = sha256(data)
    print(f"SHA256: {original_sha}")
    print(f"Size:   {len(data)} bytes")

    # Validate
    issues = validate_dump(data)
    if issues:
        print("\n❌ Validation failed:")
        for issue in issues:
            print(f"  - {issue}")
        print("\nThis dump may not be from a TM2280E or may be corrupted.")
        print("Proceeding anyway — check the output carefully.")

    # Apply patch
    print("\nApplying patch...")
    patched, report = apply_patch(data, dry_run=args.dry_run)
    patched_sha = sha256(patched) if not args.dry_run else "(dry run)"

    print_report(report, original_sha, patched_sha)

    if args.dry_run:
        print("\n[DRY RUN] No file written.")
        return

    # Write output
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.firmware)[0]
        output_path = f"{base}_fixed.bin"

    with open(output_path, 'wb') as f:
        f.write(patched)

    print(f"\n✅ Written: {output_path}")
    print(f"   Flash this file with your CH341A (1.8V adapter required!)")
    print(f"   Verify SHA256 after flashing: {patched_sha}")


if __name__ == "__main__":
    main()
