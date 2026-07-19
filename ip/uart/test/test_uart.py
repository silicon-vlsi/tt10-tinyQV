# SPDX-License-Identifier: MIT
#
# test_uart.py — cocotb verification IP for uart_riscv_if
#
# Tests:
#   test_reset_state       — STATUS = 0x00 after reset; DATA = 0x00; BAUD_DIV sane
#   test_tx_basic          — Write DATA, verify UART TX framing on uart_tx pin
#   test_tx_busy_flag      — STATUS[0] (tx_busy) is asserted while sending
#   test_rx_basic          — Drive uart_rx with a UART frame; read DATA register
#   test_rx_valid_flag     — STATUS[1] (rx_valid) asserts on receipt, clears on read
#   test_ctrl_irq_enables  — Write CTRL, verify rx_irq / tx_irq outputs
#   test_baud_div          — BAUD_DIV register returns correct value
#   test_loopback          — TX byte looped back through RX; verify end-to-end
#
# Testbench parameters (set in tb_uart.v):
#   CLK_HZ   = 10_000_000  (10 MHz → 100 ns/cycle)
#   BIT_RATE =  1_000_000  (1 Mbaud → 10 cycles/bit)
#   CYCLES_PER_BIT = (CLK_HZ - 1) // BIT_RATE = 9
#   BIT_CYCLES (observable period)  = CYCLES_PER_BIT + 1 = 10

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, FallingEdge, Timer

# ---------------------------------------------------------------------------
# Testbench constants (must match tb_uart.v / uart_riscv_if parameters)
# ---------------------------------------------------------------------------
CLK_PERIOD_NS  = 100          # 10 MHz
CLK_HZ         = 10_000_000
BIT_RATE       = 1_000_000
CYCLES_PER_BIT = (CLK_HZ - 1) // BIT_RATE   # = 9
BIT_CYCLES     = CYCLES_PER_BIT + 1          # = 10 (observable clocks per bit)

# Register word addresses
ADDR_DATA     = 0b00
ADDR_STATUS   = 0b01
ADDR_CTRL     = 0b10
ADDR_BAUD_DIV = 0b11

# STATUS bits
STATUS_TX_BUSY  = 0x01
STATUS_RX_VALID = 0x02

# CTRL bits
CTRL_RX_IRQ_EN = 0x01
CTRL_TX_IRQ_EN = 0x02


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

async def start_clock(dut):
    """Start a 10 MHz clock on dut.clk."""
    clock = Clock(dut.clk, CLK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())


async def reset_dut(dut):
    """Apply reset for several cycles then release."""
    dut.resetn.value    = 0
    dut.reg_we.value    = 0
    dut.reg_re.value    = 0
    dut.reg_addr.value  = 0
    dut.reg_wdata.value = 0
    dut.uart_rx.value   = 1   # idle-high
    await ClockCycles(dut.clk, 8)
    dut.resetn.value = 1
    await ClockCycles(dut.clk, 2)


async def reg_write(dut, addr, data):
    """Write one word to the register interface (single-cycle pulse)."""
    await RisingEdge(dut.clk)
    dut.reg_addr.value  = addr
    dut.reg_wdata.value = data
    dut.reg_we.value    = 1
    await RisingEdge(dut.clk)
    dut.reg_we.value    = 0
    dut.reg_addr.value  = 0


async def reg_read(dut, addr):
    """Read one word from the register interface (single-cycle pulse)."""
    await RisingEdge(dut.clk)
    dut.reg_addr.value = addr
    dut.reg_re.value   = 1
    await RisingEdge(dut.clk)
    dut.reg_re.value   = 0
    val = int(dut.reg_rdata.value)
    dut.reg_addr.value = 0
    return val


async def read_status(dut):
    """Return current STATUS register value (combinational; no clock pulse needed)."""
    dut.reg_addr.value = ADDR_STATUS
    await Timer(1, units="ns")   # let combinational settle
    val = int(dut.reg_rdata.value)
    dut.reg_addr.value = 0
    return val


