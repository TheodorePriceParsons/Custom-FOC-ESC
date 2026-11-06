/*
 * bench_sil.cpp
 * Compiles the unmodified firmware/App/bench/bench.c for the PC. It is built as C++ only so
 * the LPUART1 registers in stubs/sil_uart.hpp can move bytes; the code itself is the C file.
 */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "main.h"

extern "C" {
#include "bench.c"
}

SilUart_t sil_lpuart1;
