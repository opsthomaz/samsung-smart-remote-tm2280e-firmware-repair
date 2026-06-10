#!/usr/bin/env python3
"""
Boot flag analyzer for Atmosic ATM3 dual-bank system (Samsung TM2280E)

Documents the progressive bit-programming scheme used by the Atmosic
proprietary bootloader (USR format, pre-MCUboot era) for OTA lifecycle
management.

Usage:
  python3 boot_flag_analysis.py controller_original.bin
"""

import sys
import struct
import argparse

# Windows consoles often default to a legacy code page (cp1252) that
# cannot encode the box-drawing characters printed below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# The Atmosic USR boot header has a 1-byte flag at offset +0x10
# (immediately before the 3-byte "USR" signature)
# In NOR flash: bit=1 = erased (unprogrammed), bit=0 = programmed
#
# The OTA process programs bits sequentially from MSB to LSB:
#
#   0xFF  (11111111)  ERASED — no firmware present
#   0xFE  (11111110)  MK_PROGRAMMED — firmware written to flash
#   0xFC  (11111100)  MK_VALID — image CRC verified
#   0xF8  (11111000)  DOWNLOAD_OK — download phase complete
#   0xF0  (11110000)  VERIFY_OK — verification phase complete
#   0xE0  (11100000)  FINISH_OK — OTA finish command received
#   0xC0  (11000000)  APP_STARTED — application began executing
#   0x80  (10000000)  APP_STABLE — application ran successfully
#   0x08  (00001000)  NEARLY_CONFIRMED — all bits except bit3
#   0x00  (00000000)  BOOT_CONFIRMED — fully active, confirmed boot
#
# The bit3 gap (0x08 instead of 0x00) observed in the TM2280E dump
# indicates the OTA completed all phases but the application never
# wrote the final BOOT_CONFIRMED marker — most likely because NVDS
# validation failed on first boot after OTA.

BOOT_FLAG_MAP = {
    0xFF: ("ERASED",           "No firmware in this bank"),
    0xFE: ("MK_PROGRAMMED",    "Firmware written — factory/fallback state"),
    0xFC: ("MK_VALID",         "CRC verified"),
    0xF8: ("DOWNLOAD_OK",      "OTA download phase complete"),
    0xF0: ("VERIFY_OK",        "OTA verify phase complete"),
    0xE0: ("FINISH_OK",        "OTA finish command acknowledged"),
    0xC0: ("APP_STARTED",      "Application started executing"),
    0x80: ("APP_STABLE",       "Application running stably"),
    0x08: ("NEARLY_CONFIRMED", "⚠️  All bits set EXCEPT bit3 — BOOT_CONFIRMED missing"),
    0x00: ("BOOT_CONFIRMED",   "✅ Fully confirmed — bootloader will prefer this bank"),
}

BANK_HEADER_OFFSETS = {
    "Bank A": 0x0010,
    "Bank B": 0x40010,
}


def analyze_flag(flag: int) -> dict:
    """Analyze a boot flag byte."""
    bits_programmed = bin(~flag & 0xFF).count('1')

    if flag in BOOT_FLAG_MAP:
        state, description = BOOT_FLAG_MAP[flag]
    else:
        state = "PARTIAL"
        description = f"Intermediate state — {bits_programmed} bits programmed"

    return {
        "value": flag,
        "binary": f"{flag:08b}",
        "bits_programmed": bits_programmed,
        "state": state,
        "description": description,
    }


def print_flag_table():
    """Print the complete flag progression table."""
    print("\nAtmosic ATM3 Boot Flag Progression (NOR flash: bit=0 = programmed)")
    print("─" * 75)
    print(f"  {'Hex':>5}  {'Binary':>10}  {'State':<22}  Description")
    print("─" * 75)
    for val in [0xFF, 0xFE, 0xFC, 0xF8, 0xF0, 0xE0, 0xC0, 0x80, 0x08, 0x00]:
        state, desc = BOOT_FLAG_MAP[val]
        arrow = "←" if val == 0x08 else " "
        print(f"  0x{val:02X}   {val:08b}    {state:<22}  {desc} {arrow}")
    print("─" * 75)
    print("  ← = state found in TM2280E dump (Bank B)")


def analyze_firmware(data: bytes):
    """Analyze boot flags in a firmware dump."""
    print("\nBank Header Analysis")
    print("─" * 60)

    results = {}
    for bank_name, offset in BANK_HEADER_OFFSETS.items():
        flag = data[offset]
        sig = data[offset + 1:offset + 4]
        ptr1 = struct.unpack_from('<I', data, offset + 4)[0]

        sig_valid = sig == b'USR'
        analysis = analyze_flag(flag)
        results[bank_name] = analysis

        print(f"\n  {bank_name} (header @ 0x{offset:05X}):")
        print(f"    Signature:       {'✅ USR' if sig_valid else f'❌ {sig.hex()}'}")
        print(f"    Flag byte:       0x{flag:02X} = {flag:08b}b")
        print(f"    State:           {analysis['state']}")
        print(f"    Description:     {analysis['description']}")
        print(f"    Bits programmed: {analysis['bits_programmed']} of 8")
        print(f"    Entry pointer:   0x{ptr1:08X}")

    # Boot decision analysis
    print(f"\n{'─'*60}")
    print("Boot Decision Analysis")
    print("─" * 60)

    flag_a = results["Bank A"]["value"]
    flag_b = results["Bank B"]["value"]

    print(f"\n  Bank A flag: 0x{flag_a:02X} ({results['Bank A']['state']})")
    print(f"  Bank B flag: 0x{flag_b:02X} ({results['Bank B']['state']})")

    bits_a = results["Bank A"]["bits_programmed"]
    bits_b = results["Bank B"]["bits_programmed"]

    print()
    if flag_b == 0x00:
        print("  ✅ Bank B is BOOT_CONFIRMED — bootloader should prefer it")
    elif flag_b == 0x08:
        print("  ⚠️  Bank B is NEARLY_CONFIRMED (bit3 missing)")
        print("     The application never wrote the final BOOT_CONFIRMED marker.")
        print("     Bootloader behavior is undefined — may execute Bank B or")
        print("     fall back to Bank A depending on ROM implementation.")
        print()
        print("  Fix: program bit3 of Bank B flag byte (0x08 → 0x00)")
        print(f"  Location: offset 0x{BANK_HEADER_OFFSETS['Bank B']:05X}")
    elif flag_a == 0xFE and bits_b > bits_a:
        print(f"  Bank B has more flags set ({bits_b} vs {bits_a})")
        print("  Bootloader likely prefers Bank B but state is uncertain")

    # Verify fix if applicable
    if flag_b == 0x00:
        print("\n  ✅ BOOT_CONFIRMED is set — no fix needed for this file")


def main():
    parser = argparse.ArgumentParser(
        description="Boot flag analyzer for Atmosic ATM3 (Samsung TM2280E)"
    )
    parser.add_argument("firmware", nargs='?',
                        help="Firmware binary to analyze (optional — shows table only if omitted)")
    parser.add_argument("--table", action="store_true",
                        help="Print the full flag progression table")
    args = parser.parse_args()

    if args.table or not args.firmware:
        print_flag_table()

    if args.firmware:
        with open(args.firmware, 'rb') as f:
            data = f.read()
        print(f"\nFirmware: {args.firmware} ({len(data)} bytes)")
        analyze_firmware(data)


if __name__ == "__main__":
    main()