async def wait_tx_idle(dut, timeout=500):
    """Poll STATUS[tx_busy] until clear, raise on timeout."""
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        dut.reg_addr.value = ADDR_STATUS
        await Timer(1, units="ns")
        busy = int(dut.reg_rdata.value) & STATUS_TX_BUSY
        if not busy:
            dut.reg_addr.value = 0
            return
    raise TimeoutError(f"tx_busy did not clear within {timeout} cycles")


async def capture_tx_byte(dut):
    """Capture one UART frame from dut.uart_tx; return the data byte.

    Waits for the falling edge of uart_tx (start bit), then samples each
    data bit at the mid-point of its bit period.
    """
    # Wait for start bit (falling edge)
    await FallingEdge(dut.uart_tx)

    # Skip to middle of start bit to confirm it is really low
    await ClockCycles(dut.clk, BIT_CYCLES // 2)
    assert int(dut.uart_tx.value) == 0, "Expected start bit (logic 0)"

    # Sample 8 data bits (LSB first) at mid-bit
    received = 0
    for i in range(8):
        await ClockCycles(dut.clk, BIT_CYCLES)
        bit = int(dut.uart_tx.value)
        received |= (bit << i)

    # Check stop bit
    await ClockCycles(dut.clk, BIT_CYCLES)
    assert int(dut.uart_tx.value) == 1, "Expected stop bit (logic 1)"

    return received


async def send_rx_byte(dut, byte):
    """Drive dut.uart_rx with a complete UART frame for the given byte.

    The RX module has a 2-cycle input synchroniser, so we drive the pin
    one full bit-period before the nominal start-bit edge — the synchroniser
    latency means the first sample is aligned correctly.
    """
    # Ensure line is idle
    dut.uart_rx.value = 1
    await ClockCycles(dut.clk, 2)

    # Start bit
    dut.uart_rx.value = 0
    await ClockCycles(dut.clk, BIT_CYCLES)

    # 8 data bits (LSB first)
    for i in range(8):
        dut.uart_rx.value = (byte >> i) & 1
        await ClockCycles(dut.clk, BIT_CYCLES)

    # Stop bit
    dut.uart_rx.value = 1
    await ClockCycles(dut.clk, BIT_CYCLES)

    # Extra cycles for FSM to reach READY state
    await ClockCycles(dut.clk, 4)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_state(dut):
    """After reset: STATUS=0, CTRL=0, BAUD_DIV matches expected value."""
    await start_clock(dut)
    await reset_dut(dut)

    status = await reg_read(dut, ADDR_STATUS)
    assert status == 0, f"STATUS after reset: expected 0, got 0x{status:08X}"

    ctrl = await reg_read(dut, ADDR_CTRL)
    assert ctrl == 0, f"CTRL after reset: expected 0, got 0x{ctrl:08X}"

    baud_div = await reg_read(dut, ADDR_BAUD_DIV)
    expected_div = (CLK_HZ - 1) // BIT_RATE
    assert baud_div == expected_div, \
        f"BAUD_DIV: expected {expected_div}, got {baud_div}"

    dut._log.info("PASS: reset state — STATUS=0, CTRL=0, BAUD_DIV=%d", baud_div)


@cocotb.test()
async def test_baud_div(dut):
    """BAUD_DIV register returns the compile-time baud divisor."""
    await start_clock(dut)
    await reset_dut(dut)

    baud_div = await reg_read(dut, ADDR_BAUD_DIV)
    expected  = CYCLES_PER_BIT   # = (CLK_HZ-1)//BIT_RATE
    assert baud_div == expected, \
        f"BAUD_DIV: expected {expected}, got {baud_div}"
    dut._log.info("PASS: BAUD_DIV = %d", baud_div)


@cocotb.test()
async def test_tx_basic(dut):
    """Write 0x55 to DATA; verify UART framing on uart_tx pin."""
    await start_clock(dut)
    await reset_dut(dut)

    tx_byte = 0x55

    # Launch capture coroutine before triggering TX
    capture = cocotb.start_soon(capture_tx_byte(dut))

    # Write DATA register — this triggers the TX
    await reg_write(dut, ADDR_DATA, tx_byte)

    # Wait for capture to finish
    received = await capture

    assert received == tx_byte, \
        f"TX framing: wrote 0x{tx_byte:02X}, captured 0x{received:02X}"
    dut._log.info("PASS: TX basic — 0x%02X framed correctly", tx_byte)


@cocotb.test()
async def test_tx_second_byte(dut):
    """Write 0xA3 to DATA; verify correct framing (different bit pattern)."""
    await start_clock(dut)
    await reset_dut(dut)

    tx_byte = 0xA3

    capture = cocotb.start_soon(capture_tx_byte(dut))
    await reg_write(dut, ADDR_DATA, tx_byte)
    received = await capture

    assert received == tx_byte, \
        f"TX framing: wrote 0x{tx_byte:02X}, captured 0x{received:02X}"
    dut._log.info("PASS: TX second byte — 0x%02X framed correctly", tx_byte)


@cocotb.test()
async def test_tx_busy_flag(dut):
    """STATUS[tx_busy] is 1 during transmission and 0 afterwards."""
    await start_clock(dut)
    await reset_dut(dut)

    # Confirm not busy before write
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_TX_BUSY) == 0, \
        f"tx_busy should be 0 before write, got STATUS=0x{status:08X}"

    # Trigger TX
    await reg_write(dut, ADDR_DATA, 0xAA)

    # One clock after write, tx_busy should be high
    await RisingEdge(dut.clk)
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_TX_BUSY) != 0, \
        f"tx_busy should be 1 right after write, got STATUS=0x{status:08X}"

    # Wait for TX to complete and verify busy clears
    await wait_tx_idle(dut)
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_TX_BUSY) == 0, \
        f"tx_busy should clear after TX done, got STATUS=0x{status:08X}"

    dut._log.info("PASS: tx_busy flag transitions correctly")


