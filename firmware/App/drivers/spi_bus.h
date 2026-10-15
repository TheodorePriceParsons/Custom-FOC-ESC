/*
 * spi_bus.h
 * SPI3 is shared by the MT6701 and DRV8305, which need different SPI modes.
 * The FOC interrupt reads the encoder; the main loop talks to the DRV.
 * The lock stops the interrupt from using the bus while main has it.
 */
#ifndef DRIVERS_SPI_BUS_H_
#define DRIVERS_SPI_BUS_H_

#include "main.h"
#include <stdbool.h>

extern SPI_HandleTypeDef hspi3;
#define SPI_BUS (&hspi3)

void spi_bus_init(void);           // leaves the bus in MT mode
void spi_bus_lock_for_drv(void);   // main loop only: lock + switch to DRV mode
void spi_bus_release(void);        // switch back to MT mode + unlock
bool spi_bus_locked(void);

#endif
