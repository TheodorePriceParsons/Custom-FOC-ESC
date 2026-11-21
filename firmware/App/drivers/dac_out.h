/*
 * dac_out.h
 * Scope output on PA4 (DAC1_OUT1, Nucleo CN7 pin 32 / A2). Lets you put internal
 * signals (phase current, iq, electrical angle) on a scope channel without a current probe.
 */
#ifndef DRIVERS_DAC_OUT_H_
#define DRIVERS_DAC_OUT_H_

#include <stdint.h>

void dac_out_start(void);              /* after MX_DAC1_Init; output starts at mid-scale */
void dac_out_write(uint16_t code);     /* 12-bit, right aligned. Safe from the ISR */

#endif