@cocotb.test()
async def test_rx_basic(dut):
    """Drive uart_rx with byte 0x37; verify DATA register returns 0x37."""
    await start_clock(dut)
    await reset_dut(dut)

    rx_byte = 0x37

    # Send frame on uart_rx
    await send_rx_byte(dut, rx_byte)

    # rx_valid should be set
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_RX_VALID) != 0, \
        f"rx_valid not set after receiving byte; STATUS=0x{status:08X}"

    # Read DATA
    data = await reg_read(dut, ADDR_DATA)
    assert (data & 0xFF) == rx_byte, \
        f"DATA after RX: expected 0x{rx_byte:02X}, got 0x{data & 0xFF:02X}"

    dut._log.info("PASS: RX basic — received 0x%02X correctly", rx_byte)


@cocotb.test()
async def test_rx_valid_clears_on_read(dut):
    """rx_valid (STATUS[1]) clears after reading DATA register."""
    await start_clock(dut)
    await reset_dut(dut)

    # Send a byte
    await send_rx_byte(dut, 0xC0)

    # Confirm rx_valid is set
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_RX_VALID) != 0, "rx_valid should be set before read"

    # Read DATA — this should pulse uart_rx_read and clear rx_valid
    _ = await reg_read(dut, ADDR_DATA)

    # Allow one cycle for rx FSM to transition back to IDLE
    await ClockCycles(dut.clk, 2)

    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_RX_VALID) == 0, \
        f"rx_valid should clear after DATA read; STATUS=0x{status:08X}"

    dut._log.info("PASS: rx_valid clears after DATA read")


@cocotb.test()
async def test_ctrl_rx_irq_enable(dut):
    """rx_irq output follows rx_valid gated by CTRL[rx_irq_en]."""
    await start_clock(dut)
    await reset_dut(dut)

    # IRQ should be 0 when disabled (reset default)
    await send_rx_byte(dut, 0x5A)
    await ClockCycles(dut.clk, 2)
    assert int(dut.rx_irq.value) == 0, "rx_irq should be 0 when CTRL[rx_irq_en]=0"

    # Enable rx_irq and verify it reflects rx_valid
    await reg_write(dut, ADDR_CTRL, CTRL_RX_IRQ_EN)
    await ClockCycles(dut.clk, 1)
    assert int(dut.rx_irq.value) == 1, \
        "rx_irq should be 1 when rx_valid=1 and CTRL[rx_irq_en]=1"

    # Clearing rx_valid by reading DATA should de-assert rx_irq
    _ = await reg_read(dut, ADDR_DATA)
    await ClockCycles(dut.clk, 2)
    assert int(dut.rx_irq.value) == 0, "rx_irq should de-assert after DATA read"

    dut._log.info("PASS: rx_irq gated by CTRL[rx_irq_en]")


