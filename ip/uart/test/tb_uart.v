// SPDX-License-Identifier: MIT
//
// tb_uart.v — cocotb testbench top for uart_riscv_if
//
// Parameters are intentionally set for fast simulation:
//   CLK_HZ   = 10_000_000  (10 MHz)
//   BIT_RATE =  1_000_000  (1 Mbaud → 10 cycles/bit)
//
// The testbench is a plain Verilog wrapper; cocotb drives all signals.
// Verilator notes: --public is not needed; cocotb's Verilator flow handles
// signal access automatically.
//

`default_nettype none
`timescale 1ns/1ps

module tb_uart;

    // ── Simulation parameters ──────────────────────────────────────────────
    // 10 MHz clock → 100 ns period; 1 Mbaud → 10 clock-cycles per UART bit.
    parameter CLK_HZ   = 10_000_000;
    parameter BIT_RATE =  1_000_000;

    // ── DUT I/O ───────────────────────────────────────────────────────────
    reg         clk;
    reg         resetn;
    reg  [1:0]  reg_addr;
    reg  [31:0] reg_wdata;
    reg         reg_we;
    reg         reg_re;
    wire [31:0] reg_rdata;
    wire        uart_tx;
    reg         uart_rx;
    wire        tx_irq;
    wire        rx_irq;

    // ── DUT instantiation ─────────────────────────────────────────────────
    uart_riscv_if #(
        .CLK_HZ  (CLK_HZ),
        .BIT_RATE(BIT_RATE)
    ) dut (
        .clk      (clk),
        .resetn   (resetn),
        .reg_addr (reg_addr),
        .reg_wdata(reg_wdata),
        .reg_we   (reg_we),
        .reg_re   (reg_re),
        .reg_rdata(reg_rdata),
        .uart_tx  (uart_tx),
        .uart_rx  (uart_rx),
        .tx_irq   (tx_irq),
        .rx_irq   (rx_irq)
    );

    // ── Waveform dump (opt-in via -DDUMP_WAVES compile flag) ──────────────
`ifdef DUMP_WAVES
    initial begin
        $dumpfile("waves.vcd");
        $dumpvars(0, tb_uart);
    end
`endif

    // ── Initial conditions ────────────────────────────────────────────────
    initial begin
        clk       = 0;
        resetn    = 0;
        reg_addr  = 2'b00;
        reg_wdata = 32'h0;
        reg_we    = 1'b0;
        reg_re    = 1'b0;
        uart_rx   = 1'b1;   // idle-high
    end

endmodule
