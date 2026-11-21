/*
 * dac_out.c
 * DAC1 channel 1 is set up in CubeMX with no trigger and the output buffer on, so a write to
 * DHR12R1 reaches the pin within a few APB clocks: one register store per ISR tick.
 */
#include "dac_out.h"
#include "main.h"

extern DAC_HandleTypeDef hdac1;

void dac_out_start(void)
{
    HAL_DAC_SetValue(&hdac1, DAC_CHANNEL_1, DAC_ALIGN_12B_R, 2048u);
    HAL_DAC_Start(&hdac1, DAC_CHANNEL_1);
}

void dac_out_write(uint16_t code)
{
    DAC1->DHR12R1 = code;
}
