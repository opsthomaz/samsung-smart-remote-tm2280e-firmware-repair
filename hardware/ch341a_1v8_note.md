# CH341A Voltage Warning — W25Q40EW is 1.8V

## The Problem

The **Winbond W25Q40EW** used in the Samsung TM2280E is a **1.8V chip**:

- Operating voltage: 1.65V – 1.95V
- Absolute maximum on I/O pins: ~2.1V
- The "EW" suffix in Winbond naming = 1.8V variant (vs "BV" = 3.3V)

The **CH341A programmer default configuration outputs 3.3V** on all SPI signal lines (CLK, MOSI, MISO, CS). This exceeds the chip's absolute maximum ratings.

## Consequences of Using Wrong Voltage

- **Silent write corruption**: The chip may appear to accept writes but store incorrect data
- **Verify failures**: The programmed data won't match what was sent
- **Cumulative damage**: Repeated 3.3V writes degrade the chip over time
- **Complete failure**: The chip stops responding entirely

In this specific repair case, multiple flashing attempts at 3.3V caused the remote LED to stop lighting entirely — consistent with chip damage or severe data corruption.

## The Fix

Purchase a **1.8V adapter for CH341A**. These are small PCBs that sit between the CH341A and the chip socket, shifting signal levels from 3.3V to 1.8V.

**Search terms:**
- "CH341A 1.8V adapter"
- "1.8V SPI flash adapter"
- "CH341A voltage adapter 1.8V"

**Cost:** ~$2–5 USD on AliExpress, Amazon, eBay

**Availability:** Widely available from electronics suppliers

## How to Verify You Have the Right Adapter

When AsProgrammer or NeoProgrammer detects the chip, it should show:

```
W25Q40EW    1.8V    4 Mbits    256 Bytes    WINBOND    SPI_NOR
```

(not the 3.3V variant `W25Q40EW_1.8V` shown as a fallback — use the primary 1.8V entry)

## Alternative: In-System Programming at the Correct Voltage

If the chip is still soldered and you have access to the board's power rail, you can verify the operating voltage with a multimeter on the VCC pin of the W25Q40EW. The Samsung TM2280E board powers the flash at **1.8V** (consistent with the ATM3's 1.8V I/O supply).

If using a clip-on SOIC adapter in-circuit, the board's own 1.8V supply will power the chip correctly — but the CH341A's 3.3V signals on CLK/MOSI/CS will still damage it. The voltage adapter is still required.

## Flashrom Users

When using flashrom on Linux/macOS, the CH341A driver defaults to 3.3V. The same warning applies — use the hardware 1.8V adapter.

There is no software-only solution for the CH341A voltage issue. The hardware adapter is mandatory.
