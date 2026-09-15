#include "drv8305.h"
#include <math.h>

void SPI_MODE_MT(SPI_HandleTypeDef *hspi) {
  HAL_SPI_DeInit(hspi);
  hspi->Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi->Init.CLKPhase = SPI_PHASE_1EDGE;
  HAL_SPI_Init(hspi);
}

void SPI_MODE_DRV(SPI_HandleTypeDef *hspi) {
  HAL_SPI_DeInit(hspi);
  hspi->Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi->Init.CLKPhase = SPI_PHASE_2EDGE;
  HAL_SPI_Init(hspi);
}

#define PERIOD (float)0xFFF7
void DUTY_CYCLE(HRTIM_HandleTypeDef *hrtim, uint32_t timind, float duty) {
  if (duty < 0.001f) {
    duty = 0.001f;
  } else if (duty > 1.0f) {
    duty = 1.0f;
  }
  __HAL_HRTIM_SetCompare(hrtim, timind, HRTIM_COMPAREUNIT_1,
                         (uint32_t)(PERIOD * (1.0f - duty)) / 2);
  __HAL_HRTIM_SetCompare(hrtim, timind, HRTIM_COMPAREUNIT_2,
                         (uint32_t)(PERIOD * (1.0f + duty)) / 2);
}

// In radians
float MT_READ(SPI_HandleTypeDef *hspi) {
  uint8_t tx_buf[2] = {0x00, 0x00};
  uint8_t rx_buf[2];
  uint16_t angle_raw;
  float angle_degrees;

  HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(hspi, tx_buf, rx_buf, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_SET);

  if (status != HAL_OK) {
    return -1.0f;
  }

  uint16_t received_16bit_word = ((uint16_t)rx_buf[1] << 8) | rx_buf[0];
  uint16_t data_shifted_for_dummy = received_16bit_word & 0x7FFF;
  angle_raw = (data_shifted_for_dummy >> 1) & 0x3FFF;
  angle_degrees = ((float)angle_raw) / 16384.0f * 2 * M_PI;

  return angle_degrees;
}

uint16_t DRV_Read(SPI_HandleTypeDef *hspi, uint8_t address) {
  uint16_t command_word;
  uint16_t received_word;
  uint16_t data_value;

  command_word = (1U << 15) | ((address & 0x0F) << 11);

  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(hspi, (uint8_t *)&command_word,
                              (uint8_t *)&received_word, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_SET);

  if (status != HAL_OK) {
    return 0xFFFF;
  }

  data_value = received_word & 0x07FF;

  return data_value;
}

HAL_StatusTypeDef DRV_Write(SPI_HandleTypeDef *hspi, uint8_t address,
                            uint16_t data) {
  uint16_t command_word;
  uint16_t tx_data;

  data &= 0x07FF;
  command_word = ((address & 0x0F) << 11) | data;
  tx_data = command_word;

  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Transmit(hspi, (uint8_t *)&tx_data, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_SET);

  return status;
}
