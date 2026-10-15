/*
 * sense.c
 */
#include "sense.h"
#include "main.h"
#include "board.h"

extern ADC_HandleTypeDef hadc1;

volatile uint16_t sense_dma[4];

void sense_init(void)
{
    HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED);
}

void sense_start(void)
{
    HAL_ADC_Start_DMA(&hadc1, (uint32_t *)sense_dma, 4);
}

float sense_vbus(void)
{
#if USE_VBUS_SENSE
    return (float)sense_dma[ADC_RANK_VBUS] * VOLTS_PER_COUNT;
#else
    return VBUS_NOMINAL;
#endif
}
