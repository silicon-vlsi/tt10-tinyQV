# ip/uart/test/Makefile — cocotb runner for uart_riscv_if
#
# Usage:
#   make                      # run all tests with Icarus Verilog (default)
#   make SIM=icarus           # explicit Icarus Verilog
#   make SIM=verilator        # run with Verilator
#   make WAVES=1              # enable VCD waveform dump
#   make clean                # remove build artefacts
#
# Prerequisites:
#   pip install cocotb        # cocotb >= 1.9
#   apt  install iverilog     # for SIM=icarus (default)
#   apt  install verilator    # for SIM=verilator (>= 4.106)
#
# Expected output (all tests pass):
#   PASS: reset state — STATUS=0, CTRL=0, BAUD_DIV=9
#   PASS: BAUD_DIV = 9
#   PASS: TX basic — 0x55 framed correctly
#   PASS: TX second byte — 0xA3 framed correctly
#   PASS: tx_busy flag transitions correctly
#   PASS: RX basic — received 0x37 correctly
#   PASS: rx_valid clears after DATA read
#   PASS: rx_irq gated by CTRL[rx_irq_en]
#   PASS: tx_irq gated by CTRL[tx_irq_en]
#   PASS: loopback — 0x6E sent and received correctly
#   PASS: multiple RX bytes all received correctly

SIM          ?= icarus
WAVES        ?= 0
TOPLEVEL_LANG = verilog

RTL_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../rtl)
TEST_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# RTL sources
VERILOG_SOURCES  = $(RTL_DIR)/uart_tx.v
VERILOG_SOURCES += $(RTL_DIR)/uart_rx.v
VERILOG_SOURCES += $(RTL_DIR)/uart_riscv_if.v

# Testbench top
VERILOG_SOURCES += $(TEST_DIR)/tb_uart.v

TOPLEVEL = tb_uart
MODULE   = test_uart

SIM_BUILD = sim_build/uart

# ── Icarus-specific ────────────────────────────────────────────────────────
ifeq ($(SIM),icarus)
ifeq ($(WAVES),1)
COMPILE_ARGS += -DDUMP_WAVES
endif
endif

# ── Verilator-specific ─────────────────────────────────────────────────────
ifeq ($(SIM),verilator)
# --trace enables VCD dumps when WAVES=1 (cocotb sets COCOTB_ENABLE_WAVES)
EXTRA_ARGS += --trace
# Suppress common warnings from the UART RTL that are benign in simulation
EXTRA_ARGS += -Wno-UNOPTFLAT
EXTRA_ARGS += -Wno-TIMESCALEMOD
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
