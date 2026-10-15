/*
 * spi_bus.c
 * Same modes as your SPI_MODE_MT / SPI_MODE_DRV. HAL_SPI_Init alone is enough
 * once the handle is initialised (no DeInit, which would also reset the pins).
 */
#include "spi_bus.h"

static volatile bool locked;

static void mode_mt(void)
{
    SPI_BUS->Init.CLKPolarity = SPI_POLARITY_HIGH;
    SPI_BUS->Init.CLKPhase    = SPI_PHASE_1EDGE;
    HAL_SPI_Init(SPI_BUS);
}

static void mode_drv(void)
{
    SPI_BUS->Init.CLKPolarity = SPI_POLARITY_LOW;
    SPI_BUS->Init.CLKPhase    = SPI_PHASE_2EDGE;
    HAL_SPI_Init(SPI_BUS);
}

void spi_bus_init(void)
{
    mode_mt();
    locked = false;
}

void spi_bus_lock_for_drv(void)
{
    locked = true;
    __DSB();
    mode_drv();
}

void spi_bus_release(void)
{
    mode_mt();
    __DSB();
    locked = false;
}

bool spi_bus_locked(void) { return locked; }
