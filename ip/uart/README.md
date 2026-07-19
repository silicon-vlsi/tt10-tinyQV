# UART IP — Single-Cycle RISC-V Interface

This directory contains the UART IP extracted from the
[tt10-tinyQV](https://github.com/silicon-vlsi/tt10-tinyQV) design, together
with a generic memory-mapped wrapper (`uart_riscv_if`) suitable for integrating
a UART into any single-cycle RISC-V core, and a complete cocotb-based
verification environment.

---

## File Layout

```
ip/uart/
├── README.md               ← This file
├── rtl/
│   ├── uart_tx.v           ← UART transmitter (Ben Marshall / Michael Bell, MIT)
│   ├── uart_rx.v           ← UART receiver    (Ben Marshall / Michael Bell, MIT)
│   └── uart_riscv_if.v     ← Memory-mapped wrapper for single-cycle RISC-V cores
└── test/
    ├── Makefile            ← cocotb runner — supports Icarus Verilog & Verilator
    ├── tb_uart.v           ← Verilog testbench top (instantiates uart_riscv_if)
    └── test_uart.py        ← cocotb test suite (11 test cases)
```

The original UART RTL files live in
`src/tinyQV/peri/uart/` and are **unchanged**; the copies in `ip/uart/rtl/`
are provided so this directory can be used as a self-contained IP block.

---

## Interface Signals (`uart_riscv_if`)

```verilog
module uart_riscv_if #(parameter
    CLK_HZ       = 50_000_000,  // System clock frequency (Hz)
    BIT_RATE     = 115_200,     // Baud rate (bps)
    PAYLOAD_BITS = 8,           // Data bits per frame
    STOP_BITS    = 1            // Stop bits per frame
) (
    input  wire         clk,        // System clock
    input  wire         resetn,     // Active-low synchronous reset

    // Memory-mapped register bus (see Register Map below)
    input  wire [1:0]   reg_addr,   // Word address (2 bits → 4 registers)
    input  wire [31:0]  reg_wdata,  // Write data
    input  wire         reg_we,     // Write-enable (1-cycle pulse)
    input  wire         reg_re,     // Read-enable  (1-cycle pulse)
    output reg  [31:0]  reg_rdata,  // Read data (combinational)

    // UART serial pins
    output wire         uart_tx,    // Serial transmit (idle = 1)
    input  wire         uart_rx,    // Serial receive  (idle = 1)

    // Level-based interrupts (gated by CTRL register)
    output wire         tx_irq,     // TX serialiser idle    (if CTRL[tx_irq_en])
    output wire         rx_irq      // RX byte available     (if CTRL[rx_irq_en])
);
```

### Bus Interface Notes

| Signal      | Direction | Width | Description |
|-------------|-----------|-------|-------------|
| `reg_addr`  | in        | 2     | Word address. Connect `cpu_addr[3:2]` for a byte-addressed bus. |
| `reg_wdata` | in        | 32    | Write data. Only `[7:0]` is used for DATA writes. |
| `reg_we`    | in        | 1     | 1-cycle write-enable pulse. |
| `reg_re`    | in        | 1     | 1-cycle read-enable pulse. Pulses `uart_rx_read` internally. |
| `reg_rdata` | out       | 32    | Combinational read data (valid whenever `reg_addr` is stable). |

The interface is intentionally minimal. For single-cycle cores with a
simple request/valid handshake, assert `reg_we`/`reg_re` for exactly
**one clock cycle**. The response is always available in the **same cycle**
(no wait states).

---

## Register Map

Base address is chosen by the system integrator; the UART occupies 4 × 4-byte
words (16 bytes of address space).

| Word Addr | Byte Offset | Name       | Access | Description |
|-----------|-------------|------------|--------|-------------|
| `2'b00`   | `+0x00`     | `DATA`     | R/W    | **Write**: queues TX byte `[7:0]`. Ignored if `tx_busy = 1`. **Read**: returns last received byte `[7:0]`; reading clears `rx_valid`. |
| `2'b01`   | `+0x04`     | `STATUS`   | RO     | `[0]` = `tx_busy` — serialiser is active. `[1]` = `rx_valid` — received byte waiting. |
| `2'b10`   | `+0x08`     | `CTRL`     | R/W    | `[0]` = `rx_irq_en`. `[1]` = `tx_irq_en`. Reset value = `0x00`. |
| `2'b11`   | `+0x0C`     | `BAUD_DIV` | RO     | `[15:0]` = `(CLK_HZ − 1) / BIT_RATE`. Read-only; set at synthesis time via parameters. |

### Transmit Flow

```
1.  Poll STATUS until tx_busy == 0  (or use tx_irq if CTRL[tx_irq_en]=1)
2.  Write desired byte to DATA
3.  TX serialises autonomously; uart_tx goes low (start bit) one clock later
```

### Receive Flow

```
1.  Poll STATUS until rx_valid == 1  (or use rx_irq if CTRL[rx_irq_en]=1)
2.  Read DATA  — this automatically clears rx_valid (re-arms the receiver)
3.  The received byte is in bits [7:0] of the read value
```

### Interrupt Notes

Both interrupt outputs are **level-based**:

- `rx_irq = rx_valid && CTRL[rx_irq_en]` — stays asserted until DATA is read.
- `tx_irq = !tx_busy && CTRL[tx_irq_en]` — stays asserted while TX is idle.

Typical TX interrupt flow: enable `tx_irq_en`, write DATA, disable `tx_irq_en`
in the ISR after the byte is sent.

---

## Parameter Guide

| Parameter     | Default        | Description |
|---------------|----------------|-------------|
| `CLK_HZ`      | `50_000_000`   | System clock frequency in Hz. Must match actual clock. |
| `BIT_RATE`    | `115_200`      | Desired baud rate. Common values: 9600, 115200, 1000000. |
| `PAYLOAD_BITS`| `8`            | Data bits per frame (almost always 8). |
| `STOP_BITS`   | `1`            | Stop bits (1 or 2). |

The baud divisor is computed as:

```
CYCLES_PER_BIT = (CLK_HZ - 1) / BIT_RATE   (integer division)
```

Actual baud rate = `CLK_HZ / (CYCLES_PER_BIT + 1)`. Verify with `BAUD_DIV`
register at runtime.

---

## Running the cocotb Tests

### Prerequisites

```bash
# Python packages
pip install cocotb>=1.9

# Icarus Verilog (for SIM=icarus, the default)
sudo apt-get install iverilog

# Verilator (for SIM=verilator; version >= 4.106 recommended)
sudo apt-get install verilator
```

### Run with Icarus Verilog (default)

```bash
cd ip/uart/test
make
```

Expected output (all 11 tests pass):

```
PASS: reset state — STATUS=0, CTRL=0, BAUD_DIV=9
PASS: BAUD_DIV = 9
PASS: TX basic — 0x55 framed correctly
PASS: TX second byte — 0xA3 framed correctly
PASS: tx_busy flag transitions correctly
PASS: RX basic — received 0x37 correctly
PASS: rx_valid clears after DATA read
PASS: rx_irq gated by CTRL[rx_irq_en]
PASS: tx_irq gated by CTRL[tx_irq_en]
PASS: loopback — 0x6E sent and received correctly
PASS: multiple RX bytes all received correctly
 ─────────── 11 passed ───────────
```

### Run with Verilator

```bash
cd ip/uart/test
make SIM=verilator
```

### Enable Waveform Dump (VCD)

```bash
# Icarus Verilog — produces waves.vcd in the run directory
make WAVES=1

# Verilator — produces dump.vcd (set COCOTB_ENABLE_WAVES=1)
COCOTB_ENABLE_WAVES=1 make SIM=verilator
```

Open with GTKWave:

```bash
gtkwave waves.vcd &
```

### Clean Build Artefacts

```bash
make clean
```

---

## Integration Guide for a Single-Cycle RISC-V Core

### Step 1 — Copy the IP files

Copy `ip/uart/rtl/` into your project (or add them as sources):

```
your_project/
  src/
    uart_tx.v
    uart_rx.v
    uart_riscv_if.v
```

### Step 2 — Instantiate `uart_riscv_if`

Adjust `CLK_HZ` and `BIT_RATE` to match your design:

```verilog
wire [31:0] uart_rdata;
wire        uart_tx_pin;
wire        uart_rx_irq, uart_tx_irq;

uart_riscv_if #(
    .CLK_HZ  (50_000_000),   // 50 MHz system clock
    .BIT_RATE(115_200)        // 115200 baud
) u_uart (
    .clk      (clk),
    .resetn   (resetn),

    // Connect to your data-bus decode logic:
    // For a byte-addressed bus, uart_base = 32'h1000_0000
    // reg_addr = cpu_daddr[3:2]
    .reg_addr (cpu_daddr[3:2]),
    .reg_wdata(cpu_wdata),
    .reg_we   (uart_sel && cpu_we),
    .reg_re   (uart_sel && cpu_re),
    .reg_rdata(uart_rdata),

    .uart_tx  (uart_tx_pin),
    .uart_rx  (uart_rx_pin),
    .tx_irq   (uart_tx_irq),
    .rx_irq   (uart_rx_irq)
);

// Address decode (example: UART at 0x1000_0000 – 0x1000_000F)
wire uart_sel = (cpu_daddr[31:4] == 28'h100000);

// Mux read data
assign cpu_rdata = uart_sel ? uart_rdata : mem_rdata;
```

### Step 3 — Software Usage (C pseudo-code)

```c
#define UART_BASE    0x10000000u
#define UART_DATA    (*(volatile uint32_t *)(UART_BASE + 0x00))
#define UART_STATUS  (*(volatile uint32_t *)(UART_BASE + 0x04))
#define UART_CTRL    (*(volatile uint32_t *)(UART_BASE + 0x08))
#define UART_BAUD    (*(volatile uint32_t *)(UART_BASE + 0x0C))

#define TX_BUSY      (1u << 0)
#define RX_VALID     (1u << 1)
#define RX_IRQ_EN    (1u << 0)
#define TX_IRQ_EN    (1u << 1)

void uart_putc(char c) {
    while (UART_STATUS & TX_BUSY);  // wait until idle
    UART_DATA = (uint8_t)c;
}

int uart_getc(void) {
    if (!(UART_STATUS & RX_VALID)) return -1;  // nothing available
    return UART_DATA & 0xFF;                    // clears rx_valid
}
```

### Step 4 — Interrupt Handling (optional)

```c
// Enable RX interrupt
UART_CTRL = RX_IRQ_EN;

// In ISR (triggered when rx_irq goes high):
void uart_rx_isr(void) {
    char c = (char)(UART_DATA & 0xFF);  // read and clear rx_valid
    // process c ...
}
```

---

## Original UART Attribution

The low-level `uart_tx.v` and `uart_rx.v` modules are based on the
[UART implementation by Ben Marshall](https://github.com/ben-marshall/uart)
(MIT License), with modifications by Michael Bell for the
[tt10-tinyQV](https://github.com/silicon-vlsi/tt10-tinyQV) project.
