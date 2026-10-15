
/*
 * mt6701.c
 * Your MT_READ decode, split to return the raw count.
 */
#include "mt6701.h"
#include "spi_bus.h"

uint16_t mt6701_read_raw(void)
{
    uint16_t rx = 0, tx = 0;

    HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_RESET);
    HAL_StatusTypeDef status =
        HAL_SPI_TransmitReceive(SPI_BUS, (uint8_t *)&tx, (uint8_t *)&rx, 1, 2);
    HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_SET);

    if (status != HAL_OK) return MT6701_ERR;

    return (uint16_t)(((rx & 0x7FFFu) >> 1) & 0x3FFFu);   // drop dummy bit, keep 14-bit angle
}

float mt6701_read_rad(void)
{
    uint16_t raw = mt6701_read_raw();
    if (raw == MT6701_ERR) return -1.0f;
    return (float)raw * (6.28318530718f / 16384.0f);
}
