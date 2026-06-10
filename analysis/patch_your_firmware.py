#!/usr/bin/env python3
"""
patch_your_firmware.py — Apply the TM2280E OTA fix to YOUR OWN firmware dump.

⚠️  DO NOT use controller_fixed5.bin from this repo on your remote.
    That file contains BD Address and RF calibration data specific to
    the researcher's hardware. Flash it and you will clone someone
    else's Bluetooth address and overwrite your factory RF calibration.

    USE THIS SCRIPT INSTEAD. It patches your own dump, preserving your
    unique BD Address and the device-specific RF calibration entries
    stored in your NVDS.

What this script does:
  1. Validates your dump (size, Bank A/B USR signatures)
  2. Programs Bank B BOOT_CONFIRMED flag: 0x08 → 0x00 at offset 0x40010
  3. Restores Bank A NVDS secondary slot from primary: 0x30000 → 0x3F000
  4. Verifies your BD Address and RF calibration are preserved
  5. Saves the patched file as <original>_fixed.bin

The fix is two changes (188 bytes on the reference dump): one flag byte
plus the NVDS secondary restore. No firmware code is modified.

Usage:
  python3 patch_your_firmware.py your_backup.bin
  python3 patch_your_firmware.py your_backup.bin --output my_fixed.bin
  python3 patch_your_firmware.py your_backup.bin --dry-run
"""

import sys
import os
import hashlib
import argparse

# Windows consoles often default to a legacy code page (cp1252) that
# cannot encode the arrows/checkmarks printed below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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

# NVDS entry format: [tag: 1][status: 1][length: 1][value: length bytes]
# Status 0x06 = current entry, 0x02 = superseded (an update was appended later)
NVDS_MAGIC = b'NVDS'
NVDS_STATUS_CURRENT = 0x06
NVDS_TAG_BD_ADDRESS = 0x01
NVDS_TAG_RF_CAL = 0xC1

# The ONLY two byte changes this script makes
BOOT_CONFIRMED = 0x00
NEARLY_CONFIRMED = 0x08


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def format_bd_address(data: bytes) -> str:
    return ':'.join(f'{b:02X}' for b in reversed(data))


def iter_nvds_entries(data: bytes, offset: int, size: int):
    """Yield (pos, tag, status, length, value) for each NVDS entry.

    The chain ends at the first 0xFF tag byte (erased flash) or when an
    entry would run past the slot boundary.
    """
    if data[offset:offset + 4] != NVDS_MAGIC:
        return
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


def find_bd_address(data: bytes, offset: int, size: int = 0xF000) -> bytes | None:
    """Find the BD Address (tag 0x01) in an NVDS region, preferring a
    current entry over superseded ones."""
    found = None
    for _, tag, status, length, value in iter_nvds_entries(data, offset, size):
        if tag == NVDS_TAG_BD_ADDRESS and length == 6:
            if status == NVDS_STATUS_CURRENT:
                found = value
            elif found is None:
                found = value
    return found


def count_calibration_entries(data: bytes, offset: int, size: int = 0xF000) -> int:
    """Count RF calibration entries (tag 0xC1) in an NVDS region."""
    return sum(1 for _, tag, _, _, _ in iter_nvds_entries(data, offset, size)
               if tag == NVDS_TAG_RF_CAL)


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
    """Extract the populated NVDS data (magic + entries) from a slot.

    Capped at 4 KB because the restore target (the secondary slot) is a
    single 4 KB sector.
    """
    if data[offset:offset + 4] != NVDS_MAGIC:
        return b''

    end = offset + 4
    for pos, _, _, length, _ in iter_nvds_entries(data, offset, 0x1000):
        end = pos + 3 + length

    return data[offset:end]


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
