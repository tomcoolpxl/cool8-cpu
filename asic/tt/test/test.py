# SPDX-License-Identifier: Apache-2.0
"""Pin-level smoke test for the COOL8 TinyTapeout wrapper.

The real verification lives in the CPU's own repository: every one of
the 511 encodings is co-simulated against a reference emulator, at the
core's memory interface and again through this wrapper against
behavioural 74HC573 and SRAM models. What is worth testing *here* is the
thing that is specific to the chip — that the three-phase bus appears on
the pins in the right order, and that a bus grant takes the CPU off them.

  T1  AD = A[7:0],  ALE_L high
  T2  AD = A[15:8], ALE_H high
  T3  nRD low, AD released, data sampled at the end

After reset the first thing the CPU does is read the reset vector from
$FFF8 and $FFF9, so that is what should come out of the pins.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

ALE_L, ALE_H, N_RD, N_WR, SYNC, HALTED, IACK, BUSAK = range(8)


def bit(dut, n):
    return (int(dut.uo_out.value) >> n) & 1


async def settle(dut):
    """One clock on, then a quarter period, so combinational outputs
    have propagated and the half-cycle ALE pulses are still high."""
    await RisingEdge(dut.clk)
    await Timer(2, unit="us")


async def next_access(dut, data=0x00, limit=200):
    """Run one three-phase bus cycle and return (address, was_a_read)."""
    for _ in range(limit):
        await settle(dut)
        if bit(dut, ALE_L):
            lo = int(dut.uio_out.value)
            assert int(dut.uio_oe.value) == 0xFF, "AD not driven in T1"
            await settle(dut)
            assert bit(dut, ALE_H), "ALE_H did not follow ALE_L"
            hi = int(dut.uio_out.value)
            await settle(dut)
            read = bit(dut, N_RD) == 0
            if read:
                assert int(dut.uio_oe.value) == 0x00, \
                    "AD not released for the read in T3"
                dut.uio_in.value = data
            return (hi << 8) | lo, read
    raise AssertionError("no bus cycle started")


@cocotb.test()
async def test_reset_vector(dut):
    """After reset the CPU reads $FFF8 and $FFF9."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())

    dut.ena.value = 1
    dut.ui_in.value = 0x0F        # all active-low inputs idle, READY high
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    addr, read = await next_access(dut, data=0x34)
    assert read, "the reset vector fetch must be a read"
    assert addr == 0xFFF8, f"expected $FFF8, got ${addr:04X}"

    addr, read = await next_access(dut, data=0x12)
    assert read
    assert addr == 0xFFF9, f"expected $FFF9, got ${addr:04X}"

    # PC is now $1234, so the first opcode fetch lands there and SYNC
    # marks it as an opcode rather than data.
    for _ in range(200):
        await settle(dut)
        if bit(dut, ALE_L):
            assert int(dut.uio_out.value) == 0x34, "wrong PC low byte"
            assert bit(dut, SYNC), "SYNC not asserted on an opcode fetch"
            break
    else:
        raise AssertionError("no opcode fetch after the reset vector")


@cocotb.test()
async def test_bus_grant(dut):
    """nBUSRQ takes the CPU off the bus entirely."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())

    dut.ena.value = 1
    dut.ui_in.value = 0x0F
    dut.uio_in.value = 0x20       # NOP, whatever it fetches
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 40)

    dut.ui_in.value = 0x07        # nBUSRQ low
    for _ in range(200):
        await settle(dut)
        if bit(dut, BUSAK):
            break
    else:
        raise AssertionError("BUSAK never asserted")

    # Held for a while, the CPU must drive nothing at all.
    for _ in range(30):
        await settle(dut)
        assert bit(dut, BUSAK), "BUSAK dropped while nBUSRQ was low"
        assert int(dut.uio_oe.value) == 0x00, "AD still driven during a grant"
        assert bit(dut, N_RD) and bit(dut, N_WR), "strobe active during a grant"
        assert not bit(dut, ALE_L) and not bit(dut, ALE_H), \
            "ALE active during a grant"

    dut.ui_in.value = 0x0F        # release
    for _ in range(200):
        await settle(dut)
        if not bit(dut, BUSAK):
            break
    else:
        raise AssertionError("BUSAK never released")

    await next_access(dut, data=0x20)   # and it carries on
