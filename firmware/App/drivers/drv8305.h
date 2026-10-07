#ifndef DRV8305_H
#define DRV8305_H

#include "main.h"

void SPI_MODE_MT(SPI_HandleTypeDef *hspi);
void SPI_MODE_DRV(SPI_HandleTypeDef *hspi);
void DUTY_CYCLE(HRTIM_HandleTypeDef *hrtim, uint32_t timind, float duty);
float MT_READ(SPI_HandleTypeDef *hspi);
uint16_t DRV_Read(SPI_HandleTypeDef *hspi, uint8_t address);
HAL_StatusTypeDef DRV_Write(SPI_HandleTypeDef *hspi, uint8_t address, uint16_t data);

#endif