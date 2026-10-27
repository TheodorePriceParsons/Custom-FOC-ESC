/*
 * bench.h
 * Test-bench interface for the automated benchmark suite (see bench/ in the repo root).
 *
 *  - Line-based ASCII commands over LPUART1 (ST-LINK virtual COM port, 115200 8N1)
 *  - RAM capture of 4 channels from the control ISR, with a step applied at an exact sample
 *  - Binary dump of the capture to the host
 *  - Host watchdog: every command kicks it; the ISR trips FLT_WATCHDOG if it expires while running
 *  - E-stop on the Nucleo user button (B1)
 *
 * Protocol: bench/PROTOCOL.md
 */
#ifndef BENCH_BENCH_H_
#define BENCH_BENCH_H_

#define BENCH_PROTO_VERSION  1u
#define BENCH_CAP_N          2048u     /* samples per capture */
#define BENCH_CAP_CH         4u        /* float channels per sample (32 KB total) */
#define BENCH_CAP_PRE        200u      /* sample index at which the step is applied */
#define BENCH_UART_IRQ_PRIO  5u        /* below HRTIM (0): never delays the control loop */

void bench_init(void);   /* after BSP_COM_Init(COM1, ...) */
void bench_poll(void);   /* main loop: parse and execute host commands */
void bench_isr(void);    /* end of foc_isr(): capture + step injection */

#endif /* BENCH_BENCH_H_ */
