/*
 * sense.h
 * ADC1 regular conversions, HRTIM-triggered, DMA circular into sense_dma[].
 */
#ifndef DRIVERS_SENSE_H_
#define DRIVERS_SENSE_H_

#include <stdint.h>

extern volatile uint16_t sense_dma[4];

void  sense_init(void);    // ADC calibration, before sense_start
void  sense_start(void);   // start DMA; conversions then follow HRTIM triggers
float sense_vbus(void);    // volts (VBUS_NOMINAL until USE_VBUS_SENSE = 1)

#endif
