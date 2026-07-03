#!/bin/bash

verilator --lint-only --timing -DSIM -Wall -Wno-DECLFILENAME -Wno-MULTITOP project.v latch_mem.v tinyQV/cpu/*.v tinyQV/peri/*/*.v
