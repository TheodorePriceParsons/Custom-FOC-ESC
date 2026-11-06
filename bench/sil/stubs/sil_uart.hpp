/*
 * sil_uart.hpp
 * LPUART1 for bench.c on the PC. bench.c polls ISR, reads RDR and writes TDR exactly as on
 * the STM32; here those "registers" are small C++ objects that move bytes to and from the
 * host-side queues in sil.c. This is why bench.c is compiled as C++ (sil/bench_sil.cpp):
 * plain C has no way to run code on a register write.
 */
#ifndef SIL_UART_HPP_
#define SIL_UART_HPP_

#include <stdint.h>

#define USART_ISR_FE                (1u << 1)
#define USART_ISR_NE                (1u << 2)
#define USART_ISR_ORE               (1u << 3)
#define USART_ISR_RXNE_RXFNE        (1u << 5)
#define USART_ISR_TXE_TXFNF         (1u << 7)
#define USART_ICR_FECF              (1u << 1)
#define USART_ICR_NECF              (1u << 2)
#define USART_ICR_ORECF             (1u << 3)
#define USART_CR1_RXNEIE_RXFNEIE    (1u << 5)

extern "C" {
int     sil_rx_pending(void);
uint8_t sil_rx_pop(void);
void    sil_tx_push(uint8_t b);
}

struct SilIsrReg {   /* TX always ready; RXNE while host bytes are queued */
    operator uint32_t() const { return USART_ISR_TXE_TXFNF | (sil_rx_pending() ? USART_ISR_RXNE_RXFNE : 0u); }
};
struct SilRdrReg {   /* reading RDR pops one byte */
    operator uint32_t() const { return sil_rx_pop(); }
};
struct SilTdrReg {   /* writing TDR sends one byte */
    SilTdrReg &operator=(uint32_t v) { sil_tx_push((uint8_t)v); return *this; }
};
struct SilUart_t {
    SilIsrReg ISR;
    SilRdrReg RDR;
    SilTdrReg TDR;
    uint32_t  ICR, CR1;
};
extern SilUart_t sil_lpuart1;
#define LPUART1 (&sil_lpuart1)

#endif