@cocotb.test()
async def test_ctrl_tx_irq_enable(dut):
    """tx_irq output is high when TX idle and CTRL[tx_irq_en]=1."""
    await start_clock(dut)
    await reset_dut(dut)

    # Enable tx_irq
    await reg_write(dut, ADDR_CTRL, CTRL_TX_IRQ_EN)
    await ClockCycles(dut.clk, 1)

    # TX is idle → tx_irq should be 1
    assert int(dut.tx_irq.value) == 1, \
        "tx_irq should be 1 when TX idle and tx_irq_en=1"

    # Trigger TX — tx_irq should go low
    capture = cocotb.start_soon(capture_tx_byte(dut))
    await reg_write(dut, ADDR_DATA, 0xFF)
    await ClockCycles(dut.clk, 2)
    assert int(dut.tx_irq.value) == 0, \
        "tx_irq should be 0 while TX is busy"

    # Wait for TX to finish — tx_irq should return high.
    # capture_tx_byte exits at the middle of the stop bit; poll until
    # the TX FSM fully returns to IDLE before checking tx_irq.
    await capture
    await wait_tx_idle(dut)
    await ClockCycles(dut.clk, 1)
    assert int(dut.tx_irq.value) == 1, \
        "tx_irq should re-assert when TX completes"

    dut._log.info("PASS: tx_irq gated by CTRL[tx_irq_en]")


@cocotb.test()
async def test_loopback(dut):
    """Loopback test: TX frame is captured, re-sent on uart_rx, then verified.

    Validates the end-to-end path: register write → uart_tx serialiser →
    UART framing → uart_rx deserialiser → DATA register read.
    """
    await start_clock(dut)
    await reset_dut(dut)

    tx_byte = 0x6E

    # Step 1 — capture the UART frame transmitted on uart_tx
    capture = cocotb.start_soon(capture_tx_byte(dut))
    await reg_write(dut, ADDR_DATA, tx_byte)
    captured = await capture

    assert captured == tx_byte, \
        f"Loopback TX capture: wrote 0x{tx_byte:02X}, captured 0x{captured:02X}"

    # Step 2 — wait for TX FSM to fully return to IDLE
    await wait_tx_idle(dut)

    # Step 3 — feed the captured byte back in via uart_rx
    await send_rx_byte(dut, captured)

    # Step 4 — verify RX received correctly
    status = await reg_read(dut, ADDR_STATUS)
    assert (status & STATUS_RX_VALID) != 0, \
        f"rx_valid not set after loopback; STATUS=0x{status:08X}"

    data = await reg_read(dut, ADDR_DATA)
    assert (data & 0xFF) == tx_byte, \
        f"Loopback: wrote 0x{tx_byte:02X}, received 0x{data & 0xFF:02X}"

    dut._log.info("PASS: loopback — 0x%02X sent and received correctly", tx_byte)


@cocotb.test()
async def test_multiple_rx_bytes(dut):
    """Receive three consecutive bytes and verify DATA/STATUS each time."""
    await start_clock(dut)
    await reset_dut(dut)

    test_bytes = [0x11, 0xAB, 0xFF]

    for expected in test_bytes:
        await send_rx_byte(dut, expected)

        status = await reg_read(dut, ADDR_STATUS)
        assert (status & STATUS_RX_VALID) != 0, \
            f"rx_valid not set for byte 0x{expected:02X}"

        data = await reg_read(dut, ADDR_DATA)
        assert (data & 0xFF) == expected, \
            f"Expected 0x{expected:02X}, got 0x{data & 0xFF:02X}"

        # Clear rx_valid for next iteration
        await ClockCycles(dut.clk, 4)

    dut._log.info("PASS: multiple RX bytes all received correctly")
