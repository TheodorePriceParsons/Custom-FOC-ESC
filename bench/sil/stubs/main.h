/*
 * main.h (SIL stand-in)
 * Replaces Core/Inc/main.h when the firmware is compiled for the PC. Only the few
 * register and HAL names that foc.c and bench.c touch are provided; everything else
 * the firmware uses goes through App/drivers, which sil/stubs/drivers_sil.c replaces.
 */
#ifndef SIL_MAIN_H_
#define SIL_MAIN_H_

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* DWT cycle counter (ISR timing). It never advances on the PC: ISR load is a target-only metric. */
typedef struct { volatile uint32_t DEMCR; } SilCoreDebug_t;
typedef struct { volatile uint32_t CTRL, CYCCNT; } SilDWT_t;
extern SilCoreDebug_t sil_coredebug;
extern SilDWT_t       sil_dwt;
#define CoreDebug                   (&sil_coredebug)
#define DWT                         (&sil_dwt)
#define CoreDebug_DEMCR_TRCENA_Msk  (1u << 24)
#define DWT_CTRL_CYCCNTENA_Msk      (1u << 0)

/* scope timing pin */
typedef struct { volatile uint32_t BSRR, BRR; } SilGPIO_t;
extern SilGPIO_t sil_gpioa;
#define TIMING_OUT_GPIO_Port        (&sil_gpioa)
#define TIMING_OUT_Pin              (1u << 9)

/* HAL bits */
typedef struct { int unused; } SPI_HandleTypeDef;
typedef enum { BUTTON_USER = 0 } Button_TypeDef;
#define LPUART1_IRQn                91
uint32_t HAL_GetTick(void);
static inline void HAL_NVIC_SetPriority(int irq, uint32_t pre, uint32_t sub) { (void)irq; (void)pre; (void)sub; }
static inline void HAL_NVIC_EnableIRQ(int irq) { (void)irq; }

#ifdef __cplusplus
}
#include "sil_uart.hpp"     /* LPUART1 registers, only bench.c needs them */
#endif

#endif
